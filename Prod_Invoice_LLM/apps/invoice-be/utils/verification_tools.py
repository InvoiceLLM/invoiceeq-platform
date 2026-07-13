import logging

logger = logging.getLogger(__name__)

def verify_line_items_math(items: list[dict], subtotal: float | None) -> dict | None:
    """
    Checks if sum(item.amount) == subtotal.
    Returns an alert dict if mismatch, else None.
    """
    if subtotal is None:
        return None
        
    try:
        # Sum the amount field from each item, defaulting to 0.0 if missing/None
        total_line_amount = sum(float(item.get("amount") or 0.0) for item in items)
        if abs(total_line_amount - subtotal) >= 0.01:
            return {
                "type": "line_items_mismatch",
                "message": f"Line items sum ({total_line_amount:.2f}) does not match subtotal ({subtotal:.2f})",
                "field": "subtotal"
            }
    except Exception as e:
        logger.warning("Failed to perform line items math verification: %s", e)
        
    return None

def verify_totals_math(subtotal: float | None, tax_amount: float | None, grand_total: float | None) -> dict | None:
    """
    Checks if subtotal + tax_amount == grand_total.
    Returns an alert dict if mismatch, else None.
    """
    if grand_total is None or subtotal is None:
        return None
        
    try:
        tax = tax_amount or 0.0
        expected_grand_total = subtotal + tax
        if abs(expected_grand_total - grand_total) >= 0.01:
            return {
                "type": "tax_mismatch",
                "message": f"Subtotal ({subtotal:.2f}) + Tax ({tax:.2f}) does not match Grand Total ({grand_total:.2f})",
                "field": "tax_amount"
            }
    except Exception as e:
        logger.warning("Failed to perform totals math verification: %s", e)
        
    return None
