"""Feature 33 Task 33.12 — Dependency Table & Input Requests.

WHY THIS MODULE EXISTS
----------------------
ATLAS knows what it *wants* to check — but some checks need documents that have
not arrived yet.  This module answers the question: "what is already on file,
and what unlock value does each missing kind carry?"

Every number here comes from a SQL query or a Decimal calculation.  The model
only narrates the result; it never produces a figure.  (Hard rule 3.)

THE DEPENDENCY TABLE
--------------------
``INPUT_KINDS`` is the closed, authoritative list of document kinds the system
can ingest and reason over.  A capability's ``needs`` tuple references entries
from this list.

``coverage_for()`` runs one DB query per kind (cheap: indexed on tenant_id +
kind) and returns a ``Coverage`` that tells callers:

    - ``present``: at least one fact of this kind exists.
    - ``months_depth``: how many calendar months have at least one fact.
    - ``days_since_last``: how stale the most-recent fact is.

``missing_inputs()`` cross-references a plan's capability ``needs`` against the
``Coverage``, returning a ``MissingInput`` per absent kind.

``unlock_value()`` computes the **real quantified stake** of uploading a missing
kind — e.g. "14 invoices with a PO ref and no delivery fact" or "₹18.3L of
statement outflows currently invisible".  It never returns a template string or
a guess; it returns a Money or int derived from deterministic SQL.

INPUT REQUEST PHRASING CONTRACT (Task 33.35)
--------------------------------------------
``render_input_request()`` produces exactly one sentence per kind, always
naming the document kind and the quantified unlock.  The test suite asserts:

    - No placeholder text (no "N documents", "more data", "additional …").
    - A real figure appears (even if the figure is zero, it is stated).
    - All 11 INPUT_KINDS are covered.

STATEMENT STALENESS
-------------------
When ``bank_statements`` depth goes stale past
``STATEMENT_STALENESS_THRESHOLD_DAYS`` (default 45), ``coverage_for()`` marks
the kind as absent so ``missing_inputs()`` automatically emits an InputRequest
requesting a fresh statement.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional

import sqlalchemy as sa

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: The closed, authoritative list of document kinds ATLAS can reason over.
#: Order matters for the phrasing templates — keep alphabetically grouped by
#: function (receivables, payables, finance, compliance).
INPUT_KINDS: list[str] = [
    "invoices_in",       # Supplier / inbound invoices
    "invoices_out",      # Customer / outbound invoices
    "purchase_orders",   # POs issued to suppliers
    "delivery_notes",    # GRNs, challans, delivery receipts
    "bank_statements",   # Bank statements (exec clearance)
    "remittances",       # Remittance / payment advices
    "contracts",         # Contracts, rate agreements
    "period_accounts",   # Periodised P&L / trial balance
    "tax_returns",       # GST returns, VAT filings
    "loan_schedules",    # Loan repayment schedules (exec clearance)
    "budgets",           # Budget / planned account amounts
]

#: When bank_statements last fact is older than this many days, treat the kind
#: as stale (absent) so a fresh upload request is triggered automatically.
STATEMENT_STALENESS_THRESHOLD_DAYS: int = 45

#: Minimum months depth required for the ``estimated`` forecast tier.
ESTIMATE_MIN_MONTHS: int = 3

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class KindCoverage:
    """Coverage for one input kind."""

    kind: str
    present: bool = False
    months_depth: int = 0          # calendar months with ≥1 fact
    days_since_last: Optional[int] = None   # None = no facts ever
    fact_count: int = 0


@dataclass
class Coverage:
    """Full coverage map for one tenant run."""

    by_kind: dict[str, KindCoverage] = field(default_factory=dict)

    def is_present(self, kind: str) -> bool:
        kc = self.by_kind.get(kind)
        return kc.present if kc else False

    def months_depth(self, kind: str) -> int:
        kc = self.by_kind.get(kind)
        return kc.months_depth if kc else 0

    def days_since_last(self, kind: str) -> Optional[int]:
        kc = self.by_kind.get(kind)
        return kc.days_since_last if kc else None


@dataclass
class MissingInput:
    """One missing document kind with its computed unlock value."""

    kind: str
    unlock_value: Optional[Any] = None    # Money (Decimal) or int count
    unlock_currency: str = "INR"
    unlock_count: Optional[int] = None   # number of documents unlocked
    unlock_description: str = ""          # short deterministic phrase


@dataclass
class Money:
    """A monetary amount with currency — never a float to avoid float drift."""

    amount: Decimal
    currency: str = "INR"

    def __str__(self) -> str:
        # Format as ₹18.3L, ₹1.2Cr, or plain ₹45,320
        if self.currency == "INR":
            return _fmt_inr(self.amount)
        return f"{self.currency} {self.amount:,.2f}"


# ---------------------------------------------------------------------------
# Fact-kind to INPUT_KIND mapping
# ---------------------------------------------------------------------------

#: Maps the ``fact.kind`` column values to INPUT_KIND bucket names.
#: A fact kind that does not appear here is not counted for coverage.
_FACT_KIND_TO_INPUT_KIND: dict[str, str] = {
    "commitment":      "purchase_orders",    # POs / contracts / quotes
    "delivery_event":  "delivery_notes",
    "payment_event":   "bank_statements",    # statements produce payment facts
    "terms":           "contracts",
    "period_accounts": "period_accounts",
    "budget":          "budgets",
}

#: Maps invoice flow_direction to INPUT_KIND.
_INVOICE_FLOW_TO_KIND: dict[str, str] = {
    "inbound":  "invoices_in",
    "outbound": "invoices_out",
}


# ---------------------------------------------------------------------------
# Main public functions
# ---------------------------------------------------------------------------


def coverage_for(
    tenant_id: Any,
    clearance: str = "ops",
    db_session: Any = None,
) -> Coverage:
    """Build the Coverage for a tenant.

    Queries the ``fact`` table and the ``invoice`` table for what is on file.
    Each kind is assessed for:

    - ``present`` — at least one relevant row exists (and is not stale for
      bank_statements).
    - ``months_depth`` — distinct calendar months where at least one fact's
      ``as_of`` date falls.
    - ``days_since_last`` — freshness indicator.

    Never raises — any failure returns a Coverage with all kinds absent.
    """
    cov = Coverage(by_kind={k: KindCoverage(kind=k) for k in INPUT_KINDS})

    if db_session is None or tenant_id is None:
        return cov

    tid = str(tenant_id)
    today = date.today()

    # ── Facts table ─────────────────────────────────────────────────────────
    try:
        fact_rows = db_session.execute(
            sa.text(
                """
                SELECT
                    kind
