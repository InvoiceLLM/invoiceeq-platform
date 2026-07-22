"""Procedural invoice generator: produces (pdf_builder_kwargs, ground_truth) pairs
per region, with known-correct ground truth (since we control the numbers).

Region tax conventions:
  US    - single flat sales-tax % at invoice level (sometimes 0%), no per-line tax.
  INDIA - genuine per-line GST% (varies by HSN/product), split into CGST+SGST,
          per-line discount%, a Round Off line.
  UK    - genuine per-line VAT% (20 standard / 5 reduced / 0 zero-rated), with an
          occasional reverse-charge note on 0%-rated cross-border service lines.

Flaw types (for the "flawed" half of each day's batch), one per invoice. All three
math-breaking flaws below inject a gap scaled to the affected amount (a percentage
plus a fixed floor), not a flat few units, so they reliably exceed
verify_totals_math/verify_line_items_math's tolerance (max(0.01, 0.5% relative) —
Gap 31, fixed Jul 21, 2026) regardless of invoice size, instead of risking getting
swallowed by it on large high-complexity invoices:
  broken_total           - printed TOTAL DUE doesn't reconcile -> tax_mismatch alert
  subtotal_mismatch      - printed Subtotal != sum of line amounts -> line_items_mismatch alert
  rounding_gap           - one line's amount doesn't match qty*price*(1-discount)(1+tax)
                            -> line_item_calculation_mismatch alert
  missing_optional_field - omit PO number / due date -> should NOT trigger AUDIT_REQUIRED;
                            checks extraction correctly leaves the field null instead of
                            hallucinating a value
"""
import random
import re
from dataclasses import dataclass, field

from tests.benchmark.catalog import REGIONS

FLAW_TYPES = ["broken_total", "subtotal_mismatch", "rounding_gap", "missing_optional_field"]


@dataclass
class GeneratedInvoice:
    name: str
    region: str
    pdf_kwargs: dict
    ground_truth: dict = field(default_factory=dict)


def _fmt(amount: float, symbol: str) -> str:
    return f"{symbol}{amount:,.2f}"


def _pick_line_items(rng: random.Random, region: str, count: int):
    products = REGIONS[region]["products"]
    return rng.sample(products, k=min(count, len(products))) if count <= len(products) else \
        [rng.choice(products) for _ in range(count)]


def _generate_us(rng: random.Random, invoice_id: str, complexity: str, flaw: str | None) -> GeneratedInvoice:
    data = REGIONS["US"]
    vendor_name, vendor_addr = rng.choice(data["vendors"])
    customer_name, customer_addr = rng.choice(data["customers"])
    symbol = data["currency_symbol"]

    n_items = rng.randint(3, 6) if complexity == "medium" else rng.randint(7, 15)
    items = _pick_line_items(rng, "US", n_items)

    rows, line_total_check = [], 0.0
    for idx, (desc, lo, hi) in enumerate(items, start=1):
        qty = rng.randint(1, 20)
        unit_price = round(rng.uniform(lo, hi), 2)
        amount = round(qty * unit_price, 2)
        rows.append([str(idx), desc, str(qty), _fmt(unit_price, symbol), _fmt(amount, symbol)])
        line_total_check += amount

    subtotal = round(line_total_check, 2)
    discount_pct = rng.choice([0, 0, 5, 10, 15])
    discount_amt = round(subtotal * discount_pct / 100.0, 2)
    after_discount = round(subtotal - discount_amt, 2)
    tax_pct = rng.choice([0, 0, 5, 6, 7.5, 8, 10])
    tax_amt = round(after_discount * tax_pct / 100.0, 2)
    grand_total = round(after_discount + tax_amt, 2)

    summary_rows = [["Subtotal:", _fmt(subtotal, symbol)]]
    if discount_pct:
        summary_rows.append([f"Discount ({discount_pct}%):", f"-{_fmt(discount_amt, symbol)}"])
        summary_rows.append(["After Discount:", _fmt(after_discount, symbol)])
    summary_rows.append([f"Tax ({tax_pct}%):", _fmt(tax_amt, symbol)])

    po_number = f"PO-{rng.randint(10000, 99999)}"
    meta_lines = [f"Invoice Number: {invoice_id}", "Invoice Date: 10 Jul 2026", "Due Date: 09 Aug 2026", f"PO Number: {po_number}"]
    gt = {
        "invoice_number": invoice_id,
        "expected_grand_total": grand_total,
        "expected_tax_amount": tax_amt,
        "expected_subtotal": subtotal,
        "expected_po_number": po_number,
        "expected_vendor_name": vendor_name,
    }

    grand_total = _apply_flaw(flaw, rng, rows, summary_rows, meta_lines, gt, symbol, grand_total, subtotal)
    summary_rows.append(["TOTAL DUE:", _fmt(grand_total, symbol)])

    return GeneratedInvoice(
        name=f"us_{invoice_id}",
        region="US",
        pdf_kwargs=dict(
            vendor_lines=[f"<b>{vendor_name}</b>", vendor_addr],
            meta_lines=meta_lines,
            bill_to_lines=[customer_name, customer_addr],
            columns=["#", "Description", "Qty", "Unit Price (USD)", "Amount (USD)"],
            rows=rows,
            summary_rows=summary_rows,
        ),
        ground_truth=gt,
    )


