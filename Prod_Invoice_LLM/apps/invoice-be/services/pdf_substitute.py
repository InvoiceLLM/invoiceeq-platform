"""Feature 17: in-place value substitution on the source invoice PDF.

The "exact copy" half of founder decision D3. The generated PDF *is* the source
PDF with the changed values painted over and reprinted in place, so the logo,
the layout, the fonts and the legal footer survive untouched — which is the
whole reason this feature needs neither a logo upload, nor a template picker,
nor a branding screen.

Locating a value is deterministic and has two sources of truth, in order:

1. `Invoice.coordinates` — the Document Intelligence bounding polygons already
   stored per field at extraction time (Feature 2 / Gap 178), normalised to
   0–100 percentages of the page by `queue_worker/handlers.py::_run_ocr`
   (Gap 330). This is what disambiguates a date printed twice.
2. `page.search_for()` on the printed text.

Neither is an LLM call, and nothing here asks a model whether a substitution is
correct (CONVENTIONS hard rule 3). When a changed value cannot be found, the
field name is returned and the endpoint answers 422 — the builder refuses
rather than silently shipping a PDF that still prints last month's total.
"""
from __future__ import annotations

import logging
import re
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Callable, Iterable

import fitz  # PyMuPDF

from services.invoice_builder import Substitution

logger = logging.getLogger(__name__)

#: Our field names → Azure prebuilt-invoice field names, the keys DI writes
#: into `Invoice.coordinates`. Same mapping `routers/trainer.py`'s
#: `_CONFIDENCE_ALIASES` uses, plus the AR-side `CustomerName`.
DI_FIELD_ALIASES: dict[str, list[str]] = {
    "customer_name": ["CustomerName", "CustomerAddressRecipient"],
    "invoice_number": ["InvoiceId"],
    "invoice_date": ["InvoiceDate"],
    "due_date": ["DueDate"],
    "subtotal": ["SubTotal"],
    "tax_amount": ["TotalTax"],
    "grand_total": ["InvoiceTotal", "AmountDue"],
}

#: Line items get no alias: Document Intelligence emits one polygon for the
#: whole `Items` array, not one per cell, so a per-line value is located by its
#: printed text alone.


# ---------------------------------------------------------------------------
# Number formatting
# ---------------------------------------------------------------------------

_NUM_RE = re.compile(
    r"^(?P<pre>[^0-9-]*)(?P<sign>-?)(?P<num>[0-9][0-9.,\s ']*[0-9]|[0-9])(?P<post>.*)$"
)
_GROUP_CHARS = ".,  '"

#: Fraction of the located rect's height trimmed off the top and the bottom
#: before it is used as a redaction annotation — see `substitute()`.
_REDACT_INSET = 0.15


def format_like(sample: str, value: Decimal) -> str:
    """Render `value` using the separator style and decimal places of `sample`.

    Pure. `format_like("1.250,00", Decimal("2000"))` → `"2.000,00"`;
    `format_like("1,250.00", Decimal("2000"))` → `"2,000.00"`;
    `format_like("1250.00", ...)` → `"2000.00"` (no grouping was observed, so
    none is invented). Any prefix/suffix in the sample (a currency symbol, a
    trailing code) is preserved around the new number.

    A separator followed by exactly three digits is read as grouping, not as a
    decimal point — the standard, and the only reading under which `1.250` and
    `1,250` both mean one thousand two hundred and fifty.
    """
    match = _NUM_RE.match((sample or "").strip())
    if not match:
        dec_sep, grp_sep, places, pre, post = ".", "", 2, "", ""
    else:
        pre, post = match.group("pre"), match.group("post")
        num = match.group("num")
        seps = [(i, c) for i, c in enumerate(num) if c in _GROUP_CHARS]
        dec_sep, grp_sep, places = "", "", 0
        if seps:
            last_i, last_c = seps[-1]
            tail = len(num) - last_i - 1
            if last_c in ".," and 1 <= tail <= 2:
                dec_sep, places = last_c, tail
                others = [c for i, c in seps[:-1]]
            else:
                others = [c for i, c in seps]
            if others:
                grp_sep = others[-1]

    quant = Decimal(1).scaleb(-places)
    q = value.quantize(quant, rounding=ROUND_HALF_UP)
    sign = "-" if q < 0 else ""
    digits = f"{abs(q):f}"
    if "." in digits:
        int_part, frac = digits.split(".", 1)
    else:
        int_part, frac = digits, ""

    if grp_sep:
        chunks = []
        while len(int_part) > 3:
            chunks.insert(0, int_part[-3:])
            int_part = int_part[:-3]
        chunks.insert(0, int_part)
        int_part = grp_sep.join(chunks)

    body = int_part + (dec_sep + frac if places and dec_sep else "")
    return f"{pre}{sign}{body}{post}"


