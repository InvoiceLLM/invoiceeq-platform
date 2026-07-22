import logging
import re

logger = logging.getLogger(__name__)

# Gap 31: a flat 0.01 absolute tolerance flags economically-immaterial rounding
# differences on large invoices (e.g. a ~13-unit gap on an 80,000-unit line from
# percentage-discount rounding). Add a relative tolerance alongside it.
REL_TOLERANCE = 0.005  # 0.5%


def _within_tolerance(actual: float, expected: float, abs_tol: float = 0.01, rel_tol: float = REL_TOLERANCE) -> bool:
    return abs(actual - expected) <= max(abs_tol, rel_tol * abs(expected))


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
                    
                # Apply item-level tax if present (unless it looks like a copied-down invoice-level rate).
                # Gap 31-adjacent: a per-line tax_percent/tax_amount doesn't always mean the printed
                # "amount" already includes it — some invoices print a per-line rate purely for
                # rate-bucketing (VAT summed separately at the invoice level, amount stays pre-tax,
                # e.g. eu_vat_reverse_charge), others print amount as genuinely post-tax per line
                # (e.g. India GST). Accept either: only flag if amount matches neither.
                expected_pre_tax = discounted_subtotal
                expected_post_tax = discounted_subtotal
                if not suppress_line_tax:
                    tax_percent = item.get("tax_percent")
                    tax_amount = item.get("tax_amount")
                    if tax_percent is not None:
                        expected_post_tax += discounted_subtotal * (float(tax_percent) / 100.0)
                    elif tax_amount is not None:
                        expected_post_tax += float(tax_amount)

                if not (_within_tolerance(amount, expected_pre_tax) or _within_tolerance(amount, expected_post_tax)):
                    return {
                        "type": "line_item_calculation_mismatch",
                        "message": f"Line item '{item.get('description', '')}' amount ({amount:.2f}) does not match calculated amount ({expected_post_tax:.2f}) based on qty/unit_price/discount/tax",
                        "field": "items"
                    }

        # 2. Verify subtotal matches sum of line item amounts.
        # Gap 31 (4th dimension): on US/UK-style invoices, item.amount is pre-tax and
        # should equal subtotal directly. On India GST-style invoices, item.amount is
        # the line's post-tax figure (taxable value + that line's GST), so the sum only
        # reconciles against subtotal + invoice_tax_amount. Accept either convention.
        total_line_amount = sum(float(item.get("amount") or 0.0) for item in items)
        matches_pre_tax = _within_tolerance(total_line_amount, subtotal)
        matches_post_tax = invoice_tax_amount is not None and _within_tolerance(total_line_amount, subtotal + float(invoice_tax_amount))
        if not (matches_pre_tax or matches_post_tax):
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
    discount_percent: float | None = None,
    round_off: float | None = None,
) -> dict | None:
    """
    Checks subtotal + tax_amount - discount + round_off == grand_total.
    Returns an alert dict if mismatch, else None.

    Gap 31: `subtotal` is ambiguous across invoice conventions — the schema's own
    description says "before taxes/discounts" (pre-discount), but GST-style invoices
    often print "Subtotal (Taxable Value)" already net of any per-line discount
    (post-discount). Rather than assume one, accept either interpretation: only
    flag a mismatch if grand_total matches neither. When there's no discount, both
    formulas collapse to the same value, so non-discount invoices are unaffected.
    `round_off` covers the small +/- rounding adjustment line common on Indian
    GST invoices (and the combined CGST+SGST split, once summed into tax_amount
    by extraction, needs no special handling here beyond this).
    """
    if grand_total is None or subtotal is None:
        return None

    try:
        tax = tax_amount or 0.0
        adjustment = round_off or 0.0
        discount = discount_amount or 0.0
        if discount_percent is not None:
            discount = subtotal * (float(discount_percent) / 100.0)

        expected_pre_discount = subtotal - discount + tax + adjustment
        expected_post_discount = subtotal + tax + adjustment

        if _within_tolerance(grand_total, expected_pre_discount) or _within_tolerance(grand_total, expected_post_discount):
            return None

        msg = f"Subtotal ({subtotal:.2f}) + Tax ({tax:.2f})"
        if discount > 0:
            msg += f" - Discount ({discount:.2f})"
        if adjustment:
            msg += f" + Round Off ({adjustment:.2f})"
        msg += f" does not match Grand Total ({grand_total:.2f})"
        return {
            "type": "tax_mismatch",
            "message": msg,
            "field": "tax_amount"
        }
    except Exception as e:
        logger.warning("Failed to perform totals math verification: %s", e)

    return None


