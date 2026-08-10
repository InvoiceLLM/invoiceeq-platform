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
    """
    if subtotal is None:
        return None

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
                    
                # Apply item-level tax if present. Gap 31-adjacent: a per-line tax_percent/
                # tax_amount doesn't always mean the printed "amount" already includes it —
                # some invoices print a per-line rate purely for rate-bucketing (VAT summed
                # separately at the invoice level, amount stays pre-tax, e.g.
                # eu_vat_reverse_charge), others print amount as genuinely post-tax per line
                # (e.g. India GST). Accept either: only flag if amount matches neither.
                expected_pre_tax = discounted_subtotal
                expected_post_tax = discounted_subtotal
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
                        "field": "items",
                        "severity": "error"
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
                "field": "subtotal",
                "severity": "error"
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
            "field": "tax_amount",
            "severity": "error"
        }
    except Exception as e:
        logger.warning("Failed to perform totals math verification: %s", e)

    return None


def _number_text_variants(value: float) -> list[str]:
    """Plausible printed forms of a number: with/without thousands separator,
    with/without trailing .00, and rounded to 0/1/2 decimals (OCR sometimes
    drops trailing zeros or a decimal entirely on whole-number totals).
    Also supports negative number variations (absolute value, parenthesized,
    and credit suffixes)."""
    variants = set()
    values_to_format = [value]
    if value < 0:
        values_to_format.append(abs(value))

    for val in values_to_format:
        for decimals in (2, 1, 0):
            rounded = round(val, decimals)
            plain = f"{rounded:.{decimals}f}"
            with_commas = f"{rounded:,.{decimals}f}"
            variants.add(plain)
            variants.add(with_commas)

            # If the original value was negative, add negative-specific formats for the absolute value variants
            if value < 0 and val >= 0:
                variants.add(f"({plain})")
                variants.add(f"({with_commas})")
                variants.add(f"{plain}-")
                variants.add(f"{with_commas}-")
                variants.add(f"{plain} Cr")
                variants.add(f"{with_commas} Cr")
                variants.add(f"{plain} CR")
                variants.add(f"{with_commas} CR")
    return list(variants)


def _variant_found_in_text(variants: list[str], ocr_text: str) -> bool:
    """
    Checks whether any printed-number variant appears in the OCR text as a
    standalone number, not merely as a substring of a larger one — plain
    `v in ocr_text` would false-negative on e.g. variant "10" matching inside
    "100.00" or "210.00", silently defeating the faithfulness check it's part
    of (found via test_gap_46/56's own regression test). Digit-boundary
    lookaround instead of `\\b`, since "." isn't a word character and would
    let `\\b` match right before/after the decimal point.
    """
    for v in variants:
        if re.search(rf"(?<!\d){re.escape(v)}(?!\d)", ocr_text):
            return True
    return False


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
        if _variant_found_in_text(variants, ocr_text):
            return None

        return {
            "type": "total_not_verified_in_source",
            "message": f"{grand_total:.2f}",
            "field": "grand_total",
            "severity": "warning"
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
            if not _variant_found_in_text(variants, ocr_text):
                unverified.append((idx, item.get("description") or f"item {idx + 1}", float(amount)))

        if not unverified:
            return None

        amounts_str = ", ".join(f"{a:.2f}" for _, _, a in unverified)
        any_negative = any(a < 0 for _, _, a in unverified)
        msg = amounts_str
        if any_negative:
            msg += " (negative/credit values may be printed as positive or parenthesized)"

        return {
            "type": "line_item_not_verified_in_source",
            "message": msg,
            "field": "items",
            "severity": "warning"
        }
    except Exception as e:
        logger.warning("Failed to perform line item source-text verification: %s", e)

    return None


def verify_subtotal_in_source_text(subtotal: float | None, ocr_text: str | None) -> dict | None:
    """
    Gap 43: Same principle as Gap 33 (grand_total) and Gap 36 (line items).
    An LLM extracting from an internally-inconsistent invoice (printed subtotal
    doesn't match the sum of line items) will sometimes silently "correct" the
    extracted subtotal instead of transcribing it as printed.

    This check verifies that the extracted subtotal appears verbatim (in some
    plausible printed form) anywhere in the raw OCR text.
    """
    if subtotal is None or not ocr_text:
        return None

    try:
        variants = _number_text_variants(float(subtotal))
        if _variant_found_in_text(variants, ocr_text):
            return None

        return {
            "type": "subtotal_not_verified_in_source",
            "message": f"{subtotal:.2f}",
            "field": "subtotal",
            "severity": "warning"
        }
    except Exception as e:
        logger.warning("Failed to perform subtotal source-text verification: %s", e)

    return None


def verify_unit_prices_in_source_text(items: list[dict] | None, ocr_text: str | None) -> dict | None:
    """
    Gap 44: Same principle as Gap 33 (grand_total), Gap 36 (line items), and Gap 43 (subtotal).
    If a printed line amount does not equal quantity * unit_price, the LLM
    sometimes silently recalculates/corrects the extracted unit_price (or quantity)
    to reconcile the line multiplication, inventing a price that was never printed on the page.

    This check verifies that each extracted line item's unit_price appears
    verbatim (in some plausible printed form) anywhere in the raw OCR text.
    """
    if not items or not ocr_text:
        return None

    try:
        unverified = []
        for idx, item in enumerate(items):
            price = item.get("unit_price")
            if price is None:
                continue
            variants = _number_text_variants(float(price))
            if not _variant_found_in_text(variants, ocr_text):
                unverified.append((idx, item.get("description") or f"item {idx + 1}", float(price)))

        if not unverified:
            return None

        msg = ", ".join(f"{p:.2f}" for _, _, p in unverified)
        return {
            "type": "unit_price_not_verified_in_source",
            "message": msg,
            "field": "items",
            "severity": "warning"
        }
    except Exception as e:
        logger.warning("Failed to perform unit-price source-text verification: %s", e)

    return None


def verify_tax_amount_in_source_text(
    tax_amount: float | None,
    ocr_text: str | None,
    tax_components: list[dict] | None = None,
) -> dict | None:
    """
    Gap 46: Tax amount OCR source-text verification.
    If a printed invoice contains bad vendor tax arithmetic, the LLM extraction
    prompt occasionally auto-corrects tax_amount to make math reconcile, masking
    the printed vendor flaw and preventing audit alerts.

    This check verifies that the extracted non-zero tax_amount appears verbatim
    (in a plausible printed form) anywhere in the raw OCR text.

    Gap 69: on invoices that split tax across multiple printed lines (e.g. India's
    CGST + SGST convention), the *summed* tax_amount never appears as one printed
    figure by construction — every genuine India GST invoice would otherwise
    guaranteed-fail this check regardless of vendor, forcing manual dismissal on
    every single one. Rather than weaken the check, make it component-aware: if
    the combined figure isn't found, fall back to verifying each individual tax
    component (e.g. `taxes[]` — CGST, SGST) appears verbatim on its own AND that
    they sum to tax_amount. This is not a weaker check — every component still
    has to be independently grounded in the printed text, so a genuinely
    fabricated tax_amount (not backed by real printed components) still gets
    caught; only a faithfully-transcribed multi-line split now passes.
    """
    if tax_amount is None or not ocr_text:
        return None

    try:
        # Skip 0.0 tax check as zero tax is frequently implicit/unprinted
        if float(tax_amount) == 0.0:
            return None

        variants = _number_text_variants(float(tax_amount))
        if _variant_found_in_text(variants, ocr_text):
            return None

        # Gap 69: combined figure not found — check if it's a faithful sum of
        # individually-verbatim tax components instead of a silent correction.
        if tax_components:
            component_amounts = []
            for component in tax_components:
                amount = component.get("amount") if isinstance(component, dict) else None
                if amount is None:
                    component_amounts = []
                    break
                component_variants = _number_text_variants(float(amount))
                if not _variant_found_in_text(component_variants, ocr_text):
                    component_amounts = []
                    break
                component_amounts.append(float(amount))

            if component_amounts and _within_tolerance(sum(component_amounts), float(tax_amount)):
                return None

        return {
            "type": "tax_amount_not_verified_in_source",
            "message": f"{tax_amount:.2f}",
            "field": "tax_amount",
            "severity": "warning"
        }
    except Exception as e:
        logger.warning("Failed to perform tax_amount source-text verification: %s", e)

    return None



# ---------------------------------------------------------------------------
# Gap 3 — Critic Node: confidence-driven audit routing
# ---------------------------------------------------------------------------
# Azure Document Intelligence returns a per-field confidence score (0.0–1.0)
# for every field it extracts from the document. Until this check was added,
# those scores were saved to the DB but never acted on — so a smudged or
# blurry invoice could be silently accepted even when the OCR engine itself
# was only 20% sure about a critical field like the invoice number.
#
# This function checks whether any *critical* field has a confidence score
# below the given threshold. If so, it returns a per-field alert so the
# extraction agent can either retry (hoping the LLM does better on a second
# pass with feedback) or flag the invoice for human audit review.
# ---------------------------------------------------------------------------

# These are the fields we consider critical — if the OCR is unsure about
# any of these, the invoice should not be auto-completed without review.
CRITICAL_CONFIDENCE_FIELDS = [
    "VendorName",
    "InvoiceId",
    "InvoiceDate",
    "InvoiceTotal",
    "SubTotal",
    "TotalTax",
    "PurchaseOrder",
]

# Minimum acceptable OCR confidence for critical fields.
# Fields below this threshold will be flagged for audit.
CONFIDENCE_THRESHOLD = 0.4


def verify_field_confidence(
    field_confidence: dict | None,
    threshold: float = CONFIDENCE_THRESHOLD,
) -> list[dict]:
    """
    Gap 3 (Critic Node): checks OCR-level confidence scores for critical
    invoice fields. Returns a list of alert dicts — one per low-confidence
    field — so the auditor sees exactly *which* fields need a second look,
    not a generic "review everything" warning.

    The field names come from Azure Document Intelligence's prebuilt-invoice
    model (e.g. "VendorName", "InvoiceId", "InvoiceTotal"). We map them to
    our schema's field names in the alert for frontend display.

    Returns an empty list if all critical fields are above threshold or if
    no confidence data is available (e.g. mock/local OCR mode).
    """
    if not field_confidence:
        return []

    # Map Azure Doc Intelligence field names → our schema field names
    # so the frontend can highlight the right cell in the auditor UI.
    AZURE_TO_SCHEMA = {
        "VendorName": "vendor_name",
        "InvoiceId": "invoice_number",
        "InvoiceDate": "invoice_date",
        "InvoiceTotal": "grand_total",
        "SubTotal": "subtotal",
        "TotalTax": "tax_amount",
        "PurchaseOrder": "po_number",
    }

    low_confidence_alerts = []

    try:
        for azure_field in CRITICAL_CONFIDENCE_FIELDS:
            score = field_confidence.get(azure_field)
            # score is None when the field wasn't found on the document at all
            # — that's fine, skip it (missing optional fields aren't a concern).
            if score is None:
                continue
            if score < threshold:
                schema_field = AZURE_TO_SCHEMA.get(azure_field, azure_field)
                low_confidence_alerts.append({
                    "type": "low_confidence_field",
                    "message": f"{score:.0%} (threshold {threshold:.0%})",
                    "field": schema_field,
                    "confidence": score,
                    "severity": "warning",
                })
    except Exception as e:
        logger.warning("Failed to perform field confidence verification: %s", e)

    return low_confidence_alerts




