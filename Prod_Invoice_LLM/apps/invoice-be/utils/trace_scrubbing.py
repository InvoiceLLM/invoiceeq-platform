"""Feature 23 — the **Scrub** step of Identify -> Extract -> Scrub -> Codify -> Refine.

What this is for
----------------
`feature_23_ai_control_tower.md` states the constraint plainly: a captured trace
contains the assembled system prompt (with `tenant_stats`), real vendor/customer
names, invoice numbers, GSTINs, bank details from `payment_instructions`, and
full monetary values — and *"this cannot leave the production boundary or enter
a committed test fixture unscrubbed"*. It also states the counter-constraint:
*"too aggressive and the bug stops reproducing, too light and real customer data
ends up in git history."*

This module implements the compromise the doc asked for, and the compromise is
the whole design, not an implementation detail:

**Consistent pseudonymisation, not blanket redaction.**
Every distinct real value is replaced by a stable alias — the same vendor is
``<VENDOR_1>`` in the question, in the system prompt, in the SQL, in the tool
result and in the answer. Blanket ``[REDACTED]`` would destroy exactly the
property most gap reproductions turn on: *did the answer talk about the same
entity the question asked about?* (Gap 270's direction flip, Gap 276's stale
prior-SQL reuse and Gap 263's tax relabelling are all detectable after
aliasing and all invisible after flattening.)

**What survives, on purpose**

* Every dict **key**. Field names are schema, not customer data, and a
  reasoning error is usually *about* a field name (`status` read as a payment
  status; `tax_amount` relabelled as CGST).
* The **shape** of the question and the answer — sentence structure, ordering,
  hedging, the results table's row/column layout. Only the leaf values move.
* **Referential identity** — equal inputs get equal aliases, distinct inputs get
  distinct aliases, within one scrub pass.
* Explicitly structural values (`currency`, `quantity`, `flow_direction`,
  `status`, `role`, `stop_reason`, `method_type`, ...) are never rewritten, so
  "USD vs INR", "INBOUND vs OUTBOUND" and "IBAN+SWIFT vs ACH" survive.

**What is deliberately lost, and what that costs**

Monetary values become ``<AMOUNT_n>``. Equal amounts share an alias and distinct
amounts do not, so a *mismatch* bug still reproduces — Gap 269's
``5,000 x USD 0.08 = USD 420.00`` survives as
``5000 x USD <AMOUNT_1> = USD <AMOUNT_2>`` (quantity and currency untouched)
with ``<AMOUNT_2>`` visibly not the same figure the line's own amount column
carried. What does **not** survive is *arithmetic verifiability*: a scrubbed
trace can show that two figures which should have been identical were not, but
cannot be used to check that a sum is right. Any gap whose reproduction needs
real arithmetic must either run against a synthetic tenant or stay
production-only. `scrub_trace(..., preserve_amounts=True)` exists for the
inside-the-boundary case and must never be used to produce a committed fixture.

Two exceptions are carved out of amount redaction because they carry reasoning
signal and disclose nothing: the **currency token** stays verbatim (mixed-
currency handling is a real tested behaviour), and a **zero** becomes the fixed
``<AMOUNT_ZERO>`` rather than joining the alias pool — Gap 224's
false-confident-zero failure is unreproducible if zero is indistinguishable
from any other figure.

**Known holes — stated rather than implied**

* Postal addresses, phone numbers, and personal names that appear only in prose
  (never in an entity field and not passed via `extra_entity_names`) are **not**
  detected. Email addresses and the labelled bank-detail patterns below are.
* A document identifier that appears *only* in prose and does not carry a 3+
  digit run (see `DOC_ID_RE`) is not detected. Every identifier format across
  this repo's four test tenants does carry one, and any id that also appears in
  an `invoice_number`/`po_number` field is caught by exact-literal replacement
  regardless of format — but the free-text pattern alone is not exhaustive.

This module is a *reduction* of disclosure risk, not a certification of
anonymity, and Feature 23's SOC 2 questions (retention, access control, whether
a trace is customer data at all) remain open regardless of what this does.

No new dependency: `re` and the standard library only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

# ---------------------------------------------------------------------------
# Field classification
# ---------------------------------------------------------------------------

#: Leaf values here are treated as real party names and aliased everywhere they
#: appear in the trace, including inside free text.
VENDOR_NAME_FIELDS = ("vendor_name", "vendor", "biller", "biller_name", "supplier_name")
CUSTOMER_NAME_FIELDS = ("customer_name", "customer", "bill_to", "billed_to", "buyer_name")

#: Document identifiers. `po_number` is included: it is the same disclosure
#: class as an invoice number and appears in the same prompts.
INVOICE_ID_FIELDS = (
    "invoice_number",
    "invoice_no",
    "po_number",
    "purchase_order",
    "reference_number",
)

#: Monetary leaves. Aliased by value, so equal amounts stay equal.
MONEY_FIELDS = (
    "grand_total",
    "subtotal",
    "sub_total",
    "tax_amount",
    "total",
    "total_amount",
    "amount",
    "line_amount",
    "unit_price",
    "price",
    "discount_amount",
    "balance_due",
    "total_line_amount",
    "avg_line_amount",
    "total_grand_total",
    "total_tax_amount",
    "total_spend",
)

#: Never rewritten, even when a value would otherwise match a pattern. These
#: carry the reasoning shape a reproduction depends on.
STRUCTURAL_FIELDS = frozenset(
    {
        "currency",
        "quantity",
        "line_qty",
        "qty",
        "flow_direction",
        "status",
        "role",
        "route",
        "stop_reason",
        "clarification_reason",
        "tool",
        "tool_name",
        "agent_name",
        "model",
        "method_type",
        "ref_type",
        "address_type",
        "alert_type",
        "field",
        "field_name",
        "case_id",
        "verdict",
        "source",
        "source_gap",
        "invoice_count",
        "line_item_count",
        "llm_calls",
        "llm_call_count",
        "tokens_in",
        "tokens_out",
        "latency_ms",
    }
)

#: Free-text fields that get the full pattern sweep. Anything not listed here is
#: still swept if it is a string — this tuple only documents the expected ones.
FREE_TEXT_FIELDS = (
    "question",
    "answer",
    "content",
    "prompt",
    "system_prompt",
    "generated_sql",
    "expected_answer",
    "reason",
    "notes",
    "tenant_stats",
    "description",
    "line_description",
)

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

# 15-char GSTIN: 2 state digits + 10-char PAN + entity digit + 'Z' + checksum.
GSTIN_RE = re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][0-9A-Z]Z[0-9A-Z]\b")

# EU VAT identifier, e.g. DE123456789 / FR12345678901. Two-letter country code
# followed by 8-12 alphanumerics. Kept narrow to avoid eating ordinary words.
VAT_ID_RE = re.compile(r"\b(?:AT|BE|BG|CY|CZ|DE|DK|EE|EL|ES|FI|FR|HR|HU|IE|IT|LT|LU|LV|MT|NL|PL|PT|RO|SE|SI|SK)[0-9A-Z]{8,12}\b")

# Leading-symbol / leading-code money: "USD 18,450.00", "$450.00", "Rs 41,300", "€1,516.50".
_CURRENCY = "USD|EUR|INR|GBP|AUD|CAD|SGD|AED|Rs\\.?|\\$|₹|€|£"
MONEY_PREFIX_RE = re.compile("({0})(\\s?)(-?\\d[\\d,]*(?:\\.\\d{{1,6}})?)".format(_CURRENCY))
# Trailing-code money: "18,450.00 USD".
MONEY_SUFFIX_RE = re.compile(
    r"(-?\d[\d,]*(?:\.\d{1,6})?)(\s?)(USD|EUR|INR|GBP|AUD|CAD|SGD|AED)\b"
)

# Document identifiers: an all-caps stem plus at least one hyphenated segment,
# and at least one digit somewhere in the token. Matches INV-2026-0034,
# TSD-620458, US-20260722-001, BRL-7702, IEQ-US-9001, PO-IN-4410, OR-EX-88231.
#
# The `\d{3,}` requirement is what keeps domain acronyms out -- "CGST-SGST" and
# "RCM-B2B" are the vocabulary a tax-reasoning bug is *made of*, and "RCM-B2B"
# defeats a naive "contains a digit" rule. Every real identifier in this repo's
# four tenants carries a 3+ digit run; a hypothetical "AB-12-34" would not be
# caught by this pattern in free text. That residual is covered whenever the
# same id also appears in an `invoice_number`/`po_number` field, because those
# values are registered as literals and replaced by exact match (see
# `_collect_entities`) -- and is a stated hole otherwise.
DOC_ID_RE = re.compile(r"\b(?=[A-Z0-9-]*\d{3})[A-Z][A-Z0-9]{1,9}(?:-[A-Z0-9]{2,9}){1,3}\b")

EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")

# International Bank Account Number.
IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")
# Indian IFSC: 4 letters, a literal 0, then 6 alphanumerics.
IFSC_RE = re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")
# A labelled account-ish value: "Account No: 000123456789", "SWIFT: HDFCINBBXXX".
# The label matches case-insensitively; the *value* does not, and must be 6+
# characters of upper-case/digit/hyphen/slash. Without that restriction the
# pattern eats ordinary prose ("the account balance is not stored") -- which is
# over-redaction that silently destroys the question shape the trace exists for.
LABELLED_BANK_RE = re.compile(
    r"(?i:\b(account|a/c|acct|iban|swift|bic|ifsc|routing|sort\s?code|upi)\b"
    r"\s*(?:no\.?|number|id|code)?)\s*[:#=]?\s*([A-Z0-9][A-Z0-9\-/]{5,})"
)

#: A zero amount is not confidential -- it discloses nothing about a customer --
#: and "was the total zero?" is exactly the property Gap 224's
#: false-confident-zero failure turns on. Zeroes therefore keep a fixed
#: placeholder of their own instead of being pooled with real figures.
ZERO_AMOUNT_PLACEHOLDER = "<AMOUNT_ZERO>"

#: Placeholders this module emits. Used to keep scrubbing idempotent.
PLACEHOLDER_RE = re.compile(
    r"<(?:VENDOR|CUSTOMER|PARTY|INVOICE_NO|GSTIN|VAT_ID|AMOUNT|BANK_DETAILS|EMAIL)_\d+>"
    r"|<AMOUNT_ZERO>"
)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class ScrubReport:
    """What the pass actually did — the audit trail for a scrub decision.

    `aliases` maps the *real* value to the placeholder that replaced it. It is
    the re-identification key, so it is returned to the caller in memory and is
    never written into the scrubbed trace itself: a fixture that carried its own
    key would defeat the entire exercise.
    """

    aliases: dict[str, str] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)

    def record(self, category: str) -> None:
        self.counts[category] = self.counts.get(category, 0) + 1

    @property
    def total_redactions(self) -> int:
        return sum(self.counts.values())


@dataclass
class ScrubResult:
    trace: Any
    report: ScrubReport


# ---------------------------------------------------------------------------
# Alias registry
# ---------------------------------------------------------------------------


#: Legal-entity suffixes stripped to derive a short-form variant of a party
#: name. Real traces mix the two freely — `vendor_name` holds "Rajesh Steel Pvt
#: Ltd" while the user's question and the generated SQL's LIKE both say "Rajesh
#: Steel". Aliasing only the long form leaves the real surname in the question,
#: which is the exact leak this module exists to prevent.
_LEGAL_SUFFIX_RE = re.compile(
    r"(?i)[\s,]+(?:private\s+limited|pvt\.?\s*ltd\.?|pvt\.?|limited|ltd\.?|llc|l\.l\.c\.?"
    r"|inc\.?|incorporated|corp\.?|corporation|company|co\.?|gmbh|ag|sarl|s\.a\.r\.l\.?"
    r"|s\.a\.?|b\.v\.?|bv|nv|ab|oy|s\.l\.?|sl|plc|llp|lp)\.?$"
)

#: A stripped variant shorter than this is not registered — it would be a
#: common word, and aliasing it would corrupt unrelated prose.
_MIN_VARIANT_LEN = 5

_PARTY_CATEGORIES = ("VENDOR", "CUSTOMER", "PARTY")


def _short_form(name: str) -> Optional[str]:
    """"Rajesh Steel Pvt Ltd" -> "Rajesh Steel"; None when nothing was stripped."""
    current = name.strip()
    for _ in range(3):  # "X Pvt. Ltd." needs two passes
        stripped = _LEGAL_SUFFIX_RE.sub("", current).strip(" .,")
        if stripped == current:
            break
        current = stripped
    if current == name.strip() or len(current) < _MIN_VARIANT_LEN:
        return None
    return current


class _Aliaser:
    """Stable value -> placeholder mapping, one counter per category."""

    def __init__(self, report: ScrubReport):
        self._report = report
        self._by_value: dict[tuple[str, str], str] = {}
        self._counters: dict[str, int] = {}

    def alias(self, category: str, value: str) -> str:
        key = (category, value.strip())
        existing = self._by_value.get(key)
        if existing is not None:
            self._report.record(category)
            return existing
        self._counters[category] = self._counters.get(category, 0) + 1
        placeholder = f"<{category}_{self._counters[category]}>"
        self._by_value[key] = placeholder
        self._report.aliases[value.strip()] = placeholder
        self._report.record(category)
        if category in _PARTY_CATEGORIES:
            variant = _short_form(value)
            # Same placeholder on purpose: the long and short spelling are one
            # entity, and a reproduction depends on them still reading as one.
            if variant and (category, variant) not in self._by_value:
                self._by_value[(category, variant)] = placeholder
                self._report.aliases[variant] = placeholder
        return placeholder

    def text_literals(self) -> list[tuple[str, str]]:
        """Values already aliased from a structured field that must also be
        replaced wherever they appear in free text, longest first.

        Longest-first matters: replacing "Titan Steel" before "Titan Steel
        Distributors" would leave a real name fragment behind. Document ids are
        included as well as party names, so an id whose format `DOC_ID_RE` is
        too strict to recognise is still caught whenever it also appears in an
        `invoice_number`/`po_number` field somewhere in the same trace.
        """
        literals = [
            (value, placeholder)
            for (category, value), placeholder in self._by_value.items()
            if category in _PARTY_CATEGORIES or category == "INVOICE_NO"
        ]
        return sorted(literals, key=lambda pair: len(pair[0]), reverse=True)


# ---------------------------------------------------------------------------
# Text scrubbing
# ---------------------------------------------------------------------------


def _scrub_text(text: str, aliaser: _Aliaser, *, preserve_amounts: bool) -> str:
    """Sweep one string. Order is load-bearing — see the inline notes."""
    if not text:
        return text

    # 1. Literals already seen in a structured field (party names, document
    #    ids), longest first, case-insensitively. Doing this before the pattern
    #    sweep stops a vendor name that happens to look like a doc id from being
    #    aliased twice under two categories.
    for real, placeholder in aliaser.text_literals():
        if not real:
            continue
        pattern = re.compile(re.escape(real), re.IGNORECASE)
        text, n = pattern.subn(placeholder, text)
        for _ in range(n):
            aliaser._report.record("literal_in_text")

    # 2. Labelled bank details before the generic identifier patterns, because
    #    "Account No: 000123456789" would otherwise be split by them.
    def _bank_sub(match: re.Match) -> str:
        label, value = match.group(1), match.group(2)
        return f"{label}: {aliaser.alias('BANK_DETAILS', value.strip())}"

    text = LABELLED_BANK_RE.sub(_bank_sub, text)
    text = IBAN_RE.sub(lambda m: aliaser.alias("BANK_DETAILS", m.group(0)), text)
    text = IFSC_RE.sub(lambda m: aliaser.alias("BANK_DETAILS", m.group(0)), text)

    # 3. Tax identifiers before doc ids and money (a GSTIN has no hyphen, so it
    #    cannot collide with DOC_ID_RE, but a VAT id could be read as one).
    text = GSTIN_RE.sub(lambda m: aliaser.alias("GSTIN", m.group(0)), text)
    text = VAT_ID_RE.sub(lambda m: aliaser.alias("VAT_ID", m.group(0)), text)

    # 4. Money before doc ids. The currency token is kept verbatim and only the
    #    figure is aliased, so mixed-currency reasoning still reproduces.
    if not preserve_amounts:
        text = MONEY_PREFIX_RE.sub(
            lambda m: f"{m.group(1)}{m.group(2)}{_money_alias(aliaser, m.group(3))}", text
        )
        text = MONEY_SUFFIX_RE.sub(
            lambda m: f"{_money_alias(aliaser, m.group(1))}{m.group(2)}{m.group(3)}", text
        )

    # 5. Document identifiers.
    text = DOC_ID_RE.sub(
        lambda m: m.group(0)
        if PLACEHOLDER_RE.fullmatch(m.group(0))
        else aliaser.alias("INVOICE_NO", m.group(0)),
        text,
    )

    # 6. Email last — nothing above can produce one.
    text = EMAIL_RE.sub(lambda m: aliaser.alias("EMAIL", m.group(0)), text)

    return text


# ---------------------------------------------------------------------------
# Entity discovery
# ---------------------------------------------------------------------------


def _collect_entities(node: Any, aliaser: _Aliaser) -> None:
    """Walk the trace once, registering every party name and document id that
    appears in a named field.

    Registration has to happen for the whole trace before any text is swept: a
    vendor named in the tool result must be aliased in the *question* too, and
    the question may be visited first.
    """
    if isinstance(node, dict):
        for key, value in node.items():
            lowered = str(key).lower()
            if isinstance(value, str) and value.strip():
                if lowered in VENDOR_NAME_FIELDS:
                    aliaser.alias("VENDOR", value)
                elif lowered in CUSTOMER_NAME_FIELDS:
                    aliaser.alias("CUSTOMER", value)
                elif lowered in INVOICE_ID_FIELDS:
                    aliaser.alias("INVOICE_NO", value)
            _collect_entities(value, aliaser)
    elif isinstance(node, list):
        for item in node:
            _collect_entities(item, aliaser)


# ---------------------------------------------------------------------------
# The walk
# ---------------------------------------------------------------------------


def _scrub_node(
    node: Any,
    aliaser: _Aliaser,
    *,
    parent_key: Optional[str],
    preserve_amounts: bool,
    in_payment_instructions: bool,
) -> Any:
    key = (parent_key or "").lower()

    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for k, v in node.items():
            out[k] = _scrub_node(
                v,
                aliaser,
                parent_key=k,
                preserve_amounts=preserve_amounts,
                # `payment_instructions` entries are {method_type, details}; the
                # type is structure, the detail is the bank account.
                in_payment_instructions=in_payment_instructions
                or str(k).lower() == "payment_instructions",
            )
        return out

    if isinstance(node, list):
        return [
            _scrub_node(
                item,
                aliaser,
                parent_key=parent_key,
                preserve_amounts=preserve_amounts,
                in_payment_instructions=in_payment_instructions,
            )
            for item in node
        ]

    # Structural leaves are returned untouched regardless of what they contain.
    if key in STRUCTURAL_FIELDS:
        return node

    if isinstance(node, bool) or node is None:
        return node

    if isinstance(node, (int, float)):
        if key in MONEY_FIELDS and not preserve_amounts:
            return _money_alias(aliaser, node)
        return node

    if isinstance(node, str):
        if not node.strip():
            return node
        if in_payment_instructions and key in ("details", "value", "account", "iban"):
            return aliaser.alias("BANK_DETAILS", node)
        if key in VENDOR_NAME_FIELDS:
            return aliaser.alias("VENDOR", node)
        if key in CUSTOMER_NAME_FIELDS:
            return aliaser.alias("CUSTOMER", node)
        if key in INVOICE_ID_FIELDS:
            return aliaser.alias("INVOICE_NO", node)
        if key in MONEY_FIELDS and not preserve_amounts:
            return _money_alias(aliaser, node)
        return _scrub_text(node, aliaser, preserve_amounts=preserve_amounts)

    return node


def _format_number(value: Any) -> str:
    """Stable string form for a numeric amount, so 420, 420.0 and "420.00" and
    "USD 420.00" all resolve to one alias — which is what makes "the same figure
    appears in the line item and in the total" survive scrubbing."""
    try:
        as_float = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return str(value)
    if as_float == int(as_float):
        return f"{int(as_float)}"
    return f"{as_float}"


