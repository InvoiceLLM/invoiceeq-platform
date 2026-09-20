"""Feature 35 (ATLAS Intelligence) task 35.4 — the briefing loop.

Spec: `docs/feature_35_atlas_intelligence.md` §3.1, §3.3, §6 (task 35.4's row).

One tool-calling loop over the registry in `services/atlas_tools.py`, on the
`atlas` model role (GPT-5.6 Terra, §3.4). It computes nothing: every number it
can state came back from a Feature 34 service, and every id it can cite was put
on the run by `run_tool()`.

Three things this module is shaped around.

**It is a generator.** `run_briefing()` yields `BriefingEvent`s as they happen so
task 35.7 can stream them to an SSE response without buffering the whole
briefing first -- a briefing that takes twelve seconds to write should start
appearing in two, not arrive whole at twelve.

**The caps are the control, the prompt is not.** Six rounds, twelve invocations
and twenty seconds of wall clock (§8 ruling 2 -- starting numbers, to be
measured). Each is checked in code before the call it would allow, so a model
that decided to keep calling tools stops regardless of what it intends. On any
cap the loop emits `truncated` and then whatever text it already has, rather
than raising: a partial briefing that says so is more useful than an error.

**The model does not choose what it starts with** (BE Gap 716). Each role's
opening rows are fetched through `run_tool()` before the first model call and
handed over as context -- an Admin gets `list_lines`, `invoices`,
`cash_position` and `forecast`, because the four Admin needs cannot be answered
from one tool's rows and the first live run proved a model that finds the work
screen full never asks for the rest. They count against the invocation cap and
are logged on the run like any other call.

**Two things do not depend on what the model chose** (BE Gaps 717/718). After
the paragraphs have passed the guards, any pre-fetched row whose alert is still
open (`alert_open`) and which no surviving paragraph cited gets one paragraph
appended, built from that row's own strings; and if the model asked no question
while an open duplicate pair sits unresolved in memory, one question is emitted
from the alert sentence itself. Both go through the same guards as model prose.
The prompt still says to do both -- it decides yield; these decide correctness
(CONVENTIONS hard rule 3).

**Nothing the model writes is trusted.** The final message is parsed as JSON,
deterministically; anything unparseable becomes zero paragraphs and an `error`
event, never a fallback that writes prose. Every surviving paragraph and the
question go through `validate_briefing_paragraph()` (task 35.5) before they are
yielded, and a failure is a drop, counted on `run.dropped` and logged -- not a
repair. Repairing a model's sentence about money means writing one, which is the
thing this feature exists not to do (CONVENTIONS hard rule 3).
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import date
from typing import Any, Iterator

from sqlmodel import Session

from agents.atlas_prompts import (
    BRIEFING_SYSTEM,
    INTERVIEW_INSTRUCTION,
    OUTPUT_FORMAT,
    briefing_user_prompt,
)
from services.atlas_contract import (
    AtlasContractError,
    BriefingEvent,
    BriefingParagraph,
    BriefingQuestion,
    Citation,
    validate_briefing_paragraph,
)
from services.atlas_tools import (
    BriefingRun,
    ToolContext,
    run_tool,
    tool_schemas,
)

logger = logging.getLogger(__name__)

__all__ = [
    "MAX_ROUNDS",
    "MAX_INVOCATIONS",
    "MAX_SECONDS",
    "run_briefing",
]

#: §8 ruling 2: starting numbers, deliberately not tuned before there is data to
#: tune them against. `atlas_briefings.tool_calls` (task 35.6) is what they will
#: be measured from.
MAX_ROUNDS = 6
MAX_INVOCATIONS = 12
MAX_SECONDS = 20.0

#: What each role is handed **before** its first turn -- BE Gap 716.
#:
#: The first live run showed the cost of leaving tool selection to the model: an
#: Admin called `list_lines`, found the screen full, and wrote the whole briefing
#: from it -- never `forecast`, never anything about an invoice that no skill
#: emits a line for. The four Admin needs (`feature_34_atlas.md` §2.3) cannot be
#: answered from one tool's rows, so the rows that answer them are fetched rather
#: than hoped for. The model may still call whatever it likes afterwards; this
#: only decides what it starts with.
#:
#: Keyed by `_role_from()`'s word, with `_PREFETCH_FALLBACK` for anyone else, so
#: a role added later is a line in this table rather than an `if`. Every entry is
#: dispatched through `run_tool()`, which re-checks visibility -- a role listed
#: here against a tool it may not see gets a refusal row, not a leak.
_PREFETCH: dict[str, tuple[str, ...]] = {
    "admin": ("list_lines", "invoices", "cash_position", "forecast"),
    "auditor": ("list_lines", "invoices"),
    "trainer": ("list_lines",),
    "loader": ("list_lines",),
}

#: A role nobody mapped starts where the prompt says to start, and nowhere else.
_PREFETCH_FALLBACK: tuple[str, ...] = ("list_lines",)

#: The reasons §3.3's `truncated` event carries. Named rather than inline so the
#: FE contract and the tests read the same three strings.
_ROUNDS = "rounds"  # hardcode-ok: this module's own cap names, the §3.3 wire enum
_INVOCATIONS = "invocations"  # hardcode-ok: §3.3 wire enum
_WALL_CLOCK = "wall_clock"  # hardcode-ok: §3.3 wire enum


# ═════════════════════════════════════════════════════════════════════════════
# Entry point
# ═════════════════════════════════════════════════════════════════════════════

def run_briefing(
    db: Session,
    ctx: ToolContext,
    *,
    today: date,
    llm: Any = None,
    role: str = "",
    rules: Any = None,
    run: BriefingRun | None = None,
) -> Iterator[BriefingEvent]:
    """Produce one briefing, as a stream of events.

    `llm` is injected for tests and for a caller that has already built a model;
    left `None` it is `get_llm_for_role("atlas")`, which is the only place in
    this feature a model is chosen (§3.4 -- every ATLAS Intelligence call is
    Terra, and nothing else changes model).

    `run` is injected the same way: the caller that will persist the briefing
    (task 35.6) needs the token counts, the cost, the tool call log and the drop
    count *after* the generator is exhausted, and a generator's return value is
    not reachable from a `for` loop. Passing the run in is how those come back.

    The `db` argument is the session the memory rules are read from when `rules`
    is not supplied; every other read goes through `ctx`.
    """
    run = run or BriefingRun(tenant_id=ctx.skill.tenant_id, user_id=ctx.user_id)
    started = time.monotonic()

    bound, model_name = _bind(llm, ctx)
    run.model = model_name

    caller_role = role or _role_from(ctx.grants)
    # Read once and kept: the prompt states them, and BE Gap 718's question test
    # ("has this workspace already ruled on this pair?") reads the same list.
    # Reading them twice would let the two halves disagree inside one briefing.
    rule_texts = [
        str(r) for r in (_rules_for(db, ctx) if rules is None else (rules or []))
    ]
    messages: list = [
        ("system", BRIEFING_SYSTEM + "\n\n" + INTERVIEW_INSTRUCTION + "\n\n" + OUTPUT_FORMAT),
        (
            "human",
            briefing_user_prompt(caller_role, ctx.grants, rule_texts, today),
        ),
    ]

    # BE Gap 716: the rows this role always needs, fetched before the model is
    # asked anything, and counted against the same cap as a call it makes itself.
    prefetched = _prefetch(ctx, run, caller_role)
    if prefetched:
        messages.append(("human", _prefetch_block(prefetched)))

    text, truncated = _loop(
        bound, messages, ctx, run, started, invocations=len(prefetched)
    )
    run.truncated = truncated
    _finish_accounting(run)

    if truncated:
        # §3.3's `truncated` frame comes first, then whatever the model had
        # already written, so a reader knows the briefing below is partial
        # before they read it rather than after.
        yield BriefingEvent(type="truncated", data={"reason": truncated})

    paragraphs, question, parse_error, extra_questions = _parse(text)
    run.dropped += extra_questions
    if parse_error:
        logger.warning(
            "ATLAS briefing output was not parseable for tenant %s: %s",
            ctx.skill.tenant_id, parse_error,
        )
        yield BriefingEvent(type="error", data={"message": parse_error})

    cited: set[str] = set()
    for paragraph in paragraphs:
        event = _guarded(paragraph, run, ctx, kind="paragraph")
        if event is not None:
            cited |= _cited_ids(paragraph)
            yield event

    # BE Gap 717: the invariant does not depend on what the model chose. Any
    # invoice whose alert is still open and which no surviving paragraph cited
    # gets one paragraph, built from that row's own strings.
    for flagged in _uncited_open_alerts(db, ctx, prefetched, cited):
        event = _guarded(flagged, run, ctx, kind="paragraph")
        if event is not None:
            yield event

    if question is None:
        # BE Gap 718: neither does the interview. A duplicate pair nobody has
        # ruled on is a question whether or not the model thought to ask it.
        question = _duplicate_question(prefetched, rule_texts)
    if question is not None:
        event = _guarded(question, run, ctx, kind="question")
        if event is not None:
            yield event

    yield BriefingEvent(
        type="done",
        data={
            "cached": False,
            "model": run.model,
            "dropped_paragraphs": run.dropped,
        },
    )


# ═════════════════════════════════════════════════════════════════════════════
# The loop
# ═════════════════════════════════════════════════════════════════════════════

def _prefetch(
    ctx: ToolContext, run: BriefingRun, role: str
) -> list[tuple[str, list[dict]]]:
    """The role's opening rows, dispatched through `run_tool()` — BE Gap 716.

    Through `run_tool()` and not through the adapters directly, which is the
    whole point: visibility is re-checked, the ids land in `run.emitted_ids` so a
    paragraph about them is citable, the figures land in `run.rendered_tokens` so
    a paragraph about them is sayable, and each dispatch is logged on
    `run.tool_calls` exactly as a model-chosen call is. A pre-fetch the run does
    not record would be evidence the briefing could use and nobody could audit.
    """
    out: list[tuple[str, list[dict]]] = []
    for name in _PREFETCH.get(str(role or "").strip().lower(), _PREFETCH_FALLBACK):
        result = run_tool(name, {}, ctx, run)
        out.append((name, result.rows))
    return out


def _prefetch_block(prefetched: list[tuple[str, list[dict]]]) -> str:
    """The pre-fetched rows as one context message.

    A plain human message rather than `ToolMessage`s, deliberately: a tool
    message must answer an assistant message that asked for it, and inventing an
    assistant turn so the shape typechecks would mean putting words the model
    never said into its own history. This block says what it is, names the tool
    each group came from, and carries the rows verbatim as the JSON the model
    would have received had it asked.
    """
    parts = [
        "These tools have already been run for you. Their rows are below, and "
        "they are evidence exactly as a tool call's rows are -- you may cite them "
        "and you do not need to call these tools again:"
    ]
    for name, rows in prefetched:
        parts.append(f"\n{name} ({len(rows)} rows):\n" + json.dumps(rows, default=str))
    return "\n".join(parts)


def _loop(
    bound: Any,
    messages: list,
    ctx: ToolContext,
    run: BriefingRun,
    started: float,
    *,
    invocations: int = 0,
) -> tuple[str, str | None]:
    """Round after round until the model writes, or a cap stops it.

    Returns the final text (empty when a cap fired before the model wrote) and
    the truncation reason, if any.

    Every cap is tested *before* the work it would authorise, which is what makes
    the numbers mean what they say: `MAX_INVOCATIONS = 12` means twelve tool
    calls run and the thirteenth is refused, not that thirteen run and the
    thirteenth is reported.

    `invocations` starts at whatever the pre-fetch already spent (BE Gap 716), so
    the cap counts every dispatch in the briefing rather than only the ones the
    model asked for -- four free calls on top of twelve would be a sixteen-call
    budget nobody wrote down.
    """
    from langchain_core.messages import ToolMessage

    rounds = 0

    while True:
        if rounds >= MAX_ROUNDS:
            return "", _ROUNDS
        if time.monotonic() - started > MAX_SECONDS:
            return "", _WALL_CLOCK

        message = bound.invoke(messages)
        rounds += 1
        _count_tokens(run, message)
        messages.append(message)

        calls = list(getattr(message, "tool_calls", None) or [])
        if not calls:
            return _text_of(message), None

        for call in calls:
            if invocations >= MAX_INVOCATIONS:
                return "", _INVOCATIONS

            invocations += 1
            result = run_tool(call.get("name", ""), call.get("args"), ctx, run)
            messages.append(
                ToolMessage(
                    content=json.dumps(result.rows, default=str),
                    tool_call_id=str(call.get("id") or ""),
                    name=str(call.get("name") or ""),
                )
            )

            # Checked after each dispatch, not only per round: one slow tool can
            # spend the whole budget inside a single round, and a wall clock only
            # tested at the top of the loop would not notice until the next one.
            if time.monotonic() - started > MAX_SECONDS:
                return "", _WALL_CLOCK


def _bind(llm: Any, ctx: ToolContext) -> tuple[Any, str]:
    """The model with this caller's tools bound, and the deployment it names.

    The schema list comes from `tool_schemas(ctx.grants)`, so a tool the caller
    may not use is never described to the model -- §3.2's "absent, not refused".
    """
    from utils.llm import get_llm_for_role
    from utils.model_registry import resolve_model

    model = llm if llm is not None else get_llm_for_role("atlas")
    return model.bind_tools(tool_schemas(ctx.grants)), resolve_model("atlas").deployment


def _count_tokens(run: BriefingRun, message: Any) -> None:
    """Accumulate `usage_metadata` across rounds (§3.6).

    Fail-soft: a provider that does not return usage gives a cost of zero, and a
    briefing is not worth failing over an accounting field. The zero is visible
    in `atlas_briefings.cost_usd`, which is where §3.6 says the real figure gets
    established from.
    """
    usage = getattr(message, "usage_metadata", None) or {}
    try:
        run.tokens_in += int(usage.get("input_tokens") or 0)
        run.tokens_out += int(usage.get("output_tokens") or 0)
    except (AttributeError, TypeError, ValueError):  # pragma: no cover - defensive
        pass


def _finish_accounting(run: BriefingRun) -> None:
    from utils.model_registry import cost_usd

    run.cost_usd = cost_usd(run.model, run.tokens_in, run.tokens_out)


def _text_of(message: Any) -> str:
    """An `AIMessage`'s content as a string, whatever shape the provider used."""
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in content
        )
    return str(content or "")