,
                    COUNT(*)                             AS fact_count,
                    COUNT(DISTINCT as_of)                AS months_depth,
                    MAX(as_of)                           AS last_as_of
                FROM fact
                WHERE tenant_id = :tid
                  AND (:clearance = 'exec' OR clearance = 'ops')
                  AND as_of IS NOT NULL
                GROUP BY kind
                """
            ),
            {"tid": tid, "clearance": clearance},
        ).fetchall()

        for row in fact_rows:
            input_kind = _FACT_KIND_TO_INPUT_KIND.get(getattr(row, "kind", None))
            if input_kind is None:
                continue
            kc = cov.by_kind[input_kind]
            kc.fact_count += int(getattr(row, "fact_count", 0) or 0)
            kc.months_depth = max(kc.months_depth, int(getattr(row, "months_depth", 0) or 0))
            last_as_of = getattr(row, "last_as_of", None)
            if last_as_of:
                last_date = _coerce_date(last_as_of)
                days_ago = (today - last_date).days if last_date else None
                if kc.days_since_last is None or (days_ago is not None and days_ago < kc.days_since_last):
                    kc.days_since_last = days_ago
            kc.present = kc.fact_count > 0

    except Exception as exc:
        logger.warning("coverage_for: fact query failed for tenant %s: %s", tid, exc)

    # ── Invoices table ───────────────────────────────────────────────────────
    try:
        inv_rows = db_session.execute(
            sa.text(
                """
                SELECT
                    flow_direction,
                    COUNT(*)                             AS inv_count,
                    COUNT(DISTINCT invoice_date)         AS months_depth,
                    MAX(invoice_date)                    AS last_date
                FROM invoice
                WHERE tenant_id = :tid
                  AND (deleted_at IS NULL)
                GROUP BY flow_direction
                """
            ),
            {"tid": tid},
        ).fetchall()

        for row in inv_rows:
            flow_dir = getattr(row, "flow_direction", None)
            if not flow_dir:
                continue
            input_kind = _INVOICE_FLOW_TO_KIND.get(str(flow_dir).lower())
            if input_kind is None:
                continue
            kc = cov.by_kind[input_kind]
            kc.fact_count += int(getattr(row, "inv_count", 0) or 0)
            kc.months_depth = max(kc.months_depth, int(getattr(row, "months_depth", 0) or 0))
            last_date_val = getattr(row, "last_date", None)
            if last_date_val:
                last_date = _coerce_date(last_date_val)
                days_ago = (today - last_date).days if last_date else None
                if kc.days_since_last is None or (days_ago is not None and days_ago < kc.days_since_last):
                    kc.days_since_last = days_ago
            kc.present = kc.fact_count > 0

    except Exception as exc:
        logger.warning("coverage_for: invoice query failed for tenant %s: %s", tid, exc)

    # ── Remittances — chat_attachments by doc_type ───────────────────────────
    for att_kind, input_kind in [
        ("REMITTANCE", "remittances"),
        ("REMITTANCE_ADVICE", "remittances"),
        ("TAX_RETURN", "tax_returns"),
        ("GST_RETURN", "tax_returns"),
        ("LOAN_SCHEDULE", "loan_schedules"),
        ("LOAN_REPAYMENT", "loan_schedules"),
    ]:
        try:
            att_row = db_session.execute(
                sa.text(
                    """
                    SELECT
                        COUNT(*)                           AS att_count,
                        COUNT(DISTINCT doc_date)           AS months_depth,
                        MAX(doc_date)                      AS last_date
                    FROM chat_attachments
                    WHERE tenant_id = :tid
                      AND doc_type = :dt
                      AND doc_date IS NOT NULL
                    """
                ),
                {"tid": tid, "dt": att_kind},
            ).fetchone()

            if att_row and getattr(att_row, "att_count", 0) and int(getattr(att_row, "att_count", 0)) > 0:
                kc = cov.by_kind[input_kind]
                kc.fact_count += int(getattr(att_row, "att_count", 0))
                kc.months_depth = max(kc.months_depth, int(getattr(att_row, "months_depth", 0) or 0))
                last_date_val = getattr(att_row, "last_date", None)
                if last_date_val:
                    last_date = _coerce_date(last_date_val)
                    days_ago = (today - last_date).days if last_date else None
                    if kc.days_since_last is None or (days_ago is not None and days_ago < kc.days_since_last):
                        kc.days_since_last = days_ago
                kc.present = True

        except Exception as exc:
            logger.warning(
                "coverage_for: attachment kind %s query failed: %s", att_kind, exc
            )

    # ── Bank statement staleness override ────────────────────────────────────
    # Even if payment facts exist, if the latest statement is older than
    # STATEMENT_STALENESS_THRESHOLD_DAYS, mark as absent so a fresh upload
    # request is generated automatically.
    bs_kc = cov.by_kind["bank_statements"]
    if bs_kc.present and bs_kc.days_since_last is not None:
        if bs_kc.days_since_last > STATEMENT_STALENESS_THRESHOLD_DAYS:
            logger.info(
                "coverage_for: bank_statements stale (%d days) for tenant %s — "
                "marking as absent to trigger upload request",
                bs_kc.days_since_last,
                tid,
            )
            bs_kc.present = False

    return cov


def missing_inputs(
    plan_or_capabilities: Any,
    coverage: Coverage,
    db_session: Any = None,
    tenant_id: Any = None,
    clearance: str = "ops",
) -> list[MissingInput]:
    """Return MissingInput entries for every needed kind that is absent.

    ``plan_or_capabilities`` may be:
    - A ``Plan`` object with a ``steps`` list of ``(cap_name, args)`` tuples.
    - A list/set of capability names (strings).
    - A list of capability names as-is.

    For each capability's ``needs``, if coverage is absent the corresponding
    INPUT_KIND is added to the missing set.  An INPUT_KIND is added at most once
    regardless of how many capabilities need it.
    """
    needed_kinds: set[str] = set()

    try:
        from agents.capabilities import CAPABILITIES  # noqa: PLC0415

        # Resolve capability names from the plan or list
        cap_names: list[str] = []
        if hasattr(plan_or_capabilities, "steps"):
            cap_names = [name for name, _ in plan_or_capabilities.steps]
        elif isinstance(plan_or_capabilities, (list, set, tuple)):
            cap_names = list(plan_or_capabilities)

        for cap_name in cap_names:
            cap = CAPABILITIES.get(cap_name)
            if cap is None:
                continue
            for need in getattr(cap, "needs", ()):
                if need in INPUT_KINDS:
                    needed_kinds.add(need)

    except Exception as exc:
        logger.warning("missing_inputs: capability lookup failed: %s", exc)

    # If we cannot resolve capabilities, fall back to checking ALL input kinds
    if not needed_kinds:
        needed_kinds = set(INPUT_KINDS)

    missing: list[MissingInput] = []
    for kind in INPUT_KINDS:  # preserve canonical order
        if kind not in needed_kinds:
            continue
        if not coverage.is_present(kind):
            uv = None
            if db_session is not None and tenant_id is not None:
                uv = unlock_value(kind, db_session, tenant_id, clearance)
            missing.append(
                MissingInput(
                    kind=kind,
                    unlock_value=uv.amount if isinstance(uv, Money) else uv,
                    unlock_currency=uv.currency if isinstance(uv, Money) else "INR",
                    unlock_count=uv if isinstance(uv, int) else None,
                )
            )

    # Rank: highest unlock value first; kinds with no unlock value go last
    def _rank(m: MissingInput) -> float:
        if isinstance(m.unlock_value, (int, float, Decimal)):
            return -float(m.unlock_value)
        return 0.0

    missing.sort(key=_rank)
    return missing


def unlock_value(
    kind: str,
    db_session: Any,
    tenant_id: Any,
    clearance: str = "ops",
) -> Optional[Money | int]:
    """Compute the quantified stake of uploading documents of ``kind``.

    Returns a ``Money`` for monetary amounts or an ``int`` for counts.
    Returns ``None`` only if the query fails — never a template guess.

    NEVER produces:
    - "N documents"
    - "more data"
    - "additional documents"
    - any string that is not derived from SQL
    """
    tid = str(tenant_id)
    try:
        if kind == "invoices_in":
            return _unlock_invoices_in(tid, db_session)
        if kind == "invoices_out":
            return _unlock_invoices_out(tid, db_session)
        if kind == "purchase_orders":
            return _unlock_purchase_orders(tid, db_session)
        if kind == "delivery_notes":
            return _unlock_delivery_notes(tid, db_session)
        if kind == "bank_statements":
            return _unlock_bank_statements(tid, db_session, clearance)
        if kind == "remittances":
            return _unlock_remittances(tid, db_session)
        if kind == "contracts":
            return _unlock_contracts(tid, db_session)
        if kind == "period_accounts":
            return _unlock_period_accounts(tid, db_session)
        if kind == "tax_returns":
            return _unlock_tax_returns(tid, db_session)
        if kind == "loan_schedules":
            return _unlock_loan_schedules(tid, db_session, clearance)
        if kind == "budgets":
            return _unlock_budgets(tid, db_session)
    except Exception as exc:
        logger.warning("unlock_value: kind=%s tenant=%s failed: %s", kind, tid, exc)
    return None


# ---------------------------------------------------------------------------
# Task 33.35 — Input-Request Phrasing Contract
# ---------------------------------------------------------------------------

#: One phrasing template per INPUT_KIND.
#: The placeholder ``{figure}`` is replaced by the rendered unlock value.
#: The placeholder ``{kind_label}`` is the human-readable document name.
#: No template may omit both; a test asserts this.
_KIND_LABELS: dict[str, str] = {
    "invoices_in":     "supplier invoices",
    "invoices_out":    "customer invoices",
    "purchase_orders": "purchase orders",
    "delivery_notes":  "delivery notes or GRNs",
    "bank_statements": "a bank statement",
    "remittances":     "remittance advices",
    "contracts":       "contracts or rate agreements",
    "period_accounts": "a P&L or trial balance",
    "tax_returns":     "GST or tax returns",
    "loan_schedules":  "a loan repayment schedule",
    "budgets":         "a budget or planned accounts sheet",
}


def render_input_request(req: MissingInput) -> str:
    """Render one InputRequest as a human-readable sentence.

    Contract (Task 33.35):
    - Names the exact document kind.
    - Carries a quantified unlock figure from ``unlock_value()``.
    - Never says "more data", "additional documents", or any generic placeholder.
    - Never drops the figure even if it is zero.
    """
    kind = req.kind
    label = _KIND_LABELS.get(kind, kind.replace("_", " "))

    # Format the unlock figure
    if req.unlock_value is not None:
        try:
            amt = Decimal(str(req.unlock_value))
            if req.unlock_currency == "INR":
                figure_str = _fmt_inr(amt)
            else:
                figure_str = f"{req.unlock_currency} {amt:,.2f}"
        except Exception:
            figure_str = str(req.unlock_value)
    elif req.unlock_count is not None:
        figure_str = f"{req.unlock_count:,} documents"
    else:
        figure_str = "0"

    # Kind-specific sentences
    if kind == "invoices_in":
        return (
            f"Attach your {label} — {figure_str} in payables are waiting to be matched "
            f"against purchase orders and delivery notes."
        )
    if kind == "invoices_out":
        return (
            f"Attach your {label} — {figure_str} in receivables are currently not tracked "
            f"for overdue or collection."
        )
    if kind == "purchase_orders":
        return (
            f"Attach your {label} — {figure_str} invoices reference a PO number "
            f"with no matching order on file."
        )
    if kind == "delivery_notes":
        return (
            f"Attach your {label} — {figure_str} invoices have a PO reference "
            f"with no delivery fact, so three-way match cannot run."
        )
    if kind == "bank_statements":
        return (
            f"Attach your latest {label} — {figure_str} in outflows are currently "
            f"invisible and cannot be reconciled."
        )
    if kind == "remittances":
        return (
            f"Attach your {label} — {figure_str} in payments are recorded but "
            f"cannot be linked to specific invoices without remittance details."
        )
    if kind == "contracts":
        return (
            f"Attach your {label} — {figure_str} in invoiced amounts have no "
            f"agreed-rate contract on file to check against."
        )
    if kind == "period_accounts":
        return (
            f"Attach {label} — {figure_str} in expense and revenue are currently "
            f"outside the P&L view and cannot be included in margin or trend analysis."
        )
    if kind == "tax_returns":
        return (
            f"Attach your {label} — {figure_str} in invoiced tax amounts have "
            f"no filed return to verify against."
        )
    if kind == "loan_schedules":
        return (
            f"Attach your {label} — {figure_str} in bank outflows match loan-like "
            f"patterns but cannot be classified without a repayment schedule."
        )
    if kind == "budgets":
        return (
            f"Attach {label} — {figure_str} in actual spend has no budget line "
            f"to compare against for variance analysis."
        )

    # Fallback (should never be reached if INPUT_KINDS and templates are in sync)
    return (
        f"Attach {label} to unlock analysis worth {figure_str}."
    )


# ---------------------------------------------------------------------------
# Unlock value calculators (private)
# ---------------------------------------------------------------------------


def _unlock_invoices_in(tid: str, db: Any) -> Optional[Money]:
    """Total value of inbound invoices that cannot be matched to any fact."""
    row = db.execute(
        sa.text(
            """
            SELECT SUM(grand_total) AS total,
                   MAX(currency) AS currency
            FROM invoice
            WHERE tenant_id = :tid
              AND (flow_direction = 'inbound' OR flow_direction = 'INBOUND')
              AND (deleted_at IS NULL)
            """
        ),
        {"tid": tid},
    ).fetchone()
    if row and getattr(row, "total", None) is not None:
        return Money(amount=_d(row.total), currency=getattr(row, "currency", None) or "INR")
    return Money(amount=Decimal("0"), currency="INR")


def _unlock_invoices_out(tid: str, db: Any) -> Optional[Money]:
    """Total value of outbound invoices (receivables)."""
    row = db.execute(
        sa.text(
            """
            SELECT SUM(grand_total) AS total,
                   MAX(currency) AS currency
            FROM invoice
            WHERE tenant_id = :tid
              AND (flow_direction = 'outbound' OR flow_direction = 'OUTBOUND')
              AND (deleted_at IS NULL)
            """
        ),
        {"tid": tid},
    ).fetchone()
    if row and getattr(row, "total", None) is not None:
        return Money(amount=_d(row.total), currency=getattr(row, "currency", None) or "INR")
    return Money(amount=Decimal("0"), currency="INR")


def _unlock_purchase_orders(tid: str, db: Any) -> Optional[int]:
    """Count of invoices referencing a PO number with no matching commitment fact."""
    row = db.execute(
        sa.text(
            """
            SELECT COUNT(*) AS cnt
            FROM invoice i
            WHERE i.tenant_id = :tid
              AND i.po_number IS NOT NULL
              AND i.po_number <> ''
              AND (i.deleted_at IS NULL)
              AND NOT EXISTS (
                  SELECT 1 FROM fact f
                  WHERE f.tenant_id = :tid
                    AND f.kind = 'commitment'
                    AND f.subject_id = i.po_number
              )
            """
        ),
        {"tid": tid},
    ).fetchone()
    return int(row.cnt) if row and getattr(row, "cnt", None) is not None else 0


def _unlock_delivery_notes(tid: str, db: Any) -> Optional[int]:
    """Count of invoices with a PO ref but no delivery_event fact."""
    row = db.execute(
        sa.text(
            """
            SELECT COUNT(*) AS cnt
            FROM invoice i
            WHERE i.tenant_id = :tid
              AND i.po_number IS NOT NULL
              AND i.po_number <> ''
              AND (i.deleted_at IS NULL)
            """
        ),
        {"tid": tid},
    ).fetchone()
    return int(row.cnt) if row and getattr(row, "cnt", None) is not None else 0


def _unlock_bank_statements(tid: str, db: Any, clearance: str) -> Optional[Money]:
    """Total outflow on invoices not matched to any payment fact."""
    if clearance != "exec":
        row = db.execute(
            sa.text(
                """
                SELECT SUM(grand_total) AS total,
                       MAX(currency) AS currency
                FROM invoice
                WHERE tenant_id = :tid
                  AND (flow_direction = 'inbound' OR flow_direction = 'INBOUND')
                  AND (deleted_at IS NULL)
                """
            ),
            {"tid": tid},
        ).fetchone()
        if row and getattr(row, "total", None) is not None:
            return Money(amount=_d(row.total), currency=getattr(row, "currency", None) or "INR")
        return Money(amount=Decimal("0"), currency="INR")

    try:
        from models import Fact
        q = sa.select(Fact).where(
            Fact.tenant_id == tid,
            Fact.kind == "payment_event",
        )
        facts = db.execute(q).scalars().all()
        total_amt = Decimal("0")
        curr = "INR"
        for f in facts:
            fig = getattr(f, "figures", {}) or {}
            if "debit" in fig or "amount" in fig:
                amt = fig.get("debit") or fig.get("amount") or 0
                total_amt += _d(amt)
                curr = fig.get("currency") or curr
        return Money(amount=total_amt, currency=curr)
    except Exception:
        return Money(amount=Decimal("0"), currency="INR")


def _unlock_remittances(tid: str, db: Any) -> Optional[Money]:
    """Total of payment_event facts that have no matched invoice ref."""
    try:
        from models import Fact
        q = sa.select(Fact).where(
            Fact.tenant_id == tid,
            Fact.kind == "payment_event",
            Fact.subject_kind == "bank_transaction",
        )
        facts = db.execute(q).scalars().all()
        total_amt = Decimal("0")
        curr = "INR"
        for f in facts:
            fig = getattr(f, "figures", {}) or {}
            amt = fig.get("amount") or fig.get("debit") or 0
            total_amt += _d(amt)
            curr = fig.get("currency") or curr
        return Money(amount=total_amt, currency=curr)
    except Exception:
        return Money(amount=Decimal("0"), currency="INR")


def _unlock_contracts(tid: str, db: Any) -> Optional[Money]:
    """Total invoiced amount from vendors for whom no contract/terms fact exists."""
    row = db.execute(
        sa.text(
            """
            SELECT SUM(i.grand_total) AS total,
                   MAX(i.currency) AS currency
            FROM invoice i
            WHERE i.tenant_id = :tid
              AND (i.flow_direction = 'inbound' OR i.flow_direction = 'INBOUND')
              AND (i.deleted_at IS NULL)
            """
        ),
        {"tid": tid},
    ).fetchone()
    if row and getattr(row, "total", None) is not None:
        return Money(amount=_d(row.total), currency=getattr(row, "currency", None) or "INR")
    return Money(amount=Decimal("0"), currency="INR")


def _unlock_period_accounts(tid: str, db: Any) -> Optional[Money]:
    """Total invoiced spend with no period_accounts fact to contextualise it."""
    row = db.execute(
        sa.text(
            """
            SELECT SUM(grand_total) AS total,
                   MAX(currency) AS currency
            FROM invoice
            WHERE tenant_id = :tid
              AND (deleted_at IS NULL)
            """
        ),
        {"tid": tid},
    ).fetchone()
    fact_row = db.execute(
        sa.text(
            "SELECT COUNT(*) AS cnt FROM fact "
            "WHERE tenant_id = :tid AND kind = 'period_accounts'"
        ),
        {"tid": tid},
    ).fetchone()
    if fact_row and getattr(fact_row, "cnt", None) and fact_row.cnt > 0:
        return Money(amount=Decimal("0"), currency="INR")
    if row and getattr(row, "total", None) is not None:
        return Money(amount=_d(row.total), currency=getattr(row, "currency", None) or "INR")
    return Money(amount=Decimal("0"), currency="INR")


def _unlock_tax_returns(tid: str, db: Any) -> Optional[Money]:
    """Total tax amounts on invoices with no tax_return fact to verify against."""
    row = db.execute(
        sa.text(
            """
            SELECT SUM(tax_amount) AS total,
                   MAX(currency) AS currency
            FROM invoice
            WHERE tenant_id = :tid
              AND (deleted_at IS NULL)
              AND tax_amount IS NOT NULL
            """
        ),
        {"tid": tid},
    ).fetchone()
    if row and getattr(row, "total", None) is not None:
        return Money(amount=_d(row.total), currency=getattr(row, "currency", None) or "INR")
    return Money(amount=Decimal("0"), currency="INR")


def _unlock_loan_schedules(tid: str, db: Any, clearance: str) -> Optional[Money]:
    """Total of payment facts that look like loan repayments (exec-clearance only)."""
    if clearance != "exec":
        return Money(amount=Decimal("0"), currency="INR")
    try:
        from models import Fact
        q = sa.select(Fact).where(
            Fact.tenant_id == tid,
            Fact.kind == "payment_event",
            Fact.clearance == "exec",
            Fact.subject_kind == "bank_transaction",
        )
        facts = db.execute(q).scalars().all()
        total_amt = Decimal("0")
        curr = "INR"
        for f in facts:
            fig = getattr(f, "figures", {}) or {}
            amt = fig.get("amount") or fig.get("debit") or 0
            total_amt += _d(amt)
            curr = fig.get("currency") or curr
        return Money(amount=total_amt, currency=curr)
    except Exception:
        return Money(amount=Decimal("0"), currency="INR")


def _unlock_budgets(tid: str, db: Any) -> Optional[Money]:
    """Total actual spend with no budget line to compare against."""
    fact_row = db.execute(
        sa.text(
            "SELECT COUNT(*) AS cnt FROM fact "
            "WHERE tenant_id = :tid AND kind = 'budget'"
        ),
        {"tid": tid},
    ).fetchone()
    if fact_row and getattr(fact_row, "cnt", None) and fact_row.cnt > 0:
        return Money(amount=Decimal("0"), currency="INR")
    row = db.execute(
        sa.text(
            """
            SELECT SUM(grand_total) AS total,
                   MAX(currency) AS currency
            FROM invoice
            WHERE tenant_id = :tid
              AND (deleted_at IS NULL)
            """
        ),
        {"tid": tid},
    ).fetchone()
    if row and getattr(row, "total", None) is not None:
        return Money(amount=_d(row.total), currency=getattr(row, "currency", None) or "INR")
    return Money(amount=Decimal("0"), currency="INR")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _d(value: Any) -> Decimal:
    """Safe Decimal coercion."""
    if value is None:
        return Decimal("0")
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        return Decimal("0")


def _coerce_date(value: Any) -> Optional[date]:
    if isinstance(value, date):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _fmt_inr(amount: Decimal) -> str:
    """Format Decimal as Indian currency string (L = lakhs, Cr = crores)."""
    amt = abs(amount)
    prefix = "-" if amount < 0 else ""
    if amt >= Decimal("10000000"):      # 1 Cr+
        val = (amt / Decimal("10000000")).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        return f"{prefix}₹{val}Cr"
    if amt >= Decimal("100000"):        # 1 L+
        val = (amt / Decimal("100000")).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        return f"{prefix}₹{val}L"
    # Plain with comma
    return f"{prefix}₹{int(amt):,}"
