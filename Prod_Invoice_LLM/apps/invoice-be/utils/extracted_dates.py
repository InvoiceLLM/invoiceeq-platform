"""BE Gap 670: turning a date the extractor read off a document into a stored date.

Before this, every worker write site parsed with `strptime(..., "%Y-%m-%d")` inside a
bare `except` and left the column NULL for any other printed format. The reviewer saw
a blank date with nothing saying the document printed one.

Now there is ONE deterministic parser, `utils.correction_values.parse_date` (the same
one the audit correction screens use), and this module only adds what a document
needs on top of it: when the parser cannot read a value -- unrecognised, or a numeric
date whose day/month order reads two ways, such as 05/06/2026 -- the date stays empty,
nothing is guessed, and an `unreadable_date` alert carries the printed text.

What the caller does with the alert (send to review) is decided at the write site
(founder ruling D1, 2026-09-17).
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Optional, Tuple

from utils.correction_values import is_blank, parse_date

logger = logging.getLogger(__name__)

DATE_ALERT_TYPE = "unreadable_date"

_FIELD_LABELS = {
    "invoice_date": "invoice date",
    "due_date": "due date",
    "doc_date": "document date",
    "valid_until": "valid-until date",
}


def parse_extracted_date(raw_value: Any, field_name: str = "invoice_date") -> Tuple[Optional[date], Optional[dict]]:
    """Return `(date, None)`, `(None, None)` for an empty value, or `(None, alert)` when unreadable."""
    if is_blank(raw_value):
        return None, None
    try:
        return parse_date(raw_value), None
    except (ValueError, TypeError, OverflowError) as exc:
        label = _FIELD_LABELS.get(field_name, field_name.replace("_", " "))
        printed = str(raw_value).strip()[:80]
        # parse_date's reasons end with typing advice meant for the correction
        # screen ("— use YYYY-MM-DD"); on a document alert only the reason fits.
        reason = str(exc).split(" — use ")[0]
        logger.warning("BE Gap 670: could not read printed %s %r (%s)", field_name, printed, reason)
        return None, {
            "type": DATE_ALERT_TYPE,
            "field": field_name,
            "severity": "warning",
            "message": f"The printed {label} '{printed}' could not be read ({reason}). Enter it manually.",
        }