def _role_from(grants) -> str:
    """The word the prompt uses for this caller, from their grants.

    Derived rather than passed when the caller did not say, because `GrantSet` is
    what the tools were filtered on: describing someone as an Admin to a model
    that was handed a Trainer's tool list would be the one inconsistency the
    prompt cannot recover from.
    """
    if getattr(grants, "is_admin", False):
        return "admin"
    if getattr(grants, "can_audit", False):
        return "auditor"
    if getattr(grants, "can_train", False):
        return "trainer"
    if getattr(grants, "can_load", False):
        return "loader"
    return "user"


def _rules_for(db: Session, ctx: ToolContext) -> list[str]:
    """Active memory rules as plain strings, for the prompt's context block.

    Fail-soft, and read here rather than in `atlas_prompts`: the prompt module
    stays free of database access, and a run whose memory read fails still
    produces a briefing -- one without the lessons, which is worse than a full
    briefing and much better than none.
    """
    try:
        from services.atlas_memory import list_rules

        out = []
        for rule in list_rules(db, ctx.skill.tenant_id):
            if getattr(rule, "active", True) and getattr(rule, "text", ""):
                out.append(str(rule.text))
        return out
    except Exception:  # pragma: no cover - a missing lesson is not a failed briefing
        logger.warning(
            "ATLAS briefing could not read memory rules for tenant %s",
            ctx.skill.tenant_id, exc_info=True,
        )
        return []


