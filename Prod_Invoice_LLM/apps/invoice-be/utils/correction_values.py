"""Reading a human correction into the value that gets stored.

Shared by `routers/audit.py` and `routers/outbound_audit.py`. Every function either
returns the value to store or raises `ValueError` saying what is wrong, so a
correction is never silently dropped, wrapped or guessed.
"""
import json
import math
import re
from datetime import date, datetime
from typing import Any, Type, get_args

from pydantic import BaseModel, ValidationError

_CURRENCY_SYMBOLS = ("₹", "$", "€", "£", "¥")
_CURRENCY_CODE = re.compile(r"^[A-Za-z]{3}\s+|\s+[A-Za-z]{3}$")
# Western (1,250,000.50) or Indian (12,50,000.50) grouping; anything else with a comma is refused.
_GROUPED_NUMBER = re.compile(r"[+-]?\d{1,3}(,\d{2,3})*(\.\d+)?")
_NUMERIC_DATE = re.compile(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})")
# BE Gap 670: the worker reads printed document dates with this same parser, so the
# forms below are additive -- nothing that was refused before is now guessed.
_YEAR_FIRST_DATE = re.compile(r"(\d{4})[/.-](\d{1,2})[/.-](\d{1,2})")
_TRAILING_TIME = re.compile(r"\s+\d{1,2}:\d{2}(:\d{2})?(\s*[AaPp][Mm])?$")
_ORDINAL_DAY = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)\b", re.IGNORECASE)
_SEPT = re.compile(r"\bsept\b", re.IGNORECASE)
_WORD_DATE_FORMATS = (
    "%d %b %Y", "%d %B %Y", "%b %d %Y", "%B %d %Y",
    "%d-%b-%Y", "%d-%B-%Y", "%b-%d-%Y", "%B-%d-%Y",
)


def is_blank(raw_value: Any) -> bool:
    """BE Gap 532: a correction value that means "empty" — None, or text that is only whitespace."""
    return raw_value is None or (isinstance(raw_value, str) and not raw_value.strip())


def parse_money(raw_value: Any) -> float:
    """BE Gaps 530/533: an amount as typed by a person — "$1,250.60", "₹12,50,000", "(500.00)" — or ValueError.

    Negative amounts are valid (credit notes). Ambiguous formats such as "1.250,50" are refused, never guessed.
    """
    if isinstance(raw_value, bool):
        raise ValueError("not an amount")
    if isinstance(raw_value, (int, float)):
        value = float(raw_value)
    else:
        text = str(raw_value).strip()
        negative = text.startswith("(") and text.endswith(")")
        if negative:
            text = text[1:-1].strip()
        text = _CURRENCY_CODE.sub("", text)
        for symbol in _CURRENCY_SYMBOLS:
            text = text.replace(symbol, "")
        text = text.replace(" ", "")
        if "," in text:
            if not _GROUPED_NUMBER.fullmatch(text):
                raise ValueError("unrecognised number format — use digits with an optional decimal point, e.g. 1250.50")
            text = text.replace(",", "")
        value = float(text)
        if negative:
            value = -value
    if not math.isfinite(value):
        raise ValueError("not a finite number")
    return value


def parse_date(raw_value: Any) -> date:
    """BE Gap 530: a date as typed by a person, or ValueError. A day/month order that could be read two ways is refused."""
    if isinstance(raw_value, datetime):
        return raw_value.date()
    if isinstance(raw_value, date):
        return raw_value
    text = str(raw_value).strip()
    try:
        return date.fromisoformat(text.split("T")[0].split(" ")[0])
    except ValueError:
        pass
    # BE Gap 670: a time printed after the date ("15/09/2026 10:30") is not part of it.
    text = _TRAILING_TIME.sub("", text)
    year_first = _YEAR_FIRST_DATE.fullmatch(text)
    if year_first:
        return date(int(year_first[1]), int(year_first[2]), int(year_first[3]))
    numeric = _NUMERIC_DATE.fullmatch(text)
    if numeric:
        first, second, year = int(numeric[1]), int(numeric[2]), int(numeric[3])
        if first > 12 >= second:
            return date(year, second, first)
        if second > 12 >= first:
            return date(year, first, second)
        if first == second:
            return date(year, first, second)
        raise ValueError(f"'{text}' could be day/month or month/day — use YYYY-MM-DD")
    # BE Gap 670: "15th September, 2026", "15 Sept 2026" -- the ordinal and the four-letter
    # abbreviation carry nothing once the day and month are read.
    words = " ".join(_SEPT.sub("Sep", _ORDINAL_DAY.sub(r"\1", text.replace(",", " "))).split())
    for fmt in _WORD_DATE_FORMATS:
        try:
            return datetime.strptime(words, fmt).date()
        except ValueError:
            continue
    raise ValueError("unrecognised date — use YYYY-MM-DD")


