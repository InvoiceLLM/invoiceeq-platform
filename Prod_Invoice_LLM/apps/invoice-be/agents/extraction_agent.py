import base64
import io
import logging
import time
from dataclasses import dataclass
from functools import lru_cache, partial
from typing import List, Dict, Any, Tuple, Type, TypedDict, Optional, Callable
from pydantic import BaseModel, Field
import fitz  # PyMuPDF

from config import get_settings
from telemetry import tracked_llm_call
from utils.llm import get_llm
from utils.verification_tools import (
    verify_line_items_math,
    verify_totals_math,
    verify_grand_total_in_source_text,
    verify_line_item_amounts_in_source_text,
    verify_subtotal_in_source_text,
    verify_unit_prices_in_source_text,
    verify_tax_amount_in_source_text,  # Gap 46: tax_amount source-text verification
    verify_field_confidence,
)
from utils.token_management import check_token_guardrails
from utils.rule_schema import (
    normalize_constraints,
    tolerance_overrides,
    confidence_threshold_override,
    apply_alert_overrides,
)
from services.storage import download_pdf_from_storage
# Feature 27 (G3). The taxonomy and the family map are owned by the classifier
# module and imported here rather than restated — the overlay table below is
# keyed on `DOC_TYPES` and the family stance block is keyed on `DOC_TYPE_FAMILY`,
# so a type added there without an overlay is caught by a test rather than
# silently falling through to a generic prompt. The family constants are imported
# by name because `INVOICE` is already a `doc_type` *value*: comparing against the
# bare literal `"INVOICE"` when a family was meant is the exact collision the G2
# build note flags (see `services/document_type_classifier.py`, naming note 1).
from services.doc_attributes import derive_doc_attributes
from services.document_type_classifier import (
    ADVISORY_FAMILY,
    COMMITMENT_FAMILY,
    DOC_TYPE_FAMILY,
    DOC_TYPES,
    MONEY_FAMILY,
    OTHER_FAMILY,
    QUANTITY_FAMILY,
    # Feature 27 (G4). Imported at module level rather than inside the node (the
    # shape `classify_node` uses for `classify_invoice_complexity`) because this
    # module already depends on the same file for the constants above -- a local
    # import would suggest a cycle that does not exist. The name is looked up on
    # this module at call time, so tests patch `ea.classify_doc_type`.
    classify_doc_type,
)
from langchain_core.messages import HumanMessage
from langgraph.graph import StateGraph, END

logger = logging.getLogger(__name__)

# Gap 46: Directive instructing LLM to extract figures 100% verbatim without auto-correcting vendor math flaws
GAP_46_VERBATIM_DIRECTIVE = (
    "CRITICAL VERBATIM EXTRACTION DIRECTIVE: You are a strict document transcriber, NOT a calculator. "
    "Transcribe all numerical figures (subtotal, tax_amount, grand_total, line-item amounts, unit prices) 100% verbatim "
    "as printed on the document. Do NOT recalculate, smooth, balance, or auto-correct any math, even if vendor arithmetic "
    "is blatantly incorrect on the document. Downstream audit tools need to see exact printed numbers to flag vendor flaws.\n"
    "CRITICAL NOTE ON NEGATIVE NUMBERS: If any line-item amount, unit price, tax, discount, or total is printed as a negative value "
    "(e.g., prefixed with a minus sign like '-5,000.00', or enclosed in parentheses like '(5,000.00)'), you MUST extract it "
    "as a negative float (e.g. -5000.0). Do NOT strip the minus sign/parentheses to make it positive, as this will break arithmetic checks.\n\n"
)

# 1. Structured Output Schema
# NOTE: every model below sets model_config = {"extra": "forbid"}. Azure/OpenAI structured
# output (with_structured_output's default method="json_schema", strict mode) requires
# `additionalProperties: false` on every object in the schema, recursively — Pydantic only
# emits that when extra="forbid" is set. A bare Dict[str, Any] can never satisfy this (it
# renders as {"type": "object", "additionalProperties": true} — the opposite of what's
# required), so every previously-freeform nested list below is now a typed model instead.
class InvoiceLineItem(BaseModel):
    model_config = {"extra": "forbid"}
    description: str = Field(description="Description of the item or service")
    quantity: Optional[float] = Field(default=None, description="Quantity of the item")
    unit_price: Optional[float] = Field(default=None, description="Unit price of the item. CRITICAL: If the printed figure is negative (prefixed with '-' or in parentheses), you MUST extract it as a negative number (e.g., -5000.0).")
    amount: float = Field(description="Total amount for this line item. Transcribe printed figure verbatim; do not recalculate quantity * unit_price or auto-correct bad vendor math. CRITICAL: If the printed figure represents a credit, discount, negative adjustment, or credit-note/debit-note line (often prefixed with a minus sign '-' or enclosed in parentheses like '(5,000)'), you MUST extract it as a negative number (e.g. -5000.0). Do not strip the minus sign or convert it to a positive magnitude.")
    hsn_sac_code: Optional[str] = Field(default=None, description="HSN/SAC code (mandatory for Indian GST)")
    uom: Optional[str] = Field(default=None, description="Unit of measure (e.g., each, kg, hours)")
    discount_percent: Optional[float] = Field(default=None, description="Discount percentage applied to this line item")
    discount_amount: Optional[float] = Field(default=None, description="Discount amount applied to this line item")
    tax_percent: Optional[float] = Field(default=None, description="Tax percentage applied to THIS specific line item, ONLY if shown per-row in the line-items table (e.g. a GST%/Tax% column). Leave null if tax appears once in the invoice's summary/totals section — that is invoice-level tax, not a line-item field.")
    tax_amount: Optional[float] = Field(default=None, description="Tax amount applied to THIS specific line item, ONLY if itemized per-row. Leave null if tax is invoice-level only (see tax_percent).")

class TaxItem(BaseModel):
    model_config = {"extra": "forbid"}
    tax_type: str = Field(description="e.g. 'VAT', 'GST', 'CGST', 'SGST', 'IGST', 'Sales Tax'")
    rate_percent: Optional[float] = Field(default=None, description="Tax rate as a percentage")
    amount: float = Field(description="Tax amount")

class DiscountItem(BaseModel):
    model_config = {"extra": "forbid"}
    discount_type: str = Field(description="e.g. 'trade discount', 'early-payment discount', 'promo code'")
    percent: Optional[float] = Field(default=None, description="Discount rate as a percentage")
    amount: float = Field(description="Discount amount")

class DeductionItem(BaseModel):
    model_config = {"extra": "forbid"}
    deduction_type: str = Field(description="e.g. 'retention/holdback', 'advance payment already received'")
    amount: float = Field(description="Deduction amount")

class TaxIdItem(BaseModel):
    model_config = {"extra": "forbid"}
    id_type: str = Field(description="e.g. 'GSTIN', 'PAN', 'EU VAT', 'USt-IdNr', 'SIRET', 'EIN'")
    value: str = Field(description="The tax ID value")
    party: Optional[str] = Field(default=None, description="'vendor' or 'buyer'")

class PaymentInstructionItem(BaseModel):
    model_config = {"extra": "forbid"}
    method_type: str = Field(description="e.g. 'IBAN+SWIFT/BIC', 'ACH routing+account', 'UPI ID + IFSC'")
    details: str = Field(description="The payment method details/value")

class ReferenceItem(BaseModel):
    model_config = {"extra": "forbid"}
    ref_type: str = Field(description="e.g. 'Sales Order', 'e-Way Bill', 'Credit Note', 'Debit Note'")
    value: str = Field(description="The reference value")

class AddressItem(BaseModel):
    model_config = {"extra": "forbid"}
    address_type: str = Field(description="'billing', 'shipping', or 'vendor'")
    text: str = Field(description="The full address text")
    country: Optional[str] = Field(default=None, description="Country name or code")

class ComplianceMetadataItem(BaseModel):
    model_config = {"extra": "forbid"}
    key: str = Field(description="e.g. 'IRN', 'QR code', 'Peppol electronic address', 'SDI code'")
    value: str = Field(description="The compliance metadata value")

class InvoiceExtractionSchema(BaseModel):
    model_config = {"extra": "forbid"}
    vendor_name: Optional[str] = Field(default=None, description="Name of the vendor")
    invoice_number: Optional[str] = Field(default=None, description="Invoice number")
    invoice_date: Optional[str] = Field(default=None, description="Date of the invoice (YYYY-MM-DD format if possible)")
    due_date: Optional[str] = Field(default=None, description="Due date of the invoice (YYYY-MM-DD format if possible)")
    subtotal: Optional[float] = Field(default=None, description="Subtotal before taxes/discounts. Transcribe printed figure verbatim. On invoices with a 'Subtotal (Taxable Value)' line (common on Indian GST invoices) that is already net of discount, use that printed value as-is rather than adding the discount back. Do not auto-correct math.")
    tax_amount: Optional[float] = Field(default=None, description="Tax amount. Transcribe printed figure verbatim. On invoices with a CGST + SGST (or IGST) split, sum them into this single field. Do not recalculate or auto-correct bad vendor tax math.")
    grand_total: Optional[float] = Field(default=None, description="Grand total amount. Transcribe the printed figure exactly as it appears (e.g. the 'TOTAL DUE' or 'Grand Total' line) — even if it does not appear to reconcile with the subtotal and tax. Do not calculate, correct, or override it yourself; a mismatch between the printed total and the arithmetic is a real finding the downstream verification step needs to see, not something to fix here.")

    round_off: Optional[float] = Field(default=None, description="Small rounding adjustment line (e.g. 'Round Off'), positive or negative, common on Indian GST invoices. Leave null if the invoice has no such line.")
    po_number: Optional[str] = Field(default=None, description="Purchase order (PO) number")
    items: List[InvoiceLineItem] = Field(default=[], description="List of line items in the invoice")
    tags: List[str] = Field(default=[], description="Suggested category or tag keywords for the invoice")
    currency: Optional[str] = Field(default=None, description="ISO 4217 currency code (e.g. INR, EUR, USD)")
    discount_percent: Optional[float] = Field(default=None, description="Top-level discount percentage")
    discount_amount: Optional[float] = Field(default=None, description="Top-level discount amount")
    taxes: List[TaxItem] = Field(default=[], description="Detailed list of taxes")
    discounts: List[DiscountItem] = Field(default=[], description="Detailed list of discounts")
    deductions: List[DeductionItem] = Field(default=[], description="Detailed list of deductions")
    tax_ids: List[TaxIdItem] = Field(default=[], description="List of tax registration numbers")
    payment_instructions: List[PaymentInstructionItem] = Field(default=[], description="Payment methods")
    references: List[ReferenceItem] = Field(default=[], description="Secondary document references")
    addresses: List[AddressItem] = Field(default=[], description="Addresses")
    compliance_metadata: List[ComplianceMetadataItem] = Field(default=[], description="E-invoicing compliance metadata")


# ---------------------------------------------------------------------------
# Outbound (AR) structured output schema — Feature 2.1
# ---------------------------------------------------------------------------
# Gap 283: these two models used to live in `agents/outbound_extraction_agent.py`
# next to a second, near-duplicate LangGraph. The graph is gone (one shared graph
# now, see `_DIRECTION_PROFILES` below); the schema stays a genuinely separate
# model because an outbound document is the tenant's own invoice addressed to a
# customer — `customer_name` instead of `vendor_name` — and because the
# downstream outbound consumers (`queue_worker/outbound_handlers.py`,
# `routers/outbound_audit.py`) are written against exactly this field set.
class OutboundInvoiceLineItem(BaseModel):
    model_config = {"extra": "forbid"}
    description: str = Field(description="Description of the item or service")
    quantity: Optional[float] = Field(default=None, description="Quantity of the item")
    unit_price: Optional[float] = Field(default=None, description="Unit price of the item. CRITICAL: If the printed figure is negative (prefixed with '-' or in parentheses), you MUST extract it as a negative number (e.g., -5000.0).")
    amount: float = Field(description="Total amount for this line item. Transcribe printed figure verbatim. CRITICAL: If the printed figure represents a credit, discount, negative adjustment, or credit-note/debit-note line (often prefixed with a minus sign '-' or enclosed in parentheses like '(5,000)'), you MUST extract it as a negative number (e.g. -5000.0). Do not strip the minus sign or convert it to a positive magnitude.")


class OutboundInvoiceExtractionSchema(BaseModel):
    model_config = {"extra": "forbid"}
    customer_name: Optional[str] = Field(default=None, description="Name of the customer this invoice is addressed to")
    invoice_number: Optional[str] = Field(default=None, description="Invoice number")
    invoice_date: Optional[str] = Field(default=None, description="Date of the invoice (YYYY-MM-DD format if possible)")
    due_date: Optional[str] = Field(default=None, description="Due date of the invoice (YYYY-MM-DD format if possible)")
    subtotal: Optional[float] = Field(default=None, description="Subtotal amount (sum of line items before tax). Transcribe printed figure verbatim.")
    grand_total: Optional[float] = Field(default=None, description="Grand total amount. Transcribe the printed figure exactly as it appears.")
    tax_amount: Optional[float] = Field(default=None, description="Tax amount. Transcribe printed figure verbatim. On invoices with a CGST + SGST (or IGST) split, sum them into this single field AND list each component separately in `taxes`.")
    currency: Optional[str] = Field(default=None, description="ISO 4217 currency code (e.g. INR, EUR, USD)")
    # Gap 293: without these, a correct outbound invoice with a printed trade
    # discount or "Round Off" line always fails verify_totals_math (below) and
    # lands on NEEDS_REVIEW, because the shared verification node passes
    # data.get("discount_amount")/data.get("round_off") straight through and
    # those keys never existed on this schema. Same top-level scalar fields
    # InvoiceExtractionSchema already carries (lines ~120, 125-126) — mirrored
    # here, not the per-line-item discount fields.
    round_off: Optional[float] = Field(default=None, description="Small rounding adjustment line (e.g. 'Round Off'), positive or negative, common on Indian GST invoices. Leave null if the invoice has no such line.")
    discount_percent: Optional[float] = Field(default=None, description="Top-level discount percentage")
    discount_amount: Optional[float] = Field(default=None, description="Top-level discount amount")
    items: List[OutboundInvoiceLineItem] = Field(default=[], description="List of line items in the invoice")
    # Post-Gap-283 correction: Gap 283 added the "sum CGST + SGST into
    # tax_amount" instruction above without giving the model anywhere to put the
    # components, so `verify_tax_amount_in_source_text(..., tax_components=...)`
    # always received None for OUTBOUND. Gap 69's component-aware fallback (the
    # one that exists precisely for split-tax invoices where the summed figure is
    # never printed as a single number) could therefore never engage, and every
    # genuine CGST+SGST outbound invoice failed the tax-faithfulness check for a
    # correctly-extracted value. Same `TaxItem` shape inbound uses, feeding the
    # same shared `Invoice.taxes` JSON column (models.py) both directions already
    # write to.
    taxes: List[TaxItem] = Field(default=[], description="Detailed list of taxes, one entry per printed tax line (e.g. CGST 9% and SGST 9% as two separate entries). Transcribe each component amount verbatim as printed.")


# ---------------------------------------------------------------------------
# Reference documents (PO / quotation) — Feature 26 (Gap 366)
# ---------------------------------------------------------------------------
# A purchase order and a quotation are the SAME shape as far as extraction is
# concerned: a party, a document number, a date, line items, subtotal/tax/total
# and a currency. They differ only in what the header calls itself and in
# whether the number is the tenant's own PO number or the counterparty's quote
# number. So this is ONE schema with a `doc_type` discriminator, not two
# near-identical parallel schemas -- the second schema would have been a
# copy/paste of this one with a different class name, which is exactly the
# duplication Gap 283 spent a whole gap removing from the outbound flow.
#
# Deliberately a NARROWER field set than InvoiceExtractionSchema: no
# `compliance_metadata`, no `payment_instructions`, no `deductions`. A PO is not
# an e-invoice and has no IRN/QR/Peppol block, and asking a model for a field
# the document cannot contain invites it to invent somewhere to put something.
class ReferenceDocLineItem(BaseModel):
    model_config = {"extra": "forbid"}
    description: str = Field(description="Description of the ordered/quoted item or service")
    quantity: Optional[float] = Field(default=None, description="Quantity ordered or quoted")
    unit_price: Optional[float] = Field(default=None, description="Unit price. Transcribe the printed figure verbatim, including a leading minus sign if the line is a credit or discount.")
    amount: Optional[float] = Field(default=None, description="Line total. Transcribe the printed figure verbatim. If the printed figure is negative (prefixed '-' or in parentheses), extract it as a negative number.")
    # --- B3/R10: the line-item matcher's join keys --------------------------
    #
    # WITHOUT THESE, the only key available across the two sides is free-text
    # description -- which is precisely the judgement call `_compare_one()`
    # refused to make when it stopped at line-item COUNT ("Widget, blue, 10pk"
    # vs "Blue widget x10"). Widening this schema is therefore B3's stated
    # PREREQUISITE, not a convenience: L1 matching keys on
    # `hsn_sac_code` + `uom`, and it cannot exist until the reference side
    # carries them.
    #
    # Wording is matched to `InvoiceLineItem`'s deliberately. The two schemas are
    # about to be compared field-for-field, and two descriptions of the same
    # concept are how a model comes to populate them differently.
    #
    # Additive and all Optional, so every existing REFERENCE extraction stays
    # valid byte-for-byte; the schema is `extra="forbid"`, so this is a real
    # edit rather than a no-op.
    hsn_sac_code: Optional[str] = Field(default=None, description="HSN/SAC code (mandatory for Indian GST)")
    uom: Optional[str] = Field(default=None, description="Unit of measure (e.g., each, kg, hours)")
    line_number: Optional[int] = Field(default=None, description="The line's printed row number or serial number, if the document numbers its rows. Null if the table is unnumbered — never invent a position.")
    page_number: Optional[int] = Field(default=None, description="The 1-based page this row is printed on. Fill it only when you can see which page the row came from; null otherwise. NEVER guess a page, and never assume page 1 for a multi-page document -- a wrong page reference is worse than none, because it sends a reader to the wrong place to check a figure.")


