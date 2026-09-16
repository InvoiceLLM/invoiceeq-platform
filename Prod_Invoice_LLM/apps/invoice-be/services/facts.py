"""Feature 33 (ATLAS Analyst Agent) — The Facts Ledger.

Task 33.8: Fact model, FACT_EMITTERS by shape, emit_facts(), facts_for().

WHY THIS MODULE EXISTS
----------------------
Documents are channels; facts are the ledger.
Chat attachment becomes one entry channel like email-in and the connector;
the channel no longer decides the lifetime.

Critical Lifecycle Rule:
- TTL sweeper deletes chat_attachments rows; DB foreign key is ON DELETE SET NULL,
  preserving Fact rows with source_id=None.
- User hard-delete explicitly invokes `delete_facts_for_source(source_id, session)`
  within the same DB transaction to wipe associated facts for compliance/privacy.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Callable, Dict, List, Optional, Sequence
from uuid import UUID, uuid4

from sqlmodel import Session, select, delete
import sqlalchemy as sa

from models import Fact, ChatAttachment

logger = logging.getLogger(__name__)


def _to_date(value: Any) -> Optional[date]:
    """Parse date or return None."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d %b %Y", "%d-%b-%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(text[: len(fmt) + 4], fmt).date()
        except ValueError:
            continue
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _to_float(value: Any) -> Optional[float]:
    """Parse float or return None."""
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


# =============================================================================
# Fact Emitters by Shape
# =============================================================================

def emit_commitment(
    attachment_row: Optional[ChatAttachment],
    extracted_json: dict,
    overlap: Optional[dict] = None,
) -> list[Fact]:
    """Doc has agreed lines + counterparty -> PO / contract / quotation facts."""
    facts: list[Fact] = []
    tenant_id = attachment_row.tenant_id if attachment_row else extracted_json.get("tenant_id")
    if not tenant_id:
        return facts
    
    clearance = getattr(attachment_row, "clearance", "ops") if attachment_row else "ops"
    source_id = attachment_row.id if attachment_row else None
    source_kind = "chat_attachment" if attachment_row else extracted_json.get("source_kind", "chat_attachment")
    
    doc_type = (extracted_json.get("doc_type") or (attachment_row.doc_type if attachment_row else "OTHER")).upper()
    doc_number = extracted_json.get("doc_number") or (attachment_row.doc_number if attachment_row else None) or "UNKNOWN"
    party_name = extracted_json.get("party_name") or extracted_json.get("vendor_name") or extracted_json.get("customer_name") or (attachment_row.party_name if attachment_row else None)
    doc_date = _to_date(extracted_json.get("doc_date") or (attachment_row.doc_date if attachment_row else None))
    currency = extracted_json.get("currency") or (attachment_row.currency if attachment_row else "INR")
    grand_total = _to_float(extracted_json.get("grand_total") or (attachment_row.grand_total if attachment_row else None))
    
    # Check if doc has commitment shape: PO, Quotation, Contract, Proforma, or has agreed lines
    line_items = extracted_json.get("line_items") or extracted_json.get("lines") or []
    is_commitment_type = doc_type in ("PURCHASE_ORDER", "PO", "QUOTATION", "QUOTE", "CONTRACT", "PROFORMA", "ORDER_CONFIRMATION")
    
    if is_commitment_type or (line_items and grand_total is not None):
        figures = {
            "total_amount": grand_total,
            "currency": currency,
            "line_count": len(line_items),
            "lines": [
                {
                    "item_name": item.get("item_name") or item.get("description") or "Item",
                    "quantity": _to_float(item.get("quantity") or item.get("qty")),
                    "unit_price": _to_float(item.get("unit_price") or item.get("rate")),
                    "total_amount": _to_float(item.get("total_amount") or item.get("amount")),
                }
                for item in line_items if isinstance(item, dict)
            ]
        }
        evidence = {
            "doc_type": doc_type,
            "doc_number": doc_number,
            "party_name": party_name,
            "doc_date": str(doc_date) if doc_date else None,
        }
        
        subject_kind = "po" if "PO" in doc_type or "PURCHASE" in doc_type else ("contract" if "CONTRACT" in doc_type else "quotation")
        
        fact = Fact(
            id=uuid4(),
            tenant_id=tenant_id,
            clearance=clearance,
            kind="commitment",
            subject_kind=subject_kind,
            subject_id=str(doc_number),
            counterparty_id=str(party_name) if party_name else None,
            as_of=doc_date,
            figures=figures,
            source_kind=source_kind,
            source_id=source_id,
            evidence=evidence,
            created_at=datetime.utcnow(),
        )
        facts.append(fact)

    return facts