def _money_alias(aliaser: "_Aliaser", raw: str) -> str:
    """Alias one monetary figure, mapping any spelling of zero to one token."""
    normalised = _format_number(raw)
    if normalised in ("0", "-0"):
        aliaser._report.record("AMOUNT_ZERO")
        return ZERO_AMOUNT_PLACEHOLDER
    return aliaser.alias("AMOUNT", normalised)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def scrub_trace(
    trace: Any,
    *,
    extra_entity_names: Iterable[str] = (),
    preserve_amounts: bool = False,
) -> ScrubResult:
    """Redact a captured trace/prompt structure in place-safe fashion.

    Args:
        trace: any JSON-shaped structure — the captured turn, the assembled
            prompt dict, a list of turns. Not mutated; a new structure is
            returned.
        extra_entity_names: party names that appear only in prose (a vendor
            mentioned in the user's question but absent from every structured
            field). Registered before the sweep so they alias consistently.
        preserve_amounts: keep real monetary values. For inside-the-production-
            boundary analysis only — a trace scrubbed this way must not be
            committed. Defaults to False.

    Returns:
        `ScrubResult(trace=<scrubbed copy>, report=ScrubReport(...))`. The
        report holds the real-value -> placeholder map; it is the
        re-identification key and is never embedded in the scrubbed trace.
    """
    report = ScrubReport()
    aliaser = _Aliaser(report)

    for name in extra_entity_names:
        if name and str(name).strip():
            aliaser.alias("PARTY", str(name))

    _collect_entities(trace, aliaser)

    scrubbed = _scrub_node(
        trace,
        aliaser,
        parent_key=None,
        preserve_amounts=preserve_amounts,
        in_payment_instructions=False,
    )
    return ScrubResult(trace=scrubbed, report=report)