# ═════════════════════════════════════════════════════════════════════════════
# Parsing the model's answer
# ═════════════════════════════════════════════════════════════════════════════

def _strip_fence(text: str) -> str:
    """Remove a markdown fence the model was told not to write.

    Tolerated because it is a formatting habit rather than a content failure, and
    because the alternative -- dropping a correct briefing over three backticks --
    is the kind of brittleness that gets a guard switched off.
    """
    stripped = str(text or "").strip()
    if not stripped.startswith("```"):
        return stripped
    body = stripped[3:]
    if body[:4].lower().startswith("json"):
        body = body[4:]
    end = body.rfind("```")
    return (body[:end] if end != -1 else body).strip()


def _parse(
    text: str,
) -> tuple[list[BriefingParagraph], BriefingQuestion | None, str, int]:
    """The model's JSON, or nothing and a reason.

    Deterministic and unforgiving by design. There is no salvage path that turns
    prose into a paragraph: an answer this function cannot read produces an
    `error` event and an empty briefing, because the only alternative is to
    fabricate structure around a sentence nobody validated.
    """
    body = _strip_fence(text)
    if not body:
        return [], None, "", 0

    try:
        payload = json.loads(body)
    except (ValueError, TypeError) as exc:
        return [], None, f"the briefing model did not return readable JSON: {exc}", 0
    if not isinstance(payload, dict):
        return [], None, "the briefing model returned JSON that is not an object", 0

    paragraphs: list[BriefingParagraph] = []
    for raw in payload.get("paragraphs") or []:
        try:
            paragraphs.append(
                BriefingParagraph(
                    text=str((raw or {}).get("text") or ""),
                    citations=_citations(raw),
                )
            )
        except Exception:
            # One malformed paragraph is not a malformed briefing. It is not
            # repaired either -- it simply never existed.
            logger.warning("ATLAS briefing dropped an unreadable paragraph")

    question = None
    extras = 0
    for index, raw in enumerate(_questions(payload)):
        if index == 0:
            try:
                question = BriefingQuestion(
                    text=str((raw or {}).get("text") or ""),
                    citations=_citations(raw),
                    answer_kind=str((raw or {}).get("answer_kind") or "free_text"),
                )
            except Exception:
                logger.warning("ATLAS briefing dropped an unreadable question")
        else:
            extras += 1

    if extras:
        # §3.1 step 6: one question maximum, extras dropped. Counted on the run
        # through the same counter as a guard drop, because from the user's side
        # it is the same thing -- the model said something that did not reach
        # them, and the `done` event says how much.
        logger.info("ATLAS briefing dropped %s extra question(s)", extras)
    return paragraphs, question, "", extras