def _generate_india(rng: random.Random, invoice_id: str, complexity: str, flaw: str | None) -> GeneratedInvoice:
    data = REGIONS["INDIA"]
    vendor_name, vendor_addr, vendor_gstin = rng.choice(data["vendors"])
    customer_name, customer_addr, customer_gstin = rng.choice(data["customers"])
    symbol = data["currency_symbol"]

    n_items = rng.randint(3, 6) if complexity == "medium" else rng.randint(7, 15)
    products = data["products"]
    items = rng.sample(products, k=min(n_items, len(products)))

    rows, taxable_total, gst_buckets = [], 0.0, {}
    for idx, (desc, hsn, gst_rate, lo, hi) in enumerate(items, start=1):
        qty = rng.randint(2, 50)
        rate = round(rng.uniform(lo, hi), 2)
        line_subtotal = qty * rate
        discount_pct = rng.choice([0, 0, 5, 7.5, 10]) if complexity == "high" else 0
        taxable_value = round(line_subtotal * (1 - discount_pct / 100.0), 2)
        amount = round(taxable_value * (1 + gst_rate / 100.0), 2)
        rows.append([str(idx), hsn, desc, str(qty), f"{rate:,.2f}", f"{discount_pct}%" if discount_pct else "-", f"{taxable_value:,.2f}", f"{gst_rate}%", f"{amount:,.2f}"])
        taxable_total += taxable_value
        gst_buckets[gst_rate] = gst_buckets.get(gst_rate, 0.0) + taxable_value

    taxable_total = round(taxable_total, 2)
    total_gst = round(sum(v * r / 100.0 for r, v in gst_buckets.items()), 2)
    cgst = round(total_gst / 2, 2)
    sgst = round(total_gst - cgst, 2)
    round_off = round(rng.uniform(-0.49, 0.49), 2)
    grand_total = round(taxable_total + cgst + sgst + round_off, 2)

    summary_rows = [
        ["Subtotal (Taxable Value):", f"{taxable_total:,.2f}"],
        ["Total CGST:", f"{cgst:,.2f}"],
        ["Total SGST:", f"{sgst:,.2f}"],
        ["Round Off:", f"{round_off:,.2f}"],
    ]

    meta_lines = [f"Invoice No: {invoice_id}", "Invoice Date: 10-Jul-2026", "Due Date: 09-Aug-2026"]
    gt = {
        "invoice_number": invoice_id,
        "expected_grand_total": grand_total,
        "expected_tax_amount": round(cgst + sgst, 2),
        "expected_subtotal": taxable_total,
        "expected_vendor_name": vendor_name,
        # India's post-discount subtotal + CGST/SGST split + round-off are known-unresolved
        # (Gap 31) - verify_totals_math will likely false-flag these even when the invoice
        # itself is internally consistent. Not asserted strictly; harness records it as a
        # known-gap category rather than a new defect.
        "known_gap_31_affected": True,
    }

    grand_total = _apply_flaw(flaw, rng, rows, summary_rows, meta_lines, gt, symbol, grand_total, taxable_total, amount_col_index=-1)
    summary_rows.append(["GRAND TOTAL (INR):", f"{grand_total:,.2f}"])

    return GeneratedInvoice(
        name=f"india_{invoice_id}",
        region="INDIA",
        pdf_kwargs=dict(
            vendor_lines=[f"<b>{vendor_name}</b>", vendor_addr, f"GSTIN: {vendor_gstin}"],
            meta_lines=meta_lines,
            bill_to_lines=[customer_name, customer_addr, f"GSTIN: {customer_gstin}"],
            columns=["#", "HSN/SAC", "Description", "Qty", "Rate (INR)", "Discount", "Taxable Value", "GST %", "Amount (INR)"],
            rows=rows,
            summary_rows=summary_rows,
        ),
        ground_truth=gt,
    )


