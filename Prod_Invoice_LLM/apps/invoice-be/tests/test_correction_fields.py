"""BE Gap 674: the derived correctable-field set.

`utils/correction_fields.py` replaced two hand-written dicts. These assert the
properties that made the hand-written version safe, so the derivation cannot quietly
widen or narrow what an auditor may edit.
"""
from datetime import date
from typing import Optional

from pydantic import BaseModel

from agents.extraction_agent import InvoiceExtractionSchema, OutboundInvoiceExtractionSchema
from models import Invoice
from utils.correction_fields import (
    derive_correctable_fields,
    entry_name_for,
    kind_from_annotation,
)


class _Schema(BaseModel):
    vendor_name: Optional[str] = None
    invoice_date: Optional[date] = None
    grand_total: Optional[float] = None
    items: list = []
    currency: Optional[str] = None
    discount_percent: Optional[float] = None
    round_off: Optional[float] = None          # extracted, no column
    charges: list = []                         # a list field nobody has named


class _Model(BaseModel):
    """Stands in for the Invoice table. The derivation reads `model_fields` only, so a
    plain model is enough and leaves no probe table behind in the test database."""
    vendor_name: Optional[str] = None
    invoice_date: Optional[date] = None
    grand_total: Optional[float] = None
    items: list = []
    currency: Optional[str] = None
    discount_percent: Optional[float] = None
    charges: list = []
    tenant_id: Optional[str] = None            # internal, must never be correctable
    file_path: Optional[str] = None            # internal


def test_a_field_with_no_column_is_not_correctable():
    assert "round_off" not in derive_correctable_fields(_Schema, _Model, extra={})


def test_internal_columns_never_enter_the_set():
    derived = derive_correctable_fields(_Schema, _Model, extra={})
    assert "tenant_id" not in derived and "file_path" not in derived


def test_semantic_kinds_win_over_the_inferred_type():
    derived = derive_correctable_fields(_Schema, _Model, extra={})
    # both are floats/strs on the model; the validation they need is not structural
    assert derived["currency"] == "currency"
    assert derived["discount_percent"] == "percent"


def test_structural_kinds_come_from_the_annotation():
    derived = derive_correctable_fields(_Schema, _Model, extra={})
    assert derived["invoice_date"] == "date"
    assert derived["grand_total"] == "float"
    assert derived["vendor_name"] == "str"
    assert derived["items"] == "list"


def test_a_new_list_field_is_correctable_without_being_named():
    """The point of BE Gap 674: a field added later needs no router edit."""
    derived = derive_correctable_fields(_Schema, _Model, extra={})
    assert derived["charges"] == "list"
    assert entry_name_for("charges", {"items": "line item"}) == "charge"
    assert entry_name_for("items", {"items": "line item"}) == "line item"


def test_optional_is_unwrapped():
    assert kind_from_annotation(Optional[date]) == "date"
    assert kind_from_annotation(Optional[list]) == "list"


def test_every_extracted_field_with_a_column_is_derived_for_both_routers():
    """The BE Gap 531 property, asserted against the derivation itself."""
    for schema in (InvoiceExtractionSchema, OutboundInvoiceExtractionSchema):
        derived = derive_correctable_fields(schema, Invoice, extra={})
        stored = set(schema.model_fields) & set(Invoice.model_fields)
        assert stored - set(derived) == set()
