# Phase 2 Enhancements — Idea Capture

> **Status: CAPTURE ONLY. Not scoped, not designed, not started.**
> Filed 2026-09-01 at the founder's request to record the ideas before they're
> lost, ahead of any detailed design. Each item below gets its own
> `feature_N_*.md` spec (per this repo's doc convention) when it's actually
> scoped — this document is the index, not the design. No Gap should be
> opened against any of these until that scoping happens.
>
> Item 1 (chat attachments) was removed 2026-09-04: it shipped as Feature 26
> and its Phases 1-5 -- see `apps/invoice-be/docs/feature_26_chat_attached_documents.md`.

## 5. WAF on Front Door

No WAF/security policy attached to `invoiceeq-fd-profile` (found by the
2026-09-01 live security pass, `reports/security/2026-09-01-live-dev-pass.md`
F1). Deliberately deferred, not fixed now — it's a real Azure cost, and the
founder's call is to hold it for Phase 2 rather than add spend against the
dev environment now. Attach a managed ruleset + rate limiting before any real
production cutover, not before.

## 6. VNet/subnet — private networking for Postgres, Storage, Key Vault, etc.

Groups with the WAF item above: both are the same class of "don't pay for
this on a dev box, do it properly once there's a real prod environment."
`active-work.md`'s `networkIsolation` bool already exists in the bicep as of
2026-08-01 (dev=false/no VNet, prod=true/full private networking including
Redis/Postgres/Storage/OpenAI/DocIntel private endpoints) — this item is
about actually turning that on for a real prod environment, not building it
from scratch. Directly related findings from the same security pass worth
folding into this scoping later: Postgres has `publicNetworkAccess: Enabled`
plus an `AllowAllAzureIPs` rule and two stale personal-IP dev firewall rules;
Storage has `publicNetworkAccess: Enabled` with an open default network rule.
Both would be closed by this item rather than patched individually.

## 2. Accept non-PDF file formats for invoice upload

Today, invoice upload only accepts `.pdf`. Allow common image formats (at
least JPG/JPEG/PNG) by converting them to PDF at the upload boundary before
anything else touches the file, rather than teaching every downstream
consumer (extraction, storage, the viewer, Autopilot's Drive sync) to
understand multiple formats natively.

Already investigated in this session, same day: `pymupdf` (`fitz`) is
already a dependency and can convert a raw image to PDF bytes directly, so
this needs no new library. The real work is inserting that conversion at
each upload entry point (`routers/invoices.py`, `routers/outbound_invoices.py`,
`routers/trainer.py`, `routers/email_ingestion.py`), widening the FE dropzone
`accept` attributes, and widening Autopilot's Google Drive listing filter
(currently `mimeType = 'application/pdf'` only) if Drive-sourced images
should be included too.

**Scoped 2026-09-04** → `apps/invoice-be/docs/feature_28_image_upload_pdf_boundary.md`
(BE) and `apps/invoice-fe/docs/feature_19_image_upload_accept.md` (FE). Awaiting
founder approval of the spec; not started.

## 3. Invoice builder — generate an outbound invoice from an existing one

A tool to create a new outbound vendor invoice using an existing one as the
starting point/template, rather than building one from scratch every time.

Open questions for later scoping: how much is copied verbatim vs. meant to
be edited (line items, amounts, dates), whether this targets recurring
vendors specifically, and how it relates to the existing outbound invoice
creation flow.

**Scoped 2026-09-04** → solution section appended to
`apps/invoice-be/docs/feature_17_invoice_builder.md` (clone-and-edit from an
existing outbound invoice; its PDF is the template). **Approved and built
2026-09-04** — BE Feature 17 (all 10 tasks, `tests/test_invoice_builder.py`
`53 passed` on real Postgres) and FE Feature 20. The open questions above are
answered by founder decisions D1–D7 in the BE spec: everything is copied and
everything listed in `BuildRequest` is editable, rows may be added or removed
(which switches the renderer from in-place substitution to a structured
re-render), no recurring-vendor targeting, and it enters the existing outbound
pipeline exactly as an upload does. Still open on both halves: the manual
dev-stack ("Azure path") verification row.

## 4. Full-scale platform monitoring — Azure SRE-style

A comprehensive observability/monitoring/alerting build-out for the whole
platform — dashboards, alerting, SLOs, incident-response tooling — the kind
of setup an Azure SRE practice would run, rather than the current ad-hoc
state.

Cross-references existing standing decisions worth checking before scoping
this: the dashboard approach is already settled as Azure Workbooks across
every feature, never a custom in-app page — don't re-litigate that. Also
note the full infra rebuild (including monitoring) is currently deferred
until after benchmark/RAG work — this item may be the trigger to revisit
that deferral, or may need to be sequenced after it, founder's call when
this gets scoped.