def _number_renderings(value: Decimal) -> list[str]:
    """Every plausible way the source might have printed `value`, most likely
    first. Used as the search list; whichever one the page actually contains
    becomes the `format_like` sample for the replacement."""
    q = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    plain = f"{abs(q):.2f}"
    int_part, frac = plain.split(".")
    sign = "-" if q < 0 else ""

    def grouped(sep: str) -> str:
        chunks, rest = [], int_part
        while len(rest) > 3:
            chunks.insert(0, rest[-3:])
            rest = rest[:-3]
        chunks.insert(0, rest)
        return sep.join(chunks)

    out = [
        f"{sign}{grouped(',')}.{frac}",
        f"{sign}{int_part}.{frac}",
        f"{sign}{grouped('.')},{frac}",
        f"{sign}{int_part},{frac}",
        f"{sign}{grouped(' ')},{frac}",
        f"{sign}{grouped(' ')}.{frac}",
    ]
    if frac == "00":
        out += [f"{sign}{grouped(',')}", f"{sign}{int_part}", f"{sign}{grouped('.')}"]
    # Quantities print as `2` or `2.5` far more often than `2.00`.
    trimmed = f"{q.normalize():f}"
    if trimmed not in out:
        out.append(trimmed)
    seen, unique = set(), []
    for candidate in out:
        if candidate not in seen:
            seen.add(candidate)
            unique.append(candidate)
    return unique


#: Date renderings, as functions so the *same* renderer that matched the source
#: produces the replacement — a source printing `15/07/2026` gets `12/08/2026`
#: back, never an ISO string dropped into a European layout.
_DATE_RENDERERS: list[Callable[[date], str]] = [
    lambda d: d.strftime("%Y-%m-%d"),
    lambda d: d.strftime("%d/%m/%Y"),
    lambda d: d.strftime("%m/%d/%Y"),
    lambda d: d.strftime("%d-%m-%Y"),
    lambda d: d.strftime("%m-%d-%Y"),
    lambda d: d.strftime("%d.%m.%Y"),
    lambda d: d.strftime("%Y/%m/%d"),
    lambda d: f"{d.day}/{d.month}/{d.year}",
    lambda d: f"{d.month}/{d.day}/{d.year}",
    lambda d: d.strftime("%b %d, %Y"),
    lambda d: d.strftime("%d %b %Y"),
    lambda d: d.strftime("%B %d, %Y"),
    lambda d: d.strftime("%d %B %Y"),
    lambda d: f"{d.day} {d.strftime('%B')} {d.year}",
    lambda d: d.strftime("%d/%m/%y"),
    lambda d: d.strftime("%m/%d/%y"),
]


def candidate_renderings(sub: Substitution) -> list[tuple[str, str]]:
    """`(old_text_to_search_for, replacement_text)` pairs for one substitution,
    most likely first. Pure."""
    if sub.kind == "number" and sub.old_value is not None and sub.new_value is not None:
        return [
            (old, format_like(old, sub.new_value))
            for old in _number_renderings(sub.old_value)
        ]
    if sub.kind == "date" and isinstance(sub.old_value, date) and isinstance(sub.new_value, date):
        pairs, seen = [], set()
        for render in _DATE_RENDERERS:
            old = render(sub.old_value)
            if old in seen:
                continue
            seen.add(old)
            pairs.append((old, render(sub.new_value)))
        return pairs
    if not sub.old_text:
        return []
    return [(sub.old_text, sub.new_text)]


# ---------------------------------------------------------------------------
# Locating
# ---------------------------------------------------------------------------

def _di_rects(page: "fitz.Page", field: str, coordinates: Iterable[dict] | None) -> list["fitz.Rect"]:
    aliases = DI_FIELD_ALIASES.get(field)
    if not aliases or not coordinates:
        return []
    rects = []
    pw, ph = page.rect.width, page.rect.height
    for entry in coordinates:
        if not isinstance(entry, dict) or entry.get("field") not in aliases:
            continue
        if int(entry.get("page") or 1) != page.number + 1:
            continue
        try:
            x = float(entry["x"]) / 100.0 * pw
            y = float(entry["y"]) / 100.0 * ph
            w = float(entry["width"]) / 100.0 * pw
            h = float(entry["height"]) / 100.0 * ph
        except (KeyError, TypeError, ValueError):
            continue
        rects.append(fitz.Rect(x, y, x + w, y + h))
    return rects