class ReferenceDocExtractionSchema(BaseModel):
    model_config = {"extra": "forbid"}
    doc_type: Optional[str] = Field(default=None, description="What this document calls itself: 'PURCHASE_ORDER' if it is a purchase order, 'QUOTATION' if it is a quotation/quote/estimate/proforma, otherwise 'OTHER'. Decide from the printed document title, not from the content.")
    party_name: Optional[str] = Field(default=None, description="The counterparty named on the document -- the supplier a purchase order is addressed to, or the issuer of a quotation.")
    doc_number: Optional[str] = Field(default=None, description="The document's own number as printed (PO number, or quotation/quote number).")
    po_number: Optional[str] = Field(default=None, description="The purchase order number this document references. On a purchase order this is normally the same value as doc_number; on a quotation it is the customer PO number if one is quoted, otherwise null.")
    doc_date: Optional[str] = Field(default=None, description="Date of the document (YYYY-MM-DD format if possible)")
    subtotal: Optional[float] = Field(default=None, description="Subtotal before taxes/discounts. Transcribe the printed figure verbatim. Do not auto-correct math.")
    tax_amount: Optional[float] = Field(default=None, description="Total tax. Transcribe the printed figure verbatim. On a CGST + SGST (or IGST) split, sum them into this single field. Do not recalculate.")
    grand_total: Optional[float] = Field(default=None, description="Grand total as printed. Transcribe exactly, even if it does not reconcile with subtotal plus tax -- a mismatch is a real finding for the comparison step, not something to fix here.")
    currency: Optional[str] = Field(default=None, description="ISO 4217 currency code (e.g. INR, EUR, USD)")
    discount_amount: Optional[float] = Field(default=None, description="Top-level discount amount, if printed")
    items: List[ReferenceDocLineItem] = Field(default=[], description="List of ordered or quoted line items")
    taxes: List[TaxItem] = Field(default=[], description="Detailed list of taxes, one entry per printed tax line")


# ---------------------------------------------------------------------------
# Feature 27 (G3) — the generic document schema, for NON-INVOICE types only
# ---------------------------------------------------------------------------
# Design record: `docs/feature_27_generic_extraction.md`, E8 as scoped by
# amendment A2. Read both before changing anything below.
#
# SCOPE, WHICH IS THE WHOLE POINT OF A2: nothing here is ever applied to an
# invoice. The INVOICE family (`INVOICE`, `PROFORMA_INVOICE`, `CREDIT_NOTE`,
# `DEBIT_NOTE` — `MONEY_FAMILY`) keeps `InvoiceExtractionSchema` /
# `OutboundInvoiceExtractionSchema` and the existing `_DIRECTION_PROFILES`
# machinery in BOTH flag states. `GenericDocumentSchema`'s spine deliberately
# carries none of `compliance_metadata` (the India IRN/QR e-invoicing block),
# `payment_instructions`, `deductions`, `tax_ids`, `addresses`, `round_off`,
# `discount_percent` or per-line `hsn_sac_code` — putting an invoice on it would
# silently drop years of Gap 31/33/36/43/44/46/293 work with no error raised
# anywhere. That is why these classes are ADDITIVE: every existing schema above
# is untouched.
#
# `ReferenceDocExtractionSchema` (above) also stays exactly as it is. It is
# Feature 26's chat-attachment path with its own three-value vocabulary, and A2
# leaves the REFERENCE direction unchanged in v1.
#
# WIRING STATUS (updated by G3b): these classes and the two prompt builders below
# are now named by the `GENERIC` entry in `_DIRECTION_PROFILES` and reachable
# through `resolve_extraction_profile()` — but that function is itself called from
# nowhere. `extract_node`/`verify_node`/`run_extraction_agent` still call
# `resolve_direction_profile` directly, so no document has yet been extracted on
# this schema. The graph node and the conditional entry point are G4; the
# family-keyed verification rubric is G5.
class GenericLineItem(BaseModel):
    """A line on any commercial document — widened from `ReferenceDocLineItem`.

    **Every field is Optional and defaults to `None`, deliberately (E8).** A
    delivery note legitimately prints no `unit_price`; a framework contract
    legitimately prints no `amount`; a GRN prints a received quantity against an
    ordered one. `None` means "the document did not state it" and must NEVER be
    read, written or coerced as zero — Gap 283 already fixed exactly that
    truthiness bug in `verify_node` (a real printed 0.00 being read as missing),
    and re-introducing the inverse here would be the same defect facing the other
    way. No validator on this model converts an absent value into `0`, `0.0` or
    `""`, and none should be added.

    `description` is Optional here where `ReferenceDocLineItem.description` is
    required: a delivery-note row can be a bare part number with a quantity, and
    a required field on a structured-output schema is an invitation to invent one.
    """
    model_config = {"extra": "forbid"}
    description: Optional[str] = Field(default=None, description="Description of the item, service or material as printed. Null if the row prints no description at all.")
    quantity: Optional[float] = Field(default=None, description="The row's headline quantity as printed. If the row prints several quantity columns (ordered / delivered / received), put the one the document leads with here and fill the specific fields below as well. Null if no quantity is printed.")
    unit_price: Optional[float] = Field(default=None, description="Unit price, transcribed verbatim including a leading minus sign if the line is a credit or discount. NULL if no price is printed — many document types omit prices by design. Never infer or compute one.")
    amount: Optional[float] = Field(default=None, description="Line total, transcribed verbatim. If the printed figure is negative (prefixed '-' or in parentheses), extract it as a negative number. NULL if no amount is printed — do NOT compute quantity * unit_price.")
    quantity_ordered: Optional[float] = Field(default=None, description="Quantity ordered, ONLY when the row prints an explicit ordered/order-qty column (common on a purchase order, a GRN or a part-delivery note). Null otherwise.")
    quantity_delivered: Optional[float] = Field(default=None, description="Quantity actually despatched/delivered, ONLY when the row prints it as its own column. Null otherwise.")
    quantity_received: Optional[float] = Field(default=None, description="Quantity actually received/accepted, ONLY when the row prints it as its own column (a goods receipt note typically prints ordered, received and rejected side by side). Null otherwise.")
    uom: Optional[str] = Field(default=None, description="Unit of measure exactly as printed (e.g. 'NOS', 'KG', 'PCS', 'hours', 'each').")
    batch_or_serial: Optional[str] = Field(default=None, description="Batch, lot or serial number printed against this row, as a single string. Null if the row prints none.")
    page_number: Optional[int] = Field(default=None, description="The 1-based page this row is printed on. Fill it only when you can see which page the row came from; null otherwise. NEVER guess a page, and never assume page 1 for a multi-page document -- a wrong page reference is worse than none, because it sends a reader to the wrong place to check a figure.")

    # NOT widened with `hsn_sac_code` / `line_number`, deliberately -- an earlier
    # pass of R10 added them here and two tests caught it. A2 names per-line
    # `hsn_sac_code` among the invoice-only fields the generic spine must NOT
    # carry, and `test_the_existing_schemas_are_unchanged_by_g3` asserts exactly
    # that. B3's prerequisite is `ReferenceDocLineItem` (Feature 26's
    # chat-attachment path), which is a different schema; widening this one was
    # scope creep that would have weakened A2 for no caller.

class ReferencedDocument(BaseModel):
    """One document a statement or remittance advice REFERS TO (A7).

    An advisory document's whole substance is a list of pointers at other
    documents -- which invoices a payment covers, which invoices are still open.
    This is the shape of one such pointer, and it is what Feature 26's
    `list_reconcile` comparison joins against `Invoice` rows.

    Every field Optional: a statement line may print a number and an amount and
    nothing else. `status_hint` is transcribed EXACTLY AS PRINTED and never
    inferred -- "Open" on a supplier's statement is the supplier's claim, not our
    finding, and the entire value of reconciling is in seeing where the two differ.
    """
    model_config = {"extra": "forbid"}

    doc_number: Optional[str] = Field(default=None, description="The referenced document's number, exactly as printed (an invoice number, a credit note number, a payment reference).")
    doc_date: Optional[str] = Field(default=None, description="The referenced document's date as printed, ISO 8601 if unambiguous. Null if not stated.")
    amount: Optional[float] = Field(default=None, description="The amount shown against this reference. Transcribe exactly, including a negative sign for a credit. Null if no amount is printed on the line.")
    currency: Optional[str] = Field(default=None, description="ISO currency code for this line if printed per-line. Null if the document states one currency globally.")
    status_hint: Optional[str] = Field(default=None, description="The status the DOCUMENT ITSELF claims for this reference: OPEN, PAID, PARTIALLY_PAID or DISPUTED. Transcribe only what is printed and never infer one from the amount -- this is the counterparty's claim, and comparing it to our own record is the point.")


class DeductionItem(BaseModel):
    """One amount withheld from a payment (A7).

    This is what makes "what did they short-pay?" answerable. A remittance advice
    that settles 92,000 against a 100,000 invoice is not a discrepancy to
    investigate if it also prints "TDS u/s 194C: 8,000" -- it is a correct
    payment, and the deduction is the explanation.

    Deductions are reported INDIVIDUALLY and never netted into one figure: a
    single unexplained 8,000 gap is a support ticket, while "TDS 6,000 +
    chargeback 2,000" is an answer.
    """
    model_config = {"extra": "forbid"}

    kind: Optional[str] = Field(default=None, description="What was withheld: TDS, GST_TDS, CHARGEBACK, SKONTO, EARLY_PAYMENT_DISCOUNT, RETENTION, or OTHER. Choose from the printed label; use OTHER rather than guessing.")
    amount: Optional[float] = Field(default=None, description="The amount withheld, as a positive number. Null if the document names a deduction without quantifying it.")
    currency: Optional[str] = Field(default=None, description="ISO currency code if printed per-line. Null if global.")
    reference: Optional[str] = Field(default=None, description="What the deduction is against or under -- an invoice number, a TDS section, a chargeback code. Quoted as printed.")


class GenericDocumentSchema(BaseModel):
    """The union spine every commercial document has (E8), for non-INVOICE types.

    One schema object with prompt-level overlays (`_DOC_TYPE_OVERLAYS`), not ten
    schemas: one `with_structured_output` call shape and one place a field can
    drift. Same `None`-is-not-zero discipline as `GenericLineItem` above — a
    contract with no grand total and a delivery note with no currency are normal
    documents, not incomplete extractions.

    `party_name` / `counterparty_name` are defined here once, by ROLE rather than
    by document type: `party_name` is whoever ISSUED the document,
    `counterparty_name` whoever it is addressed to. Nine types with nine
    different words for the same two roles (vendor/buyer, supplier/consignee,
    quoting party/prospect) is how a field acquires a different meaning per
    document, which is precisely what a union spine exists to avoid.
    """
    model_config = {"extra": "forbid"}
    doc_type: Optional[str] = Field(
        default=None,
        description=(
            "What this document calls itself, as one of: "
            + ", ".join(DOC_TYPES)
            + ". Decide from the printed title, not from what the document mentions."
        ),
    )
    # NOTE, deliberate: this is a plain Optional[str], not a Literal over
    # DOC_TYPES, even though `DocTypeClassification.doc_type` in the classifier IS
    # a Literal. The reason is the blast radius of a violation. There, an
    # out-of-vocabulary value is the classifier's whole answer and failing it
    # closed to OTHER costs nothing. Here it would fail the ENTIRE extraction —
    # every line item, every total — over a disagreement about a label that the
    # deterministic classifier has already decided authoritatively upstream. This
    # field is a cross-check on that decision, not the decision.
    party_name: Optional[str] = Field(default=None, description="The party that ISSUED this document (the supplier despatching goods, the buyer raising an order, the party making an offer).")
    counterparty_name: Optional[str] = Field(default=None, description="The party this document is ADDRESSED TO (the consignee receiving goods, the supplier an order is placed with, the party being quoted).")
    doc_number: Optional[str] = Field(default=None, description="The document's own number as printed (challan number, PO number, quotation number, contract reference).")
    po_number: Optional[str] = Field(default=None, description="The purchase order number this document REFERENCES. On a purchase order this is normally the same value as doc_number; elsewhere it is the order the document is raised against, or null.")
    reference_numbers: List[str] = Field(default=[], description="Any other document numbers this one cites, as printed strings (e.g. an original invoice number a credit note adjusts, a quotation number an order accepts, a delivery-note number a GRN receipts). One entry per printed reference.")
    doc_date: Optional[str] = Field(default=None, description="Date printed on the document (YYYY-MM-DD format if possible).")
    valid_until: Optional[str] = Field(default=None, description="The end of the document's validity window, where one is printed — a quotation's expiry, a proforma's validity, a contract's end date (YYYY-MM-DD format if possible). Null if the document states none. Do NOT derive it from the document date.")
    currency: Optional[str] = Field(default=None, description="ISO 4217 currency code (e.g. INR, EUR, USD). Null if the document prints no monetary values at all — that is normal for a delivery note or a goods receipt note.")
    subtotal: Optional[float] = Field(default=None, description="Subtotal before taxes/discounts, transcribed verbatim. Null if not printed. Never computed from the line items.")
    tax_amount: Optional[float] = Field(default=None, description="Total tax, transcribed verbatim. On a CGST + SGST (or IGST) split, sum them into this single field and list each component in `taxes`. Null if the document prints no tax.")
    discount_amount: Optional[float] = Field(default=None, description="Top-level discount amount, if printed. Null otherwise.")
    grand_total: Optional[float] = Field(default=None, description="Grand total as printed, transcribed exactly even if it does not reconcile with subtotal plus tax. NULL if the document prints no total — a rate card, a framework agreement and an unpriced delivery note all legitimately have none. Never compute one.")
    items: List[GenericLineItem] = Field(default=[], description="The document's line items, one entry per printed row. Empty list if the document has no line-item table.")
    taxes: List[TaxItem] = Field(default=[], description="Detailed list of taxes, one entry per printed tax line. Empty if none are printed.")
    payment_terms: Optional[str] = Field(default=None, description="Payment terms as printed (e.g. 'Net 30 days from invoice date', '30% advance, balance against delivery'). Null if not stated.")
    delivery_terms: Optional[str] = Field(default=None, description="Delivery terms, schedule or lead time as printed (e.g. 'Delivery within 4 weeks of order', 'Ex-works Pune'). Null if not stated.")
    incoterms: Optional[str] = Field(default=None, description="Incoterms as printed, with the named place if given (e.g. 'FOB Nhava Sheva', 'DDP Hamburg', 'CIF'). Null if not stated.")
    notes: Optional[str] = Field(default=None, description="Free-text terms, conditions and remarks worth keeping that no other field holds — validity/renewal/termination wording, short-delivery or damage remarks, the reason a credit or debit note was raised. Quote the document rather than summarising it.")
    # --- A7/R9: the ADVISORY family's two lists -----------------------------
    #
    # Populated for STATEMENT_OF_ACCOUNT and REMITTANCE_ADVICE, and empty for
    # every other type. They are additive and default to `[]`, so no existing
    # document's extracted shape changes.
    #
    # These carry the substance of a document that HAS NO LINE ITEMS to diff
    # (research §5 trap 6). A statement's rows are pointers at other documents,
    # not goods, which is why Feature 26 gives this family its own comparison
    # mode (`list_reconcile`, B8) instead of running the L1-L3 line matcher over
    # something that is not a line.
    referenced_documents: List[ReferencedDocument] = Field(default=[], description="For a STATEMENT OF ACCOUNT or REMITTANCE ADVICE: one entry per referenced invoice, credit note or payment listed on the document. Empty for every other document type. Transcribe the list exactly and never total it.")
    # NAMED `payment_deductions`, NOT `deductions` -- a deliberate deviation from
    # A7's field name, forced by a collision the disjointness test caught.
    #
    # `deductions` already exists on `InvoiceExtractionSchema` (Tasks 2.21-2.31)
    # and means something ELSE: deduction LINES on an invoice. A2 guarantees the
    # generic spine carries none of the invoice-only fields, and
    # `test_the_existing_schemas_are_unchanged_by_g3` asserts that set is disjoint
    # -- which is how the repo proves an invoice is never silently extracted onto
    # the generic schema, dropping compliance_metadata and the rest.
    #
    # Reusing the name would have broken a load-bearing invariant to satisfy a
    # label. These are genuinely different things (an invoice's deduction lines
    # vs amounts withheld from a payment), so the distinct name is also the more
    # honest one.
    payment_deductions: List[DeductionItem] = Field(default=[], description="For a REMITTANCE ADVICE: one entry per amount withheld from the payment (TDS, GST-TDS, chargeback, Skonto, retention). Empty for every other document type. Report each separately and NEVER net them into a single figure.")


# 2. State definition
class ExtractionState(TypedDict):
    file_path: str
    ocr_text: str
    images: List[str]
    extracted_data: Optional[Dict[str, Any]]
    alerts: List[Dict[str, Any]]
    status: str
    rules: Optional[Dict[str, Any]]
    complexity: str
    ocr_result: Optional[Any]
    retry_count: int
    max_retries: int
    feedback: List[str]
    dynamic_qa_context: Optional[str]
    # Gap 283: "INBOUND" (a vendor's bill received by the tenant) or "OUTBOUND"
    # (the tenant's own invoice sent to a customer). This is the ONLY thing that
    # differs between the two flows inside the graph — see `_DIRECTION_PROFILES`.
    flow_direction: str
    # Feature 23 Phase 1: carried purely so the per-call telemetry event can be
    # attributed to a tenant. No node reads it for any extraction decision — the
    # graph's behaviour is identical whether it is present, empty or absent.
    tenant_id: str
    # Feature 27 (G4/E7). Written by `classify_doc_type_node`, which is present in
    # the compiled graph ONLY when `ENABLE_GENERIC_EXTRACTION` is on (see
    # `_build_extraction_graph`). With the flag off the node is absent from the
    # graph entirely, so these three keys stay `None` for the whole run and
    # `resolve_extraction_profile(direction, None)` returns exactly the profile
    # `resolve_direction_profile(direction)` returns today — E3's guarantee.
    #
    # `doc_type` is one of `DOC_TYPES` (the classifier's own output is
    # `Literal`-constrained to them) or `None` for "not classified".
    # `doc_type_evidence` is the verbatim printed phrase the decision was made
    # from, so a misclassification is reviewable rather than only wrong (E7), and
    # `doc_type_confidence` is what N2's threshold calibration needs; both are
    # columns on E10's `documents` table, which is why they are carried forward
    # rather than only logged. The classifier's `doc_type_method` /
    # `doc_type_reason` are logged by the node and deliberately not carried: they
    # have no persistence target in E10's column list.
    doc_type: Optional[str]
    doc_type_evidence: Optional[str]
    doc_type_confidence: Optional[float]
    # Feature 27 A6/R8. Written by `classify_doc_type_node`; persisted onto the
    # row's `doc_attributes` column by the handler. Absent (not None) on every
    # flag-OFF run, because the node that writes it is not in that graph at all.
    doc_attributes: Optional[Dict[str, Any]]