def parse_entries(raw_value: Any, entry_model: Type[BaseModel], entry_name: str) -> list[dict]:
    """BE Gaps 531/534: a list correction (line items, tax lines, addresses, …) whose every entry is valid for `entry_model`."""
    entries = raw_value
    if isinstance(raw_value, str):
        try:
            entries = json.loads(raw_value)
        except json.JSONDecodeError:
            raise ValueError(f"must be a list of {entry_name} entries, not plain text") from None
    if not isinstance(entries, list):
        raise ValueError(f"must be a list of {entry_name} entries")

    cleaned: list[dict] = []
    for index, entry in enumerate(entries, start=1):
        try:
            model = entry_model.model_validate(entry)
        except ValidationError as e:
            first = e.errors()[0]
            where = ".".join(str(part) for part in first["loc"]) or entry_name
            raise ValueError(f"{entry_name} {index}: {where} — {first['msg']}") from None
        values = model.model_dump(exclude_unset=True)
        for key, value in values.items():
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError(f"{entry_name} {index}: {key} — not a finite number")
        cleaned.append(values)
    return cleaned


def list_entry_model(schema: Type[BaseModel], field: str) -> Type[BaseModel]:
    """BE Gap 531: the entry model a schema's `List[...]` field really uses, read from the field itself.

    Read from the field rather than imported by class name, so the correction always validates against the
    model the schema really uses: `agents/extraction_agent.py` once defined `DeductionItem` twice and a
    by-name import got the remittance-advice model (fixed by BE Gap 567; this stays the robust way).
    """
    return get_args(schema.model_fields[field].annotation)[0]


def parse_line_items(raw_value: Any, item_model: Type[BaseModel]) -> list[dict]:
    """BE Gap 534: every entry must be a valid line item for `item_model`."""
    return parse_entries(raw_value, item_model, "line item")


_CURRENCY_ISO_CODE = re.compile(r"[A-Z]{3}")


def parse_currency(raw_value: Any) -> str:
    """BE Gap 531: a 3-letter ISO 4217 code ("eur" is stored as "EUR"), or ValueError."""
    code = raw_value.strip().upper() if isinstance(raw_value, str) else ""
    if not _CURRENCY_ISO_CODE.fullmatch(code):
        raise ValueError("use a 3-letter currency code, e.g. INR, USD, EUR")
    return code


def parse_percent(raw_value: Any) -> float:
    """BE Gap 531: a percentage from 0 to 100 ("12.5" or "12.5%"), or ValueError."""
    if isinstance(raw_value, bool):
        raise ValueError("not a percentage")
    if isinstance(raw_value, (int, float)):
        value = float(raw_value)
    else:
        try:
            value = float(str(raw_value).strip().removesuffix("%").strip())
        except ValueError:
            raise ValueError("not a percentage — use a number such as 12.5") from None
    if not math.isfinite(value) or not 0 <= value <= 100:
        raise ValueError("a percentage must be between 0 and 100")
    return value


def parse_tags(raw_value: Any) -> list[str]:
    """BE Gap 531: tags as a list of words or comma-separated text ("it, hardware"); blanks and repeats dropped, order kept."""
    tags = raw_value
    if isinstance(raw_value, str):
        text = raw_value.strip()
        if text.startswith("["):
            try:
                tags = json.loads(text)
            except json.JSONDecodeError:
                raise ValueError("tags must be a list of words") from None
        else:
            tags = text.split(",")
    if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
        raise ValueError("tags must be a list of words")
    return list(dict.fromkeys(tag.strip() for tag in tags if tag.strip()))
