"""Feature 23 (AI Control Tower) — Phase 3: answer scoring.

Three scores per answer, following the three definitions `agents/README.md`
§3.2 has named since before this module existed (and which nothing had ever
implemented):

  * **faithfulness** — does the answer only assert things the retrieved
    context/tool results actually support? Computed the way RAGAS defines it:
    decompose the answer into atomic claims, judge each claim independently
    against the context, score = supported claims / total claims.
  * **relevance** — does the answer address the question that was asked,
    without side-tracking?
  * **accuracy** — does the answer agree with the golden set's reference
    answer on the facts that reference answer asserts?

Why an LLM judge and not the `ragas` package
--------------------------------------------
Checked before deciding, not assumed:

  * Licensing is not the blocker — ragas is Apache-2.0, same as most of this
    stack.
  * Dependency weight is. `ragas` is not currently installed here, and it pulls
    `datasets` (and through it `pyarrow`, `dill`, `multiprocess`, `xxhash`,
    `fsspec`) plus `pandas` and `nest-asyncio`. This backend's Docker images
    install with `uv sync --frozen` from one lockfile shared by the API and the
    queue worker — there is no separate "eval" image — so adding it would put
    several hundred MB of transitive dependencies into every production
    container to support a job that runs nightly and touches no request path.
  * The three metrics are, at bottom, three prompts. Reimplementing the two that
    matter here (claim-decomposed faithfulness, reference-compared accuracy) is
    ~100 lines against the model this application already has configured, with
    no new dependency and no second LLM client to configure.

Where this deliberately differs from ragas, stated plainly rather than left to
look like an oversight:

  * ragas' `answer_relevancy` generates N questions *from* the answer and takes
    the mean cosine similarity of their embeddings against the original
    question. That needs an embedding round-trip per generated question; this
    application's embeddings are the local BAAI/bge-m3 model, whose first load
    is a multi-GB download and which is mocked out (`MOCK_EMBEDDINGS`) in every
    non-live context. Relevance here is a direct LLM judgement against the same
    written definition instead. It is the same *definition*, not the same
    *estimator* — a relevance number from this module is not comparable to a
    published ragas benchmark figure, and should not be reported as one.
  * ragas' `context_precision` (its third metric) is not implemented: it grades
    a retriever's ranking, and the question this feature asks is about the
    answer. Worth adding when retrieval tuning is the subject.

Four judge failure modes found by actually running it (2026-08-21)
------------------------------------------------------------------
All four were found on real runs of `scripts/run_agent_eval.py` against
gpt-5-mini, not reasoned about in advance, and all four systematically
*under*-scored correct answers — worth recording because they are the shape of
thing that makes an unvalidated eval harness worse than none:

1. **An empty result read as an absence of evidence.** A correct "no records were
   found for Nonexistent Holdings" answer scored faithfulness 0/3, because the
   judge treated "No records found matching the query criteria." as no context
   rather than as a real, negative result. The verdict prompt now says so
   explicitly, at length, because one clause saying it was not enough.
2. **Capability text decomposed into claims.** A greeting listing what the
   assistant can do ("I can show you spend summaries...") decomposed into
   "claims", which then had no context to support them, scoring the cheapest and
   most obviously-correct turn in the sample 0.00. The decomposition prompt now
   rules capability/greeting text out with examples.

The two below survived that first fix, were recorded in
`feature_23_ai_control_tower.md` as unresolved, and are fixed here (also
2026-08-21, later the same day). Both were diagnosed from the persisted output of
the run that exhibited them (`tests/agent_eval_output.json`), not from a guess:

3. **A correct "no records found" answer still scored faithfulness 0.00 — because
   the judge was never shown the query.** Failure mode 1's fix added an emphatic
   rule saying an empty result is evidence, and it was still not enough, which
   looked like judge stubbornness and was not. The real cause is visible in the
   run: the evidence handed to the judge was the whole of
   ``"DATABASE RESULTS:\nNo records found matching the query criteria."`` while
   the two claims under judgement were "No records were found for *Nonexistent
   Holdings* *last quarter*" and "There were no recorded spends with
   *Nonexistent Holdings* during *the period*". Nothing in that evidence says
   which vendor or which period was queried, so under rules 1-2 ("judge only
   against the context"; "a plausible inference the context does not contain is
   NOT supported") the verdict was *correct on the evidence it was given*. Rule 5
   already anticipated this — "supported when the context shows that query was
   the one executed" — but its precondition could never be met, because the
   executed query was not part of the context. The scorer never had a way to
   distinguish "the vendor does not exist" from "the tool was asked about a
   different vendor entirely", which is exactly the confusion Gap 224's
   false-confident-zero is made of. Fixed two ways, both general:

   * `score_faithfulness()`/`score_answer()` take ``executed_queries`` — the SQL
     and/or the tool calls *with their arguments* that produced the results — and
     render it as its own evidence block. `scripts/run_agent_eval.py` now records
     and passes it. An empty result is now attributable to a query.
   * The verdict rubric no longer bolts the empty-result case on as an exception
     after three absolute rules. Each verdict must first assign a ``claim_type``
     (``positive_fact`` / ``absence`` / ``query_scope`` / ``non_factual``), and
     the evidence standard is stated per type. A rule the judge has to *apply*
     before deciding is obeyed; a carve-out it reads after forming a verdict is
     not.
   * ``non_factual`` verdicts leave the denominator instead of counting as
     unsupported. That is a third instance of the same family as failure mode 2:
     any pleasantry the decomposition step failed to filter used to cost real
     score.
4. **The same correct refusal scored relevance 1.0 on one path and 0.0 on the
   other, in the same run.** ``out_of_scope_code_request`` — "write me a python
   script to reverse a string" — was declined correctly by both paths in near
   identical words, and scored 0.0 (default) against 1.0 (SAGE). The greeting case
   showed the same instability at lower amplitude (0.7 against 1.0). The cause is
   structural, not random: every numeric anchor in the relevance rubric was
   phrased as *"answers what was asked"*, and a refusal by construction does not
   answer what was asked, so the anchors themselves drive a judge to 0.0. The
   three carve-outs (clarification, no-results, refusal) sat *after* the anchors
   as prose and contradicted them, so whether a given call honoured them was a
   coin flip. Same shape as failure mode 1: a rule that fights the rubric it is
   appended to does not win reliably.

   Fixed by making the judge **classify before it scores**: `RelevanceVerdict`
   carries an ``answer_kind`` the model must choose, and for the three kinds whose
   correct relevance is definitional rather than a matter of degree
   (``no_results_report``, ``out_of_scope_refusal``, ``capability_or_greeting`` →
   1.0; ``off_topic`` → 0.0) the score is fixed *in code* by
   ``RELEVANCE_KIND_SCORES``, not left to the judge's number. Only
   ``direct_answer`` and ``clarifying_question`` — where relevance genuinely is a
   matter of degree — use the judge's own 0-1 score. Two paraphrases of the same
   refusal now cannot score differently unless the judge disagrees about what kind
   of response it is looking at, which is a far more stable judgement than a
   free-floating number. A judge that returns no ``answer_kind`` at all (an older
   double, a malformed response) falls back to the raw score rather than failing.

Any figure produced before this note existed is not comparable to figures after
it. That is a property of every LLM-judged metric and the reason the pass floors
below are a policy choice recorded in code rather than an intrinsic threshold.
In particular the 2026-08-21 measurement round's faithfulness/relevance means
predate fixes 3 and 4 and must not be compared against anything produced after
them.

Cost
----
Judging is itself billable — three to four extra model round-trips per graded
answer. Every judge call goes through the same `tracked_llm_call()` wrapper as
the product's own calls, under `eval.*` agent names, so eval spend shows up in
Phase 2's cost rollup as its own line rather than hiding inside the totals or
being invisible. Anything counting a *product* turn's LLM calls must therefore
filter `eval.*` out (`scripts/run_agent_eval.py` does, by only counting events
emitted inside the turn itself).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from pydantic import BaseModel, Field

from telemetry import tracked_llm_call

logger = logging.getLogger(__name__)


# What counts as a pass. Deliberately three separate floors rather than one
# averaged score: an answer that invents a figure (faithfulness 0.5) is not
# redeemed by being extremely on-topic (relevance 1.0), and averaging is exactly
# what would let it be. A run fails if any scored dimension is below its floor.
FAITHFULNESS_FLOOR = 0.80
RELEVANCE_FLOOR = 0.70
ACCURACY_FLOOR = 0.70

# Guard on the claim decomposition. A long answer with a results table appended
# can decompose into dozens of claims; past this the marginal claim adds cost,
# not signal.
MAX_CLAIMS = 12

# How much of the context the judge is shown. Faithfulness is judged against the
# *whole* evidence set, so this is generous — but a 200-row markdown table in
# every judge prompt is a real cost, and the claims being judged are prose.
MAX_CONTEXT_CHARS = 12000

# The executed-query block is small by nature (one SQL statement, or a handful of
# tool calls with their arguments) and is the *only* thing that makes a negative
# result attributable — see failure mode 3. Given its own, tighter budget so a
# huge results table can never crowd it out of the prompt.
MAX_QUERY_CHARS = 3000


# ---------------------------------------------------------------------------
# Claim types — the evidence standard is per type, not one rule for all claims
# ---------------------------------------------------------------------------
# Failure mode 3: an "absence" claim and a "positive_fact" claim need opposite
# treatment against the same empty result set, and a single rubric that tries to
# cover both with a carve-out loses to its own earlier rules. The judge assigns
# the type first; these names are the vocabulary it assigns from.
CLAIM_TYPE_POSITIVE = "positive_fact"
CLAIM_TYPE_ABSENCE = "absence"
CLAIM_TYPE_QUERY_SCOPE = "query_scope"
CLAIM_TYPE_NON_FACTUAL = "non_factual"

#: Claims of this type are dropped from the faithfulness denominator entirely
#: rather than counted unsupported. Same family as failure mode 2: a pleasantry
#: the decomposition step failed to filter must cost nothing, not cost score.
_UNGRADEABLE_CLAIM_TYPES = frozenset({CLAIM_TYPE_NON_FACTUAL})


# ---------------------------------------------------------------------------
# Relevance response kinds — classify first, then score
# ---------------------------------------------------------------------------
# Failure mode 4: for some response shapes "how relevant is this" is not a matter
# of degree at all, it is definitional, and leaving it to a free-floating 0-1
# number is what let one correct refusal score 1.0 on one path and 0.0 on the
# other in the same run. The judge picks the kind; the policy below decides the
# score for the kinds that have one. `None` means "the judge's own number".
KIND_DIRECT_ANSWER = "direct_answer"
KIND_CLARIFYING_QUESTION = "clarifying_question"
KIND_NO_RESULTS_REPORT = "no_results_report"
KIND_OUT_OF_SCOPE_REFUSAL = "out_of_scope_refusal"
KIND_CAPABILITY_OR_GREETING = "capability_or_greeting"
KIND_OFF_TOPIC = "off_topic"

RELEVANCE_KIND_SCORES: dict[str, Optional[float]] = {
    # Relevance is a matter of degree here, so the judge scores it.
    KIND_DIRECT_ANSWER: None,
    KIND_CLARIFYING_QUESTION: None,
    # These three ARE the relevant response to what was asked, by definition.
    # Whether they are *correct* is faithfulness/accuracy's job, not this one.
    KIND_NO_RESULTS_REPORT: 1.0,
    KIND_OUT_OF_SCOPE_REFUSAL: 1.0,
    KIND_CAPABILITY_OR_GREETING: 1.0,
    # And this one is definitionally irrelevant.
    KIND_OFF_TOPIC: 0.0,
}


# ---------------------------------------------------------------------------
# Judge output schemas
# ---------------------------------------------------------------------------


class ClaimList(BaseModel):
    """The answer, broken into standalone factual assertions."""

    model_config = {"extra": "forbid"}

    claims: list[str] = Field(
        default_factory=list,
        description=(
            "Each factual assertion the answer makes, rewritten to stand alone "
            "(no pronouns referring to other claims). Exclude pleasantries, "
            "hedges, and offers to help further -- they assert nothing."
        ),
    )


class ClaimVerdict(BaseModel):
    model_config = {"extra": "forbid"}

    claim: str = Field(description="The claim being judged, copied verbatim.")
    claim_type: str = Field(
        default=CLAIM_TYPE_POSITIVE,
        description=(
            "What kind of assertion this claim is, decided BEFORE judging it: "
            "'positive_fact' (asserts a value -- an amount, a date, a vendor, a "
            "count), 'absence' (asserts that nothing was found / nothing is "
            "recorded / no such thing exists), 'query_scope' (restates what was "
            "looked for rather than what was found), or 'non_factual' (a "
            "pleasantry, an offer of help, a question back to the user, a "
            "statement about what the assistant can do)."
        ),
    )
    supported: bool = Field(
        description="True only if the evidence supports this claim, by the standard for its claim_type."
    )
    reason: str = Field(default="", description="One short sentence of justification.")


class FaithfulnessVerdicts(BaseModel):
    model_config = {"extra": "forbid"}

    verdicts: list[ClaimVerdict] = Field(default_factory=list)


class ScoreWithReason(BaseModel):
    model_config = {"extra": "forbid"}

    score: float = Field(description="A number between 0.0 and 1.0 inclusive.")
    reason: str = Field(default="", description="One short sentence of justification.")


class RelevanceVerdict(BaseModel):
    """Classify the response kind first, then score it.

    See failure mode 4 in the module docstring: the score field is only consulted
    for the kinds where relevance is genuinely a matter of degree.
    """

    model_config = {"extra": "forbid"}

    answer_kind: str = Field(
        default=KIND_DIRECT_ANSWER,
        description=(
            "What kind of response this is, chosen BEFORE scoring: "
            "'direct_answer', 'clarifying_question', 'no_results_report', "
            "'out_of_scope_refusal', 'capability_or_greeting', or 'off_topic'."
        ),
    )
    score: float = Field(
        default=1.0,
        description=(
            "0.0-1.0. Only used for 'direct_answer' and 'clarifying_question'; "
            "the other kinds have a fixed relevance and this number is ignored."
        ),
    )
    reason: str = Field(default="", description="One short sentence of justification.")


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------


@dataclass
class EvalScores:
    """The answer scores plus why each is what it is.

    A `None` score means "not scored" and never "scored zero": no reference
    answer to compare against, an empty answer, or a judge call that failed.
    `passed` is computed only over the dimensions that actually produced a
    number.

    Two groups of scores, deliberately kept apart:

      * **Answer-level** (`faithfulness`, `relevance`, `accuracy`) — the original
        three, and the only three `decide_pass()` looks at. Their floors are the
        pass policy and their trend is comparable across the whole history of
        this table.
      * **Component-level** (`context`, `orchestration`, `persona`) — Feature
        23's "which part of the pipeline is broken" decomposition. Added
        2026-08-21, additive and inert: they are recorded and trended, they do
        **not** feed `passed`. Folding them in would silently redefine what a
        pass means halfway through the series, which is the one thing a trend
        must not do.
    """

    faithfulness_score: Optional[float] = None
    relevance_score: Optional[float] = None
    accuracy_score: Optional[float] = None
    # Component-level. See the class docstring for why these are not in `passed`.
    context_score: Optional[float] = None
    orchestration_score: Optional[float] = None
    persona_score: Optional[float] = None
    passed: bool = False
    notes: list[str] = field(default_factory=list)
    claims: list[str] = field(default_factory=list)
    judge_llm_calls: int = 0

    def note_text(self) -> str:
        return " | ".join(self.notes)


# ---------------------------------------------------------------------------
# Judge plumbing
# ---------------------------------------------------------------------------


def _invoke_structured(llm: Any, schema: type[BaseModel], prompt: str, agent_name: str):
    """One judge round-trip, instrumented, returning None instead of raising.

    A judge that fails must degrade to "not scored" — the alternative is an eval
    harness that throws away a real measured latency/call-count because the
    grader had a bad minute.
    """
    try:
        structured = llm.with_structured_output(schema)
        with tracked_llm_call(agent_name, llm=llm):
            return structured.invoke(prompt)
    except Exception as e:  # pragma: no cover - exercised by the judge-failure test
        logger.warning("Eval judge call %s failed: %s", agent_name, e)
        return None


def _clamp(value: Any) -> Optional[float]:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return None


def _truncate(text: str, limit: int) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n... (truncated for the judge prompt)"


# ---------------------------------------------------------------------------
# The three metrics
# ---------------------------------------------------------------------------


def decompose_claims(answer: str, llm: Any) -> tuple[list[str], int]:
    """Break an answer into atomic, standalone factual claims (RAGAS step 1)."""
    if not (answer or "").strip():
        return [], 0

    prompt = (
        "Break the ANSWER below into its atomic factual claims.\n\n"
        "Rules:\n"
        "1. One assertion per claim, rewritten so it stands alone without the "
        "surrounding sentences.\n"
        "2. A claim is something that could be checked against THIS TENANT'S "
        "invoice data: an amount, a date, a vendor, a status, a count, a "
        "relationship between them.\n"
        "3. Do NOT emit claims for greetings, offers of further help, formatting, "
        "or statements about what the assistant can do -- those assert nothing "
        "about the data. This is not a minor exclusion: a capability list is the "
        "usual content of a greeting, and every line of it ('I can show you spend "
        "summaries', 'try asking which vendor you spend the most with', 'you can "
        "explore your invoices') must be excluded. An answer that is entirely "
        "greeting and capability text yields ZERO claims -- return an empty list, "
        "do not manufacture one.\n"
        "4. A question put back to the user is not a claim. Neither is a refusal, "
        "an apology, or a suggestion about how to rephrase or broaden a search.\n"
        "5. Copy the wording from the answer; do not correct, interpret or "
        "improve it.\n\n"
        f"ANSWER:\n{_truncate(answer, MAX_CONTEXT_CHARS)}\n"
    )
    result = _invoke_structured(llm, ClaimList, prompt, "eval.claim_decomposition")
    if result is None:
        return [], 1
    claims = [c.strip() for c in (result.claims or []) if isinstance(c, str) and c.strip()]
    return claims[:MAX_CLAIMS], 1


def score_faithfulness(
    answer: str,
    context: str,
    llm: Any,
    executed_queries: Optional[str] = None,
) -> tuple[Optional[float], list[str], list[str], int]:
    """Supported claims / total claims, judged one claim at a time.

    `executed_queries` is the SQL and/or the tool calls **with their arguments**
    that produced `context`. It is part of the evidence, not decoration: without
    it a judge cannot tell an empty result set for the vendor that was asked about
    from an empty result set for some other vendor entirely, and so cannot support
    a correct "nothing was found for X" claim at all (failure mode 3 in the module
    docstring). Optional so existing callers keep working, but a caller that has
    it and does not pass it is measuring faithfulness against half the evidence.

    Returns `(score, claims, notes, judge_call_count)`. Score is None when there
    was nothing to judge (no claims) or the judge could not be reached — never
    0.0, which would be indistinguishable from "every claim was fabricated".
    """
    notes: list[str] = []
    claims, calls = decompose_claims(answer, llm)
    if not claims:
        notes.append("faithfulness: not scored (no factual claims in the answer)")
        return None, [], notes, calls

    query_block = (executed_queries or "").strip()
    if not (context or "").strip() and not query_block:
        # Nothing ran, nothing was retrieved, and the answer still asserted facts.
        # That is the unfaithful case by definition, and it is a real 0.0, not an
        # absent score. Note the precondition: with a query block present this
        # branch is not taken, because "the tool ran and matched nothing" is
        # evidence and gets judged like any other evidence.
        notes.append(f"faithfulness: 0.00 ({len(claims)} claims asserted with no tool context at all)")
        return 0.0, claims, notes, calls

    numbered = "\n".join(f"{i + 1}. {c}" for i, c in enumerate(claims))
    query_section = (
        "QUERIES / TOOL CALLS THAT PRODUCED THE RESULTS BELOW "
        f"(this is evidence too -- it is what was looked for):\n{_truncate(query_block, MAX_QUERY_CHARS)}\n\n"
        if query_block
        else "QUERIES / TOOL CALLS THAT PRODUCED THE RESULTS BELOW: (not recorded for this turn)\n\n"
    )
    prompt = (
        "You are checking an assistant's answer for faithfulness to its evidence.\n\n"
        "The EVIDENCE is two things together: the queries/tool calls that were "
        "made, and the results they returned. Both count. A result set that came "
        "back empty is a real, negative finding about the thing the query asked "
        "for -- it is NOT an absence of evidence.\n\n"
        "For EACH claim below, do two things IN THIS ORDER:\n"
        "  STEP 1 - assign a `claim_type`. Decide what kind of assertion it is "
        "before you decide anything about whether it holds:\n"
        f"    * '{CLAIM_TYPE_POSITIVE}' -- asserts a value: an amount, a date, a "
        "vendor name, a status, a count, a relationship between them.\n"
        f"    * '{CLAIM_TYPE_ABSENCE}' -- asserts that nothing was found, that "
        "there is no recorded spend, that no matching invoice exists, that some "
        "figure is not stored or not tracked in the data.\n"
        f"    * '{CLAIM_TYPE_QUERY_SCOPE}' -- restates what was looked for (the "
        "vendor asked about, the period asked about) rather than what was found.\n"
        f"    * '{CLAIM_TYPE_NON_FACTUAL}' -- a pleasantry, an offer of further "
        "help, a question back to the user, a refusal, or a statement about what "
        "the assistant can do. Asserts nothing about the data.\n"
        "  STEP 2 - decide `supported`, using the standard FOR THAT TYPE:\n"
        f"    * '{CLAIM_TYPE_POSITIVE}': supported only if the results state it, "
        "or it follows directly from what the results state. A plausible "
        "inference the evidence does not actually contain is NOT supported. A "
        "number must match the evidence's number exactly, rounding and thousands "
        "separators aside.\n"
        f"    * '{CLAIM_TYPE_ABSENCE}': supported if the queries/tool calls show "
        "that this thing was actually looked for AND the results came back empty "
        "or without it -- e.g. 'No records found matching the query criteria.', "
        "an empty results table, a zero row count, or a results set that simply "
        "has no such column/field. This is the normal case for a correct 'nothing "
        "was found' answer and it must be marked supported=true. It is unsupported "
        "only when the evidence shows the opposite (the thing IS in the results), "
        "or when nothing resembling that query was run at all.\n"
        f"    * '{CLAIM_TYPE_QUERY_SCOPE}': supported if the queries/tool calls "
        "shown above are in fact about that vendor / period / filter. This is "
        "why the query block is given to you -- an empty results table cannot "
        "tell you what was searched for, and the query can.\n"
        f"    * '{CLAIM_TYPE_NON_FACTUAL}': set supported=true and move on. These "
        "are excluded from the score entirely; they are neither faithful nor "
        "unfaithful.\n"
        "Your own world knowledge is never evidence. Return one verdict per "
        "claim, in the same order, with the claim copied verbatim.\n\n"
        f"{query_section}"
        f"RESULTS (everything the assistant's tools returned):\n{_truncate(context, MAX_CONTEXT_CHARS) or '(no results recorded)'}\n\n"
        f"CLAIMS:\n{numbered}\n"
    )
    result = _invoke_structured(llm, FaithfulnessVerdicts, prompt, "eval.faithfulness")
    calls += 1
    if result is None or not result.verdicts:
        notes.append("faithfulness: not scored (judge unavailable)")
        return None, claims, notes, calls

    verdicts = result.verdicts[: len(claims)]
    gradeable = [
        v for v in verdicts if (v.claim_type or CLAIM_TYPE_POSITIVE) not in _UNGRADEABLE_CLAIM_TYPES
    ]
    dropped = len(verdicts) - len(gradeable)
    if not gradeable:
        # Everything the decomposition emitted turned out to be pleasantry. Same
        # outcome as decomposing to zero claims: nothing to be faithful to.
        notes.append(
            f"faithfulness: not scored (all {len(verdicts)} claims were non-factual)"
        )
        return None, claims, notes, calls

    supported = sum(1 for v in gradeable if v.supported)
    score = supported / len(gradeable)
    unsupported = [v.claim for v in gradeable if not v.supported]
    note = f"faithfulness: {supported}/{len(gradeable)} claims supported"
    if dropped:
        note += f" ({dropped} non-factual claim(s) excluded)"
    notes.append(note)
    if unsupported:
        notes.append("unsupported: " + "; ".join(unsupported[:3]))
    return score, claims, notes, calls


def score_relevance(question: str, answer: str, llm: Any) -> tuple[Optional[float], list[str], int]:
    """Does the answer address the question actually asked?

    See the module docstring: this is ragas' *definition* of answer relevance,
    judged directly, not ragas' embedding-similarity estimator of it.

    Two-step by design (failure mode 4): the judge classifies the response kind,
    and only the kinds where relevance is a matter of degree get scored by the
    judge at all. The rest are fixed by `RELEVANCE_KIND_SCORES`, so two
    paraphrases of the same correct refusal cannot land on different numbers.
    """
    if not (answer or "").strip():
        return None, ["relevance: not scored (empty answer)"], 0

    prompt = (
        "Classify the ANSWER, then score it. Do the classification FIRST -- the "
        "kind you choose determines how relevance is judged, and for several "
        "kinds it determines the score outright.\n\n"
        "STEP 1 -- choose exactly one `answer_kind`:\n"
        f"  * '{KIND_DIRECT_ANSWER}' -- attempts to answer the question from the "
        "user's data.\n"
        f"  * '{KIND_CLARIFYING_QUESTION}' -- asks the user something back "
        "instead of answering, because the question was ambiguous.\n"
        f"  * '{KIND_NO_RESULTS_REPORT}' -- reports that nothing matching was "
        "found, or that the thing asked for is not recorded/not tracked in the "
        "data.\n"
        f"  * '{KIND_OUT_OF_SCOPE_REFUSAL}' -- declines because the request is "
        "outside what this assistant does (writing general code, general "
        "knowledge, anything unrelated to the user's invoices and this platform). "
        "An answer that declines AND offers an invoice-related alternative is "
        "still this kind -- the offer does not change what the response is.\n"
        f"  * '{KIND_CAPABILITY_OR_GREETING}' -- the question was a greeting or "
        "an 'what can you do' question, and the answer greets and/or describes "
        "what the assistant can help with.\n"
        f"  * '{KIND_OFF_TOPIC}' -- talks about something else entirely, and is "
        "not any of the above.\n\n"
        "STEP 2 -- score, from 0.0 to 1.0:\n"
        f"  * For '{KIND_DIRECT_ANSWER}': 1.0 = answers exactly what was asked, "
        "completely, nothing off-topic. 0.7 = answers it but is incomplete or "
        "padded with unrequested material. 0.4 = partially on topic; the central "
        "thing asked for is missing. 0.0 = does not address the question.\n"
        f"  * For '{KIND_CLARIFYING_QUESTION}': 1.0 = a specific question that "
        "would actually resolve the ambiguity. 0.4 = vague or asks about "
        "something the user already said. 0.0 = unrelated to the ambiguity.\n"
        "  * For every other kind the score is fixed by policy and your number is "
        "ignored -- just classify correctly and put 1.0.\n\n"
        "Judge RELEVANCE ONLY. Do NOT reward or penalise the answer for being "
        "factually right or wrong; separate checks handle that. In particular, a "
        "refusal, a clarification and a 'nothing found' report are all responses "
        "TO the question -- 'it did not give me the thing I asked for' is not a "
        "relevance failure when giving that thing would have been wrong.\n\n"
        f"QUESTION:\n{question}\n\n"
        f"ANSWER:\n{_truncate(answer, MAX_CONTEXT_CHARS)}\n"
    )
    result = _invoke_structured(llm, RelevanceVerdict, prompt, "eval.relevance")
    if result is None:
        return None, ["relevance: not scored (judge unavailable)"], 1

    kind = (getattr(result, "answer_kind", "") or "").strip().lower()
    judged = _clamp(getattr(result, "score", None))
    if kind in RELEVANCE_KIND_SCORES:
        fixed = RELEVANCE_KIND_SCORES[kind]
        score = judged if fixed is None else fixed
        source = "judged" if fixed is None else "fixed by kind"
    else:
        # An unrecognised (or absent) kind: fall back to the raw number rather
        # than losing the score. A judge double that predates this schema, or a
        # model that invented its own label, still produces a usable figure.
        score = judged
        kind = kind or "unclassified"
        source = "judged (kind not recognised)"

    reason = (getattr(result, "reason", "") or "").strip()[:160]
    note = (
        f"relevance: {score if score is not None else 'unparseable'} "
        f"[{kind}, {source}] ({reason})"
    )
    return score, [note], 1


def score_accuracy(
    question: str, expected_answer: Optional[str], actual_answer: str, llm: Any
) -> tuple[Optional[float], list[str], int]:
    """Agreement with the golden set's reference answer.

    Not string similarity: the reference answers in this repo's question banks
    are prose with a stated grading rubric ("the correct number/entity is
    required; a rounded restatement alongside the exact figure does not fail"),
    so the comparison has to be semantic on the asserted facts.
    """
    if not (expected_answer or "").strip():
        return None, ["accuracy: not scored (no reference answer for this case)"], 0
    if not (actual_answer or "").strip():
        return 0.0, ["accuracy: 0.00 (empty answer)"], 0

    prompt = (
        "Compare an assistant's ANSWER against the REFERENCE answer for the same "
        "QUESTION, and score agreement from 0.0 to 1.0.\n\n"
        "Grade on the facts the REFERENCE asserts:\n"
        "1.0 = every fact in the reference is stated or directly implied, and the "
        "answer contradicts none of them.\n"
        "0.5 = some of the reference's facts are right, others are missing.\n"
        "0.0 = the answer contradicts the reference, or misses all of it.\n\n"
        "Rules:\n"
        "- Wording, length, tone and formatting do not matter at all.\n"
        "- Extra correct detail beyond the reference is not penalised.\n"
        "- Currency figures must match to the cent to count as agreeing, but a "
        "rounded restatement alongside the exact figure is fine.\n"
        "- A stated currency that differs from the reference's is a contradiction, "
        "not a formatting difference.\n"
        "- If the reference says the correct behaviour is to ask a clarifying "
        "question or to decline, then asking that question / declining scores 1.0 "
        "and answering anyway scores 0.0.\n\n"
        f"QUESTION:\n{question}\n\n"
        f"REFERENCE ANSWER:\n{_truncate(expected_answer, MAX_CONTEXT_CHARS)}\n\n"
        f"ANSWER:\n{_truncate(actual_answer, MAX_CONTEXT_CHARS)}\n"
    )
    result = _invoke_structured(llm, ScoreWithReason, prompt, "eval.accuracy")
    if result is None:
        return None, ["accuracy: not scored (judge unavailable)"], 1
    score = _clamp(result.score)
    note = f"accuracy: {score if score is not None else 'unparseable'} ({result.reason.strip()[:160]})"
    return score, [note], 1


# ---------------------------------------------------------------------------
# Component-level scoring — which part of the pipeline was wrong (2026-08-21)
# ---------------------------------------------------------------------------
# `feature_23_ai_control_tower.md`, "Component-level scoring, not one blended
# number": a single score per turn tells you *that* an answer was bad, not
# *which* stage to fix. Three stages, three genuinely different mechanisms — not
# the same check run three times:
#
#   context_score       deterministic set comparison, no judge
#   orchestration_score mechanical arithmetic/string traceability, no judge
#   persona_score       LLM-judged, because domain reasoning is the one thing
#                       here that actually needs judgement
#
# They are recorded and trended; they do not change `decide_pass()`. See
# `EvalScores`' docstring.


# --- Context builder: did retrieval fetch the right rows? ------------------

#: Keys whose values identify an invoice, wherever they appear in a tool result.
_IDENTIFIER_KEYS = ("invoice_number", "invoice_id")


def collect_invoice_identifiers(value: Any, _depth: int = 0) -> set[str]:
    """Every invoice identifier anywhere in a nested tool result.

    Walks dicts/lists rather than pattern-matching prose, because the tool
    results are structured and a regex over free text would happily match a PO
    number, a date or a phone number. Values are upper-cased and stripped so
    `dps-9981` and `DPS-9981 ` are the same invoice.
    """
    found: set[str] = set()
    if _depth > 8:
        return found
    if isinstance(value, dict):
        for key, item in value.items():
            if key in _IDENTIFIER_KEYS and isinstance(item, (str, int)) and str(item).strip():
                found.add(str(item).strip().upper())
            else:
                found |= collect_invoice_identifiers(item, _depth + 1)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            found |= collect_invoice_identifiers(item, _depth + 1)
    return found


def identifiers_from_markdown(markdown: str) -> set[str]:
    """Pull an `invoice_number`/`invoice_id` column out of a pipe table.

    The default (non-agentic) chat path's evidence is `execute_generated_sql()`'s
    rendered markdown, not a structure — so for that path this is the only place
    the fetched identifiers exist. Deliberately keyed on the header cell name, so
    a query that did not select the column yields nothing rather than a guess.
    """
    lines = [line for line in (markdown or "").splitlines() if "|" in line]
    if not lines:
        return set()
    header = [cell.strip().lower() for cell in lines[0].split("|")]
    column = next((i for i, cell in enumerate(header) if cell in _IDENTIFIER_KEYS), None)
    if column is None:
        return set()
    found: set[str] = set()
    for line in lines[1:]:
        cells = [cell.strip() for cell in line.split("|")]
        if len(cells) <= column:
            continue
        cell = cells[column]
        if not cell or set(cell) <= {"-", ":"}:  # the `--- | ---` separator row
            continue
        found.add(cell.upper())
    return found


def score_context(
    fetched: Any, expected: Any
) -> tuple[Optional[float], list[str]]:
    """Retrieval precision/recall against the golden case's known-correct set.

    Deterministic by design — no judge is involved and none is needed. Reported
    as F1 so one number moves on either failure (fetched the wrong invoice /
    missed the right one), with precision and recall both in the notes because
    they mean different things: low precision is an over-broad filter, low recall
    is a filter that excluded the answer.

    **The empty-expected case is scored, not skipped.** A golden case whose
    correct retrieval is *nothing* (Gap 224's shape — a vendor that does not
    exist) is a real and important test of the context builder: fetching nothing
    is 1.0, fetching anything at all is 0.0. Returning None there would hide the
    single most diagnostic case in the set.

    Returns `(score, notes)`. None means the case declares no expected set at
    all, i.e. there is nothing to compare against — distinct from "the expected
    set is empty".
    """
    if expected is None:
        return None, ["context: not scored (no expected invoice set on this case)"]

    expected_set = {str(v).strip().upper() for v in expected if str(v).strip()}
    fetched_set = {str(v).strip().upper() for v in (fetched or []) if str(v).strip()}

    if not expected_set:
        correct = not fetched_set
        note = (
            "context: 1.00 (correctly fetched nothing)"
            if correct
            else f"context: 0.00 (expected no rows, fetched {sorted(fetched_set)[:5]})"
        )
        return (1.0 if correct else 0.0), [note]

    hits = expected_set & fetched_set
    precision = len(hits) / len(fetched_set) if fetched_set else 0.0
    recall = len(hits) / len(expected_set)
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    notes = [
        f"context: {f1:.2f} (precision {precision:.2f}, recall {recall:.2f}; "
        f"expected {sorted(expected_set)}, fetched {sorted(fetched_set)[:8]})"
    ]
    missed = sorted(expected_set - fetched_set)
    if missed:
        notes.append("context missed: " + ", ".join(missed[:5]))
    return f1, notes


# --- Orchestration: does every figure in the answer trace to the evidence? --

#: A whole date, matched before bare numbers so `2026` and `08` never leak out
#: of `2026-08-01` and get graded as three separate figures.
_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")

#: A number, with optional thousands separators and decimal part.
_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")

#: Below this, a bare integer with no decimal part and no separator is not
#: graded. "3 invoices", "top 5", a list marker and a page number are as likely
#: as a fetched figure, and grading them would re-create the exact
#: under-scoring-correct-answers bug this module already has a history of. They
#: are counted and reported in the notes as skipped, not silently dropped.
MIN_GRADEABLE_MAGNITUDE = 100

#: Cost bound on the derivation search below (pairs, so this is squared).
MAX_DERIVATION_POOL = 60

#: Cents. Two figures that agree to the cent are the same figure.
_MONEY_TOLERANCE = Decimal("0.01")


def _canonical(raw: str) -> Optional[Decimal]:
    try:
        return Decimal(raw.replace(",", ""))
    except (InvalidOperation, AttributeError):
        return None


def _is_gradeable(raw: str, value: Decimal) -> bool:
    return "." in raw or "," in raw or abs(value) >= MIN_GRADEABLE_MAGNITUDE


def extract_figures(text: str) -> tuple[set[str], list[tuple[str, Decimal]], int]:
    """`(dates, [(raw, value), ...], skipped_count)` out of a piece of text.

    Public because both halves of the orchestration check use it — the answer's
    figures and the evidence's figures have to be extracted the same way or the
    comparison is meaningless.
    """
    text = text or ""
    dates = set(_DATE_RE.findall(text))
    without_dates = _DATE_RE.sub(" ", text)
    numbers: list[tuple[str, Decimal]] = []
    skipped = 0
    for raw in _NUMBER_RE.findall(without_dates):
        value = _canonical(raw)
        if value is None:
            continue
        if _is_gradeable(raw, value):
            numbers.append((raw, value))
        else:
            skipped += 1
    return dates, numbers, skipped


def _derivable(target: Decimal, pool: list[Decimal]) -> bool:
    """Is `target` the sum/difference/product/quotient of two evidence figures?

    "Every number must trace to a fetched field **or a `compute()` output**" is
    the design instruction, and a `compute()` output is by definition arithmetic
    over fetched fields. Without this, a correct "a difference of USD 14,350.00"
    would be scored as a fabrication — the same under-scoring-correct-answers
    trap this module has been bitten by twice. Bounded to one operation over a
    pair: two hops is where coincidence starts producing false passes.
    """
    for a in pool:
        for b in pool:
            for candidate in (a + b, a - b, a * b):
                if abs(target - candidate) <= _MONEY_TOLERANCE:
                    return True
            if b:
                try:
                    if abs(target - (a / b)) <= _MONEY_TOLERANCE:
                        return True
                except (InvalidOperation, ZeroDivisionError):  # pragma: no cover
                    continue
    return False


def score_orchestration(
    answer: str, context: str, executed_queries: Optional[str] = None
) -> tuple[Optional[float], list[str]]:
    """Mechanical groundedness: traceable figures / total figures. No judge.

    Deliberately *not* the same thing as `score_faithfulness()`. Faithfulness
    asks a model whether the claims hold; this asks arithmetic whether every
    figure in the answer can be found in, or computed from, the evidence. It
    catches the one failure that matters most and that a judge is least reliable
    at — a number that appears nowhere in the data — and it catches it the same
    way every time, at zero marginal cost and with no judge variance.

    Returns `(score, notes)`. None when the answer states no gradeable figure at
    all (a greeting, a refusal, a clarifying question): there is nothing to
    ground, which is not the same as being ungrounded.

    **The error this metric can make, stated rather than left to be discovered:**
    it is biased toward *false passes*, not false failures. Allowing arithmetic
    derivation means a fabricated figure that happens to equal an operation over
    two real ones is scored as traceable — a fabricated CGST of half a combined
    tax total would slip through if the literal `2` also appeared somewhere in
    the evidence. That direction is the deliberate choice: this component is a
    cheap mechanical screen for numbers that appear nowhere, and the expensive
    judged check (`score_faithfulness`) is what catches wrong-but-derivable.
    """
    evidence = "\n".join(part for part in (context or "", executed_queries or "") if part)
    answer_dates, answer_numbers, skipped = extract_figures(answer)
    evidence_dates, evidence_numbers, _ = extract_figures(evidence)

    total = len(answer_dates) + len(answer_numbers)
    if not total:
        note = "orchestration: not scored (no gradeable figures in the answer)"
        if skipped:
            note += f"; {skipped} small bare integer(s) skipped"
        return None, [note]

    evidence_values = []
    seen: set[Decimal] = set()
    for _raw, value in evidence_numbers:
        if value not in seen:
            seen.add(value)
            evidence_values.append(value)
    pool = evidence_values[:MAX_DERIVATION_POOL]

    untraceable: list[str] = []
    traceable = 0

    for date in answer_dates:
        if date in evidence_dates:
            traceable += 1
        else:
            untraceable.append(date)

    # Pass 1 — against the evidence itself, plus one arithmetic hop over it.
    pending: list[tuple[str, Decimal]] = []
    established: list[Decimal] = list(pool)
    for raw, value in answer_numbers:
        if any(abs(value - candidate) <= _MONEY_TOLERANCE for candidate in evidence_values):
            traceable += 1
            established.append(value)
        elif _derivable(value, pool):
            traceable += 1
            established.append(value)
        else:
            pending.append((raw, value))

    # Pass 2 — a second hop, but only over figures already *established* as
    # grounded, never over other pending ones. Found by running this against the
    # 2026-08-21 round's real output: `bolts_reconciliation`'s correct answer
    # ("5,000 units at USD 0.08 computes to USD 400.00, but the printed amount is
    # USD 420.00 -- a USD 20.00 discrepancy") had 20.00 marked untraceable,
    # because 20 = 420 - 400 and 400 is itself derived. That is a correct answer
    # being under-scored, which is the exact bug class this module has four
    # documented instances of. Restricting the second hop to already-grounded
    # figures keeps it from degenerating into "almost any number is derivable",
    # which an unrestricted two-hop search over the whole evidence set would.
    if pending:
        second_pool = established[:MAX_DERIVATION_POOL]
        for raw, value in pending:
            if _derivable(value, second_pool):
                traceable += 1
            else:
                untraceable.append(raw)

    score = traceable / total
    notes = [
        f"orchestration: {traceable}/{total} figures trace to the evidence"
        + (f" ({skipped} small bare integer(s) skipped)" if skipped else "")
    ]
    if untraceable:
        notes.append("untraceable figures: " + ", ".join(untraceable[:6]))
    return score, notes


# --- Persona: domain expertise, the one component that needs a judge --------


class PersonaVerdict(BaseModel):
    """Domain-reasoning judgement, with an explicit "not applicable" escape."""

    model_config = {"extra": "forbid"}

    applicable: bool = Field(
        default=True,
        description=(
            "False when the turn required no invoice/tax/accounting domain "
            "judgement at all -- a greeting, a refusal, a pure lookup with no "
            "reasoning. Set this rather than inventing a score."
        ),
    )
    score: float = Field(
        default=1.0, description="0.0-1.0. Ignored entirely when applicable is false."
    )
    domain_areas: list[str] = Field(
        default_factory=list,
        description="Which domain judgements the turn actually required, e.g. 'tax components'.",
    )
    reason: str = Field(default="", description="One short sentence of justification.")


def score_persona(
    question: str, answer: str, expected_answer: Optional[str], llm: Any
) -> tuple[Optional[float], list[str], int]:
    """Did the model apply invoice/tax domain expertise correctly?

    **Stated limitation, not buried:** the feature doc scopes this as needing
    "its own dedicated golden set of domain-knowledge questions". No such set
    exists in this repo — checked, not assumed: `tests/agent_eval_golden_sample.py`
    is nine general chat cases, and `tests/golden_bank/golden_bank.json`'s 87
    seeded cases are per-tenant regression questions with no domain-reasoning
    axis. Rather than block the whole component on authoring a new bank, this
    scores the *general* sample with a persona-focused rubric and returns
    `applicable=False` (score None) for every turn that required no domain
    judgement. The consequence is real and should be read into the number: the
    denominator is small and self-selected, so `persona_score` is a signal about
    the cases that happen to touch tax/category reasoning, not a coverage
    measure of domain competence. A dedicated domain bank remains the right fix
    and is still not written.

    The rubric's specifics are this repo's own closed gaps, not generic
    accounting: relabelling a combined `tax_amount` as CGST (Gaps 263/264),
    reading document-processing status as payment status (Gap 270), invoice
    total vs. line-item figure for a category question (Gap 271), a printed line
    amount that does not equal quantity x unit price (Gap 269), and mixing
    currencies with no rate available.
    """
    if not (answer or "").strip():
        return None, ["persona: not scored (empty answer)"], 0

    prompt = (
        "You are grading an invoice-domain assistant on DOMAIN EXPERTISE only: "
        "whether it reasoned correctly about accounting, tax and document "
        "semantics. You are NOT grading whether it retrieved the right rows, "
        "whether it cited its evidence, or how it was worded -- separate checks "
        "cover all three.\n\n"
        "FIRST decide `applicable`. Set applicable=false, and stop, if the turn "
        "required no domain judgement at all: a greeting, a refusal of an "
        "out-of-scope request, a clarifying question, or a plain single-value "
        "lookup with no interpretation. Do not invent a score for those.\n\n"
        "If it IS applicable, score 0.0-1.0 on domain correctness. These are the "
        "judgements that matter in this product, each a real past failure:\n"
        "  * Tax components. A single combined tax amount must NOT be relabelled "
        "as CGST, SGST or IGST. If only a combined figure exists, saying so is "
        "correct and splitting it is wrong. IGST applies inter-state, CGST+SGST "
        "intra-state -- asserting one without evidence is wrong.\n"
        "  * Reverse charge (RCM). Zero tax on an RCM invoice is a correct "
        "value, not missing data. Calling it missing is a domain error.\n"
        "  * Status semantics. A document-processing status (e.g. COMPLETED, "
        "PROCESSED) is NOT a payment status. Reading it as 'paid' is wrong; "
        "saying payment is not tracked is right.\n"
        "  * Category judgement. A question about a charge category (freight, "
        "shipping, storage) must be answered with the LINE ITEM's figure, not "
        "the invoice grand total, and a vendor's name is not evidence of what "
        "was billed.\n"
        "  * Arithmetic honesty. If a printed line amount does not equal "
        "quantity x unit price, saying so is correct; writing the false equation "
        "is a domain error.\n"
        "  * Currency. Amounts in different currencies must never be added or "
        "compared without an exchange rate; the currency must be stated.\n\n"
        "1.0 = every domain judgement the turn required was made correctly.\n"
        "0.5 = one material domain judgement wrong or dodged.\n"
        "0.0 = the central domain judgement is wrong (e.g. a fabricated tax "
        "split, or a processing status read as payment).\n\n"
        f"QUESTION:\n{question}\n\n"
        + (
            f"REFERENCE (what a domain expert would say):\n{_truncate(expected_answer, MAX_CONTEXT_CHARS)}\n\n"
            if (expected_answer or "").strip()
            else ""
        )
        + f"ANSWER:\n{_truncate(answer, MAX_CONTEXT_CHARS)}\n"
    )
    result = _invoke_structured(llm, PersonaVerdict, prompt, "eval.persona")
    if result is None:
        return None, ["persona: not scored (judge unavailable)"], 1
    if not getattr(result, "applicable", True):
        return None, ["persona: not scored (no domain judgement required by this turn)"], 1

    score = _clamp(getattr(result, "score", None))
    areas = ", ".join((getattr(result, "domain_areas", None) or [])[:4])
    reason = (getattr(result, "reason", "") or "").strip()[:160]
    note = f"persona: {score if score is not None else 'unparseable'}"
    if areas:
        note += f" [{areas}]"
    return score, [f"{note} ({reason})"], 1


def score_answer(
    *,
    question: str,
    answer: str,
    context: str,
    expected_answer: Optional[str] = None,
    llm: Any = None,
    executed_queries: Optional[str] = None,
    expected_invoice_ids: Any = None,
    fetched_invoice_ids: Any = None,
    score_persona_component: bool = True,
) -> EvalScores:
    """All six metrics for one answer, plus the pass/fail decision.

    `context` is everything the turn's tools actually returned — the results
    table, the document chunks, the computed figures. It is the evidence
    faithfulness is judged against, so a caller that passes the *prompt* instead
    of the *tool output* is measuring something else.

    `executed_queries` is the other half of that evidence — the SQL and/or tool
    calls with their arguments. Passing it is what makes a correct "nothing was
    found for X" answer scoreable at all; see failure mode 3.

    `expected_invoice_ids`/`fetched_invoice_ids` drive `context_score`. Leave
    `expected_invoice_ids` as None on a case that declares no known-correct
    retrieval set and that component stays unscored rather than guessed. An
    *empty* expected set is a real expectation ("this should fetch nothing") and
    is scored.

    `score_persona_component=False` skips the one component that costs a judge
    call, for callers measuring cost rather than quality.
    """
    if llm is None:
        from utils.llm import get_llm

        llm = get_llm()

    scores = EvalScores()

    faithfulness, claims, notes, calls = score_faithfulness(answer, context, llm, executed_queries)
    scores.faithfulness_score = faithfulness
    scores.claims = claims
    scores.notes.extend(notes)
    scores.judge_llm_calls += calls

    relevance, notes, calls = score_relevance(question, answer, llm)
    scores.relevance_score = relevance
    scores.notes.extend(notes)
    scores.judge_llm_calls += calls

    accuracy, notes, calls = score_accuracy(question, expected_answer, answer, llm)
    scores.accuracy_score = accuracy
    scores.notes.extend(notes)
    scores.judge_llm_calls += calls

    # --- Component-level. Two of the three cost nothing; only persona is a
    # judge call, and it is skipped entirely when the caller opts out.
    context_score, notes = score_context(fetched_invoice_ids, expected_invoice_ids)
    scores.context_score = context_score
    scores.notes.extend(notes)

    orchestration, notes = score_orchestration(answer, context, executed_queries)
    scores.orchestration_score = orchestration
    scores.notes.extend(notes)

    if score_persona_component:
        persona, notes, calls = score_persona(question, answer, expected_answer, llm)
        scores.persona_score = persona
        scores.notes.extend(notes)
        scores.judge_llm_calls += calls

    # Deliberately over the original three only — see `EvalScores`' docstring.
    scores.passed = decide_pass(scores)
    return scores


def decide_pass(scores: EvalScores) -> bool:
    """Every dimension that produced a number must clear its own floor.

    An answer with no scored dimension at all is a fail, not a pass: "nothing
    could be graded" is not evidence of quality, and a harness that defaulted to
    pass would go green on the day the judge broke.
    """
    checks = [
        (scores.faithfulness_score, FAITHFULNESS_FLOOR),
        (scores.relevance_score, RELEVANCE_FLOOR),
        (scores.accuracy_score, ACCURACY_FLOOR),
    ]
    graded = [(value, floor) for value, floor in checks if value is not None]
    if not graded:
        return False
    return all(value >= floor for value, floor in graded)