# 3. Document to base64 images helper
#
# Feature 27 (G8, §4 "Non-PDF image support"). The extensions this dispatches to
# the single-page image branch. Kept as a module-level constant rather than
# inlined so `components/ingestion/DropZone.tsx`'s accept list (FE task G11) has
# one authoritative thing to agree with, and so a test can assert the two halves
# of the dispatch are exhaustive over it.
#
# `.tif` is included alongside `.tiff` because scanners emit both spellings and a
# document silently losing its visual channel over a missing character is exactly
# the failure this task exists to remove.
_IMAGE_SUFFIXES: tuple[str, ...] = (
    ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp",
)


def document_to_base64_images(file_path: str) -> List[str]:
    """
    Converts a document into base64 PNG strings for the multimodal visual channel,
    dispatching on the file's suffix.

    Feature 27 (G8). Before this, the function was `pdf_to_base64_images` and
    opened *whatever it was given* with `fitz.open(..., filetype="pdf")`. §4 is
    explicit that **the silent degradation is the actual defect, more than the
    missing format**, which is why the third branch below logs rather than just
    returning empty.

    **One correction of fact, measured while building this (Gap 384).** §4 states
    that handing that old function a PNG made the `except` log and return `[]`.
    Against the installed PyMuPDF (1.28.0 / MuPDF 1.29.0) it does **not**:
    `fitz.open(stream=<png bytes>, filetype="pdf")` succeeds, because MuPDF sniffs
    the real container and ignores the declared `filetype`, and the PNG comes back
    as a one-page document. So the pre-G8 silent loss was real for formats MuPDF
    cannot parse at all (`.docx`, `.xlsx`) and for corrupt bytes, but *not* for the
    common image formats §4 names. That does not make this branch redundant — it
    makes it deterministic. Relying on an undeclared sniffing behaviour of a
    vendored C library to render half the accepted input formats is a dependency
    on something nobody wrote down and no version pin protects; the explicit pillow
    path is the same output from a stated contract.

    Three branches, and the split is the whole function:

      * `.pdf` -> today's `fitz` page-render path, unchanged. Byte-for-byte: same
        `get_pixmap()`, same `tobytes("png")`, same `data:image/png;base64,`
        prefix, same one entry per page, same error handling. A test asserts a
        PDF's output is identical to what the old function produced.
      * an image suffix (`_IMAGE_SUFFIXES`) -> single page: read the bytes,
        normalise to PNG through pillow (already a dependency, `pillow>=12.2.0`,
        and already used by `utils/token_management.py` to size images for the
        token guardrail), base64-encode, return a one-element list. Normalising
        rather than passing the original bytes through matters because the data
        URL prefix says `image/png`: shipping JPEG bytes under a PNG media type
        is the kind of thing that works on one model endpoint and not the next.
      * anything else -> `[]` **and a WARNING naming the extension.** This is the
        fix. `[]` is still the right return — an unrenderable attachment must not
        take an extraction down, since OCR text alone is a degraded but genuine
        answer — but it is no longer silent.

    `download_pdf_from_storage`'s own failure (a missing blob) keeps its existing
    warning-and-empty-list behaviour and is deliberately **not** folded into the
    unsupported-format warning: "the file is not where we think it is" and "we
    cannot render this format" are different operational problems with different
    fixes, and merging them would make the new warning useless for the thing it
    was added to detect.

    `pdf_to_base64_images` remains as a thin alias below — `agents/outbound_extraction_agent.py`
    imports it by that name, `run_extraction_agent` calls it, and
    `benchmarks/extraction/harness.py` names it in its docstring.
    """
    base64_images: List[str] = []
    suffix = "." + file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""

    if suffix not in (".pdf",) + _IMAGE_SUFFIXES:
        # The G8 fix. WARNING, not DEBUG: a document arriving in a format this
        # pipeline cannot render is a real (if survivable) loss of extraction
        # quality, and it was previously invisible.
        logger.warning(
            "Cannot render %r for the multimodal channel: unsupported extension %r "
            "(supported: .pdf plus %s). Extraction will continue on OCR text only.",
            file_path, suffix or "<none>", ", ".join(_IMAGE_SUFFIXES),
        )
        return base64_images

    try:
        file_bytes = download_pdf_from_storage(file_path)
    except Exception as e:
        logger.warning("PDF file not found for base64 conversion: %s (%s)", file_path, e)
        return base64_images

    if suffix in _IMAGE_SUFFIXES:
        try:
            from PIL import Image

            buffer = io.BytesIO()
            with Image.open(io.BytesIO(file_bytes)) as image:
                # A scanned TIFF can be 1-bit or CMYK, and a PNG-encoded CMYK
                # image is not a thing pillow will write. RGB is the common
                # denominator every vision endpoint accepts. Bound to a second
                # name so the `with` still closes the image it opened.
                renderable = image if image.mode in ("RGB", "RGBA", "L") else image.convert("RGB")
                renderable.save(buffer, format="PNG")
            b64_str = base64.b64encode(buffer.getvalue()).decode("utf-8")
            base64_images.append(f"data:image/png;base64,{b64_str}")
        except Exception as e:
            # Same failure policy as the PDF branch below: an unreadable image
            # degrades the extraction to OCR text, it does not fail it.
            logger.error("Failed to convert image %s to a base64 PNG: %s", file_path, e)
        return base64_images

    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        for page in doc:
            pix = page.get_pixmap()
            img_bytes = pix.tobytes("png")
            b64_str = base64.b64encode(img_bytes).decode("utf-8")
            base64_images.append(f"data:image/png;base64,{b64_str}")
        doc.close()
    except Exception as e:
        logger.error("Failed to convert PDF pages to base64 images: %s", e)
    return base64_images


def pdf_to_base64_images(file_path: str) -> List[str]:
    """Feature 27 (G8): the pre-rename name, kept as a thin alias.

    Deliberately a wrapper rather than a module-level assignment
    (`pdf_to_base64_images = document_to_base64_images`): the existing tests and
    `queue_worker` patch sites use `patch("agents.extraction_agent.pdf_to_base64_images")`,
    and an alias that is the *same object* would make a patch of one silently
    patch the other, which is the kind of test-only coupling that later reads as a
    real behavioural guarantee. §4 asks only that no existing caller or test
    breaks — `agents/outbound_extraction_agent.py:37` imports this name,
    `run_extraction_agent` calls it, and `benchmarks/extraction/harness.py`
    documents it.
    """
    return document_to_base64_images(file_path)

def build_multimodal_prompt(ocr_text: str, images: List[str], rules: Optional[Dict[str, Any]] = None) -> List[HumanMessage]:
    """
    Pipes visual streams and OCR text layout content into the agent model.
    """
    prompt_text = (
        "You are an expert invoice processing agent. Analyze the following OCR text "
        "and visual representations of the invoice. Extract structured data aligning "
        "with the schema.\n\n"
        + GAP_46_VERBATIM_DIRECTIVE
    )
    # Feature 18: one shared normalizer renders legacy free-text rules and
    # structured rule objects into identical prompt lines, so a tenant's
    # already-committed strings behave exactly as they did before.
    prompt_constraints = normalize_constraints(rules)
    if prompt_constraints:
        prompt_text += "You MUST respect the following layout extraction constraints/rules:\n"
        for rule in prompt_constraints:
            prompt_text += f"- {rule}\n"
        prompt_text += "\n"

    prompt_text += f"OCR Text:\n{ocr_text}"
    
    content = [
        {
            "type": "text",
            "text": prompt_text
        }
    ]
    for img_url in images:
        content.append({
            "type": "image_url",
            "image_url": {"url": img_url}
        })
    return [HumanMessage(content=content)]


def build_outbound_multimodal_prompt(ocr_text: str, images: List[str], rules: Optional[Dict[str, Any]] = None) -> List[HumanMessage]:
    """Framed as the tenant's own invoice being sent to a customer, not a
    vendor's invoice being received -- the one prompt-level difference from
    the inbound path, everything else about reading a printed document is
    the same."""
    prompt_text = (
        "You are an expert invoice processing agent. This is the TENANT'S OWN invoice, "
        "being sent to one of their customers -- not a vendor bill being received. "
        "Analyze the following OCR text and visual representations of the invoice. "
        "Extract structured data aligning with the schema.\n\n"
        + GAP_46_VERBATIM_DIRECTIVE
    )
    # Feature 18: same shared normalizer as the inbound path -- legacy strings
    # and structured rule objects render identically.
    prompt_constraints = normalize_constraints(rules)
    if prompt_constraints:
        prompt_text += "You MUST respect the following layout extraction constraints/rules:\n"
        for rule in prompt_constraints:
            prompt_text += f"- {rule}\n"
        prompt_text += "\n"

    prompt_text += f"OCR Text:\n{ocr_text}"

    content = [{"type": "text", "text": prompt_text}]
    for img_url in images:
        content.append({"type": "image_url", "image_url": {"url": img_url}})
    return [HumanMessage(content=content)]


def _build_inbound_text_prompt(state: "ExtractionState", rules: Optional[Dict[str, Any]]) -> str:
    """Text-only (no page images / non-Azure) inbound extraction prompt.
    Extracted verbatim out of `extract_node` by Gap 283 so the direction
    profile can select it — the wording is unchanged."""
    if state.get("complexity") == "COMPLEX":
        prompt = (
            "You are analyzing a COMPLEX invoice. This invoice contains complex layouts, multi-tax tables (like GST/VAT), "
            "or item-level discount structures. Please perform a deep dynamic extraction. Do not restrict yourself to standard fields; "
            "extract all taxes, discounts, deductions, compliance metadata, and banking references into the appropriate list structures.\n\n"
            + GAP_46_VERBATIM_DIRECTIVE
        )
        dynamic_qa_context = state.get("dynamic_qa_context")
        if dynamic_qa_context:
            prompt += f"\nDYNAMIC LAYOUT PRE-ANALYSIS FINDINGS (Gap 4 Targeted Q&A):\n{dynamic_qa_context}\n"
        prompt += f"\nExtract structured details from the following invoice OCR text:\n\n{state['ocr_text']}"
    else:
        prompt = (
            "Extract structured details from the following standard invoice OCR text:\n\n"
            + GAP_46_VERBATIM_DIRECTIVE
        )
        prompt_constraints = normalize_constraints(rules)
        if prompt_constraints:
            prompt += "You MUST respect the following layout extraction constraints/rules:\n"
            for rule in prompt_constraints:
                prompt += f"- {rule}\n"
            prompt += "\n"
        prompt += f"{state['ocr_text']}"
    return prompt


def _build_outbound_text_prompt(state: "ExtractionState", rules: Optional[Dict[str, Any]]) -> str:
    """Text-only outbound extraction prompt. Same tenant's-own-invoice framing
    as `build_outbound_multimodal_prompt`. Gap 283 additionally threads the
    COMPLEX classification and the dynamic-QA findings through here, which the
    old 2-node outbound graph had no way to produce. Deliberately does NOT ask
    for `discounts[]`/`deductions[]`/`compliance_metadata[]` the way the inbound
    COMPLEX prompt does — `OutboundInvoiceExtractionSchema` has no such LIST
    fields, so asking for them would invite the model to invent a place to put
    them. `taxes[]` is the exception, and does get asked for: the schema carries
    it (post-Gap-283 correction) precisely so the summed `tax_amount` on a
    split-tax invoice has verifiable components to fall back on. The schema does
    carry top-level scalar `discount_percent`/`discount_amount`/`round_off`
    (Gap 293) — no extra prompt text needed for those, same as inbound, since
    the schema field descriptions alone drive structured-output extraction."""
    prompt = (
        "This is the tenant's own outbound invoice, being sent to a customer. "
        "Extract structured details from the following OCR text:\n\n"
        + GAP_46_VERBATIM_DIRECTIVE
    )
    if state.get("complexity") == "COMPLEX":
        prompt += (
            "This invoice has been classified as COMPLEX (multi-rate tax tables, retention/holdback "
            "lines, or specialised compliance identifiers). Read the totals block carefully: "
            "`tax_amount` must be the sum of every printed tax component, transcribed verbatim, "
            "and every individual printed tax line (e.g. CGST 9%, SGST 9%, IGST 18%) must ALSO be "
            "listed separately in `taxes` with its own verbatim amount.\n\n"
        )
    dynamic_qa_context = state.get("dynamic_qa_context")
    if dynamic_qa_context:
        prompt += f"DYNAMIC LAYOUT PRE-ANALYSIS FINDINGS (Gap 4 Targeted Q&A):\n{dynamic_qa_context}\n\n"
    prompt_constraints = normalize_constraints(rules)
    if prompt_constraints:
        prompt += "You MUST respect the following layout extraction constraints/rules:\n"
        for rule in prompt_constraints:
            prompt += f"- {rule}\n"
        prompt += "\n"
    prompt += state["ocr_text"]
    return prompt


def build_reference_multimodal_prompt(ocr_text: str, images: List[str], rules: Optional[Dict[str, Any]] = None) -> List[HumanMessage]:
    """Feature 26: framed as a REFERENCE document (purchase order or quotation),
    not a bill. The distinction matters at the prompt level because a PO's
    totals are an *intent to buy* and a quotation's are an *offer* -- neither is
    an amount owed, and a model told it is reading an invoice will happily
    relabel a 'Quotation Total' as a grand total due."""
    prompt_text = (
        "You are reading a REFERENCE commercial document -- a PURCHASE ORDER or a "
        "QUOTATION. It is NOT an invoice and nothing on it is an amount currently "
        "owed: a purchase order records what was ordered, a quotation records what "
        "was offered. Analyze the following OCR text and visual representations and "
        "extract structured data aligning with the schema.\n\n"
        "Set `doc_type` from the document's own printed title: 'PURCHASE_ORDER' for a "
        "purchase order, 'QUOTATION' for a quotation/quote/estimate/proforma, "
        "'OTHER' if it is plainly neither. Do not guess from the content if the "
        "title is legible.\n\n"
        + GAP_46_VERBATIM_DIRECTIVE
    )
    prompt_constraints = normalize_constraints(rules)
    if prompt_constraints:
        prompt_text += "You MUST respect the following layout extraction constraints/rules:\n"
        for rule in prompt_constraints:
            prompt_text += f"- {rule}\n"
        prompt_text += "\n"

    prompt_text += f"OCR Text:\n{ocr_text}"

    content = [{"type": "text", "text": prompt_text}]
    for img_url in images:
        content.append({"type": "image_url", "image_url": {"url": img_url}})
    return [HumanMessage(content=content)]


def _build_reference_text_prompt(state: "ExtractionState", rules: Optional[Dict[str, Any]]) -> str:
    """Text-only (no page images / non-Azure) reference-document prompt. Same
    framing as `build_reference_multimodal_prompt`."""
    prompt = (
        "This is a REFERENCE commercial document -- a PURCHASE ORDER or a QUOTATION, "
        "not an invoice and not an amount owed. Set `doc_type` from the printed "
        "document title. Extract structured details from the following OCR text:\n\n"
        + GAP_46_VERBATIM_DIRECTIVE
    )
    dynamic_qa_context = state.get("dynamic_qa_context")
    if dynamic_qa_context:
        prompt += f"DYNAMIC LAYOUT PRE-ANALYSIS FINDINGS (Gap 4 Targeted Q&A):\n{dynamic_qa_context}\n\n"
    prompt_constraints = normalize_constraints(rules)
    if prompt_constraints:
        prompt += "You MUST respect the following layout extraction constraints/rules:\n"
        for rule in prompt_constraints:
            prompt += f"- {rule}\n"
        prompt += "\n"
    prompt += state["ocr_text"]
    return prompt


