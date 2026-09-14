"""Generic guards against fixture-shaped literals in product source.

Layer 3 of the anti-hardcoding harness (founder ask 2026-09-13). The hooks under
`.claude/hooks/` only see an edit as it is made; these run in the suite, so they apply to
whoever writes the code and catch regressions long after the session that introduced them.

Every assertion here is a PROPERTY over all of product source, never an expectation about
one card, one vendor or one document. That is deliberate: Feature 30 §11.3's guard test is
written the same way, and a test that pins one fixture's exact output is the thing this file
exists to prevent.

Scope note: `tests/`, `benchmarks/`, `scripts/`, `docs/` and `alembic/versions/` are excluded.
Concrete data is correct there.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

BE_ROOT = Path(__file__).resolve().parents[1]

SOURCE_DIRS = ("agents", "routers", "services", "workers")
SOURCE_FILES = ("config.py", "models.py", "schemas.py", "main.py")

EXCLUDED_PARTS = ("__pycache__", ".venv", "node_modules")

GOLDEN = BE_ROOT / "benchmarks" / "insight_golden.json"

# Same shapes the PostToolUse hook uses. Kept in sync deliberately: the hook is the fast
# feedback and this is the durable gate, and a rule that exists in only one of them is a
# rule that can be walked past.
GSTIN_RE = re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z]\d[A-Z0-9]{2}\b")
VAT_RE = re.compile(
    r"\b(?:ATU|BE|BG|CY|CZ|DE|DK|EE|EL|ES|FI|FR|HR|HU|IE|IT|LT|LU|LV|MT|NL|PL|PT|RO|SE|SI|SK|XI)"
    r"\d{8,12}\b"
)
DOC_ID_RE = re.compile(r"\b[A-Z]{2,5}-(?:[A-Z]{2,5}-)?\d{3,}\b")
# "INV-2026" / "TICK-2026" are id *templates* a generator concatenates onto, not a reference
# to one document. A bare year is not a document number.
DOC_ID_TEMPLATE_RE = re.compile(r"^[A-Z]{2,5}-(?:19|20)\d{2}$")
DOC_ID_ALLOW = {
    "SHA-256", "SHA-512", "SHA-1", "UTF-8", "UTF-16", "ISO-8601", "ISO-4217",
    "ISO-3166", "RFC-822", "RFC-2822", "RFC-3339", "AES-256", "RS-256", "HS-256",
    "GPT-4", "GPT-5", "EN-16931", "HTTP-401", "HTTP-403", "HTTP-404", "HTTP-500",
}

MONEY_WORDS_RE = re.compile(
    r"(?:₹|€|£|\$|\b(?:amount|amounts|total|totals|value|balance|outstanding|invoiced|owed|paid|pay|payable|due|bills|billed|charge|charges|charged|costs|cost|spend|refund|credit|debit|shortfall|excess|overdue|quoted|quote|average|net|subtotal|price|priced|rate)\b)",
    re.IGNORECASE,
)
FSTRING_RE = re.compile(r"""(?:f"[^"\n]*"|f'[^'\n]*')""")
# money_text() / days_text() / count_text() are the formatters 30.20 introduced; a line
# that calls one, or interpolates a value one already produced, is compliant.
FORMATTED_RE = re.compile(
    r"(?:money\s*\(|money_text\s*\(|days_text\s*\(|count_text\s*\(|\{[a-z_]*_text\}"
    r"|:,|:\.\d|_money|\.quantize|format_currency)"
)
PLACEHOLDER_RE = re.compile(r"\{[^{}]+\}")
# A placeholder whose expression is a date, a count, an id/key or a name is not a figure
# reaching text unformatted. Shapes, not vendors: `.isoformat()`, `['as_of']`, `len(`,
# `_count`, `.party_name`, `.invoice_number`, `doc_number`, `.id`, `.card`.
NONMONEY_PLACEHOLDER_RE = re.compile(
    r"\{[^{}]*(?:isoformat\(|\['as_of'\]|len\(|_count\b|\.party_name|\.invoice_number|doc_number|\.id\b|\.card\b|\.doc_type)[^{}]*\}"
)

# The claim layer — the modules whose whole job is turning a computed figure into a
# sentence. F30 §11.3 gives number-to-text one owner; this is where that is enforced.
# Error strings and PDF labels elsewhere are not claims and are out of scope.
CLAIM_MODULES = (
    "services/attachment_insights.py",
    "services/rule_cards.py",
    "services/bank_matching.py",
    "services/insights.py",
    "services/knowledge.py",
)

SUPPRESS_RE = re.compile(r"hardcode-ok:\s*\S+")

COMMENT_PREFIXES = ("#", '"""', "'''", "*")


def _source_files() -> list[Path]:
    files: list[Path] = []
    for d in SOURCE_DIRS:
        root = BE_ROOT / d
        if root.is_dir():
            files.extend(
                p
                for p in root.rglob("*.py")
                if not any(part in p.parts for part in EXCLUDED_PARTS)
            )
    files.extend(BE_ROOT / f for f in SOURCE_FILES if (BE_ROOT / f).is_file())
    return sorted(files)


