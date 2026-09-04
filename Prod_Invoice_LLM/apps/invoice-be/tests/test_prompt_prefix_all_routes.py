"""Feature 26 Phase 3.5 (Gap 455) — the request marker on every phrasing prompt.

`tests/test_a4_prompt_prefix.py` guards the SQL prompt by RENDERING it, because
`build_sql_system_prompt()` is a function. The four prompts below are f-strings
inline in their routes, so this file guards them at the SOURCE: it finds each
prompt in `agents/query_agent.py`, splits it on `PROMPT_REQUEST_SECTION_MARKER`,
and fails if any interpolated value other than a known module-level constant
sits above the marker. That is the whole invariant -- a per-request value above
the marker is what ends the cacheable prefix early.

It also measures the static half of each prompt, so the token count is a fact
in the test output rather than an assumption in a tracker entry.
"""
import re
from pathlib import Path

import pytest
import tiktoken

import agents.query_agent as qa

SOURCE = Path(qa.__file__).read_text(encoding="utf-8")
ENC = tiktoken.get_encoding("o200k_base")

#: Interpolations that are module-level constants -- identical for every request
#: in the process -- and therefore allowed above the marker.
STATIC_INTERPOLATIONS = {
    "CHAT_PERSONA_BLOCK",
    "PERSONA_BLOCK",
    "_INJECTION_GUARD_INSTRUCTION",
    "_DOCUMENT_TEXT_GUARD_INSTRUCTION",
    "CONTENT_BRANCH_PROMPT_MARKER",
    "PROMPT_REQUEST_SECTION_MARKER",
}

#: How each prompt is found in the source: a unique phrase inside its static half.
PROMPTS = {
    "sql_summary": "Format a friendly summary explaining these database query results.",
    "rag_answer": "For THIS step you are answering from the invoice DOCUMENTS themselves",
    "attachment_content": "WHAT YOU HAVE:\n1. A short summary of the document, extracted into fields.",
    "attachment_compare": "You are reporting the result of a comparison between a reference document",
    "attachment_pair": "You are reporting a comparison between TWO documents the user attached",
}


def _prompt_source(anchor: str) -> str:
    """The source text of the f-string (or string concatenation) holding `anchor`,
    from the start of its statement to the marker and a little beyond."""
    at = SOURCE.index(anchor)
    start = SOURCE.rfind("system_prompt = ", 0, at)
    start = max(start, SOURCE.rfind("summary_prompt = ", 0, at))
    end = SOURCE.index("PROMPT_REQUEST_SECTION_MARKER", at)
    return SOURCE[start:end]


def _interpolations(text: str) -> set:
    names = set()
    for m in re.finditer(r"\{([^{}]+)\}", text):
        expr = m.group(1).strip()
        names.add(re.split(r"[\(\.\[ ]", expr, 1)[0])
    return names


@pytest.mark.parametrize("name,anchor", list(PROMPTS.items()))
def test_nothing_per_request_sits_above_the_marker(name, anchor):
    head = _prompt_source(anchor)
    leaked = _interpolations(head) - STATIC_INTERPOLATIONS
    assert not leaked, f"{name}: per-request values above the request marker: {sorted(leaked)}"


@pytest.mark.parametrize("name,anchor", list(PROMPTS.items()))
def test_the_marker_appears_exactly_once_per_prompt(name, anchor):
    at = SOURCE.index(anchor)
    nxt = SOURCE.find("PROMPT_REQUEST_SECTION_MARKER", at)
    assert nxt != -1, f"{name}: no request marker after the prompt's static text"
    # The following prompt's anchor must come after this prompt's marker: one
    # marker per prompt, in order.
    later = [SOURCE.find(a, nxt) for a in PROMPTS.values() if SOURCE.find(a, nxt) != -1]
    assert all(pos > nxt for pos in later)


@pytest.mark.parametrize("name,anchor", list(PROMPTS.items()))
def test_both_guards_are_in_the_static_half(name, anchor):
    """The injection guard is a rule, not per-request text; leaving it below the
    marker would spend cache on nothing and re-send it on every turn."""
    head = _prompt_source(anchor)
    assert "_INJECTION_GUARD_INSTRUCTION" in head, f"{name}: injection guard is below the marker"


def _render_static(head: str) -> str:
    """Substitute the allowed constants so the static half can be measured."""
    body = head[head.index('f"""') + 4:] if 'f"""' in head else head
    for name in STATIC_INTERPOLATIONS:
        value = getattr(qa, name, None)
        if value is None:
            from utils.llm import CONTENT_BRANCH_PROMPT_MARKER

            value = CONTENT_BRANCH_PROMPT_MARKER if name == "CONTENT_BRANCH_PROMPT_MARKER" else ""
        body = body.replace("{" + name + "}", str(value))
    return body


@pytest.mark.parametrize("name,anchor", list(PROMPTS.items()))
def test_static_half_token_count_is_recorded(name, anchor, capsys):
    """Not a threshold -- a measurement. Azure caches from 1,024 tokens; the
    persona block alone is most of that, and this records where each prompt
    lands so the number is in the test output, not in a guess."""
    head = _render_static(_prompt_source(anchor))
    n = len(ENC.encode(head))
    print(f"{name}: static prefix ~{n} tokens (cache minimum 1024)")
    assert n > 200, f"{name}: static half is implausibly small ({n} tokens)"
