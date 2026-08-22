import base64
import logging
import time
from dataclasses import dataclass
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



# 3. PDF to base64 images helper
def pdf_to_base64_images(file_path: str) -> List[str]:
    """
    Converts PDF pages into base64 visual PNG strings to support table/column layout mapping.
    """
    base64_images = []
    try:
        pdf_bytes = download_pdf_from_storage(file_path)
    except Exception as e:
        logger.warning("PDF file not found for base64 conversion: %s (%s)", file_path, e)
        return base64_images

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        for page in doc:
            pix = page.get_pixmap()
            img_bytes = pix.tobytes("png")
            b64_str = base64.b64encode(img_bytes).decode("utf-8")
            base64_images.append(f"data:image/png;base64,{b64_str}")
        doc.close()
    except Exception as e:
        logger.error("Failed to convert PDF pages to base64 images: %s", e)
    return base64_images

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
    COMPLEX prompt does — `OutboundInvoiceExtractionSchema` has no such fields,
    so asking for them would invite the model to invent a place to put them.
    `taxes[]` is the exception, and does get asked for: the schema carries it
    (post-Gap-283 correction) precisely so the summed `tax_amount` on a split-tax
    invoice has verifiable components to fall back on."""
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
}


def resolve_direction_profile(flow_direction: Optional[str]) -> _DirectionProfile:
    """Direction lookup with an INBOUND default, so a state dict written before
    Gap 283 (or a caller that never passes the flag) behaves exactly as it did."""
    return _DIRECTION_PROFILES.get((flow_direction or "INBOUND").upper(), _DIRECTION_PROFILES["INBOUND"])


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
    profile = resolve_direction_profile(state.get("flow_direction"))
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
                messages = profile.build_multimodal_prompt(state["ocr_text"], state["images"], rules)
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
    if extracted_data.get("tax_amount") is None:
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
    profile = resolve_direction_profile(state.get("flow_direction"))

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

    # 1. Verify line items math check
    items = data.get("items", [])
    subtotal = data.get("subtotal")
    line_item_alert = verify_line_items_math(
        items, subtotal, invoice_tax_amount=data.get("tax_amount"), tolerances=tolerances
    )
    if line_item_alert:
        alerts.append(line_item_alert)

    # 2. Verify totals math check
    tax_amount = data.get("tax_amount")
    grand_total = data.get("grand_total")
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
builder = StateGraph(ExtractionState)
builder.add_node("classify", classify_node)
builder.add_node("dynamic_qa", dynamic_qa_node)
builder.add_node("extract", extract_node)
builder.add_node("verify", verify_node)
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
graph = builder.compile()

# Gap 2: friendly log lines for each graph node, surfaced to the FE terminal
# feed. Retries loop back through "extract"/"verify" again, which is fine —
# seeing "Extracting..." / "Verifying..." repeat is itself useful signal.
_NODE_LOG_MESSAGES = {
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
    }
    
    if on_log:
        # Gap 2: .stream() instead of .invoke() so each node transition can be
        # surfaced as a real-time log line, not just the 4 coarse SSE stages.
        final_state = dict(initial_state)
        for update in graph.stream(initial_state, stream_mode="updates"):
            for node_name, node_update in update.items():
                final_state.update(node_update)
                on_log(_NODE_LOG_MESSAGES.get(node_name, f"Running {node_name}..."))
    else:
        final_state = graph.invoke(initial_state)

    return {
        "status": final_state["status"],
        "alerts": final_state["alerts"],
        "extracted_data": final_state["extracted_data"]
    }

