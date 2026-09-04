"""Feature 27 (G3 + G3b + G4 + G5) — the generic schema/overlays/prompts, the
profile resolution rule that decides when they are used, the classifier node and
conditional graph entry point that put a real document type into state, and the
verification rubric that decides what a document of that type is graded against.

Scope of THIS file today: the schema/overlay/prompt-builder slice (G3),
`resolve_extraction_profile()` + the `GENERIC` profile entry (G3b),
`classify_doc_type_node` + the flag-conditional graph (G4), and
`_VerificationRubric` / `_RUBRIC_BY_DOC_TYPE` + `verify_node`'s gating (G5, the
last section — T-R-1/2/3/4). §4 names `tests/test_generic_extraction.py` as the
home for the flag-ON *pipeline* tests; G4 is where those start being real, since
a run can now be driven end to end, and G5 is where the founder's original bug
finally has a test that fails without the fix.

What is covered here:
  * **T-R-5's shape, at the schema level** — `GenericLineItem` and
    `GenericDocumentSchema` accept partial documents with fields genuinely
    `None`, never coerced to `0`, `0.0` or `""`. This is the regression guard on
    the Gap 283 truthiness class of bug, applied to the new schema before
    anything can depend on the wrong behaviour.
  * **Overlay completeness** — a loop over `DOC_TYPES`, so adding an eleventh
    document type without writing it an overlay fails loudly here rather than
    silently serving it a generic prompt in production.
  * **A2's guarantee, asserted rather than assumed** — `InvoiceExtractionSchema`,
    `OutboundInvoiceExtractionSchema`, `ReferenceDocExtractionSchema` and
    `_DIRECTION_PROFILES` are unchanged by G3. G3 claims to be purely additive;
    that claim is worth an assertion, because the whole point of A2 is that a
    generic-schema extraction of an invoice still *looks* plausible.
  * **The prompt builders** — the resolved overlay text actually reaches the
    prompt string, for a couple of sample types.
  * **(G3b) A2's four-condition profile rule as an explicit truth table** — all
    four conditions true → the `GENERIC` profile; each one false in turn (flag
    off / OUTBOUND / `doc_type is None` / a money-family type) → identical to
    calling `resolve_direction_profile` directly, asserted by identity rather
    than by "not generic".
  * **(G4) E3's flag-off guarantee asserted on graph structure, not on output** —
    with the flag off `classify_doc_type_node` is absent from the compiled graph,
    not inert in it — plus real end-to-end runs through `run_extraction_agent` in
    both flag states, and the classified `doc_type` reaching `extract_node` /
    `verify_node`.

  * **(G7) the trust boundaries on `prebuilt-invoice`'s invoice-specific output**
    — T-R-7 (a non-invoice document raises no `low_confidence_field` alerts even
    when Document Intelligence returns low scores for `VendorName`/`InvoiceTotal`),
    the Gap 68 tax backfill gated to the money family, and `invoice.coordinates`
    persisted for the money family only, asserted through the real
    `handle_process_invoice` persistence block.

No network and no real LLM call. G7's last three tests are the only ones that
touch a DB, and it is in-memory SQLite: per hard rule 2 nothing here is a
Postgres-backed verification of the pipeline, and none is claimed — that is task
V, which is blocked on §7 task F's fixtures.
"""
import base64
import inspect
import io
import logging
from unittest.mock import Mock, patch
from uuid import uuid4

import fitz
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import config
import agents.extraction_agent as ea
import queue_worker.handlers as handlers
import services.document_type_classifier as dtc
from models import Invoice
from agents.extraction_agent import (
    GenericDocumentSchema,
    GenericLineItem,
    InvoiceExtractionSchema,
    OutboundInvoiceExtractionSchema,
    ReferenceDocExtractionSchema,
    build_generic_multimodal_prompt,
    resolve_direction_profile,
    resolve_doc_type_overlay,
    resolve_extraction_profile,
)
from services.document_type_classifier import (
    COMMITMENT_FAMILY,
    DOC_TYPE_FAMILY,
    DOC_TYPES,
    MONEY_FAMILY,
    OTHER_FAMILY,
    QUANTITY_FAMILY,
)

_OVERLAYS = ea._DOC_TYPE_OVERLAYS
_STANCE = ea._GENERIC_FAMILY_STANCE

# Every non-INVOICE value in the closed taxonomy. `INVOICE` is excluded
# deliberately and NOT by name-matching a family: under A2 an invoice keeps
# `InvoiceExtractionSchema` in both flag states and never reaches this path.
_NON_INVOICE_DOC_TYPES = tuple(dt for dt in DOC_TYPES if dt != "INVOICE")

# G3b's two halves of the taxonomy, derived from the family map rather than
# listed by hand, so a family reassignment (QUOTATION's COMMITMENT mapping is
# still provisional — see the Gap 369 build note) moves the type between these
# tuples automatically instead of leaving a stale hardcoded list passing.
_MONEY_DOC_TYPES = tuple(dt for dt in DOC_TYPES if DOC_TYPE_FAMILY[dt] == MONEY_FAMILY)
_GENERIC_ELIGIBLE_DOC_TYPES = tuple(dt for dt in DOC_TYPES if DOC_TYPE_FAMILY[dt] != MONEY_FAMILY)


def _state(ocr_text: str = "OCR", **extra):
    """The subset of `ExtractionState` the text prompt builder reads."""
    state = {"ocr_text": ocr_text}
    state.update(extra)
    return state


# --- None is not zero (E8; the Gap 283 truthiness class) ---------------------


def test_generic_line_item_accepts_a_bare_description_with_everything_else_none():
    """A delivery-note row: a description, a quantity, and no money anywhere.

    The assertion that matters is `is None`, not falsiness — `0.0 == None` is
    False but `not 0.0` and `not None` are both True, and reading these fields
    with truthiness is exactly how Gap 283 happened.
    """
    item = GenericLineItem(description="M8 hex bolts, zinc plated", quantity=250.0)

    assert item.description == "M8 hex bolts, zinc plated"
    assert item.quantity == 250.0
    for field in (
        "unit_price",
        "amount",
        "quantity_ordered",
        "quantity_delivered",
        "quantity_received",
        "uom",
        "batch_or_serial",
    ):
        assert getattr(item, field) is None, f"{field} was coerced away from None"


def test_generic_line_item_constructs_with_no_arguments_at_all():
    """Every field is Optional with a `None` default (E8).

    Also the §8 trap 2 property: `MockInvoiceLLM._generate_structured()`'s
    fallback is `try: return schema_cls()`, so a required field anywhere on a
    structured-output schema turns a mock-mode failure into a silent *empty
    extraction* rather than an error.
    """
    item = GenericLineItem()
    assert all(getattr(item, name) is None for name in GenericLineItem.model_fields)


def test_generic_document_schema_constructs_with_no_arguments_at_all():
    doc = GenericDocumentSchema()

    # The list-valued fields are DERIVED from the model rather than hardcoded.
    # A7/R9 added two more (`referenced_documents`, `payment_deductions`) and the
    # old hardcoded tuple made that an unrelated failure -- the test would break
    # on every future additive field, which is the opposite of what a
    # "constructs with no arguments" guard is for.
    list_fields = [
        name for name, field in GenericDocumentSchema.model_fields.items()
        if isinstance(field.default, list)
    ]
    scalars = [n for n in GenericDocumentSchema.model_fields if n not in list_fields]

    assert all(getattr(doc, name) is None for name in scalars)
    for name in list_fields:
        assert getattr(doc, name) == [], name

    # Named explicitly as well, so a field silently ceasing to be a list is still
    # caught rather than quietly dropping out of the derived set above.
    for name in ("items", "taxes", "reference_numbers", "referenced_documents",
                 "payment_deductions"):
        assert name in list_fields, name


def test_a_delivery_note_with_no_prices_is_a_complete_document_not_a_broken_one():
    """The founder's original symptom, expressed as a schema-level assertion.

    Quantities, units and batch numbers; no currency, no subtotal, no tax, no
    grand total. Every money field must stay `None` — not `0.0`, which would read
    downstream as a document that genuinely printed zero.
    """
    doc = GenericDocumentSchema(
        doc_type="DELIVERY_NOTE",
        party_name="Sample Supplier Pvt Ltd",
        counterparty_name="Northbridge Manufacturing Ltd",
        doc_number="DC-2026-0091",
        po_number="PO-2026-4471",
        doc_date="2026-09-01",
        items=[
            GenericLineItem(
                description="Hydraulic seal kit",
                quantity=12.0,
                quantity_delivered=12.0,
                uom="NOS",
                batch_or_serial="B-77213",
            ),
            GenericLineItem(description="Filter element", quantity=4.0, uom="NOS"),
        ],
    )

    for field in ("currency", "subtotal", "tax_amount", "discount_amount", "grand_total"):
        assert getattr(doc, field) is None, f"{field} was coerced away from None"
    assert [i.unit_price for i in doc.items] == [None, None]
    assert [i.amount for i in doc.items] == [None, None]
    assert doc.items[1].batch_or_serial is None


def test_a_printed_zero_is_preserved_as_zero_not_flattened_to_none():
    """The other half of the same discipline, and the reason Gap 283 exists.

    A genuinely printed 0.00 (a free-of-charge sample line, a nil-rated tax) must
    survive as `0.0`. `None` means "not stated"; `0.0` means "stated as zero".
    Collapsing either into the other loses a real distinction.
    """
    doc = GenericDocumentSchema(
        doc_type="QUOTATION",
        currency="INR",
        tax_amount=0.0,
        grand_total=0.0,
        items=[GenericLineItem(description="Free sample", quantity=1.0, unit_price=0.0, amount=0.0)],
    )

    assert doc.tax_amount == 0.0 and doc.tax_amount is not None
    assert doc.grand_total == 0.0 and doc.grand_total is not None
    assert doc.items[0].unit_price == 0.0 and doc.items[0].unit_price is not None
    assert doc.items[0].amount == 0.0


def test_the_schema_forbids_extra_fields_so_structured_output_stays_strict():
    """`extra="forbid"` on every model, for the reason stated at the top of the
    file: Azure/OpenAI `with_structured_output` strict mode requires
    `additionalProperties: false` recursively, and pydantic only emits it when
    extra is forbidden."""
    with pytest.raises(Exception):
        GenericDocumentSchema(vendor_name="Should not be accepted here")
    with pytest.raises(Exception):
        GenericLineItem(hsn_sac_code="8481")


# --- Overlay completeness (E8) ----------------------------------------------


@pytest.mark.parametrize("doc_type", _NON_INVOICE_DOC_TYPES)
def test_every_non_invoice_doc_type_has_an_overlay(doc_type):
    """Loop-based on purpose: an eleventh type added to `DOC_TYPES` without an
    overlay fails HERE, rather than silently receiving a generic prompt written
    for a document it is not."""
    assert doc_type in _OVERLAYS, f"{doc_type} has no entry in _DOC_TYPE_OVERLAYS"
    assert _OVERLAYS[doc_type].strip(), f"{doc_type}'s overlay is empty"


def test_the_overlay_table_holds_exactly_the_non_invoice_types_and_no_more():
    """Both directions. A stale entry for a type that has been removed from the
    taxonomy is as much a defect as a missing one, and `INVOICE` must NOT have an
    overlay: per A2 an invoice never reaches this path, and providing one would
    make the omission look like an oversight."""
    assert set(_OVERLAYS) == set(_NON_INVOICE_DOC_TYPES)
    assert "INVOICE" not in _OVERLAYS


@pytest.mark.parametrize("family", [MONEY_FAMILY, QUANTITY_FAMILY, COMMITMENT_FAMILY, OTHER_FAMILY])
def test_every_family_has_a_stance_paragraph(family):
    """Same completeness property one level up. `resolve_doc_type_overlay` looks
    the stance up by `DOC_TYPE_FAMILY[doc_type]`, so a family with no stance
    would silently serve the OTHER text."""
    assert _STANCE.get(family, "").strip()


def test_every_doc_types_family_is_one_the_stance_map_knows():
    for doc_type in DOC_TYPES:
        assert DOC_TYPE_FAMILY[doc_type] in _STANCE


def test_the_delivery_note_overlay_carries_e8s_verbatim_instruction():
    """E8 specifies this overlay's substance in words: prices are frequently
    absent by design, do not infer them, do not compute a total. It is the
    founder's original symptom, so it is asserted rather than left to review."""
    overlay = _OVERLAYS["DELIVERY_NOTE"].lower()
    assert "absent by design" in overlay
    assert "do not infer" in overlay
    assert "do not compute" in overlay


def test_the_contract_overlay_carries_e8s_verbatim_instruction():
    """E8: capture validity window / renewal / termination into `notes`; a
    framework agreement may have no grand total."""
    overlay = _OVERLAYS["CONTRACT"].lower()
    assert "validity window" in overlay
    assert "renewal" in overlay and "termination" in overlay
    assert "`notes`" in overlay
    assert "framework agreement" in overlay
    assert "no grand total" in overlay


# --- Overlay resolution ------------------------------------------------------


@pytest.mark.parametrize("doc_type", _NON_INVOICE_DOC_TYPES)
def test_resolved_overlay_is_the_family_stance_plus_the_types_own_text(doc_type):
    resolved = resolve_doc_type_overlay(doc_type)
    assert _STANCE[DOC_TYPE_FAMILY[doc_type]] in resolved
    assert _OVERLAYS[doc_type] in resolved


@pytest.mark.parametrize("value", [None, "", "   ", "LIEFERSCHEIN", "not_a_doc_type"])
def test_unknown_doc_types_fall_back_to_the_conservative_other_overlay(value):
    """Fail-closed, matching E1's reasoning for the flag default and the
    classifier's own fallback: an unrecognised type gets the most conservative
    instruction set in the table, not an invoice-shaped one."""
    assert resolve_doc_type_overlay(value) == resolve_doc_type_overlay("OTHER")


def test_asking_for_an_invoice_overlay_warns_and_falls_back(caplog):
    """A2: an invoice must never reach the generic path. If it does,
    `resolve_extraction_profile` (G3b) has a defect — so this logs rather than
    quietly serving a conservative prompt."""
    with caplog.at_level("WARNING", logger="agents.extraction_agent"):
        resolved = resolve_doc_type_overlay("INVOICE")
    assert resolved == resolve_doc_type_overlay("OTHER")
    assert any("InvoiceExtractionSchema" in r.message for r in caplog.records)


def test_doc_type_matching_is_case_and_whitespace_insensitive():
    assert resolve_doc_type_overlay(" delivery_note ") == resolve_doc_type_overlay("DELIVERY_NOTE")


# --- The prompt builders (E8) ------------------------------------------------


@pytest.mark.parametrize("doc_type", ["DELIVERY_NOTE", "CONTRACT", "PURCHASE_ORDER", "GRN"])
def test_multimodal_prompt_contains_the_resolved_overlay(doc_type):
    messages = build_generic_multimodal_prompt(
        "DELIVERY CHALLAN\nQty 250 NOS", ["data:image/png;base64,AAAA"], None, doc_type
    )
    text = messages[0].content[0]["text"]

    assert _OVERLAYS[doc_type] in text
    assert _STANCE[DOC_TYPE_FAMILY[doc_type]] in text
    assert f"type {doc_type}" in text
    assert "ABSENT IS NOT ZERO" in text
    assert ea.GAP_46_VERBATIM_DIRECTIVE in text
    assert "OCR Text:\nDELIVERY CHALLAN\nQty 250 NOS" in text
    # The images still ride along on the same message, as they do for every
    # other multimodal builder in this file.
    assert messages[0].content[1]["image_url"]["url"] == "data:image/png;base64,AAAA"


@pytest.mark.parametrize("doc_type", ["DELIVERY_NOTE", "CONTRACT", "QUOTATION", "OTHER"])
def test_text_prompt_contains_the_resolved_overlay_for_the_states_doc_type(doc_type):
    prompt = ea._build_generic_text_prompt(_state("PACKING SLIP\n12 NOS", doc_type=doc_type), None)

    assert _OVERLAYS[doc_type] in prompt
    assert _STANCE[DOC_TYPE_FAMILY[doc_type]] in prompt
    assert prompt.endswith("PACKING SLIP\n12 NOS")


def test_text_prompt_without_a_doc_type_uses_the_conservative_other_overlay():
    """G4 added `doc_type` to `ExtractionState`, but the key is still absent
    whenever the classifier node is not in the graph (flag off) or a caller built
    the state by hand, so the builder must work — conservatively — without it."""
    prompt = ea._build_generic_text_prompt(_state("SOME DOCUMENT"), None)
    assert _OVERLAYS["OTHER"] in prompt


def test_prompt_builders_render_tenant_rules_the_same_way_every_other_builder_does():
    """Feature 18's shared `normalize_constraints` — legacy free-text rules and
    structured rule objects must render identically here too."""
    rules = {"constraints": ["Read quantities from the right-hand column"]}
    text = build_generic_multimodal_prompt("OCR", [], rules, "DELIVERY_NOTE")[0].content[0]["text"]
    prompt = ea._build_generic_text_prompt(_state("OCR", doc_type="DELIVERY_NOTE"), rules)

    for rendered in (text, prompt):
        assert "You MUST respect the following layout extraction constraints/rules:" in rendered
        assert "- Read quantities from the right-hand column" in rendered


def test_text_prompt_carries_the_dynamic_qa_findings_like_its_siblings():
    prompt = ea._build_generic_text_prompt(
        _state("OCR", doc_type="CONTRACT", dynamic_qa_context="Rate table spans two pages"), None
    )
    assert "DYNAMIC LAYOUT PRE-ANALYSIS FINDINGS" in prompt
    assert "Rate table spans two pages" in prompt