# ---------------------------------------------------------------------------
# Feature 27 (G3) — generic extraction prompts: base template + per-type overlay
# ---------------------------------------------------------------------------
# E8: "Overlays are prompt-level, not schema-level." One `GenericDocumentSchema`
# and one `with_structured_output` call shape; what changes per document type is
# the instructions appended to a shared base template. Ten schemas would mean ten
# places a field can drift.
#
# Two lookups, both keyed maps rather than `if doc_type == ...` chains, for the
# same reason E6 gives for the rubric map: an eleventh document type should be
# one map entry, never a new branch.
#
#   `_GENERIC_FAMILY_STANCE`  — keyed on `DOC_TYPE_FAMILY[doc_type]`, one short
#                               paragraph per verification family. This is what a
#                               newly-added type inherits before anyone writes it
#                               a specific overlay, so the default is conservative
#                               rather than invoice-shaped.
#   `_DOC_TYPE_OVERLAYS`      — keyed on the `doc_type` itself, one entry per
#                               NON-INVOICE value in `DOC_TYPES`. Completeness is
#                               asserted by a loop-based test
#                               (`tests/test_generic_extraction.py`) so adding a
#                               type without an overlay fails loudly.
#
# `INVOICE` deliberately has NO overlay: per A2 an invoice never reaches this
# path at all, and providing one would make the omission look like an oversight
# to whoever wires G3b. `resolve_doc_type_overlay()` logs a warning if it is ever
# asked for one, rather than quietly serving a generic prompt for a document that
# should have gone to `InvoiceExtractionSchema`.
_GENERIC_FAMILY_STANCE: Dict[str, str] = {
    ADVISORY_FAMILY: (
        "This document is ADVISORY: it reports on other documents and is NEVER itself a payable. "
        "Its substance is a LIST OF REFERENCES -- invoice numbers, credit notes, payments -- and, "
        "on a remittance advice, the DEDUCTIONS taken against them.\n"
        "- Transcribe the list exactly. Do NOT total it, do not reconcile it, and do not compute a "
        "balance the document does not print.\n"
        "- Report each deduction separately with its own stated reason. Never net several "
        "deductions into one figure -- the reasons are the answer, not the arithmetic.\n"
        "- A status printed against a reference (Open, Paid, Overdue) is the COUNTERPARTY'S CLAIM. "
        "Transcribe it as printed and never infer one from an amount."
    ),
    MONEY_FAMILY: (
        "This document type prints monetary values and its arithmetic is checked downstream. "
        "Transcribe every figure exactly as printed. A total that does not reconcile with the "
        "lines above it is a real finding for the verification step, not something to correct here."
    ),
    QUANTITY_FAMILY: (
        "This is a QUANTITY document. Quantities, units of measure and item identity are the "
        "substance of it; prices and totals are optional and are frequently absent BY DESIGN. "
        "An absent price is not an error, not a zero, and not something to derive from anywhere else."
    ),
    COMMITMENT_FAMILY: (
        "This document records a COMMITMENT over a horizon rather than an amount currently due. "
        "Terms matter as much as figures: validity window, delivery schedule, payment and delivery "
        "terms, incoterms. A partially priced or entirely unpriced schedule is normal here, and a "
        "document of this kind may legitimately print no grand total at all."
    ),
    OTHER_FAMILY: (
        "The type of this document has not been established. Extract conservatively: only what is "
        "plainly printed, nothing inferred, nothing forced into a shape the document does not have."
    ),
}

_DOC_TYPE_OVERLAYS: Dict[str, str] = {
    # E4: an offer, not a payable. Priced and arithmetically checkable, but a
    # partially-priced or option-heavy quote is normal — which is why G2 mapped it
    # to COMMITMENT rather than MONEY (that mapping is provisional and flagged for
    # founder confirmation at G5; this overlay is written to be correct either way).
    "QUOTATION": (
        "This is a QUOTATION (quote / estimate / offer). It is what a supplier is OFFERING, not "
        "an amount owed and not an order that has been placed.\n"
        "- `party_name` is the party making the offer; `counterparty_name` is the party being quoted.\n"
        "- `doc_number` is the quotation number. Set `po_number` only if the quote cites a customer "
        "purchase order number.\n"
        "- Capture any stated expiry or validity period into `valid_until` ('valid for 30 days', "
        "'offer expires 31/10/2026'). If the document states none, leave it null — do not compute one.\n"
        "- Optional items, alternates and 'price on application' lines are normal. Leave their prices "
        "null; do not carry a price down from a similar row.\n"
        "- Put lead time, warranty and any conditions of the offer into `notes` or `delivery_terms`."
    ),
    # E4: sits after commitment and before shipment — used to open a letter of
    # credit, arrange advance payment and clear customs. Structurally invoice-like
    # but NOT a tax document. It is MONEY_FAMILY, so under A2 it resolves to the
    # invoice schema and this overlay is currently unreachable; it is written
    # anyway so the table is complete per `DOC_TYPES` and so a later family change
    # cannot leave a type with no instructions at all.
    "PROFORMA_INVOICE": (
        "This is a PROFORMA INVOICE. It states the exact goods, values and terms the buyer has "
        "committed to, and it is used to open a letter of credit, arrange advance payment or clear "
        "customs — but it is NOT a tax document. It creates no receivable, no input-tax credit and no "
        "payment obligation of its own.\n"
        "- Extract the totals block exactly as printed, the same way you would on an invoice.\n"
        "- Do NOT relabel it as an invoice and do not treat its total as an amount due.\n"
        "- Capture any stated validity period into `valid_until`, and advance-payment or "
        "letter-of-credit wording into `payment_terms`.\n"
        "- Shipment terms, incoterms and port of loading/discharge belong in `incoterms` / "
        "`delivery_terms`, not in `notes`, when the document prints them as their own fields."
    ),
    # E4: money + quantity, terms-heavy, longer horizon. Explicitly NOT to be
    # structurally conflated with an invoice.
    "PURCHASE_ORDER": (
        "This is a PURCHASE ORDER — a buyer's commitment to buy. Nothing on it is an amount currently "
        "owed; it records what was ordered, on what terms, for delivery at some future point.\n"
        "- `party_name` is the buyer issuing the order; `counterparty_name` is the supplier it is "
        "placed with.\n"
        "- `doc_number` is the PO number; `po_number` is normally the same value on this type.\n"
        "- Where a row prints an ordered quantity as its own column, fill `quantity_ordered` as well "
        "as `quantity`, and capture the unit of measure into `uom` exactly as printed.\n"
        "- Delivery schedule, required-by dates, incoterms and payment terms are the substance of this "
        "document: put them in `delivery_terms`, `incoterms` and `payment_terms`. Penalty, "
        "liquidated-damages and cancellation wording goes into `notes`.\n"
        "- Call-off, blanket and schedule lines with no price are normal. Leave those prices and "
        "amounts null and do not compute a total the document does not print."
    ),
    # E8 gives this overlay's substance verbatim: validity window / renewal /
    # termination into `notes`; a framework agreement may have no grand total.
    "CONTRACT": (
        "This is a CONTRACT or AGREEMENT (including a master service agreement, framework agreement "
        "or rate contract).\n"
        "- Capture the validity window, renewal terms and termination terms into `notes`, quoting the "
        "document rather than summarising it. Put the end of the validity window into `valid_until` as "
        "well when a definite date is printed.\n"
        "- A framework agreement or rate card may have NO grand total at all. That is normal: leave "
        "`grand_total` null rather than totalling a rate table or a schedule of prices.\n"
        "- A rate-card row is a line item: put the described service in `description` and the rate in "
        "`unit_price`, and leave `amount` null when no line total is printed.\n"
        "- Payment terms, delivery/service-level obligations and incoterms go into their own fields "
        "where the contract states them plainly."
    ),
    # E8 gives this overlay's substance verbatim: prices frequently absent by
    # design, do not infer them, do not compute a total. This is the founder's
    # original symptom — a delivery challan graded against the money rubric.
    "DELIVERY_NOTE": (
        "This is a DELIVERY NOTE (delivery challan / packing slip / Lieferschein / DDT / bon de "
        "livraison / pakbon / albaran). It records what was physically despatched.\n"
        "- PRICES ARE FREQUENTLY ABSENT BY DESIGN on this document — commonly so that the recipient's "
        "warehouse staff cannot see pricing. DO NOT infer them, leave `unit_price` and `amount` null, "
        "and DO NOT compute a subtotal, tax or grand total. A delivery note with no money on it "
        "anywhere is a complete, correct extraction.\n"
        "- `party_name` is the despatching supplier; `counterparty_name` is the consignee it is "
        "delivered to.\n"
        "- Quantities are the substance: fill `quantity` for every row, `quantity_delivered` where the "
        "row prints a despatched column of its own, `uom` exactly as printed, and `batch_or_serial` "
        "where batch, lot or serial numbers are listed.\n"
        "- The order this delivery is against goes in `po_number`; vehicle, transporter and e-way-bill "
        "references go in `reference_numbers` or `notes`."
    ),
    # E4: low-frequency and internal-origin — generated by the buyer's own
    # receiving process, and usually only shared externally to substantiate a
    # short-delivery or damage claim. Low GRN volume is not a classifier defect.
    "GRN": (
        "This is a GOODS RECEIPT NOTE — the buyer's own record of what was actually received against "
        "an order, usually raised to confirm receipt or to substantiate a short-delivery or damage "
        "claim.\n"
        "- Quantities are the whole point, and this type routinely prints several per row. Fill "
        "`quantity_received` from the received/accepted column, `quantity_ordered` from the ordered "
        "column and `quantity_delivered` from the despatched column, each only where that column is "
        "actually printed. `quantity` takes whichever figure the document leads with.\n"
        "- Prices are usually absent. Leave them null; never infer a price and never compute a total.\n"
        "- Rejected, damaged or short quantities and the inspection remarks against them go into "
        "`notes`, quoted as printed — they are the reason this document exists.\n"
        "- `doc_number` is the GRN number; `po_number` is the order it receipts; the delivery note or "
        "invoice it cites goes into `reference_numbers`."
    ),
    # MONEY_FAMILY under G2's map, so unreachable via the generic path under A2 —
    # same reasoning as PROFORMA_INVOICE above.
    "CREDIT_NOTE": (
        "This is a CREDIT NOTE (credit memo) — a reduction of an amount previously invoiced, raised "
        "for returned goods, a rebate, an overcharge or a price correction.\n"
        "- Transcribe every figure exactly as printed, INCLUDING its sign. If an amount is printed as "
        "negative (a leading minus or in parentheses), extract it as a negative number. Do not strip "
        "the sign or flip it to make the document read like an invoice.\n"
        "- The original invoice number(s) this note adjusts go into `reference_numbers`.\n"
        "- The stated reason for the credit goes into `notes`, quoted as printed."
    ),
    "DEBIT_NOTE": (
        "This is a DEBIT NOTE (debit memo) — an additional charge raised against the counterparty, for "
        "an undercharge, freight, a rejected-goods claim or a similar adjustment.\n"
        "- Transcribe every figure exactly as printed, including its sign, and do not convert it to "
        "the shape of an invoice.\n"
        "- The original invoice or delivery reference this note is raised against goes into "
        "`reference_numbers`.\n"
        "- The stated reason for the debit goes into `notes`, quoted as printed."
    ),
    # --- A5/R7: the four new document types ---------------------------------
    "ORDER_CONFIRMATION": (
        "This is an ORDER CONFIRMATION (order acknowledgement, Auftragsbestaetigung, sales order) - "
        "the SELLER's acknowledgement of a buyer's purchase order, stating what they have accepted "
        "and on what terms.\n"
        "- Direction matters and is the only thing separating this from a PURCHASE ORDER: the party "
        "ISSUING it is the seller, so `party_name` is the supplier and `counterparty_name` is the "
        "buyer. Do not swap them because the layout resembles a PO.\n"
        "- The buyer's own PO number is a REFERENCE, not this document's number: put it in "
        "`po_number`, and put this acknowledgement's own number in `doc_number`.\n"
        "- Confirmed prices frequently DIFFER from the ordered prices, and the confirmed figure is "
        "the one that matters. Transcribe exactly what is printed; never reconcile the two.\n"
        "- Promised delivery dates and lead times go into `delivery_terms`; validity into "
        "`valid_until`."
    ),
    "RECEIPT": (
        "This is a RECEIPT - a payment receipt, fiscal receipt, cash memo, or a SIMPLIFIED invoice "
        "(Kleinbetragsrechnung, scontrino, fattura semplificata, ticket, faktura uproszczona).\n"
        "- These documents are legally allowed to omit things a full invoice must carry: the BUYER'S "
        "NAME, the UNIT PRICE, and sometimes the VAT AMOUNT (a rate alone is permitted). Their "
        "absence is normal and is NOT a defect - leave those fields null and do not infer them.\n"
        "- Do not compute a VAT amount from a rate, and do not derive a unit price by dividing a line "
        "total by a quantity. A figure the document does not print must not appear.\n"
        "- The total actually paid goes into `grand_total`; the payment method and any reference "
        "(card, UPI, UTR) go into `notes`."
    ),
    "REMITTANCE_ADVICE": (
        "This is a REMITTANCE ADVICE (payment advice, Zahlungsavis) - it tells a supplier WHICH "
        "invoices a payment covers. It is NOT itself a payable and creates no obligation.\n"
        "- Its substance is a LIST OF REFERENCES to other documents. Every invoice number it settles "
        "goes into `reference_numbers`, exactly as printed.\n"
        "- DEDUCTIONS are the reason this document is interesting: TDS, GST-TDS, chargebacks, "
        "short-payments, early-payment discount (Skonto). Capture each deduction and its stated "
        "reason verbatim in `notes`. NEVER net them into a single figure and never recompute a "
        "total.\n"
        "- `grand_total` is the amount actually remitted, if printed. If the document shows only "
        "per-invoice amounts, leave it null rather than summing them yourself."
    ),
    "STATEMENT_OF_ACCOUNT": (
        "This is a STATEMENT OF ACCOUNT (vendor statement, ledger, Kontoauszug, Khata) - a periodic "
        "list of open or settled items between two parties. It must NEVER be treated as a payable.\n"
        "- Its substance is a LIST OF REFERENCES: every invoice, credit note and payment it lists "
        "goes into `reference_numbers` exactly as printed.\n"
        "- A statement carries a RUNNING BALANCE, not a subtotal/tax/total triple. Put the closing "
        "balance in `grand_total` only if it is printed as such, and leave `subtotal` and "
        "`tax_amount` null - they usually do not exist on this document.\n"
        "- The statement period goes into `notes` along with any aging buckets, quoted as printed.\n"
        "- Do not add the listed amounts up. The document's own arithmetic is what it states."
    ),
    # E5: transport and custody documents — bill of lading, air waybill, CMR
    # consignment note, India's e-way bill — are deliberately out of v1 and land
    # here. This overlay is what stops them being force-fitted into an invoice.
    "OTHER": (
        "The type of this document could not be established, or it is outside the supported "
        "vocabulary. Transport and custody documents — bills of lading, air waybills, CMR consignment "
        "notes, e-way bills — deliberately land here.\n"
        "- Extract ONLY what is plainly printed. Leave every field the document does not state null.\n"
        "- Do not force it into an invoice shape: no inferred totals, no invented party roles, no "
        "currency guessed from a country.\n"
        "- Put the printed document title and any identifying numbers you cannot place into "
        "`reference_numbers` and `notes`, so a human reviewing the record can see what it actually was."
    ),
}


def resolve_doc_type_overlay(doc_type: Optional[str]) -> str:
    """The prompt text appended to the base template for `doc_type` (E8).

    Family stance first (one lookup on `DOC_TYPE_FAMILY`), then the type's own
    overlay. Anything unrecognised — `None`, an empty string, a value outside
    `DOC_TYPES`, or `INVOICE` itself — falls back to the `OTHER` stance and
    overlay, which is the most conservative instruction set in the table: extract
    only what is printed, infer nothing.

    `INVOICE` additionally logs a WARNING. Per A2 an invoice must never reach the
    generic path at all, so arriving here means `resolve_extraction_profile`
    (G3b) has a defect, and a silent conservative prompt would hide it.
    """
    resolved = (doc_type or "").strip().upper()
    if resolved == "INVOICE":
        logger.warning(
            "resolve_doc_type_overlay called for INVOICE — an invoice must use "
            "InvoiceExtractionSchema, not GenericDocumentSchema (feature 27, A2). "
            "Falling back to the OTHER overlay."
        )
        resolved = "OTHER"
    elif resolved not in _DOC_TYPE_OVERLAYS:
        if resolved:
            logger.warning(
                "No generic extraction overlay for doc_type %r; using OTHER.", doc_type
            )
        resolved = "OTHER"

    family = DOC_TYPE_FAMILY.get(resolved, OTHER_FAMILY)
    stance = _GENERIC_FAMILY_STANCE.get(family, _GENERIC_FAMILY_STANCE[OTHER_FAMILY])
    return f"{stance}\n\n{_DOC_TYPE_OVERLAYS[resolved]}"


def _generic_base_prompt(doc_type: Optional[str]) -> str:
    """Shared opening of both generic prompt builders — the framing, the
    absent-is-not-zero directive, and the resolved overlay.

    The absent-is-not-zero paragraph is stated at prompt level as well as in the
    schema field descriptions on purpose. Hard rule 3 means it is not a control
    either way — no figure's correctness is decided by prompt text — but a model
    told it is reading an invoice will happily produce a total for a document
    that prints none, and a fabricated zero reads exactly like a real one
    downstream.
    """
    resolved = (doc_type or "").strip().upper() or "OTHER"
    return (
        f"You are reading a commercial document of type {resolved}. It is NOT necessarily an "
        "invoice, and nothing on it is necessarily an amount owed. Extract structured data "
        "aligning with the schema.\n\n"
        "PARTY ROLES: `party_name` is the party that ISSUED this document; `counterparty_name` is "
        "the party it is ADDRESSED TO. Use those roles, not the words the document happens to use.\n\n"
        "CRITICAL — ABSENT IS NOT ZERO: leave a field null whenever the document does not print it. "
        "Never write 0, 0.00 or an empty string to mean 'not stated', and never compute, derive or "
        "carry over a figure the document does not print. A null is a true fact about the document; a "
        "fabricated zero is a wrong answer that reads like a right one.\n\n"
        + GAP_46_VERBATIM_DIRECTIVE
        + resolve_doc_type_overlay(doc_type)
        + "\n\n"
    )


def build_generic_multimodal_prompt(
    ocr_text: str,
    images: List[str],
    rules: Optional[Dict[str, Any]] = None,
    doc_type: Optional[str] = None,
) -> List[HumanMessage]:
    """Multimodal generic-document prompt (E8), modelled on
    `build_reference_multimodal_prompt`.

    `doc_type` is a trailing keyword with a default so this stays call-compatible
    with `_DirectionProfile.build_multimodal_prompt`'s three-argument signature;
    G3b binds the classified type (e.g. via `functools.partial`) when it adds the
    `GENERIC` profile entry. Called with no `doc_type`, it produces the `OTHER`
    overlay — the conservative default, not an invoice-shaped one.
    """
    prompt_text = _generic_base_prompt(doc_type)
    # Feature 18: same shared normalizer as every other builder in this file, so
    # a tenant's already-committed rule strings behave identically here.
    prompt_constraints = normalize_constraints(rules)
    if prompt_constraints:
        prompt_text += "You MUST respect the following layout extraction constraints/rules:\n"
        for rule in prompt_constraints:
            prompt_text += f"- {rule}\n"
        prompt_text += "\n"

    prompt_text += f"OCR Text:\n{ocr_text}"

    content = [{"type": "text", "text": prompt_text}]
    for img_url in images:
        content.append({"type": "image_url", "image_url": {"url": img_url}})
    return [HumanMessage(content=content)]