def _number_text_variants(value: float) -> list[str]:
    """Plausible printed forms of a number: with/without thousands separator,
    with/without trailing .00, and rounded to 0/1/2 decimals (OCR sometimes
    drops trailing zeros or a decimal entirely on whole-number totals)."""
    variants = set()
    for decimals in (2, 1, 0):
        rounded = round(value, decimals)
        plain = f"{rounded:.{decimals}f}"
        with_commas = f"{rounded:,.{decimals}f}"
        variants.add(plain)
        variants.add(with_commas)
    return list(variants)


def verify_grand_total_in_source_text(grand_total: float | None, ocr_text: str | None) -> dict | None:
    """
    Gap 33: an LLM extracting from an internally-inconsistent invoice (printed
    total doesn't match subtotal+tax) will sometimes "correct" the figure to
    the arithmetically-correct value instead of transcribing what's actually
    printed — silently defeating verify_totals_math, since the corrected
    number reconciles perfectly with itself and no mismatch is ever raised.

    This check is deliberately independent of arithmetic: it only asks
    whether the extracted grand_total appears verbatim (in some plausible
    printed form) anywhere in the raw OCR text. A faithfully-transcribed
    total — correct or deliberately wrong — always passes this; a
    silently-recalculated one usually does not, because the recalculated
    figure was never printed on the document at all.
    """
    if grand_total is None or not ocr_text:
        return None

    try:
        variants = _number_text_variants(float(grand_total))
        if any(v in ocr_text for v in variants):
            return None

        return {
            "type": "total_not_verified_in_source",
            "message": (
                f"Extracted grand_total ({grand_total:.2f}) was not found verbatim in the "
                "source document text — possible silent correction of a printed figure rather "
                "than faithful transcription. Flagged for manual review."
            ),
            "field": "grand_total"
        }
    except Exception as e:
        logger.warning("Failed to perform grand_total source-text verification: %s", e)

    return None


def verify_line_item_amounts_in_source_text(items: list[dict] | None, ocr_text: str | None) -> dict | None:
    """
    Gap 36 — Gap 33's sibling at the line-item level: the same LLM behavior that
    silently "corrects" an inconsistent grand_total can also silently correct an
    individual line item's amount so sum(items) reconciles with the printed
    subtotal, defeating verify_line_items_math's subtotal-sum/per-line checks
    the same way Gap 33 defeated verify_totals_math. Found via the benchmark's
    `subtotal_mismatch`/`rounding_gap` flaw types (deliberately bump one printed
    row's amount without touching the printed subtotal) — the extraction
    repeatedly extracted a line amount that summed exactly to the correct
    (unflawed) subtotal instead of the deliberately-wrong printed figure.

    Same principle as verify_grand_total_in_source_text: independent of
    arithmetic, only asks whether each line item's extracted `amount` appears
    verbatim (in a plausible printed form) anywhere in the raw OCR text.
    """
    if not items or not ocr_text:
        return None

    try:
        unverified = []
        for idx, item in enumerate(items):
            amount = item.get("amount")
            if amount is None:
                continue
            variants = _number_text_variants(float(amount))
            if not any(v in ocr_text for v in variants):
                unverified.append((idx, item.get("description") or f"item {idx + 1}", float(amount)))

        if not unverified:
            return None

        desc = "; ".join(f"'{d}' ({a:.2f})" for _, d, a in unverified)
        return {
            "type": "line_item_not_verified_in_source",
            "message": (
                f"Extracted line item amount(s) not found verbatim in the source document text: {desc} — "
                "possible silent correction of a printed figure rather than faithful transcription. "
                "Flagged for manual review."
            ),
            "field": "items"
        }
    except Exception as e:
        logger.warning("Failed to perform line item source-text verification: %s", e)

    return None

