"""OCR Model Registry — BE Gap 526.

Maps document types to appropriate Azure Document Intelligence models.
Prevents force-fitting 'prebuilt-invoice' onto non-invoice documents such as
contracts, delivery notes, goods receipt notes, and bank statements.
"""

from typing import Final, Optional

INVOICE_OCR_MODEL: Final[str] = "prebuilt-invoice"
LAYOUT_OCR_MODEL: Final[str] = "prebuilt-layout"

# Document type to Document Intelligence model mapping
DOC_TYPE_TO_OCR_MODEL: Final[dict[str, str]] = {
    # Money family — structured invoices, notes, adjustments
    "INVOICE": INVOICE_OCR_MODEL,
    "PROFORMA_INVOICE": INVOICE_OCR_MODEL,
    "CREDIT_NOTE": INVOICE_OCR_MODEL,
    "DEBIT_NOTE": INVOICE_OCR_MODEL,
    "PURCHASE_ORDER": INVOICE_OCR_MODEL,
    # Non-invoice / layout / contract / tabular documents
    "DELIVERY_NOTE": LAYOUT_OCR_MODEL,
    "GOODS_RECEIPT_NOTE": LAYOUT_OCR_MODEL,
    "CONTRACT": LAYOUT_OCR_MODEL,
    "STATEMENT_OF_ACCOUNT": LAYOUT_OCR_MODEL,
    "BANK_STATEMENT": LAYOUT_OCR_MODEL,
    "OTHER": LAYOUT_OCR_MODEL,
}


def resolve_ocr_model_for_doc_type(doc_type: Optional[str], default_model: Optional[str] = None) -> str:
    """Resolve the appropriate Azure Document Intelligence model for a document type.

    If doc_type is None, returns default_model or 'prebuilt-invoice' for backward compatibility.
    """
    if not doc_type:
        return default_model or INVOICE_OCR_MODEL
    normalized = str(doc_type).strip().upper()
    return DOC_TYPE_TO_OCR_MODEL.get(normalized, default_model or INVOICE_OCR_MODEL)