def _build_generic_text_prompt(state: "ExtractionState", rules: Optional[Dict[str, Any]]) -> str:
    """Text-only (no page images / non-Azure) generic-document prompt. Same
    framing and the same overlay as `build_generic_multimodal_prompt`.

    Reads the document type from `state.get("doc_type")` — the key G4's
    `classify_doc_type_node` writes. Until that node exists the key is absent,
    `.get` returns `None`, and the conservative `OTHER` overlay applies; nothing
    here needs `ExtractionState` widened to work, and widening it is G4's change
    to make.
    """
    prompt = _generic_base_prompt(state.get("doc_type"))
    dynamic_qa_context = state.get("dynamic_qa_context")
    if dynamic_qa_context:
        prompt += f"DYNAMIC LAYOUT PRE-ANALYSIS FINDINGS (Gap 4 Targeted Q&A):\n{dynamic_qa_context}\n\n"
    prompt_constraints = normalize_constraints(rules)
    if prompt_constraints:
        prompt += "You MUST respect the following layout extraction constraints/rules:\n"
        for rule in prompt_constraints:
            prompt += f"- {rule}\n"
        prompt += "\n"
    prompt += state["ocr_text"]
    return prompt


# ---------------------------------------------------------------------------
# Gap 283 — one graph, two directions
# ---------------------------------------------------------------------------
# Outbound extraction used to be a second, near-duplicate 2-node LangGraph in
# `agents/outbound_extraction_agent.py` (extract -> verify), which meant the
# outbound flow silently missed `classify`, `dynamic_qa`, and the bounded
# verify->extract retry loop. Every one of those nodes is purely
# document-structure-driven — none of them read vendor/customer or direction at
# all — so there was never a reason for outbound to have its own graph.
#
# The genuinely direction-specific pieces are enumerated exhaustively here.
# Anything not in this table runs identically for both directions.
@dataclass(frozen=True)
class _DirectionProfile:
    schema: Type[BaseModel]
    max_tokens: int
    build_multimodal_prompt: Callable[[str, List[str], Optional[Dict[str, Any]]], List[HumanMessage]]
    build_text_prompt: Callable[["ExtractionState", Optional[Dict[str, Any]]], str]
    # Fields whose absence is worth flagging. Inbound deliberately has none: a
    # vendor document is unpredictable and inbound has never raised
    # `missing_required_field`. Outbound is the tenant's own invoice, so the
    # three fields the send/AR flow depends on are always expected.
    required_fields: Tuple[str, ...]
    passed_status: str
    review_status: str
    # Legacy `"audit" in file_path` short-circuit in verify_node, relied on by
    # tests/test_sse.py. Inbound-only, exactly as before — an outbound invoice
    # whose filename happens to contain "audit" must not land on an inbound-only
    # status string that outbound's own lifecycle has no meaning for.
    legacy_audit_path_shim: bool


_DIRECTION_PROFILES: Dict[str, _DirectionProfile] = {
    "INBOUND": _DirectionProfile(
        schema=InvoiceExtractionSchema,
        max_tokens=16384,
        build_multimodal_prompt=build_multimodal_prompt,
        build_text_prompt=_build_inbound_text_prompt,
        required_fields=(),
        passed_status="COMPLETED",
        review_status="AUDIT_REQUIRED",
        legacy_audit_path_shim=True,
    ),
    "OUTBOUND": _DirectionProfile(
        schema=OutboundInvoiceExtractionSchema,
        max_tokens=8192,
        build_multimodal_prompt=build_outbound_multimodal_prompt,
        build_text_prompt=_build_outbound_text_prompt,
        required_fields=("customer_name", "invoice_number", "grand_total"),
        passed_status="VERIFIED",
        review_status="NEEDS_REVIEW",
        legacy_audit_path_shim=False,
    ),
    # Feature 26 (Gap 366). A third direction, purely additive: INBOUND and
    # OUTBOUND above are byte-for-byte unchanged, and `resolve_direction_profile`
    # still defaults to INBOUND for anything it does not recognise, so no
    # existing caller can reach this entry by accident -- only an explicit
    # flow_direction="REFERENCE" does.
    #
    # `required_fields=()` for the same reason INBOUND has none: a counterparty's
    # purchase order is as unpredictable as a vendor's bill, and a missing field
    # here is a matching problem to be surfaced to the user, not an extraction
    # failure. The status vocabulary is its own -- "EXTRACTED"/"EXTRACT_FAILED"
    # rather than COMPLETED/AUDIT_REQUIRED -- because a reference document has no
    # audit lifecycle at all; it is never approved, sent or paid.
    # `legacy_audit_path_shim=False`: the `"audit" in file_path` short-circuit is
    # an inbound-only legacy behaviour and a reference doc whose filename happens
    # to contain "audit" must not inherit an inbound status string.
    "REFERENCE": _DirectionProfile(
        schema=ReferenceDocExtractionSchema,
        max_tokens=8192,
        build_multimodal_prompt=build_reference_multimodal_prompt,
        build_text_prompt=_build_reference_text_prompt,
        required_fields=(),
        passed_status="EXTRACTED",
        review_status="EXTRACT_FAILED",
        legacy_audit_path_shim=False,
    ),
    # Feature 27 (G3b) — the fourth entry, per §4 and amendment A2.
    #
    # NOT a flow direction. It is a profile keyed into the same map because
    # `_DirectionProfile` is exactly the shape a profile needs and a second
    # near-identical dataclass/map would be the duplication Gap 283 removed. It is
    # reachable only through `resolve_extraction_profile()` below, which returns it
    # solely for (flag ON ∧ INBOUND ∧ doc_type known ∧ family != MONEY). No caller
    # passes flow_direction="GENERIC" — the eight `run_extraction_agent` call sites
    # pass "OUTBOUND", "REFERENCE", the invoice row's own direction, or nothing —
    # so `resolve_direction_profile("GENERIC")` is unreachable in practice today.
    #
    # NOTE FOR G6 (the E9 fail-loud): the set of valid *directions* is
    # INBOUND/OUTBOUND/REFERENCE, which is no longer the same thing as
    # `_DIRECTION_PROFILES.keys()`. Validate against the three named directions,
    # not against this map's keys, or "GENERIC" silently becomes an accepted
    # flow_direction value.
    #
    # **Done (G6, Gap 384).** `_VALID_FLOW_DIRECTIONS` below is that tuple, and
    # `resolve_direction_profile("GENERIC")` now raises `UnknownFlowDirectionError`
    # rather than returning this entry. A test asserts the tuple is exactly this
    # map's keys minus `GENERIC`, so adding a fifth profile here cannot quietly
    # make it an accepted direction either.
    #
    # Field choices, each with a reason rather than a copy:
    #   * `schema=GenericDocumentSchema` — E8's union spine (G3). Never applied to
    #     an invoice; that is A2's whole point and is enforced by the family test
    #     in `resolve_extraction_profile`.
    #   * `max_tokens=8192` — REFERENCE's figure, not INBOUND's 16384. The generic
    #     spine is wider than `ReferenceDocExtractionSchema` but far narrower than
    #     `InvoiceExtractionSchema` (no compliance_metadata / payment_instructions /
    #     addresses / deductions / tax_ids blocks). Stated as a starting value, not
    #     a measured one: if §7 task F's real fixtures show a long multi-page
    #     delivery note truncating, this is the number to raise.
    #   * prompt builders — G3's pair. `build_generic_multimodal_prompt` has
    #     `doc_type` as a trailing keyword with a default, so it satisfies
    #     `build_multimodal_prompt`'s three-argument signature; called through
    #     `extract_node` as it stands today it would produce the conservative OTHER
    #     overlay. Binding the classified type at that call site is G4's change,
    #     together with widening `ExtractionState` — `_build_generic_text_prompt`
    #     already reads `state.get("doc_type")` and needs nothing more.
    #   * `required_fields=()` — A2 states it explicitly, for the same reason
    #     INBOUND and REFERENCE have none: a counterparty's delivery note is as
    #     unpredictable as a vendor's bill, and this feature exists to STOP
    #     absent-by-design fields being reported as failures.
    #   * `EXTRACTED`/`EXTRACT_FAILED` — deliberately the same pair REFERENCE uses
    #     (above), not a new vocabulary, and for the reason stated there: a
    #     delivery note has no audit lifecycle; it is never approved, sent or paid.
    #     E10 gives the `documents` table the same two values, so the profile and
    #     the table agree by construction rather than by a mapping table.
    #   * `legacy_audit_path_shim=False` — the `"audit" in file_path` short-circuit
    #     is an inbound-invoice legacy behaviour; a delivery challan whose filename
    #     happens to contain "audit" must not inherit an invoice status string.
    "GENERIC": _DirectionProfile(
        schema=GenericDocumentSchema,
        max_tokens=8192,
        build_multimodal_prompt=build_generic_multimodal_prompt,
        build_text_prompt=_build_generic_text_prompt,
        required_fields=(),
        passed_status="EXTRACTED",
        review_status="EXTRACT_FAILED",
        legacy_audit_path_shim=False,
    ),
}


class UnknownFlowDirectionError(ValueError):
    """Feature 27 (G6 / decision E9): a `flow_direction` that is neither absent
    nor one of the three real directions.

    A `ValueError` subclass rather than a bare `ValueError` so a caller that
    genuinely wants to tolerate one can catch precisely this and nothing else,
    and so it is greppable. It is raised by `resolve_direction_profile()` below
    **in both flag states** -- see that function's docstring for why that is
    deliberate.
    """


# The set of real flow directions, deliberately NOT `_DIRECTION_PROFILES.keys()`
# (G3b's note at the `GENERIC` entry above asks for exactly this). `GENERIC` is a
# *profile* that happens to live in the direction map for shape reuse; keying
# validation off the map's keys would make `flow_direction="GENERIC"` an accepted
# external input, which is the one thing that note warns against. Two names for
# one idea is normally drift, but here the divergence is the point, so the two are
# tied together by a test that asserts this tuple is exactly the map's keys minus
# `GENERIC`.
_VALID_FLOW_DIRECTIONS: tuple[str, ...] = ("INBOUND", "OUTBOUND", "REFERENCE")


def resolve_direction_profile(flow_direction: Optional[str]) -> _DirectionProfile:
    """Direction lookup with an INBOUND default, so a state dict written before
    Gap 283 (or a caller that never passes the flag) behaves exactly as it did.

    Feature 27 (G6 / decision E9) -- **fails loud, in both flag states.** This is
    the single deliberate exception to E3's flag-OFF-is-byte-identical rule, and
    E9 argues it directly: gating a fail-loud correction behind the flag leaves
    the footgun armed in exactly the configuration running in production today,
    and this feature is what makes a fourth direction value likely.

    Two behaviours, and the split matters:

      * `None`, absent, `""` or whitespace -> **still INBOUND, unchanged.** Not a
        convenience: `agents/trainer_agent.py`, `routers/trainer.py` and
        `benchmarks/extraction/harness.py` pass nothing at all, and every
        pre-Gap-283 persisted state dict has no key here. Preserving it is
        required, not optional.
      * Any other unrecognised value -> `UnknownFlowDirectionError`. Before this,
        `"REFERNCE"` silently became INBOUND -- meaning
        `InvoiceExtractionSchema`, the inbound prompt, `COMPLETED`/`AUDIT_REQUIRED`
        and the `"audit" in file_path` legacy shim -- and produced a *plausible
        wrong answer* rather than an error. That is the highest-severity class of
        defect this module can have.

    A padded value (`"  inbound "`) raises too, and that is on purpose rather than
    an oversight. The normalisation here is the same `.upper()` expression
    `resolve_extraction_profile` and `resolve_verification_rubric` use, so the
    three cannot drift about which documents Feature 27 applies to; silently
    stripping here would make `"  outbound "` resolve to OUTBOUND in one of the
    three and stay ineligible in the other two. A caller with whitespace in its
    direction has a defect, and E9's whole argument is that such a caller should
    hear about it rather than get INBOUND.

    Blast radius, enumerated so the risk is a known quantity rather than a
    hope: the call sites pass `"OUTBOUND"` (the outbound agent), `"REFERENCE"`
    (`routers/chat_attachments.py`), an explicit direction read off the invoice
    row (handlers/audit), or nothing at all (trainer x2, benchmark harness).
    None can reach the raise. It is reachable only from new or typo'd code --
    which is the point.
    """
    # `or ""` rather than `or "INBOUND"` so the empty/whitespace case is decided
    # once, explicitly, instead of falling out of a lookup miss.
    normalized = (flow_direction or "").upper()
    if not normalized.strip():
        return _DIRECTION_PROFILES["INBOUND"]

    if normalized not in _VALID_FLOW_DIRECTIONS:
        raise UnknownFlowDirectionError(
            f"Unknown flow_direction {flow_direction!r}. "
            f"Valid directions are {', '.join(_VALID_FLOW_DIRECTIONS)}; "
            "None/empty defaults to INBOUND."
        )

    return _DIRECTION_PROFILES[normalized]


def resolve_extraction_profile(flow_direction: Optional[str], doc_type: Optional[str]) -> _DirectionProfile:
    """Feature 27 (G3b) — the one place document type is allowed to change the
    extraction profile. Implements amendment A2's rule verbatim.

    Returns `resolve_direction_profile(flow_direction)` — i.e. exactly today's
    behaviour — **unless all four of these hold**, in which case it returns the
    `GENERIC` profile:

      1. `settings.ENABLE_GENERIC_EXTRACTION` is True (E1/E2: software-level, read
         once through `get_settings()`, never per-tenant),
      2. `flow_direction` resolves to INBOUND,
      3. `doc_type is not None`,
      4. `DOC_TYPE_FAMILY[doc_type] != MONEY_FAMILY`.

    Every fall-through is **fail-closed to today's behaviour**, matching E1's
    reasoning for the flag's default: the failure mode of guessing wrong here is
    an invoice extracted on the generic spine, which silently drops
    `compliance_metadata` (the India IRN/QR block), `tax_ids`,
    `payment_instructions`, `addresses`, `deductions`, `round_off` and per-line
    `hsn_sac_code` while still returning a plausible `vendor_name` and
    `grand_total`. Nothing raises; the wrong answer just looks right. That is the
    class of defect A2 exists to prevent, and it is why the four conditions are
    conjunctive and why the family test uses the imported `MONEY_FAMILY` constant
    rather than the bare literal `"INVOICE"` (which is a doc_type *value*, so
    `!= "INVOICE"` reads true for `PROFORMA_INVOICE`, `CREDIT_NOTE` and
    `DEBIT_NOTE` — three money documents routed to the wrong schema).

    Wiring status: **called from nowhere.** `extract_node`, `verify_node` and
    `run_extraction_agent` still call `resolve_direction_profile` directly; moving
    them onto this function is G4, along with the `doc_type` state key it reads.

    `doc_type` has no default on purpose. A caller that forgot it gets a
    `TypeError` at the call site instead of silently taking the invoice path,
    which is the whole decision this function exists to make explicit.
    """
    profile = resolve_direction_profile(flow_direction)

    # 1. The flag. Read at call time, not at import, so a test (or a restart-free
    #    config change) sees the current value -- the same shape
    #    `services/online_quality_judge.py` uses for ENABLE_PRODUCTION_QUALITY_JUDGE.
    if not get_settings().ENABLE_GENERIC_EXTRACTION:
        return profile

    # 2. INBOUND only (A2). OUTBOUND is the tenant's own AR invoice, whose
    #    downstream consumers (`routers/outbound_audit.py`,
    #    `queue_worker/outbound_handlers.py`) are written against
    #    `OutboundInvoiceExtractionSchema`; REFERENCE is Feature 26's
    #    chat-attachment path with its own schema and status vocabulary. Both are
    #    unchanged in v1 -- doc_type is still classified and recorded for them, it
    #    simply never changes their schema or rubric.
    #
    #    The normalisation below is deliberately the *same expression*
    #    `resolve_direction_profile` uses, so the two cannot drift. A consequence
    #    worth stating: `None`/`""` resolve to INBOUND and so are eligible (E9
    #    preserves that default), while a typo'd or padded value ("REFERNCE",
    #    "  inbound ") is NOT eligible.
    #
    #    **Updated by G6 (Gap 384):** a typo'd or padded value no longer reaches
    #    this line at all -- `resolve_direction_profile(flow_direction)` on the
    #    first line of this function now raises `UnknownFlowDirectionError` for
    #    it, in both flag states (E9). So this branch is left to decide exactly
    #    one thing: a *valid* direction that is not INBOUND.
    direction = (flow_direction or "INBOUND").upper()
    if direction == "REFERENCE":
        # Gap 435 (2026-09-04): a statement of account / remittance advice
        # attached in chat needs `referenced_documents[]` -- a field only the
        # generic spine has -- for B8's list reconcile. On the REFERENCE schema
        # the list is never extracted, so the reconcile branch always answered
        # "I could not read a list of invoice references" (F26 benchmark
        # S18-S20). Only the ADVISORY family crosses over; a PO or quotation
        # keeps the REFERENCE schema and everything Part 1 was written against.
        if doc_type is not None and DOC_TYPE_FAMILY.get(str(doc_type).strip().upper()) == ADVISORY_FAMILY:
            return _DIRECTION_PROFILES["GENERIC"]
        return profile
    if direction != "INBOUND":
        return profile

    # 3. No classification -> the existing profile, exactly as today. This is the
    #    flag-ON-but-classifier-skipped case: `run_extraction_agent`'s caller
    #    supplied `doc_type=None` (G4's override, used by
    #    `routers/chat_attachments.py` where the user already told us what they
    #    attached), or the node has not run.
    if doc_type is None:
        return profile

    # 4. The family. `DOC_TYPE_FAMILY` is keyed on the canonical uppercase values
    #    of `DOC_TYPES`; the classifier only ever emits those (its
    #    `DocTypeClassification.doc_type` is a `Literal` over them), but a
    #    caller-supplied override is free-text, so normalise before looking up.
    family = DOC_TYPE_FAMILY.get(str(doc_type).strip().upper())

    if family is None:
        # An out-of-vocabulary doc_type. Not in the spec's four conditions, and
        # NOT treated as "not the money family" -- an unrecognised label is an
        # unknown document, and the safe answer for an unknown document is the one
        # this pipeline already gives it. Logged rather than silent: reaching here
        # means a caller invented a type outside the closed enum, which is a
        # defect in that caller. (Distinct from E9's raise, which is G6 and is
        # about flow_direction: raising here would fail an entire extraction over
        # a label, whereas falling back merely gets today's behaviour.)
        logger.warning(
            "resolve_extraction_profile: doc_type %r is not in DOC_TYPES; "
            "falling back to the %s direction profile (fail-closed).",
            doc_type,
            (flow_direction or "INBOUND").upper(),
        )
        return profile

    if family == MONEY_FAMILY:
        # INVOICE, PROFORMA_INVOICE, CREDIT_NOTE, DEBIT_NOTE. A2: the money family
        # keeps `InvoiceExtractionSchema` and the existing machinery byte-for-byte
        # in BOTH flag states. This is the branch T-R-6 exists to prove.
        return profile

    return _DIRECTION_PROFILES["GENERIC"]