def _questions(payload: dict) -> list[dict]:
    """Whatever the model put in `question`, as a list.

    A model handed "ask at most one question" sometimes answers with a list of
    them. Accepting the list and keeping the first is how the cap becomes
    observable: the extras are counted and dropped, where a parser that only
    read an object would silently keep whichever one happened to be there.
    """
    raw = payload.get("question")
    if raw is None:
        raw = payload.get("questions")
    if raw is None:
        return []
    if isinstance(raw, dict):
        return [raw]
    if isinstance(raw, (list, tuple)):
        return [q for q in raw if isinstance(q, dict)]
    return []


def _citations(raw: Any) -> list[Citation]:
    out: list[Citation] = []
    for item in (raw or {}).get("citations") or []:
        if not isinstance(item, dict):
            continue
        try:
            out.append(
                Citation(
                    tool=str(item.get("tool") or ""),
                    record_kind=str(item.get("record_kind") or ""),
                    record_id=str(item.get("record_id") or ""),
                )
            )
        except Exception:
            logger.warning("ATLAS briefing dropped an unreadable citation")
    return out


# ═════════════════════════════════════════════════════════════════════════════
# Deterministic guarantees — BE Gaps 717 and 718
#
# Everything below runs *after* the model has written and *before* the frames
# reach the wire, and none of it asks the model anything. The prompt still says
# "an invoice's alert is the headline for it" and "ask one question when
# something is genuinely ambiguous", and that is guidance -- it decides yield.
# These two functions decide correctness (CONVENTIONS hard rule 3): a flagged
# invoice is reported and an unresolved duplicate pair is asked about, whatever
# the model happened to pick.
#
# Both are built **only out of strings a tool already returned this run**. They
# compose nothing, re-derive nothing and round nothing, and they go through the
# same `_guarded()` as a model paragraph -- so an appended paragraph that
# somehow named an unemitted id or an unrendered number is dropped exactly as
# the model's would be, rather than being trusted because this file wrote it.
# ═════════════════════════════════════════════════════════════════════════════

