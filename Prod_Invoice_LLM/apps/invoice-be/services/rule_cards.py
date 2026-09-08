"""Feature 30 tasks 30.9-30.11 — regional rule cards and their deterministic checks.

WHAT A RULE CARD IS
-------------------
A markdown file under `knowledge/rule_cards/{in,eu,us}/` with YAML front matter:

    ---
    id: in-credit-note-original-reference
    region: IN
    title: A credit note must identify the invoice it adjusts
    source_url: https://.../section-34
    source_title: CGST Act, section 34
    fetched_at: 2026-09-08
    effective_from: 2017-07-01
    review_at: 2026-12-31
    owner: founder
    applies_to_doc_types: [CREDIT_NOTE]
    verify: credit_note_references_invoice
    status: verified
    ---
    One paragraph, in the user's words, quoting the source.

**`status` is the honesty field, and hard rule 8 is why it exists.** A card whose
primary source was actually fetched and read is `verified` and may be shown with
its citation. A card written from memory is `unverified`: it carries the
`source_url` it OUGHT to be checked against, has NO rule text, and
`load_rule_cards()` will not return it for display. Inventing the text of a tax
rule is the single worst thing this feature could do — it would be a confident,
citable-looking statement about the law that nobody checked.

WHAT A `verify` IS
------------------
The name of a function in `CHECKS` below. Every check is deterministic Python
over the extracted document: a field is present or it is not, a reference is
there or it is not. **No check asks a model whether a document complies** — the
card supplies the rule and the citation, the code supplies the verdict.

A card may have `verify: null`, and that is a real state: the rule is worth
showing ("keep this for six years") but nothing in the document can be checked
against it. Those cards are surfaced as `informational`, never as a pass.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Sequence

logger = logging.getLogger(__name__)

#: Where the cards live. One directory per region, lower-cased, so a card's
#: region is visible from its path as well as from its front matter.
RULE_CARD_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "knowledge", "rule_cards"
)

STATUS_VERIFIED = "verified"
STATUS_UNVERIFIED = "unverified"

#: Every field a card must declare. A card missing one of these is a
#: half-written card, and a half-written compliance rule is worse than none:
#: `load_rule_cards()` logs and skips it rather than showing a rule with no
#: source or no scope.
REQUIRED_FIELDS = (
    "id", "region", "title", "source_url", "applies_to_doc_types", "status",
)


@dataclass
class RuleCard:
    """One rule, its provenance and the check that tests it."""

    id: str
    region: str
    title: str
    source_url: str
    applies_to_doc_types: tuple
    status: str = STATUS_UNVERIFIED
    body: str = ""
    source_title: str = ""
    fetched_at: str = ""
    effective_from: str = ""
    review_at: str = ""
    owner: str = ""
    verify: Optional[str] = None
    path: str = ""

    @property
    def is_showable(self) -> bool:
        """May this card be put in front of a user?

        Only when someone actually fetched the source. See the module docstring.
        """
        return self.status == STATUS_VERIFIED and bool(self.body.strip())

    def applies_to(self, doc_type: Optional[str]) -> bool:
        if not doc_type:
            return False
        return doc_type.strip().upper() in {t.upper() for t in self.applies_to_doc_types}


# ---------------------------------------------------------------------------
# The checks (30.11)
# ---------------------------------------------------------------------------
#
# Each takes `(data, row)` -- the extracted JSON and the attachment row -- and
# returns `(outcome, detail)` where outcome is "pass" | "fail" | "not_applicable".
#
# "not_applicable" is a first-class answer and never a silent pass: a check that
# cannot run because the document does not carry the field must say so, or the
# compliance card reads as "we checked and it was fine" when nothing was checked.


def _texts(data: dict) -> str:
    import json

    try:
        return json.dumps(data, default=str).lower()
    except Exception:  # pragma: no cover - defensive
        return str(data).lower()


def credit_note_references_invoice(data: dict, row: Any) -> tuple:
    """A credit or debit note must identify the invoice it adjusts."""
    refs = data.get("referenced_documents") or []
    numbered = [r for r in refs if isinstance(r, dict) and (r.get("doc_number") or "").strip()]
    if numbered:
        return "pass", f"references {', '.join(str(r['doc_number']) for r in numbered[:3])}"
    # A note may print the reference in prose rather than in a list.
    if re.search(r"\b(against|ref|reference|adjust\w*)\b.{0,40}\b[A-Z]{2,}[-/ ]?\d{2,}", str(data.get("notes") or ""), re.I):
        return "pass", "the note names the original document in its remarks"
    return "fail", "this note does not name the invoice it adjusts"


def gstin_present(data: dict, row: Any) -> tuple:
    """An Indian tax document must carry a GSTIN."""
    from services.region import GSTIN_PATTERN

    if GSTIN_PATTERN.search(_texts(data).upper()):
        return "pass", "a GSTIN is printed on the document"
    return "fail", "no GSTIN is printed on this document"


def hsn_code_present(data: dict, row: Any) -> tuple:
    """Indian GST line items carry an HSN/SAC code."""
    items = data.get("items") or []
    if not items:
        return "not_applicable", "this document has no line items"
    with_code = [i for i in items if isinstance(i, dict) and (i.get("hsn_sac_code") or "")]
    if not with_code:
        return "fail", f"none of the {len(items)} lines carry an HSN/SAC code"
    if len(with_code) < len(items):
        return "fail", f"{len(items) - len(with_code)} of {len(items)} lines have no HSN/SAC code"
    return "pass", "every line carries an HSN/SAC code"


def vat_id_present(data: dict, row: Any) -> tuple:
    """A EU cross-border document must carry a VAT identification number."""
    from services.region import VAT_PATTERN

    if VAT_PATTERN.search(_texts(data).upper()):
        return "pass", "a VAT identification number is printed on the document"
    return "fail", "no VAT identification number is printed on this document"


def reverse_charge_flagged(data: dict, row: Any) -> tuple:
    """A reverse-charge supply must say so on its face."""
    blob = _texts(data)
    if "reverse charge" in blob or "reverse-charge" in blob:
        return "pass", "the document states that reverse charge applies"
    tax = data.get("tax_amount")
    if tax in (None, 0, 0.0) and (data.get("grand_total") or 0):
        return "fail", "no tax is charged and the document does not say reverse charge applies"
    return "not_applicable", "tax is charged, so no reverse-charge wording is expected"


def payment_terms_stated(data: dict, row: Any) -> tuple:
    """A contract or order should state when payment is due."""
    if (data.get("payment_terms") or "").strip():
        return "pass", f"payment terms are stated: {data['payment_terms']}"
    return "fail", "this document does not state when payment is due"


def document_number_present(data: dict, row: Any) -> tuple:
    """Every commercial document needs its own identifier."""
    if (getattr(row, "doc_number", None) or data.get("doc_number") or "").strip():
        return "pass", "the document carries its own number"
    return "fail", "this document prints no number of its own"


def supplier_address_present(data: dict, row: Any) -> tuple:
    """A US sales document should identify the supplier's place of business."""
    blob = _texts(data)
    if data.get("addresses") or re.search(r"\b[a-z]{2}\s+\d{5}(-\d{4})?\b", blob):
        return "pass", "a supplier address is printed"
    return "fail", "no supplier address is printed on this document"