# --- A2: G3 is additive. The invoice path is untouched. ----------------------


def test_the_existing_schemas_are_unchanged_by_g3():
    """A2's whole point. `GenericDocumentSchema`'s spine carries none of
    `compliance_metadata`, `payment_instructions`, `deductions`, `tax_ids`,
    `addresses`, `round_off`, `discount_percent` or per-line `hsn_sac_code` — so
    an invoice put on it would silently lose the India e-invoicing block, the GST
    HSN codes and the round-off handling, with no error raised anywhere."""
    invoice_only = {
        "compliance_metadata",
        "payment_instructions",
        "deductions",
        "tax_ids",
        "addresses",
        "round_off",
        "discount_percent",
    }
    assert invoice_only <= set(InvoiceExtractionSchema.model_fields)
    assert not (invoice_only & set(GenericDocumentSchema.model_fields))
    assert "hsn_sac_code" in ea.InvoiceLineItem.model_fields
    assert "hsn_sac_code" not in GenericLineItem.model_fields

    # `ReferenceDocExtractionSchema` (Feature 26's chat-attachment path) keeps its
    # narrower field set and its required `description`; A2 leaves REFERENCE
    # unchanged in v1.
    assert set(ReferenceDocExtractionSchema.model_fields) == {
        "doc_type", "party_name", "doc_number", "po_number", "doc_date", "subtotal",
        "tax_amount", "grand_total", "currency", "discount_amount", "items", "taxes",
    }
    assert ea.ReferenceDocLineItem.model_fields["description"].is_required()


def test_the_three_existing_direction_entries_are_unchanged():
    """Updated by G3b, which added a fourth `GENERIC` entry to this map. The three
    real directions are still there and still resolve to the same schemas they
    always did — that is the part E3/A2 guarantee. `GENERIC` is asserted
    separately below; it is a profile, not a direction, and nothing reaches it
    except `resolve_extraction_profile`."""
    assert ea._DIRECTION_PROFILES["INBOUND"].schema is InvoiceExtractionSchema
    assert ea._DIRECTION_PROFILES["OUTBOUND"].schema is OutboundInvoiceExtractionSchema
    assert ea._DIRECTION_PROFILES["REFERENCE"].schema is ReferenceDocExtractionSchema
    assert ea.resolve_direction_profile("INBOUND").schema is InvoiceExtractionSchema
    assert set(ea._DIRECTION_PROFILES) == {"INBOUND", "OUTBOUND", "REFERENCE", "GENERIC"}


def test_g7s_honest_scope_the_di_trust_boundaries_are_wired_and_g6_still_is_not():
    """**Updated by G6 (Gap 384)** — the fail-loud marker below is now flipped, not
    deleted, per this feature's convention for its own markers. E9 has shipped:
    `UnknownFlowDirectionError` exists and `resolve_direction_profile` raises it.
    The docstring below is kept verbatim for the record and the one line it
    contradicts is corrected here rather than by rewriting it.

    **Updated by G7** (was `test_g5s_honest_scope_...`), which gated the two
    *Document Intelligence*-derived checks — the Gap 3 Critic in `verify_node` and
    the Gap 68 `tax_details_sum` backfill in `extract_node` — on the rubric fields
    G5 declared for it, and gated `invoice.coordinates` persistence on the family
    in `queue_worker/handlers.py`.

    What is still NOT built, asserted so the tracker entry stays checkable:
      * `UnknownFlowDirectionError`, E9's fail-loud (the rest of G6).
      * G9's persistence: nothing writes `doc_type` onto a row, and there is no
        `documents` table (E10). `run_extraction_agent` now returns the type,
        because G7's coordinates gate is the first thing that needs it back out
        of the graph, but that is the whole of it.

    `run_extraction_agent` deliberately keeps `resolve_direction_profile`: its one
    use of a profile is the pre-flight token-guardrail early return, which happens
    before OCR text ever reaches the graph, so no `doc_type` exists at that point.
    """
    assert hasattr(ea, "classify_doc_type_node")  # G4, built
    assert hasattr(ea, "_VerificationRubric")  # G5, built
    assert hasattr(ea, "_RUBRIC_BY_DOC_TYPE")  # G5, built
    assert hasattr(ea, "resolve_verification_rubric")  # G5, built
    assert hasattr(ea, "UnknownFlowDirectionError")  # G6's fail-loud, built (Gap 384)

    # G7's two fields live on the rubric and NOT on the profile dataclass — the
    # DI trust boundaries are a property of the document family, not of the flow
    # direction. Asserted on the dataclasses rather than on source text, which any
    # comment naming them would defeat.
    assert "run_field_confidence" in ea._VerificationRubric.__dataclass_fields__
    assert "run_di_tax_backfill" in ea._VerificationRubric.__dataclass_fields__
    assert "run_field_confidence" not in ea._DirectionProfile.__dataclass_fields__
    assert "run_di_tax_backfill" not in ea._DirectionProfile.__dataclass_fields__

    # ...and both are now read, each in the node that owns its check. This is the
    # marker G5 left to flip rather than delete: the behavioural proof is in the
    # G7 section at the end of this file, and these are the structural half.
    extract_source = inspect.getsource(ea.extract_node)
    assert "resolve_verification_rubric" in extract_source  # G7, wired
    assert "rubric.run_di_tax_backfill" in extract_source  # G7, wired
    verify_source = inspect.getsource(ea.verify_node)
    assert "rubric.run_line_item_math" in verify_source  # G5, wired
    assert "rubric.run_totals_math" in verify_source  # G5, wired
    assert "rubric.advisory_only" in verify_source  # G5, wired
    assert "rubric.run_field_confidence" in verify_source  # G7, wired

    for fn in (ea.extract_node, ea.verify_node):
        assert "resolve_extraction_profile(" in inspect.getsource(fn), (
            f"{fn.__name__} must resolve its profile from the direction AND the "
            "classified doc_type — that is what G4 wired."
        )

    assert "resolve_direction_profile(" in inspect.getsource(ea.run_extraction_agent)


# =============================================================================
def test_gap_435_reference_direction_takes_the_generic_spine_for_advisory_types_only(monkeypatch):
    """A chat-attached statement/remittance must be extracted on the generic
    schema (it alone carries `referenced_documents[]`); a chat-attached PO must
    not change profile at all."""
    import agents.extraction_agent as ea
    from agents.extraction_agent import resolve_extraction_profile

    monkeypatch.setattr(ea.get_settings(), "ENABLE_GENERIC_EXTRACTION", True)
    for adv in ("STATEMENT_OF_ACCOUNT", "REMITTANCE_ADVICE"):
        assert resolve_extraction_profile("REFERENCE", adv) is ea._DIRECTION_PROFILES["GENERIC"]
    for other in ("PURCHASE_ORDER", "QUOTATION", "DELIVERY_NOTE", "CONTRACT", "INVOICE", None):
        assert resolve_extraction_profile("REFERENCE", other) is ea._DIRECTION_PROFILES["REFERENCE"]
    monkeypatch.setattr(ea.get_settings(), "ENABLE_GENERIC_EXTRACTION", False)
    assert resolve_extraction_profile("REFERENCE", "STATEMENT_OF_ACCOUNT") is ea._DIRECTION_PROFILES["REFERENCE"]


# Feature 27 (G3b) — `resolve_extraction_profile()` + the `GENERIC` profile entry
# =============================================================================
# Amendment A2, "Profile resolution — the exact rule to implement". The function
# returns `resolve_direction_profile(flow_direction)` in every case EXCEPT all
# four of these holding together:
#
#   1. `ENABLE_GENERIC_EXTRACTION` is True
#   2. `flow_direction` resolves to INBOUND
#   3. `doc_type is not None`
#   4. `DOC_TYPE_FAMILY[doc_type] != MONEY_FAMILY`
#
# The tests below are written as an explicit truth table: all four true, then each
# one false in turn. Every fall-through case asserts **identity with the result of
# calling `resolve_direction_profile` directly** (`is`, not "is not GENERIC"),
# because "not the generic profile" would still pass if the function returned some
# other wrong profile, and the guarantee A2 actually makes is that those paths are
# byte-for-byte today's behaviour.


@pytest.fixture
def generic_flag_on(monkeypatch):
    """Turn `ENABLE_GENERIC_EXTRACTION` on for one test.

    Patches the attribute on the `config.settings` singleton — the shape
    `tests/test_chat_queue.py` and `tests/test_online_quality_judge.py` already
    use for the sibling flags. `get_settings()` is `@lru_cache`d and returns that
    same object, so `agents.extraction_agent`'s call-time read sees the patch.
    """
    monkeypatch.setattr(config.settings, "ENABLE_GENERIC_EXTRACTION", True)
    assert ea.get_settings().ENABLE_GENERIC_EXTRACTION is True
    return True


def test_the_flag_defaults_off_so_this_whole_path_is_unreachable_by_default():
    """E1/E3's fail-closed default, asserted here rather than assumed by every
    other test in this section. A deployment that has not thought about Feature 27
    gets today's behaviour."""
    assert ea.get_settings().ENABLE_GENERIC_EXTRACTION is False


def test_the_generic_profile_entry_has_the_shape_a2_specifies():
    """The `GENERIC` entry itself: E8's schema, G3's builders, no required fields,
    REFERENCE's status vocabulary, no legacy audit shim."""
    generic = ea._DIRECTION_PROFILES["GENERIC"]
    reference = ea._DIRECTION_PROFILES["REFERENCE"]

    assert generic.schema is GenericDocumentSchema
    assert generic.build_multimodal_prompt is ea.build_generic_multimodal_prompt
    assert generic.build_text_prompt is ea._build_generic_text_prompt
    assert generic.required_fields == ()
    assert generic.legacy_audit_path_shim is False

    # The status pair is REFERENCE's, deliberately and not by coincidence: a
    # delivery note has no audit lifecycle, exactly as a chat-attached reference
    # document has none. E10 gives the `documents` table the same two values.
    assert (generic.passed_status, generic.review_status) == ("EXTRACTED", "EXTRACT_FAILED")
    assert (generic.passed_status, generic.review_status) == (
        reference.passed_status,
        reference.review_status,
    )


def test_the_generic_profile_is_not_reachable_through_any_real_flow_direction():
    """It lives in `_DIRECTION_PROFILES` for shape reuse, but it is not a
    direction. Nothing any of the eight `run_extraction_agent` call sites can pass
    reaches it — only `resolve_extraction_profile` returns it.

    **Updated by G6 (Gap 384).** `"NONSENSE"` no longer *resolves* to anything — it
    raises `UnknownFlowDirectionError`, which is a strictly stronger statement of
    the same property: it cannot reach `GENERIC` because it cannot reach a profile
    at all. `"inbound"` is unaffected (the lookup has always upper-cased). Both
    halves are asserted so the original claim is not weakened, and `"GENERIC"`
    itself is added — the literal name of this entry must not be an accepted
    direction, which is the trap G3b's note left for G6."""
    generic = ea._DIRECTION_PROFILES["GENERIC"]
    for direction in (None, "", "INBOUND", "OUTBOUND", "REFERENCE", "inbound"):
        assert resolve_direction_profile(direction) is not generic

    for direction in ("NONSENSE", "GENERIC", "generic"):
        with pytest.raises(ea.UnknownFlowDirectionError):
            resolve_direction_profile(direction)


# --- All four conditions true -------------------------------------------------


@pytest.mark.parametrize("doc_type", _GENERIC_ELIGIBLE_DOC_TYPES)
def test_all_four_conditions_true_returns_the_generic_profile(generic_flag_on, doc_type):
    """Flag ON + INBOUND + a known doc_type + a non-money family. Parametrised over
    every non-money value in `DOC_TYPES` (QUOTATION, PURCHASE_ORDER, CONTRACT,
    DELIVERY_NOTE, GRN, OTHER) rather than a hand-picked one."""
    profile = resolve_extraction_profile("INBOUND", doc_type)
    assert profile is ea._DIRECTION_PROFILES["GENERIC"]
    assert profile.schema is GenericDocumentSchema


@pytest.mark.parametrize("flow_direction", [None, ""])
def test_absent_flow_direction_still_resolves_inbound_and_is_therefore_eligible(
    generic_flag_on, flow_direction
):
    """A2 says "resolves to INBOUND", and E9 requires `None`/`""` to keep
    defaulting there — the trainer agent and the benchmark harness pass nothing at
    all. So an unclassified-direction delivery note is eligible."""
    assert resolve_extraction_profile(flow_direction, "DELIVERY_NOTE") is ea._DIRECTION_PROFILES["GENERIC"]


@pytest.mark.parametrize("doc_type", ["delivery_note", "  Delivery_Note  ", "grn"])
def test_doc_type_is_normalised_before_the_family_lookup(generic_flag_on, doc_type):
    """`DOC_TYPE_FAMILY` is keyed on the canonical uppercase values. The classifier
    only emits those (its `doc_type` is a `Literal`), but `run_extraction_agent`'s
    caller-supplied override is free text, so it is normalised first."""
    assert resolve_extraction_profile("INBOUND", doc_type) is ea._DIRECTION_PROFILES["GENERIC"]


# --- Condition 1 false: the flag is off ---------------------------------------


@pytest.mark.parametrize("doc_type", _GENERIC_ELIGIBLE_DOC_TYPES)
def test_flag_off_falls_through_to_exactly_the_existing_profile(doc_type):
    """E3: with the flag off, nothing about profile resolution changes — asserted
    as identity with `resolve_direction_profile`'s own answer, not merely as "not
    generic"."""
    assert ea.get_settings().ENABLE_GENERIC_EXTRACTION is False
    assert resolve_extraction_profile("INBOUND", doc_type) is resolve_direction_profile("INBOUND")
    assert resolve_extraction_profile("INBOUND", doc_type).schema is InvoiceExtractionSchema


def test_flag_off_is_identical_to_resolve_direction_profile_for_every_combination():
    """The exhaustive form of E3 for this function: every direction the codebase
    can produce (including the absent and typo'd cases) crossed with every value in
    the closed taxonomy plus `None`.

    **Updated by G6 (Gap 384).** `"REFERNCE"` moved out of the identity loop and
    into its own assertion below, because E9 now makes it raise rather than
    resolve. The equality being proved is unchanged in kind — the two functions
    still agree on every input, including agreeing on which inputs raise — so the
    typo'd case is asserted as *matching failure*, not dropped."""
    assert ea.get_settings().ENABLE_GENERIC_EXTRACTION is False
    for flow_direction in (None, "", "INBOUND", "OUTBOUND", "REFERENCE", "inbound"):
        for doc_type in (None,) + DOC_TYPES:
            assert resolve_extraction_profile(flow_direction, doc_type) is resolve_direction_profile(
                flow_direction
            ), f"{flow_direction!r} / {doc_type!r} diverged with the flag OFF"

    for doc_type in (None,) + DOC_TYPES:
        with pytest.raises(ea.UnknownFlowDirectionError):
            resolve_direction_profile("REFERNCE")
        with pytest.raises(ea.UnknownFlowDirectionError):
            resolve_extraction_profile("REFERNCE", doc_type)


# --- Condition 2 false: the direction is not INBOUND --------------------------


@pytest.mark.parametrize("doc_type", (None,) + DOC_TYPES)
@pytest.mark.parametrize("flow_direction", ["OUTBOUND", "REFERENCE"])
def test_outbound_and_reference_are_unchanged_for_every_doc_type(
    generic_flag_on, flow_direction, doc_type
):
    """A2: "OUTBOUND and REFERENCE are unchanged in v1." doc_type is still
    classified and recorded for both; it simply never changes their schema.
    OUTBOUND's consumers (`routers/outbound_audit.py`,
    `queue_worker/outbound_handlers.py`) are written against
    `OutboundInvoiceExtractionSchema`, and REFERENCE is Feature 26's
    chat-attachment path.

    Gap 435 (2026-09-04) carved out ONE exception: REFERENCE + an ADVISORY type
    takes the generic spine, because reconcile needs `referenced_documents[]`.
    """
    if flow_direction == "REFERENCE" and doc_type in ("STATEMENT_OF_ACCOUNT", "REMITTANCE_ADVICE"):
        pytest.skip("Gap 435: covered by test_gap_435_reference_direction_takes_the_generic_spine_for_advisory_types_only")
    resolved = resolve_extraction_profile(flow_direction, doc_type)
    assert resolved is resolve_direction_profile(flow_direction)
    assert resolved is ea._DIRECTION_PROFILES[flow_direction]


@pytest.mark.parametrize("flow_direction", ["  inbound ", "REFERNCE", "NONSENSE", "GENERIC "])
def test_a_padded_or_typod_direction_now_raises(generic_flag_on, flow_direction):
    """**Renamed and inverted by G6 (Gap 384)** — was
    `test_a_padded_or_typod_direction_falls_closed_to_todays_behaviour`, whose own
    docstring already named this as the pending change: "it gets whatever it gets
    today (the INBOUND default), **until G6's fail-loud makes it raise**." It now
    raises, so the assertion is inverted rather than the case dropped.

    The parametrised list is untouched, including `"  inbound "`: padding is not
    forgiven. The direction test still uses the *same* normalising expression
    `resolve_direction_profile` uses, so the two cannot drift — and stripping in
    one of them is exactly how they would. Note this is asserted with the flag
    **ON**; the flag-OFF half is asserted in the exhaustive E3 test above, because
    E9 is unconditional."""
    with pytest.raises(ea.UnknownFlowDirectionError):
        resolve_direction_profile(flow_direction)
    with pytest.raises(ea.UnknownFlowDirectionError):
        resolve_extraction_profile(flow_direction, "DELIVERY_NOTE")