def emit_delivery_event(
    attachment_row: Optional[ChatAttachment],
    extracted_json: dict,
    overlap: Optional[dict] = None,
) -> list[Fact]:
    """Doc has delivered quantities -> delivery / challan / receipt facts."""
    facts: list[Fact] = []
    tenant_id = attachment_row.tenant_id if attachment_row else extracted_json.get("tenant_id")
    if not tenant_id:
        return facts
    
    clearance = getattr(attachment_row, "clearance", "ops") if attachment_row else "ops"
    source_id = attachment_row.id if attachment_row else None
    source_kind = "chat_attachment" if attachment_row else extracted_json.get("source_kind", "chat_attachment")
    
    doc_type = (extracted_json.get("doc_type") or (attachment_row.doc_type if attachment_row else "OTHER")).upper()
    doc_number = extracted_json.get("doc_number") or (attachment_row.doc_number if attachment_row else None) or "UNKNOWN"
    party_name = extracted_json.get("party_name") or extracted_json.get("vendor_name") or (attachment_row.party_name if attachment_row else None)
    doc_date = _to_date(extracted_json.get("delivery_date") or extracted_json.get("doc_date") or (attachment_row.doc_date if attachment_row else None))
    
    line_items = extracted_json.get("delivery_lines") or extracted_json.get("line_items") or extracted_json.get("lines") or []
    is_delivery_type = doc_type in ("DELIVERY_NOTE", "DELIVERY_CHALLAN", "CHALLAN", "GOODS_RECEIPT", "GRN", "PACKING_SLIP")
    
    if is_delivery_type or "delivery" in doc_type.lower() or "challan" in doc_type.lower():
        delivered_lines = []
        total_delivered_qty = 0.0
        for item in line_items:
            if isinstance(item, dict):
                qty = _to_float(item.get("delivered_quantity") or item.get("quantity") or item.get("qty")) or 0.0
                total_delivered_qty += qty
                delivered_lines.append({
                    "item_name": item.get("item_name") or item.get("description") or "Item",
                    "delivered_qty": qty,
                    "po_reference": item.get("po_reference") or item.get("po_number"),
                })
        
        figures = {
            "total_delivered_qty": total_delivered_qty,
            "line_count": len(delivered_lines),
            "lines": delivered_lines,
        }
        evidence = {
            "doc_type": doc_type,
            "doc_number": doc_number,
            "party_name": party_name,
            "delivery_date": str(doc_date) if doc_date else None,
            "po_reference": extracted_json.get("po_reference") or extracted_json.get("po_number"),
        }
        
        fact = Fact(
            id=uuid4(),
            tenant_id=tenant_id,
            clearance=clearance,
            kind="delivery_event",
            subject_kind="delivery_note",
            subject_id=str(doc_number),
            counterparty_id=str(party_name) if party_name else None,
            as_of=doc_date,
            figures=figures,
            source_kind=source_kind,
            source_id=source_id,
            evidence=evidence,
            created_at=datetime.utcnow(),
        )
        facts.append(fact)

    return facts


