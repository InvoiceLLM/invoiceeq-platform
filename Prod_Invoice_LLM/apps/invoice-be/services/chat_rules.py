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


def render_chat_rule(category: str, pattern: str = "", context_text: str = "") -> str:
    """Deterministically render a chat rule to its prompt sentence.

    `context_text` is accepted for signature symmetry with the caller but is
    never interpolated -- see the module docstring.
    """
    spec = CHAT_RULE_CATEGORIES.get(category)
    if not spec:
        return ""
    clean = (pattern or "").strip()
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
    return None
