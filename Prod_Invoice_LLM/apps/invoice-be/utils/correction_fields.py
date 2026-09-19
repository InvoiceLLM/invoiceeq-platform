"""BE Gap 674: derive the auditor-correctable field set instead of typing it out.

The rule the product wants is one sentence: **if the extractor can write a field
onto the invoice, a human can correct it.** That is what `tests/test_audit.py::
test_every_extracted_field_with_a_column_is_correctable` asserts, and until now the
two routers satisfied it by hand -- a dict per router, updated by whoever remembered.
BE Gap 674 is what happens when someone does not: `freight_amount` was extracted,
given a column and a migration, and left out of both dicts, so the pipeline read a
freight charge the reviewer could not touch.

Deriving the set from `schema.model_fields & Invoice.model_fields` closes that class
rather than that instance. The intersection is also exactly the right boundary:
internal columns (`tenant_id`, `file_path`, `batch_id`, `status`, `deleted_at`) are
not extraction outputs, so they never enter the set and stay unwritable through the
correction endpoint -- which is the reason the allow-list existed in the first place.

What still needs a human decision is *validation kind*, not permission. Most fields
are mechanical (a date is a date, a float is a float). Four are semantic -- an ISO
currency code, a 0-100 percent, the tag list, and the list fields whose entries are
checked against the schema's own nested model. Those live in the override maps below
and in each router's `_LIST_ENTRY_NAMES`; a field absent from both gets its kind from
its annotation.
"""
from datetime import date as _date
from typing import Any, Union, get_args, get_origin

#: Fields whose validation is semantic rather than structural. Keyed by field name
#: because the annotation cannot express "this string must be an ISO 4217 code".
SPECIAL_KINDS = {
    "currency": "currency",
    "discount_percent": "percent",
    "tags": "tags",
}

#: Correctable despite not being an extraction output. `tags` is user-applied
#: labelling, never read off a document, and has always been editable.
EXTRA_CORRECTABLE = {
    "tags": "tags",
}


def _unwrap_optional(annotation: Any) -> Any:
    """`str | None` -> `str`. Optional is the norm on these models, not the exception."""
    if get_origin(annotation) is Union:
        args = [a for a in get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return annotation


def kind_from_annotation(annotation: Any) -> str:
    """The validation kind implied by a field's type, for everything not in SPECIAL_KINDS."""
    inner = _unwrap_optional(annotation)
    origin = get_origin(inner) or inner
    if origin in (list, tuple, set):
        return "list"
    if inner is _date:
        return "date"
    if inner in (float, int):
        return "float"
    return "str"


def derive_correctable_fields(schema, model, *, extra=None) -> dict:
    """{field: validation kind} for every field this schema stores on this model.

    `schema` is the extraction schema (what the pipeline can fill in), `model` is the
    SQLModel table (what has a column). The intersection is the set of document facts
    that reach the database, which is precisely what an auditor is allowed to correct.
    """
    fields = {}
    model_fields = set(model.model_fields)
    for name, field in schema.model_fields.items():
        if name not in model_fields:
            # Extracted but with nowhere to land (e.g. `round_off`) -- nothing to correct.
            continue
        if name in SPECIAL_KINDS:
            fields[name] = SPECIAL_KINDS[name]
            continue
        fields[name] = kind_from_annotation(model.model_fields[name].annotation)
    fields.update(EXTRA_CORRECTABLE if extra is None else extra)
    return fields


def entry_name_for(field: str, names: dict) -> str:
    """The human label for one entry of a list field, for error messages.

    Named fields keep their curated wording ("line item", "tax ID"); a list field
    added later falls back to a readable singular so a new field is still usable
    before anyone writes it down.
    """
    if field in names:
        return names[field]
    label = field.replace("_", " ")
    return label[:-1] if label.endswith("s") else label