# --- Condition 3 false: doc_type is None --------------------------------------


@pytest.mark.parametrize("flow_direction", [None, "", "INBOUND", "OUTBOUND", "REFERENCE"])
def test_doc_type_none_falls_through_to_exactly_the_existing_profile(generic_flag_on, flow_direction):
    """A2: "`doc_type is None` → the existing profile, exactly as today.
    Fail-closed to invoice behaviour." This is the flag-ON-but-not-classified case
    — `run_extraction_agent`'s caller-supplied skip, or the node not having run."""
    assert resolve_extraction_profile(flow_direction, None) is resolve_direction_profile(flow_direction)


def test_doc_type_has_no_default_so_a_caller_cannot_forget_it():
    """A missing `doc_type` is a defect in the caller, and it should be a
    `TypeError` at the call site rather than a silent fall-through to the invoice
    path — the decision this function exists to make explicit."""
    with pytest.raises(TypeError):
        resolve_extraction_profile("INBOUND")


# --- Condition 4 false: the doc_type is in the money family -------------------


@pytest.mark.parametrize("doc_type", _MONEY_DOC_TYPES)
def test_money_family_doc_types_keep_the_invoice_profile(generic_flag_on, doc_type):
    """A2's core guarantee, and the one that protects the existing business:
    INVOICE, PROFORMA_INVOICE, CREDIT_NOTE and DEBIT_NOTE keep
    `InvoiceExtractionSchema` in BOTH flag states. Putting one on
    `GenericDocumentSchema` would silently drop `compliance_metadata` (the India
    IRN/QR block), `tax_ids`, `payment_instructions`, `addresses`, `deductions`,
    `round_off` and per-line `hsn_sac_code` while still returning a plausible
    `vendor_name` and `grand_total`."""
    resolved = resolve_extraction_profile("INBOUND", doc_type)
    assert resolved is resolve_direction_profile("INBOUND")
    assert resolved.schema is InvoiceExtractionSchema


@pytest.mark.parametrize("doc_type", ["PROFORMA_INVOICE", "CREDIT_NOTE", "DEBIT_NOTE"])
def test_the_family_test_is_the_family_constant_not_the_literal_invoice(generic_flag_on, doc_type):
    """The specific bug the G1/G2 build note flagged for this task. A1/A2's prose
    says `DOC_TYPE_FAMILY[doc_type] != "INVOICE"`, but the family key shipped as
    `MONEY` — and `"INVOICE"` is already a doc_type *value*, so a literal
    comparison reads true for these three money documents and routes them to the
    generic schema. These three are the whole test: a `doc_type == "INVOICE"`
    check, or a `!= "INVOICE"` family check, passes every other test in this file
    and fails these."""
    assert DOC_TYPE_FAMILY[doc_type] == MONEY_FAMILY
    assert resolve_extraction_profile("INBOUND", doc_type).schema is InvoiceExtractionSchema