#: The only functions a card may name. A card whose `verify` is not in here is
#: loaded and shown, but its check reports `not_applicable` with that as the
#: reason — a typo in a card must not silently become a pass.
CHECKS: dict = {
    "credit_note_references_invoice": credit_note_references_invoice,
    "gstin_present": gstin_present,
    "hsn_code_present": hsn_code_present,
    "vat_id_present": vat_id_present,
    "reverse_charge_flagged": reverse_charge_flagged,
    "payment_terms_stated": payment_terms_stated,
    "document_number_present": document_number_present,
    "supplier_address_present": supplier_address_present,
}


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

_FRONT_MATTER = re.compile(r"^---\s*\n(?P<yaml>.*?)\n---\s*\n?(?P<body>.*)$", re.S)


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        return tuple(v.strip().strip("'\"") for v in value[1:-1].split(",") if v.strip())
    if value.lower() in ("null", "none", "~", ""):
        return None
    return value.strip("'\"")


def parse_rule_card(text: str, path: str = "") -> Optional[RuleCard]:
    """One markdown file -> a `RuleCard`, or None if it is not a valid card.

    A hand-rolled front-matter parser rather than PyYAML: the front matter is
    five to ten flat keys, PyYAML is not currently a dependency of this app, and
    adding one to read a file this simple is not a trade worth making.
    """
    match = _FRONT_MATTER.match(text or "")
    if not match:
        return None

    fields: dict = {}
    for line in match.group("yaml").splitlines():
        if not line.strip() or line.strip().startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        fields[key.strip()] = _parse_scalar(value)

    missing = [f for f in REQUIRED_FIELDS if not fields.get(f)]
    if missing:
        logger.warning("Rule card %s is missing %s; skipped", path or "<inline>", missing)
        return None

    applies = fields.get("applies_to_doc_types")
    if isinstance(applies, str):
        applies = tuple(t.strip() for t in applies.split(",") if t.strip())

    return RuleCard(
        id=str(fields["id"]),
        region=str(fields["region"]).upper(),
        title=str(fields["title"]),
        source_url=str(fields["source_url"]),
        applies_to_doc_types=tuple(applies or ()),
        status=str(fields.get("status") or STATUS_UNVERIFIED).lower(),
        body=(match.group("body") or "").strip(),
        source_title=str(fields.get("source_title") or ""),
        fetched_at=str(fields.get("fetched_at") or ""),
        effective_from=str(fields.get("effective_from") or ""),
        review_at=str(fields.get("review_at") or ""),
        owner=str(fields.get("owner") or ""),
        verify=fields.get("verify"),
        path=path,
    )