#: The one producer's near-duplicate sentence, as `_alert_prose()` leaves it
#: (`queue_worker/handlers.py::handle_process_invoice`, Gap 503):
#: "Possible duplicate: <vendor> invoice <other> has the same date and total
#: (<amount>) but a different number (<this>). Check whether this is a re-issue."
#: Matched rather than interpreted: the two invoice numbers and the party are
#: read back out of the sentence the pipeline wrote, so the question ATLAS asks
#: names exactly what the system flagged. A message this does not match produces
#: no question at all -- BE Gap 718 adds a question ATLAS can ground, never one
#: it guessed the shape of.
_DUPLICATE_ALERT_RE = re.compile(
    r"duplicate:\s*(?P<party>.+?)\s+invoice\s+(?P<other>\S+)\s+has the same date"
    r".*?different number\s*\(\s*(?P<this>[^)]+?)\s*\)",
    re.IGNORECASE | re.DOTALL,
)


def _cited_ids(item: Any) -> set[str]:
    """Every record id one paragraph or question rests on."""
    return {
        str(getattr(c, "record_id", "") or "")
        for c in (getattr(item, "citations", None) or [])
        if str(getattr(c, "record_id", "") or "")
    }


def _flagged_rows(prefetched: list[tuple[str, list[dict]]]) -> dict[str, dict]:
    """The open-alert rows this run pre-fetched, one entry per invoice.

    Keyed by invoice id, because the same invoice reaches the model twice on an
    Admin run -- once as a `list_lines` recommendation and once as an `invoices`
    row -- and a briefing that said the same thing twice about RAJ-2009 would be
    a worse defect than the one this closes. Each entry carries every id that
    *counts as having covered* that invoice (`citable`), so a paragraph citing
    either form suppresses the append.

    The `invoices` row is preferred for the text when there is one: it carries
    `party` and `invoice_number` as separate fields, where a recommendation
    carries a ranked headline. Row order is the pre-fetch order, so the output
    is stable across runs.
    """
    out: dict[str, dict] = {}
    for tool_name, rows in prefetched:
        for row in rows:
            if not row.get("alert_open"):
                continue
            messages = [str(m) for m in (row.get("alerts") or []) if str(m).strip()]
            if not messages:
                continue
            kind = str(row.get("record_kind") or "")
            record_id = str(row.get("record_id") or "")
            invoice_id = (
                record_id if kind == "invoice" else str(row.get("entity_id") or "")
            )
            if not invoice_id or not record_id:
                continue

            entry = out.setdefault(
                invoice_id,
                {"citable": set(), "row": row, "tool": tool_name, "messages": messages},
            )
            entry["citable"].add(record_id)
            if kind == "invoice":
                entry["row"] = row
                entry["tool"] = tool_name
                entry["messages"] = messages
    return out


