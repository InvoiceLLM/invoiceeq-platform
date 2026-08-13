import logging
from typing import List, Dict, Any, TypedDict, Optional
from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage
from langgraph.graph import StateGraph, END

from config import get_settings
from utils.llm import get_llm
from utils.verification_tools import (
    verify_grand_total_in_source_text,
    verify_line_item_amounts_in_source_text,
    verify_tax_amount_in_source_text,
    verify_field_confidence,
    verify_line_items_math,
    verify_totals_math,
    verify_subtotal_in_source_text,
)
from utils.token_management import check_token_guardrails
from agents.extraction_agent import pdf_to_base64_images, invoke_with_retry, GAP_46_VERBATIM_DIRECTIVE

logger = logging.getLogger(__name__)

# Feature 2.1 (Outbound Invoice Ingestion): a parallel pipeline, not a shared
# one -- reusing InvoiceExtractionSchema would mean adding a customer_name
# field to shipped, tested code. Per the design decision in
# feature_2.1_vendor_flow_ingestion.md, this is a wholly separate schema,
# prompt, and 2-node graph, reusing only pure, already-reusable pieces
# (verification_tools.py's checks, extraction_agent.py's PDF/retry helpers)
# by import, never by edit.


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
    tax_amount: Optional[float] = Field(default=None, description="Tax amount. Transcribe printed figure verbatim.")
    currency: Optional[str] = Field(default=None, description="ISO 4217 currency code (e.g. INR, EUR, USD)")
    items: List[OutboundInvoiceLineItem] = Field(default=[], description="List of line items in the invoice")


class OutboundExtractionState(TypedDict):
    file_path: str
    ocr_text: str
    images: List[str]
    extracted_data: Optional[Dict[str, Any]]
    alerts: List[Dict[str, Any]]
    status: str
    rules: Optional[Dict[str, Any]]
    ocr_result: Optional[Any]


# Fields whose absence is worth flagging -- a tenant's own invoice should
# always have these, unlike an unpredictable vendor document.
_REQUIRED_FIELDS = ("customer_name", "invoice_number", "grand_total")


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
    if rules and "constraints" in rules:
        prompt_text += "You MUST respect the following layout extraction constraints/rules:\n"
        for rule in rules["constraints"]:
            prompt_text += f"- {rule}\n"
        prompt_text += "\n"

    prompt_text += f"OCR Text:\n{ocr_text}"

    content = [{"type": "text", "text": prompt_text}]
    for img_url in images:
        content.append({"type": "image_url", "image_url": {"url": img_url}})
    return [HumanMessage(content=content)]


def extract_node(state: OutboundExtractionState) -> Dict[str, Any]:
    settings = get_settings()
    llm = get_llm(max_tokens=8192)
    rules = state.get("rules")

    extracted_data = {}
    alerts = []

    try:
        structured_llm = llm.with_structured_output(OutboundInvoiceExtractionSchema)

        if settings.LLM_PROVIDER.lower() == "azure" and state["images"]:
            messages = build_outbound_multimodal_prompt(state["ocr_text"], state["images"], rules)
            result = invoke_with_retry(structured_llm.invoke, messages)
        else:
            prompt = (
                "This is the tenant's own outbound invoice, being sent to a customer. "
                "Extract structured details from the following OCR text:\n\n"
                + GAP_46_VERBATIM_DIRECTIVE
            )
            if rules and "constraints" in rules:
                prompt += "You MUST respect the following layout extraction constraints/rules:\n"
                for rule in rules["constraints"]:
                    prompt += f"- {rule}\n"
                prompt += "\n"
            prompt += state["ocr_text"]
            result = invoke_with_retry(structured_llm.invoke, prompt)

        if hasattr(result, "dict"):
            extracted_data = result.dict()
        elif isinstance(result, dict):
            extracted_data = result
        else:
            alerts.append({"type": "extraction_failed", "message": "Structured extraction failed to parse model response."})

    except Exception as e:
        logger.warning("Outbound structured extraction failed: %s.", e)
        alerts.append({"type": "extraction_failed", "message": f"Structured extraction failed due to error: {str(e)}."})

    return {"extracted_data": extracted_data, "alerts": alerts}