_AFFIX_RE = re.compile(r"^(?P<pre>[^0-9A-Za-z]*)(?P<core>.*?)(?P<post>[^0-9A-Za-z]*)$")


def _split_affixes(token: str) -> tuple[str, str, str]:
    """`"$1,250.00,"` → `("$", "1,250.00", ",")`. The affixes are preserved
    around the replacement, so a currency symbol printed hard against the
    number survives the substitution."""
    match = _AFFIX_RE.match(token)
    if not match:
        return "", token, ""
    return match.group("pre"), match.group("core"), match.group("post")


def locate_token(
    page: "fitz.Page",
    field: str,
    old_text: str,
    coordinates: Iterable[dict] | None = None,
    allow_substring: bool = True,
) -> "tuple[fitz.Rect, str] | None":
    """`(rect, printed_token)` for `old_text` on this page, or None.

    Whole-token matching first, `page.search_for()` substring matching only
    when `allow_substring` (never for a number). That distinction is not
    cosmetic: an unqualified substring search for a quantity of `5.00` happily
    matches the `5.00` inside a *different line's* `175.00` and silently
    rewrites the wrong cell — observed on the `us_style` fixture during this
    build, which is why the number path is token-anchored.
    """
    if not old_text:
        return None

    matches: list[tuple["fitz.Rect", str]] = []
    try:
        words = page.get_text("words")
    except Exception as exc:  # pragma: no cover - defensive, malformed page
        logger.warning("get_text('words') failed on page %s: %s", page.number, exc)
        words = []
    for word in words:
        token = word[4]
        if _split_affixes(token)[1] == old_text:
            matches.append((fitz.Rect(word[0], word[1], word[2], word[3]), token))

    if not matches and allow_substring:
        try:
            matches = [(rect, old_text) for rect in page.search_for(old_text)]
        except Exception as exc:  # pragma: no cover
            logger.warning("search_for(%r) failed on page %s: %s", old_text, page.number, exc)
            return None
    if not matches:
        return None

    di = _di_rects(page, field, coordinates)
    if di:
        def distance(entry: "tuple[fitz.Rect, str]") -> float:
            rect = entry[0]
            best = None
            for target in di:
                dx = (rect.x0 + rect.x1) / 2 - (target.x0 + target.x1) / 2
                dy = (rect.y0 + rect.y1) / 2 - (target.y0 + target.y1) / 2
                d = (dx * dx + dy * dy) ** 0.5
                best = d if best is None else min(best, d)
            return best or 0.0

        return min(matches, key=distance)
    return min(matches, key=lambda e: (round(e[0].y0, 1), e[0].x0))


def locate_field(
    page: "fitz.Page",
    field: str,
    old_text: str,
    coordinates: Iterable[dict] | None = None,
    allow_substring: bool = True,
) -> "fitz.Rect | None":
    """Where `old_text` is printed on `page`, or None.

    Several hits are resolved by the Document Intelligence polygon stored for
    that field: the hit whose centre is nearest the polygon wins. That is what
    makes the "date printed twice" case deterministic — the header date carries
    the `InvoiceDate` polygon, the footer repetition does not. Without a
    polygon the topmost hit wins, which is a stated tie-break, not a guess
    dressed up as one.
    """
    found = locate_token(page, field, old_text, coordinates, allow_substring)
    return found[0] if found else None


# ---------------------------------------------------------------------------
# Substituting
# ---------------------------------------------------------------------------

def _span_style(page: "fitz.Page", rect: "fitz.Rect") -> tuple[float, tuple[float, float, float]]:
    """Font size and colour of the text already at `rect`, so the replacement
    is printed in the source's own style rather than a house default."""
    best_area, size, color = 0.0, 10.0, (0.0, 0.0, 0.0)
    try:
        data = page.get_text("dict")
    except Exception:  # pragma: no cover
        return size, color
    for block in data.get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                sr = fitz.Rect(span["bbox"])
                inter = sr & rect
                area = inter.get_area() if not inter.is_empty else 0.0
                if area > best_area:
                    best_area = area
                    size = float(span.get("size") or size)
                    raw = int(span.get("color") or 0)
                    color = (
                        ((raw >> 16) & 255) / 255.0,
                        ((raw >> 8) & 255) / 255.0,
                        (raw & 255) / 255.0,
                    )
    return size, color


