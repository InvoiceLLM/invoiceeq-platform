"""Feature 29 task 29.10 / phase-2 P1.4 — five genuinely multi-page documents.

**Why these had to be authored at all.** The eight probe documents in
`scripts/attach_chat_eval.py` are single-page and about 2 KB each. A long-context recall
gate built on 2 KB documents measures nothing: Luna and Terra would both score whatever
the agent logic scores, which is what the 16-turn probe already measured. The whole reason
the `long_doc` role exists is that a 1M-token window is not a 1M-token memory — Luna's MRCR
is ~41% against Terra's 89%+ — and only a document long enough to bury a fact can see that
difference.

**So every document here buries its decisive fact deliberately.** The fact that answers the
question is never on page 1: it is a clause two thirds of the way through a contract, one
unmatched line on the third page of a statement, line 47 of a 60-line purchase order. A
model that reads the beginning and the end and skims the middle scores well on a short
document and fails here, which is exactly the discrimination the 2-point rule at CP1 needs.

**Ground truth is DERIVED, never transcribed.** Each document is described by a data
structure; the PDF and the expected answers are both generated from it. Hand-writing "line
47 is $1,240.00" next to a generator that emits a different figure is the obvious way to
get a benchmark that grades the wrong thing, and this module makes that impossible: change
the data and both the document and its ground truth move together.

FOUNDER SPOT-CHECK OWED (decision 7's habit applied to fixtures): the figures below are
authored by this session, not taken from a real document. Task 29.10's role decision rests
on them, so they want a read before the number is treated as final.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Document descriptions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LongDoc:
    """One multi-page fixture and everything true about it.

    The property under test is that the document stays LONG and its decisive fact stays
    off page 1. A future edit that shortens a document would float the fact forward, and
    the fixture would quietly stop discriminating between models while still passing
    every other test -- so the parse test asserts both, and `min_pages` is the floor.
    """

    key: str
    title: str
    doc_type: str
    party: str
    header: tuple[str, ...]
    columns: str
    rows: tuple[str, ...]
    clauses: tuple[str, ...] = ()
    footer: tuple[str, ...] = ()
    #: The single fact the golden case asks for. `min_pages` is a FLOOR, not an
    #: exact count: the property under test is "this document is long and the fact
    #: is not on the first page", and pinning an exact page number would break on
    #: any harmless wording edit while testing nothing extra.
    buried_fact: str = ""
    min_pages: int = 3
    ground_truth: dict[str, Any] = field(default_factory=dict)


def _money(value: Decimal | float | int) -> str:
    return f"{Decimal(str(value)):,.2f}"


# --- 1. multi-page master services agreement --------------------------------
# 34 numbered clauses. The late-payment rate is clause 27.4, deep in the document,
# and clause 12.1 states a DIFFERENT percentage (a discount) as a decoy -- a model
# that grabs the first percentage it sees answers 2.0% and is wrong.
_CONTRACT_CLAUSES = tuple(
    [
        "1.1 This Master Services Agreement governs all work ordered by the Customer.",
        "1.2 Capitalised terms have the meanings given in Schedule A.",
        "2.1 The Supplier shall provide the Services with reasonable skill and care.",
        "2.2 The Supplier may subcontract only with the Customer's written consent.",
        "3.1 The Customer shall provide access to premises as reasonably required.",
        "4.1 Each Statement of Work is incorporated into this Agreement by reference.",
        "5.1 The Term begins on the Effective Date and continues for 36 months.",
        "6.1 Either party may terminate for material breach on 30 days' notice.",
        "6.2 Termination does not affect accrued rights or remedies.",
        "7.1 The Supplier shall maintain insurance of not less than USD 2,000,000.",
        "8.1 Each party shall keep the other's Confidential Information secret.",
        "9.1 Intellectual property created under a Statement of Work vests in the Customer.",
        "10.1 The Supplier warrants that the Services do not infringe third-party rights.",
        "11.1 Neither party is liable for indirect or consequential loss.",
        "11.2 Aggregate liability is capped at the fees paid in the preceding 12 months.",
        "12.1 A prompt-payment discount of 2.0% applies to invoices settled within 10 days.",
        "13.1 Invoices are issued monthly in arrears.",
        "14.1 The Customer shall pay undisputed invoices within 45 days of receipt.",
        "15.1 Disputed amounts must be notified within 15 days of the invoice date.",
        "16.1 The Supplier shall keep accurate records for 6 years.",
        "17.1 The Customer may audit those records once per calendar year.",
        "18.1 Change requests must be agreed in writing before work begins.",
        "19.1 The Supplier shall comply with all applicable anti-bribery laws.",
        "20.1 The Supplier shall comply with applicable data protection legislation.",
        "21.1 Personal data is processed only on the Customer's documented instructions.",
        "22.1 Neither party may assign without the other's consent.",
        "23.1 Notices must be given in writing to the addresses in Schedule B.",
        "24.1 No waiver of any breach constitutes a waiver of any other breach.",
        "25.1 If any provision is held invalid the remainder continues in force.",
        "26.1 This Agreement constitutes the entire agreement between the parties.",
        "27.1 Payment is due in the currency stated on the invoice.",
        "27.2 Bank charges are borne by the paying party.",
        "27.3 The Customer shall not set off any amount without the Supplier's consent.",
        "27.4 Overdue amounts bear interest at 1.5% per month from the due date until paid.",
        "28.1 Force majeure suspends performance for so long as the event continues.",
        "29.1 The parties are independent contractors and not partners or agents.",
        "30.1 This Agreement is governed by the laws of the State of Oregon.",
        "31.1 The parties submit to the exclusive jurisdiction of the Oregon courts.",
        "31.2 Sales tax is charged at the rate applicable in the delivery jurisdiction.",
        "32.1 This Agreement may be executed in counterparts.",
        "33.1 Schedules A and B form part of this Agreement.",
        "34.1 Signed for and on behalf of the parties by their authorised representatives.",
    ]
)


#: Schedules A and B. These exist to make the agreement a realistic length -- a
#: four-page contract is the point of the fixture -- and they sit AFTER the clauses
#: so clause 27.4 stays buried in the middle rather than drifting to the last page,
#: where a model that reads only the head and tail would find it.
_CONTRACT_SCHEDULES = tuple(
    ["SCHEDULE A - DEFINITIONS"]
    + [
        f"A.{i} \"{term}\" has the meaning given to it in clause {i}."
        for i, term in enumerate(
            [
                "Affiliate", "Agreement", "Business Day", "Change Request",
                "Confidential Information", "Customer Data", "Deliverable",
                "Effective Date", "Fees", "Force Majeure Event", "Good Industry Practice",
                "Intellectual Property Rights", "Personal Data", "Services",
                "Statement of Work", "Term", "Working Hours", "Acceptance Criteria",
                "Milestone", "Service Credit", "Supplier Personnel", "Third Party Software",
            ],
            start=1,
        )
    ]
    + ["", "SCHEDULE B - SERVICE LEVELS AND NOTICES"]
    + [
        f"B.{i} {line}"
        for i, line in enumerate(
            [
                "Target availability for the hosted components is 99.5% per calendar month.",
                "Availability excludes scheduled maintenance notified 5 Business Days ahead.",
                "A Priority 1 incident is responded to within 1 Working Hour.",
                "A Priority 2 incident is responded to within 4 Working Hours.",
                "A Priority 3 incident is responded to within 2 Business Days.",
                "Service Credits accrue at 2% of the monthly Fee per full point below target.",
                "Service Credits are the Customer's sole financial remedy for downtime.",
                "The Supplier reports against these levels monthly in arrears.",
                "Notices to the Supplier: 400 Willamette Ave, Portland, OR 97204.",
                "Notices to the Customer: 1900 Ironline Way, Beaverton, OR 97005.",
                "Notices sent by email are effective on acknowledgement only.",
                "Escalation contact for the Supplier is the Account Director.",
                "Escalation contact for the Customer is the Head of Procurement.",
                "This Schedule does not vary any clause of the Agreement.",
            ],
            start=1,
        )
    ]
)

CONTRACT = LongDoc(
    key="lc_contract",
    title="MASTER SERVICES AGREEMENT",
    doc_type="CONTRACT",
    party="Redwood Facilities Group",
    header=(
        "Agreement number: MSA-RFG-2026-014",
        "Between: Redwood Facilities Group (the Supplier)",
        "And: Ironline Equipment Inc (the Customer)",
        "Effective date: 2026-01-15",
        "Term: 36 months",
    ),
    columns="",
    rows=(),
    clauses=_CONTRACT_CLAUSES + _CONTRACT_SCHEDULES,
    footer=("Signed: R. Ellery, Director", "Signed: M. Okonjo, VP Operations"),
    buried_fact="1.5% per month",
    min_pages=4,
    ground_truth={
        "late_payment_interest": "1.5% per month",
        "late_payment_clause": "27.4",
        "decoy_percentage": "2.0% prompt-payment discount (clause 12.1)",
        "payment_terms_days": 45,
        "governing_law": "State of Oregon",
        "liability_cap": "fees paid in the preceding 12 months",
    },
)


# --- 2. three-page statement of account -------------------------------------
# 45 lines. Exactly one is unmatched, and it sits at line 38 -- on the last page.
def _statement_rows() -> tuple[tuple[str, ...], list[dict]]:
    rows, truth = [], []
    for i in range(1, 71):
        number = f"BRL-20{1000 + i}"
        amount = Decimal("485.00") + Decimal(i) * Decimal("37.15")
        rows.append(f"{number:<16} 2026-0{(i % 9) + 1}-1{i % 9}   {_money(amount):>12}")
        truth.append({"invoice_number": number, "amount": _money(amount)})
    return tuple(rows), truth


_STATEMENT_ROWS, _STATEMENT_TRUTH = _statement_rows()
#: The one line the Customer has no invoice for. Line 62 of 70 -> final page.
_STATEMENT_UNMATCHED = _STATEMENT_TRUTH[61]

STATEMENT = LongDoc(
    key="lc_statement",
    title="STATEMENT OF ACCOUNT",
    doc_type="STATEMENT",
    party="Blue Ridge Logistics",
    header=(
        "Statement number: SOA-BRL-2026-09",
        "Account: Ironline Equipment Inc",
        "Period: 2026-01-01 to 2026-09-30",
        "Lines on this statement: 70",
    ),
    columns=f"{'Invoice':<16} {'Date':<12} {'Amount USD':>12}",
    rows=_STATEMENT_ROWS,
    footer=(
        f"Total of 70 lines: USD {_money(sum(Decimal(t['amount'].replace(',', '')) for t in _STATEMENT_TRUTH))}",
        "Queries to accounts@blueridgelogistics.example",
    ),
    buried_fact=_STATEMENT_UNMATCHED["invoice_number"],
    min_pages=3,
    ground_truth={
        "line_count": 70,
        "unmatched_invoice": _STATEMENT_UNMATCHED["invoice_number"],
        "unmatched_amount": _STATEMENT_UNMATCHED["amount"],
        "first_invoice": _STATEMENT_TRUTH[0]["invoice_number"],
        "last_invoice": _STATEMENT_TRUTH[-1]["invoice_number"],
    },
)


# --- 3 & 4. two long purchase orders ----------------------------------------
def _po_rows(prefix: str, count: int, bad_line: int, bad_unit: Decimal):
    rows, truth, total = [], [], Decimal("0.00")
    for i in range(1, count + 1):
        qty = 5 + (i % 7)
        unit = bad_unit if i == bad_line else Decimal("18.40") + Decimal(i % 11)
        amount = Decimal(qty) * unit
        total += amount
        desc = f"{prefix} component {i:03d}"
        rows.append(
            f"{i:>3}  {desc:<28} {qty:>4} x {_money(unit):>9} = {_money(amount):>11}"
        )
        truth.append({"line": i, "description": desc, "qty": qty,
                      "unit_price": _money(unit), "amount": _money(amount)})
    return tuple(rows), truth, total


_PO_A_ROWS, _PO_A_TRUTH, _PO_A_TOTAL = _po_rows("Hydraulic", 60, 47, Decimal("212.75"))

PO_ALPHA = LongDoc(
    key="lc_po_alpha",
    title="PURCHASE ORDER",
    doc_type="PURCHASE_ORDER",
    party="Summit Office Supplies",
    header=(
        "PO number: PO-SOS-2026-4471",
        "Supplier: Summit Office Supplies",
        "Buyer: Ironline Equipment Inc",
        "Order date: 2026-04-02",
        "Line items: 60",
    ),
    columns=f"{'#':>3}  {'Description':<28} {'Qty':>4}   {'Unit':>9}   {'Amount':>11}",
    rows=_PO_A_ROWS,
    footer=(f"Order total: USD {_money(_PO_A_TOTAL)}", "Delivery: DAP Portland, OR"),
    #: line 47 is priced an order of magnitude above every other line
    buried_fact=_PO_A_TRUTH[46]["unit_price"],
    min_pages=3,
    ground_truth={
        "line_count": 60,
        "order_total": _money(_PO_A_TOTAL),
        "outlier_line": 47,
        "outlier_unit_price": _PO_A_TRUTH[46]["unit_price"],
        "outlier_amount": _PO_A_TRUTH[46]["amount"],
        "typical_unit_price_range": "18.40 to 28.40",
    },
)

_PO_B_ROWS, _PO_B_TRUTH, _PO_B_TOTAL = _po_rows("Fastener", 55, 0, Decimal("0"))

PO_BETA = LongDoc(
    key="lc_po_beta",
    title="PURCHASE ORDER",
    doc_type="PURCHASE_ORDER",
    party="Apex Print Solutions",
    header=(
        "PO number: PO-APS-2026-8820",
        "Supplier: Apex Print Solutions",
        "Buyer: Ironline Equipment Inc",
        "Order date: 2026-05-19",
        "Line items: 55",
    ),
    columns=f"{'#':>3}  {'Description':<28} {'Qty':>4}   {'Unit':>9}   {'Amount':>11}",
    rows=_PO_B_ROWS,
    footer=(
        f"Order total: USD {_money(_PO_B_TOTAL)}",
        "Delivery terms: partial shipments are NOT permitted under this order.",
        "Freight: prepaid and added.",
    ),
    #: the decisive term is the very last footer line, after 55 rows
    buried_fact="partial shipments are NOT permitted",
    min_pages=3,
    ground_truth={
        "line_count": 55,
        "order_total": _money(_PO_B_TOTAL),
        "partial_shipments_allowed": False,
        "freight": "prepaid and added",
    },
)


# --- 5. long delivery note --------------------------------------------------
def _delivery_rows():
    rows, truth, short = [], [], []
    for i in range(1, 71):
        ordered = 20 + (i % 9)
        delivered = ordered - 3 if i in (11, 29, 63) else ordered
        desc = f"CNC machined part {i:03d}"
        rows.append(f"{i:>3}  {desc:<26} ordered {ordered:>3}   delivered {delivered:>3}")
        entry = {"line": i, "description": desc, "ordered": ordered, "delivered": delivered}
        truth.append(entry)
        if delivered != ordered:
            short.append(entry)
    return tuple(rows), truth, short


_DN_ROWS, _DN_TRUTH, _DN_SHORT = _delivery_rows()

DELIVERY_NOTE = LongDoc(
    key="lc_delivery_note",
    title="DELIVERY NOTE",
    doc_type="DELIVERY_NOTE",
    party="Cascade Manufacturing Co",
    header=(
        "Delivery note: DN-CMC-2026-3390",
        "Against PO: PO-88342",
        "Supplier: Cascade Manufacturing Co",
        "Delivered to: Ironline Equipment Inc",
        "Lines: 70",
    ),
    columns=f"{'#':>3}  {'Description':<26} {'Ordered':>10}   {'Delivered':>10}",
    rows=_DN_ROWS,
    footer=("Received by: J. Alvarez", "Condition: goods received in good order"),
    #: the LAST short-shipped line, as it literally appears in the document
    buried_fact=_DN_ROWS[62],
    min_pages=3,
    ground_truth={
        "line_count": 70,
        "po_number": "PO-88342",
        "short_shipped_lines": [s["line"] for s in _DN_SHORT],
        "short_shipped_count": len(_DN_SHORT),
        "shortfall_per_line": 3,
    },
)


LONG_DOCS: tuple[LongDoc, ...] = (CONTRACT, STATEMENT, PO_ALPHA, PO_BETA, DELIVERY_NOTE)
LONG_DOCS_BY_KEY = {d.key: d for d in LONG_DOCS}


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

#: Body lines per page at the 8.6pt/15.5pt leading `render_pdf` uses on US Letter.
#: The parse test asserts each document still clears its `min_pages` floor, so this
#: cannot be raised without the fixtures being re-checked.
LINES_PER_PAGE = 30


def page_layout(doc: LongDoc) -> list[list[str]]:
    """The document as a list of pages, each a list of lines.

    Pure and reportlab-free, so the page count and what sits on which page can be
    asserted without generating a PDF -- which is what makes `buried_on_page`
    testable in the unit suite.
    """
    body: list[str] = []
    body.extend(doc.header)
    body.append("")
    if doc.columns:
        body.append(doc.columns)
    body.extend(doc.rows)
    if doc.clauses:
        body.extend(doc.clauses)
    body.append("")
    body.extend(doc.footer)

    pages, current = [], [doc.title]
    for line in body:
        if len(current) >= LINES_PER_PAGE:
            pages.append(current)
            current = [f"{doc.title} (continued)"]
        current.append(line)
    if current:
        pages.append(current)
    return pages


def page_of(doc: LongDoc, needle: str) -> Optional[int]:
    """1-based page number containing `needle`, or None."""
    for index, page in enumerate(page_layout(doc), 1):
        if any(needle in line for line in page):
            return index
    return None


def render_pdf(doc: LongDoc, path: str) -> str:
    """Write `doc` to a real multi-page PDF. reportlab imported lazily."""
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(path, pagesize=letter)
    for page in page_layout(doc):
        y = 750
        for i, line in enumerate(page):
            bold = i == 0
            c.setFont("Helvetica-Bold" if bold else "Helvetica", 13 if bold else 8.6)
            c.drawString(46, y, line)
            y -= 20 if bold else 15.5
        c.showPage()
    c.save()
    return path


def build_long_documents(docs_dir: str) -> dict[str, str]:
    """Generate all five, `{key: path}`. Regenerated rather than committed, for the
    same reason the probe regenerates its eight: the figures in them are ground
    truth, and a committed binary drifts from the module that describes it."""
    import os

    os.makedirs(docs_dir, exist_ok=True)
    return {d.key: render_pdf(d, os.path.join(docs_dir, f"{d.key}.pdf")) for d in LONG_DOCS}


__all__ = [
    "CONTRACT",
    "DELIVERY_NOTE",
    "LINES_PER_PAGE",
    "LONG_DOCS",
    "LONG_DOCS_BY_KEY",
    "LongDoc",
    "PO_ALPHA",
    "PO_BETA",
    "STATEMENT",
    "build_long_documents",
    "page_layout",
    "page_of",
    "render_pdf",
]