# ---------------------------------------------------------------------------
# Feature 27 (G5) — the verification rubric. E6, keyed on the FAMILY, not the type.
# ---------------------------------------------------------------------------
# This is the piece the feature exists for. `verify_node` has always run the money
# rubric — line-item math, totals math — unconditionally, so a delivery note (which
# prints quantities and no prices, by design, precisely so warehouse staff cannot
# see pricing) came back covered in discrepancies on a document that was perfectly
# correct. It was not broken; it was being graded against the wrong rubric (§1).
#
# E6's shape, deliberately: ONE declaration (the family table) and ONE lookup, never
# an `if doc_type == "DELIVERY_NOTE"` chain. Adding an eleventh document type later
# is one entry in `DOC_TYPE_FAMILY` plus, at most, one rubric — not a new branch in
# verification code.
#
# Hard rule 3 note: every check these booleans gate stays deterministic Python. The
# classifier picks the rubric; it does not adjudicate any figure, and no LLM decides
# whether a document reconciles.
@dataclass(frozen=True)
class _VerificationRubric:
    """What it means for a document of this family to verify.

    E6's field list, plus the two A1 added for the Document-Intelligence-derived
    checks. Every field is declarative: the rubric says what should be checked, and
    `verify_node` is the single place that acts on it.
    """

    # The two arithmetic checks in `utils/verification_tools.py`. Those functions
    # are NOT modified by this feature — E6 is explicit that they are correct and
    # that what was wrong was calling them unconditionally.
    run_line_item_math: bool
    run_totals_math: bool

    # Declarative today. There is no currency check anywhere in `verify_node` (or
    # in `utils/verification_tools.py`) to gate — E6 lists the field, so it exists
    # and carries the family's intent, but adding a *new* check under it would
    # change the alert set an INVOICE produces and break T-R-3, which is the one
    # test proving this task regresses nothing. Whoever adds a currency check wires
    # it to this flag; until then it is a statement of intent, not a control.
    require_currency: bool

    # E4's quantity-family rule, verbatim: "no total-arithmetic check attempted
    # unless prices are actually present, in which case the money checks run
    # additionally, not instead". This is what makes that "additionally" real —
    # `verify_node` escalates the two math checks back on when the extracted
    # document actually carries money figures (`_prices_present`).
    price_fields_optional: bool

    # E4's `OTHER` rule: alerts are recorded but never set a review status, because
    # we do not know what the document is and have no rubric we can defend.
    advisory_only: bool

    # E6's "the status pair to emit". Recorded here and cross-checked against the
    # resolved profile by a test, but NOT what `verify_node` emits — see
    # `resolve_verification_rubric`'s docstring for why the profile stays in charge
    # of the status vocabulary.
    passed_status: str
    review_status: str

    # --- A1's two, for G7, declared now so G7 has something to gate on ----------
    # Both are UNGATED as of this task, deliberately and honestly: G5 is the
    # arithmetic rubric, G7 is the DI trust boundary. The fields exist here now so
    # that G7 is a wiring change at two call sites rather than a redesign.
    #
    # `run_field_confidence` gates the Gap 3 / Task 2.32 Critic step
    # (`verify_field_confidence`, below). True for the money family only: that check
    # maps DI's *invoice* field names onto invoice schema names, so on a delivery
    # note it emits `low_confidence_field` alerts about fields the document does not
    # have — and that alert type is non-retryable and forces a review status, which
    # is the founder's original symptom arriving by a second, independent route.
    run_field_confidence: bool
    # `run_di_tax_backfill` gates the Gap 68 `tax_details_sum` backfill in
    # `extract_node`. True for the money family only: a document that prints no tax
    # must not acquire one from DI's misparse of a document it force-fit.
    run_di_tax_backfill: bool


# E4's three families, one rubric each. The MONEY entry is today's behaviour written
# down — every boolean True, nothing optional, nothing advisory — so "the money
# family is unchanged" is a readable property of this table rather than a claim.
_MONEY_RUBRIC = _VerificationRubric(
    run_line_item_math=True,
    run_totals_math=True,
    require_currency=True,
    price_fields_optional=False,
    advisory_only=False,
    passed_status="COMPLETED",
    review_status="AUDIT_REQUIRED",
    run_field_confidence=True,
    run_di_tax_backfill=True,
)

# QUANTITY (`DELIVERY_NOTE`, `GRN`). The founder's actual bug. Price fields are
# optional and frequently absent BY DESIGN, so absent price is not a discrepancy and
# no total-arithmetic check is attempted — unless prices are actually present, in
# which case `verify_node` escalates and the money checks run additionally.
_QUANTITY_RUBRIC = _VerificationRubric(
    run_line_item_math=False,
    run_totals_math=False,
    require_currency=False,
    price_fields_optional=True,
    advisory_only=False,
    passed_status="EXTRACTED",
    review_status="EXTRACT_FAILED",
    run_field_confidence=False,
    run_di_tax_backfill=False,
)

# COMMITMENT (`PURCHASE_ORDER`, `CONTRACT`, and provisionally `QUOTATION` — see the
# Gap 369 build note's second open decision, and `DOC_TYPE_FAMILY`, which is the
# real mapping this file reads rather than re-deriving). E4: "Arithmetic checks run
# where totals are printed, but an unpriced or partially-priced schedule line is
# normal, and a CONTRACT frequently has no grand total at all (rate cards, framework
# agreements). Missing-total is not a failure for this family."
#
# So both math checks stay ON — "where printed" — and missing-total is handled by
# the checks' own existing behaviour rather than by a new branch: `verify_totals_math`
# returns None when `grand_total` or `subtotal` is None, and `verify_line_items_math`
# returns None when `subtotal` is None. `required_fields=()` on the GENERIC profile
# means no `missing_required_field` is raised for the absent total either. That is
# the whole of "missing-total is not a failure", and it is why this family needs no
# code beyond the table.
_COMMITMENT_RUBRIC = _VerificationRubric(
    run_line_item_math=True,
    run_totals_math=True,
    require_currency=False,
    price_fields_optional=True,
    advisory_only=False,
    passed_status="EXTRACTED",
    review_status="EXTRACT_FAILED",
    run_field_confidence=False,
    run_di_tax_backfill=False,
)

# OTHER. E4: "`OTHER` runs the money rubric in advisory mode only: alerts are
# recorded but never set a review status, because we do not know what the document
# is and have no rubric we can defend." Hence the money booleans with
# `advisory_only=True` — with the two exceptions A1 states later and more
# specifically: `run_field_confidence` / `run_di_tax_backfill` are False for EVERY
# non-money family, and a bill of lading is exactly the document DI would force-fit
# an `InvoiceTotal` onto.
_OTHER_RUBRIC = _VerificationRubric(
    run_line_item_math=True,
    run_totals_math=True,
    require_currency=True,
    price_fields_optional=False,
    advisory_only=True,
    passed_status="EXTRACTED",
    review_status="EXTRACT_FAILED",
    run_field_confidence=False,
    run_di_tax_backfill=False,
)

# A7/R9: the fourth family.
#
# NOT `OTHER` with a friendlier name. `OTHER` means "we do not know what this is";
# `ADVISORY` means "we know exactly what it is, and it is not a payable". They
# share `advisory_only=True` and nothing else -- ADVISORY has a schema
# (`referenced_documents[]`, `deductions[]`) and a comparison mode
# (`list_reconcile`, Feature 26 B8); OTHER has neither.
#
# The arithmetic flags are the substantive difference from `_OTHER_RUBRIC`, which
# leaves both math checks ON. A statement carries a RUNNING BALANCE, not a
# subtotal/tax/total triple, and a remittance lists per-invoice amounts against a
# payment -- so `verify_line_items_math` and `verify_totals_math` have nothing to
# check and would report the absence of a structure that was never supposed to be
# there. Research §5 trap 6: money-only, no lines.
_ADVISORY_RUBRIC = _VerificationRubric(
    run_line_item_math=False,
    run_totals_math=False,
    # Declarative, as G5 left it -- there is still no currency check in
    # `verify_node` to gate. Recorded because an amount without a currency is
    # meaningless for reconciliation, which is this family's entire purpose.
    require_currency=True,
    price_fields_optional=True,
    # Never sets a review status and never enters spend. These rows go to
    # `documents` (E10), so `/dashboard/*` cannot see them by construction --
    # this flag is the second layer, not the only one.
    advisory_only=True,
    passed_status="EXTRACTED",
    review_status="EXTRACT_FAILED",
    # §8 trap 1: DI's invoice fields force-fit onto a statement are wrong by
    # construction, and a `low_confidence_field` alert naming `InvoiceTotal` on a
    # vendor statement is the founder's original symptom in a new costume.
    run_field_confidence=False,
    run_di_tax_backfill=False,
)

_RUBRIC_BY_FAMILY: Dict[str, _VerificationRubric] = {
    MONEY_FAMILY: _MONEY_RUBRIC,
    QUANTITY_FAMILY: _QUANTITY_RUBRIC,
    COMMITMENT_FAMILY: _COMMITMENT_RUBRIC,
    OTHER_FAMILY: _OTHER_RUBRIC,
    ADVISORY_FAMILY: _ADVISORY_RUBRIC,
}

# E6's "one entry per enum value, derived from the family table". Derived by
# comprehension rather than written out, so the map cannot fall out of step with
# `DOC_TYPES`: a new document type is complete here the moment it has a family, and
# a family with no rubric raises a KeyError at import rather than serving a silently
# wrong rubric at runtime.
_RUBRIC_BY_DOC_TYPE: Dict[str, _VerificationRubric] = {
    doc_type: _RUBRIC_BY_FAMILY[DOC_TYPE_FAMILY[doc_type]] for doc_type in DOC_TYPES
}


def _prices_present(data: Optional[Dict[str, Any]]) -> bool:
    """Does this extracted document actually carry money figures?

    E4's quantity-family escape hatch: a delivery note that *does* print prices
    should have the money checks run against it "additionally, not instead". This is
    the test for "actually present".

    Every comparison is `is not None`, never truthiness. A genuinely printed `0.00`
    is a price the document stated and must count as present — `not 0.0` and
    `not None` are both True, and treating them alike is exactly the Gap 283 bug
    `verify_node`'s own required-field check was corrected for.
    """
    if not isinstance(data, dict):
        return False

    for key in ("subtotal", "grand_total", "tax_amount", "discount_amount"):
        if data.get(key) is not None:
            return True

    for item in data.get("items") or []:
        if isinstance(item, dict) and (
            item.get("unit_price") is not None or item.get("amount") is not None
        ):
            return True

    return False


def resolve_verification_rubric(
    flow_direction: Optional[str], doc_type: Optional[str]
) -> Optional[_VerificationRubric]:
    """The one place a document type is allowed to change what gets verified.

    Returns `None` — meaning **"do not consult the rubric; run today's checks
    exactly as they have always run"** — unless all three of these hold:

      1. `settings.ENABLE_GENERIC_EXTRACTION` is True (E1/E2: software-level, read
         once through `get_settings()`, never per-tenant),
      2. `flow_direction` resolves to INBOUND,
      3. `doc_type` is a known value in `DOC_TYPES`.

    Conditions 1–3 are deliberately the first three of `resolve_extraction_profile`'s
    four, in the same order and with the same normalisation, so the schema a document
    is extracted on and the rubric it is verified against cannot disagree about which
    documents Feature 27 applies to.

    **There is no fourth condition here, and that asymmetry is the point.** The money
    family is excluded from the *schema* change (A2 — an invoice keeps
    `InvoiceExtractionSchema`) but is NOT excluded from the rubric: `_MONEY_RUBRIC`
    is today's behaviour written down, every boolean True, so consulting it for an
    INVOICE resolves to the same checks in the same order with the same arguments.
    T-R-3 asserts that equality directly rather than trusting this paragraph.

    **Why OUTBOUND and REFERENCE never reach the map.** A2, verbatim: `doc_type` "is
    still classified and recorded for both — it simply never changes their schema or
    rubric". An OUTBOUND document is the tenant's own AR invoice on
    `OutboundInvoiceExtractionSchema`, and a classified `DELIVERY_NOTE` there must
    not quietly switch off the arithmetic its own downstream consumers
    (`routers/outbound_audit.py`, `queue_worker/outbound_handlers.py`) are written
    against.

    **Why the rubric's status pair is not what `verify_node` emits.** E6 predates
    A2, which put the status vocabulary on `_DirectionProfile` (`GENERIC` →
    `EXTRACTED`/`EXTRACT_FAILED`, REFERENCE's pair) and G4 wired `verify_node` to
    emit the *resolved profile's* pair. Two sources for one decision is how they
    drift, and the rubric is the weaker of the two here: it is keyed on `doc_type`
    alone, so letting it win would give an OUTBOUND invoice the inbound
    `COMPLETED`/`AUDIT_REQUIRED` pair instead of its own `VERIFIED`/`NEEDS_REVIEW`.
    The pair is carried on the rubric because E6 asks for it and because it makes the
    family's intent readable in one table, and a test asserts it agrees with the
    profile on every path where the rubric is actually consulted.

    An out-of-vocabulary `doc_type` returns `None` — fail-closed to today's checks,
    the same call the unknown-type branch of `resolve_extraction_profile` makes, and
    for the same reason: an unrecognised label is an unknown document, and the safe
    answer for an unknown document is the one this pipeline already gives it.
    """
    # 1. The flag, read at call time (not at import) so a test or a restart-free
    #    config change sees the current value.
    if not get_settings().ENABLE_GENERIC_EXTRACTION:
        return None

    # 2. INBOUND only. Same normalising expression `resolve_direction_profile` and
    #    `resolve_extraction_profile` use, so the three cannot drift: None/"" resolve
    #    to INBOUND and are eligible; a padded or typo'd value is not.
    #
    #    Unlike the other two, this function does NOT raise on a typo'd direction
    #    (G6/Gap 384) -- it never calls `resolve_direction_profile`, and adding a
    #    raise here would fail an extraction from the *verification* step, after
    #    the model spend, for an input the profile resolution already rejected
    #    earlier and more cheaply. Returning None here is fail-closed to today's
    #    checks, which is this function's contract for every unrecognised input.
    if (flow_direction or "INBOUND").upper() != "INBOUND":
        return None

    # 3. A known type. `doc_type is None` is the flag-ON-but-unclassified case (the
    #    node has not run, or `run_extraction_agent`'s caller supplied an override) —
    #    today's checks, exactly as `resolve_extraction_profile` returns today's
    #    profile for it.
    if doc_type is None:
        return None

    rubric = _RUBRIC_BY_DOC_TYPE.get(str(doc_type).strip().upper())
    if rubric is None:
        logger.warning(
            "resolve_verification_rubric: doc_type %r is not in DOC_TYPES; running "
            "the existing checks unchanged (fail-closed).",
            doc_type,
        )
    return rubric


# ---------------------------------------------------------------------------
# Gap 41 — App-level retry loop with exponential backoff for network errors
# ---------------------------------------------------------------------------
# Transient cloud network glitches (connection timeouts, rate limits, 502/503s)
# can cause raw API exceptions during LLM calls. Instead of letting a 1-second
# network blip fail the invoice permanently, this helper catches connection-class
# errors and retries automatically with exponential backoff (1s, 2s, 4s wait).
# ---------------------------------------------------------------------------
def invoke_with_retry(llm_callable, payload, max_retries: int = 3):
    """
    Gap 41: Invokes an LLM with exponential backoff retries for transient
    connection and network-level failures before raising an exception.
    """
    for attempt in range(max_retries):
        try:
            return llm_callable(payload)
        except Exception as e:
            err_msg = str(e).lower()
            is_transient = any(kw in err_msg for kw in [
                "connection", "timeout", "rate", "429", "503", "502", "504", "reset", "overloaded"
            ])
            if is_transient and attempt < max_retries - 1:
                wait_s = 2 ** attempt
                logger.warning(
                    "Transient connection error during LLM call (attempt %d/%d): %s. Retrying in %ds...",
                    attempt + 1, max_retries, e, wait_s
                )
                time.sleep(wait_s)
            else:
                raise e