def emit_payment_event(
    attachment_row: Optional[ChatAttachment],
    extracted_json: dict,
    overlap: Optional[dict] = None,
) -> list[Fact]:
    """Doc has settled invoice ref / UTR / bank line match -> payment facts."""
    facts: list[Fact] = []
    tenant_id = attachment_row.tenant_id if attachment_row else extracted_json.get("tenant_id")
    if not tenant_id:
        return facts
    
    doc_type = (extracted_json.get("doc_type") or (attachment_row.doc_type if attachment_row else "OTHER")).upper()
    source_id = attachment_row.id if attachment_row else None
    source_kind = "chat_attachment" if attachment_row else extracted_json.get("source_kind", "chat_attachment")
    attachment_clearance = getattr(attachment_row, "clearance", "ops") if attachment_row else "ops"
    
    # Process bank statement lines or payment references
    statement_lines = extracted_json.get("statement_lines") or extracted_json.get("bank_lines") or []
    if not statement_lines and doc_type in ("BANK_STATEMENT", "STATEMENT"):
        statement_lines = extracted_json.get("referenced_documents") or []

    for raw in statement_lines:
        if not isinstance(raw, dict):
            continue
        debit = _to_float(raw.get("debit"))
        credit = _to_float(raw.get("credit"))
        amount = debit if debit is not None else (_to_float(raw.get("amount")) or credit)
        if amount is None:
            continue
        
        line_date = _to_date(raw.get("line_date") or raw.get("date") or raw.get("doc_date"))
        narration = raw.get("narration") or raw.get("description") or raw.get("doc_number")
        utr = raw.get("utr_ref") or raw.get("utr") or raw.get("reference_number")
        matched_invoice_id = raw.get("matched_invoice_id") or raw.get("invoice_id")
        counterparty = raw.get("counterparty") or raw.get("party_name") or narration
        
        # Option C clearance rule:
        # A payment fact linked to an invoice that ops can see flows down as "ops"
        # Non-invoice lines (salary, loan, etc.) inherit the attachment's clearance
        fact_clearance = "ops" if matched_invoice_id else attachment_clearance

        subject_kind = "invoice" if matched_invoice_id else "bank_transaction"
        subject_id = str(matched_invoice_id) if matched_invoice_id else (str(utr) if utr else f"tx_{uuid4().hex[:8]}")

        figures = {
            "amount": amount,
            "currency": extracted_json.get("currency") or "INR",
            "debit": debit,
            "credit": credit,
            "balance": _to_float(raw.get("balance")),
        }
        evidence = {
            "narration": narration,
            "utr": utr,
            "line_date": str(line_date) if line_date else None,
            "matched_invoice_id": str(matched_invoice_id) if matched_invoice_id else None,
            "match_status": raw.get("match_status"),
        }

        fact = Fact(
            id=uuid4(),
            tenant_id=tenant_id,
            clearance=fact_clearance,
            kind="payment_event",
            subject_kind=subject_kind,
            subject_id=subject_id,
            counterparty_id=str(counterparty) if counterparty else None,
            as_of=line_date,
            figures=figures,
            source_kind=source_kind,
            source_id=source_id,
            evidence=evidence,
            created_at=datetime.utcnow(),
        )
        facts.append(fact)

    return facts


def emit_terms(
    attachment_row: Optional[ChatAttachment],
    extracted_json: dict,
    overlap: Optional[dict] = None,
) -> list[Fact]:
    """Doc has rates / payment terms + effective period -> terms facts."""
    facts: list[Fact] = []
    tenant_id = attachment_row.tenant_id if attachment_row else extracted_json.get("tenant_id")
    if not tenant_id:
        return facts
    
    clearance = getattr(attachment_row, "clearance", "ops") if attachment_row else "ops"
    source_id = attachment_row.id if attachment_row else None
    source_kind = "chat_attachment" if attachment_row else extracted_json.get("source_kind", "chat_attachment")
    
    doc_number = extracted_json.get("doc_number") or (attachment_row.doc_number if attachment_row else None) or "UNKNOWN"
    party_name = extracted_json.get("party_name") or extracted_json.get("vendor_name") or (attachment_row.party_name if attachment_row else None)
    doc_date = _to_date(extracted_json.get("doc_date") or (attachment_row.doc_date if attachment_row else None))
    
    payment_terms = extracted_json.get("payment_terms") or extracted_json.get("terms")
    terms_days = extracted_json.get("payment_terms_days") or extracted_json.get("due_days")
    discount_pct = _to_float(extracted_json.get("discount_pct") or extracted_json.get("early_payment_discount"))
    
    if payment_terms or terms_days is not None or discount_pct is not None:
        figures = {
            "payment_terms_raw": str(payment_terms) if payment_terms else None,
            "payment_terms_days": int(terms_days) if terms_days is not None else None,
            "discount_pct": discount_pct,
        }
        evidence = {
            "doc_number": doc_number,
            "party_name": party_name,
            "effective_date": str(doc_date) if doc_date else None,
        }
        
        fact = Fact(
            id=uuid4(),
            tenant_id=tenant_id,
            clearance=clearance,
            kind="terms",
            subject_kind="vendor" if party_name else "contract",
            subject_id=str(party_name or doc_number),
            counterparty_id=str(party_name) if party_name else None,
            as_of=doc_date,
            figures=figures,
            source_kind=source_kind,
            source_id=source_id,
            evidence=evidence,
            created_at=datetime.utcnow(),
        )
        facts.append(fact)

    return facts


