"""Gap 178: Doc Intelligence field serialization for source_document_json."""
from types import SimpleNamespace

from queue_worker.handlers import _serialize_di_field, _serialize_di_document_fields


def test_serialize_di_string_and_number_fields():
    fields = {
        "VendorName": SimpleNamespace(
            type="string",
            confidence=0.98,
            value_string="ACME",
            value_number=None,
            value_integer=None,
            value_date=None,
            value_time=None,
            value_phone_number=None,
            value_country_region=None,
            value_currency=None,
            value_address=None,
            value_array=None,
            value_object=None,
            content="ACME",
        ),
        "InvoiceTotal": SimpleNamespace(
            type="currency",
            confidence=0.95,
            value_string=None,
            value_number=None,
            value_integer=None,
            value_date=None,
            value_time=None,
            value_phone_number=None,
            value_country_region=None,
            value_currency=SimpleNamespace(amount=200.0, currency_code="INR"),
            value_address=None,
            value_array=None,
            value_object=None,
            content="200.00",
        ),
    }
    out = _serialize_di_document_fields(fields)
    assert out["VendorName"]["value"] == "ACME"
    assert out["InvoiceTotal"]["value"]["amount"] == 200.0
    assert "bounding_regions" not in out["VendorName"]


def test_serialize_di_items_array():
    line = SimpleNamespace(
        type="object",
        confidence=0.9,
        value_string=None,
        value_number=None,
        value_integer=None,
        value_date=None,
        value_time=None,
        value_phone_number=None,
        value_country_region=None,
        value_currency=None,
        value_address=None,
        value_array=None,
        value_object={
            "Description": SimpleNamespace(
                type="string",
                confidence=0.9,
                value_string="Widget",
                value_number=None,
                value_integer=None,
                value_date=None,
                value_time=None,
                value_phone_number=None,
                value_country_region=None,
                value_currency=None,
                value_address=None,
                value_array=None,
                value_object=None,
                content="Widget",
            ),
            "Quantity": SimpleNamespace(
                type="number",
                confidence=0.9,
                value_string=None,
                value_number=2.0,
                value_integer=None,
                value_date=None,
                value_time=None,
                value_phone_number=None,
                value_country_region=None,
                value_currency=None,
                value_address=None,
                value_array=None,
                value_object=None,
                content="2",
            ),
        },
        content=None,
    )
    items_field = SimpleNamespace(
        type="array",
        confidence=0.9,
        value_string=None,
        value_number=None,
        value_integer=None,
        value_date=None,
        value_time=None,
        value_phone_number=None,
        value_country_region=None,
        value_currency=None,
        value_address=None,
        value_array=[line],
        value_object=None,
        content=None,
    )
    serialized = _serialize_di_field(items_field)
    assert serialized["value"][0]["value"]["Description"]["value"] == "Widget"
    assert serialized["value"][0]["value"]["Quantity"]["value"] == 2.0
