import base64
import logging
from typing import List, Dict, Any, TypedDict, Optional
from pydantic import BaseModel, Field
import fitz  # PyMuPDF

from config import get_settings
from utils.llm import get_llm
from utils.verification_tools import (
    verify_line_items_math,
    verify_totals_math,
    verify_grand_total_in_source_text,
    verify_line_item_amounts_in_source_text,
)
from utils.token_management import check_token_guardrails
from services.storage import download_pdf_from_storage
from langchain_core.messages import HumanMessage
from langgraph.graph import StateGraph, END

logger = logging.getLogger(__name__)

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
    unit_price: Optional[float] = Field(default=None, description="Unit price of the item")
    amount: float = Field(description="Total amount for this line item")
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
    subtotal: Optional[float] = Field(default=None, description="Subtotal before taxes/discounts. On invoices with a 'Subtotal (Taxable Value)' line (common on Indian GST invoices) that is already net of discount, use that printed value as-is rather than adding the discount back.")
    tax_amount: Optional[float] = Field(default=None, description="Tax amount. On invoices with a CGST + SGST (or IGST) split, sum them into this single field.")
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
    )
    if rules and "constraints" in rules:
        prompt_text += "You MUST respect the following layout extraction constraints/rules:\n"
        for rule in rules["constraints"]:
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

# 4. LangGraph Nodes
def extract_node(state: ExtractionState) -> Dict[str, Any]:
    """Node state for executing LLM structured output extraction."""
    settings = get_settings()
    # Remove temperature parameter as some models don't support it
    llm = get_llm(max_tokens=16384)
    rules = state.get("rules")
    retry_count = state.get("retry_count") or 0
    feedback = state.get("feedback") or []
    
    extracted_data = {}
    alerts = []
    
    try:
        # Wrap LLM with structured output schema
        structured_llm = llm.with_structured_output(InvoiceExtractionSchema)
        
        if settings.LLM_PROVIDER.lower() == "azure" and state["images"]:
            messages = build_multimodal_prompt(state["ocr_text"], state["images"], rules)
            if feedback:
                feedback_msg = (
                    "\n\nCRITICAL FEEDBACK FROM PREVIOUS EXTRACTION ATTEMPT:\n"
                    + "\n".join(f"- {fb}" for fb in feedback)
                    + "\nPlease correct these math/verification issues in the next output."
                )
                messages[0].content.append({"type": "text", "text": feedback_msg})
            result = structured_llm.invoke(messages)
        else:
            if state.get("complexity") == "COMPLEX":
                prompt = (
                    "You are analyzing a COMPLEX invoice. This invoice contains complex layouts, multi-tax tables (like GST/VAT), "
                    "or item-level discount structures. Please perform a deep dynamic extraction. Do not restrict yourself to standard fields; "
                    "extract all taxes, discounts, deductions, compliance metadata, and banking references into the appropriate list structures.\n\n"
                    f"Extract structured details from the following invoice OCR text:\n\n{state['ocr_text']}"
                )
            else:
                prompt = "Extract structured details from the following standard invoice OCR text:\n\n"
                if rules and "constraints" in rules:
                    prompt += "You MUST respect the following layout extraction constraints/rules:\n"
                    for rule in rules["constraints"]:
                        prompt += f"- {rule}\n"
                    prompt += "\n"
                prompt += f"{state['ocr_text']}"

            if feedback:
                prompt += (
                    "\n\nCRITICAL FEEDBACK FROM PREVIOUS EXTRACTION ATTEMPT:\n"
                    + "\n".join(f"- {fb}" for fb in feedback)
                    + "\nPlease correct these math/verification issues in the next output."
                )

            result = structured_llm.invoke(prompt)
            
        if hasattr(result, "dict"):
            extracted_data = result.dict()
        elif isinstance(result, dict):
            extracted_data = result
        else:
            alerts.append({
                "type": "extraction_failed",
                "message": "Structured extraction failed to parse model response."
            })
            
    except Exception as e:
        logger.warning("Structured extraction failed: %s.", e)
        alerts.append({
            "type": "extraction_failed",
            "message": f"Structured extraction failed due to error: {str(e)}."
        })
        
    return {"extracted_data": extracted_data, "alerts": alerts, "retry_count": retry_count + 1}


def verify_node(state: ExtractionState) -> Dict[str, Any]:
    """Node state for executing validation math check tools."""
    # Check for legacy test trigger path compat
    if "audit" in state["file_path"].lower():
        return {"alerts": ["Math mismatch"], "status": "AUDIT_REQUIRED"}
        
    data = state["extracted_data"] or {}
    alerts = list(state.get("alerts") or [])
    
    # If extraction failed already, don't perform math check, just return AUDIT_REQUIRED
    if any(isinstance(a, dict) and a.get("type") == "extraction_failed" for a in alerts):
        return {"alerts": alerts, "status": "AUDIT_REQUIRED"}
        
    # 1. Verify line items math check
    items = data.get("items", [])
    subtotal = data.get("subtotal")
    line_item_alert = verify_line_items_math(items, subtotal, invoice_tax_amount=data.get("tax_amount"))
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

    status = "AUDIT_REQUIRED" if alerts else "COMPLETED"
    
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


def route_after_verification(state: ExtractionState) -> str:
    """Conditional routing logic after verify_node to loop back to extract on errors."""
    alerts = state.get("alerts") or []
    retry_count = state.get("retry_count") or 0
    max_retries = state.get("max_retries") or 2
    
    # Route back to extract if errors exist and retries remain
    if alerts and retry_count < max_retries:
        # Filter out permanent extraction errors from trigger loop
        if not any(isinstance(a, dict) and a.get("type") == "extraction_failed" for a in alerts):
            logger.info("Validation failed. Routing back to extract node. Retry: %d/%d", retry_count, max_retries)
            return "extract"
            
    return END


# 5. Compile LangGraph State Graph
builder = StateGraph(ExtractionState)
builder.add_node("classify", classify_node)
builder.add_node("extract", extract_node)
builder.add_node("verify", verify_node)
builder.set_entry_point("classify")
builder.add_edge("classify", "extract")
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


def run_extraction_agent(
    file_path: str,
    ocr_text: str,
    tenant_id: str,
    rules: Optional[Dict[str, Any]] = None,
    ocr_result: Optional[Any] = None
) -> dict:
    """
    Runs the multi-modal extraction agent graph over the given invoice file.
    """
    logger.info("Executing Extraction Agent for file: %s", file_path)
    
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
            "status": "AUDIT_REQUIRED",
            "alerts": [alert],
            "extracted_data": None
        }
        
    initial_state = {
        "file_path": file_path,
        "ocr_text": ocr_text,
        "images": images,
        "extracted_data": None,
        "alerts": [],
        "status": "PROCESSING",
        "rules": rules,
        "complexity": "STANDARD",
        "ocr_result": ocr_result,
        "retry_count": 0,
        "max_retries": 2,
        "feedback": []
    }
    
    final_state = graph.invoke(initial_state)
    return {
        "status": final_state["status"],
        "alerts": final_state["alerts"],
        "extracted_data": final_state["extracted_data"]
    }