def emit_period_accounts(
    attachment_row: Optional[ChatAttachment],
    extracted_json: dict,
    overlap: Optional[dict] = None,
) -> list[Fact]:
    """Doc has periodised account table -> P&L / trial balance facts."""
    facts: list[Fact] = []
    tenant_id = attachment_row.tenant_id if attachment_row else extracted_json.get("tenant_id")
    if not tenant_id:
        return facts
    
    clearance = getattr(attachment_row, "clearance", "exec") if attachment_row else "exec"
    source_id = attachment_row.id if attachment_row else None
    source_kind = "chat_attachment" if attachment_row else extracted_json.get("source_kind", "chat_attachment")
    
    accounts = extracted_json.get("period_accounts") or extracted_json.get("accounts") or extracted_json.get("pnl_accounts") or []
    period_end = _to_date(extracted_json.get("period_end") or extracted_json.get("doc_date") or (attachment_row.doc_date if attachment_row else None))
    period_label = extracted_json.get("period_label") or extracted_json.get("period") or "Current"
    currency = extracted_json.get("currency") or "INR"
    
    for item in accounts:
        if not isinstance(item, dict):
            continue
        account_name = item.get("account_name") or item.get("name") or item.get("category")
        if not account_name:
            continue
        
        revenue = _to_float(item.get("revenue") or item.get("income"))
        expense = _to_float(item.get("expense") or item.get("cost"))
        net = _to_float(item.get("net_amount") or item.get("net"))
        
        figures = {
            "period": period_label,
            "currency": currency,
            "revenue": revenue,
            "expense": expense,
            "net": net,
        }
        evidence = {
            "account_code": item.get("account_code"),
            "category": item.get("category"),
            "period_end": str(period_end) if period_end else None,
        }
        
        fact = Fact(
            id=uuid4(),
            tenant_id=tenant_id,
            clearance=clearance,
            kind="period_accounts",
            subject_kind="account",
            subject_id=str(account_name),
            counterparty_id=None,
            as_of=period_end,
            figures=figures,
            source_kind=source_kind,
            source_id=source_id,
            evidence=evidence,
            created_at=datetime.utcnow(),
        )
        facts.append(fact)

    return facts


