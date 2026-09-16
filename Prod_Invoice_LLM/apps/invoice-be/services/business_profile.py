"""Feature 33 Task 33.22 — Business Profile Discovery.

WHAT THIS MODULE DOES
---------------------
Discovers a deterministic BusinessProfile of the tenant from facts and records on file.
Pure function over DB rows — no LLM call authoring figures.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Union
from uuid import UUID

from sqlmodel import Session, select
import sqlalchemy as sa

from models import Fact, Invoice, ChatAttachment
from services.clearance import clearance_filter
from services.dependency import Coverage, coverage_for

logger = logging.getLogger(__name__)


@dataclass
class BusinessProfile:
    """The discovered profile of a tenant's business operations."""
    doc_types: dict[str, int] = field(default_factory=dict)
    vendor_clusters: list[dict] = field(default_factory=list)
    customer_clusters: list[dict] = field(default_factory=list)
    currencies: list[str] = field(default_factory=list)
    tax_regimes: list[str] = field(default_factory=list)
    fields_consistent: dict[str, list[str]] = field(default_factory=dict)
    payment_habits: dict[str, int] = field(default_factory=dict)
    doc_chains: list[str] = field(default_factory=list)
    coverage: Optional[Coverage] = None
    total_invoices_seen: int = 0
    total_attachments_seen: int = 0


def profile_tenant(
    tenant_id: Union[str, UUID],
    clearance: str = "ops",
    db_session: Optional[Session] = None,
) -> BusinessProfile:
    """Compute deterministic BusinessProfile for the given tenant."""
    tenant_str = str(tenant_id)
    t_uuid = UUID(tenant_str)
    profile = BusinessProfile()

    if db_session is None:
        return profile

    profile.coverage = coverage_for(t_uuid, clearance, db_session)

    # 1. Invoices scan
    inv_stmt = select(Invoice).where(
        Invoice.tenant_id == t_uuid,
        Invoice.deleted_at == None,  # noqa: E711
    )
    inv_stmt = clearance_filter(inv_stmt, Invoice, clearance)
    invoices = db_session.exec(inv_stmt).all()
    profile.total_invoices_seen = len(invoices)

    doc_types: dict[str, int] = {}
    currencies: set[str] = set()
    vendors: dict[str, int] = {}
    customers: dict[str, int] = {}

    for inv in invoices:
        curr = inv.currency or "INR"
        currencies.add(curr)
        is_out = getattr(inv, "direction", "inbound") == "outbound"
        d_type = "INVOICE_OUT" if is_out else "INVOICE_IN"
        doc_types[d_type] = doc_types.get(d_type, 0) + 1

        if is_out and inv.customer_name:
            customers[inv.customer_name] = customers.get(inv.customer_name, 0) + 1
        elif not is_out and inv.vendor_name:
            vendors[inv.vendor_name] = vendors.get(inv.vendor_name, 0) + 1

    # 2. Attachments scan
    att_stmt = select(ChatAttachment).where(
        ChatAttachment.tenant_id == t_uuid,
    )
    att_stmt = clearance_filter(att_stmt, ChatAttachment, clearance)
    attachments = db_session.exec(att_stmt).all()
    profile.total_attachments_seen = len(attachments)

    for att in attachments:
        dtype = (att.doc_type or "OTHER").upper()
        doc_types[dtype] = doc_types.get(dtype, 0) + 1
        if att.currency:
            currencies.add(att.currency)

    profile.doc_types = doc_types
    profile.currencies = sorted(list(currencies)) or ["INR"]

    # 3. Vendor & customer clusters
    profile.vendor_clusters = [
        {"name": name, "invoice_count": cnt}
        for name, cnt in sorted(vendors.items(), key=lambda x: -x[1])[:10]
    ]
    profile.customer_clusters = [
        {"name": name, "invoice_count": cnt}
        for name, cnt in sorted(customers.items(), key=lambda x: -x[1])[:10]
    ]

    # 4. Tax Regimes (infer from country/region/tax fields)
    tax_regimes = set()
    for inv in invoices[:20]:
        if getattr(inv, "gstin", None) or getattr(inv, "vendor_gstin", None):
            tax_regimes.add("GST_IN")
        if getattr(inv, "vat_number", None):
            tax_regimes.add("VAT_EU")
    profile.tax_regimes = sorted(list(tax_regimes)) if tax_regimes else ["GST_IN"]

    # 5. Doc Chains
    chains = []
    if "PURCHASE_ORDER" in doc_types and "INVOICE_IN" in doc_types:
        chains.append("PO -> Invoice")
    if "DELIVERY_NOTE" in doc_types or "CHALLAN" in doc_types:
        chains.append("Delivery -> Invoice")
    if "BANK_STATEMENT" in doc_types:
        chains.append("Invoice -> Payment Reconcile")
    profile.doc_chains = chains

    return profile