# 4. LangGraph Nodes
def extract_node(state: ExtractionState) -> Dict[str, Any]:
    """Node state for executing LLM structured output extraction."""
    settings = get_settings()
    # Feature 27 (G4, the narrow slice of G6 this task carries): the profile is
    # resolved from the direction AND the classified document type, not from the
    # direction alone. `resolve_extraction_profile` (G3b) returns exactly
    # `resolve_direction_profile(flow_direction)` unless all four of A2's
    # conditions hold (flag ON, INBOUND, doc_type known, non-money family), so
    # with the flag off -- where `doc_type` is `None` anyway, because the node
    # that writes it is not in the compiled graph at all -- this line is today's
    # behaviour, unchanged (E3).
    doc_type = state.get("doc_type")
    profile = resolve_extraction_profile(state.get("flow_direction"), doc_type)
    direction = (state.get("flow_direction") or "INBOUND").upper()
    # Remove temperature parameter as some models don't support it
    llm = get_llm(max_tokens=profile.max_tokens)
    rules = state.get("rules")
    retry_count = state.get("retry_count") or 0
    feedback = state.get("feedback") or []

    extracted_data = {}
    alerts = []

    try:
        # Wrap LLM with structured output schema
        structured_llm = llm.with_structured_output(profile.schema)

        # Feature 23 Phase 1: one `llm_agent_call` event per extraction round-trip.
        # `invoke_with_retry`'s backoff attempts are inside the block deliberately --
        # a retried call costs real tokens twice and takes real wall-clock time
        # twice, so the event reports the summed cost of the whole attempt.
        # Inbound and outbound are reported as separate agents because they are
        # separate rows in the Feature 23 registry, even though Gap 283 made them
        # one graph.
        with tracked_llm_call(
            f"extraction.{direction}.extract",
            llm=llm,
            tenant_id=str(state.get("tenant_id") or ""),
            flow_direction=direction,
            complexity=state.get("complexity"),
            retry_count=retry_count,
        ):
            dynamic_qa_context = state.get("dynamic_qa_context")
            if settings.LLM_PROVIDER.lower() == "azure" and state["images"]:
                # Feature 27 (G4): the GENERIC profile's multimodal builder takes
                # the classified type as a trailing keyword (G3's hand-off
                # contract) -- unbound, it would serve the conservative OTHER
                # overlay to a delivery note whose type we already know. Bound
                # here rather than by widening `_DirectionProfile`, because
                # `doc_type` is the ONLY profile whose prompt depends on it and
                # the text builder already reads the same key off state. Every
                # other profile is called exactly as before.
                build_prompt = profile.build_multimodal_prompt
                if profile is _DIRECTION_PROFILES["GENERIC"]:
                    build_prompt = partial(build_generic_multimodal_prompt, doc_type=doc_type)
                messages = build_prompt(state["ocr_text"], state["images"], rules)
                if dynamic_qa_context:
                    messages[0].content.append({"type": "text", "text": f"\n\nDYNAMIC LAYOUT PRE-ANALYSIS FINDINGS:\n{dynamic_qa_context}"})
                if feedback:
                    feedback_msg = (
                        "\n\nCRITICAL FEEDBACK FROM PREVIOUS EXTRACTION ATTEMPT:\n"
                        + "\n".join(f"- {fb}" for fb in feedback)
                        + "\nPlease correct these math/verification issues in the next output."
                    )
                    messages[0].content.append({"type": "text", "text": feedback_msg})
                result = invoke_with_retry(structured_llm.invoke, messages)
            else:
                prompt = profile.build_text_prompt(state, rules)

                if feedback:
                    prompt += (
                        "\n\nCRITICAL FEEDBACK FROM PREVIOUS EXTRACTION ATTEMPT:\n"
                        + "\n".join(f"- {fb}" for fb in feedback)
                        + "\nPlease correct these math/verification issues in the next output."
                    )

                result = invoke_with_retry(structured_llm.invoke, prompt)

        if hasattr(result, "dict"):
            extracted_data = result.dict()
        elif isinstance(result, dict):
            extracted_data = result
        else:
            # Gap 70: include the active ExtractionTemplate constraints in the alert
            # so auditors can see which rules were active when extraction failed.
            # Feature 18: `for_prompt=False` — an auditor wants every active rule,
            # including the verification-tuning ones that never reach the prompt.
            active_constraints = normalize_constraints(rules, for_prompt=False)
            alerts.append({
                "type": "extraction_failed",
                "message": "Structured extraction failed to parse model response.",
                "active_constraints": active_constraints,
            })
            
    except Exception as e:
        logger.warning("Structured extraction failed: %s.", e)
        active_constraints = normalize_constraints(rules, for_prompt=False)
        alerts.append({
            "type": "extraction_failed",
            "message": f"Structured extraction failed due to error: {str(e)}.",
            "active_constraints": active_constraints,
        })

    # Doc Intelligence tax-anchor backfill: Doc Intelligence isolates each printed
    # tax line (e.g. separate CGST/SGST rows) deterministically, independent of the
    # LLM. If the LLM extracted the individual tax components into `taxes[]` but
    # never summed them into the scalar `tax_amount` field, fall back to Doc
    # Intelligence's own sum rather than leaving tax_amount null. This ONLY fires
    # when the LLM's tax_amount is missing — it never overrides a value the LLM did
    # transcribe, and verify_totals_math / verify_tax_amount_in_source_text (Gap 46)
    # still run against the final value unchanged either way, so no existing
    # faithfulness/arithmetic check is bypassed.
    #
    # Feature 27 (G7 / §2A A1): whether Doc Intelligence's `TaxDetails` read can be
    # trusted at all is a property of the document family, not of the extraction.
    # `_run_ocr` calls `prebuilt-invoice` for every document in both flag states
    # (A1 — there is no model selector), and that model does not decline to analyse
    # a delivery note: it force-fits its invoice fields onto one at low confidence.
    # A delivery note prints no tax, so a `tax_details_sum` derived from one is a
    # misparse, and backfilling it writes a tax figure onto a document that states
    # none — the plausible-wrong-answer class E9 exists to prevent. `None` from the
    # resolver means "flag off / not INBOUND / unclassified / unknown type", i.e.
    # exactly today's unconditional behaviour; the money family resolves to
    # `run_di_tax_backfill=True`, which is the same call with the same arguments.
    rubric = resolve_verification_rubric(state.get("flow_direction"), doc_type)
    run_di_tax_backfill = rubric is None or rubric.run_di_tax_backfill

    if run_di_tax_backfill and extracted_data.get("tax_amount") is None:
        ocr_result = state.get("ocr_result")
        di_tax_sum = ocr_result.get("tax_details_sum") if isinstance(ocr_result, dict) else None
        if di_tax_sum is not None:
            logger.info(
                "Backfilling null tax_amount from Doc Intelligence TaxDetails sum (%.2f) for %s",
                di_tax_sum, state.get("file_path")
            )
            extracted_data["tax_amount"] = di_tax_sum

    return {"extracted_data": extracted_data, "alerts": alerts, "retry_count": retry_count + 1}


def verify_node(state: ExtractionState) -> Dict[str, Any]:
    """Node state for executing validation math check tools."""
    # Feature 27 (G4): same resolution as `extract_node`, and it has to be the
    # same one -- the status vocabulary a document is verified against must be the
    # vocabulary of the schema it was extracted on, or a delivery note extracted
    # on `GenericDocumentSchema` would come back COMPLETED/AUDIT_REQUIRED.
    profile = resolve_extraction_profile(state.get("flow_direction"), state.get("doc_type"))

    # Feature 27 (G5): what to verify, as opposed to what to extract. `None` means
    # "do not consult the rubric" -- flag off, a non-INBOUND direction, an
    # unclassified document, or an out-of-vocabulary type -- and every check below
    # then runs exactly as it has always run. This is E6's single lookup; there is
    # deliberately no `if doc_type == ...` anywhere in this function.
    #
    # The same resolved rubric now also gates the Gap 3 Critic step (check 8
    # below) on `run_field_confidence` (G7 / §2A A1) -- the *Document
    # Intelligence*-derived check, as opposed to the two arithmetic ones. Its
    # sibling, the Gap 68 `tax_details_sum` backfill, is gated on the same rubric
    # in `extract_node`, resolved there from the same two state keys.
    rubric = resolve_verification_rubric(state.get("flow_direction"), state.get("doc_type"))

    # Check for legacy test trigger path compat (inbound only -- see
    # _DirectionProfile.legacy_audit_path_shim)
    if profile.legacy_audit_path_shim and "audit" in state["file_path"].lower():
        return {"alerts": ["Math mismatch"], "status": "AUDIT_REQUIRED"}

    data = state["extracted_data"] or {}
    alerts = list(state.get("alerts") or [])

    # Feature 18: this node never read `state["rules"]` at all, despite `rules`
    # being part of ExtractionState and read by extract_node -- so a tenant could
    # commit a "this alert is unnecessary" correction and nothing downstream
    # would ever consult it. The three tolerance-overridable checks and the
    # confidence threshold now resolve from the tenant's committed rules, with
    # None/absent meaning the untouched defaults.
    rules = state.get("rules")
    tolerances = tolerance_overrides(rules)
    threshold_override = confidence_threshold_override(rules)

    # If extraction failed already, don't perform math check, just return for review
    if any(isinstance(a, dict) and a.get("type") == "extraction_failed" for a in alerts):
        return {"alerts": apply_alert_overrides(alerts, rules), "status": profile.review_status}

    # 0. Missing required field check. Empty for INBOUND (a vendor document is
    # unpredictable, so inbound has never raised this); the tenant's own
    # outbound invoice should always carry customer/number/total.
    #
    # Post-Gap-283 correction: this was `if not data.get(field)`, a bare
    # truthiness test, which treats a legitimately-extracted 0/0.0 as "missing".
    # A fully-credited outbound invoice (credit note, 100%-discounted order)
    # with a genuine printed `grand_total` of 0.00 would raise a spurious
    # `missing_required_field` and land on NEEDS_REVIEW for a field that was in
    # fact transcribed faithfully. "Missing" means absent or None; an empty /
    # whitespace-only string still counts as missing (that's the original intent
    # for the two string fields), but a numeric zero does not.
    for field in profile.required_fields:
        value = data.get(field)
        is_missing = (
            field not in data
            or value is None
            or (isinstance(value, str) and not value.strip())
        )
        if is_missing:
            alerts.append({
                "type": "missing_required_field",
                "field": field,
                "message": f"Required field '{field}' could not be extracted.",
            })

    # Feature 27 (G5): which of the two arithmetic checks apply to THIS document.
    # With no rubric (flag off / not INBOUND / unclassified) both run, which is the
    # unconditional behaviour this function has always had.
    #
    # With a rubric, the family decides -- plus E4's quantity-family escape hatch:
    # a delivery note that *does* print prices gets the money checks "additionally,
    # not instead", so the flags escalate back on when the extracted document
    # actually carries money figures. For the money family this resolves to
    # True/True and the calls below are byte-for-byte today's (T-R-3).
    if rubric is None:
        run_line_item_math = True
        run_totals_math = True
    else:
        prices_present = rubric.price_fields_optional and _prices_present(data)
        run_line_item_math = rubric.run_line_item_math or prices_present
        run_totals_math = rubric.run_totals_math or prices_present

    # 1. Verify line items math check
    items = data.get("items", [])
    subtotal = data.get("subtotal")
    if run_line_item_math:
        line_item_alert = verify_line_items_math(
            items, subtotal, invoice_tax_amount=data.get("tax_amount"), tolerances=tolerances
        )
        if line_item_alert:
            alerts.append(line_item_alert)

    # 2. Verify totals math check
    tax_amount = data.get("tax_amount")
    grand_total = data.get("grand_total")
    if run_totals_math:
        totals_alert = verify_totals_math(
            subtotal,
            tax_amount,
            grand_total,
            discount_amount=data.get("discount_amount"),
            discount_percent=data.get("discount_percent"),
            round_off=data.get("round_off"),
            tolerances=tolerances,
        )
        if totals_alert:
            alerts.append(totals_alert)

    # 3. Gap 33: grand_total faithfulness check, independent of arithmetic —
    # catches the case where the LLM silently "corrected" an inconsistent
    # printed total instead of transcribing it (which verify_totals_math
    # alone cannot detect, since a self-corrected total always reconciles).
    source_text_alert = verify_grand_total_in_source_text(grand_total, state.get("ocr_text"))
    if source_text_alert:
        alerts.append(source_text_alert)

    # 4. Gap 36 (Gap 33's sibling): same faithfulness check, per line item.
    line_item_source_text_alert = verify_line_item_amounts_in_source_text(items, state.get("ocr_text"))
    if line_item_source_text_alert:
        alerts.append(line_item_source_text_alert)

    # 5. Gap 43: subtotal faithfulness check, independent of arithmetic.
    subtotal_source_text_alert = verify_subtotal_in_source_text(subtotal, state.get("ocr_text"))
    if subtotal_source_text_alert:
        alerts.append(subtotal_source_text_alert)

    # 6. Gap 44: unit price faithfulness check, independent of arithmetic.
    unit_price_source_text_alert = verify_unit_prices_in_source_text(items, state.get("ocr_text"))
    if unit_price_source_text_alert:
        alerts.append(unit_price_source_text_alert)

    # 7. Gap 46: tax_amount faithfulness check, independent of arithmetic.
    # Catches silent LLM tax auto-correction when vendor printed tax calculation is flawed.
    tax_source_text_alert = verify_tax_amount_in_source_text(tax_amount, state.get("ocr_text"), tax_components=data.get("taxes"))
    if tax_source_text_alert:
        alerts.append(tax_source_text_alert)

    # 8. Gap 3 (Critic Node): confidence-driven audit routing.

    # Azure Document Intelligence attaches a confidence score (0.0–1.0) to
    # every field it reads from the document. If a critical field (like
    # vendor_name or grand_total) has a low confidence score, the document
    # may be blurred/smudged — flag those specific fields for human review
    # instead of blindly accepting the AI's uncertain guess.
    #
    # Feature 27 (G7 / §2A A1): that reasoning holds only for a document Doc
    # Intelligence was asked the right question about. This check maps DI's
    # *invoice* field names onto invoice schema names
    # (`InvoiceTotal`->`grand_total`, `VendorName`->`vendor_name`,
    # `utils/verification_tools.py`), and `prebuilt-invoice` force-fits those
    # fields onto a delivery note at low confidence rather than declining to
    # read it. Run unconditionally, the Critic therefore emits
    # `low_confidence_field` alerts naming fields the document does not have —
    # and that type is in NON_RETRYABLE_ALERT_TYPES and any alert sets the review
    # status, so a perfectly correct delivery note lands in review carrying an
    # alert no retry can clear. That is the founder's original symptom by its
    # second, independent route: gating only the arithmetic (G5) left it in place.
    #
    # `rubric is None` -- flag off, not INBOUND, unclassified, unknown type --
    # runs this exactly as it has always run, and the money family resolves to
    # `run_field_confidence=True`, i.e. the same call with the same argument
    # (T-R-3 asserts that on `call_args_list`, not just on the alert set). The
    # check function in `utils/verification_tools.py` is untouched: it is
    # correct, and what was wrong was calling it for every document.
    if rubric is None or rubric.run_field_confidence:
        ocr_result = state.get("ocr_result")
        field_confidence = ocr_result.get("field_confidence", {}) if isinstance(ocr_result, dict) else {}
        # Feature 18: threshold (not tolerance) -- a different parameter on a
        # different function, which is why it has its own correction form.
        if threshold_override is not None:
            confidence_alerts = verify_field_confidence(field_confidence, threshold=threshold_override)
        else:
            confidence_alerts = verify_field_confidence(field_confidence)
        if confidence_alerts:
            alerts.extend(confidence_alerts)

    # Feature 18: severity/message relabelling runs after every check, never
    # inside them -- verification_tools.py's checks are deliberately left
    # unrestructured.
    alerts = apply_alert_overrides(alerts, rules)

    # Feature 27 (G5): `OTHER`'s advisory mode (E4). We do not know what the
    # document is, so we have no rubric we can defend -- the alerts are still
    # recorded on the row, because they are real observations and a reviewer may
    # want them, but they do not route the document into review.
    #
    # The status vocabulary itself stays the resolved *profile's*, not the rubric's:
    # the rubric is keyed on doc_type alone and letting it win would give an
    # OUTBOUND invoice the inbound status pair (see `resolve_verification_rubric`).
    #
    # The `extraction_failed` early return above is deliberately NOT advisory. That
    # branch is the pipeline reporting its own failure, not this rubric judging the
    # document: suppressing it would mark a document with no extracted data at all
    # as passed.
    if rubric is not None and rubric.advisory_only:
        status = profile.passed_status
    else:
        status = profile.review_status if alerts else profile.passed_status

    feedback = []
    if alerts:
        for alert in alerts:
            if isinstance(alert, dict) and "message" in alert:
                feedback.append(alert["message"])
            elif isinstance(alert, str):
                feedback.append(alert)
                
    return {"alerts": alerts, "status": status, "feedback": feedback}



