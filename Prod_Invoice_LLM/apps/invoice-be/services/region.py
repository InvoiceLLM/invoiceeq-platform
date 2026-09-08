"""Feature 30 task 30.0d — which country's rules apply to THIS document.

Region is a property of the document, not of the tenant. An Indian tenant is
routinely sent a EU supplier's invoice, and applying CBIC rule cards to it would
produce compliance findings that are simply wrong. So the answer is derived from
what is printed on the page — a GSTIN, a VAT id — and stored on the attachment
row (`ChatAttachment.region`), next to the document it describes.

The order of the checks is the whole design:

  1. **GSTIN** -> IN. A 15-character checksum-shaped id that no other regime
     issues, so it is decided first and never overridden.
  2. **VAT id** -> EU. Two-letter country code from the EU/EEA set plus 8-12
     alphanumerics. The country-code allow-list is what stops "IN123456789"
     (an Indian party writing a non-GST id) and "US..." from being read as EU.
  3. **EIN / ZIP + state** -> US.
  4. Otherwise **None** — and None means "we do not know", never "US". A rule
     card that fires by default is a rule card that fires on the wrong
     documents; §8.9's own check is "neither -> None".

Deterministic and offline (hard rule 3): regexes over the extracted JSON, no
model call and no lookup service.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Optional

REGION_IN = "IN"
REGION_EU = "EU"
REGION_US = "US"

#: 2 digits (state) + 10-char PAN + 1 entity digit + "Z" + 1 checksum char.
#: Anchored on the PAN shape rather than on "15 alphanumerics", which would also
#: match half the reference numbers on a delivery note.
GSTIN_PATTERN = re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z]\d[A-Z][0-9A-Z]\b")

#: EU/EEA VAT country prefixes. "EL" is Greece's VAT prefix (not "GR"), "XI" is
#: Northern Ireland post-Brexit; both are real and both are missed by anyone who
#: generates this list from ISO country codes.
_EU_VAT_PREFIXES = (
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "EL",
    "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK",
    "SI", "ES", "SE", "XI",
)
VAT_PATTERN = re.compile(
    r"\b(" + "|".join(_EU_VAT_PREFIXES) + r")[ -]?([0-9A-Z]{8,12})\b"
)

#: US employer identification number, 2 digits + hyphen + 7.
EIN_PATTERN = re.compile(r"\b\d{2}-\d{7}\b")
#: A US ZIP immediately after a two-letter state, which is how a US address
#: prints. A bare 5-digit number is not evidence of anything.
US_STATE_ZIP_PATTERN = re.compile(r"\b[A-Z]{2}\s+\d{5}(?:-\d{4})?\b")

#: Where an id is likely to be. Searched in this order, then the whole document
#: as a fallback — a tax id printed inside an address block is still a tax id.
_ID_FIELDS = (
    "tax_ids",
    "regional_ids",
    "compliance_metadata",
    "party_tax_id",
    "vendor_tax_id",
    "gstin",
    "vat_id",
    "addresses",
    "party_address",
)


def _texts(value: Any) -> Iterable[str]:
    """Every string inside an arbitrarily nested extraction structure."""
    if value is None:
        return
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _texts(v)
    elif isinstance(value, (list, tuple, set)):
        for v in value:
            yield from _texts(v)
    elif isinstance(value, (int, float)):
        yield str(value)


def detect_region(extracted_json: Optional[dict], ocr_text: str | None = None) -> Optional[str]:
    """"IN" / "EU" / "US" / None for one document.

    `ocr_text` is optional and searched last: a tax id that the extractor did not
    lift into a field is still printed on the page, and the compliance cards are
    the one consumer that would rather read the raw text than skip the check.
    Never raises — an unparseable document is `None`, which every caller already
    has to handle as "checks not run".
    """
    haystacks: list[str] = []
    data = extracted_json or {}

    for field in _ID_FIELDS:
        if field in data:
            haystacks.extend(_texts(data[field]))
    # Then the whole extraction, then the raw text.
    haystacks.extend(_texts(data))
    if ocr_text:
        haystacks.append(str(ocr_text))

    blob = " ".join(h.upper() for h in haystacks if h)
    if not blob:
        return None

    if GSTIN_PATTERN.search(blob):
        return REGION_IN
    if VAT_PATTERN.search(blob):
        return REGION_EU
    if EIN_PATTERN.search(blob) or US_STATE_ZIP_PATTERN.search(blob):
        return REGION_US
    return None


def set_attachment_region(row: Any, db_session: Any, ocr_text: str | None = None) -> Optional[str]:
    """Detect and persist the region for one `ChatAttachment`. Returns it.

    Best-effort: a failure leaves `region` as it was (usually None) and does not
    fail the extraction that called it, because region only decides which
    OPTIONAL compliance cards run.
    """
    try:
        region = detect_region(row.extracted_json, ocr_text)
        if region != row.region:
            row.region = region
            db_session.add(row)
            db_session.commit()
            db_session.refresh(row)
        return region
    except Exception:  # pragma: no cover - defensive
        try:
            db_session.rollback()
        except Exception:
            pass
        return None