def substitute(
    pdf_bytes: bytes,
    subs: list[Substitution],
    coordinates: Iterable[dict] | None = None,
) -> tuple[bytes, list[str]]:
    """Apply `subs` to `pdf_bytes` and return `(new_pdf, unlocated_fields)`.

    Redact-then-reprint, per page: every located span is covered with a
    redaction annotation, `apply_redactions()` removes the underlying text, and
    the new value is printed into the same rectangle at the same size and
    colour, right-aligned for numeric fields. Images are explicitly left alone
    by the redaction pass — otherwise the tenant's own logo would be erased
    whenever a value happened to overlap it.

    Two details that are not cosmetic:

    * The redaction rectangle is the **middle 70%** of the located rect's
      height (`_REDACT_INSET`). A word rect from PyMuPDF spans the whole line
      box, ascender to descender, and consecutive lines in a tightly-leaded
      header overlap — redacting the full rect for `INV-0042` also deleted the
      tail of the *next* line's invoice date on this feature's own `us_style`
      fixture. Inset vertically, the annotation still intersects every glyph of
      its own token (so the value really is removed, not merely covered) and no
      longer touches its neighbours.
    * `fill=None`, so no white box is painted. The text is gone from the
      content stream either way, and a white rectangle would punch a hole in a
      shaded table row.

    A field that could not be located anywhere in the document is *not* an
    exception: its name goes into the returned list and the caller answers 422.
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        unlocated: list[str] = []
        ops: dict[int, list[tuple["fitz.Rect", str, str]]] = {}

        for sub in subs:
            pairs = candidate_renderings(sub)
            # A number is never matched as a substring: see `locate_token`.
            allow_substring = sub.kind == "text"
            found = False
            for page in doc:
                for old_text, new_text in pairs:
                    hit = locate_token(
                        page, sub.field, old_text, coordinates,
                        allow_substring or " " in old_text,
                    )
                    if hit is not None:
                        rect, token = hit
                        pre, _core, post = _split_affixes(token)
                        if sub.kind == "number" and sub.new_value is not None:
                            printed = pre + format_like(_core, sub.new_value) + post
                        else:
                            printed = pre + new_text + post
                        ops.setdefault(page.number, []).append((rect, printed, sub.align))
                        found = True
                        break
                if found:
                    break
            if not found:
                unlocated.append(sub.field)

        for page_number, page_ops in ops.items():
            page = doc[page_number]
            styles = [_span_style(page, rect) for rect, _, _ in page_ops]
            for rect, _, _ in page_ops:
                inset = rect.height * _REDACT_INSET
                page.add_redact_annot(
                    fitz.Rect(rect.x0, rect.y0 + inset, rect.x1, rect.y1 - inset),
                    fill=None,
                )
            try:
                page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
            except TypeError:  # pragma: no cover - older PyMuPDF signature
                page.apply_redactions()

            for (rect, new_text, align), (size, color) in zip(page_ops, styles):
                _print_value(page, rect, new_text, size, color, align)

        return doc.tobytes(), unlocated
    finally:
        doc.close()


def _print_value(
    page: "fitz.Page",
    rect: "fitz.Rect",
    text: str,
    size: float,
    color: tuple[float, float, float],
    align: str,
) -> None:
    """Print `text` into `rect`, growing the box away from the alignment edge
    and shrinking the font only if it still will not fit."""
    right = align == "right"
    fontsize = size
    for _ in range(8):
        needed = fitz.get_text_length(text, fontname="helv", fontsize=fontsize)
        extra = max(0.0, needed - rect.width) + 2.0
        box = fitz.Rect(
            rect.x0 - (extra if right else 0.0),
            rect.y0 - fontsize * 0.35,
            rect.x1 + (0.0 if right else extra),
            rect.y1 + fontsize * 0.45,
        )
        rc = page.insert_textbox(
            box,
            text,
            fontsize=fontsize,
            fontname="helv",
            color=color,
            align=fitz.TEXT_ALIGN_RIGHT if right else fitz.TEXT_ALIGN_LEFT,
        )
        if rc >= 0:
            return
        fontsize -= 0.75
        if fontsize < 4:
            break
    logger.warning("Could not fit %r into %s at any size >= 4pt", text, rect)
