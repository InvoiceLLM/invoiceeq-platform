from typing import Any
from uuid import UUID, uuid4
from datetime import datetime, date
from sqlmodel import SQLModel, Field, Column
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from config import settings

# Cross-platform JSON type: JSONB on PostgreSQL, JSON/Text fallback on SQLite
JSON_VARIANT = sa.JSON().with_variant(JSONB, "postgresql")

class Tenant(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(max_length=255)
    domain: str = Field(max_length=255, unique=True, index=True)
    clerk_org_id: str | None = Field(default=None, max_length=255, unique=True, index=True)
    billing_plan: str = Field(default="free", max_length=50)
    free_invoices_remaining: int = Field(default_factory=lambda: settings.DEFAULT_FREE_INVOICES_LIMIT)
    # Gap 118: when the free allowance above next refills. routers/invoices.py
    # only ever decrements free_invoices_remaining, so without this the "50
    # invoices/month" free tier was really 50 invoices for the lifetime of the
    # account. NULL means "the cycle clock has not started yet" -- true for
    # every row predating the migration and for a tenant that has never been on
    # the free plan -- and is seeded, without granting a refill, the first time
    # services/billing_lifecycle.refresh_free_quota() sees the tenant.
    free_quota_reset_at: datetime | None = Field(default=None)
    payu_customer_id: str | None = Field(default=None, max_length=255)
    payu_subscription_id: str | None = Field(default=None, max_length=255)
    # Gap 71: end of the currently-paid-for billing cycle. PayU's classic API
    # has no subscription object, so this is the only record that a paid plan
    # was ever paid *for a period* rather than once. Extended by
    # services/billing_lifecycle.extend_paid_through() on every verified
    # payment; NULL means "never paid" (free tier) or a legacy pre-Gap-71 row,
    # neither of which may be lapsed -- see is_lapsed().
    paid_through: datetime | None = Field(default=None)
    # BE Gap 264: the user explicitly asked to stop renewing, recorded
    # separately from paid_through/billing_plan so the two questions ("when
    # does access end" and "did the tenant choose that or just go idle")
    # don't collapse into one signal. Does not itself change billing_plan or
    # paid_through -- access continues exactly as already designed until
    # paid_through, and services/billing_lifecycle.py's existing sweep still
    # owns the actual downgrade. NULL means no cancellation is pending.
    cancel_requested_at: datetime | None = Field(default=None)
    # Feature 16: Service Flow toggles
    receive_invoices_enabled: bool = Field(default=True)   # Inbound (AP) — on by default, preserves existing behaviour
    send_invoices_enabled: bool = Field(default=False)     # Outbound (AR) — opt-in, requires pro_combined plan
    outbound_sender_email: str | None = Field(default=None, max_length=255)  # Legacy Gap 125 Reply-To placeholder; Email Setup uses TenantEmailSender sets
    # Gap 184: programmatic API key for this tenant. The raw key is NEVER stored
    # -- only a PBKDF2-HMAC-SHA256 digest of it (`api_key_hash`) plus the
    # per-key random `api_key_salt` it was derived with, so a database dump
    # cannot be replayed as credentials. `api_key_prefix` is the leading,
    # deliberately non-secret slice of the raw key (`inv_live_` + 6 chars),
    # kept only so the UI can show *which* key is active without being able to
    # reconstruct it; the raw value exists in exactly one response, the one that
    # created or rotated it (same "shown once" rule as WebhookSubscription.secret).
    # NULL across all of these means "this tenant has never issued a key".
    api_key_hash: str | None = Field(default=None, max_length=255)
    api_key_salt: str | None = Field(default=None, max_length=64)
    api_key_prefix: str | None = Field(default=None, max_length=32, index=True)
    api_key_rotated_at: datetime | None = Field(default=None)
    # Last time the key successfully authenticated a request. Purely
    # observational (lets an Admin spot a key that is still in use before
    # rotating it, or one that has never been used at all).
    api_key_last_used_at: datetime | None = Field(default=None)
    # Feature 25 / Gap 335: how much of the invoice lifecycle this tenant's API
    # key is allowed to finish. Exactly two values:
    #   "readonly" -- the founder's "Strict Review": the integration may upload
    #                 and read; a human finalizes in the web UI.
    #   "actions"  -- the founder's "Full Automation": the key may additionally
    #                 approve/reject/verify (audit resolve, inbound and
    #                 outbound), confirm-send, and mark-paid.
    # The default is "readonly" and that is a FAIL-CLOSED choice, not a
    # stylistic one: every tenant that already exists when migration
    # d8e9f0a1b2c3 runs, and every tenant created later without an explicit
    # decision, must NOT silently acquire the ability to have a machine approve
    # its invoices. Widening is an explicit act.
    #
    # This is on Tenant rather than on a key row because services/api_keys.py is
    # one-key-per-tenant by design (see its module docstring) -- there is no
    # per-key table to hang it off, and a tenant therefore cannot hold a
    # readonly key and an actions key at the same time.
    #
    # Note this is NOT a pipeline auto-approval threshold, and NOT Feature 13's
    # "Tenant Autopilot" (scheduled Drive sync) -- see
    # docs/feature_25_plug_and_play_workflows.md for that naming collision.
    api_key_scope: str = Field(default="readonly", max_length=20, nullable=False)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Invoice(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(index=True)
    batch_id: UUID | None = Field(default=None, index=True)
    file_path: str = Field(max_length=1024)
    file_hash: str | None = Field(default=None, index=True, max_length=64)

    vendor_name: str | None = Field(default=None)
    subtotal: float | None = Field(default=None)
    grand_total: float | None = Field(default=None)
    invoice_number: str | None = Field(default=None)
    invoice_date: date | None = Field(default=None)
    due_date: date | None = Field(default=None)
    tax_amount: float | None = Field(default=None)
    po_number: str | None = Field(default=None)
    # Gap 195: nullable self-reference, set only on status=DUPLICATE rows
    # (see routers/invoices.py::_ingest_single_file's duplicate branch) --
    # gives webhook subscribers and any future UI a structured pointer to
    # the original invoice instead of the prose inside sa_alerts.
    duplicate_of_invoice_id: UUID | None = Field(default=None, foreign_key="invoice.id", nullable=True, index=True)
    status: str = Field(default="PROCESSING")
    sa_alerts: list = Field(default=[], sa_column=Column(JSON_VARIANT))
    tags: list = Field(default=[], sa_column=Column(JSON_VARIANT))
    items: list = Field(default=[], sa_column=Column(JSON_VARIANT))
    coordinates: list = Field(default=[], sa_column=Column(JSON_VARIANT))
    field_confidence: dict = Field(default={}, sa_column=Column(JSON_VARIANT))
    # Gap 178: Doc Intelligence prebuilt-invoice structured fields (JSON), used
    # as the PDF-side reference when checking extraction completeness. Not the
    # PDF binary — that stays in blob storage via file_path.
    source_document_json: dict | None = Field(default=None, sa_column=Column(JSON_VARIANT, nullable=True))
    currency: str | None = Field(default=None)
    discount_percent: float | None = Field(default=None)
    discount_amount: float | None = Field(default=None)
    taxes: list = Field(default=[], sa_column=Column(JSON_VARIANT))
    discounts: list = Field(default=[], sa_column=Column(JSON_VARIANT))
    deductions: list = Field(default=[], sa_column=Column(JSON_VARIANT))
    tax_ids: list = Field(default=[], sa_column=Column(JSON_VARIANT))
    payment_instructions: list = Field(default=[], sa_column=Column(JSON_VARIANT))
    references: list = Field(default=[], sa_column=Column(JSON_VARIANT))
    addresses: list = Field(default=[], sa_column=Column(JSON_VARIANT))
    compliance_metadata: list = Field(default=[], sa_column=Column(JSON_VARIANT))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = Field(default=None)
    # Gap 192: soft delete. NULL = live; set to utcnow() hides the row from
    # product queries while preserving the Invoice + AuditLog compliance trail.
    deleted_at: datetime | None = Field(default=None, index=True)

    # FE Gaps 81/84: stuck-invoice reconciliation bookkeeping. `last_enqueued_at`
    # is when a queue message was last *sent* for this invoice (upload time, or
    # the last reconciliation re-enqueue) -- staleness has to be measured from
    # that, not from created_at, or a re-enqueued invoice would look permanently
    # overdue and be re-enqueued on every sweep. `processing_attempts` bounds how
    # many times the sweep will retry before giving up and marking it FAILED,
    # so a genuinely unprocessable file can't be requeued forever.
    last_enqueued_at: datetime | None = Field(default=None)
    processing_attempts: int = Field(default=0)

    # Feature 2.1 (Outbound Invoice Ingestion, Task 2.1.1): flow_direction
    # distinguishes a vendor's invoice addressed to this tenant (INBOUND,
    # every existing row's default -- unaffected) from this tenant's own
    # invoice addressed to their customer (OUTBOUND). customer_name is the AR
    # mirror of vendor_name, populated only for OUTBOUND rows. customer_id is
    # reserved for future customer-record linking -- unused in v1, no
    # customer-facing portal exists yet.
    flow_direction: str = Field(default="INBOUND", max_length=20)
    customer_name: str | None = Field(default=None)
    customer_id: UUID | None = Field(default=None)
    # Feature 8.1 (Outbound Dashboard) Task 8.1.1, bundled in here since
    # Feature 2.1's own confirm-send endpoint needs sent_at immediately --
    # set when the outbound confirm-send/mark-paid endpoints actually fire
    # those transitions, never estimated.
    sent_at: datetime | None = Field(default=None)
    paid_at: datetime | None = Field(default=None)
    # Gap 126: when the `outbound_invoice.overdue` webhook was fired for this
    # invoice by the scheduled sweep (services/outbound_overdue.py). NULL means
    # "never fired". This is bookkeeping for the sweep only -- overdue itself
    # stays a virtual, read-time computation (Feature 7.1/8.1: SENT past
    # due_date); no OVERDUE value is ever written to `status`. Without this
    # column the daily sweep would re-fire the same event for the same invoice
    # every single day it stays unpaid.
    overdue_notified_at: datetime | None = Field(default=None)
    # Gap 125: email (or UI) submitter — process-complete staff notify target.
    # Never used to email end customers from the app.
    submitted_by_email: str | None = Field(default=None, max_length=255)

    # Feature 27 (G9 / E10): the classified document type and the verbatim
    # printed phrase the classifier decided from.
    #
    # On THIS table these are always an INVOICE-family value -- "INVOICE",
    # "PROFORMA_INVOICE", "CREDIT_NOTE", "DEBIT_NOTE" -- or NULL. A non-invoice
    # document is never an `Invoice` row (E10): it goes to `Document` below, and
    # `queue_worker/handlers.py` deletes the upload-time placeholder row in the
    # same transaction that writes it. So this column records an invoice's own
    # *sub-type*, which is real information (a proforma creates no receivable and
    # a credit note reverses one), not "which of ten kinds of paper is this".
    #
    # Both are nullable with a `None` default, deliberately: every row that
    # already exists stays valid with no backfill, and a flag-OFF run writes
    # NULL exactly as it writes nothing today (the classifier node is not in the
    # compiled graph at all when `ENABLE_GENERIC_EXTRACTION` is false). NULL here
    # means "never classified", never "not an invoice".
    doc_type: str | None = Field(default=None, max_length=32)
    doc_type_evidence: str | None = Field(default=None)

    # Feature 27 A6 / task R8: the classification attributes derived from the
    # document's own text by `services/doc_attributes.py` -- `direction`,
    # `invoice_subtype`, `correction_method`, `fiscal_markers`, `regional_ids`,
    # `cumulative`, each with its evidence.
    #
    # ONE JSON COLUMN, not six typed ones, and the reason is not convenience:
    # these attributes are a SET THAT GROWS (A8 adds `rule_era`; the research
    # names several more as v2 candidates), every one of them is optional, and
    # none is ever queried on. A typed column per attribute would be a migration
    # per amendment for fields nothing filters by.
    #
    # KEYS ARE OMITTED WHEN UNDETERMINED rather than stored as null. `{}` and NULL
    # both mean "nothing established"; a key present with a null value would be a
    # third state nobody wants. NULL on the column itself means never classified.
    doc_attributes: dict | None = Field(
        default=None, sa_column=Column(JSON_VARIANT, nullable=True)
    )

    # FE Gap 29: dashboard/list filters are always tenant-scoped plus one of
    # status/date/vendor, so composite indexes led by tenant_id (rather than
    # single-column ones) are what the query planner actually uses here.
    __table_args__ = (
        sa.Index("ix_invoice_tenant_status", "tenant_id", "status"),
        sa.Index("ix_invoice_tenant_invoice_date", "tenant_id", "invoice_date"),
        sa.Index("ix_invoice_tenant_vendor_name", "tenant_id", "vendor_name"),
        sa.Index("ix_invoice_tenant_flow_direction", "tenant_id", "flow_direction"),
    )


class Document(SQLModel, table=True):
    __tablename__ = "documents"
    # Feature 27 (G9), decision E10 / amendment A3: a non-INVOICE-family
    # commercial document -- a delivery note, a purchase order, a quotation, a
    # contract, a GRN -- extracted through the same graph as an invoice and
    # stored HERE, never in `invoice`.
    #
    # Why a separate table rather than a `doc_type` filter on `invoice`: the
    # alternative was measured, not estimated. Keeping these rows in `invoice`
    # means adding a doc_type predicate to **39 tenant-scoped Invoice query sites
    # across 19 files**, plus a new obligation on every Invoice query anyone
    # writes from now on, forever -- and one of those 39 cannot be filtered
    # deterministically at all: the chat NL->SQL route generates free-form
    # `SELECT ... FROM invoice`, and `execute_generated_sql` is a validator, not
    # a rewriter (the execution-time rewriter was deleted at Gap 253 and is the
    # origin of CONVENTIONS hard rule 3). "How much did we spend last month?"
    # would count delivery notes every time the model omitted a filter it was
    # merely *asked* to add.
    #
    # The same decision was already taken and shipped for chat attachments
    # (Feature 26 D2 -- see `ChatAttachment`'s docstring below), so option (a)
    # would have made the same purchase order a `chat_attachments` row when
    # attached in chat and an `Invoice` row when uploaded through ingestion:
    # two contradictory answers to one question inside one codebase. And the
    # failure mode is not hypothetical -- Gap 329 is exactly this, on exactly
    # this table: `flow_direction` was added to `Invoice`, `/dashboard/metrics`
    # was never filtered on it, and OUTBOUND rows blended into every inbound
    # aggregate until the founder spotted it on screen. That was ONE new
    # row-kind and ONE missed file. This feature adds nine kinds.
    #
    # The columns are `GenericDocumentSchema`'s spine (Feature 27 E8) plus
    # `Invoice`'s *operational* columns -- Gap 192's soft delete and FE Gap
    # 81/84's re-enqueue bookkeeping -- so the existing sweeps and audit-trail
    # patterns transfer unchanged. Nothing money-specific beyond what a PO or a
    # contract genuinely prints: no `compliance_metadata`, no `tax_ids`, no
    # `round_off`, no `coordinates` (Doc Intelligence labels every box with an
    # *invoice* field name, so an overlay drawn over a purchase order would
    # mislabel it -- A1; an empty overlay is honest, a mislabelled one is not).
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(index=True)
    batch_id: UUID | None = Field(default=None, index=True)
    file_path: str = Field(max_length=1024)
    file_hash: str | None = Field(default=None, index=True, max_length=64)

    # The classified type (one of the nine non-INVOICE values in `DOC_TYPES`),
    # the verbatim printed phrase it was decided from, and the classifier's
    # confidence. The evidence is persisted so a misclassification is
    # *reviewable* after the fact rather than only being a wrong answer, and the
    # confidence because §2A/N2's 0.6 threshold is an uncalibrated placeholder
    # and has nothing to calibrate against without the distribution.
    doc_type: str | None = Field(default=None, max_length=32, index=True)
    doc_type_evidence: str | None = Field(default=None)
    doc_type_confidence: float | None = Field(default=None)

    # Feature 27 A6 / task R8: the classification attributes derived from the
    # document's own text by `services/doc_attributes.py` -- `direction`,
    # `invoice_subtype`, `correction_method`, `fiscal_markers`, `regional_ids`,
    # `cumulative`, each with its evidence.
    #
    # ONE JSON COLUMN, not six typed ones, and the reason is not convenience:
    # these attributes are a SET THAT GROWS (A8 adds `rule_era`; the research
    # names several more as v2 candidates), every one of them is optional, and
    # none is ever queried on. A typed column per attribute would be a migration
    # per amendment for fields nothing filters by.
    #
    # KEYS ARE OMITTED WHEN UNDETERMINED rather than stored as null. `{}` and NULL
    # both mean "nothing established"; a key present with a null value would be a
    # third state nobody wants. NULL on the column itself means never classified.
    doc_attributes: dict | None = Field(
        default=None, sa_column=Column(JSON_VARIANT, nullable=True)
    )

    # Roles, not document-type words. `party_name` is whoever ISSUED the
    # document; `counterparty_name` is whoever it is addressed to. Defined once,
    # here and in `GenericDocumentSchema`, because nine types with nine
    # word-pairs for the same two roles (vendor/buyer, supplier/consignee,
    # quoting party/prospect) is how one column acquires a different meaning per
    # row.
    party_name: str | None = Field(default=None)
    counterparty_name: str | None = Field(default=None)
    doc_number: str | None = Field(default=None)
    po_number: str | None = Field(default=None)
    reference_numbers: list = Field(default=[], sa_column=Column(JSON_VARIANT))
    doc_date: date | None = Field(default=None)
    valid_until: date | None = Field(default=None)

    # Money is OPTIONAL on this table and that is the point of the feature. A
    # delivery note prints quantities and no prices *by design* (so the
    # recipient's warehouse staff cannot see pricing) and a framework contract
    # frequently has no grand total at all. NULL means "the document did not
    # state it" and must never be read as, or coerced to, zero -- Gap 283 is the
    # truthiness bug where a real 0.00 was read as missing, and this is the same
    # distinction from the other side.
    currency: str | None = Field(default=None, max_length=8)
    subtotal: float | None = Field(default=None)
    tax_amount: float | None = Field(default=None)
    discount_amount: float | None = Field(default=None)
    grand_total: float | None = Field(default=None)
    items: list = Field(default=[], sa_column=Column(JSON_VARIANT))
    taxes: list = Field(default=[], sa_column=Column(JSON_VARIANT))
    payment_terms: str | None = Field(default=None)
    delivery_terms: str | None = Field(default=None)
    incoterms: str | None = Field(default=None, max_length=32)
    notes: str | None = Field(default=None)

    # "EXTRACTED" | "EXTRACT_FAILED" -- the same two-value vocabulary the
    # REFERENCE direction profile uses (`agents/extraction_agent.py`), and the
    # same one the `GENERIC` extraction profile emits, so the profile and the
    # table agree by construction rather than through a mapping table someone
    # has to maintain. Deliberately NOT the invoice vocabulary: a delivery note
    # has no audit lifecycle. It is never approved, sent or paid, so
    # COMPLETED/AUDIT_REQUIRED/PAID would be three states it can never reach and
    # one (AUDIT_REQUIRED) that would put it into a review queue it does not
    # belong in.
    status: str = Field(default="EXTRACTED", max_length=32)
    sa_alerts: list = Field(default=[], sa_column=Column(JSON_VARIANT))
    # Gap 178's raw Doc Intelligence snapshot, kept for the same diagnostic
    # reason it is kept on `Invoice` and safe for the same one: it is already
    # excluded from every LLM-visible projection (`agents/query_tools.py`,
    # `agents/sage_prompts.py`), so a misfit DI read of a non-invoice cannot
    # reach an answer.
    source_document_json: dict | None = Field(default=None, sa_column=Column(JSON_VARIANT, nullable=True))

    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = Field(default=None)
    # Gap 192's soft delete, mirrored: NULL = live.
    deleted_at: datetime | None = Field(default=None, index=True)
    # FE Gaps 81/84's stuck-row reconciliation bookkeeping, mirrored so the
    # existing sweep pattern transfers if this table ever needs one.
    last_enqueued_at: datetime | None = Field(default=None)
    processing_attempts: int = Field(default=0)
    # Gap 125's process-complete notify target, mirrored.
    submitted_by_email: str | None = Field(default=None, max_length=255)

    # Same reasoning as `Invoice.__table_args__` (FE Gap 29): every product
    # query on this table is tenant-scoped plus one more predicate, so the
    # composite index led by tenant_id is what a planner can actually use.
    __table_args__ = (
        sa.Index("ix_documents_tenant_doc_type", "tenant_id", "doc_type"),
        sa.Index("ix_documents_tenant_created_at", "tenant_id", "created_at"),
    )


class TenantConnection(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(index=True)
    provider: str  # 'google_drive' (Gap 334 removed 'salesforce')
    encrypted_access_token: str
    encrypted_refresh_token: str | None = Field(default=None)
    token_expiry: datetime
    status: str = Field(default="active")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    # DEAD COLUMN, deliberately retained (Gap 334, 2026-08-28). This existed
    # only for Salesforce, whose REST API base is per-org (unlike Google
    # Drive's fixed www.googleapis.com), so it had to be stored per-connection.
    # Nothing writes or reads it now. It is NOT dropped because its migration
    # (a7b8c9d0e1f2) sits mid-chain -- removing either the column or the
    # migration would break `alembic upgrade` for any database that already
    # ran it. Harmless nullable column; leave it alone.
    instance_url: str | None = Field(default=None)

class ChatSession(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(index=True)
    title: str = Field(max_length=255)
    created_at: datetime = Field(default_factory=datetime.utcnow)

class ChatMessage(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    session_id: UUID = Field(index=True)
    role: str = Field(max_length=50)  # 'user' or 'assistant'
    content: str
    generated_sql: str | None = Field(default=None)
    citations: list = Field(default=[], sa_column=Column(JSON_VARIANT))
    # Feature 18 (Gap 231): which invoices actually fed this reply, captured at
    # answer time. Before this column, only the RAG route left any row identity
    # behind (via `citations[].invoice_id`); the SQL route set `citations = []`
    # and returned nothing but `generated_sql` plus a markdown table string --
    # so for an aggregate answer like "total spend across 40 invoices" there was
    # literally nothing to build a "which invoice was wrong?" picker from, which
    # is exactly what the wrong-data triage flow needs.
    #
    # Best-effort by construction (see agents/query_agent.py::_harvest_invoice_ids):
    # an empty list means "we could not determine the row set", never "no rows
    # were involved". The triage API treats empty as "ask the user which invoice"
    # rather than asserting a claim it can't back.
    result_invoice_ids: list = Field(default=[], sa_column=Column(JSON_VARIANT))
    # Feature 26 task H16 / amendment B12 (Gap 386): the attached-document answer
    # contract, persisted.
    #
    # `agents/query_agent.py` computes `attachment_confirmation`,
    # `attachment_comparison`, `suggested_actions`, `evidence`,
    # `needs_confirmation` and `attachment_clarification` -- and before this column
    # every one of them was dropped twice over: `MessageResponse` declared none of
    # them, so FastAPI stripped them at serialisation, and this row had nowhere to
    # put them, so a session reload had nothing to restore. The FE renderers
    # (FE Gaps 376/380/383) were wired to a contract the API did not emit.
    #
    # ONE column rather than six, and rather than a side table:
    #   * They are one object -- the turn's answer contract. Six nullable columns
    #     would be six migrations as the contract grows (B10 already adds three
    #     more: `line_items`, `unmatched`, `reconciliation`).
    #   * Persisted, not transient, for the three reasons B12 states: the reload
    #     path (P2.6.6) must restore the confirmation card; the async worker
    #     computes the answer in a DIFFERENT PROCESS from the request, so there is
    #     no response object to hang a transient field on; and the D4 confirmation
    #     gate is a two-turn interaction where turn 2 must know what turn 1 offered.
    #   * A side table would fork the ownership check, which is the Gap 341 shape
    #     E-6 already refused for `chat_attachments` itself.
    #
    # NULL means "not an attachment turn" -- the overwhelming majority of rows, and
    # every row written before this migration. It never means "an attachment turn
    # that produced nothing": the contract rule in P2.8 makes an answer with no
    # evidence and no comparison a bug, so an attachment turn always writes a dict.
    # Bounded by the caps that already exist: <=3 suggested actions, Tier-2 <=20 /
    # Tier-3 <=10 candidates, DEFAULT_SEARCH_LIMIT=6 evidence spans.
    attachment_payload: dict | None = Field(
        default=None, sa_column=Column(JSON_VARIANT, nullable=True)
    )
    # Gap 280: Queue-based Async Chat Architecture
    # Lifecycle status: 'queued' | 'processing' | 'completed' | 'failed'
    status: str = Field(default="completed", max_length=32)
    job_id: str | None = Field(default=None, index=True, max_length=64)
    error_message: str | None = Field(default=None, max_length=1000)
    created_at: datetime = Field(default_factory=datetime.utcnow)

class ChatAttachment(SQLModel, table=True):
    __tablename__ = "chat_attachments"
    # Feature 26 (Gap 366): a reference document (purchase order or quotation)
    # attached to a chat session so the user can ask "does this bill agree with
    # what we agreed?".
    #
    # This is deliberately NOT an `Invoice` row (Feature 26, decision D2). A
    # quotation is not a payable. Writing one into `invoice` would silently
    # corrupt spend aggregates, /dashboard/insights, the AUDIT_REQUIRED count,
    # billing quota and the RAG index -- five separate consumers that all read
    # `invoice` as "money we owe or are owed". It is also not session-scratch:
    # the FE reload/reattach path and the async chat worker (a different OS
    # process from the request that uploaded the file) both need to read it
    # back, and neither can read a request-scoped dict.
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(index=True)
    session_id: UUID = Field(foreign_key="chatsession.id", index=True)
    filename: str = Field(max_length=512)
    blob_path: str = Field(max_length=1024)
    # "PURCHASE_ORDER" | "QUOTATION" | "OTHER" -- what the extractor decided the
    # document is. One profile with a discriminator rather than two parallel
    # schemas (D1): a PO and a quotation carry the same field spine and differ
    # only in what the header calls itself.
    doc_type: str = Field(default="OTHER", max_length=32)
    # Persisted so D3's 10 MB cap is auditable after the fact, not just a
    # transient check inside the upload handler.
    file_size_bytes: int = Field(default=0)
    # "PENDING" | "EXTRACTED" | "EXTRACT_FAILED"
    extraction_status: str = Field(default="PENDING", max_length=32)
    extracted_json: dict | None = Field(default=None, sa_column=Column(JSON_VARIANT, nullable=True))
    # Denormalised out of extracted_json purely so the Tier 1/Tier 2 match query
    # is a plain indexed SQL predicate instead of a JSON dig in Python.
    doc_number: str | None = Field(default=None, max_length=255)
    party_name: str | None = Field(default=None, max_length=512)
    doc_date: date | None = Field(default=None)
    currency: str | None = Field(default=None, max_length=8)
    grand_total: float | None = Field(default=None)
    # What find_candidate_invoices() proposed, and what the user actually
    # confirmed. These are kept separate on purpose: the confirmation gate (D4)
    # turns on `confirmed_invoice_ids` being non-empty, and a proposal must
    # never be able to satisfy it. Empty confirmed list + non-empty candidate
    # list == "we found these, the user has not agreed yet".
    candidate_invoice_ids: list = Field(default=[], sa_column=Column(JSON_VARIANT))
    confirmed_invoice_ids: list = Field(default=[], sa_column=Column(JSON_VARIANT))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    # Feature 26 Part 2 (E-6, task H4): the document's own text is embedded into
    # the sibling Chroma collection `chat_docs_{tenant_id}` so an open-ended
    # question ("what are the payment terms?") has something to read -- the ~15
    # denormalised fields above cannot answer one.
    #
    # These three are the *observable* half of that. Indexing is best-effort and
    # never fails an upload (the Part 1 comparison path needs no chunks at all),
    # so "did it work?" has to be answerable from the row rather than only from a
    # log line: `chunk_count == 0` with `indexed_at is None` on an EXTRACTED row
    # means the embed step ran and did not succeed, and is inspectable with a
    # single query instead of a log search.
    chunk_count: int = Field(default=0)
    indexed_at: datetime | None = Field(default=None)
    # E-7's TTL. Written at upload time as `created_at + CHAT_ATTACHMENT_TTL_DAYS`
    # so a row's lifetime is fixed when the user attaches it and does not move if
    # the config knob is retuned later. Null means no expiry, which is what every
    # row written before this column existed reads as -- the sweeper (H8) must
    # therefore treat null as "keep", not as "expired at the epoch".
    expires_at: datetime | None = Field(default=None)


class ChatFeedback(SQLModel, table=True):
    __tablename__ = "chat_feedback"
    # Gap 54: signal-only per-answer thumbs up/down, tied to that turn's
    # generated_sql/citations via message_id. One vote per message -- voting
    # again overwrites rather than accumulating, so `message_id` is unique.
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(index=True)
    session_id: UUID = Field(index=True)
    message_id: UUID = Field(index=True, unique=True)
    vote: str = Field(max_length=10)  # "up" or "down"
    # Feature 18 (Gap 232): a thumbs-down is no longer signal-only -- it is the
    # entry point to the chat-correction triage flow, and the three reasons below
    # route to three structurally different destinations:
    #   wrong_data          -> auto-diff against the stored DB value; may end up
    #                          redirecting into the *extraction* flow instead if
    #                          the stored data (not the reply) is what's wrong
    #   wrong_interpretation-> a TenantChatRule about the agent's own reasoning
    #   bad_tone            -> TenantChatSettings, not a rule at all
    # NULL on every pre-Feature-18 row and on any thumbs-up (a positive vote has
    # no reason to give), which is why it stays nullable rather than defaulted.
    reason: str | None = Field(default=None, max_length=32)
    # Optional free text. Deliberately secondary context only -- never the
    # primary input to rule generation, so a blank note can't produce a rule and
    # a prose note can't quietly become one.
    note: str | None = Field(default=None, max_length=2000)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class User(SQLModel, table=True):
    __tablename__ = "users"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID | None = Field(default=None, foreign_key="tenant.id", nullable=True)
    email: str = Field(max_length=255, unique=True, index=True)
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    role: str = Field(max_length=50)
    clerk_user_id: str = Field(max_length=255, unique=True, index=True)
    # Feature 1.1 (Granular RBAC, Task 1.1.1): per-area permissions, least
    # privilege by default. These are our own data, deliberately NOT sourced
    # from the Clerk JWT -- an Admin grants them via the Admin console and the
    # effect is immediate on the next request without a re-login.
    # A user with all three False sees Dashboard + Chat + Help only. Admin
    # implies all three (resolved in dependencies.get_tenant_context, not stored
    # redundantly here). Gap 337 retired the name "Viewer" for that state — the
    # permission shape it described is unchanged; see RoleMapper.NO_ROLE.
    can_train: bool = Field(default=False, nullable=False)
    can_audit: bool = Field(default=False, nullable=False)
    can_load: bool = Field(default=False, nullable=False)
    # Gap 405: granular per-user visibility for the Send Invoices feature,
    # layered on top of (not replacing) Tenant.send_invoices_enabled's
    # tenant-wide plan/email prerequisite gate (feature_16_settings.md) --
    # both must be true for a given user to see/use outbound sending.
    can_send_invoices: bool = Field(default=False, nullable=False)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_login: datetime | None = Field(default=None)

class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_logs"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(index=True)
    invoice_id: UUID = Field(index=True)
    actor_user_id: UUID = Field(foreign_key="users.id")
    actor_role: str = Field(max_length=50)
    action: str = Field(max_length=255)
    details: dict | None = Field(default=None, sa_column=Column(JSON_VARIANT))
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ExtractionTemplate(SQLModel, table=True):
    __tablename__ = "extraction_templates"
    # Two scopes share this table (feature_10_trainer.md):
    #   - vendor_name IS NULL  -> the tenant's single "Global" template (scope #1)
    #   - vendor_name set       -> a per-vendor template (scope #2 / #3)
    # Feature 7.1 (Outbound Auditor) Task 7.1.1 adds flow_direction so an
    # outbound Global rule (vendor_name IS NULL, flow_direction="OUTBOUND")
    # can coexist with the tenant's existing inbound Global rule without
    # colliding on the old tenant-only partial unique index -- both
    # constraints below now include flow_direction for that reason.
    __table_args__ = (
        sa.UniqueConstraint("tenant_id", "vendor_name", "flow_direction", name="uq_extraction_templates_tenant_vendor"),
        sa.Index(
            "uq_extraction_templates_tenant_global",
            "tenant_id",
            "flow_direction",
            unique=True,
            postgresql_where=sa.text("vendor_name IS NULL"),
            sqlite_where=sa.text("vendor_name IS NULL"),
        ),
    )
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(index=True)
    vendor_name: str | None = Field(default=None, max_length=255)
    flow_direction: str = Field(default="INBOUND", max_length=20)
    rules: dict = Field(default={}, sa_column=Column(JSON_VARIANT))
    version: int = Field(default=1)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ExtractionTemplateVersion(SQLModel, table=True):
    """Append-only history of every committed/rolled-back ExtractionTemplate change.

    Lets the Trainer's Rule History drawer show what changed and revert it
    (feature_10_trainer.md Task 10.10). One row is written on each commit and each
    rollback, capturing the rules value at that version plus who/when.
    """
    __tablename__ = "extraction_template_versions"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    template_id: UUID = Field(index=True, foreign_key="extraction_templates.id")
    tenant_id: UUID = Field(index=True)
    vendor_name: str | None = Field(default=None, max_length=255)
    version: int
    rules: dict = Field(default={}, sa_column=Column(JSON_VARIANT))
    changed_by: str | None = Field(default=None, max_length=255)
    changed_at: datetime = Field(default_factory=datetime.utcnow)


class TenantChatSettings(SQLModel, table=True):
    """Feature 18 (Gap 230): the tenant's Chat response style, in its own table.

    Replaces the storage location Gap 221 originally shipped: the style dict used
    to live inside the Global INBOUND `ExtractionTemplate` row's
    `rules["chat_style"]`. That was a reasonable place for it when the Global row
    was the natural home for tenant-wide Trainer state -- but Feature 18 removes
    Global-scope rule *creation* from the Trainer, so the Global row is no longer
    something a user ever opens or edits, and hanging live chat configuration off
    a row nobody visits (and which is otherwise about *extraction* rules, not
    chat behaviour) is exactly the kind of coupling this redesign exists to undo.

    The migration copies existing `rules["chat_style"]` dicts across and
    deliberately **leaves the source key in place** -- it is tenant data, and a
    non-destructive move means a rollback of this deploy loses nothing.

    Shaped after `TenantAutopilotConfig` (one row per tenant, enforced by a
    UNIQUE on `tenant_id`). It deliberately does NOT carry a `tenant.id` foreign
    key, matching the closer analogues for tenant-scoped config that this table
    actually sits alongside (`ExtractionTemplate`, `WebhookSubscription`,
    `ChatSession`), all of which use a plain indexed `tenant_id`.
    """
    __tablename__ = "tenant_chat_settings"
    __table_args__ = (
        sa.UniqueConstraint("tenant_id", name="uq_tenant_chat_settings_tenant"),
        sa.Index("idx_tenant_chat_settings_tenant", "tenant_id"),
    )
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(index=True)
    # 'brief' | 'balanced' | 'detailed'
    response_length: str = Field(default="balanced", max_length=20)
    # 'formal' | 'conversational' | 'technical'
    tone: str = Field(default="conversational", max_length=20)
    custom_instructions: str = Field(default="", max_length=2000)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class TenantChatRule(SQLModel, table=True):
    """Feature 18 (Gap 232): one committed chat-behaviour rule.

    Structurally separate from `ExtractionTemplate.rules["constraints"]`, and
    that separation is the point rather than an implementation detail: a chat
    rule is about how the *answering agent* should reason, filter or scope a
    question ("also search line-item descriptions", "invoices received means
    INBOUND"). It has nothing to teach the extraction pipeline, and letting the
    two share a table is how "the trainer taught chat something weird" and "the
    trainer taught extraction something weird" became the same, undiagnosable
    class of bug. Nothing in this table is ever read by the extraction agent, and
    nothing in `ExtractionTemplate` is ever read by `_chat_rules_block()`.

    `category` is one of a fixed vocabulary (see
    `services/chat_rules.py::CHAT_RULE_CATEGORIES`) -- structured pick, not free
    text. `pattern` is the specific thing the category applies to (e.g. the term
    that should have been included). `context_text` is optional secondary colour
    from the user, never the primary input.
    """
    __tablename__ = "tenant_chat_rules"
    __table_args__ = (
        sa.Index("idx_tenant_chat_rules_tenant_enabled", "tenant_id", "enabled"),
    )
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(index=True)
    category: str = Field(max_length=64)
    pattern: str = Field(default="", max_length=500)
    context_text: str = Field(default="", max_length=2000)
    created_by: str | None = Field(default=None, max_length=255)
    enabled: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class TenantEmailSender(SQLModel, table=True):
    """Authorized tenant-owned emails that may submit PDFs to the global app mailbox.

    One platform mailbox (EMAIL_APP_ADDRESS). Webhook resolves tenant_id and
    direction from From → this row (`email_set` inbound|outbound). `email` is
    globally unique so one sender maps to exactly one tenant/set.
    """
    __tablename__ = "tenant_email_senders"
    __table_args__ = (
        sa.UniqueConstraint("email", name="uq_tenant_email_senders_email"),
    )
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(index=True, foreign_key="tenant.id")
    email: str = Field(index=True, max_length=255)
    email_set: str = Field(default="inbound", max_length=20, index=True)  # inbound | outbound
    created_at: datetime = Field(default_factory=datetime.utcnow)


class DroppedInboundEmail(SQLModel, table=True):
    """Gap 124 item 6: one inbound-mail POST that never became an invoice.

    Every rejection path in `routers/email_ingestion.py::email_mailintegration_webhook`
    used to end at a `logger.warning` and a 200 with `status: dropped` — the mail
    vanished with no trace anyone outside the container logs could see, which is
    the worst possible failure mode for a channel whose whole job is unattended
    ingestion. Each of those paths now also writes a row here, and
    `routers/admin.py::list_dropped_emails` renders them in the Admin console.

    `tenant_id` is nullable on purpose: the mailbox is platform-wide, so the
    tenant is only known once the From address has been matched against
    `tenant_email_senders`. A request rejected *before* that point (bad shared
    secret, oversized body, unparseable multipart, unregistered sender) belongs
    to no tenant at all. `sender_domain` is stored alongside so those
    unattributed rows can still be surfaced to the one tenant they plausibly
    concern — see list_dropped_emails for that visibility rule.

    Deliberately not an `AuditLog`: that table requires a real
    `actor_user_id` FK (a human who acted on an invoice) and an `invoice_id`.
    A dropped mail has neither — there is no actor and, by definition, no
    invoice.
    """
    __tablename__ = "dropped_inbound_emails"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID | None = Field(default=None, index=True)
    # One of services.inbound_mail_security.DROP_REASONS.
    reason: str = Field(max_length=64, index=True)
    detail: str = Field(default="", max_length=1024)
    from_email: str | None = Field(default=None, max_length=320, index=True)
    to_email: str | None = Field(default=None, max_length=320)
    # Lowercased domain half of from_email, denormalised so the Admin list can
    # filter unattributed rows without re-parsing every address in SQL.
    sender_domain: str | None = Field(default=None, max_length=255, index=True)
    filename: str | None = Field(default=None, max_length=512)
    # Declared Content-Length of the POST, or the measured attachment byte
    # total when the request was rejected after parsing. NULL when neither is
    # known (e.g. a malformed request with no Content-Length header).
    content_length: int | None = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class WebhookSubscription(SQLModel, table=True):
    """Feature 15 (Task 15.1): a tenant-registered HTTP endpoint that receives
    real-time invoice status-change notifications instead of polling the API.

    `secret` is generated server-side on create and used to HMAC-sign every
    delivery (`X-Webhook-Signature`) -- never returned by the API after
    creation. `subscribed_events` is a subset of: invoice.completed,
    invoice.audit_required, invoice.paid, invoice.rejected,
    outbound_invoice.sent, outbound_invoice.overdue, outbound_invoice.paid.
    `consecutive_failures` drives Task 15.5's auto-disable-after-10 rule;
    reset to 0 on any successful delivery.

    Gap 194: failure tracking is now counted per *event type* in
    `event_failure_counts` ({event_type: consecutive failures}), not as one
    flat counter. `consecutive_failures` is kept as the denormalised
    max(event_failure_counts.values()) so the existing settings-page health
    warning and the public API shape are unchanged, but the auto-disable
    decision reads the per-event map -- see
    services/webhooks.record_delivery_result().
    """
    __tablename__ = "webhook_subscriptions"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(index=True)
    target_url: str = Field(max_length=2048)
    secret: str = Field(max_length=255)
    subscribed_events: list = Field(default=[], sa_column=Column(JSON_VARIANT))
    enabled: bool = Field(default=True)
    consecutive_failures: int = Field(default=0)
    event_failure_counts: dict = Field(default_factory=dict, sa_column=Column(JSON_VARIANT))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class WebhookDeliveryLog(SQLModel, table=True):
    """Gap 194: one row per completed delivery *attempt series* (the 3-attempt
    retry sequence in services/webhooks._deliver_with_retry counts as one row,
    with `attempts` recording how many HTTP calls it took).

    Before this table existed there was no way, from inside the product, to
    answer "did this event actually fire?" -- delivery errors are swallowed by
    design so an invoice operation never fails because a subscriber is down,
    which meant a completely broken fan-out looked identical to a clean one.

    `error` is a short diagnostic string (transport error text, or the HTTP
    status line for a non-2xx). Never contains the payload or the signing
    secret. Rows are tenant-scoped so the settings UI can read them under the
    normal tenant context.
    """
    __tablename__ = "webhook_delivery_logs"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(index=True)
    subscription_id: UUID = Field(index=True)
    event_type: str = Field(max_length=100)
    success: bool = Field(default=False)
    status_code: int | None = Field(default=None)
    attempts: int = Field(default=0)
    duration_ms: int | None = Field(default=None)
    error: str | None = Field(default=None, max_length=1000)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


# Feature 13: Tenant Autopilot — Ingestion & Scheduled Sync
# Stores per-tenant cloud folder sync configuration. One config row per tenant
# (enforced via UNIQUE on tenant_id). Google Drive is the only supported
# source type (Gap 334 removed Salesforce).
# trigger_mode is 'interval' (minutes) or 'cron' (cron expression).
# flow_direction mirrors Invoice.flow_direction: INBOUND (AP) or OUTBOUND (AR).
class TenantAutopilotConfig(SQLModel, table=True):
    __tablename__ = "tenant_autopilot_configs"
    __table_args__ = (
        sa.UniqueConstraint("tenant_id", name="uq_autopilot_config_tenant"),
        sa.Index("idx_autopilot_config_tenant", "tenant_id"),
    )
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(foreign_key="tenant.id")
    # 'gdrive' (Gap 334 removed 'salesforce')
    source_type: str = Field(max_length=50)
    # Google Drive Folder ID
    source_ref: str = Field(max_length=1024)
    # 'INBOUND' (AP — invoices coming in) | 'OUTBOUND' (AR — invoices going out)
    flow_direction: str = Field(default="INBOUND", max_length=10)
    # 'interval' (run every N minutes) | 'cron' (cron expression e.g. '0 * * * *')
    trigger_mode: str = Field(max_length=20)
    # cron expression string OR interval in minutes as a string (e.g. '60')
    trigger_value: str = Field(max_length=100)
    # array of email strings to notify on sync completion
    notify_emails: list = Field(default=[], sa_column=Column(JSON_VARIANT))
    # if True, sync notification emails include a manual audit approval link
    send_approval_links: bool = Field(default=False)
    # Gap 429: how long this tenant's sync-history NOISE rows are kept before
    # services/autopilot_sync.py::prune_autopilot_history() hard-deletes them.
    # Only SKIPPED_DUPLICATE / FAILED / NO_NEW_FILES rows are ever deleted --
    # SUCCESS rows are the dedup ledger (source_file_id and content_hash
    # lookups) and the incremental `since` watermark, so deleting one would
    # cause an already-ingested invoice to be re-imported. Bounded 7..365 in
    # routers/autopilot.py; defaulted rather than nullable so a tenant that
    # never touches the setting still gets pruned.
    history_retention_days: int = Field(default=90)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class TenantWorkflowConfig(SQLModel, table=True):
    """Feature 25 (Gap 336): the tenant's Plug & Play workflow choices.

    One row per tenant — the answers to "how do invoices reach us, how much may a
    machine finish, where do results go, how is chat reached". Written by the
    Settings workflow wizard (`PUT /api/v1/settings/workflow`, Admin only).

    Shaped after `TenantAutopilotConfig` deliberately: same one-row-per-tenant
    pattern, same `UNIQUE(tenant_id)` + index, same `tenant.id` foreign key, same
    `JSON_VARIANT` list columns (JSONB on Postgres, JSON on SQLite).

    ------------------------------------------------------------------------
    `audit_policy` IS NOT THE ENFORCEMENT PRIMITIVE. Read this before using it.
    ------------------------------------------------------------------------
    `Tenant.api_key_scope` (Gap 335) is the single source of truth for what an
    API key may actually do, and it is the only thing the auth layer reads.
    This column is the *user-facing wording* of that same decision:

        full_automation  <-> Tenant.api_key_scope == "actions"
        strict_review    <-> Tenant.api_key_scope == "readonly"

    `PUT /settings/workflow` writes BOTH in one transaction, and
    `GET /settings/workflow` **derives** `audit_policy` from
    `Tenant.api_key_scope` rather than reading this column back. So if the two
    ever disagree — an Admin editing the tenant column directly, a partially
    applied write — the API reports what is actually enforced, not what the
    wizard was last told. This column is kept because it is what the wizard
    wrote and is useful history; it is never an authorisation input.

    (Naming: "Full Automation"/"Strict Review" are the founder's two policies.
    The user-facing name for the first is still provisional — Feature 13 already
    ships a "Tenant Autopilot" meaning scheduled Drive sync. See
    docs/feature_25_plug_and_play_workflows.md.)

    `output_destinations` was a *stored intention* under Gap 336 — no delivery
    code read it. **Gap 339 changed that**: `services/workflow_outputs.py` reads
    this column when an invoice is approved and, if it contains `email_summary`,
    emails the tenant's registered addresses a summary with CSV + JSON
    attachments. So `webhook`, `dashboard_only` and `email_summary` are all
    accepted now. `drive_archive` (Gap 338) is still rejected at the endpoint
    with a 422 rather than stored and silently ignored, because a tenant
    believing its invoices are being filed to Drive when nothing sends them is
    worse than being told the feature is not available yet. `email_summary`
    additionally requires the tenant to hold at least one registered
    `TenantEmailSender` row, since that allowlist is where its recipients come
    from — see routers/settings.py::_validate_destinations.
    """
    __tablename__ = "tenant_workflow_configs"
    __table_args__ = (
        sa.UniqueConstraint("tenant_id", name="uq_workflow_config_tenant"),
        sa.Index("idx_workflow_config_tenant", "tenant_id"),
    )
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(foreign_key="tenant.id")
    # subset of 'email' | 'drive' | 'api' | 'manual'
    input_channels: list = Field(default=[], sa_column=Column(JSON_VARIANT))
    # 'full_automation' | 'strict_review' — mirrors Tenant.api_key_scope, see above
    audit_policy: str = Field(default="strict_review", max_length=32)
    # subset of 'webhook' | 'dashboard_only' | 'email_summary' (Gap 339);
    # 'drive_archive' (Gap 338) is not built and is rejected at the endpoint
    output_destinations: list = Field(default=[], sa_column=Column(JSON_VARIANT))
    # 'dashboard' | 'api' | 'widget'
    chat_access: str = Field(default="dashboard", max_length=20)
    # When the tenant first completed the wizard. Set once, on the first
    # successful PUT, and deliberately NOT reset by later edits — it answers
    # "has this tenant been through onboarding", not "when was this last saved"
    # (updated_at answers that).
    completed_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class SandboxTenant(SQLModel, table=True):
    """Feature 25 (Gap 340): the sandbox marker for a throwaway-but-real tenant.

    A sandbox key (`inv_test_...`) resolves to a **fresh, real `Tenant` row** --
    not a shared demo tenant. That is the founder's decision and it is what makes
    the sandbox worth having: a visitor uploads their own invoice and sees their
    own data, in a workspace that can later be *claimed* by a real signup rather
    than thrown away and rebuilt.

    ------------------------------------------------------------------------
    WHY THIS IS A SEPARATE TABLE AND NOT THREE COLUMNS ON `Tenant`
    ------------------------------------------------------------------------
    Two reasons, both load-bearing:

    1. **"Is this tenant a sandbox" must be answerable by row existence.** Every
       predicate in this feature -- the adoption blocker, the readonly pin, the
       expiry check, the global cap, the chat counter -- is "does a row exist,
       and is it unclaimed". A nullable column on `Tenant` would make the
       fail-open answer (NULL) look identical to "an ordinary tenant", which is
       the right default for a *column* and the wrong default for a *claim*.
    2. **The overwhelming majority of tenants are not sandboxes.** Five columns
       on `Tenant` for a state almost no row is in, on the single hottest table
       in the schema, is the wrong trade.

    `Tenant.domain` for a sandbox row is always the synthetic
    `sandbox-<tenant_id>.invalid` (services/sandbox.py::sandbox_domain) --
    `.invalid` is RFC 2606's reserved never-resolving TLD, the same device
    `routers/auth.py::_create_tenant_with_unique_domain()` already uses for a
    colliding org domain. That is what keeps a sandbox tenant permanently outside
    the domain-matched adoption path: no real company's email domain can equal
    it, and the tenant id inside it makes every value distinct (`Tenant.domain`
    is `unique=True, nullable=False`).
    """
    __tablename__ = "sandbox_tenants"
    # Index names are spelled here rather than via `index=True` on the fields so
    # they match migration b1c2d3e4f5a6 byte for byte -- same convention as
    # TenantWorkflowConfig above. SQLModel's implicit `ix_<table>_<col>` naming
    # would otherwise disagree with what Alembic actually created.
    __table_args__ = (
        sa.UniqueConstraint("tenant_id", name="uq_sandbox_tenant"),
        sa.Index("idx_sandbox_tenant_tenant_id", "tenant_id"),
        # `claimed_at IS NULL` is the unclaimed predicate, counted on every
        # issuance for the global cap; `expires_at` is the reaper's sweep key.
        sa.Index("idx_sandbox_tenant_claimed", "claimed_at"),
        sa.Index("idx_sandbox_tenant_expires", "expires_at"),
    )
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(foreign_key="tenant.id")
    # When the key stops verifying. Enforced live in
    # dependencies.resolve_api_key_context() *and* swept by
    # scripts/sweep_sandbox_tenants.py -- a flag nobody reads is not a TTL, so
    # expiry is both checked at auth time and actually reaped.
    expires_at: datetime
    # NULL means unclaimed, and it is the compare-and-set predicate the claim
    # transaction turns on (services/sandbox.py::claim_sandbox_tenant). Once set
    # this row is inert history: the tenant is an ordinary tenant from then on.
    claimed_at: datetime | None = Field(default=None)
    claimed_by_clerk_org_id: str | None = Field(default=None, max_length=255)
    # Gap 340 requirement 7: chat is the one thing a readonly sandbox key can do
    # that spends real Azure OpenAI money, and services/billing_quota.py's
    # free-tier charge covers ingestion only. A plain bounded counter, not a
    # second quota system -- issuance is already rate-limited and capped, so
    # this only has to stop one visitor's key running a bill up.
    chat_messages_used: int = Field(default=0)
    # Rate-limit forensics only. The IP that was issued this key, as resolved by
    # routers/support.py::_get_client_ip() (i.e. only values our own
    # infrastructure produced). Never used as an authorisation input.
    issued_from_ip: str | None = Field(default=None, max_length=64)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class WidgetToken(SQLModel, table=True):
    """Feature 25 (Gap 341): a chat-only token for a tenant's embedded widget.

    ------------------------------------------------------------------------
    THIS IS NOT AN API KEY, AND THE SEPARATION IS THE POINT
    ------------------------------------------------------------------------
    A widget token is pasted into the *customer's own website's client-side
    code*. It is visible in page source to every visitor, every crawler and
    every browser extension. It therefore cannot carry the trust level of an
    `inv_live_` key, and the containment is structural rather than a matter of
    checking a scope carefully:

    * it lives here, in its own table, and NOT in `Tenant.api_key_hash` /
      `api_key_salt` / `api_key_prefix` -- those are one-key-per-tenant by
      design (services/api_keys.py's docstring) and adding a third credential
      type to them would make "which credential is this" a question every
      reader of those columns has to ask;
    * it resolves to `dependencies.WidgetContext`, which has no `role`, no
      `key_scope` and none of the three permission booleans -- so
      `require_actions_scope` / `require_can_load_or_api_key` and every other
      gate in the codebase have structurally nothing to inspect on it. A scope
      bug elsewhere cannot widen a widget token, because there is no field for
      the bug to get wrong;
    * `get_widget_context()` is mounted on exactly one route, the widget chat
      send, and nowhere else.

    `allowed_origins` is an ADDITIONAL layer, not the control. It is checked
    against the request's `Origin`/`Referer`, which any non-browser client can
    set to whatever it likes -- so it raises the cost of casual reuse of a
    scraped token and nothing more. Nothing in this codebase or its docs should
    describe it as a guarantee.
    """
    __tablename__ = "widget_tokens"
    # Same naming reason as SandboxTenant above -- these are the names migration
    # b1c2d3e4f5a6 creates.
    __table_args__ = (
        # UNIQUE, unlike Tenant.api_key_prefix which is only indexed: this is the
        # sole lookup key across every tenant, so two rows sharing a prefix would
        # make resolution ambiguous rather than merely slow.
        sa.Index("idx_widget_token_prefix", "token_prefix", unique=True),
        sa.Index("idx_widget_token_tenant", "tenant_id"),
    )
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(foreign_key="tenant.id")
    # Same storage contract as Tenant.api_key_*: PBKDF2-HMAC-SHA256 over the raw
    # token with a fresh per-token salt, and the raw value transmitted exactly
    # once, by the response that created it. `token_prefix` is the non-secret
    # lookup slice (`inv_widget_` + 6) -- indexed, and unique because unlike the
    # one-key-per-tenant columns there can be several of these per tenant.
    token_hash: str = Field(max_length=255)
    token_salt: str = Field(max_length=64)
    token_prefix: str = Field(max_length=32)
    # Human label so an Admin can tell "marketing site" from "docs site" in the
    # Settings list. Never an authorisation input.
    label: str = Field(default="Chat widget", max_length=100)
    # Origins this token is expected to be embedded on, e.g.
    # ["https://acme.com", "https://www.acme.com"]. Empty list means the origin
    # layer is not applied -- see the class docstring on why that is a
    # defence-in-depth setting and not the gate.
    allowed_origins: list = Field(default=[], sa_column=Column(JSON_VARIANT))
    # Set on revoke. Checked on every resolve, so revocation takes effect on the
    # next request rather than at some TTL boundary. Rows are kept rather than
    # deleted so a revoked token in a log line can still be explained.
    revoked_at: datetime | None = Field(default=None)
    last_used_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)


# Feature 13: Tenant Autopilot — Deduplication Ledger
# One row per file processed (or attempted) by Autopilot — both scheduled and
# manual "Sync Now" runs. Two-layer deduplication:
#   Layer 1: source_file_id match (same file seen before by ID)
#   Layer 2: content_hash match (same PDF bytes, even if renamed/moved)
# status values: 'SUCCESS' | 'SKIPPED_DUPLICATE' | 'FAILED' | 'NO_NEW_FILES'
# Gap 427: rows are additionally grouped into runs by batch_id -- see the field
# comments below and GET /autopilot/history in routers/autopilot.py.
class TenantAutopilotLog(SQLModel, table=True):
    __tablename__ = "tenant_autopilot_logs"
    __table_args__ = (
        # Composite index: dedup layer 1 lookup (tenant + file ID)
        sa.Index("idx_autopilot_log_tenant_file", "tenant_id", "source_file_id"),
        # Index for dedup layer 2 lookup (content hash across tenant)
        sa.Index("idx_autopilot_log_hash", "content_hash"),
        # Gap 427: the Sync History screen groups these rows into *runs*, so the
        # read path is "every row of this tenant's batch" / "GROUP BY batch_id
        # for this tenant" -- neither of the two dedup indexes above serves it.
        sa.Index("idx_autopilot_log_tenant_batch", "tenant_id", "batch_id"),
    )
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(foreign_key="tenant.id", index=True)
    # 'gdrive' | 'manual' (for manually triggered syncs).
    # Gap 334 removed 'salesforce'; historical rows may still carry it.
    source_type: str = Field(max_length=50)
    # Google Drive fileId
    source_file_id: str = Field(max_length=255)
    # Gap 427: the human-readable file name as the source reported it, captured
    # at ingest time. The raw Drive fileId is the only thing the history table
    # could show before this, which is unreadable. Nullable because rows written
    # before this column existed can never be back-filled -- the name is not
    # recoverable from anything else stored.
    source_file_name: str | None = Field(default=None, max_length=512)
    # SHA-256 hash of raw document bytes — reuses email attachment dedup logic
    content_hash: str = Field(max_length=64)
    # Gap 427: which sync run wrote this row. run_sync() already minted a
    # per-run batch_id and stamped it on the Invoice rows it created, but never
    # on its own log rows -- so the history endpoint had no notion of a "run"
    # at all and could only page over individual files. Nullable: every row
    # written before this column existed belongs to no identifiable run, and
    # those legacy rows collapse into one synthetic "before run tracking"
    # entry in GET /autopilot/history.
    #
    # Indexed by the composite idx_autopilot_log_tenant_batch declared above
    # rather than index=True here: every read of this column is already
    # tenant-scoped, so a standalone single-column index would be redundant.
    batch_id: UUID | None = Field(default=None)
    # Gap 427: 'manual' (POST /autopilot/sync, a human pressed Sync Now) or
    # 'scheduled' (the ACA job). Nullable for the same legacy reason as above.
    trigger: str | None = Field(default=None, max_length=20)
    ingested_at: datetime = Field(default_factory=datetime.utcnow)
    # 'SUCCESS' | 'SKIPPED_DUPLICATE' | 'FAILED' | 'NO_NEW_FILES'
    # Gap 427: NO_NEW_FILES is a run-level marker, not a file -- one row with an
    # empty source_file_id, written when a run finds nothing to do, so that an
    # empty run is still visible in history instead of vanishing. It is
    # deliberately NOT 'SUCCESS': both dedup layers and the incremental
    # since_dt lookup filter on status == 'SUCCESS', and a marker row carrying
    # an empty file id/hash must not participate in any of them.
    status: str = Field(max_length=50)
    # populated only on FAILED rows — stores the exception message
    error_detail: str | None = Field(default=None)
    # Gap 429: when the user hid this row from the Sync History screen (NULL =
    # visible). A soft delete, never a hard one: this table is also the dedup
    # ledger and the incremental-poll watermark, so a hidden SUCCESS row must
    # still stop its file being re-imported. Every READ path in
    # routers/autopilot.py filters `hidden_at IS NULL`; every DEDUP/watermark
    # query in services/autopilot_sync.py deliberately does not.
    hidden_at: datetime | None = Field(default=None)


# ---------------------------------------------------------------------------
# Feature 23 (AI Control Tower) — Phase 3: golden-set evaluation results
# ---------------------------------------------------------------------------

class AgentEvalRun(SQLModel, table=True):
    """One graded golden-set question, for one agent/path, at one point in time.

    Phase 1 answers "what did this call cost"; this table answers "was the answer
    any good", and — because every row is timestamped — "is it getting worse".
    `ChatFeedback` (Gap 54) only records what a user happened to vote on; this is
    the same fixed question set re-asked on a schedule, which is what makes a
    quality *trend* readable rather than a shifting sample.

    `agent_name` uses the same vocabulary as Phase 1's `llm_agent_call` events
    (`chat.*`, `sage.*`, `extraction.*`), so cost telemetry and quality rows join
    on one name. Phase 3's own runs add two path-level names that identify a whole
    turn rather than a single call site: `chat.default_path` (`run_query_agent()`)
    and, until Gap 316 deleted the orchestrator on 2026-08-25, `sage.agentic_path`
    (`run_agentic_sage()`). Historical rows still carry the latter, so nothing
    reading this column may treat the vocabulary as a closed set.

    The `pass` column is spelled that way in SQL deliberately (it is not a reserved
    word in Postgres or SQLite) but `pass` is a Python keyword, so the attribute is
    `passed` and the column name is pinned via `sa_column`.

    **Two populations live in this table since Gap 304 half (2) (2026-08-24)**, and
    `run_source` is the only thing that tells them apart:

      * `golden` — one graded question from the fixed bank, written by
        `scripts/run_agent_eval.py`. Carries its own `question`/`actual_answer`
        text, because a golden case's text is test data the repo owns.
      * `production` — one real end-user chat turn, scored by
        `services/online_quality_judge.py`. Carries **no question or answer text
        at all**: it is scores plus `message_id`, which points at the
        `chatmessage` row that already holds the text. Duplicating a customer's
        question into an analytics table is a second copy of the same personal
        data with its own retention story, and the founder's decision was that
        this table never gets one.

    That is why `question`/`actual_answer` became nullable and why the
    `ck_agent_eval_run_text_or_message` CHECK exists: nullable alone would have
    quietly allowed a golden row with no text, which is a corrupt row. The check
    keeps the golden invariant ("a bank row carries its text") while allowing the
    production shape ("a live row carries a pointer instead").

    Every consumer that trends the golden bank must filter on `run_source`, or it
    blends two populations that are not comparable — production rows can never
    have `accuracy_score`/`context_score` (both need a reference answer) and their
    `pass` is decided on fewer dimensions. `services/online_eval_signals.py`'s
    golden-bank filter is the worked example.
    """
    __tablename__ = "agent_eval_run"
    __table_args__ = (
        # The two questions this table exists to answer, both of them a scan by
        # time: "how did agent X trend" and "what happened on day D".
        sa.Index("idx_agent_eval_run_agent_time", "agent_name", "run_at"),
        sa.Index("idx_agent_eval_run_tenant_time", "tenant_id", "run_at"),
        # Gap 304 half (2): every consumer of this table now has to say which
        # population it means, and the ops digest asks for exactly this pair
        # (one source, one time window) twice per run.
        sa.Index("idx_agent_eval_run_source_time", "run_source", "run_at"),
        # A golden row without its text is a corrupt row; a production row with
        # text is a privacy regression. One constraint, both directions.
        sa.CheckConstraint(
            "message_id IS NOT NULL OR (question IS NOT NULL AND actual_answer IS NOT NULL)",
            name="ck_agent_eval_run_text_or_message",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    agent_name: str = Field(max_length=100, index=True)
    run_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    #: Which population this row belongs to — `golden` or `production` (Gap 304
    #: half (2)). Defaults to `golden` so every pre-existing row and every
    #: existing writer keeps its meaning without a data migration; only the
    #: online judge ever writes `production`. Deliberately a plain string rather
    #: than an enum, matching `telemetry.RUN_SOURCE_*` (which also has a
    #: `predeploy` value; the DB only needs the population, not the schedule).
    run_source: str = Field(
        default="golden",
        max_length=20,
        sa_column=sa.Column(
            "run_source", sa.String(length=20), nullable=False, server_default="golden", index=True
        ),
    )

    #: The `chatmessage.id` this score belongs to, on production rows only.
    #: NULL on every golden row (a bank case is not a chat message). No FK on
    #: purpose, matching this table's own `tenant_id`: the score is a
    #: measurement that must survive its subject being deleted, and a cascade
    #: from `chatmessage` would silently rewrite quality history when a user
    #: deletes a thread.
    message_id: UUID | None = Field(default=None, index=True)

    # Nullable since Gap 304 half (2) — production rows carry `message_id`
    # instead. See the class docstring and the CHECK above.
    question: str | None = Field(default=None)
    # NULL where the golden case has no single reference answer to compare
    # against (a clarification-shaped case, a greeting). Accuracy is then not
    # scored at all rather than scored against a guess.
    expected_answer: str | None = Field(default=None)
    # Nullable since Gap 304 half (2), same reason as `question` above.
    actual_answer: str | None = Field(default=None)

    # NOT the same predicate on both populations, and a chart that compares the
    # two pass rates without saying so is wrong: a `golden` row's pass is decided
    # over faithfulness + relevance + accuracy, a `production` row's over
    # faithfulness + relevance only, because accuracy needs a reference answer
    # that live traffic does not have. Both come from the same `decide_pass()`,
    # which only grades the dimensions that produced a number -- the difference
    # is in the inputs, not the rule. Filter by `run_source` before averaging.
    passed: bool = Field(
        default=False,
        sa_column=sa.Column("pass", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    # All three are nullable on purpose: a judge that could not be reached, or a
    # case with no reference answer, must leave the score absent rather than
    # record a 0.0 that reads as "scored, and terrible".
    faithfulness_score: float | None = Field(default=None)
    relevance_score: float | None = Field(default=None)
    accuracy_score: float | None = Field(default=None)

    # Component-level scores (added 2026-08-21, migration `c4a91e77b208`).
    # Feature 23's "component-level scoring, not one blended number": the three
    # above say *that* an answer was bad, these three say *which stage* to fix.
    # Same nullable-means-not-scored contract, and deliberately NOT averaged into
    # anything -- the workbook plots three separate trend lines, because an
    # average of a retrieval score and a tax-reasoning score is not a quantity.
    #
    #   context_score       deterministic: fetched invoice ids vs. the golden
    #                       case's known-correct set (F1). No LLM judge.
    #   orchestration_score mechanical: figures in the answer that trace to a
    #                       fetched field or an arithmetic combination of them,
    #                       over total figures. No LLM judge.
    #   persona_score       LLM-judged domain reasoning (tax components, RCM,
    #                       status semantics, category judgement). NULL on every
    #                       turn that required no domain judgement, which is most
    #                       of them -- read the denominator before the level.
    context_score: float | None = Field(default=None)
    orchestration_score: float | None = Field(default=None)
    persona_score: float | None = Field(default=None)

    # Wall-clock for the whole turn, and how many real model round-trips it took.
    # `llm_call_count` is counted from Phase 1's own `llm_agent_call` events, not
    # estimated — it is the number Feature 21's cost/latency question turns on.
    latency_ms: float = Field(default=0.0)
    llm_call_count: int = Field(default=0)

    tenant_id: UUID = Field(index=True)
    # Free text: the case id, the route/tools taken, and any reason a score is
    # absent. Deliberately not a structured column set — this is for a human
    # reading one row, the structured signal is the scores above.
    notes: str | None = Field(default=None)


class RoleMapper:
    """
    Enterprise Role & Permission Engine (Gap 108).
    Maps any 3rd-party IDP string to internal application roles and default permission flags.

    Feature 25 (Gap 337): the user-facing role vocabulary is **Admin, Auditor,
    Trainer** — three roles, per the founder's decision. "Viewer" is retired as a
    *name*; Trainer (which already existed with exactly the permissions the
    founder described: can_train only) takes its place as the third choice an
    Admin can hand out.

    Retiring the name was not a rename, because "Viewer" was doing two unrelated
    jobs at once:
      1. a role an Admin could assign, and
      2. the system's **zero-permission fallback** — what an unmapped IDP role
         string, a missing role, an org-mismatched session (Gap 173's escalation
         clamp) and an API-key request all resolved to.

    Job 2 still has to exist, and it must NOT be one of the three user-facing
    roles: if the fallback slot were Trainer, every unknown role string and every
    org-mismatched session would silently acquire `can_train`, which is the exact
    class of quiet escalation Gap 173 was opened for. So the fallback keeps its
    own name, `NO_ROLE`, deliberately spelled "Restricted" — a value that must
    never appear in an invite dropdown, a role picker, or any user-facing copy.
    `USER_FACING_ROLES` below is the assignable set; `NO_ROLE` is not in it.
    """

    # The internal zero-permission fallback. Not a role anyone is given; the
    # answer to "we could not establish a role for this request".
    NO_ROLE = "Restricted"

    # The three roles a human is ever assigned. Anything outside this tuple is
    # either Admin-adjacent legacy data or the fallback above.
    USER_FACING_ROLES = ("Admin", "Auditor", "Trainer")

    ROLE_ALIAS_MAP = {
        "org:admin": "Admin",
        "admin": "Admin",
        "org_admin": "Admin",
        "org:trainer": "Trainer",
        "trainer": "Trainer",
        "org_trainer": "Trainer",
        "org:auditor": "Auditor",
        "auditor": "Auditor",
        # Gap 337: an IDP "member" is not a Trainer. These three used to map to
        # "Viewer" and resolved to zero permissions; they now map to the fallback
        # and resolve to exactly the same zero permissions. `viewer` is kept as a
        # legacy input alias precisely so an old Clerk role string, or a `users`
        # row written before this gap, still lands somewhere safe.
        "org:member": NO_ROLE,
        "member": NO_ROLE,
        "viewer": NO_ROLE,
        "restricted": NO_ROLE,
    }

    # Gap 405: can_send_invoices defaults False for every role, including
    # Auditor -- least-privilege by design, matching this class's existing
    # philosophy for the other three (an Admin grants it explicitly per user,
    # same as can_train/can_audit/can_load).
    ROLE_PERMISSION_DEFAULTS = {
        "Admin":   {"can_train": True,  "can_audit": True,  "can_load": True,  "can_send_invoices": True},
        "Trainer": {"can_train": True,  "can_audit": False, "can_load": False, "can_send_invoices": False},
        "Auditor": {"can_train": False, "can_audit": True,  "can_load": False, "can_send_invoices": False},
        NO_ROLE:   {"can_train": False, "can_audit": False, "can_load": False, "can_send_invoices": False},
    }

    @classmethod
    def normalize_role(cls, raw_role: str | None) -> str:
        """Translates raw strings (e.g. 'org:trainer', 'trainer') into internal DB roles ('Trainer')."""
        if not raw_role:
            return cls.NO_ROLE
        clean_key = str(raw_role).strip().lower()
        return cls.ROLE_ALIAS_MAP.get(clean_key, raw_role.title() if raw_role else cls.NO_ROLE)

    @classmethod
    def resolve_permissions(cls, role: str, user: Any = None) -> tuple[bool, bool, bool, bool]:
        """Resolves (can_train, can_audit, can_load, can_send_invoices) for any role."""
        if role == "Admin":
            return True, True, True, True

        # Gap 337: an unrecognised role — including the literal "Viewer" on any
        # row that predates this gap's data migration — falls to the
        # zero-permission fallback, never to a role that grants something.
        defaults = cls.ROLE_PERMISSION_DEFAULTS.get(role, cls.ROLE_PERMISSION_DEFAULTS[cls.NO_ROLE])
        can_train = getattr(user, "can_train", None) if user else None
        can_audit = getattr(user, "can_audit", None) if user else None
        can_load  = getattr(user, "can_load", None)  if user else None
        can_send_invoices = getattr(user, "can_send_invoices", None) if user else None

        res_train = can_train if can_train is not None else defaults["can_train"]
        res_audit = can_audit if can_audit is not None else defaults["can_audit"]
        res_load  = can_load  if can_load  is not None  else defaults["can_load"]
        res_send  = can_send_invoices if can_send_invoices is not None else defaults["can_send_invoices"]

        return bool(res_train), bool(res_audit), bool(res_load), bool(res_send)

# ---------------------------------------------------------------------------
# Feature 19 / Feature Website 5: Support Ticket & Inquiry Engine
# ---------------------------------------------------------------------------

class SupportTicket(SQLModel, table=True):
    """
    Persists all inbound support interactions:
      - WEBSITE_CONTACT  : public /contact form submissions from invoice-website
      - HELP_CHATBOT     : AI-escalated tickets from invoice-fe Help Center
      - DIRECT_TICKET    : manually raised tickets from Help Center chat header

    ticket_number is the human-visible reference:
      - INQ-YYYY-XXXXXXXX  for website contact inquiries (source=WEBSITE_CONTACT)
      - TICK-YYYY-XXXXXXXX for app support tickets (source=HELP_CHATBOT / DIRECT_TICKET)

    The suffix is 8 uppercase hex characters from `secrets.token_hex(4)` -- see
    routers/support.py::_generate_ticket_number. Gap 251: this replaced a
    4-digit `randint(1000, 9999)` suffix, whose 9,000 values per year per prefix
    could be exhausted by a few thousand unauthenticated POSTs, after which
    every new ticket failed. The current keyspace is 4.29 billion per year per
    prefix, and exhaustion now surfaces as a 503 rather than an uncaught 500.
    """
    __tablename__ = "supportticket"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    ticket_number: str = Field(max_length=32, unique=True, index=True)

    # Tenant + user — nullable because website contact submissions are anonymous
    tenant_id: UUID | None = Field(default=None, nullable=True, index=True)
    user_id: UUID | None = Field(default=None, nullable=True)
    user_email: str = Field(max_length=255, index=True)
    user_name: str | None = Field(default=None, max_length=255)

    # Submission source & classification
    source: str = Field(default="WEBSITE_CONTACT", max_length=32)  # WEBSITE_CONTACT | HELP_CHATBOT | DIRECT_TICKET
    category: str = Field(default="GENERAL", max_length=64)         # SALES | TECHNICAL_SUPPORT | BILLING | PARTNERSHIP | GENERAL
    priority: str = Field(default="NORMAL", max_length=32)          # LOW | NORMAL | URGENT

    # Content
    subject: str = Field(max_length=255)
    description: str
    company_name: str | None = Field(default=None, max_length=255)

    # For chatbot-escalated tickets — the full conversation transcript is attached
    chat_transcript: list = Field(default=[], sa_column=Column(JSON_VARIANT))

    # Lifecycle
    status: str = Field(default="OPEN", max_length=32)  # OPEN | IN_PROGRESS | RESOLVED | CLOSED
    admin_notes: str | None = Field(default=None)

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
