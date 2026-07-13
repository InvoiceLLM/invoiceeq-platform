import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

def classify_invoice_complexity(ocr_result: Dict[str, Any] | str) -> str:
    """
    Scores and classifies an invoice's complexity as 'STANDARD' or 'COMPLEX'.
    """
    complex_keywords = [
        "gst", "vat", "discount", "deduction", "hsn", "sac", 
        "cgst", "sgst", "igst", "tds", "withholding", "reverse charge"
    ]
    
    if isinstance(ocr_result, str):
        text = ocr_result.lower()
        for kw in complex_keywords:
            if kw in text:
                logger.info("Classified as COMPLEX based on text keyword: '%s'", kw)
                return "COMPLEX"
        return "STANDARD"

    # If Azure prebuilt-invoice dict format
    fields = ocr_result.get("field_confidence", {})
    complex_fields = {"Taxes", "Discounts", "CustomerTaxId", "VendorTaxId", "Items"}
    for k in complex_fields:
        if k in fields:
            logger.info("Classified as COMPLEX based on Azure field presence: '%s'", k)
            return "COMPLEX"

    text = ocr_result.get("content", "").lower()
    for kw in complex_keywords:
        if kw in text:
            logger.info("Classified as COMPLEX based on content keyword: '%s'", kw)
            return "COMPLEX"

    return "STANDARD"