def test_lowercase_money_types_are_normalised_before_the_family_test_too():
    """The normalisation must not become a hole: 'invoice' lower-case must reach
    the money family, not fall through the unknown-type branch by accident."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(config.settings, "ENABLE_GENERIC_EXTRACTION", True)
        assert resolve_extraction_profile("INBOUND", " invoice ").schema is InvoiceExtractionSchema


# --- Out of vocabulary: not one of A2's four conditions, decided here ----------


@pytest.mark.parametrize("doc_type", ["LIEFERSCHEIN", "not_a_doc_type", "", "   ", "BILL_OF_LADING"])
def test_an_unknown_doc_type_falls_closed_to_the_existing_profile_and_warns(
    generic_flag_on, doc_type, caplog
):
    """A2 does not rule on a doc_type outside `DOC_TYPES`, so G3b decides it and
    records the decision: an unrecognised label is an unknown document, and the
    safe answer for an unknown document is the one this pipeline already gives it.
    Explicitly NOT treated as "not the money family" — that reading would route
    every typo onto the generic schema. Logged, because reaching here means a
    caller invented a type outside the closed enum."""
    with caplog.at_level("WARNING", logger="agents.extraction_agent"):
        resolved = resolve_extraction_profile("INBOUND", doc_type)
    assert resolved is resolve_direction_profile("INBOUND")
    assert resolved.schema is InvoiceExtractionSchema
    assert any("not in DOC_TYPES" in r.message for r in caplog.records)


def test_a_known_doc_type_does_not_log_a_warning(generic_flag_on, caplog):
    """The companion assertion to the one above: the warning has to mean
    something, so the ordinary path must be silent."""
    with caplog.at_level("WARNING", logger="agents.extraction_agent"):
        resolve_extraction_profile("INBOUND", "DELIVERY_NOTE")
        resolve_extraction_profile("INBOUND", "INVOICE")
    assert [r.message for r in caplog.records] == []


# =============================================================================
# Feature 27 (G4) — `classify_doc_type_node` + the conditional graph entry point
# =============================================================================
# E7 and §2A/A1's sequence:
#
#   _run_ocr (prebuilt-invoice, unconditional)
#     -> classify_doc_type -> classify (complexity) -> dynamic_qa -> extract -> verify
#
# The tests below split into three groups, and the split matters:
#
#   1. **Graph structure.** E3 does not say "the doc-type node does nothing when
#      the flag is off", it says the flag-off pipeline is byte-identical. So the
#      assertion is on the compiled graph's node set and edges — with the flag
#      off the node is ABSENT, not inert, and there is therefore no execution path
#      through it to reason about at all.
#   2. **Real runs through the real graph.** These are the first tests in this
#      repo that drive `run_extraction_agent` end to end (against a fake LLM),
#      because the claim being made is about execution order and profile
#      selection, and both are properties of a run rather than of a function.
#   3. **The one slice of G6 this task carries** — `extract_node`/`verify_node`
#      resolving through `resolve_extraction_profile`, which was dead code until a
#      node existed to put a real `doc_type` into state.
#
# Pure Python: no DB, no network, no real model call. Per hard rule 2 nothing here
# is a Postgres-backed verification of the pipeline, and none is claimed.

# A delivery challan whose title band is unambiguous, so the deterministic pass
# resolves it with no model call. The letterhead lines above the title are not
# decoration: without them a classifier that matched anywhere in the text rather
# than on a title line would pass these tests for the wrong reason.
_DELIVERY_CHALLAN_TEXT = (
    "Northbridge Manufacturing Ltd\n"
    "17 Industrial Estate, Pune 411019\n"
    "DELIVERY CHALLAN\n"
    "Challan No: DC-4471          Dated: 01/09/2026\n"
    "Item: M8 hex bolts, zinc plated          Qty: 250 NOS\n"
)

_TAX_INVOICE_TEXT = (
    "Northbridge Manufacturing Ltd\n"
    "GSTIN 27AABCS1429B1ZQ\n"
    "TAX INVOICE\n"
    "Invoice No: INV-2026-0447    Dated: 01/09/2026\n"
    "Item: M8 hex bolts    Qty: 250\n"
)

# Two disjoint synonyms in one printed title line — a real Indian document, and
# the case the deterministic pass is designed to send to the model rather than
# resolve by picking a winner (Gap 369's build note, decision 2).
_AMBIGUOUS_TEXT = (
    "Northbridge Manufacturing Ltd\n"
    "TAX INVOICE CUM DELIVERY NOTE\n"
    "Ref: 4471    Dated: 01/09/2026\n"
)


class _RecordingStructuredLLM:
    """The `with_structured_output(...)` half of a fake LLM.

    Returns a plain dict rather than a pydantic instance: `extract_node` accepts
    either (`hasattr(result, "dict")` / `isinstance(result, dict)`), and a dict
    keeps these tests off the schema-construction path, which G3's own tests
    already cover.
    """

    def __init__(self, payload, prompts):
        self._payload = payload
        self._prompts = prompts

    def invoke(self, prompt):
        self._prompts.append(prompt)
        return dict(self._payload)


class _RecordingLLM:
    def __init__(self, payload=None):
        self._payload = payload or {}
        self.schemas = []
        self.prompts = []

    def with_structured_output(self, schema):
        self.schemas.append(schema)
        return _RecordingStructuredLLM(self._payload, self.prompts)


def _pipeline_state(**extra):
    """A complete `ExtractionState` for a direct node call."""
    state = {
        "file_path": "tenant-a/delivery_challan.png",
        "ocr_text": _DELIVERY_CHALLAN_TEXT,
        "images": [],
        "extracted_data": None,
        "alerts": [],
        "status": "PROCESSING",
        "rules": None,
        "complexity": "STANDARD",
        "ocr_result": None,
        "retry_count": 0,
        "max_retries": 2,
        "feedback": [],
        "dynamic_qa_context": None,
        "flow_direction": "INBOUND",
        "tenant_id": "tenant-a",
        "doc_type": None,
        "doc_type_evidence": None,
        "doc_type_confidence": None,
    }
    state.update(extra)
    return state


def _node_names(compiled):
    """The compiled graph's own node set, minus langgraph's `__start__` sentinel."""
    return {name for name in compiled.nodes if not name.startswith("__")}


def _edges(compiled):
    return {(e.source, e.target) for e in compiled.get_graph().edges}


def _expected_log_trace(*node_names):
    return [ea._NODE_LOG_MESSAGES[name] for name in node_names]


def _referenced_globals(fn):
    """The global names a function's bytecode actually references.

    Used instead of matching on `inspect.getsource` for the two "this function
    does NOT do X" assertions below, because several of the functions under test
    *document* the thing being asserted absent ("the flag is not read here", "no
    second `tracked_llm_call` here") — and a source match would make an accurate
    docstring fail the test that is describing it.
    """
    return set(fn.__code__.co_names)


# --- Group 1: graph structure (E3's "byte-identical, testably") ---------------


def test_flag_off_the_compiled_graph_does_not_contain_the_doc_type_node_at_all():
    """E3's real assertion. Not "doc_type comes back None" — that would also be
    true of a node that ran and returned nothing. The node is not in the compiled
    graph, so there is no execution path through it to reason about."""
    assert ea.get_settings().ENABLE_GENERIC_EXTRACTION is False
    assert _node_names(ea.graph) == {"classify", "dynamic_qa", "extract", "verify"}
    assert "classify_doc_type" not in ea.graph.nodes


def test_flag_off_the_entry_point_is_still_the_complexity_classifier():
    """E3, verbatim: "The compiled graph's entry point is `classify`
    (complexity), the existing `classify_node`"."""
    assert ("__start__", "classify") in _edges(ea.graph)
    assert ("__start__", "classify_doc_type") not in _edges(ea.graph)


def test_flag_off_resolves_to_the_module_level_graph_object_itself():
    """Identity, not equivalence: the flag-off pipeline runs the same compiled
    object it ran before Feature 27 existed."""
    assert ea.resolve_extraction_graph() is ea.graph


def test_flag_on_the_graph_gains_exactly_one_node_and_two_edges(generic_flag_on):
    """The change is additive at the graph level too. `classify` keeps its
    position and its behaviour (E7) — the two classifications are orthogonal, and
    merging them would couple two things that change for different reasons."""
    on_graph = ea.resolve_extraction_graph()

    assert _node_names(on_graph) - _node_names(ea.graph) == {"classify_doc_type"}
    assert _node_names(ea.graph) - _node_names(on_graph) == set()
    assert _edges(on_graph) - _edges(ea.graph) == {
        ("__start__", "classify_doc_type"),
        ("classify_doc_type", "classify"),
    }
    # The only edge that goes away is the old entry edge; every downstream edge,
    # including the conditional retry edge back to `extract`, is untouched.
    assert _edges(ea.graph) - _edges(on_graph) == {("__start__", "classify")}


def test_flag_on_the_entry_point_is_the_doc_type_node_feeding_the_complexity_node(
    generic_flag_on,
):
    on_graph = ea.resolve_extraction_graph()
    assert ("__start__", "classify_doc_type") in _edges(on_graph)
    assert ("classify_doc_type", "classify") in _edges(on_graph)


def test_each_flag_state_compiles_its_own_graph_once_and_reuses_it(generic_flag_on):
    """Two compiled graphs, cached, one per flag state — the replacement for the
    single import-time `graph = builder.compile()`, whose structure could not
    depend on a value read later."""
    assert ea.resolve_extraction_graph() is ea.resolve_extraction_graph()
    assert ea.resolve_extraction_graph() is not ea.graph


def test_the_flag_is_read_at_build_time_not_inside_the_node():
    """The distinction E3 turns on, asserted against the source so it cannot drift
    back into a runtime branch: the node itself never consults the flag, and the
    conditional lives in the graph builder."""
    node_globals = _referenced_globals(ea.classify_doc_type_node)
    assert "get_settings" not in node_globals
    assert "ENABLE_GENERIC_EXTRACTION" not in node_globals

    # ... and the conditional lives in the builder, on a parameter, so each
    # compiled graph's node set is fixed the moment it is built.
    builder_code = ea._build_extraction_graph.__code__
    assert "include_doc_type_classifier" in builder_code.co_varnames
    assert "set_entry_point" in builder_code.co_names
    assert {"classify_doc_type", "classify"} <= {
        const for const in builder_code.co_consts if isinstance(const, str)
    }


def test_the_doc_type_node_has_a_friendly_log_line_like_every_other_node():
    """Gap 2's FE terminal feed. Without an entry the user would see the raw
    "Running classify_doc_type..." fallback."""
    assert set(ea._NODE_LOG_MESSAGES) == {
        "classify_doc_type",
        "classify",
        "dynamic_qa",
        "extract",
        "verify",
    }


# --- Group 2: real runs through the real graph --------------------------------


def test_flag_off_a_full_run_never_calls_the_classifier_and_uses_the_invoice_schema(
    monkeypatch,
):
    """The end-to-end half of E3, on the founder's own symptom document: a delivery
    challan with the flag off is still extracted on `InvoiceExtractionSchema`, on
    the inbound status vocabulary, and the classifier is never reached — asserted
    on a call count, not on a `None` in the output."""
    classifier = Mock(side_effect=AssertionError("the classifier must not run with the flag off"))
    monkeypatch.setattr(ea, "classify_doc_type", classifier)
    llm = _RecordingLLM({"items": [{"description": "M8 hex bolts", "quantity": 250.0}]})
    monkeypatch.setattr(ea, "get_llm", lambda **kwargs: llm)
    trace = []

    result = ea.run_extraction_agent(
        file_path="tenant-a/delivery_challan.png",
        ocr_text=_DELIVERY_CHALLAN_TEXT,
        tenant_id="tenant-a",
        on_log=trace.append,
    )

    classifier.assert_not_called()
    assert llm.schemas == [InvoiceExtractionSchema]
    assert result["status"] == "COMPLETED"
    assert trace == _expected_log_trace("classify", "dynamic_qa", "extract", "verify")


def test_flag_on_the_doc_type_node_runs_before_the_complexity_node(
    generic_flag_on, monkeypatch
):
    """§2A/A1's sequence, asserted as an execution trace rather than as an edge
    list: classify_doc_type, then classify, then dynamic_qa, extract, verify."""
    llm = _RecordingLLM(
        {"doc_type": "DELIVERY_NOTE", "items": [{"description": "bolts", "quantity": 250.0}]}
    )
    monkeypatch.setattr(ea, "get_llm", lambda **kwargs: llm)
    trace = []

    with patch.object(dtc, "get_llm") as classifier_llm:
        ea.run_extraction_agent(
            file_path="tenant-a/delivery_challan.png",
            ocr_text=_DELIVERY_CHALLAN_TEXT,
            tenant_id="tenant-a",
            on_log=trace.append,
        )

    assert trace == _expected_log_trace(
        "classify_doc_type", "classify", "dynamic_qa", "extract", "verify"
    )
    # T-C-1's assertion shape, at pipeline level: an unambiguous printed title is
    # a fact about the document, and facts belong in code. No model call at all.
    classifier_llm.assert_not_called()


def test_flag_on_a_classified_delivery_note_reaches_the_generic_profile(
    generic_flag_on, monkeypatch
):
    """The whole point of G4: the classified type is in state by the time
    `extract_node` and `verify_node` resolve their profile, so a delivery challan
    is extracted on `GenericDocumentSchema` and verified against the
    EXTRACTED/EXTRACT_FAILED vocabulary rather than COMPLETED/AUDIT_REQUIRED."""
    llm = _RecordingLLM(
        {"doc_type": "DELIVERY_NOTE", "items": [{"description": "bolts", "quantity": 250.0}]}
    )
    monkeypatch.setattr(ea, "get_llm", lambda **kwargs: llm)

    result = ea.run_extraction_agent(
        file_path="tenant-a/delivery_challan.png",
        ocr_text=_DELIVERY_CHALLAN_TEXT,
        tenant_id="tenant-a",
    )

    assert llm.schemas == [GenericDocumentSchema]
    assert result["status"] == "EXTRACTED"
    assert result["alerts"] == []


def test_flag_on_an_invoice_still_runs_on_the_invoice_schema(generic_flag_on, monkeypatch):
    """A2's guarantee at pipeline level, and the shape T-R-6 will prove properly
    once §7 task F's fixtures exist: turning the flag on changes nothing about an
    invoice. It classifies INVOICE, which is the money family, which resolves to
    the profile it always had."""
    llm = _RecordingLLM({"vendor_name": "Northbridge", "items": []})
    monkeypatch.setattr(ea, "get_llm", lambda **kwargs: llm)

    with patch.object(dtc, "get_llm") as classifier_llm:
        result = ea.run_extraction_agent(
            file_path="tenant-a/tax_invoice.png",
            ocr_text=_TAX_INVOICE_TEXT,
            tenant_id="tenant-a",
        )

    classifier_llm.assert_not_called()
    assert llm.schemas == [InvoiceExtractionSchema]
    assert result["status"] == "COMPLETED"


def test_the_node_writes_the_type_the_evidence_and_the_confidence(generic_flag_on):
    """E7: the decision AND its evidence phrase go to state, so a misclassification
    is reviewable after the fact rather than only being a wrong answer. The
    confidence rides along because it is a column on E10's `documents` table and
    because N2's threshold calibration has nothing to calibrate against without
    it."""
    with patch.object(dtc, "get_llm") as classifier_llm:
        update = ea.classify_doc_type_node(_pipeline_state())

    classifier_llm.assert_not_called()
    assert update == {
        "doc_type": "DELIVERY_NOTE",
        "doc_type_evidence": "DELIVERY CHALLAN",
        "doc_type_confidence": 1.0,
        # A6/R8: the node now also derives the classification attributes from the
        # same OCR text. None here because a bare "DELIVERY CHALLAN" carries no
        # tax IDs, no fiscal markers and no correction marker -- which is the
        # common case and is why the key is None rather than {}.
        "doc_attributes": None,
    }


def test_the_node_emits_no_telemetry_event_of_its_own_on_the_deterministic_path():
    """E7 asks for exactly ONE `tracked_llm_call` on the fallback path, and G2 put
    it inside `_classify_with_llm` — the only place that knows a call is actually
    being made. A second wrapper here would emit an event for the deterministic
    path, which E7 requires to cost nothing and show as nothing, and would
    double-count the fallback."""
    with patch.object(ea, "tracked_llm_call") as node_telemetry, patch.object(
        dtc, "get_llm"
    ) as classifier_llm:
        ea.classify_doc_type_node(_pipeline_state())

    node_telemetry.assert_not_called()
    classifier_llm.assert_not_called()
    assert "tracked_llm_call" not in _referenced_globals(ea.classify_doc_type_node)


def test_an_ambiguous_title_falls_back_to_the_model_under_the_right_telemetry_key():
    """The other half of E7's telemetry rule: when the title band genuinely cannot
    decide ("TAX INVOICE CUM DELIVERY NOTE" — two disjoint synonyms in one printed
    line), the fallback runs and fires exactly one `extraction.classify_doc_type`
    event, so that event count stays a direct measure of how often the
    deterministic pass was not enough."""
    llm = Mock()
    llm.with_structured_output.return_value.invoke.return_value = dtc.DocTypeClassification(
        doc_type="DELIVERY_NOTE", confidence=0.9, evidence="TAX INVOICE CUM DELIVERY NOTE"
    )

    with patch.object(dtc, "get_llm", return_value=llm) as classifier_llm, patch.object(
        dtc, "tracked_llm_call"
    ) as tracked:
        update = ea.classify_doc_type_node(
            _pipeline_state(ocr_text=_AMBIGUOUS_TEXT, tenant_id="tenant-a")
        )

    classifier_llm.assert_called_once()
    tracked.assert_called_once()
    assert tracked.call_args.args[0] == "extraction.classify_doc_type"
    assert tracked.call_args.kwargs["tenant_id"] == "tenant-a"
    assert update["doc_type"] == "DELIVERY_NOTE"


def test_a_classifier_failure_degrades_to_unclassified_rather_than_failing_the_run(
    monkeypatch, caplog
):
    """`classify_doc_type` documents itself as never raising, so reaching this
    branch means something structural. The safe answer for a document we cannot
    type is the one this pipeline already gives it: `doc_type=None` sends
    `resolve_extraction_profile` straight back to today's direction profile. Same
    shape as `dynamic_qa_node`'s except, for the same reason — a pre-analysis step
    must not be able to take down the extraction it precedes."""
    monkeypatch.setattr(ea, "classify_doc_type", Mock(side_effect=RuntimeError("boom")))

    with caplog.at_level("WARNING", logger="agents.extraction_agent"):
        update = ea.classify_doc_type_node(_pipeline_state())

    assert update == {
        "doc_type": None,
        "doc_type_evidence": None,
        "doc_type_confidence": None,
        # A6/R8: the failure path clears the attributes too. A half-populated row
        # -- attributes from a run whose type derivation blew up -- would be worse
        # than an empty one, because the rubric reads both.
        "doc_attributes": None,
    }
    assert any("classification failed" in r.message for r in caplog.records)


def test_the_node_reads_ocr_text_from_state_and_carries_the_tenant_for_telemetry_only(
    monkeypatch,
):
    """The two state keys the node actually consumes, pinned so a later change
    cannot quietly start reading something invoice-specific out of `ocr_result`
    (§8 trap 1: `prebuilt-invoice` force-fits `VendorName`/`InvoiceTotal` onto a
    delivery note at low confidence, so those fields are confident wrong data for
    exactly the documents this node exists to identify)."""
    spy = Mock(
        return_value={
            "doc_type": "GRN",
            "doc_type_evidence": "GOODS RECEIPT NOTE",
            "doc_type_confidence": 1.0,
            "doc_type_method": "deterministic",
            "doc_type_reason": None,
        }
    )
    monkeypatch.setattr(ea, "classify_doc_type", spy)
    ocr_result = {"content": "ignored", "field_confidence": {"VendorName": 0.11}}

    ea.classify_doc_type_node(_pipeline_state(ocr_result=ocr_result, tenant_id="tenant-b"))

    assert spy.call_args.args[0] == _DELIVERY_CHALLAN_TEXT
    assert spy.call_args.args[1] is ocr_result
    assert spy.call_args.kwargs == {"tenant_id": "tenant-b"}


# --- Group 3: the G6 slice — the profile actually reaches the two nodes --------


def test_extract_node_extracts_a_classified_delivery_note_on_the_generic_schema(
    generic_flag_on, monkeypatch
):
    """`resolve_extraction_profile` was dead code until this task: `extract_node`
    called `resolve_direction_profile` directly, so no `doc_type` could change
    anything. This is the assertion that it no longer is."""
    llm = _RecordingLLM({"doc_type": "DELIVERY_NOTE"})
    monkeypatch.setattr(ea, "get_llm", lambda **kwargs: llm)

    ea.extract_node(_pipeline_state(doc_type="DELIVERY_NOTE"))

    assert llm.schemas == [GenericDocumentSchema]


def test_extract_node_ignores_the_doc_type_when_the_flag_is_off(monkeypatch):
    """The same state, the same classified type, flag off → `InvoiceExtractionSchema`.
    The state key existing is not what changes behaviour; the flag is."""
    assert ea.get_settings().ENABLE_GENERIC_EXTRACTION is False
    llm = _RecordingLLM({"vendor_name": "Northbridge"})
    monkeypatch.setattr(ea, "get_llm", lambda **kwargs: llm)

    ea.extract_node(_pipeline_state(doc_type="DELIVERY_NOTE"))

    assert llm.schemas == [InvoiceExtractionSchema]


@pytest.mark.parametrize(
    "doc_type, expected_status",
    [("DELIVERY_NOTE", "EXTRACTED"), ("INVOICE", "COMPLETED"), (None, "COMPLETED")],
)
def test_verify_node_uses_the_status_vocabulary_of_the_schema_it_was_extracted_on(
    generic_flag_on, doc_type, expected_status
):
    """`verify_node` has to resolve the *same* profile `extract_node` did, or a
    delivery note extracted on `GenericDocumentSchema` would come back COMPLETED —
    an inbound-invoice status for a document with no audit lifecycle.

    Deliberately NOT a rubric test — it is about the status *vocabulary*, which
    comes from the profile, not from the rubric. The payload is priceless and
    therefore alert-free either way, so this test's result is unchanged by G5's
    gating; the rubric tests are the G5 section at the end of this file."""
    state = _pipeline_state(
        doc_type=doc_type,
        extracted_data={"items": [{"description": "M8 hex bolts", "quantity": 250.0}]},
        retry_count=1,
    )

    assert ea.verify_node(state)["status"] == expected_status


def test_the_multimodal_prompt_binds_the_classified_type_instead_of_defaulting_to_other(
    generic_flag_on, monkeypatch
):
    """G3's hand-off contract, closed here. `build_generic_multimodal_prompt`'s
    `doc_type` is a trailing keyword with a default so the builder stays
    call-compatible with `_DirectionProfile.build_multimodal_prompt`'s
    three-argument signature — called unbound it would serve the conservative
    OTHER overlay to a document whose type we already know."""
    monkeypatch.setattr(config.settings, "LLM_PROVIDER", "azure")
    llm = _RecordingLLM({"doc_type": "DELIVERY_NOTE"})
    monkeypatch.setattr(ea, "get_llm", lambda **kwargs: llm)

    ea.extract_node(
        _pipeline_state(doc_type="DELIVERY_NOTE", images=["data:image/png;base64,AAAA"])
    )

    text = llm.prompts[0][0].content[0]["text"]
    assert _OVERLAYS["DELIVERY_NOTE"] in text
    assert _OVERLAYS["OTHER"] not in text


def test_the_invoice_multimodal_builder_is_still_called_unbound_and_unchanged(monkeypatch):
    """The binding above must touch nothing else: every non-GENERIC profile still
    goes through `profile.build_multimodal_prompt(ocr_text, images, rules)`
    exactly as it did, with no `doc_type` anywhere near it."""
    monkeypatch.setattr(config.settings, "LLM_PROVIDER", "azure")
    llm = _RecordingLLM({"vendor_name": "Northbridge"})
    monkeypatch.setattr(ea, "get_llm", lambda **kwargs: llm)

    ea.extract_node(
        _pipeline_state(doc_type="DELIVERY_NOTE", images=["data:image/png;base64,AAAA"])
    )

    text = llm.prompts[0][0].content[0]["text"]
    assert text.startswith("You are an expert invoice processing agent.")
    assert _OVERLAYS["DELIVERY_NOTE"] not in text


# =============================================================================
# Feature 27 (G5) — `_VerificationRubric` / `_RUBRIC_BY_DOC_TYPE` + `verify_node`
# =============================================================================
# E6, keyed on the FAMILY and not on the type, and E4's family table as the single
# declaration. This is the slice the feature exists for: `verify_node` has always
# run the money rubric unconditionally, so a delivery note — quantities, no prices,
# by design — came back covered in discrepancies on a document that was perfectly
# correct (§1, the founder's actual symptom).
#
# The tests below are written so that each one fails for exactly one reason:
#
#   * **T-R-1** — a `DELIVERY_NOTE` with quantities and no prices produces zero
#     arithmetic alerts and a passing status. Asserted on the check functions
#     being **not called at all**, not merely on an empty alert list:
#     `verify_line_items_math` already returns None when `subtotal` is None, so an
#     alert-count assertion alone would pass against completely ungated code and
#     prove nothing about the rubric.
#   * **T-R-2** — a `CONTRACT` with no grand total produces no missing-total alert,
#     while a contract that *does* print inconsistent totals still gets the
#     arithmetic ("arithmetic checks run where totals are printed", E4).
#   * **T-R-3** — an `INVOICE` produces the identical alert set, the identical
#     status, and the identical *calls* it produces with the flag off. This is the
#     regression proof; equality of alerts alone would still pass if the two checks
#     were called with different arguments and happened to agree.
#   * **T-R-4** — `OTHER` records alerts but never sets a review status, with a
#     `PURCHASE_ORDER` control on the same document proving `advisory_only` is what
#     changed the status rather than the alerts having gone away.
#   * **Flag OFF never consults the map** — asserted with a recording dict
#     substituted for `_RUBRIC_BY_DOC_TYPE`, so "no lookup happened" is a direct
#     observation rather than an inference from an identical result.
#
# Pure Python: no DB, no network, no model call. Per hard rule 2 nothing here is a
# Postgres-backed verification of the pipeline, and none is claimed.

_RUBRICS = ea._RUBRIC_BY_DOC_TYPE

_QUANTITY_DOC_TYPES = tuple(dt for dt in DOC_TYPES if DOC_TYPE_FAMILY[dt] == QUANTITY_FAMILY)
_COMMITMENT_DOC_TYPES = tuple(dt for dt in DOC_TYPES if DOC_TYPE_FAMILY[dt] == COMMITMENT_FAMILY)


# A delivery challan as it actually prints: quantities, units, no money anywhere.
# This is the founder's document.
_NO_PRICE_DELIVERY_NOTE = {
    "doc_type": "DELIVERY_NOTE",
    "party_name": "Northbridge Manufacturing Ltd",
    "counterparty_name": "Sunrise Traders",
    "doc_number": "DC-4471",
    "currency": None,
    "subtotal": None,
    "tax_amount": None,
    "discount_amount": None,
    "grand_total": None,
    "items": [
        {"description": "M8 hex bolts, zinc plated", "quantity": 250.0, "uom": "NOS",
         "unit_price": None, "amount": None},
        {"description": "M8 washers", "quantity": 500.0, "uom": "NOS",
         "unit_price": None, "amount": None},
    ],
}

# The same shape a document takes when its printed arithmetic genuinely does not
# reconcile: 2 x 10.00 is not 90.00, and 100.00 + 10.00 is not 500.00. Every figure
# below appears verbatim in `_INCONSISTENT_OCR_TEXT`, so the five faithfulness
# checks (Gaps 33/36/43/44/46) all pass and the ONLY alerts these tests can produce
# are the two arithmetic ones the rubric gates. That is deliberate: it makes an
# alert list an exact, readable assertion instead of a fuzzy count.
_INCONSISTENT_MONEY_DATA = {
    "currency": "INR",
    "subtotal": 100.0,
    "tax_amount": 10.0,
    "grand_total": 500.0,
    "items": [{"description": "M8 hex bolts", "quantity": 2.0, "unit_price": 10.0, "amount": 90.0}],
}

_INCONSISTENT_OCR_TEXT = (
    "Northbridge Manufacturing Ltd\n"
    "M8 hex bolts    2 @ 10.00    90.00\n"
    "Subtotal: 100.00\n"
    "Tax: 10.00\n"
    "Grand Total: 500.00\n"
)

_ARITHMETIC_ALERT_TYPES = {"line_item_calculation_mismatch", "tax_mismatch"}


def _alert_types(alerts):
    return [a["type"] for a in alerts if isinstance(a, dict)]


class _RecordingRubricMap(dict):
    """`_RUBRIC_BY_DOC_TYPE` that remembers every lookup made against it.

    Used for the flag-OFF proof. "The map was never consulted" is a claim about
    behaviour that an identical-output assertion cannot make: today's ungated code
    and correctly-gated-but-money-rubric code produce the same alerts for an
    invoice, and both would pass. This records the actual reads.
    """

    def __init__(self, real):
        super().__init__(real)
        self.lookups = []

    def get(self, key, default=None):
        self.lookups.append(key)
        return super().get(key, default)

    def __getitem__(self, key):
        self.lookups.append(key)
        return super().__getitem__(key)


@pytest.fixture
def recording_rubric_map(monkeypatch):
    recorder = _RecordingRubricMap(ea._RUBRIC_BY_DOC_TYPE)
    monkeypatch.setattr(ea, "_RUBRIC_BY_DOC_TYPE", recorder)
    return recorder


@pytest.fixture
def spied_math_checks(monkeypatch):
    """Both arithmetic checks, wrapped so they still do their real work.

    `wraps=` rather than a stub: the tests below assert on *whether* and *with what*
    they were called, and several of them also assert on the alerts those real calls
    produce, which a stub would have to fake.
    """
    spies = {
        "line_items": Mock(wraps=ea.verify_line_items_math),
        "totals": Mock(wraps=ea.verify_totals_math),
    }
    monkeypatch.setattr(ea, "verify_line_items_math", spies["line_items"])
    monkeypatch.setattr(ea, "verify_totals_math", spies["totals"])
    return spies


# --- The table itself (E4/E6) --------------------------------------------------


@pytest.mark.parametrize("doc_type", DOC_TYPES)
def test_every_doc_type_in_the_closed_enum_has_a_rubric(doc_type):
    """E6: "one entry per enum value". A type with no rubric would fall through to
    `.get(...) is None`, i.e. to today's unconditional money checks — safe, but
    silently so, and this is the loop that makes adding an eleventh type fail here
    rather than in production."""
    assert doc_type in _RUBRICS
    assert isinstance(_RUBRICS[doc_type], ea._VerificationRubric)


def test_the_rubric_map_holds_exactly_the_closed_enum_and_no_more():
    assert set(_RUBRICS) == set(DOC_TYPES)


@pytest.mark.parametrize("doc_type", DOC_TYPES)
def test_each_types_rubric_is_its_familys_rubric_by_identity(doc_type):
    """E6's real design constraint: the rubric is keyed on the FAMILY, not the type.
    Asserted by identity against `_RUBRIC_BY_FAMILY[DOC_TYPE_FAMILY[...]]`, so a
    hand-written per-type entry that happens to hold equal values would still fail —
    that is the `if doc_type == "DELIVERY_NOTE"` chain E6 rules out, spelled as a
    table."""
    assert _RUBRICS[doc_type] is ea._RUBRIC_BY_FAMILY[DOC_TYPE_FAMILY[doc_type]]


def test_the_family_mapping_is_read_from_the_classifier_module_not_re_derived():
    """The provisional `QUOTATION` → COMMITMENT decision (Gap 369's second open
    decision) lives in `DOC_TYPE_FAMILY` and is still the founder's to settle. This
    asserts G5 reads that map rather than restating it, so when the decision is made
    it is made in one file."""
    assert DOC_TYPE_FAMILY["QUOTATION"] == COMMITMENT_FAMILY
    assert _RUBRICS["QUOTATION"] is _RUBRICS["PURCHASE_ORDER"] is _RUBRICS["CONTRACT"]


@pytest.mark.parametrize("doc_type", _MONEY_DOC_TYPES)
def test_the_money_rubric_is_todays_behaviour_written_down(doc_type):
    """E4: the money family's rubric is "today's rubric, unchanged". Every boolean
    True, nothing optional, nothing advisory — which is what makes T-R-3 provable
    rather than hopeful."""
    rubric = _RUBRICS[doc_type]
    assert rubric.run_line_item_math is True
    assert rubric.run_totals_math is True
    assert rubric.require_currency is True
    assert rubric.price_fields_optional is False
    assert rubric.advisory_only is False


@pytest.mark.parametrize("doc_type", _QUANTITY_DOC_TYPES)
def test_the_quantity_rubric_attempts_no_arithmetic_and_treats_prices_as_optional(doc_type):
    """E4's quantity family (`DELIVERY_NOTE`, `GRN`): "Absent price is not a
    discrepancy... no total-arithmetic check attempted unless prices are actually
    present"."""
    rubric = _RUBRICS[doc_type]
    assert rubric.run_line_item_math is False
    assert rubric.run_totals_math is False
    assert rubric.price_fields_optional is True
    assert rubric.require_currency is False
    assert rubric.advisory_only is False


@pytest.mark.parametrize("doc_type", _COMMITMENT_DOC_TYPES)
def test_the_commitment_rubric_runs_arithmetic_where_printed(doc_type):
    """E4: "Arithmetic checks run where totals are printed, but an unpriced or
    partially-priced schedule line is normal, and a CONTRACT frequently has no grand
    total at all... Missing-total is not a failure for this family."

    Both math flags stay ON — that is the "where printed" half — and the
    missing-total half needs no flag at all, because `verify_totals_math` already
    returns None when `grand_total` or `subtotal` is None and the GENERIC profile
    raises no `missing_required_field`. T-R-2 asserts that end to end."""
    rubric = _RUBRICS[doc_type]
    assert rubric.run_line_item_math is True
    assert rubric.run_totals_math is True
    assert rubric.price_fields_optional is True
    assert rubric.advisory_only is False


def test_the_other_rubric_is_the_money_rubric_in_advisory_mode():
    """E4, verbatim: "`OTHER` runs the money rubric in advisory mode only: alerts
    are recorded but never set a review status"."""
    rubric = _RUBRICS["OTHER"]
    assert rubric.run_line_item_math is True
    assert rubric.run_totals_math is True
    assert rubric.advisory_only is True
    assert _RUBRICS["OTHER"] is not _RUBRICS["INVOICE"]


@pytest.mark.parametrize("doc_type", DOC_TYPES)
def test_only_the_money_family_trusts_document_intelligences_invoice_fields(doc_type):
    """A1: `run_field_confidence` / `run_di_tax_backfill` are True "for the money
    family only". Declared by G5 so G7 has something to gate on; G7 is what makes
    them do anything (the scope test above asserts they are still unread)."""
    expected = DOC_TYPE_FAMILY[doc_type] == MONEY_FAMILY
    assert _RUBRICS[doc_type].run_field_confidence is expected
    assert _RUBRICS[doc_type].run_di_tax_backfill is expected


@pytest.mark.parametrize("doc_type", DOC_TYPES)
def test_each_rubrics_status_pair_agrees_with_the_profile_it_will_be_used_with(
    generic_flag_on, doc_type
):
    """E6 puts "the status pair to emit" on the rubric; A2 later put it on
    `_DirectionProfile` and G4 wired `verify_node` to emit the *profile's*. Two
    sources for one decision is how they drift, so the rubric's pair is carried for
    readability and pinned here to the profile resolved on the one path where the
    rubric is actually consulted (flag ON + INBOUND)."""
    rubric = _RUBRICS[doc_type]
    profile = resolve_extraction_profile("INBOUND", doc_type)
    assert (rubric.passed_status, rubric.review_status) == (
        profile.passed_status,
        profile.review_status,
    )


# --- `resolve_verification_rubric`: when the map is consulted at all -----------


def test_flag_off_never_consults_the_rubric_map(recording_rubric_map):
    """E3/E6: "With the flag OFF, `verify_node` never consults the map." Asserted on
    the map itself, not on the output — an invoice produces the same alerts either
    way, so an equality assertion here would pass against a fully-gated
    implementation and prove nothing about the flag."""
    assert ea.get_settings().ENABLE_GENERIC_EXTRACTION is False

    for doc_type in DOC_TYPES:
        assert ea.resolve_verification_rubric("INBOUND", doc_type) is None

    assert recording_rubric_map.lookups == []


def test_flag_off_verify_node_never_consults_the_rubric_map_either(recording_rubric_map):
    """The same assertion one level up, through the real node, for the state that
    would otherwise reach the quantity rubric."""
    assert ea.get_settings().ENABLE_GENERIC_EXTRACTION is False

    ea.verify_node(
        _pipeline_state(doc_type="DELIVERY_NOTE", extracted_data=dict(_NO_PRICE_DELIVERY_NOTE))
    )

    assert recording_rubric_map.lookups == []


def test_flag_on_the_map_is_consulted_exactly_once_with_the_classified_type(
    generic_flag_on, recording_rubric_map
):
    ea.verify_node(
        _pipeline_state(doc_type="DELIVERY_NOTE", extracted_data=dict(_NO_PRICE_DELIVERY_NOTE))
    )

    assert recording_rubric_map.lookups == ["DELIVERY_NOTE"]


def test_flag_on_but_unclassified_never_consults_the_map(generic_flag_on, recording_rubric_map):
    """`doc_type is None` — the node has not run, or a caller supplied an override.
    Fail-closed to today's checks, the same answer `resolve_extraction_profile`
    gives for the same input."""
    assert ea.resolve_verification_rubric("INBOUND", None) is None
    assert recording_rubric_map.lookups == []


@pytest.mark.parametrize("flow_direction", ["OUTBOUND", "REFERENCE"])
def test_outbound_and_reference_never_consult_the_map(
    generic_flag_on, recording_rubric_map, flow_direction
):
    """A2, verbatim: doc_type "is still classified and recorded for both — it simply
    never changes their schema **or rubric**". An OUTBOUND document is the tenant's
    own AR invoice and its consumers are written against the arithmetic."""
    for doc_type in DOC_TYPES:
        assert ea.resolve_verification_rubric(flow_direction, doc_type) is None

    assert recording_rubric_map.lookups == []


@pytest.mark.parametrize("flow_direction", [None, ""])
def test_absent_direction_resolves_inbound_and_is_therefore_eligible(
    generic_flag_on, flow_direction
):
    """The same normalising expression `resolve_direction_profile` and
    `resolve_extraction_profile` use, so the three cannot drift about which
    documents Feature 27 applies to."""
    assert ea.resolve_verification_rubric(flow_direction, "DELIVERY_NOTE") is _RUBRICS[
        "DELIVERY_NOTE"
    ]


@pytest.mark.parametrize("doc_type", ["delivery_note", "  Delivery_Note  "])
def test_doc_type_is_normalised_before_the_rubric_lookup(generic_flag_on, doc_type):
    """`run_extraction_agent`'s caller-supplied override is free text, and a
    lower-cased `"delivery_note"` silently getting the money rubric is exactly the
    false-discrepancy this feature removes."""
    assert ea.resolve_verification_rubric("INBOUND", doc_type) is _RUBRICS["DELIVERY_NOTE"]


def test_an_unknown_doc_type_falls_closed_to_todays_checks_and_warns(generic_flag_on, caplog):
    """Fail-closed, same as `resolve_extraction_profile`'s unknown-type branch and
    for the same reason: an unrecognised label is an unknown document. Logged, not
    silent — reaching here means a caller invented a type outside the closed enum."""
    with caplog.at_level("WARNING"):
        assert ea.resolve_verification_rubric("INBOUND", "LIEFERSCHEIN") is None

    assert "LIEFERSCHEIN" in caplog.text


# --- T-R-1: the founder's document ---------------------------------------------


@pytest.mark.parametrize("doc_type", _QUANTITY_DOC_TYPES)
def test_t_r_1_a_delivery_note_with_no_prices_raises_no_arithmetic_alerts(
    generic_flag_on, spied_math_checks, doc_type
):
    """**T-R-1 — the bug this whole feature was filed for.** Quantities, no prices,
    zero arithmetic alerts, a passing status.

    The load-bearing assertion is `assert_not_called`, not the empty alert list:
    `verify_line_items_math` returns None when `subtotal` is None and
    `verify_totals_math` returns None when `grand_total` is None, so an
    alerts-only assertion would pass against completely ungated code. What is being
    proved here is that the checks were never attempted."""
    result = ea.verify_node(
        _pipeline_state(doc_type=doc_type, extracted_data=dict(_NO_PRICE_DELIVERY_NOTE))
    )

    spied_math_checks["line_items"].assert_not_called()
    spied_math_checks["totals"].assert_not_called()
    assert result["alerts"] == []
    assert result["status"] == "EXTRACTED"
    assert result["feedback"] == []


def test_t_r_1_the_same_delivery_note_under_the_flag_off_still_runs_the_money_checks(
    spied_math_checks,
):
    """The negative half of T-R-1, kept as a test rather than as a claim: with the
    flag off this document takes the identical path it always has — both checks
    attempted, both returning None because the fields are absent, an
    inbound-invoice status. The difference the flag makes is visible here."""
    assert ea.get_settings().ENABLE_GENERIC_EXTRACTION is False

    result = ea.verify_node(
        _pipeline_state(doc_type="DELIVERY_NOTE", extracted_data=dict(_NO_PRICE_DELIVERY_NOTE))
    )

    spied_math_checks["line_items"].assert_called_once()
    spied_math_checks["totals"].assert_called_once()
    assert result["status"] == "COMPLETED"


def test_a_delivery_note_that_does_print_prices_gets_the_money_checks_additionally(
    generic_flag_on, spied_math_checks
):
    """E4's exact wording for the quantity family: "no total-arithmetic check
    attempted **unless prices are actually present, in which case the money checks
    run additionally, not instead**". A packing slip that does carry values is still
    arithmetic, and a wrong one should still be caught."""
    priced_delivery_note = dict(_NO_PRICE_DELIVERY_NOTE)
    priced_delivery_note.update(_INCONSISTENT_MONEY_DATA)

    result = ea.verify_node(
        _pipeline_state(
            doc_type="DELIVERY_NOTE",
            extracted_data=priced_delivery_note,
            ocr_text=_INCONSISTENT_OCR_TEXT,
        )
    )

    spied_math_checks["line_items"].assert_called_once()
    spied_math_checks["totals"].assert_called_once()
    assert set(_alert_types(result["alerts"])) == _ARITHMETIC_ALERT_TYPES
    assert result["status"] == "EXTRACT_FAILED"


@pytest.mark.parametrize(
    "field, value",
    [
        ("grand_total", 0.0),
        ("subtotal", 0.0),
        ("tax_amount", 0.0),
        ("discount_amount", 0.0),
    ],
)
def test_a_printed_zero_counts_as_a_price_being_present(field, value):
    """Gap 283's truthiness class, applied to the escalation test. A genuinely
    printed `0.00` is a figure the document stated; `not 0.0` and `not None` are
    both True and treating them alike is how that bug happened the first time."""
    assert ea._prices_present({field: value}) is True
    assert ea._prices_present({field: None}) is False


def test_prices_present_reads_line_items_as_well_as_the_totals_block():
    assert ea._prices_present(_NO_PRICE_DELIVERY_NOTE) is False
    assert ea._prices_present({"items": [{"description": "x", "quantity": 2.0}]}) is False
    assert ea._prices_present({"items": [{"description": "x", "unit_price": 10.0}]}) is True
    assert ea._prices_present({"items": [{"description": "x", "amount": 0.0}]}) is True
    assert ea._prices_present(None) is False
    assert ea._prices_present({}) is False


# --- T-R-2: the contract with no grand total -----------------------------------


def test_t_r_2_a_contract_with_no_grand_total_produces_no_missing_total_alert(
    generic_flag_on, spied_math_checks
):
    """**T-R-2.** E4: a `CONTRACT` "frequently has no grand total at all (rate cards,
    framework agreements). Missing-total is not a failure for this family."

    Note what is asserted: `verify_totals_math` **is** called (commitment runs
    arithmetic where printed — the rubric does not switch it off) and produces
    nothing, and no `missing_required_field` appears either, because the GENERIC
    profile has none. Missing-total being a non-failure is a property of the
    existing checks plus the profile, not of a new branch."""
    rate_card = {
        "doc_type": "CONTRACT",
        "party_name": "Northbridge Manufacturing Ltd",
        "currency": "INR",
        "subtotal": None,
        "tax_amount": None,
        "grand_total": None,
        "items": [
            {"description": "M8 hex bolts, per 1000", "unit_price": 4400.0, "quantity": None,
             "amount": None},
        ],
        "payment_terms": "Net 45",
        "notes": "Framework agreement, validity 01/09/2026 - 31/08/2027. No committed volume.",
    }

    result = ea.verify_node(
        _pipeline_state(
            doc_type="CONTRACT",
            extracted_data=rate_card,
            ocr_text="MASTER SUPPLY AGREEMENT\nM8 hex bolts, per 1000: 4400.00\n",
        )
    )

    spied_math_checks["totals"].assert_called_once()
    assert result["alerts"] == []
    assert result["status"] == "EXTRACTED"


def test_a_contract_that_does_print_inconsistent_totals_is_still_checked(
    generic_flag_on, spied_math_checks
):
    """The other half of E4's commitment rule. "Missing-total is not a failure" is
    not "totals are never checked" — a PO or contract that prints arithmetic which
    does not reconcile is still worth an alert, and this is the test that would fail
    if the commitment rubric were written as a copy of the quantity one."""
    result = ea.verify_node(
        _pipeline_state(
            doc_type="PURCHASE_ORDER",
            extracted_data=dict(_INCONSISTENT_MONEY_DATA),
            ocr_text=_INCONSISTENT_OCR_TEXT,
        )
    )

    spied_math_checks["line_items"].assert_called_once()
    spied_math_checks["totals"].assert_called_once()
    assert set(_alert_types(result["alerts"])) == _ARITHMETIC_ALERT_TYPES
    assert result["status"] == "EXTRACT_FAILED"


# --- T-R-3: the regression proof ------------------------------------------------


def _verify_invoice_and_capture(monkeypatch, doc_type):
    """Run `verify_node` over the same inconsistent invoice and record both the
    result and the exact arguments the two arithmetic checks were called with."""
    spies = {
        "line_items": Mock(wraps=ea.verify_line_items_math),
        "totals": Mock(wraps=ea.verify_totals_math),
    }
    monkeypatch.setattr(ea, "verify_line_items_math", spies["line_items"])
    monkeypatch.setattr(ea, "verify_totals_math", spies["totals"])

    result = ea.verify_node(
        _pipeline_state(
            doc_type=doc_type,
            extracted_data=dict(_INCONSISTENT_MONEY_DATA),
            ocr_text=_INCONSISTENT_OCR_TEXT,
        )
    )
    calls = {name: spy.call_args_list for name, spy in spies.items()}
    monkeypatch.undo()
    return result, calls


def test_t_r_3_an_invoice_produces_the_identical_alert_set_with_the_flag_on(monkeypatch):
    """**T-R-3 — the regression proof, and the reason `resolve_verification_rubric`
    has no money-family exclusion.** The money rubric is today's behaviour written
    down, so consulting it for an INVOICE must resolve to the same checks, with the
    same arguments, producing the same alerts and the same status.

    Asserted on the call arguments as well as on the output: two differently-argued
    calls that happen to agree would pass an output-only comparison, and "the same
    result" is a weaker claim than "the same checks"."""
    assert ea.get_settings().ENABLE_GENERIC_EXTRACTION is False
    off_result, off_calls = _verify_invoice_and_capture(monkeypatch, "INVOICE")

    monkeypatch.setattr(config.settings, "ENABLE_GENERIC_EXTRACTION", True)
    # Asserted, not assumed: without this the second run would be a second flag-OFF
    # run and the equality below would be vacuously true.
    assert ea.get_settings().ENABLE_GENERIC_EXTRACTION is True
    assert ea.resolve_verification_rubric("INBOUND", "INVOICE") is _RUBRICS["INVOICE"]
    on_result, on_calls = _verify_invoice_and_capture(monkeypatch, "INVOICE")

    assert on_result["alerts"] == off_result["alerts"]
    assert on_result["status"] == off_result["status"] == "AUDIT_REQUIRED"
    assert on_result["feedback"] == off_result["feedback"]
    assert on_calls == off_calls
    assert set(_alert_types(on_result["alerts"])) == _ARITHMETIC_ALERT_TYPES


@pytest.mark.parametrize("doc_type", _MONEY_DOC_TYPES)
def test_the_whole_money_family_keeps_both_arithmetic_checks(
    generic_flag_on, spied_math_checks, doc_type
):
    """`PROFORMA_INVOICE`, `CREDIT_NOTE` and `DEBIT_NOTE` are money documents too —
    the three a literal `!= "INVOICE"` family comparison would have misrouted (the
    collision Gap 369's build note flagged for this task)."""
    ea.verify_node(
        _pipeline_state(
            doc_type=doc_type,
            extracted_data=dict(_INCONSISTENT_MONEY_DATA),
            ocr_text=_INCONSISTENT_OCR_TEXT,
        )
    )

    spied_math_checks["line_items"].assert_called_once()
    spied_math_checks["totals"].assert_called_once()


def test_an_unclassified_document_under_the_flag_is_verified_exactly_as_today(
    generic_flag_on, spied_math_checks
):
    """`doc_type is None` with the flag ON — the classifier failed, or a caller
    skipped it. Fail-closed: both checks run, inbound status vocabulary, no rubric
    anywhere in the decision."""
    result = ea.verify_node(
        _pipeline_state(
            doc_type=None,
            extracted_data=dict(_INCONSISTENT_MONEY_DATA),
            ocr_text=_INCONSISTENT_OCR_TEXT,
        )
    )

    spied_math_checks["line_items"].assert_called_once()
    spied_math_checks["totals"].assert_called_once()
    assert result["status"] == "AUDIT_REQUIRED"


# --- T-R-4: `OTHER` is advisory -------------------------------------------------


def test_t_r_4_other_records_the_alerts_but_never_sets_a_review_status(generic_flag_on):
    """**T-R-4.** E4: "`OTHER` runs the money rubric in advisory mode only: alerts
    are recorded but never set a review status, because we do not know what the
    document is and have no rubric we can defend."

    Both halves matter. The alerts are still on the result — they are real
    observations and a reviewer may want them — and the status is the passing one."""
    result = ea.verify_node(
        _pipeline_state(
            doc_type="OTHER",
            extracted_data=dict(_INCONSISTENT_MONEY_DATA),
            ocr_text=_INCONSISTENT_OCR_TEXT,
        )
    )

    assert set(_alert_types(result["alerts"])) == _ARITHMETIC_ALERT_TYPES
    assert result["feedback"]  # the alert messages are still surfaced
    assert result["status"] == "EXTRACTED"


def test_the_advisory_flag_is_what_changed_the_status_not_the_alerts_going_away(
    generic_flag_on,
):
    """The control for the test above, on the same document: a `PURCHASE_ORDER`
    produces the identical alert list and lands on `EXTRACT_FAILED`. Without this,
    a bug that dropped `OTHER`'s alerts entirely would pass T-R-4."""
    state = dict(
        extracted_data=dict(_INCONSISTENT_MONEY_DATA), ocr_text=_INCONSISTENT_OCR_TEXT
    )
    advisory = ea.verify_node(_pipeline_state(doc_type="OTHER", **state))
    routed = ea.verify_node(_pipeline_state(doc_type="PURCHASE_ORDER", **state))

    assert advisory["alerts"] == routed["alerts"]
    assert (advisory["status"], routed["status"]) == ("EXTRACTED", "EXTRACT_FAILED")


def test_an_other_document_with_no_alerts_still_passes(generic_flag_on):
    """Advisory mode is not "always pass with a caveat" — a clean document is clean,
    and the status is the same one either way."""
    result = ea.verify_node(
        _pipeline_state(doc_type="OTHER", extracted_data={"items": [], "notes": "bill of lading"})
    )

    assert result["alerts"] == []
    assert result["status"] == "EXTRACTED"


def test_advisory_mode_does_not_suppress_a_genuine_extraction_failure(generic_flag_on):
    """The `extraction_failed` early return is deliberately NOT advisory: that
    branch is the pipeline reporting its own failure, not the rubric judging the
    document. Suppressing it would mark a row with no extracted data at all as
    successfully extracted."""
    result = ea.verify_node(
        _pipeline_state(
            doc_type="OTHER",
            extracted_data={},
            alerts=[{"type": "extraction_failed", "message": "Structured extraction failed."}],
        )
    )

    assert result["status"] == "EXTRACT_FAILED"


# =============================================================================
# Feature 27 (G7) — trust boundaries on `prebuilt-invoice`'s invoice-specific output
# =============================================================================
# §2A/A1 and §8 trap 1. `_run_ocr` calls `prebuilt-invoice` for **every** document
# in both flag states — there is no model selector in this feature — and that model
# does not decline to analyse a delivery note: it force-fits `VendorName` /
# `InvoiceId` / `InvoiceTotal` onto one at low confidence. **Absence of data is not
# the hazard here; presence of confident wrong data is.** Three sites read that
# output without asking what the document is, and G7 gates all three:
#
#   1. `verify_field_confidence` — the Gap 3 Critic in `verify_node`, gated on
#      `run_field_confidence`. This is the founder's original symptom by its
#      second, independent route: `low_confidence_field` is in
#      NON_RETRYABLE_ALERT_TYPES and any alert sets the review status, so a
#      correct delivery note landed in review carrying an alert no retry could
#      clear. G5 fixed the arithmetic half; this is the other half.
#   2. The Gap 68 `tax_details_sum` backfill in `extract_node`, gated on
#      `run_di_tax_backfill` — a document that prints no tax must not acquire one
#      from DI's misparse.
#   3. `invoice.coordinates` in `queue_worker/handlers.py`, gated on the family —
#      every box is labelled with a DI *invoice* field name, so rendering them
#      over a purchase order draws a mislabelled overlay. An empty overlay is
#      honest; a mislabelled one is not.
#
# Everything here is written so the flag-OFF half is a test rather than a claim:
# each gate has a negative twin proving the same document takes the identical
# path it always has when the rubric is not consulted.

_LOW_DI_CONFIDENCE = {"VendorName": 0.31, "InvoiceTotal": 0.22}


@pytest.fixture
def worker_db():
    """An in-memory SQLite DB plus a seeded `Invoice` row, for the three tests
    that drive the real `handle_process_invoice` persistence block.

    Same shape as `tests/test_sse.py`'s fixture, which is the existing precedent
    for exercising this handler. **Evidence caveat (hard rule 2): SQLite is not
    Postgres.** These three prove the gate's wiring — which value reaches
    `invoice.coordinates` — not the storage behaviour of a JSON column; the
    Postgres run is task V's.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    tenant_id = uuid4()

    def seed(file_path):
        row = Invoice(
            id=uuid4(),
            tenant_id=tenant_id,
            file_path=file_path,
            status="PROCESSING",
        )
        with Session(engine) as session:
            session.add(row)
            session.commit()
            session.refresh(row)
        return row

    yield {"engine": engine, "tenant_id": tenant_id, "seed": seed}
    SQLModel.metadata.drop_all(engine)

_NON_MONEY_DOC_TYPES = tuple(dt for dt in DOC_TYPES if DOC_TYPE_FAMILY[dt] != MONEY_FAMILY)
_MONEY_DOC_TYPES = tuple(dt for dt in DOC_TYPES if DOC_TYPE_FAMILY[dt] == MONEY_FAMILY)


@pytest.fixture
def spied_critic(monkeypatch):
    """`verify_field_confidence`, wrapped so it still does its real work.

    `wraps=` for the same reason `spied_math_checks` uses it: several tests below
    assert on the alerts the real call produces *and* on whether it was attempted
    at all, and the second of those is the load-bearing one — the check returns
    `[]` for an empty `field_confidence` dict, so an alerts-only assertion would
    pass against completely ungated code on any document whose `ocr_result` is
    absent.
    """
    spy = Mock(wraps=ea.verify_field_confidence)
    monkeypatch.setattr(ea, "verify_field_confidence", spy)
    return spy


# --- T-R-7: the founder's document, by its second route ------------------------


@pytest.mark.parametrize("doc_type", _NON_MONEY_DOC_TYPES)
def test_t_r_7_a_non_invoice_document_produces_no_low_confidence_field_alerts(
    generic_flag_on, spied_critic, doc_type
):
    """**T-R-7 (§9), and the marker G5 left to flip rather than delete.** Hand the
    Critic exactly what `prebuilt-invoice` returns for a delivery challan — low
    confidence on `VendorName` and `InvoiceTotal`, two fields the document does not
    have — and it must produce nothing.

    Parametrised over every non-money type rather than `DELIVERY_NOTE` alone: the
    quantity family is the founder's case, but a purchase order and a contract get
    the same force-fitted invoice fields from the same model, and `OTHER` would
    otherwise pass on `advisory_only` alone while still recording nonsense alerts
    on the row.

    `assert_not_called` is the load-bearing assertion; `alerts == []` alone would
    be satisfied by a gate that ran the check and threw the result away."""
    result = ea.verify_node(
        _pipeline_state(
            doc_type=doc_type,
            extracted_data=dict(_NO_PRICE_DELIVERY_NOTE),
            ocr_result={"field_confidence": dict(_LOW_DI_CONFIDENCE)},
        )
    )

    spied_critic.assert_not_called()
    assert result["alerts"] == []
    assert result["feedback"] == []
    assert result["status"] == "EXTRACTED"


def test_t_r_7_the_same_document_under_the_flag_off_still_runs_the_critic(spied_critic):
    """The negative half of T-R-7, kept as a test rather than as a claim. This is
    the assertion the pre-G7 marker made, preserved verbatim for the flag-OFF case
    it is still true of: two alerts, a review status, and the check attempted.

    (The status is the INBOUND profile's `AUDIT_REQUIRED` rather than the
    `EXTRACT_FAILED` the marker recorded, because with the flag off this document
    resolves to the invoice profile — the same reason its schema does.)"""
    assert ea.get_settings().ENABLE_GENERIC_EXTRACTION is False

    result = ea.verify_node(
        _pipeline_state(
            doc_type="DELIVERY_NOTE",
            extracted_data=dict(_NO_PRICE_DELIVERY_NOTE),
            ocr_result={"field_confidence": dict(_LOW_DI_CONFIDENCE)},
        )
    )

    spied_critic.assert_called_once()
    assert _alert_types(result["alerts"]) == ["low_confidence_field", "low_confidence_field"]
    assert result["status"] == "AUDIT_REQUIRED"


def test_the_critic_alert_is_non_retryable_which_is_why_this_gate_matters(
    generic_flag_on, spied_critic
):
    """Why a `low_confidence_field` alert on a non-invoice was worse than a noisy
    alert: `route_after_verification` will not re-extract for it (it is in
    `NON_RETRYABLE_ALERT_TYPES`), so before this gate a correct delivery note
    reached a review status carrying an alert no retry could ever clear. Asserted
    on the router, so the reasoning in A1 is checked rather than repeated."""
    assert "low_confidence_field" in ea.NON_RETRYABLE_ALERT_TYPES

    # The pre-gate alert set, fed to the real router: no retry is even attempted,
    # so the review status those alerts force could never be cleared.
    stuck = [{"type": "low_confidence_field", "message": "Low confidence on VendorName."}]
    assert ea.route_after_verification(_pipeline_state(alerts=stuck, retry_count=0)) == "__end__"

    # ...which is why the fix has to be that the alert is never raised.
    gated = ea.verify_node(
        _pipeline_state(
            doc_type="DELIVERY_NOTE",
            extracted_data=dict(_NO_PRICE_DELIVERY_NOTE),
            ocr_result={"field_confidence": dict(_LOW_DI_CONFIDENCE)},
        )
    )
    assert gated["alerts"] == []
    spied_critic.assert_not_called()


@pytest.mark.parametrize("doc_type", _MONEY_DOC_TYPES)
def test_the_money_family_still_consults_document_intelligences_confidence_scores(
    generic_flag_on, spied_critic, doc_type
):
    """The other side of the gate. A1 turns this check off for documents DI was
    asked the wrong question about — not for invoices, where Gap 3's reasoning
    (a blurred or smudged scan should route to a human) is exactly as valid as it
    was."""
    result = ea.verify_node(
        _pipeline_state(
            doc_type=doc_type,
            extracted_data=dict(_INCONSISTENT_MONEY_DATA),
            ocr_text=_INCONSISTENT_OCR_TEXT,
            ocr_result={"field_confidence": dict(_LOW_DI_CONFIDENCE)},
        )
    )

    spied_critic.assert_called_once()
    assert _alert_types(result["alerts"]).count("low_confidence_field") == 2


def test_t_r_3_still_holds_with_the_critic_gate_layered_on(monkeypatch):
    """**T-R-3, re-confirmed with G7's change on top of G5's.** The same invoice
    with the same DI confidence scores, verified with the flag off and then on:
    equal alerts, equal status, equal feedback, and — the assertion an
    output-only comparison could not make — the Critic called with **equal
    arguments** both times.

    A1's whole claim for the money family is that consulting the rubric resolves
    to the same call, not merely to the same answer."""
    captured = {}

    for label, flag in (("off", False), ("on", True)):
        monkeypatch.setattr(config.settings, "ENABLE_GENERIC_EXTRACTION", flag)
        assert ea.get_settings().ENABLE_GENERIC_EXTRACTION is flag
        spy = Mock(wraps=ea.verify_field_confidence)
        monkeypatch.setattr(ea, "verify_field_confidence", spy)

        captured[label] = (
            ea.verify_node(
                _pipeline_state(
                    doc_type="INVOICE" if flag else None,
                    extracted_data=dict(_INCONSISTENT_MONEY_DATA),
                    ocr_text=_INCONSISTENT_OCR_TEXT,
                    ocr_result={"field_confidence": dict(_LOW_DI_CONFIDENCE)},
                )
            ),
            spy.call_args_list,
        )
        monkeypatch.undo()

    off_result, off_calls = captured["off"]
    on_result, on_calls = captured["on"]

    assert off_result["alerts"] == on_result["alerts"]
    assert off_result["status"] == on_result["status"] == "AUDIT_REQUIRED"
    assert off_result["feedback"] == on_result["feedback"]
    assert off_calls == on_calls
    assert len(on_calls) == 1


def test_the_tenants_confidence_threshold_override_still_reaches_the_gated_call(
    generic_flag_on, spied_critic
):
    """Feature 18's threshold override is resolved outside the new `if` and passed
    into it. The check moved under a condition; it did not lose its parameter —
    and a tenant that widened this threshold on their invoices must still have it
    applied. `0.15` puts both scores above the bar, so the override is proved by
    the alerts disappearing rather than by the keyword being present."""
    rules = {"constraints": [{"kind": "confidence_threshold_override", "params": {"threshold": 0.15}}]}

    result = ea.verify_node(
        _pipeline_state(
            doc_type="INVOICE",
            extracted_data={"currency": "INR", "subtotal": None, "grand_total": None, "items": []},
            ocr_result={"field_confidence": dict(_LOW_DI_CONFIDENCE)},
            rules=rules,
        )
    )

    assert spied_critic.call_args.kwargs["threshold"] == 0.15
    assert _alert_types(result["alerts"]) == []


# --- The Gap 68 DI tax backfill ------------------------------------------------


def _extract_with_di_tax(monkeypatch, doc_type, *, llm_payload, tax_details_sum=18.5):
    """One `extract_node` run against a fake LLM, with a DI TaxDetails sum in
    `ocr_result`. Returns the extracted dict."""
    monkeypatch.setattr(config.settings, "LLM_PROVIDER", "ollama")
    monkeypatch.setattr(ea, "get_llm", lambda **kwargs: _RecordingLLM(llm_payload))

    return ea.extract_node(
        _pipeline_state(
            doc_type=doc_type,
            ocr_result={"tax_details_sum": tax_details_sum, "field_confidence": {}},
        )
    )["extracted_data"]


@pytest.mark.parametrize("doc_type", _NON_MONEY_DOC_TYPES)
def test_a_non_invoice_documents_null_tax_amount_is_not_backfilled_from_di(
    generic_flag_on, monkeypatch, doc_type
):
    """A1: "a delivery note prints no tax; DI's `TaxDetails` read on one is a
    misparse, and backfilling it writes a tax figure onto a document that states
    none — the plausible-wrong-answer class E9 exists to prevent".

    `is None` rather than falsy, per Gap 283: the failure this guards against is a
    *number* appearing, and `not 0.0` is `True`."""
    extracted = _extract_with_di_tax(
        monkeypatch, doc_type, llm_payload={"doc_type": doc_type, "tax_amount": None}
    )

    assert extracted["tax_amount"] is None


def test_the_same_delivery_note_under_the_flag_off_is_still_backfilled(monkeypatch):
    """The negative half. With the flag off this is Gap 68's behaviour, untouched —
    which is also what makes the gate's effect visible rather than asserted."""
    assert ea.get_settings().ENABLE_GENERIC_EXTRACTION is False

    extracted = _extract_with_di_tax(
        monkeypatch, "DELIVERY_NOTE", llm_payload={"vendor_name": "Northbridge", "tax_amount": None}
    )

    assert extracted["tax_amount"] == 18.5


@pytest.mark.parametrize("doc_type", _MONEY_DOC_TYPES)
def test_the_money_family_still_gets_the_gap_68_backfill(generic_flag_on, monkeypatch, doc_type):
    """Gap 68 exists because Indian invoices print CGST and SGST as separate rows
    and the LLM routinely fills `taxes[]` without summing them. That is still true
    with the flag on, and this is the test that fails if the gate is written as
    "off for everything"."""
    extracted = _extract_with_di_tax(
        monkeypatch, doc_type, llm_payload={"vendor_name": "Northbridge", "tax_amount": None}
    )

    assert extracted["tax_amount"] == 18.5


def test_an_unclassified_document_under_the_flag_is_still_backfilled(
    generic_flag_on, monkeypatch
):
    """`doc_type is None` — the classifier degraded, or a caller built the state by
    hand — fails closed to today's behaviour, the same default
    `resolve_extraction_profile` and `resolve_verification_rubric` take."""
    extracted = _extract_with_di_tax(
        monkeypatch, None, llm_payload={"vendor_name": "Northbridge", "tax_amount": None}
    )

    assert extracted["tax_amount"] == 18.5


def test_the_backfill_still_never_overrides_a_tax_amount_the_model_did_transcribe(
    generic_flag_on, monkeypatch
):
    """Gap 68's own invariant, re-asserted under the flag: the backfill fires only
    where `tax_amount` is None. The gate narrows *when* it may fire; it must not
    widen *what* it may overwrite."""
    extracted = _extract_with_di_tax(
        monkeypatch, "INVOICE", llm_payload={"vendor_name": "Northbridge", "tax_amount": 5.0}
    )

    assert extracted["tax_amount"] == 5.0


def test_outbound_never_reaches_the_backfill_gate(generic_flag_on, monkeypatch):
    """A2, verbatim: a classified `doc_type` "never changes their schema or rubric"
    for OUTBOUND. An outbound invoice misclassified as a delivery note must not
    silently lose Gap 68's backfill, which `queue_worker/outbound_handlers.py` and
    `routers/outbound_audit.py` are written against."""
    monkeypatch.setattr(config.settings, "LLM_PROVIDER", "ollama")
    monkeypatch.setattr(ea, "get_llm", lambda **kwargs: _RecordingLLM({"tax_amount": None}))

    extracted = ea.extract_node(
        _pipeline_state(
            doc_type="DELIVERY_NOTE",
            flow_direction="OUTBOUND",
            ocr_result={"tax_details_sum": 18.5, "field_confidence": {}},
        )
    )["extracted_data"]

    assert extracted["tax_amount"] == 18.5


# --- `invoice.coordinates`: the one piece of G7 in the worker -------------------


def test_the_classified_type_leaves_the_graph_so_the_handler_can_gate_on_it(
    generic_flag_on, monkeypatch
):
    """G4 deferred returning `doc_type` from `run_extraction_agent` to G9 on the
    grounds that persistence is what needs it; G7's coordinates gate is the first
    thing that does. Asserted through a real run in both flag states, because the
    flag-OFF value being `None` is what makes the handler's gate a no-op today."""
    monkeypatch.setattr(config.settings, "LLM_PROVIDER", "ollama")
    monkeypatch.setattr(ea, "get_llm", lambda **kwargs: _RecordingLLM({"vendor_name": "N"}))

    on_result = ea.run_extraction_agent(
        "tenant-a/delivery_challan.png", _DELIVERY_CHALLAN_TEXT, "tenant-a"
    )
    assert on_result["doc_type"] == "DELIVERY_NOTE"

    monkeypatch.setattr(config.settings, "ENABLE_GENERIC_EXTRACTION", False)
    off_result = ea.run_extraction_agent(
        "tenant-a/delivery_challan.png", _DELIVERY_CHALLAN_TEXT, "tenant-a"
    )
    assert off_result["doc_type"] is None
    # The three pre-Feature-27 keys are untouched and `doc_type` is present. A
    # subset check rather than set equality **since G9 landed**: that task added
    # `doc_type_evidence` / `doc_type_confidence` to this same dict for its own
    # persistence needs, and pinning the exact key set here would make this test
    # fail for a change it does not own.
    assert {"status", "alerts", "extracted_data", "doc_type"} <= set(off_result)


@pytest.mark.parametrize("doc_type", _MONEY_DOC_TYPES + (None,))
def test_the_money_family_and_the_unclassified_case_keep_di_coordinates(doc_type):
    """A1's "persisted for the INVOICE family only" — where "the INVOICE family" is
    E4's money family, the four types whose DI boxes really are invoice boxes.
    `None` is every flag-OFF run and every caller that patches
    `run_extraction_agent` with a dict predating the key, and it fails closed to
    today's behaviour."""
    assert handlers._should_persist_coordinates(doc_type) is True


@pytest.mark.parametrize("doc_type", _NON_MONEY_DOC_TYPES)
def test_no_non_invoice_document_keeps_di_coordinates(doc_type):
    assert handlers._should_persist_coordinates(doc_type) is False


def test_the_coordinates_gate_normalises_and_falls_closed_on_an_unknown_type(caplog):
    """Same two edges as the profile and rubric resolvers: a padded or lower-cased
    value is normalised before the family lookup, and an out-of-vocabulary one is a
    caller defect — logged, and given today's behaviour rather than a guess."""
    assert handlers._should_persist_coordinates(" delivery_note ") is False
    assert handlers._should_persist_coordinates("invoice") is True

    with caplog.at_level("WARNING"):
        assert handlers._should_persist_coordinates("LIEFERSCHEIN") is True
    assert "not in DOC_TYPES" in caplog.text


def test_the_gate_compares_against_the_family_constant_not_the_literal_invoice():
    """Gap 369's naming note 1, the collision every Feature 27 slice has had to
    honour: `INVOICE` is a *value* in `DOC_TYPES`, so a bare
    `DOC_TYPE_FAMILY[doc_type] != "INVOICE"` is true for every document — including
    a proforma, a credit note and a debit note, whose DI boxes are genuinely
    invoice boxes."""
    assert handlers.MONEY_FAMILY == "MONEY"
    assert handlers.DOC_TYPE_FAMILY is dtc.DOC_TYPE_FAMILY
    for doc_type in ("PROFORMA_INVOICE", "CREDIT_NOTE", "DEBIT_NOTE"):
        assert handlers._should_persist_coordinates(doc_type) is True


def _process_one(worker_db, file_path, agent_result, coordinates):
    """Drive the real `handle_process_invoice` over one seeded row.

    Only `_run_ocr`, the SSE publisher and `run_extraction_agent` are patched —
    the persistence block itself, which is what G7 changed, is the real one.
    """
    with patch("queue_worker.handlers._run_ocr") as mock_ocr, \
         patch("queue_worker.handlers._publish_sse_events"), \
         patch("queue_worker.handlers.run_extraction_agent") as mock_agent, \
         patch("queue_worker.handlers.engine", worker_db["engine"]):
        mock_ocr.return_value = {
            "content": "ocr layout content text",
            "coordinates": coordinates,
            "field_confidence": {"VendorName": 0.99},
            "tax_details_sum": None,
            "source_document_json": {"docs": []},
        }
        mock_agent.return_value = agent_result
        handlers.handle_process_invoice(
            str(uuid4()), file_path, str(worker_db["tenant_id"])
        )


_DI_COORDINATES = [
    {"field": "grand_total", "page": 1, "x": 0.1, "y": 0.2, "width": 0.1, "height": 0.02},
    {"field": "vendor_name", "page": 1, "x": 0.1, "y": 0.1, "width": 0.2, "height": 0.02},
]


def test_an_invoices_coordinates_are_still_persisted_exactly_as_today(worker_db):
    """The regression half, through the real handler and a real (SQLite) row: an
    invoice's auditor overlay (Task 2.15 / Gap 16, normalised by Gap 330) is
    untouched by this feature."""
    invoice = worker_db["seed"]("tenant-a/invoice_standard.pdf")

    _process_one(
        worker_db,
        invoice.file_path,
        {
            "status": "COMPLETED",
            "alerts": [],
            "extracted_data": {"vendor_name": "Northbridge", "grand_total": 165.0},
            "doc_type": "INVOICE",
        },
        _DI_COORDINATES,
    )

    with Session(worker_db["engine"]) as session:
        row = session.get(Invoice, invoice.id)
        assert row.coordinates == _DI_COORDINATES
        # ...and the two DI outputs A1 deliberately leaves alone are still written.
        assert row.field_confidence == {"VendorName": 0.99}
        assert row.source_document_json == {"docs": []}


def test_a_delivery_note_never_reaches_the_coordinates_gate_after_g9(worker_db):
    """**Rewritten mid-task, and the reason is recorded rather than hidden.** As
    written, this test asserted that a `DELIVERY_NOTE`'s `Invoice` row is persisted
    with `coordinates == []`. That was true when G7 was built and stopped being
    true hours later, when G9/E10 landed in the same file: a non-money document no
    longer *has* an `Invoice` row at all — `_routes_to_documents_table()` sends it
    to `documents` and deletes the placeholder in the same transaction, returning
    before the coordinates line.

    So A1's hazard — DI's invoice-labelled boxes rendered over a purchase order —
    is now prevented one layer up, by the row not existing, and G7's gate is the
    invoice branch's own guard: it resolves `True` everywhere it is still reached.
    That is defence in depth, not dead code, and the two questions are deliberately
    kept separate (`_routes_to_documents_table`'s docstring says why: one of them
    draws a wrong box, the other deletes a row).

    What this test asserts now is exactly that state of affairs, so the next person
    to read the G7 build note can check its claim rather than take it on trust. The
    gate itself is covered by the unit tests above."""
    invoice = worker_db["seed"]("tenant-a/delivery_challan.pdf")

    assert handlers._should_persist_coordinates("DELIVERY_NOTE") is False

    _process_one(
        worker_db,
        invoice.file_path,
        {
            "status": "EXTRACTED",
            "alerts": [],
            "extracted_data": {"party_name": "Northbridge", "grand_total": None},
            "doc_type": "DELIVERY_NOTE",
        },
        _DI_COORDINATES,
    )

    with Session(worker_db["engine"]) as session:
        assert session.get(Invoice, invoice.id) is None


def test_a_result_dict_with_no_doc_type_key_persists_coordinates_as_today(worker_db):
    """Every existing caller and test that patches `run_extraction_agent` returns
    the three-key dict this function returned before G7. `.get()` rather than
    `[...]` is what keeps those green, and this is the test that says so — it is
    also the flag-OFF path exactly, since the classifier node is not in the
    compiled graph then."""
    invoice = worker_db["seed"]("tenant-a/invoice_legacy.pdf")

    _process_one(
        worker_db,
        invoice.file_path,
        {
            "status": "COMPLETED",
            "alerts": [],
            "extracted_data": {"vendor_name": "Northbridge", "grand_total": 165.0},
        },
        _DI_COORDINATES,
    )

    with Session(worker_db["engine"]) as session:
        assert session.get(Invoice, invoice.id).coordinates == _DI_COORDINATES


# =============================================================================
# Feature 27 (G6) — `UnknownFlowDirectionError`: E9's fail-loud
# =============================================================================
# E9, verbatim on the two halves that matter:
#
#   * `flow_direction` that is `None`, absent, or empty/whitespace -> **still
#     defaults to INBOUND**, unchanged. `agents/trainer_agent.py`,
#     `routers/trainer.py` and `benchmarks/extraction/harness.py` rely on it.
#   * A non-empty string that is not a valid direction -> raise
#     `UnknownFlowDirectionError(ValueError)` naming the value and listing the
#     valid keys.
#   * **Applies with the flag ON or OFF** — the single deliberate exception to E3.
#
# The carried constraint from G3b's note, which these tests exist to pin: the
# valid set is the three *named directions*, NOT `_DIRECTION_PROFILES.keys()`,
# which has had a fourth `GENERIC` entry since G3b.


def test_the_valid_direction_set_is_the_profile_map_minus_generic():
    """The one structural assertion that keeps `_VALID_FLOW_DIRECTIONS` and
    `_DIRECTION_PROFILES` from drifting in the *wrong* direction. Two names for
    one idea is normally how drift starts; here the divergence is deliberate and
    is exactly one entry wide, so it is asserted as an equation rather than left
    to a comment. A future fifth profile added to the map for shape reuse will
    fail here rather than quietly becoming an accepted external input."""
    assert set(ea._VALID_FLOW_DIRECTIONS) == set(ea._DIRECTION_PROFILES) - {"GENERIC"}
    assert set(ea._VALID_FLOW_DIRECTIONS) == {"INBOUND", "OUTBOUND", "REFERENCE"}


def test_unknown_flow_direction_error_is_a_valueerror():
    """A `ValueError` subclass, per E9. Anything already catching `ValueError`
    around a profile lookup keeps working; anything that wants to tolerate only
    this can catch it precisely."""
    assert issubclass(ea.UnknownFlowDirectionError, ValueError)


@pytest.mark.parametrize("flow_direction", [None, "", "   ", "\t", "\n  "])
def test_absent_or_blank_direction_still_defaults_to_inbound(flow_direction):
    """The half of E9 that is a *preservation* requirement, not a change.
    `agents/trainer_agent.py`, `routers/trainer.py` and
    `benchmarks/extraction/harness.py` pass no direction at all, and every
    pre-Gap-283 persisted state dict has no key for it. Whitespace is included
    because "empty/whitespace" is E9's own wording — a blank string arriving from
    a form field or a stripped CSV cell is absence, not a typo."""
    assert resolve_direction_profile(flow_direction) is ea._DIRECTION_PROFILES["INBOUND"]
    assert resolve_direction_profile(flow_direction).schema is InvoiceExtractionSchema


@pytest.mark.parametrize(
    "flow_direction,expected",
    [
        ("INBOUND", "INBOUND"),
        ("OUTBOUND", "OUTBOUND"),
        ("REFERENCE", "REFERENCE"),
        ("inbound", "INBOUND"),
        ("outbound", "OUTBOUND"),
        ("Reference", "REFERENCE"),
    ],
)
def test_the_three_real_directions_resolve_exactly_as_before(flow_direction, expected):
    """E9's blast-radius claim, asserted rather than trusted: the values the eight
    real call sites actually pass are untouched, case-insensitively, and each still
    returns *its own* profile object."""
    assert resolve_direction_profile(flow_direction) is ea._DIRECTION_PROFILES[expected]


def test_a_typod_direction_raises_and_names_the_value_and_the_valid_set():
    """E9's central case. `"REFERNCE"` used to silently become INBOUND — meaning
    `InvoiceExtractionSchema`, the inbound prompt, `COMPLETED`/`AUDIT_REQUIRED` and
    the `"audit" in file_path` legacy shim — and produce a plausible wrong answer.
    The message content is asserted because a fail-loud whose message does not name
    the offending value sends the reader back to the source to find out what
    happened."""
    with pytest.raises(ea.UnknownFlowDirectionError) as excinfo:
        resolve_direction_profile("REFERNCE")

    message = str(excinfo.value)
    assert "REFERNCE" in message
    for direction in ("INBOUND", "OUTBOUND", "REFERENCE"):
        assert direction in message


@pytest.mark.parametrize("flow_direction", ["GENERIC", "generic", "Generic", " GENERIC"])
def test_generic_is_not_an_accepted_flow_direction(flow_direction):
    """**The specific trap G3b's build note and the comment at the `GENERIC` map
    entry both warn about.** `GENERIC` is a profile living in the direction map for
    shape reuse (`_DirectionProfile` is exactly the shape a profile needs, and a
    second near-identical dataclass is the duplication Gap 283 removed). Validating
    against `_DIRECTION_PROFILES.keys()` would have made it an accepted external
    `flow_direction` — a caller could then route an invoice onto
    `GenericDocumentSchema`, which silently drops `compliance_metadata`, `tax_ids`,
    `payment_instructions`, `addresses`, `deductions` and per-line `hsn_sac_code`
    while still returning a plausible `vendor_name` and `grand_total`. It must not
    succeed, in either flag state."""
    with pytest.raises(ea.UnknownFlowDirectionError):
        resolve_direction_profile(flow_direction)


@pytest.mark.parametrize("flow_direction", ["REFERNCE", "NONSENSE", "GENERIC", "  inbound "])
def test_e9_raises_with_the_flag_off_too(flow_direction):
    """**E9 is the single deliberate exception to E3**, and this is the test that
    holds that exception honest in the configuration that is actually deployed
    today. Gating a fail-loud correction behind the flag would leave the footgun
    armed exactly where it is currently armed.

    The default fixture state is flag-OFF (`generic_flag_on` is opt-in), and the
    assertion on the setting makes that explicit rather than incidental."""
    assert ea.get_settings().ENABLE_GENERIC_EXTRACTION is False
    with pytest.raises(ea.UnknownFlowDirectionError):
        resolve_direction_profile(flow_direction)


@pytest.mark.parametrize("flow_direction", ["REFERNCE", "NONSENSE", "GENERIC", "  inbound "])
def test_e9_raises_with_the_flag_on_too(generic_flag_on, flow_direction):
    """The other half of the same statement. Same inputs, same outcome, flag ON —
    so "unconditional" means unconditional and not "happens to be true in the
    default configuration"."""
    assert ea.get_settings().ENABLE_GENERIC_EXTRACTION is True
    with pytest.raises(ea.UnknownFlowDirectionError):
        resolve_direction_profile(flow_direction)


def test_e9_is_the_only_visible_behaviour_change_with_the_flag_off():
    """E3's guarantee, restated for G6 specifically: with the flag off, every
    input the codebase can actually produce resolves to the same profile object it
    did before this change, and the *only* difference anywhere is that a value no
    caller passes now raises instead of silently becoming INBOUND.

    Asserted as an explicit before/after table rather than as "the suite passes",
    because "the suite passes" is what E3 says is not evidence."""
    assert ea.get_settings().ENABLE_GENERIC_EXTRACTION is False

    # Every value the eight real call sites can pass, with the profile each
    # resolved to before G6. Identical after.
    unchanged = {
        None: "INBOUND",
        "": "INBOUND",
        "INBOUND": "INBOUND",
        "OUTBOUND": "OUTBOUND",
        "REFERENCE": "REFERENCE",
        "inbound": "INBOUND",
        "outbound": "OUTBOUND",
        "reference": "REFERENCE",
    }
    for flow_direction, expected in unchanged.items():
        assert resolve_direction_profile(flow_direction) is ea._DIRECTION_PROFILES[expected]

    # ...and the one class of input whose behaviour did change, which no call site
    # produces (E9's enumerated blast radius).
    with pytest.raises(ea.UnknownFlowDirectionError):
        resolve_direction_profile("REFERNCE")


def test_run_extraction_agent_still_calls_resolve_direction_profile():
    """G4's carried constraint, re-asserted at G6 because G6 is the change most
    likely to tempt someone into "fixing" this call site. `run_extraction_agent`'s
    only use of a profile is the pre-flight token-guardrail early return, which
    happens *before* the graph runs and therefore before any `doc_type` exists —
    so `resolve_extraction_profile` would have nothing to add there and would only
    make the guardrail depend on a classification that has not happened."""
    source = inspect.getsource(ea.run_extraction_agent)
    assert "resolve_direction_profile(" in source
    assert "resolve_extraction_profile(" not in source


def test_resolve_verification_rubric_does_not_raise_on_a_typod_direction(generic_flag_on):
    """The deliberate asymmetry, stated so it is not read as an oversight.
    `resolve_verification_rubric` never calls `resolve_direction_profile`, and
    adding a raise to it would fail an extraction at the *verification* step —
    after the model spend — for an input that profile resolution already rejected
    earlier and more cheaply. Returning `None` (today's checks, fail-closed) is
    this function's contract for every unrecognised input."""
    assert ea.resolve_verification_rubric("REFERNCE", "DELIVERY_NOTE") is None
    assert ea.resolve_verification_rubric("GENERIC", "DELIVERY_NOTE") is None


# =============================================================================
# Feature 27 (G8) — `document_to_base64_images` + image dispatch + the alias
# =============================================================================
# §4, "Non-PDF image support". The defect being fixed is NOT primarily "PNGs are
# not supported" — it is that a PNG hit `fitz.open(..., filetype="pdf")`, the
# `except` logged a PDF-flavoured error and returned `[]`, and the multimodal
# visual channel was silently lost for that document. So the assertion that
# matters most below is the one on the WARNING, not the one on the return value:
# `[]` was already the return before this change.
#
# No network and no storage: `download_pdf_from_storage` is patched at its import
# site in `agents.extraction_agent`, exactly as the existing extraction tests do.


def _one_page_pdf_bytes() -> bytes:
    """A real single-page PDF, built with the same PyMuPDF the function renders
    with. Not a fixture file: this section must not depend on
    `tests/fixtures/doc_types/**`, which another dispatch owns."""
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "DELIVERY NOTE 4471")
    data = doc.tobytes()
    doc.close()
    return data


