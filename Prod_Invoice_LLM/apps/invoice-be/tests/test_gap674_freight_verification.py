"""Tests for BE Gap 674: Totals Math Verification with Freight and Additional Charges.

Verifies:
1. verify_totals_math accepts header freight and additional charges outside the line items table.
2. verify_totals_math does NOT double-count freight if already included in subtotal (Gap 31 dual-convention pattern).
3. Genuine math errors still fire tax_mismatch alert with charges noted in the message.
4. Schema declarations on InvoiceExtractionSchema and OutboundInvoiceExtractionSchema.
5. verify_node in extraction_agent integrates freight and additional charges.
6. correction_recheck accounts for freight and additional charges.
7. Postgres persistence of freight_amount and additional_charges columns on Invoice table.
"""
import uuid
import pytest
from sqlmodel import Session, select
from tests.pg_gap_fixtures import pg_engine, pg_only
from models import Invoice
from utils.verification_tools import verify_totals_math
from agents.extraction_agent import (
    InvoiceExtractionSchema,
    OutboundInvoiceExtractionSchema,
    ChargeItem,
    verify_node,
)
from utils.correction_recheck import MONEY_FIELDS, _math_alerts, snapshot_money_fields


def test_schema_includes_freight_and_additional_charges():
    """InvoiceExtractionSchema and OutboundInvoiceExtractionSchema declare freight and charges."""
    assert "freight_amount" in InvoiceExtractionSchema.model_fields
    assert "additional_charges" in InvoiceExtractionSchema.model_fields
    assert "freight_amount" in OutboundInvoiceExtractionSchema.model_fields
    assert "additional_charges" in OutboundInvoiceExtractionSchema.model_fields

    charge = ChargeItem(charge_type="freight", amount=15.50)
    assert charge.charge_type == "freight"
    assert charge.amount == 15.50


def test_verify_totals_math_with_header_freight():
    """Header freight printed outside the line-items table reconciles without alert."""
    # subtotal $100, tax $10, freight $15 -> grand total $125
    alert = verify_totals_math(
        subtotal=100.0,
        tax_amount=10.0,
        grand_total=125.0,
        freight_amount=15.0,
    )
    assert alert is None


def test_verify_totals_math_with_additional_charges_list():
    """Packing & Forwarding + Shipping in additional_charges reconciles without alert."""
    charges = [
        {"charge_type": "packing & forwarding", "amount": 5.0},
        {"charge_type": "shipping", "amount": 15.0},
    ]
    # subtotal $100, tax $10, charges $20 -> grand total $130
    alert = verify_totals_math(
        subtotal=100.0,
        tax_amount=10.0,
        grand_total=130.0,
        additional_charges=charges,
    )
    assert alert is None


def test_verify_totals_math_no_double_count_table_freight():
    """If freight was already in subtotal (line item), accepting either reading avoids false alert."""
    # Subtotal is $115 (already includes $15 freight line item), tax $10 -> grand total $125.
    # Extractor also extracts freight_amount=$15 from document notes/header.
    # verify_totals_math must accept candidate WITHOUT freight term so it doesn't fail.
    alert = verify_totals_math(
        subtotal=115.0,
        tax_amount=10.0,
        grand_total=125.0,
        freight_amount=15.0,
    )
    assert alert is None


def test_verify_totals_math_with_discount_and_freight():
    """Discounts (pre and post) work correctly alongside freight."""
    # Pre-discount: subtotal 100 - discount 10 + tax 9 + freight 15 = 114
    alert_pre = verify_totals_math(
        subtotal=100.0,
        tax_amount=9.0,
        grand_total=114.0,
        discount_amount=10.0,
        freight_amount=15.0,
    )
    assert alert_pre is None

    # Post-discount: subtotal 100 (net of discount) + tax 10 + freight 15 = 125
    alert_post = verify_totals_math(
        subtotal=100.0,
        tax_amount=10.0,
        grand_total=125.0,
        discount_amount=10.0,
        freight_amount=15.0,
    )
    assert alert_post is None


def test_verify_totals_math_genuine_mismatch_fires_alert():
    """Genuine arithmetic error still fires tax_mismatch alert and mentions charges."""
    alert = verify_totals_math(
        subtotal=100.0,
        tax_amount=10.0,
        grand_total=200.0,
        freight_amount=15.0,
    )
    assert alert is not None
    assert alert["type"] == "tax_mismatch"
    assert "Freight" in alert["message"] or "Charges" in alert["message"]
    assert "15.00" in alert["message"]


def test_verify_node_integrates_freight():
    """verify_node in extraction_agent runs verify_totals_math with freight from state."""
    state = {
        "extracted_data": {
            "subtotal": 100.0,
            "tax_amount": 10.0,
            "grand_total": 125.0,
            "freight_amount": 15.0,
            "items": [{"description": "Item 1", "amount": 100.0}],
        },
        "ocr_text": "Subtotal: 100.00 Tax: 10.00 Freight: 15.00 Grand Total: 125.00",
        "flow_direction": "INBOUND",
    }
    result = verify_node(state)
    alert_types = [a["type"] for a in result.get("alerts", [])]
    assert "tax_mismatch" not in alert_types


def test_correction_recheck_includes_freight():
    """correction_recheck recognizes freight in MONEY_FIELDS and _math_alerts."""
    assert "freight_amount" in MONEY_FIELDS
    assert "additional_charges" in MONEY_FIELDS

    values = {
        "items": [{"description": "Item", "amount": 100.0}],
        "subtotal": 100.0,
        "tax_amount": 10.0,
        "grand_total": 125.0,
        "discount_amount": None,
        "discount_percent": None,
        "freight_amount": 15.0,
        "additional_charges": [],
    }
    alerts = _math_alerts(values, tolerances={}, doc_type="INVOICE")
    math_alert_types = [a["type"] for a in alerts]
    assert "tax_mismatch" not in math_alert_types


@pg_only
def test_postgres_persistence_freight_and_additional_charges(pg_engine):
    """Postgres table persists freight_amount and additional_charges columns without error."""
    invoice_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    with Session(pg_engine) as session:
        invoice = Invoice(
            id=invoice_id,
            tenant_id=tenant_id,
            file_path=f"tenants/{tenant_id}/invoices/test.pdf",
            invoice_number=f"INV-GAP674-{uuid.uuid4().hex[:6]}",
            subtotal=100.0,
            tax_amount=10.0,
            grand_total=125.0,
            freight_amount=15.0,
            additional_charges=[{"charge_type": "freight", "amount": 15.0}],
            status="VERIFIED",
        )
        session.add(invoice)
        session.commit()

    with Session(pg_engine) as session:
        loaded = session.exec(select(Invoice).where(Invoice.id == invoice_id)).first()
        assert loaded is not None
        assert loaded.freight_amount == 15.0
        assert len(loaded.additional_charges) == 1
        assert loaded.additional_charges[0]["charge_type"] == "freight"
        assert loaded.additional_charges[0]["amount"] == 15.0