def load_rule_cards(
    region: Optional[str] = None, root: Optional[str] = None, include_unverified: bool = False
) -> list:
    """Every card on disk, optionally for one region.

    `include_unverified` defaults False: the display path must never receive a
    card whose source nobody fetched. The seeding script and the review tooling
    pass True, because "which cards still need checking" is exactly the question
    they exist to answer.
    """
    base = root or RULE_CARD_ROOT
    if not os.path.isdir(base):
        return []

    cards: list = []
    for dirpath, _dirnames, filenames in os.walk(base):
        for name in sorted(filenames):
            if not name.endswith(".md"):
                continue
            path = os.path.join(dirpath, name)
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    card = parse_rule_card(fh.read(), path)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Could not read rule card %s: %s", path, exc)
                continue
            if card is None:
                continue
            if region and card.region != region.upper():
                continue
            if not include_unverified and not card.is_showable:
                continue
            cards.append(card)
    return cards


def verify_checks_for(card: RuleCard, data: dict, row: Any) -> dict:
    """Run one card's check against one document.

    Returns `{card_id, title, source_url, outcome, detail}`. `outcome` is
    "pass" | "fail" | "not_applicable" | "informational".
    """
    result = {
        "card_id": card.id,
        "title": card.title,
        "region": card.region,
        "source_url": card.source_url,
        "source_title": card.source_title,
        "effective_from": card.effective_from,
        "verify": card.verify,
    }
    if not card.verify:
        result.update(outcome="informational", detail="this rule is guidance, not a check")
        return result

    check = CHECKS.get(card.verify)
    if check is None:
        # A typo in a card must not become a pass.
        result.update(
            outcome="not_applicable",
            detail=f"this card names a check ({card.verify}) that does not exist",
        )
        return result

    try:
        outcome, detail = check(data or {}, row)
    except Exception as exc:
        logger.error("Rule check %s failed on %s: %s", card.verify, getattr(row, "id", "?"), exc)
        result.update(outcome="not_applicable", detail="this check could not be completed")
        return result
    result.update(outcome=outcome, detail=detail)
    return result


def run_compliance_checks(row: Any, region: Optional[str] = None, root: Optional[str] = None) -> list:
    """Every applicable card's verdict for one attachment, in card-id order."""
    doc_type = str(getattr(row, "doc_type", "") or "").strip().upper()
    region = region or getattr(row, "region", None)
    if not region:
        return []
    cards = [c for c in load_rule_cards(region, root) if c.applies_to(doc_type)]
    data = getattr(row, "extracted_json", None) or {}
    return [verify_checks_for(card, data, row) for card in sorted(cards, key=lambda c: c.id)]