def _generate_uk(rng: random.Random, invoice_id: str, complexity: str, flaw: str | None) -> GeneratedInvoice:
    data = REGIONS["UK"]
    vendor_name, vendor_addr, vendor_vat = rng.choice(data["vendors"])
    customer_name, customer_addr, customer_vat = rng.choice(data["customers"])
    symbol = data["currency_symbol"]

    n_items = rng.randint(3, 6) if complexity == "medium" else rng.randint(7, 15)
    products = data["products"]
    items = rng.sample(products, k=min(n_items, len(products)))

    rows, subtotal, vat_buckets, has_reverse_charge = [], 0.0, {}, False
    for idx, (desc, vat_rate, lo, hi) in enumerate(items, start=1):
        qty = rng.randint(1, 15)
        unit_price = round(rng.uniform(lo, hi), 2)
        amount = round(qty * unit_price, 2)
        rows.append([str(idx), desc, str(qty), f"{unit_price:,.2f}", f"{vat_rate}%", f"{amount:,.2f}"])
        subtotal += amount
        vat_buckets[vat_rate] = vat_buckets.get(vat_rate, 0.0) + amount
        if "Reverse Charge" in desc:
            has_reverse_charge = True

    subtotal = round(subtotal, 2)
    total_vat = round(sum(v * r / 100.0 for r, v in vat_buckets.items()), 2)
    grand_total = round(subtotal + total_vat, 2)

    summary_rows = [["Subtotal:", f"{subtotal:,.2f}"]]
    for rate, amt in sorted(vat_buckets.items(), reverse=True):
        summary_rows.append([f"VAT ({rate}% on GBP {amt:,.2f}):", f"{amt * rate / 100.0:,.2f}"])

    notes = [f"{customer_name} VAT ID: {customer_vat}"]
    if has_reverse_charge:
        notes.append("Reverse charge - VAT to be accounted for by the recipient (Art. 196 EU VAT Directive / UK cross-border services).")

    meta_lines = [f"Invoice Number: {invoice_id}", "Invoice Date: 10 Jul 2026", "Due Date: 09 Aug 2026"]
    gt = {
        "invoice_number": invoice_id,
        "expected_grand_total": grand_total,
        "expected_tax_amount": total_vat,
        "expected_subtotal": subtotal,
        "expected_vendor_name": vendor_name,
    }

    grand_total = _apply_flaw(flaw, rng, rows, summary_rows, meta_lines, gt, symbol, grand_total, subtotal)
    summary_rows.append(["TOTAL DUE:", f"{grand_total:,.2f}"])

    return GeneratedInvoice(
        name=f"uk_{invoice_id}",
        region="UK",
        pdf_kwargs=dict(
            vendor_lines=[f"<b>{vendor_name}</b>", vendor_addr, f"VAT: {vendor_vat}"],
            meta_lines=meta_lines,
            bill_to_lines=[customer_name, customer_addr, f"VAT: {customer_vat}"],
            columns=["#", "Description", "Qty", "Unit Price (GBP)", "VAT %", "Amount (GBP)"],
            rows=rows,
            summary_rows=summary_rows,
            notes=notes,
        ),
        ground_truth=gt,
    )


def _parse_amount(s: str) -> float:
    """Strips everything except digits/decimal-point before parsing (commas AND
    a leading currency symbol, e.g. US rows are formatted via _fmt() as "$8,756.48"
    while INDIA/UK rows are plain "8,756.48" with no symbol at all - a bare
    `.replace(",", "")` leaves the "$" in place and float() raises on it)."""
    cleaned = re.sub(r"[^\d.]", "", s)
    return float(cleaned)