def _headline_of(row: dict) -> str:
    """The row's own name for the thing, never composed here.

    An `invoices` row gives party and number; a `list_lines` row gives the
    headline the ranking already wrote. Both are copied.
    """
    if str(row.get("record_kind") or "") == "invoice":
        parts = [
            str(row.get("party") or "").strip(),
            str(row.get("invoice_number") or "").strip(),
        ]
        return " ".join(p for p in parts if p)
    return str(row.get("headline") or "").strip()


def _dismissed_for(db: Session, ctx: ToolContext) -> set[str]:
    """This caller's dismissals. Fail-soft: a failed read hides nothing."""
    try:
        from services.atlas_dismissals import dismissed_ids

        return dismissed_ids(db, ctx.skill.tenant_id, ctx.user_id)
    except Exception:  # pragma: no cover - defensive; a dismissal read is not the briefing
        logger.warning(
            "ATLAS briefing could not read dismissals for tenant %s",
            ctx.skill.tenant_id, exc_info=True,
        )
        return set()


def _is_dismissed(invoice_id: str, citable: set[str], dismissed: set[str]) -> bool:
    """Whether this caller has already put this invoice's line away.

    Two tests, because the two row kinds are dismissed under different ids.
    `list_lines` already drops a dismissed line, but the `invoices` row for the
    same invoice survives -- and every emitter's id ends in the invoice's own
    uuid (`audit-approve-<invoice id>`, `train-lowconf-<invoice id>`; the
    property `services/atlas_dismissals.py` documents and tests), so a dismissal
    naming that uuid is a dismissal of this invoice's work.
    """
    if citable & dismissed:
        return True
    return any(invoice_id in d for d in dismissed)