def contains_obvious_pii(trace: Any) -> list[str]:
    """Cheap post-scrub assertion helper: what still looks like real PII?

    Returns a list of human-readable findings, empty when nothing matched. This
    is a *check*, not a guarantee — see the module docstring's "Known holes".
    Intended for a test or a pre-commit gate over a generated fixture, so a
    scrubbing regression fails loudly instead of quietly shipping.
    """
    findings: list[str] = []

    def _walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                _walk(v, f"{path}.{k}" if path else str(k))
        elif isinstance(node, list):
            for i, item in enumerate(node):
                _walk(item, f"{path}[{i}]")
        elif isinstance(node, str):
            for label, pattern in (
                ("gstin", GSTIN_RE),
                ("iban", IBAN_RE),
                ("ifsc", IFSC_RE),
                ("email", EMAIL_RE),
                ("money", MONEY_PREFIX_RE),
                ("document_id", DOC_ID_RE),
            ):
                for match in pattern.finditer(node):
                    if PLACEHOLDER_RE.fullmatch(match.group(0)):
                        continue
                    findings.append(f"{path}: {label} -> {match.group(0)!r}")

    _walk(trace, "")
    return findings


__all__ = [
    "ScrubReport",
    "ScrubResult",
    "contains_obvious_pii",
    "scrub_trace",
    "MONEY_FIELDS",
    "STRUCTURAL_FIELDS",
    "ZERO_AMOUNT_PLACEHOLDER",
    "VENDOR_NAME_FIELDS",
    "CUSTOMER_NAME_FIELDS",
    "INVOICE_ID_FIELDS",
]
