"""Feature 33 Task 33.2 — Overlap / Resolve-First Gate.

Before ATLAS runs any card, it checks whether the document resolves against
anything already on file.  A document that resolves to *nothing* gets a single
bubble: "I read this, but nothing matches your vendors, invoices or items."
The loop still completes; it just produces no findings beyond that one line.

This module is the authoritative resolver.  It is the replacement for the old
``is_insight_doc_type()`` type-based dispatch: the question is no longer "is
this a PO-type?" but "does this PO match *anything* on file?"

RESOLUTION DIMENSIONS (spec §33.2, Table 2)
-------------------------------------------
| Dimension            | Resolves against                          | Enables                        |
|----------------------|-------------------------------------------|--------------------------------|
| Party names          | Vendor/customer strings on invoice rows   | Every counterparty card        |
| Document numbers     | Invoice numbers, PO refs, prior att facts | Agreed-vs-billed, delivery, payment |
| Line descriptions    | Line items on invoices of same party      | Price drift, quantity checks   |
| Tax IDs (GSTIN/VAT)  | Region service (services/region.py)       | Compliance rule cards          |
| Amounts + dates      | Bank ledger lines in statement facts      | Reconcile                      |
| Rates/terms + period | Contract facts                            | Terms deviation                |
| Periodised accounts  | Shape only (columns presence)             | P&L emit_period_accounts       |

ENTITY-BASED, NEVER SIMILARITY-BASED
--------------------------------------
Resolution is exact or normalised-exact (lowercased, stripped of punctuation).
The system does NOT use embedding similarity to connect entity names — a fuzzy
"might be the same vendor" match is not a resolved entity.  If the name in the
document does not match a name on file after normalisation, the party dimension
is unresolved.  A document resolving to nothing is a valid, correct outcome.

RULE: EMPTY GRAPH IS NOT AN ERROR
-----------------------------------
``resolve_overlap()`` returns an ``OverlapGraph`` with all dimensions empty
when nothing matches.  Callers check ``graph.has_any()`` and produce the
"nothing matches" bubble.  They never raise an exception for an empty graph.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Optional
from uuid import UUID

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

_NON_ALNUM = re.compile(r"[^a-z0-9]")


def _norm(text: Optional[str]) -> str:
    """Lower-case, strip accents, collapse non-alphanumerics.

    Used for fuzzy-safe *exact* comparison: "Rajesh Steel Pvt." and
    "rajesh steel pvt" both normalise to "rajeshsteelpvt", so they match.
    Two strings that differ after normalisation are treated as different
    entities — no further similarity is applied.
    """
    if not text:
        return ""
    # NFD decomposition drops combining accent marks
    nfd = unicodedata.normalize("NFD", text)
    ascii_only = nfd.encode("ascii", "ignore").decode()
    return _NON_ALNUM.sub("", ascii_only.lower())


def _to_date(value: Any) -> Optional[date]:
    if isinstance(value, date):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y"):
            try:
                return datetime.strptime(value[:10], fmt).date()
            except ValueError:
                continue
    return None


def _to_decimal(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


# ---------------------------------------------------------------------------
# OverlapGraph
# ---------------------------------------------------------------------------


@dataclass
class PartyMatch:
    """A vendor or customer whose normalised name was found in the document."""

    party_name: str           # raw name as it appears in the document
    canonical_name: str       # the on-file name this matched
    invoice_ids: list[str] = field(default_factory=list)  # known invoice ids
    fact_ids: list[str] = field(default_factory=list)      # prior fact ids


@dataclass
class DocumentNumberMatch:
    """A document number in the extracted JSON that resolves to an on-file row."""

    number: str
    kind: str   # "invoice", "po", "attachment_fact"
    row_id: str


@dataclass
class LineItemMatch:
    """A line description that matches a line on a known invoice of the same party."""

    description: str          # normalised description from this document
    matched_description: str  # on-file description it matched
    invoice_id: str


@dataclass
class TaxIdMatch:
    """A tax ID found in the document with its resolved region."""

    tax_id: str
    region: str   # "IN", "EU", "US", or raw prefix


@dataclass
class BankLedgerMatch:
    """An amount + date pair that matches a bank statement fact line."""

    amount: Decimal
    currency: str
    tx_date: date
    fact_id: str


@dataclass
class ContractMatch:
    """Rate/payment terms that deviate from a prior contract fact."""

    fact_id: str
    contract_doc_number: str
    agreed_rate: Optional[Decimal]
    agreed_terms_days: Optional[int]


@dataclass
class OverlapGraph:
    """The full set of resolved entity dimensions for one document.

    All dimensions are lists; empty list = unresolved for that dimension.
    ``has_any()`` is the caller's gate: a graph with nothing resolved produces
    the "nothing matches your records" bubble.
    """

    parties: list[PartyMatch] = field(default_factory=list)
    doc_numbers: list[DocumentNumberMatch] = field(default_factory=list)
    line_items: list[LineItemMatch] = field(default_factory=list)
    tax_ids: list[TaxIdMatch] = field(default_factory=list)
    bank_ledger: list[BankLedgerMatch] = field(default_factory=list)
    contracts: list[ContractMatch] = field(default_factory=list)
    period_accounts_shape: bool = False   # True if shape looks like a P&L table

    def has_any(self) -> bool:
        """True if at least one dimension resolved to something."""
        return bool(
            self.parties
            or self.doc_numbers
            or self.line_items
            or self.tax_ids
            or self.bank_ledger
            or self.contracts
            or self.period_accounts_shape
        )

    def primary_party(self) -> Optional[PartyMatch]:
        """Return the first matched party, or None."""
        return self.parties[0] if self.parties else None

    def as_summary(self) -> dict:
        """Compact summary for logging and the observation block.

        Only sizes, not the full lists.
        """
        return {
            "parties": len(self.parties),
            "doc_numbers": len(self.doc_numbers),
            "line_items": len(self.line_items),
            "tax_ids": len(self.tax_ids),
            "bank_ledger_lines": len(self.bank_ledger),
            "contracts": len(self.contracts),
            "period_accounts_shape": self.period_accounts_shape,
        }


# ---------------------------------------------------------------------------
# Main resolver
# ---------------------------------------------------------------------------


def resolve_overlap(
    extracted_json: dict,
    scope: str,
    db_session: Any,
    tenant_id: Any,
    clearance: str = "ops",
) -> OverlapGraph:
    """Resolve the document's entities against the tenant's data on file.

    Parameters
    ----------
    extracted_json:
        The dict produced by the extraction pipeline for this document.
    scope:
        The ATLAS loop scope: "attachment", "tenant", or "onboarding".
        Shape-only dimensions (``period_accounts_shape``) are always checked
        regardless of scope.
    db_session:
        Active SQLAlchemy session.
    tenant_id:
        The tenant UUID.
    clearance:
        The calling user's clearance level ("ops" or "exec").  Only facts the
        user can see are included in the graph.

    Returns
    -------
    OverlapGraph
        All resolved dimensions.  May be fully empty — that is a valid result.
    """
    graph = OverlapGraph()

    data = extracted_json or {}

    try:
        graph.parties = _resolve_parties(data, tenant_id, db_session)
    except Exception as exc:
        logger.warning("resolve_overlap: party resolution failed: %s", exc)

    try:
        graph.doc_numbers = _resolve_doc_numbers(data, tenant_id, db_session)
    except Exception as exc:
        logger.warning("resolve_overlap: doc number resolution failed: %s", exc)

    try:
        graph.line_items = _resolve_line_items(data, graph.parties, tenant_id, db_session)
    except Exception as exc:
        logger.warning("resolve_overlap: line item resolution failed: %s", exc)

    try:
        graph.tax_ids = _resolve_tax_ids(data)
    except Exception as exc:
        logger.warning("resolve_overlap: tax id resolution failed: %s", exc)

    if clearance == "exec":
        # Bank ledger and contract dimensions are exec-clearance only.
        try:
            graph.bank_ledger = _resolve_bank_ledger(data, tenant_id, db_session)
        except Exception as exc:
            logger.warning("resolve_overlap: bank ledger resolution failed: %s", exc)

        try:
            graph.contracts = _resolve_contracts(data, graph.parties, tenant_id, db_session, clearance)
        except Exception as exc:
            logger.warning("resolve_overlap: contract resolution failed: %s", exc)

    try:
        graph.period_accounts_shape = _detect_period_accounts_shape(data)
    except Exception as exc:
        logger.warning("resolve_overlap: period accounts shape failed: %s", exc)

    logger.info(
        "resolve_overlap: tenant=%s scope=%s result=%s",
        tenant_id,
        scope,
        graph.as_summary(),
    )
    return graph


# ---------------------------------------------------------------------------
# Dimension resolvers (private)
# ---------------------------------------------------------------------------


def _party_names_from_json(data: dict) -> list[str]:
    """Extract all candidate party-name strings from the extracted JSON."""
    candidates: list[str] = []
    for key in (
        "party_name",
        "vendor_name",
        "customer_name",
        "supplier_name",
        "buyer_name",
        "seller_name",
        "payee_name",
        "payer_name",
        "bank_name",
        "entity_name",
        "company_name",
        "organization_name",
    ):
        val = data.get(key)
        if val and isinstance(val, str) and val.strip():
            candidates.append(val.strip())
    return candidates


def _resolve_parties(
    data: dict, tenant_id: Any, db_session: Any
) -> list[PartyMatch]:
    """Resolve party names against distinct counterparty strings on invoice rows.

    Strategy:
    1. Collect all party-name candidates from the document.
    2. Query the DISTINCT set of (vendor_name, invoice_id) pairs for this tenant.
    3. For each candidate, check if its normalised form matches any on-file name.

    The DB query is a plain text scan; no embedding is used.  A name that does
    not match after normalisation is not a match.
    """
    candidates = _party_names_from_json(data)
    if not candidates:
        return []

    # Normalised candidates for O(1) lookup
    norm_candidates: dict[str, str] = {_norm(c): c for c in candidates}
    if not norm_candidates:
        return []

    try:
        from sqlmodel import select  # noqa: PLC0415
        from models import Invoice  # noqa: PLC0415

        tid = tenant_id if isinstance(tenant_id, UUID) else UUID(str(tenant_id))

        stmt = select(Invoice.vendor_name, Invoice.customer_name, Invoice.id).where(
            Invoice.tenant_id == tid,
            Invoice.deleted_at.is_(None),
        )
        rows = db_session.exec(stmt).all()
    except Exception as exc:
        logger.warning("_resolve_parties: DB query failed: %s", exc)
        return []

    # Build a map: normalised_on_file → (canonical_name, [invoice_ids])
    on_file: dict[str, tuple[str, list[str]]] = {}
    for vendor_name, customer_name, inv_id in rows:
        if vendor_name and vendor_name.strip():
            n = _norm(vendor_name)
            if n not in on_file:
                on_file[n] = (vendor_name, [])
            on_file[n][1].append(str(inv_id))
        if customer_name and customer_name.strip():
            n = _norm(customer_name)
            if n not in on_file:
                on_file[n] = (customer_name, [])
            on_file[n][1].append(str(inv_id))

    matches: list[PartyMatch] = []
    seen: set[str] = set()
    for norm_candidate, raw_candidate in norm_candidates.items():
        if norm_candidate in on_file and norm_candidate not in seen:
            canonical, inv_ids = on_file[norm_candidate]
            matches.append(
                PartyMatch(
                    party_name=raw_candidate,
                    canonical_name=canonical,
                    invoice_ids=list(dict.fromkeys(inv_ids)),  # dedupe, order-preserving
                )
            )
            seen.add(norm_candidate)

    return matches


def _doc_number_candidates(data: dict) -> list[str]:
    """Extract document number candidates from the extracted JSON."""
    nums: list[str] = []
    for key in (
        "doc_number",
        "invoice_number",
        "po_number",
        "po_reference",
        "delivery_note_number",
        "challan_number",
        "grn_number",
        "order_number",
        "contract_number",
        "remittance_reference",
        "credit_note_number",
        "debit_note_number",
        "dc_number",
        "statement_number",
        "account_number",
        "loan_account",
        "fiscal_year",
        "period",
        "return_type",
    ):
        val = data.get(key)
        if val and isinstance(val, str) and val.strip():
            nums.append(val.strip())
    return nums


def _resolve_doc_numbers(
    data: dict, tenant_id: Any, db_session: Any
) -> list[DocumentNumberMatch]:
    """Match document numbers against invoice rows and prior attachment facts."""
    candidates = _doc_number_candidates(data)
    if not candidates:
        return []

    norm_candidates = {_norm(c): c for c in candidates}

    matches: list[DocumentNumberMatch] = []
    try:
        from sqlmodel import select  # noqa: PLC0415
        from models import Invoice  # noqa: PLC0415

        tid = tenant_id if isinstance(tenant_id, UUID) else UUID(str(tenant_id))

        stmt = select(Invoice.invoice_number, Invoice.po_number, Invoice.id).where(
            Invoice.tenant_id == tid,
            Invoice.deleted_at.is_(None),
        )
        rows = db_session.exec(stmt).all()

        for inv_number, po_num, inv_id in rows:
            if inv_number:
                n = _norm(str(inv_number))
                if n in norm_candidates:
                    matches.append(
                        DocumentNumberMatch(
                            number=norm_candidates[n],
                            kind="invoice",
                            row_id=str(inv_id),
                        )
                    )
            if po_num:
                n = _norm(str(po_num))
                if n in norm_candidates:
                    matches.append(
                        DocumentNumberMatch(
                            number=norm_candidates[n],
                            kind="po",
                            row_id=str(inv_id),
                        )
                    )
    except Exception as exc:
        logger.warning("_resolve_doc_numbers: invoice query failed: %s", exc)

    # Check prior attachment facts (fact.subject_id carries the doc number)
    try:
        from sqlmodel import select  # noqa: PLC0415
        from models import Fact  # noqa: PLC0415

        tid = tenant_id if isinstance(tenant_id, UUID) else UUID(str(tenant_id))

        stmt = select(Fact.subject_id, Fact.id).where(
            Fact.tenant_id == tid,
            Fact.subject_kind.in_(["invoice", "po", "delivery", "contract"]),
        )
        fact_rows = db_session.exec(stmt).all()

        for subj_id, fact_id in fact_rows:
            n = _norm(str(subj_id))
            if n in norm_candidates:
                matches.append(
                    DocumentNumberMatch(
                        number=norm_candidates[n],
                        kind="attachment_fact",
                        row_id=str(fact_id),
                    )
                )
    except Exception as exc:
        logger.warning("_resolve_doc_numbers: fact query failed: %s", exc)

    return matches


def _resolve_line_items(
    data: dict,
    matched_parties: list[PartyMatch],
    tenant_id: Any,
    db_session: Any,
) -> list[LineItemMatch]:
    """Match line descriptions against line items on known invoices of the same party.

    Only runs if at least one party resolved, to bound the query.
    """
    if not matched_parties:
        return []

    raw_lines = (
        data.get("line_items")
        or data.get("lines")
        or data.get("delivery_lines")
        or data.get("items")
        or []
    )
    if not raw_lines:
        return []

    doc_descriptions: list[str] = []
    for li in raw_lines:
        if isinstance(li, dict):
            desc = li.get("description") or li.get("item_name") or li.get("name")
            if desc and isinstance(desc, str) and desc.strip():
                doc_descriptions.append(desc.strip())

    if not doc_descriptions:
        return []

    norm_descs: dict[str, str] = {_norm(d): d for d in doc_descriptions}
    invoice_ids = [iid for pm in matched_parties for iid in pm.invoice_ids]
    if not invoice_ids:
        return []

    # Limit to a reasonable number of invoice IDs to avoid huge IN clauses
    invoice_ids = invoice_ids[:100]

    try:
        import json  # noqa: PLC0415
        from sqlmodel import select  # noqa: PLC0415
        from models import Invoice  # noqa: PLC0415

        tid = tenant_id if isinstance(tenant_id, UUID) else UUID(str(tenant_id))

        stmt = select(Invoice.id, Invoice.items).where(
            Invoice.tenant_id == tid,
            Invoice.deleted_at.is_(None),
        )
        rows = db_session.exec(stmt).all()

        target_ids = {str(i) for i in invoice_ids}
        rows = [(inv_id, items) for inv_id, items in rows if str(inv_id) in target_ids]
    except Exception as exc:
        logger.warning("_resolve_line_items: DB query failed: %s", exc)
        return []

    matches: list[LineItemMatch] = []
    seen: set[tuple[str, str]] = set()
    for inv_id, raw_items in rows:
        if isinstance(raw_items, str):
            try:
                raw_items = json.loads(raw_items)
            except Exception:
                raw_items = []
        if not isinstance(raw_items, list):
            continue
        for li in raw_items:
            if not isinstance(li, dict):
                continue
            desc = li.get("description") or li.get("item_name") or li.get("name")
            if not desc or not isinstance(desc, str):
                continue
            n = _norm(desc)
            if n in norm_descs:
                key = (n, str(inv_id))
                if key not in seen:
                    matches.append(
                        LineItemMatch(
                            description=norm_descs[n],
                            matched_description=desc,
                            invoice_id=str(inv_id),
                        )
                    )
                    seen.add(key)

    return matches


def _resolve_tax_ids(data: dict) -> list[TaxIdMatch]:
    """Extract tax IDs and determine their region using services/region.py.

    Entity-based: the GSTIN / VAT regex patterns from region.py are authoritative.
    No model call.
    """
    from services.region import (  # noqa: PLC0415
        GSTIN_PATTERN,
        VAT_PATTERN,
        EIN_PATTERN,
        REGION_IN,
        REGION_EU,
        REGION_US,
    )

    matches: list[TaxIdMatch] = []
    seen: set[str] = set()

    def _check_str(text: str) -> None:
        if GSTIN_PATTERN.search(text):
            for m in GSTIN_PATTERN.finditer(text):
                gst = m.group()
                if gst not in seen:
                    matches.append(TaxIdMatch(tax_id=gst, region=REGION_IN))
                    seen.add(gst)
        vat_m = VAT_PATTERN.search(text)
        if vat_m and vat_m.group() not in seen:
            matches.append(TaxIdMatch(tax_id=vat_m.group(), region=REGION_EU))
            seen.add(vat_m.group())
        ein_m = EIN_PATTERN.search(text)
        if ein_m and ein_m.group() not in seen:
            matches.append(TaxIdMatch(tax_id=ein_m.group(), region=REGION_US))
            seen.add(ein_m.group())

    # Search in known tax-id fields first, then the whole flat JSON
    for key in ("tax_ids", "regional_ids", "gstin", "vat_number", "gst_number", "ein"):
        val = data.get(key)
        if isinstance(val, str):
            _check_str(val)
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, str):
                    _check_str(item)
                elif isinstance(item, dict):
                    for v in item.values():
                        if isinstance(v, str):
                            _check_str(v)

    # Fallback: scan all string values in the top-level dict
    if not matches:
        for v in data.values():
            if isinstance(v, str) and len(v) > 4:
                _check_str(v)

    return matches


def _resolve_bank_ledger(
    data: dict, tenant_id: Any, db_session: Any
) -> list[BankLedgerMatch]:
    """Match amount + date pairs from statement lines against payment facts.

    The document must be a BANK_STATEMENT type with statement_lines / bank_lines.
    Exec-clearance only (checked by caller).
    """
    lines = data.get("statement_lines") or data.get("transactions") or data.get("bank_lines") or []
    if not lines:
        return []

    matches: list[BankLedgerMatch] = []
    try:
        import json  # noqa: PLC0415
        from sqlmodel import select  # noqa: PLC0415
        from models import Fact  # noqa: PLC0415

        tid = tenant_id if isinstance(tenant_id, UUID) else UUID(str(tenant_id))

        stmt = select(Fact.id, Fact.figures, Fact.as_of).where(
            Fact.tenant_id == tid,
            Fact.kind == "payment_event",
            Fact.figures.is_not(None),
        )
        fact_rows = db_session.exec(stmt).all()

        # Build lookup: (amount_str, date_str) → fact_id
        fact_index: dict[tuple[str, str, str], str] = {}
        for fact_id, figures, as_of in fact_rows:
            figs = figures or {}
            if isinstance(figs, str):
                try:
                    figs = json.loads(figs)
                except Exception:
                    figs = {}
            amt = _to_decimal(figs.get("amount") or figs.get("settled_amount"))
            cur = figs.get("currency", "INR")
            dt = as_of
            if amt is not None and dt is not None:
                fact_index[(str(amt), str(dt), cur)] = str(fact_id)

        for line in lines:
            if not isinstance(line, dict):
                continue
            amt = _to_decimal(line.get("amount") or line.get("credit") or line.get("debit"))
            cur = line.get("currency", "INR")
            dt = _to_date(line.get("date") or line.get("tx_date") or line.get("value_date") or line.get("line_date"))
            if amt is None or dt is None:
                continue
            key = (str(amt), str(dt), cur)
            if key in fact_index:
                matches.append(
                    BankLedgerMatch(
                        amount=amt,
                        currency=cur,
                        tx_date=dt,
                        fact_id=fact_index[key],
                    )
                )
    except Exception as exc:
        logger.warning("_resolve_bank_ledger: failed: %s", exc)

    return matches


def _resolve_contracts(
    data: dict,
    matched_parties: list[PartyMatch],
    tenant_id: Any,
    db_session: Any,
    clearance: str,
) -> list[ContractMatch]:
    """Match rates/payment terms against prior contract facts for the same party.

    Returns a ``ContractMatch`` for each contract fact whose agreed terms deviate
    from what the document states.  An exact match is still returned (deviation
    can be zero) so the caller can see that a contract fact exists.
    """
    if not matched_parties:
        return []

    counterparty_ids = [pm.canonical_name for pm in matched_parties]

    doc_rate = _to_decimal(
        data.get("rate")
        or data.get("unit_price")
        or data.get("agreed_rate")
    )
    doc_terms_days: Optional[int] = None
    for key in ("payment_terms_days", "due_days", "net_days"):
        v = data.get(key)
        if v is not None:
            try:
                doc_terms_days = int(v)
                break
            except (TypeError, ValueError):
                pass

    if doc_rate is None and doc_terms_days is None:
        return []

    matches: list[ContractMatch] = []
    try:
        import json  # noqa: PLC0415
        from sqlmodel import select  # noqa: PLC0415
        from models import Fact  # noqa: PLC0415

        tid = tenant_id if isinstance(tenant_id, UUID) else UUID(str(tenant_id))

        stmt = select(Fact.id, Fact.subject_id, Fact.counterparty_id, Fact.figures).where(
            Fact.tenant_id == tid,
            Fact.kind == "terms",
            Fact.figures.is_not(None),
        )
        fact_rows = db_session.exec(stmt).all()

        counterparty_set = set(counterparty_ids)
        for fact_id, subject_id, counterparty_id, figures in fact_rows:
            if counterparty_id not in counterparty_set:
                continue
            figs = figures or {}
            if isinstance(figs, str):
                try:
                    figs = json.loads(figs)
                except Exception:
                    figs = {}
            agreed_rate = _to_decimal(figs.get("agreed_rate") or figs.get("rate"))
            agreed_terms = figs.get("payment_terms_days")
            if agreed_terms is not None:
                try:
                    agreed_terms = int(agreed_terms)
                except (TypeError, ValueError):
                    agreed_terms = None
            matches.append(
                ContractMatch(
                    fact_id=str(fact_id),
                    contract_doc_number=subject_id or "",
                    agreed_rate=agreed_rate,
                    agreed_terms_days=agreed_terms,
                )
            )
    except Exception as exc:
        logger.warning("_resolve_contracts: failed: %s", exc)

    return matches


def _detect_period_accounts_shape(data: dict) -> bool:
    """Return True if the document looks like a periodised P&L / account table.

    Shape detection only — no values are read.  This is what enables
    ``emit_period_accounts`` in the fact emitter.

    Triggers when: the extracted JSON has a list under one of the known keys,
    each element is a dict, and the elements collectively have ≥3 of the
    canonical P&L column names.
    """
    if data.get("doc_type") in ("BANK_STATEMENT", "STATEMENT_OF_ACCOUNT", "PERIOD_ACCOUNTS", "BUDGET", "LOAN_SCHEDULE", "GST_RETURN"):
        return True
    for key in ("period_accounts", "accounts", "pnl_accounts", "account_lines", "budget_by_account"):
        rows = data.get(key)
        if isinstance(rows, dict) and rows:
            return True
        if not isinstance(rows, list) or not rows:
            continue
        # Sample up to 5 rows
        sample = [r for r in rows[:5] if isinstance(r, dict)]
        if not sample:
            continue
        all_keys: set[str] = set()
        for r in sample:
            all_keys.update(r.keys())
        canonical_columns = {
            "account", "account_name", "amount", "debit", "credit",
            "period", "period_end", "category", "revenue", "expense",
        }
        if len(all_keys & canonical_columns) >= 3:
            return True
    return False