def verify_node(state: OutboundExtractionState) -> Dict[str, Any]:
    data = state["extracted_data"] or {}
    alerts = list(state.get("alerts") or [])

    if any(isinstance(a, dict) and a.get("type") == "extraction_failed" for a in alerts):
        return {"alerts": alerts, "status": "NEEDS_REVIEW"}

    # Missing required field check -- a tenant's own invoice should always
    # have these, unlike an unpredictable vendor document.
    for field in _REQUIRED_FIELDS:
        if not data.get(field):
            alerts.append({"type": "missing_required_field", "field": field, "message": f"Required field '{field}' could not be extracted."})

    items = data.get("items", [])
    grand_total = data.get("grand_total")
    tax_amount = data.get("tax_amount")

    subtotal = data.get("subtotal")

    # Math consistency and source text checks
    subtotal_source_alert = verify_subtotal_in_source_text(subtotal, state.get("ocr_text"))
    if subtotal_source_alert:
        alerts.append(subtotal_source_alert)

    line_items_math_alert = verify_line_items_math(items, subtotal, tax_amount)
    if line_items_math_alert:
        alerts.append(line_items_math_alert)

    totals_math_alert = verify_totals_math(subtotal, tax_amount, grand_total)
    if totals_math_alert:
        alerts.append(totals_math_alert)

    source_text_alert = verify_grand_total_in_source_text(grand_total, state.get("ocr_text"))
    if source_text_alert:
        alerts.append(source_text_alert)

    line_item_source_text_alert = verify_line_item_amounts_in_source_text(items, state.get("ocr_text"))
    if line_item_source_text_alert:
        alerts.append(line_item_source_text_alert)

    tax_source_text_alert = verify_tax_amount_in_source_text(tax_amount, state.get("ocr_text"))
    if tax_source_text_alert:
        alerts.append(tax_source_text_alert)

    ocr_result = state.get("ocr_result")
    field_confidence = ocr_result.get("field_confidence", {}) if isinstance(ocr_result, dict) else {}
    confidence_alerts = verify_field_confidence(field_confidence)
    if confidence_alerts:
        alerts.extend(confidence_alerts)

    status = "NEEDS_REVIEW" if alerts else "VERIFIED"
    return {"alerts": alerts, "status": status}


builder = StateGraph(OutboundExtractionState)
builder.add_node("extract", extract_node)
builder.add_node("verify", verify_node)
builder.set_entry_point("extract")
builder.add_edge("extract", "verify")
builder.add_edge("verify", END)
graph = builder.compile()


def run_outbound_extraction_agent(
    file_path: str,
    ocr_text: str,
    tenant_id: str,
    rules: Optional[Dict[str, Any]] = None,
    ocr_result: Optional[Any] = None,
) -> dict:
    """Runs the outbound extraction agent graph over the given invoice file."""
    logger.info("Executing Outbound Extraction Agent for file: %s", file_path)

    images = []
    if file_path.lower().endswith(".pdf"):
        images = pdf_to_base64_images(file_path)

    settings = get_settings()
    model_name = settings.AZURE_OPENAI_DEPLOYMENT_NAME if settings.LLM_PROVIDER == "azure" else settings.OLLAMA_MODEL

    is_safe, input_tokens, limit = check_token_guardrails(
        ocr_text=ocr_text, images=images, tenant_id=tenant_id, model_name=model_name, estimated_output=4096,
    )
    if not is_safe:
        return {
            "status": "NEEDS_REVIEW",
            "alerts": [{
                "type": "token_limit_exceeded",
                "message": f"Estimated prompt length ({input_tokens} tokens) exceeds context limit ({limit} tokens) for model {model_name}.",
                "field": "file_path",
            }],
            "extracted_data": None,
        }

    initial_state = {
        "file_path": file_path,
        "ocr_text": ocr_text,
        "images": images,
        "extracted_data": None,
        "alerts": [],
        "status": "PROCESSING_OCR",
        "rules": rules,
        "ocr_result": ocr_result,
    }

    final_state = graph.invoke(initial_state)

    return {
        "status": final_state["status"],
        "alerts": final_state["alerts"],
        "extracted_data": final_state["extracted_data"],
    }
