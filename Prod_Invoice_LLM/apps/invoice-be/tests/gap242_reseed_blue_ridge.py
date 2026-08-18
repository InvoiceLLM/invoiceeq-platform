"""BE Gap 242 test-data reseed -- functional-tester pass 2026-08-17.

Blue Ridge Logistics (tenant-us) had its `items` column overwritten with a
placeholder ("TEST LINE ITEM EDIT", no freight-related text) during an
earlier Gap 234 end-to-end verification test (disclosed directly in BE Gap
242's own tracker entry). That corruption also carried `subtotal` down to
200.0 (the corrupted single line item's amount), which no longer reconciles
with the invoice's untouched grand_total/tax_amount.

Before (read directly from the DB, 2026-08-17):
  grand_total = 2386.31, tax_amount = 161.31 (7.25% sales tax), subtotal = 200.0
  items = [{"description": "TEST LINE ITEM EDIT", "quantity": 2.0,
            "unit_price": 100.0, "amount": 200.0}]

subtotal + tax_amount should equal grand_total. 2386.31 - 161.31 = 2225.00,
and 2225.00 * 7.25% = 161.3125 (rounds to 161.31, matching the stored
tax_amount exactly) -- strong evidence the real pre-corruption subtotal was
$2225.00, not $200.00. This script restores realistic freight/logistics line
items summing to exactly $2225.00, and fixes subtotal to match (grand_total
and tax_amount are left untouched -- they were never corrupted).

Application code is NOT touched. This is a raw, direct DB correction to test
fixture data only, done outside the app's own audit-correction endpoints
(deliberately -- going through PUT /audit/resolve would write an AuditLog
entry as though a human reviewer made this correction, which would misstate
the record; this is test-data repair, not an audit action).
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlmodel import Session, select

from database import engine
from models import Invoice

INVOICE_ID = "e6ccfb34-d53f-45e7-8ec9-119ced8aa0db"

NEW_ITEMS = [
    {
        "description": "LTL Freight Transportation -- Charlotte, NC to Columbus, OH (Freight Class 70)",
        "quantity": 1,
        "unit_price": 1800.00,
        "amount": 1800.00,
    },
    {
        "description": "Fuel Surcharge (12.5%)",
        "quantity": 1,
        "unit_price": 225.00,
        "amount": 225.00,
    },
    {
        "description": "Liftgate Delivery Fee",
        "quantity": 1,
        "unit_price": 125.00,
        "amount": 125.00,
    },
    {
        "description": "Residential Delivery Surcharge",
        "quantity": 1,
        "unit_price": 75.00,
        "amount": 75.00,
    },
]
NEW_SUBTOTAL = sum(i["amount"] for i in NEW_ITEMS)


def main():
    with Session(engine) as s:
        inv = s.exec(select(Invoice).where(Invoice.id == INVOICE_ID)).first()
        if inv is None:
            print("Invoice not found: " + INVOICE_ID)
            return

        before = {
            "vendor_name": inv.vendor_name,
            "invoice_number": inv.invoice_number,
            "grand_total": inv.grand_total,
            "tax_amount": inv.tax_amount,
            "subtotal": inv.subtotal,
            "items": inv.items,
            "tags": inv.tags,
        }
        print("BEFORE:")
        print(json.dumps(before, indent=2, default=str))

        assert inv.vendor_name == "Blue Ridge Logistics", "safety check: unexpected vendor on this id, aborting"
        assert round(NEW_SUBTOTAL, 2) + inv.tax_amount == inv.grand_total, (
            "safety check: new subtotal + existing tax_amount must equal existing grand_total, aborting. "
            "got " + str(NEW_SUBTOTAL) + " + " + str(inv.tax_amount) + " != " + str(inv.grand_total)
        )

        inv.items = NEW_ITEMS
        inv.subtotal = round(NEW_SUBTOTAL, 2)
        s.add(inv)
        s.commit()
        s.refresh(inv)

        after = {
            "vendor_name": inv.vendor_name,
            "invoice_number": inv.invoice_number,
            "grand_total": inv.grand_total,
            "tax_amount": inv.tax_amount,
            "subtotal": inv.subtotal,
            "items": inv.items,
            "tags": inv.tags,
        }
        print("\nAFTER:")
        print(json.dumps(after, indent=2, default=str))

        out_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "docs", "test_evidence", "gap242_blue_ridge_reseed_2026-08-17",
        )
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "before_after.json"), "w", encoding="utf-8") as f:
            json.dump({"invoice_id": INVOICE_ID, "before": before, "after": after}, f, indent=2, default=str)
        print("\nWrote " + os.path.join(out_dir, "before_after.json"))


if __name__ == "__main__":
    main()