# 4. LangGraph Nodes
def classify_doc_type_node(state: ExtractionState) -> Dict[str, Any]:
    """Feature 27 (G4) — E7's new first node: what IS this document?

    Runs before `classify_node`, and the two are deliberately separate. They are
    orthogonal questions asked for different reasons — an invoice and a contract
    can each be simple or complex — and merging them would couple two things that
    change independently (E7).

    **This node is in the compiled graph only when `ENABLE_GENERIC_EXTRACTION` is
    on.** The flag is read once, at graph-build time, in
    `_build_extraction_graph()`; with it off the node is not merely a no-op, it is
    absent from the executed path entirely, which is what makes E3's
    "byte-identical" claim testable on graph structure rather than on output.

    Telemetry: **none is emitted here, deliberately.** E7 asks for exactly one
    `tracked_llm_call("extraction.classify_doc_type", ...)` on the LLM-fallback
    path, and G2 already put it there — inside
    `document_type_classifier._classify_with_llm`, which is the only place that
    knows a call is actually being made. Wrapping this node in a second one would
    both double-count the fallback and emit an event for the deterministic path,
    which E7 requires to "cost nothing and show as nothing", turning the
    `extraction.classify_doc_type` event count into noise instead of a direct
    count of how often the title band was not enough. Which path ran is read off
    the classifier's own `doc_type_method` (`deterministic` | `llm` | `fallback`)
    rather than re-derived here.

    Failure policy: a classifier failure degrades to "unclassified", never to a
    failed extraction. `classify_doc_type` documents itself as never raising, so
    reaching the except means something structural (an import, a config read) —
    and the safe answer for a document we cannot type is the one this pipeline
    already gives it, since `doc_type=None` sends `resolve_extraction_profile`
    straight back to today's direction profile. Same shape as `dynamic_qa_node`'s
    except, and for the same reason: a pre-analysis step must not be able to take
    down the extraction it precedes.
    """
    try:
        result = classify_doc_type(
            state.get("ocr_text") or "",
            state.get("ocr_result"),
            # Telemetry attribution only, exactly as `ExtractionState["tenant_id"]`
            # is carried -- no classification decision reads it. The flag is
            # software-level, never per-tenant (E2).
            tenant_id=str(state.get("tenant_id") or ""),
        )
    except Exception as e:  # pragma: no cover - classify_doc_type does not raise
        logger.warning(
            "Document-type classification failed for %s: %s. Continuing unclassified, "
            "which resolves to today's direction profile.",
            state.get("file_path"),
            e,
        )
        return {
            "doc_type": None,
            "doc_type_evidence": None,
            "doc_type_confidence": None,
            "doc_attributes": None,
        }

    logger.info(
        "Document type %s for %s via %s (confidence %.2f, evidence %r%s)",
        result.get("doc_type"),
        state.get("file_path"),
        result.get("doc_type_method"),
        result.get("doc_type_confidence") or 0.0,
        result.get("doc_type_evidence"),
        # Only present when it fell back, and it is the whole reason the fallback
        # is reviewable rather than merely wrong (E7).
        f", reason: {result['doc_type_reason']}" if result.get("doc_type_reason") else "",
    )

    # Feature 27 A6 / task R8: the classification attributes, derived from the
    # same OCR text, in the same node.
    #
    # Here rather than in a node of their own because they answer the same
    # question the classifier does -- what IS this document -- and because they
    # are worthless without `doc_type`: `derive_invoice_subtype()` is scoped by
    # it, and A8's Gutschrift rule consumes `direction` to resolve a type the
    # title cannot. A second node would add a graph edge and a second failure
    # site for one dict.
    #
    # Pure Python, no model call (hard rule 3). These feed rubric selection and
    # Feature 26's comparison mode, both of which decide how a FIGURE is judged,
    # so a model deciding them would be deciding a financial outcome one step
    # removed. `derive_doc_attributes()` never raises, for the same reason this
    # node's own except exists: an enrichment must not fail the extraction it
    # decorates.
    doc_attributes = derive_doc_attributes(
        state.get("ocr_text") or "",
        doc_type=result.get("doc_type"),
        # Not yet plumbed: the tenant's own registered tax IDs, which is what
        # turns "two different IDs" into SUPPLIER_ISSUED vs BUYER_ISSUED. Without
        # them `derive_direction()` still answers SELF for the both-sides-equal
        # case -- the RCM self-invoice and statutory Gutschrift that A8 needs --
        # and returns None for the rest rather than guessing. Widening this is a
        # Tenant-settings change and is deliberately not smuggled in here.
        tenant_tax_ids=None,
    )
    if doc_attributes:
        logger.info(
            "Document attributes for %s: %s",
            state.get("file_path"),
            {k: v for k, v in doc_attributes.items() if not k.endswith("_evidence")},
        )

    return {
        "doc_type": result.get("doc_type"),
        "doc_type_evidence": result.get("doc_type_evidence"),
        "doc_type_confidence": result.get("doc_type_confidence"),
        "doc_attributes": doc_attributes or None,
    }


def classify_node(state: ExtractionState) -> Dict[str, Any]:
    """Node state for classifying invoice complexity."""
    from services.invoice_classifier import classify_invoice_complexity
    ocr_result = state.get("ocr_result") or state["ocr_text"]
    complexity = classify_invoice_complexity(ocr_result)
    return {"complexity": complexity}


def dynamic_qa_node(state: ExtractionState) -> Dict[str, Any]:
    """
    Gap 4: Dynamic QA Node — targeted pre-extraction Q&A for COMPLEX invoices.

    When an invoice is classified as COMPLEX (non-standard layout, multi-tax tables,
    retention/holdbacks, specialized compliance codes), this node runs a targeted
    pre-analysis pass over the OCR text. It asks document-specific questions to
    elicit non-standard structure before main extraction runs, folding the answers
    into state["dynamic_qa_context"] for extract_node to consume.
    """
    # Gap 443 (2026-09-04): this node exists to elicit non-standard INVOICE
    # structure -- multi-tax tables, retention, holdbacks -- and its questions are
    # written about an invoice. A chat-attached reference document is none of
    # those things, and the F26 benchmark measured uploads at 24-53 s with two
    # reasoning calls inside them. Skipping a node whose output the REFERENCE
    # profile has no use for removes one of those calls outright.
    if str(state.get("flow_direction") or "").upper() == "REFERENCE":
        return {"dynamic_qa_context": None}

    complexity = state.get("complexity", "STANDARD")
    if complexity != "COMPLEX":
        return {"dynamic_qa_context": None}

    logger.info("Executing Dynamic QA Node for COMPLEX invoice: %s", state.get("file_path"))
    try:
        llm = get_llm(max_tokens=2048)
        prompt = (
            "You are an expert invoice layout analyzer. Perform a targeted pre-analysis of this COMPLEX invoice.\n"
            "Analyze the document text and answer the following structural questions concisely:\n"
            "1. Tax Structure: Are there multiple tax rates/slabs (e.g. CGST/SGST, VAT 5%/20%, Reverse Charge)? List them.\n"
            "2. Deductions/Retentions: Are there advance payments, holdbacks, or retention withholdings listed?\n"
            "3. Compliance Metadata: Are there specific e-invoicing identifiers present (e.g. IRN, e-Way Bill, QR Code, Peppol ID, USt-IdNr)?\n"
            "4. References: Are there multiple Purchase Orders, Sales Orders, or Delivery Notes referenced?\n\n"
            f"Invoice OCR Text:\n{state['ocr_text']}"
        )
        # Feature 23 Phase 1: COMPLEX invoices pay for a second model round-trip
        # before extraction even starts, so it gets its own event rather than
        # being folded into the extraction one.
        with tracked_llm_call(
            f"extraction.{(state.get('flow_direction') or 'INBOUND').upper()}.dynamic_qa",
            llm=llm,
            tenant_id=str(state.get("tenant_id") or ""),
            complexity=complexity,
        ):
            response = invoke_with_retry(llm.invoke, prompt)
        qa_summary = response.content if hasattr(response, "content") else str(response)
        return {"dynamic_qa_context": qa_summary}
    except Exception as e:
        logger.warning("Dynamic QA Node pre-analysis failed: %s. Continuing with standard extraction.", e)
        return {"dynamic_qa_context": None}


# Alert types that a re-extraction pass cannot fix: extraction_failed is a permanent
# parse/LLM failure, and low_confidence_field reflects OCR confidence on the already-run
# Doc Intelligence pass, which doesn't change no matter how many times extract_node retries.
NON_RETRYABLE_ALERT_TYPES = {"extraction_failed", "low_confidence_field"}


def route_after_verification(state: ExtractionState) -> str:
    """Conditional routing logic after verify_node to loop back to extract on errors."""
    alerts = state.get("alerts") or []
    retry_count = state.get("retry_count") or 0
    max_retries = state.get("max_retries") or 2

    # Route back to extract if errors exist and retries remain
    if alerts and retry_count < max_retries:
        # Only retry if at least one alert is something extract_node could plausibly
        # fix on a second pass (math mismatch, faithfulness check, etc.) — skip retry
        # if every alert present is permanent/non-retryable.
        if any(not isinstance(a, dict) or a.get("type") not in NON_RETRYABLE_ALERT_TYPES for a in alerts):
            logger.info("Validation failed. Routing back to extract node. Retry: %d/%d", retry_count, max_retries)
            return "extract"
            
    return END


# 5. Compile LangGraph State Graph
#
# Feature 27 (G4): the assembly is a function because the entry point is
# conditional on `ENABLE_GENERIC_EXTRACTION`, and that condition is resolved
# **at build time, not inside a node**. The distinction is the whole of E3's
# guarantee: with the flag off, `classify_doc_type_node` is not a node that
# returns early -- it is not in the compiled graph at all, so there is no
# execution path through it to reason about, and the absence is assertable on
# `graph.nodes` rather than on a downstream value being `None`.
def _build_extraction_graph(*, include_doc_type_classifier: bool):
    """Assemble and compile the one extraction graph (Gap 283: there is only one).

    `include_doc_type_classifier=False` produces exactly the graph this module
    compiled before Feature 27: `classify -> dynamic_qa -> extract -> verify`
    with the conditional retry edge back to `extract`.

    `True` prepends E7's node and moves the entry point onto it, giving §2A/A1's
    sequence: `_run_ocr -> classify_doc_type -> classify -> dynamic_qa -> extract
    -> verify`. Nothing else about the graph changes -- `classify_node` keeps its
    position and its behaviour (E7), and the edge into it is the only new edge.
    """
    builder = StateGraph(ExtractionState)
    builder.add_node("classify", classify_node)
    builder.add_node("dynamic_qa", dynamic_qa_node)
    builder.add_node("extract", extract_node)
    builder.add_node("verify", verify_node)

    if include_doc_type_classifier:
        builder.add_node("classify_doc_type", classify_doc_type_node)
        builder.set_entry_point("classify_doc_type")
        builder.add_edge("classify_doc_type", "classify")
    else:
        builder.set_entry_point("classify")

    builder.add_edge("classify", "dynamic_qa")
    builder.add_edge("dynamic_qa", "extract")
    builder.add_edge("extract", "verify")
    builder.add_conditional_edges(
        "verify",
        route_after_verification,
        {
            "extract": "extract",
            END: END
        }
    )
    return builder.compile()


@lru_cache(maxsize=2)
def _compiled_extraction_graph(include_doc_type_classifier: bool):
    """One compiled graph per flag state, built once and reused.

    Compilation is not free and the graph is stateless between runs, so this
    matches the module-level `graph = builder.compile()` it replaces. Two entries
    rather than one because a process that flips the flag (a test, or a config
    reload) must get a graph whose *structure* matches the flag -- which is
    exactly what a single import-time compile could not do.
    """
    return _build_extraction_graph(include_doc_type_classifier=include_doc_type_classifier)


# Today's graph, under the name every caller and test already knows. It is the
# flag-OFF graph specifically, and `resolve_extraction_graph()` returns this same
# object whenever the flag is off -- so "the flag-off pipeline runs the graph it
# ran before Feature 27" is true by identity, not by reconstruction.
graph = _compiled_extraction_graph(False)


def resolve_extraction_graph():
    """The compiled graph for the current flag state (E7 / E3).

    Read at run time rather than at import so a deployment's flag value is not
    baked in by whichever module imported this one first; the *structure* of each
    graph is still fixed at build time, which is the property that matters.
    """
    return _compiled_extraction_graph(bool(get_settings().ENABLE_GENERIC_EXTRACTION))


# Gap 2: friendly log lines for each graph node, surfaced to the FE terminal
# feed. Retries loop back through "extract"/"verify" again, which is fine —
# seeing "Extracting..." / "Verifying..." repeat is itself useful signal.
_NODE_LOG_MESSAGES = {
    # Feature 27 (G4). Only ever emitted when the flag is on and the node is in
    # the graph; without an entry here the FE terminal would show the raw
    # "Running classify_doc_type..." fallback.
    "classify_doc_type": "Identifying document type...",
    "classify": "Classifying invoice complexity...",
    "dynamic_qa": "Running structural pre-analysis on complex invoice...",
    "extract": "Extracting structured fields via LLM...",
    "verify": "Running math and faithfulness verification checks...",
}


def run_extraction_agent(
    file_path: str,
    ocr_text: str,
    tenant_id: str,
    rules: Optional[Dict[str, Any]] = None,
    ocr_result: Optional[Any] = None,
    on_log: Optional[Callable[[str], None]] = None,
    flow_direction: str = "INBOUND",
) -> dict:
    """
    Runs the multi-modal extraction agent graph over the given invoice file.

    Gap 283: `flow_direction` selects the direction profile ("INBOUND" default,
    or "OUTBOUND" for the tenant's own invoice being sent to a customer). It
    changes the structured-output schema, the extraction prompt, the
    required-field set, and the status vocabulary — nothing else. Classification,
    dynamic QA, the verify->extract retry loop and every math/faithfulness check
    are identical for both directions.

    Feature 27 (G4): which graph runs is decided by `ENABLE_GENERIC_EXTRACTION`
    at build time — flag off is the same compiled object as before, flag on
    prepends `classify_doc_type`. §4's caller-supplied `doc_type` override (which
    would let `routers/chat_attachments.py` skip classification for a document the
    user has already named) is **not built**; it lands with G9.

    Feature 27 (G7): the returned dict gains `doc_type` — the classified type, or
    `None`. G4 deferred this to G9 on the grounds that persistence is what needs
    the type back out of the graph, and that is exactly what asks for it here:
    A1 gates `invoice.coordinates` on the document family, and
    `queue_worker/handlers.py` cannot know the family unless the graph hands the
    type back. **`None` in every flag-OFF run** (the node that writes it is not in
    the compiled graph at all), and the three existing keys are untouched, so a
    caller reading `status`/`alerts`/`extracted_data` sees no change. Callers that
    do not care must read it with `.get()`: the pre-flight token-guardrail early
    return below is reached before the graph runs and does not carry it, and the
    several tests that patch this function return three-key dicts.
    """
    profile = resolve_direction_profile(flow_direction)
    logger.info("Executing Extraction Agent (%s) for file: %s", flow_direction, file_path)

    # Convert PDF pages to visual Base64 image strings
    images = []
    if file_path.lower().endswith(".pdf"):
        images = pdf_to_base64_images(file_path)
        
    # Pre-flight token limit guardrail check
    settings = get_settings()
    model_name = settings.AZURE_OPENAI_DEPLOYMENT_NAME if settings.LLM_PROVIDER == "azure" else settings.OLLAMA_MODEL
    
    is_safe, input_tokens, limit = check_token_guardrails(
        ocr_text=ocr_text,
        images=images,
        tenant_id=tenant_id,
        model_name=model_name,
        estimated_output=4096
    )
    
    if not is_safe:
        alert = {
            "type": "token_limit_exceeded",
            "message": f"Estimated prompt length ({input_tokens} tokens) exceeds context limit ({limit} tokens) for model {model_name}.",
            "field": "file_path"
        }
        return {
            "status": profile.review_status,
            "alerts": [alert],
            "extracted_data": None
        }

    initial_state = {
        "file_path": file_path,
        "ocr_text": ocr_text,
        "images": images,
        "extracted_data": None,
        "alerts": [],
        "status": "PROCESSING" if flow_direction.upper() == "INBOUND" else "PROCESSING_OCR",
        "rules": rules,
        "complexity": "STANDARD",
        "ocr_result": ocr_result,
        "retry_count": 0,
        "max_retries": 2,
        "feedback": [],
        "dynamic_qa_context": None,
        "flow_direction": flow_direction.upper(),
        # Feature 23 Phase 1: telemetry attribution only -- see ExtractionState.
        "tenant_id": str(tenant_id or ""),
        # Feature 27 (G4): seeded unclassified. `classify_doc_type_node` overwrites
        # all three when it is in the graph; when it is not (flag off), they stay
        # `None` for the whole run and every profile resolution is today's.
        "doc_type": None,
        "doc_type_evidence": None,
        "doc_type_confidence": None,
        "doc_attributes": None,
    }

    # Feature 27 (G4): flag OFF returns the module-level `graph` object itself,
    # unchanged. `profile` above is still resolved by direction alone, and has to
    # be: `doc_type` is decided *inside* the graph, after OCR, so it does not
    # exist yet at the pre-flight token guardrail's early return.
    active_graph = resolve_extraction_graph()

    if on_log:
        # Gap 2: .stream() instead of .invoke() so each node transition can be
        # surfaced as a real-time log line, not just the 4 coarse SSE stages.
        final_state = dict(initial_state)
        for update in active_graph.stream(initial_state, stream_mode="updates"):
            for node_name, node_update in update.items():
                final_state.update(node_update)
                on_log(_NODE_LOG_MESSAGES.get(node_name, f"Running {node_name}..."))
    else:
        final_state = active_graph.invoke(initial_state)

    return {
        "status": final_state["status"],
        "alerts": final_state["alerts"],
        "extracted_data": final_state["extracted_data"],
        # Feature 27 (G7): `None` unless the classifier node ran, which is only
        # when the flag is on. `queue_worker/handlers.py` reads it to decide
        # whether Doc Intelligence's invoice-labelled `coordinates` may be
        # persisted onto the row (A1).
        "doc_type": final_state.get("doc_type"),
        # Feature 27 (G9): the other two thirds of the classifier's answer, which
        # G4 carried in state and G7 had no consumer for. Persistence is that
        # consumer: `doc_type_evidence` is a column on both `Invoice` (an
        # invoice's own sub-type) and `Document`, and is what makes a
        # misclassification *reviewable* after the fact instead of merely wrong;
        # `doc_type_confidence` is a `Document` column and is what §2A/N2's
        # uncalibrated 0.6 threshold will eventually be calibrated against —
        # there is nothing to calibrate from if the score is never written down.
        # `None` in every flag-OFF run, exactly like `doc_type` above, and every
        # existing caller reads this dict by key, so the two additions change
        # nothing for `status`/`alerts`/`extracted_data`.
        "doc_type_evidence": final_state.get("doc_type_evidence"),
        "doc_type_confidence": final_state.get("doc_type_confidence"),
        # A6/R8. `None` on every flag-OFF run: the node that writes it is absent
        # from that graph, so the key is never in state to begin with.
        "doc_attributes": final_state.get("doc_attributes"),
    }