def _png_bytes(mode: str = "RGB", size: tuple = (40, 30)) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new(mode, size, color=255 if mode == "L" else (200, 30, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


def _jpeg_bytes() -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (40, 30), color=(10, 90, 200)).save(buffer, format="JPEG")
    return buffer.getvalue()


def test_a_png_yields_one_base64_page_instead_of_an_empty_list():
    """The headline case. Before G8 this returned `[]` — `fitz.open(filetype="pdf")`
    on PNG bytes raises, the `except` logged, and the visual channel was gone."""
    with patch.object(ea, "download_pdf_from_storage", return_value=_png_bytes()):
        images = ea.document_to_base64_images("tenant-a/delivery_note.png")

    assert len(images) == 1
    assert images[0].startswith("data:image/png;base64,")
    # Decodes to real PNG bytes, not to whatever was handed in.
    payload = base64.b64decode(images[0].split(",", 1)[1])
    assert payload[:8] == b"\x89PNG\r\n\x1a\n"


@pytest.mark.parametrize(
    "filename",
    [
        "tenant-a/note.png",
        "tenant-a/note.jpg",
        "tenant-a/note.jpeg",
        "tenant-a/NOTE.PNG",
        "tenant-a/scan.tiff",
        "tenant-a/scan.tif",
        "tenant-a/scan.bmp",
        "tenant-a/scan.webp",
    ],
)
def test_every_declared_image_suffix_is_dispatched_to_the_image_branch(filename):
    """Parametrised over `_IMAGE_SUFFIXES` rather than one sample, and including an
    upper-cased name because blob paths come from user filenames. The bytes handed
    in are always a PNG — this asserts the *dispatch*, not pillow's decoders."""
    with patch.object(ea, "download_pdf_from_storage", return_value=_png_bytes()):
        images = ea.document_to_base64_images(filename)

    assert len(images) == 1


def test_a_jpeg_is_normalised_to_png_not_relabelled():
    """The data URL says `image/png`. Passing JPEG bytes through under that media
    type is the class of thing that works against one vision endpoint and fails
    against the next, so the image branch re-encodes rather than relabels."""
    with patch.object(ea, "download_pdf_from_storage", return_value=_jpeg_bytes()):
        images = ea.document_to_base64_images("tenant-a/scan.jpg")

    payload = base64.b64decode(images[0].split(",", 1)[1])
    assert payload[:8] == b"\x89PNG\r\n\x1a\n"
    assert payload[:3] != b"\xff\xd8\xff"  # not the original JPEG magic


def test_an_unsupported_extension_returns_empty_and_logs_a_warning_naming_it(caplog):
    """**The actual G8 fix.** `[]` is unchanged and is still correct — an
    unrenderable attachment must not take an extraction down, since OCR text alone
    is a degraded but genuine answer. What changed is that it is no longer silent.
    The extension is asserted to be *in the message*, because a warning that does
    not say which format was refused cannot be acted on."""
    with caplog.at_level(logging.WARNING, logger="agents.extraction_agent"):
        with patch.object(ea, "download_pdf_from_storage") as download:
            images = ea.document_to_base64_images("tenant-a/contract.docx")

    assert images == []
    assert ".docx" in caplog.text
    # Not a storage round trip either: an unsupported format is decided from the
    # name, before the blob is fetched.
    download.assert_not_called()


def test_a_file_with_no_extension_at_all_also_warns(caplog):
    """The `""` suffix branch — a blob path with no dot. Same treatment; the
    message says `<none>` rather than printing an empty string, so the log line
    stays readable."""
    with caplog.at_level(logging.WARNING, logger="agents.extraction_agent"):
        images = ea.document_to_base64_images("tenant-a/scanned_document")

    assert images == []
    assert "<none>" in caplog.text


def test_a_pdfs_output_is_byte_for_byte_what_the_old_function_produced():
    """E3-style equality for G8: the `.pdf` branch is unchanged, asserted against a
    local re-implementation of the pre-G8 body (the same `fitz` render, the same
    `tobytes("png")`, the same prefix) rather than against "it looks like a data
    URL". Anything that alters the render — a DPI argument, a colourspace, a
    different prefix — fails here."""
    pdf_bytes = _one_page_pdf_bytes()

    expected = []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    for page in doc:
        pix = page.get_pixmap()
        b64_str = base64.b64encode(pix.tobytes("png")).decode("utf-8")
        expected.append(f"data:image/png;base64,{b64_str}")
    doc.close()

    with patch.object(ea, "download_pdf_from_storage", return_value=pdf_bytes):
        images = ea.document_to_base64_images("tenant-a/invoice.pdf")

    assert images == expected
    assert len(images) == 1


def test_a_missing_blob_keeps_its_own_warning_and_is_not_folded_into_the_format_one(caplog):
    """§4 and the brief are explicit that `download_pdf_from_storage`'s failure
    path keeps today's behaviour. "The file is not where we think it is" and "we
    cannot render this format" are different operational problems with different
    fixes, and merging them would make the new warning useless for detecting the
    second."""
    with caplog.at_level(logging.WARNING, logger="agents.extraction_agent"):
        with patch.object(ea, "download_pdf_from_storage", side_effect=FileNotFoundError("gone")):
            images = ea.document_to_base64_images("tenant-a/invoice.pdf")

    assert images == []
    assert "PDF file not found for base64 conversion" in caplog.text
    assert "unsupported extension" not in caplog.text


def test_an_unreadable_image_degrades_to_ocr_text_rather_than_raising(caplog):
    """Same failure policy as the PDF branch: a corrupt attachment loses the visual
    channel, it does not fail the extraction."""
    with caplog.at_level(logging.ERROR, logger="agents.extraction_agent"):
        with patch.object(ea, "download_pdf_from_storage", return_value=b"not an image"):
            images = ea.document_to_base64_images("tenant-a/scan.png")

    assert images == []
    assert "Failed to convert image" in caplog.text


def test_the_old_name_still_resolves_and_returns_the_same_thing():
    """§4: "Keep `pdf_to_base64_images` as a thin alias so no existing caller or
    test breaks." The three callers are `agents/outbound_extraction_agent.py:37`
    (a module-level import), `run_extraction_agent` in this module, and
    `benchmarks/extraction/harness.py`'s docstring."""
    pdf_bytes = _one_page_pdf_bytes()

    with patch.object(ea, "download_pdf_from_storage", return_value=pdf_bytes):
        via_alias = ea.pdf_to_base64_images("tenant-a/invoice.pdf")
        via_new_name = ea.document_to_base64_images("tenant-a/invoice.pdf")

    assert via_alias == via_new_name
    assert len(via_alias) == 1

    # The outbound agent imported the name at module load; it must still be bound.
    import agents.outbound_extraction_agent as oea

    assert oea.pdf_to_base64_images is ea.pdf_to_base64_images


def test_the_alias_is_a_wrapper_not_the_same_object():
    """Deliberate, and the reason is test-mechanical rather than aesthetic: several
    existing tests patch `agents.extraction_agent.pdf_to_base64_images`, and if the
    two names were one object a patch of either would silently patch both — a
    test-only coupling that later reads as a real behavioural guarantee."""
    assert ea.pdf_to_base64_images is not ea.document_to_base64_images
    assert "document_to_base64_images" in inspect.getsource(ea.pdf_to_base64_images)


def test_the_pre_g8_png_claim_was_stale_and_the_new_path_does_not_rely_on_sniffing():
    """A correction of fact, kept as a test so it is not re-asserted later from the
    spec text. §4 says the old `pdf_to_base64_images` returned `[]` for a PNG
    because `fitz.open(..., filetype="pdf")` raised. Against the installed PyMuPDF
    (1.28.0 / MuPDF 1.29.0) it does not raise — MuPDF sniffs the real container and
    ignores the declared `filetype`, so a PNG already came back as a one-page
    render. The pre-G8 silent loss was therefore real for formats MuPDF cannot
    parse at all (`.docx`, `.xlsx`) and for corrupt bytes, but not for the image
    formats §4 names.

    Which is why G8's value is *determinism*, not new capability: rendering half
    the accepted input formats through an undeclared sniffing behaviour of a
    vendored C library is a dependency nobody wrote down and no version pin
    protects. The first half of this test records the sniffing; the second asserts
    our own path no longer needs it."""
    png = _png_bytes()

    sniffed = fitz.open(stream=png, filetype="pdf")
    assert sniffed.page_count == 1, (
        "PyMuPDF no longer sniffs non-PDF containers — if this fails, §4's original "
        "premise has become true again and the G8 build note should say so."
    )
    sniffed.close()

    # Our branch reaches pillow, never fitz, for an image suffix.
    with patch.object(ea, "download_pdf_from_storage", return_value=png):
        with patch.object(ea, "fitz") as fitz_module:
            images = ea.document_to_base64_images("tenant-a/note.png")

    assert len(images) == 1
    fitz_module.open.assert_not_called()


def test_run_extraction_agent_still_only_renders_pdfs_today():
    """An honest boundary marker, not an endorsement. `run_extraction_agent` guards
    its call with `file_path.lower().endswith(".pdf")`, so G8's new image branch is
    **not reachable from the normal extraction path** — a PNG upload still gets no
    visual channel, it just no longer does so by way of a misleading PDF parse
    error. Widening that guard is a caller-side change that would alter flag-OFF
    behaviour (E3), so it is deliberately not part of G8; see the G8 build note.
    This test exists so the limitation is discovered by reading the suite rather
    than by wondering why nothing changed."""
    source = inspect.getsource(ea.run_extraction_agent)
    assert 'endswith(".pdf")' in source


# --- T-R-8 (A7/R9): the ADVISORY family --------------------------------------


def test_t_r_8_the_advisory_family_runs_no_arithmetic_and_never_sets_a_review_status():
    """A statement carries a RUNNING BALANCE, not a subtotal/tax/total triple, and
    a remittance lists per-invoice amounts against one payment. Research §5 trap 6:
    money-only, no lines. Running the money checks over either reports the absence
    of a structure that was never supposed to be there -- the founder's original
    false-failure, in a new costume.

    Asserted on the rubric's flags rather than on an alert count, because both
    check functions already return None when their inputs are absent: an
    alerts-only assertion would pass against completely ungated code. What is
    proved here is that they are never ATTEMPTED.
    """
    from agents.extraction_agent import _RUBRIC_BY_DOC_TYPE
    from services.document_type_classifier import ADVISORY_FAMILY, DOC_TYPE_FAMILY

    for doc_type in ("STATEMENT_OF_ACCOUNT", "REMITTANCE_ADVICE"):
        assert DOC_TYPE_FAMILY[doc_type] == ADVISORY_FAMILY, doc_type
        rubric = _RUBRIC_BY_DOC_TYPE[doc_type]
        assert rubric.run_line_item_math is False, doc_type
        assert rubric.run_totals_math is False, doc_type
        assert rubric.advisory_only is True, doc_type
        assert rubric.price_fields_optional is True, doc_type
        # §8 trap 1: DI force-fits InvoiceTotal onto a vendor statement, so a
        # low_confidence_field alert here names a field the document never had.
        assert rubric.run_field_confidence is False, doc_type
        assert rubric.run_di_tax_backfill is False, doc_type
        assert rubric.passed_status == "EXTRACTED", doc_type


def test_t_r_8_advisory_is_not_other_with_a_friendlier_name():
    """They share `advisory_only` and nothing else. OTHER means "we could not
    establish what this is"; ADVISORY means "we know exactly what it is and it is
    not a payable" -- and knowing is what earns it a schema and a comparison mode.

    The arithmetic flags are the substantive difference and this test pins them:
    _OTHER_RUBRIC leaves both math checks ON (it has no idea what it is looking
    at, so it checks and reports advisory-only), while ADVISORY switches them off
    on purpose.
    """
    from agents.extraction_agent import _ADVISORY_RUBRIC, _OTHER_RUBRIC

    assert _OTHER_RUBRIC.advisory_only == _ADVISORY_RUBRIC.advisory_only is True
    assert _OTHER_RUBRIC.run_line_item_math is True
    assert _ADVISORY_RUBRIC.run_line_item_math is False
    assert _OTHER_RUBRIC.run_totals_math is True
    assert _ADVISORY_RUBRIC.run_totals_math is False


def test_t_r_8_the_two_advisory_lists_are_additive_and_default_empty():
    """`referenced_documents[]` and `deductions[]` are the family's substance and
    the input to Feature 26's `list_reconcile`. Additive with `[]` defaults, so no
    existing document type's extracted shape changes -- A2's guarantee applies to
    the generic schema too, not only to the invoice one."""
    from agents.extraction_agent import GenericDocumentSchema

    blank = GenericDocumentSchema()
    assert blank.referenced_documents == []
    assert blank.payment_deductions == []

    # And the money spine is untouched by A7.
    for field in ("subtotal", "tax_amount", "grand_total", "items", "taxes"):
        assert field in GenericDocumentSchema.model_fields


def test_t_r_8_a_referenced_documents_status_hint_is_never_inferred():
    """The status printed against a reference is the COUNTERPARTY'S CLAIM, and the
    whole value of reconciling is seeing where their claim and our record differ.
    A schema that defaulted it would erase exactly that."""
    from agents.extraction_agent import ReferencedDocument

    row = ReferencedDocument(doc_number="INV-1", amount=1000.0)
    assert row.status_hint is None
    assert row.doc_date is None


def test_t_r_8_deductions_are_individually_reported_never_netted():
    """A remittance settling 92,000 against a 100,000 invoice is not a
    discrepancy if it prints "TDS u/s 194C: 8,000" -- it is a correct payment with
    an explanation. One unexplained 8,000 gap is a support ticket; "TDS 6,000 +
    chargeback 2,000" is an answer. The schema carries a LIST for that reason, and
    the prompt says so; this pins the shape."""
    from agents.extraction_agent import DeductionItem, GenericDocumentSchema

    doc = GenericDocumentSchema(
        payment_deductions=[
            DeductionItem(kind="TDS", amount=6000.0, reference="194C"),
            DeductionItem(kind="CHARGEBACK", amount=2000.0, reference="OTIF-Q3"),
        ]
    )
    assert len(doc.payment_deductions) == 2
    assert {d.kind for d in doc.payment_deductions} == {"TDS", "CHARGEBACK"}
    # No total field exists on which to net them -- the absence is the control.
    assert not hasattr(doc.payment_deductions[0], "total")
    # And A2's disjointness holds: `deductions` stays invoice-only.
    assert "deductions" not in GenericDocumentSchema.model_fields


def test_t_r_8_the_advisory_stance_reaches_the_prompt():
    """The family stance is what a NEW advisory type would inherit before anyone
    writes it a specific overlay -- the reason G3 added a stance layer above the
    per-type table at all."""
    from agents.extraction_agent import resolve_doc_type_overlay

    text = resolve_doc_type_overlay("STATEMENT_OF_ACCOUNT")
    lowered = text.lower()
    assert "advisory" in lowered
    assert "never" in lowered and "payable" in lowered
    assert "list of references" in lowered