def _apply_flaw(flaw, rng, rows, summary_rows, meta_lines, gt, symbol, grand_total, subtotal, amount_col_index=-1):
    """Mutates rows/meta_lines/gt in place for the chosen flaw type; returns the (possibly broken) grand_total.

    gt["expected_status"]/["expected_alert_type"] are only set to AUDIT_REQUIRED
    once the row mutation has actually succeeded — previously they were set
    unconditionally before a try/except that could silently no-op the mutation
    (found via the benchmark's own Day 1 regression run, Jul 22 2026: US rows'
    "$"-prefixed amount strings broke float() parsing here, silently leaving the
    row un-flawed while ground truth still claimed AUDIT_REQUIRED - a false
    positive in the test harness itself, not a real extraction/verification bug).
    """
    if flaw is None:
        gt["expected_status"] = "COMPLETED"
        return grand_total

    if flaw == "broken_total":
        # Scaled with grand_total (same reasoning as the other flaws below) so it reliably
        # exceeds verify_totals_math's tolerance on large high-complexity invoices too.
        gap = grand_total * rng.uniform(0.03, 0.06) + rng.uniform(50, 500)
        broken = round(grand_total + gap, 2)
        gt["expected_status"] = "AUDIT_REQUIRED"
        gt["expected_alert_type"] = "tax_mismatch"
        return broken

    if flaw == "subtotal_mismatch":
        # Nudge one row's printed amount without changing the summary subtotal - sum(rows) != subtotal.
        # Scaled with the line's value (same reasoning as rounding_gap below) so it reliably
        # exceeds the subtotal-sum check's tolerance regardless of invoice size.
        if rows:
            row = rows[0]
            current = _parse_amount(row[amount_col_index])
            gap = current * rng.uniform(0.03, 0.06) + rng.uniform(20, 100)
            row[amount_col_index] = f"{current + gap:,.2f}"
            gt["expected_status"] = "AUDIT_REQUIRED"
            gt["expected_alert_type"] = "line_items_mismatch"
        else:
            gt["expected_status"] = "COMPLETED"
        return grand_total

    if flaw == "rounding_gap":
        if rows:
            row = rows[0]
            current = _parse_amount(row[amount_col_index])
            # Must reliably exceed verify_line_items_math's tolerance
            # (max(0.01, 0.5% relative)) regardless of line size — a flat
            # 1-5 unit gap gets swallowed by the relative tolerance on large
            # lines. Scale with the line's own value, with margin.
            gap = current * rng.uniform(0.02, 0.04) + rng.uniform(1.0, 3.0)
            row[amount_col_index] = f"{current + gap:,.2f}"
            gt["expected_status"] = "AUDIT_REQUIRED"
            gt["expected_alert_type"] = "line_item_calculation_mismatch"
        else:
            gt["expected_status"] = "COMPLETED"
        return grand_total

    if flaw == "missing_optional_field":
        meta_lines[:] = [m for m in meta_lines if not m.startswith("Due Date") and not m.startswith("PO Number")]
        gt["expected_status"] = "COMPLETED"
        gt["expected_due_date"] = None
        gt["expected_po_number"] = None
        return grand_total

    gt["expected_status"] = "COMPLETED"
    return grand_total


_GENERATORS = {"US": _generate_us, "INDIA": _generate_india, "UK": _generate_uk}


def generate_daily_batch(region: str, day_seed: int, count: int = 10) -> list[GeneratedInvoice]:
    """10 invoices for one region: 5 clean/5 flawed, 6 medium/4 high, reproducible per day_seed."""
    rng = random.Random(f"{region}-{day_seed}")
    n_flawed = count // 2
    n_high = int(round(count * 0.4))

    complexities = ["high"] * n_high + ["medium"] * (count - n_high)
    rng.shuffle(complexities)
    flaws = rng.sample(FLAW_TYPES * ((n_flawed // len(FLAW_TYPES)) + 1), n_flawed) + [None] * (count - n_flawed)
    rng.shuffle(flaws)

    invoices = []
    for i in range(count):
        invoice_id = f"{region}-{day_seed}-{i+1:03d}"
        invoices.append(_GENERATORS[region](rng, invoice_id, complexities[i], flaws[i]))
    return invoices