def _code_lines(path: Path):
    """(line_no, text) for executable lines only — no comments, docstrings or suppressions.

    Docstring bodies are tracked across lines, not just at their opening quote. A worked
    example inside a docstring ("e.g. NEFT SHREE PACKAGING PVT LTD") is documentation, and
    counting it as a hardcoded literal would train everyone to ignore this guard.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:  # pragma: no cover
        return

    in_doc = False
    delim = ""
    for i, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()

        if in_doc:
            if delim in line:
                in_doc = False
                delim = ""
            continue

        for d in ('"""', "'''"):
            if stripped.startswith(d):
                # A one-line docstring opens and closes on the same line.
                if not (len(stripped) > len(d) and stripped.endswith(d)):
                    in_doc = True
                    delim = d
                break
        else:
            if SUPPRESS_RE.search(line) or stripped.startswith(COMMENT_PREFIXES):
                continue
            yield i, line
            continue
        continue


def _rel(path: Path) -> str:
    return path.relative_to(BE_ROOT).as_posix()


@pytest.fixture(scope="module")
def source_files() -> list[Path]:
    files = _source_files()
    assert files, "no product source found — the guard would pass vacuously"
    return files


def test_no_tax_identifier_literals_in_product_source(source_files):
    """A specific GSTIN or VAT registration is one company, not a rule.

    Region detection and compliance rules must work for a taxpayer nobody has seen yet, so
    a real identifier in code is either a fixture that leaked or a check that will only ever
    fire for one tenant.
    """
    offenders = []
    for path in source_files:
        for line_no, line in _code_lines(path):
            for m in GSTIN_RE.findall(line):
                offenders.append(f"{_rel(path)}:{line_no} GSTIN {m!r}")
            for m in VAT_RE.findall(line):
                offenders.append(f"{_rel(path)}:{line_no} VAT {m!r}")
    assert not offenders, "tax identifier literals in product source:\n" + "\n".join(offenders)


def test_no_document_identifier_literals_in_product_source(source_files):
    """An invoice / PO / challan number in code means a branch that fires for one document."""
    offenders = []
    for path in source_files:
        for line_no, line in _code_lines(path):
            for m in DOC_ID_RE.findall(line):
                if m not in DOC_ID_ALLOW and not DOC_ID_TEMPLATE_RE.match(m):
                    offenders.append(f"{_rel(path)}:{line_no} {m!r}")
    assert not offenders, (
        "document identifier literals in product source:\n"
        + "\n".join(offenders)
        + "\n\nIf one is genuinely static (a standard, a fixed external code), append "
        "`hardcode-ok: <reason>`."
    )


@pytest.mark.skipif(not GOLDEN.is_file(), reason="insight golden bank not present")
def test_product_source_shares_no_literal_with_the_golden_bank(source_files):
    """The fix and the fixture must not share a string.

    The clearest signature of a change written to pass one case is that a vendor name, item
    description or reference from the golden bank also appears in the code under test.
    """
    payload = json.loads(GOLDEN.read_text(encoding="utf-8"))

    # Only the fields that name a real-world ENTITY. Shared domain vocabulary ("Net 30 days
    # from invoice date", "no transaction rows") legitimately appears in both a fixture and
    # the code; a party name or a document reference does not.
    entity_keys = {
        "vendor_name", "customer_name", "buyer_name", "supplier_name", "party",
        "canonical_name", "alias", "narration", "description", "item_description",
        "invoice_number", "po_number", "order_number", "reference", "utr_ref",
        "challan_number", "quotation_number", "contract_number",
    }

    literals: set[str] = set()

    def walk(node, key: str | None = None) -> None:
        if isinstance(node, dict):
            for k, value in node.items():
                walk(value, k)
        elif isinstance(node, list):
            for value in node:
                walk(value, key)
        elif isinstance(node, str) and key in entity_keys:
            token = node.strip()
            if len(token) >= 6 and any(c.isalpha() for c in token):
                literals.add(token)

    walk(payload.get("cases", payload))

    offenders = []
    for path in source_files:
        for line_no, line in _code_lines(path):
            for lit in literals:
                if lit in line:
                    offenders.append(f"{_rel(path)}:{line_no} golden literal {lit!r}")

    assert not offenders, "product source shares literals with the golden bank:\n" + "\n".join(
        offenders
    )


def test_money_never_reaches_text_unformatted(source_files):
    """Feature 30 §11.3's guard, as a property over every module.

    An interpolated value beside money vocabulary with no formatter on the line is how
    "437190.0 of this order has not been invoiced yet" reached the founder (Gap 509).
    """
    offenders = []
    for path in source_files:
        if _rel(path) not in CLAIM_MODULES:
            continue
        for line_no, line in _code_lines(path):
            if FORMATTED_RE.search(line):
                continue
            for frag in FSTRING_RE.findall(line):
                money_placeholders = [m for m in PLACEHOLDER_RE.findall(frag) if not NONMONEY_PLACEHOLDER_RE.fullmatch(m)]
                if money_placeholders and MONEY_WORDS_RE.search(frag):
                    offenders.append(f"{_rel(path)}:{line_no} {frag.strip()[:110]}")
                    break
    assert not offenders, (
        "a number reaches user-facing text without a formatter:\n"
        + "\n".join(offenders)
        + "\n\nRoute it through the existing money() helper (F30 §11.3 — do not add a fifth one)."
    )
