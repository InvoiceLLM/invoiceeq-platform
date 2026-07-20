import logging

logger = logging.getLogger(__name__)

def verify_line_items_math(items: list[dict], subtotal: float | None, invoice_tax_amount: float | None = None) -> dict | None:
    """
    Checks if sum(item.amount) == subtotal.
    Also verifies each item's amount matches qty * rate * (1 - discount) * (1 + tax) if details are present.
    Returns an alert dict if mismatch, else None.

    Guard: if every item shares the identical tax_percent and that rate matches the invoice's
    own effective tax rate (tax_amount / subtotal), it's almost certainly a single invoice-level
    tax rate that got copied onto each line during extraction rather than genuine per-line tax —
    skip the tax step for that case instead of raising a false positive. Invoices with real
    per-line tax (different rates per row) are unaffected, since this only fires when every rate
    is identical.
    """
    if subtotal is None:
        return None

    suppress_line_tax = False
    try:
        line_tax_percents = [float(item.get("tax_percent")) for item in items if item.get("tax_percent") is not None]
        if line_tax_percents and len(set(round(t, 2) for t in line_tax_percents)) == 1 and subtotal:
            invoice_effective_rate = (float(invoice_tax_amount) / float(subtotal)) * 100.0 if invoice_tax_amount is not None else None
            if invoice_effective_rate is not None and abs(line_tax_percents[0] - invoice_effective_rate) < 0.5:
                suppress_line_tax = True
    except (TypeError, ValueError, ZeroDivisionError):
        pass

    try:
        # 1. Verify individual line item math calculations
        for item in items:
            qty = item.get("quantity")
            unit_price = item.get("unit_price")
            amount = item.get("amount")
            
            if qty is not None and unit_price is not None and amount is not None:
                qty = float(qty)
                unit_price = float(unit_price)
                amount = float(amount)
                
                line_subtotal = qty * unit_price
                
                # Apply item-level discount if present
                discount_percent = item.get("discount_percent")
                discount_amount = item.get("discount_amount")
                discounted_subtotal = line_subtotal
                if discount_percent is not None:
                    discounted_subtotal -= line_subtotal * (float(discount_percent) / 100.0)
                elif discount_amount is not None:
                    discounted_subtotal -= float(discount_amount)
                    
                # Apply item-level tax if present (unless it looks like a copied-down invoice-level rate)
                expected_amount = discounted_subtotal
                if not suppress_line_tax:
                    tax_percent = item.get("tax_percent")
                    tax_amount = item.get("tax_amount")
                    if tax_percent is not None:
                        expected_amount += discounted_subtotal * (float(tax_percent) / 100.0)
                    elif tax_amount is not None:
                        expected_amount += float(tax_amount)
                    
                if abs(expected_amount - amount) >= 0.01:
                    return {
                        "type": "line_item_calculation_mismatch",
                        "message": f"Line item '{item.get('description', '')}' amount ({amount:.2f}) does not match calculated amount ({expected_amount:.2f}) based on qty/unit_price/discount/tax",
                        "field": "items"
                    }

        # 2. Verify subtotal matches sum of line item amounts
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

def verify_totals_math(
    subtotal: float | None,
    tax_amount: float | None,
    grand_total: float | None,
    discount_amount: float | None = None,
    discount_percent: float | None = None
) -> dict | None:
    """
    Checks if subtotal + tax_amount - discount == grand_total.
    Returns an alert dict if mismatch, else None.
    """
    if grand_total is None or subtotal is None:
        return None
        
    try:
        tax = tax_amount or 0.0
        discount = discount_amount or 0.0
        if discount_percent is not None:
            discount = subtotal * (float(discount_percent) / 100.0)
            
        expected_grand_total = subtotal + tax - discount
        if abs(expected_grand_total - grand_total) >= 0.01:
            msg = f"Subtotal ({subtotal:.2f}) + Tax ({tax:.2f})"
            if discount > 0:
                msg += f" - Discount ({discount:.2f})"
            msg += f" does not match Grand Total ({grand_total:.2f})"
            return {
                "type": "tax_mismatch",
                "message": msg,
                "field": "tax_amount"
            }
    except Exception as e:
        logger.warning("Failed to perform totals math verification: %s", e)
        
    return None