def _uncited_open_alerts(
    db: Session,
    ctx: ToolContext,
    prefetched: list[tuple[str, list[dict]]],
    cited: set[str],
) -> list[BriefingParagraph]:
    """One paragraph per flagged invoice the briefing did not mention — BE Gap 717.

    The guarantee this makes is narrow and worth stating exactly: *every invoice
    whose alert is still open, and which this caller has not dismissed, is named
    in the briefing.* It is not a claim that the model's paragraphs are good, and
    it does not edit them -- an appended paragraph is added after what the model
    wrote, in pre-fetch order, saying what the row says.
    """
    dismissed = _dismissed_for(db, ctx)
    out: list[BriefingParagraph] = []
    for invoice_id, entry in _flagged_rows(prefetched).items():
        if entry["citable"] & cited:
            continue
        if _is_dismissed(invoice_id, entry["citable"], dismissed):
            continue

        row = entry["row"]
        headline = _headline_of(row)
        body = " ".join(entry["messages"])
        text = (headline + " is still waiting on a decision. " + body) if headline else body
        out.append(
            BriefingParagraph(
                text=text,
                citations=[
                    Citation(
                        tool=str(entry["tool"]),
                        record_kind=str(row.get("record_kind") or ""),
                        record_id=str(row.get("record_id") or ""),
                    )
                ],
            )
        )
    return out


def _duplicate_question(
    prefetched: list[tuple[str, list[dict]]], rules: list[str]
) -> BriefingQuestion | None:
    """The one question a duplicate pair deserves — BE Gap 718.

    Asked only when **all** of these hold, which is why it is code rather than a
    sentence in the prompt:

    1. the model asked nothing (the caller checks this before calling);
    2. a pre-fetched row carries an open duplicate alert whose sentence names
       both numbers;
    3. no active memory rule mentions either number -- a workspace that has
       already told ATLAS "Rajesh Steel re-issues invoices" is not asked again,
       and that is the whole point of §7's memory.

    Returns at most one, from the first matching row in pre-fetch order.
    """
    haystack = " ".join(str(r).lower() for r in (rules or []))
    for entry in _flagged_rows(prefetched).values():
        row = entry["row"]
        for message in entry["messages"]:
            match = _DUPLICATE_ALERT_RE.search(message)
            if match is None:
                continue
            party = match.group("party").strip()
            other = match.group("other").strip()
            this = match.group("this").strip()
            if not other or not this:
                continue
            if this.lower() in haystack or other.lower() in haystack:
                continue
            return BriefingQuestion(
                text=(
                    (party + " " if party else "")
                    + this
                    + " looks like a copy of "
                    + other
                    + ". Is it a genuine second order?"
                ),
                citations=[
                    Citation(
                        tool=str(entry["tool"]),
                        record_kind=str(row.get("record_kind") or ""),
                        record_id=str(row.get("record_id") or ""),
                    )
                ],
                answer_kind="free_text",
            )
    return None


# ═════════════════════════════════════════════════════════════════════════════
# The guard, applied
# ═════════════════════════════════════════════════════════════════════════════

def _guarded(
    item: Any, run: BriefingRun, ctx: ToolContext, *, kind: str
) -> BriefingEvent | None:
    """One paragraph or question, checked before it is yielded.

    The single place task 35.5's guards are called from, which is what makes the
    falsification test meaningful: patch `validate_briefing_paragraph` here and
    uncited prose reaches the wire, so the guard is demonstrably load-bearing
    rather than decorative (Feature 34 §18.8's precedent).
    """
    try:
        validate_briefing_paragraph(item, run.emitted_ids, run.rendered_tokens)
    except AtlasContractError as exc:
        run.dropped += 1
        logger.warning(
            "ATLAS briefing dropped a %s for tenant %s: %s | citations=%s",
            kind, ctx.skill.tenant_id, exc,
            [c.model_dump() for c in getattr(item, "citations", []) or []],
        )
        return None

    data: dict[str, Any] = {
        "text": item.text,
        "citations": [c.model_dump() for c in item.citations],
    }
    if kind == "question":
        data["answer_kind"] = getattr(item, "answer_kind", "free_text")
    return BriefingEvent(type=kind, data=data)  # type: ignore[arg-type]
