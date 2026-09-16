"""Feature 18: the chat-correction vocabulary and rendering.

Why categories instead of a text box
------------------------------------
The whole failure this redesign addresses is "free text goes in, an LLM decides
what it meant, a rule comes out, nobody checked". Repeating that shape on the
chat side would have reproduced it exactly. So a chat correction is a **pick**
from the closed set below plus a `pattern` (the specific thing the category
applies to), and the resulting rule text is produced by a deterministic template
in this module — no LLM is involved in turning a chat correction into a rule at
all.

The optional `context_text` is carried for a human reading the rule later. It is
deliberately NOT interpolated into the prompt sentence: it is unvalidated free
text, and splicing it into an instruction block is precisely the injection
surface Gap 58 was opened about.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ChatRuleCategory:
    key: str
    label: str
    #: What the `pattern` field means for this category, shown as the FE's input hint.
    pattern_label: str
    #: Whether a pattern is required (some categories are meaningless without one).
    requires_pattern: bool
    #: Deterministic template. `{pattern}` is the only interpolation.
    template: str


CHAT_RULE_CATEGORIES: dict[str, ChatRuleCategory] = {
    "should_have_included": ChatRuleCategory(
        key="should_have_included",
        label="Should have included something it left out",
        pattern_label="What should have been included",
        requires_pattern=True,
        template=(
            "When a question could reasonably cover it, include {pattern} in the "
            "results rather than filtering it out."
        ),
    ),
    "should_have_excluded": ChatRuleCategory(
        key="should_have_excluded",
        label="Should have excluded something it included",
        pattern_label="What should have been excluded",
        requires_pattern=True,
        template=(
            "Exclude {pattern} from results unless the user explicitly asks for it."
        ),
    ),
    "wrong_date_range": ChatRuleCategory(
        key="wrong_date_range",
        label="Interpreted a date range wrongly",
        pattern_label="How the date range should be read",
        requires_pattern=True,
        template=(
            "When interpreting date ranges in a question, apply this convention: {pattern}."
        ),
    ),
    "search_line_item_descriptions": ChatRuleCategory(
        key="search_line_item_descriptions",
        label="Should have searched line-item descriptions too",
        pattern_label="Kind of question this applies to (optional)",
        requires_pattern=False,
        template=(
            "For questions about what was bought, search the line-item descriptions in "
            "the items column as well as the invoice-level fields{pattern}."
        ),
    ),
    "wrong_direction": ChatRuleCategory(
        key="wrong_direction",
        label="Confused invoices received with invoices sent",
        pattern_label="How this tenant phrases the distinction",
        requires_pattern=False,
        template=(
            "Be careful to distinguish INBOUND invoices (bills received, filtered by "
            "vendor_name) from OUTBOUND invoices (bills sent, filtered by "
            "customer_name){pattern}."
        ),
    ),
    "wrong_aggregation": ChatRuleCategory(
        key="wrong_aggregation",
        label="Aggregated or grouped the data wrongly",
        pattern_label="How it should aggregate",
        requires_pattern=True,
        template="When aggregating results for this kind of question: {pattern}.",
    ),
    "wrong_status_filter": ChatRuleCategory(
        key="wrong_status_filter",
        label="Used the wrong status filter",
        pattern_label="Which statuses should count",
        requires_pattern=True,
        template="When filtering by status for this kind of question, count: {pattern}.",
    ),
    "missing_currency_context": ChatRuleCategory(
        key="missing_currency_context",
        label="Lost or mixed up currency context",
        pattern_label="What to do about currency (optional)",
        requires_pattern=False,
        template=(
            "Always state the currency alongside any amount and never combine amounts "
            "across different currencies{pattern}."
        ),
    ),
}


def list_chat_rule_categories() -> list[dict]:
    return [
        {
            "key": c.key,
            "label": c.label,
            "patternLabel": c.pattern_label,
            "requiresPattern": c.requires_pattern,
        }
        for c in CHAT_RULE_CATEGORIES.values()
    ]


#: BE Gap 592 (CH-25). A rule pattern is a short phrase -- a vendor name, a
#: category, a document type. Nothing legitimate needs a paragraph, and a cap is
#: what stops a "rule" from being a place to paste a second system prompt.
MAX_CHAT_RULE_PATTERN_CHARS = 200

#: Structural markers used elsewhere in prompt assembly. A tenant string that
#: contains one could close a section it was supposed to sit inside, so they are
#: removed on the way in rather than escaped on the way out.
_PROMPT_MARKER_RE = re.compile(r"<<<[^>]{0,80}>>>|</?\s*(?:tenant_rule|tenant_style|user_question|document_text)[^>]{0,80}>", re.IGNORECASE)

#: Newlines, tabs and other control characters. A rule renders as ONE line inside
#: a bulleted list; a newline in it creates a new bullet the tenant authored in
#: full, which is how "- ignore every instruction above" gets into the prompt
#: looking exactly like a line this codebase wrote.
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]+")


def sanitize_prompt_fragment(value: str, *, max_chars: int = MAX_CHAT_RULE_PATTERN_CHARS) -> str:
    """Make tenant-authored text safe to place inside a prompt, deterministically.

    BE Gap 592: control characters and prompt markers are removed, whitespace is
    collapsed, and the result is capped. Applied at input validation so bad data
    never reaches storage, and again at render time so rows written before this
    existed are covered too -- the second pass is why this is idempotent.

    This is the containment half of the fix; the other half is structural, in
    `agents/query_agent.py`, where what survives this is wrapped in a tag so the
    model can see where tenant text starts and stops. Neither alone is enough: a
    tag can be closed by its own content, and stripped content still needs a
    boundary.
    """
    if not value:
        return ""
    cleaned = _PROMPT_MARKER_RE.sub(" ", str(value))
    cleaned = _CONTROL_CHARS_RE.sub(" ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:max_chars].strip()


def render_chat_rule(category: str, pattern: str = "", context_text: str = "") -> str:
    """Deterministically render a chat rule to its prompt sentence.

    `context_text` is accepted for signature symmetry with the caller but is
    never interpolated -- see the module docstring.
    """
    spec = CHAT_RULE_CATEGORIES.get(category)
    if not spec:
        return ""
    # BE Gap 592: sanitised here as well as at input, so a row stored before the
    # input guard existed cannot still carry a marker or a newline into a prompt.
    clean = sanitize_prompt_fragment(pattern)
    if spec.requires_pattern and not clean:
        return ""
    if not spec.requires_pattern:
        # Optional-pattern templates embed `{pattern}` mid-sentence, so it has to
        # render as a well-formed clause or as nothing at all.
        rendered_pattern = f" (particularly for {clean})" if clean else ""
    else:
        rendered_pattern = clean
    return spec.template.format(pattern=rendered_pattern)


def validate_chat_rule(category: str, pattern: str = "") -> str | None:
    """Return an error message, or None if the (category, pattern) pair is usable."""
    spec = CHAT_RULE_CATEGORIES.get(category)
    if not spec:
        return f"Unknown chat rule category '{category}'."
    if spec.requires_pattern and not (pattern or "").strip():
        return f"'{spec.label}' needs a value for: {spec.pattern_label}."
    # BE Gap 592: reject rather than silently truncate -- the person typing it is
    # entitled to know their rule was not stored as written.
    if len((pattern or "").strip()) > MAX_CHAT_RULE_PATTERN_CHARS:
        return (
            f"'{spec.label}' is too long: {len(pattern.strip())} characters, "
            f"limit {MAX_CHAT_RULE_PATTERN_CHARS}."
        )
    if (pattern or "").strip() and not sanitize_prompt_fragment(pattern):
        return f"'{spec.label}' contains no usable text."
    return None