def emit_budget(
    attachment_row: Optional[ChatAttachment],
    extracted_json: dict,
    overlap: Optional[dict] = None,
) -> list[Fact]:
    """Doc has planned amounts per account for future period -> budget facts."""
    facts: list[Fact] = []
    tenant_id = attachment_row.tenant_id if attachment_row else extracted_json.get("tenant_id")
    if not tenant_id:
        return facts
    
    clearance = getattr(attachment_row, "clearance", "exec") if attachment_row else "exec"
    source_id = attachment_row.id if attachment_row else None
    source_kind = "chat_attachment" if attachment_row else extracted_json.get("source_kind", "chat_attachment")
    
    budgets = extracted_json.get("budgets") or extracted_json.get("budget_items") or extracted_json.get("planned_accounts") or []
    period_start = _to_date(extracted_json.get("period_start") or extracted_json.get("doc_date"))
    period_label = extracted_json.get("period_label") or extracted_json.get("period") or "FY"
    currency = extracted_json.get("currency") or "INR"
    
    for item in budgets:
        if not isinstance(item, dict):
            continue
        account_name = item.get("account_name") or item.get("name") or item.get("category")
        amount = _to_float(item.get("budget_amount") or item.get("amount") or item.get("planned_amount"))
        if not account_name or amount is None:
            continue
        
        figures = {
            "budget_amount": amount,
            "period": period_label,
            "currency": currency,
        }
        evidence = {
            "account_code": item.get("account_code"),
            "category": item.get("category"),
            "period_start": str(period_start) if period_start else None,
        }
        
        fact = Fact(
            id=uuid4(),
            tenant_id=tenant_id,
            clearance=clearance,
            kind="budget",
            subject_kind="account",
            subject_id=str(account_name),
            counterparty_id=None,
            as_of=period_start,
            figures=figures,
            source_kind=source_kind,
            source_id=source_id,
            evidence=evidence,
            created_at=datetime.utcnow(),
        )
        facts.append(fact)

    return facts


FACT_EMITTERS: Dict[str, Callable[[Optional[ChatAttachment], dict, Optional[dict]], list[Fact]]] = {
    "emit_commitment": emit_commitment,
    "emit_delivery_event": emit_delivery_event,
    "emit_payment_event": emit_payment_event,
    "emit_terms": emit_terms,
    "emit_period_accounts": emit_period_accounts,
    "emit_budget": emit_budget,
}


# =============================================================================
# Pipeline Methods: emit_facts, facts_for, delete_facts_for_source
# =============================================================================

def emit_facts(
    attachment_row: Optional[ChatAttachment],
    extracted_json: Optional[dict] = None,
    overlap: Optional[dict] = None,
    db_session: Optional[Session] = None,
) -> list[Fact]:
    """Extract and persist facts from document extracted_json across all shape emitters.

    Idempotent: If db_session and attachment_row are provided, existing facts for
    that attachment are replaced.
    """
    data = extracted_json or (attachment_row.extracted_json if attachment_row else {}) or {}
    all_facts: list[Fact] = []

    for emitter_name, emitter_fn in FACT_EMITTERS.items():
        try:
            emitted = emitter_fn(attachment_row, data, overlap)
            if emitted:
                all_facts.extend(emitted)
        except Exception as exc:
            logger.warning("Fact emitter %s failed: %s", emitter_name, exc)

    if db_session and attachment_row and attachment_row.id:
        # Idempotence: clean previous facts for this source
        delete_facts_for_source(attachment_row.id, db_session)
        for fact in all_facts:
            db_session.add(fact)
        db_session.flush()

    return all_facts


def facts_for(
    subject_kind: str,
    subject_id: str,
    clearance: str = "ops",
    db_session: Optional[Session] = None,
    tenant_id: Optional[UUID] = None,
) -> list[Fact]:
    """Retrieve facts filtered by subject and clearance."""
    if db_session is None:
        return []

    stmt = select(Fact).where(
        Fact.subject_kind == subject_kind,
        Fact.subject_id == subject_id,
    )
    if tenant_id:
        stmt = stmt.where(Fact.tenant_id == tenant_id)

    # Clearance gate:
    # "ops" clearance only sees "ops" facts.
    # "exec" clearance sees both "ops" and "exec" facts.
    if clearance != "exec":
        stmt = stmt.where(Fact.clearance == "ops")

    return list(db_session.exec(stmt).all())


def delete_facts_for_source(source_id: UUID, db_session: Session) -> int:
    """User hard-delete explicit cleanup helper.

    Wipes all facts linked to source_id within the current transaction.
    """
    stmt = delete(Fact).where(Fact.source_id == source_id)
    res = db_session.exec(stmt)
    return getattr(res, "rowcount", 0)
