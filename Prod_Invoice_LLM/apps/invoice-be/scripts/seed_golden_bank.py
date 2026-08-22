"""Feature 23 — seed the golden question bank from this repo's own gap history.

Why this exists
---------------
`feature_23_ai_control_tower.md`: *"Rather than inventing synthetic eval cases,
mine the gaps this repo already diagnosed"* — and, on the same page, the reason
it matters: *"Gap 287 — a faithfulness change that regressed Gap 263's
already-fixed behavior and was only caught by a user, not a test — is the
concrete cost of not having this yet."* Every gap in this repo was verified once,
at closure, and nothing re-runs any of it.

This script walks the three locations the doc names — `docs/test_evidence/`,
`tests/realworld_tenant/` and `tests/us/` (plus `tests/india/` and `tests/eu/`,
which are the same artefact for two more tenants) — and extracts every
reproducible (question, expectation, source) tuple that is *actually there*,
into one JSON fixture whose `question`/`expected_answer` pair feeds
`services/agent_eval.py::score_answer()` directly.

What was really found in those directories
------------------------------------------
Four distinct formats, none of them designed to be machine-read. They are parsed
as they are, not normalised at the source:

1. ``tests/{us,india,eu,realworld_tenant}/chat_question_bank.md`` — the only
   genuinely answer-bearing source. ``Qn[ (annotation)]. <question>`` followed by
   ``Answer:`` (or ``Matching:`` + ``Computation:`` for the cross-invoice sums),
   with a per-file grading rubric. ~15/14/15/25 questions. The ``(follow-up on
   Qn)`` annotations are real and are turned into ordered multi-turn links — the
   bounded 2-3 turn scripts the doc scopes the Thread tier down to.
2. ``tests/{us,realworld_tenant}/live_test_results.md`` — a results table
   (``Q# | Question | Expected | Actual | Verdict | ... | Notes``) from a real
   live run. This is where **gap attribution** comes from: the Notes column
   names the gaps a failing turn belongs to. Nothing else in the question banks
   carries a gap number at all.
3. ``docs/test_evidence/gap244_rag_retrieval_2026-08-17/*.json`` — retrieval
   probes with ``query`` + ``expected``/``expect`` (vendor names / invoice
   numbers). These are *property* cases, not answer cases: the expectation is
   "retrieval returned this row", which is exactly the doc's "context builder"
   component and needs no LLM judge.
4. ``docs/test_evidence/gap237_*/raw_turns_*.json`` — multi-turn session
   captures. Two sub-shapes (``chat_message_db_rows`` and
   ``turns[].prompt``/``response_json``). These carry the question *sequence*
   and the observed answer, but **no authored expectation** — the post-fix runs'
   observed output is emitted as a provisional expectation flagged
   ``needs_review``, because "what it did after the fix" is a plausible
   reference answer and is not a verified one.

Honest limits, up front
-----------------------
* **Gap attribution is sparse by construction.** Only source (2) links a
  question to a gap number, and only for the turns that failed. A bank question
  that has always passed has no gap to attribute it to — that is a property of
  the source data, not a parser weakness.
* **All four question-bank directories are gitignored** (`tests/.gitignore`,
  `Prod_Invoice_LLM/.gitignore`). The generated fixture therefore contains
  content that is not currently in version control. Whether it may be committed
  is a founder decision — see `--stdout` and the `provenance` block in the
  output. These are synthetic/generated tenants, not real customer data, so the
  question is about repo hygiene rather than PII; `utils/trace_scrubbing.py`
  exists for the case where it *is* PII.
* **A scrubbed bank cannot grade accuracy.** Running the scrubber over these
  cases replaces "$450.00" with "<AMOUNT_1>", which makes the reference answer
  unusable as a reference. That is the doc's "too aggressive and the bug stops
  reproducing" tension, resolved: an answer-bearing golden bank has to come from
  a safe (synthetic) corpus, not from scrubbed production traces.

Usage
-----
    uv run python scripts/seed_golden_bank.py                 # write the fixture + print coverage
    uv run python scripts/seed_golden_bank.py --stdout        # print the fixture, write nothing
    uv run python scripts/seed_golden_bank.py --out other.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

BE_ROOT = Path(__file__).resolve().parent.parent
# Run as `python scripts/seed_golden_bank.py`, sys.path[0] is `scripts/`, so the
# backend root has to be added for `tests.agent_eval_golden_sample` to import.
if str(BE_ROOT) not in sys.path:
    sys.path.insert(0, str(BE_ROOT))

DEFAULT_OUT = BE_ROOT / "tests" / "golden_bank" / "golden_bank.json"

#: The four per-tenant question banks. `realworld_tenant` is the NovaTech
#: tenant built from a 101-PDF generated corpus (see its
#: `ground_truth_line_items.md`) — realistic in shape, not real customer data.
QUESTION_BANK_DIRS = {
    "us": BE_ROOT / "tests" / "us",
    "india": BE_ROOT / "tests" / "india",
    "eu": BE_ROOT / "tests" / "eu",
    "novatech": BE_ROOT / "tests" / "realworld_tenant",
}

TEST_EVIDENCE_DIR = BE_ROOT / "docs" / "test_evidence"
TRACKER = BE_ROOT / "docs" / "be_features_tracker.md"


# ---------------------------------------------------------------------------
# Case model
# ---------------------------------------------------------------------------

#: How an expectation is stated. The scorer only consumes `reference_answer`
#: cases directly; the rest are still real regression material but need either a
#: deterministic check (`expected_entities`) or a human pass (`observed_*`,
#: `none`) before they can be graded.
KIND_REFERENCE_ANSWER = "reference_answer"
KIND_EXPECTED_ENTITIES = "expected_entities"
KIND_OBSERVED_POST_FIX = "observed_post_fix"
KIND_NONE = "none"


@dataclass
class GoldenBankCase:
    """One recovered case.

    `question` + `expected_answer` are exactly what
    `services/agent_eval.py::score_answer(question=..., expected_answer=...)`
    takes, so a `reference_answer` case is directly runnable. `expected_entities`
    holds the deterministic form (which vendors/invoices retrieval had to
    return) that the doc's "context builder" component is scored on.
    """

    case_id: str
    question: str
    expectation_kind: str
    expected_answer: Optional[str] = None
    expected_entities: list[str] = field(default_factory=list)
    source: str = ""
    source_gap: Optional[int] = None
    related_gaps: list[int] = field(default_factory=list)
    tenant: str = ""
    tier: str = "trace"  # trace | thread | run
    thread_id: Optional[str] = None
    turn_index: Optional[int] = None
    follow_up_of: Optional[str] = None
    live_verdict: Optional[str] = None
    needs_review: bool = False
    notes: str = ""


# ---------------------------------------------------------------------------
# 1. Per-tenant question banks
# ---------------------------------------------------------------------------

_Q_START = re.compile(r"^Q(\d+)\s*(\([^)]*\))?\s*\.\s*(.+)$")
_ANSWER_START = re.compile(r"^(Answer|Matching|Computation|Comparison)\s*:\s*(.*)$")
_HEADING = re.compile(r"^#{1,6}\s")
_FOLLOW_UP = re.compile(r"follow-?up on Q(\d+)", re.IGNORECASE)


def _repo_path(path: Path) -> str:
    """Backend-root-relative POSIX path, falling back to the raw path.

    The fallback is what lets the parsers be unit-tested against a tmp_path
    fixture instead of only against the (gitignored) real directories.
    """
    try:
        return path.resolve().relative_to(BE_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _slug(text: str, limit: int = 48) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return cleaned[:limit].rstrip("_")


def parse_question_bank(path: Path, tenant: str) -> list[GoldenBankCase]:
    """Parse one `chat_question_bank.md`.

    Line-oriented on purpose: these files are hand-written prose with wrapped
    lines, inconsistent annotations and three different ways of stating an
    expected answer. A structural parser would need the source normalised first,
    and normalising four gitignored hand-written files is not a safer bet than
    reading them as they are.
    """
    if not path.exists():
        return []

    cases: list[GoldenBankCase] = []
    lines = path.read_text(encoding="utf-8").splitlines()

    current: Optional[dict] = None
    buffer_target: Optional[str] = None

    def _flush() -> None:
        nonlocal current, buffer_target
        if current is None:
            return
        question = " ".join(current["question"]).strip()
        expected = "\n".join(part.strip() for part in current["expected"] if part.strip()).strip()
        if question:
            number = current["number"]
            annotation = current["annotation"] or ""
            follow_up_match = _FOLLOW_UP.search(annotation)
            cases.append(
                GoldenBankCase(
                    case_id=f"{tenant}_q{number}_{_slug(question)}",
                    question=question,
                    expectation_kind=(
                        KIND_REFERENCE_ANSWER if expected else KIND_NONE
                    ),
                    expected_answer=expected or None,
                    source=f"{_repo_path(path)}:{current['line_no']}",
                    tenant=tenant,
                    tier="thread" if follow_up_match else "trace",
                    thread_id=f"{tenant}_{_slug(current['session'] or 'session')}"
                    if current["session"]
                    else None,
                    turn_index=number,
                    follow_up_of=(
                        f"{tenant}_q{follow_up_match.group(1)}" if follow_up_match else None
                    ),
                    notes=annotation.strip("() ") if annotation else "",
                )
            )
        current = None
        buffer_target = None

    session: Optional[str] = None
    for index, raw in enumerate(lines, start=1):
        line = raw.rstrip()
        stripped = line.strip()

        if _HEADING.match(stripped):
            _flush()
            if stripped.lower().startswith("## session"):
                session = stripped.lstrip("# ").strip()
            continue

        if stripped in ("", "---"):
            buffer_target = None
            continue

        start = _Q_START.match(stripped)
        if start:
            _flush()
            current = {
                "number": int(start.group(1)),
                "annotation": start.group(2),
                "question": [start.group(3)],
                "expected": [],
                "session": session,
                "line_no": index,
            }
            buffer_target = "question"
            continue

        if current is None:
            continue

        answer = _ANSWER_START.match(stripped)
        if answer:
            label = answer.group(1)
            body = answer.group(2)
            # "Matching:"/"Computation:"/"Comparison:" are the cross-invoice sum
            # form — the label carries meaning (which lines, then the sum), so it
            # is kept rather than flattened into bare prose.
            current["expected"].append(f"{label}: {body}" if body else f"{label}:")
            buffer_target = "expected"
            continue

        if buffer_target == "question":
            current["question"].append(stripped)
        elif buffer_target == "expected":
            current["expected"].append(stripped)

    _flush()
    return cases


# ---------------------------------------------------------------------------
# 2. Live-run result tables — the only source of gap attribution
# ---------------------------------------------------------------------------

#: Gap references as this repo actually writes them, all four spellings found in
#: the sources: "Gap 263", "gap270", "Gaps 263/264", "BE Gaps 244 / 240 / 243 /
#: 239", "Gaps 228-232". An earlier draft matched only `\bGap\s+(\d+)` and
#: therefore silently missed every plural/grouped citation — which is most of
#: the evidence-folder titles.
_GAP_REF = re.compile(r"\bgaps?\s*(\d+(?:\s*[/,–-]\s*\d+)*)", re.IGNORECASE)

#: A "Gaps 228-232" range is expanded; anything wider than this is treated as
#: two separate citations, not a range, because it is almost certainly prose.
_MAX_GAP_RANGE = 20


def extract_gap_numbers(text: str) -> list[int]:
    """Every gap number cited in a blob of prose, ranges expanded."""
    found: set[int] = set()
    for group in _GAP_REF.findall(text or ""):
        parts = re.split(r"\s*[/,]\s*", group)
        for part in parts:
            range_match = re.fullmatch(r"(\d+)\s*[–-]\s*(\d+)", part.strip())
            if range_match:
                low, high = int(range_match.group(1)), int(range_match.group(2))
                if 0 < high - low <= _MAX_GAP_RANGE:
                    found.update(range(low, high + 1))
                    continue
                found.update({low, high})
                continue
            for number in re.findall(r"\d+", part):
                found.add(int(number))
    return sorted(found)


def _split_markdown_row(line: str) -> list[str]:
    inner = line.strip()
    if inner.startswith("|"):
        inner = inner[1:]
    if inner.endswith("|"):
        inner = inner[:-1]
    # Escaped pipes inside cells are real in these files (the Actual column
    # embeds markdown tables), so split on unescaped pipes only.
    parts = re.split(r"(?<!\\)\|", inner)
    return [part.strip() for part in parts]


@dataclass
class LiveVerdict:
    question: str
    expected: str
    verdict: str
    gaps: list[int]
    source: str


def parse_live_test_results(path: Path) -> dict[int, LiveVerdict]:
    """Pull `Q# -> (expected, verdict, gaps)` out of a live-run results table."""
    if not path.exists():
        return {}

    out: dict[int, LiveVerdict] = {}
    header: Optional[list[str]] = None
    columns: dict[str, int] = {}

    for index, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line.startswith("|"):
            continue
        cells = _split_markdown_row(line)
        if header is None:
            lowered = [cell.lower() for cell in cells]
            if "q#" in lowered and "question" in lowered:
                header = cells
                for name in ("q#", "question", "expected", "verdict", "correctness", "notes"):
                    if name in lowered:
                        columns[name] = lowered.index(name)
            continue
        if set("".join(cells)) <= {"-", ":"}:
            continue  # the |---|---| separator row

        q_cell = cells[columns["q#"]] if columns.get("q#") is not None else ""
        number_match = re.match(r"(\d+)", q_cell)
        if not number_match:
            continue
        number = int(number_match.group(1))

        def cell(name: str) -> str:
            idx = columns.get(name)
            return cells[idx] if idx is not None and idx < len(cells) else ""

        notes = cell("notes")
        verdict = cell("verdict") or cell("correctness")
        out[number] = LiveVerdict(
            question=cell("question"),
            expected=cell("expected"),
            verdict=re.sub(r"[*_]", "", verdict).strip(),
            gaps=extract_gap_numbers(notes),
            source=f"{_repo_path(path)}:{index}",
        )
    return out


def attach_live_verdicts(cases: list[GoldenBankCase], tenant: str, verdicts: dict[int, LiveVerdict]) -> int:
    """Fold verdict + gap attribution onto the matching bank cases.

    Matched on question number, not on question text: the results tables
    paraphrase long questions to fit the column, so text matching would silently
    drop the very rows that carry the gap references.
    """
    attached = 0
    for case in cases:
        if case.tenant != tenant or case.turn_index is None:
            continue
        verdict = verdicts.get(case.turn_index)
        if verdict is None:
            continue
        case.live_verdict = verdict.verdict or None
        if verdict.gaps:
            case.source_gap = verdict.gaps[0]
            case.related_gaps = verdict.gaps
            attached += 1
        if not case.expected_answer and verdict.expected:
            case.expected_answer = verdict.expected
            case.expectation_kind = KIND_REFERENCE_ANSWER
    return attached


# ---------------------------------------------------------------------------
# 3. Per-gap evidence folders
# ---------------------------------------------------------------------------

_GAP_DIR = re.compile(r"gap(\d+)", re.IGNORECASE)


def _gaps_for_evidence_dir(directory: Path) -> tuple[Optional[int], list[int]]:
    """Primary gap from the directory name; related gaps from the README title.

    Several evidence folders cover a group (`gap244_rag_retrieval` is titled
    "BE Gaps 244 / 240 / 243 / 239"), so the folder name alone under-reports.
    """
    primary_match = _GAP_DIR.search(directory.name)
    primary = int(primary_match.group(1)) if primary_match else None
    related: set[int] = set()
    for number in _GAP_DIR.findall(directory.name):
        related.add(int(number))
    readme = directory / "README.md"
    if readme.exists():
        first_lines = readme.read_text(encoding="utf-8", errors="replace").splitlines()[:3]
        for line in first_lines:
            related.update(extract_gap_numbers(line))
    return primary, sorted(related)


def _retrieval_probe_cases(
    payload: Any, origin: str, primary: Optional[int], related: list[int]
) -> list[GoldenBankCase]:
    """`query` + `expected` / `expect` probes -> deterministic retrieval cases.

    These are the doc's *context builder* component: the expectation is which
    rows retrieval had to surface, checkable without any LLM judge.
    """
    cases: list[GoldenBankCase] = []

    def _harvest(turns: Iterable[dict], label: str) -> None:
        for position, turn in enumerate(turns):
            if not isinstance(turn, dict):
                continue
            question = turn.get("query") or turn.get("question")
            expected = turn.get("expected") or turn.get("expect")
            if not question or not isinstance(expected, list) or not expected:
                continue
            cases.append(
                GoldenBankCase(
                    case_id=f"gap{primary}_{label}_{position}_{_slug(str(question))}",
                    question=str(question),
                    expectation_kind=KIND_EXPECTED_ENTITIES,
                    expected_entities=[str(item) for item in expected],
                    source=origin,
                    source_gap=primary,
                    related_gaps=related,
                    tenant="evidence",
                    tier="run",
                    notes=(
                        "Retrieval probe: the expectation is which rows had to be "
                        "returned, not a natural-language answer."
                    ),
                )
            )

    if isinstance(payload, dict):
        if isinstance(payload.get("turns"), list):
            _harvest(payload["turns"], "turns")
        for key in ("cosine", "l2_default"):
            block = payload.get(key)
            if isinstance(block, dict) and isinstance(block.get("report"), list):
                _harvest(block["report"], key)
    return cases


def _session_capture_cases(
    payload: Any, origin: str, primary: Optional[int], related: list[int], thread_id: str
) -> list[GoldenBankCase]:
    """`raw_turns_*.json` -> ordered multi-turn scripts.

    Two real sub-shapes: `chat_message_db_rows` (alternating user/assistant rows
    read straight out of `ChatMessage`) and `turns[].prompt` +
    `turns[].response_json.content` (the HTTP-level capture). Neither carries an
    authored expectation; a post-fix capture's observed answer is emitted as a
    provisional one, flagged `needs_review`.
    """
    if not isinstance(payload, dict):
        return []

    label = str(payload.get("run_label") or "")
    post_fix = any(token in label.lower() or token in Path(origin).name.lower()
                   for token in ("after", "fixed"))

    pairs: list[tuple[str, Optional[str]]] = []

    rows = payload.get("chat_message_db_rows")
    if isinstance(rows, list):
        pending: Optional[str] = None
        for row in rows:
            if not isinstance(row, dict):
                continue
            if row.get("role") == "user":
                pending = str(row.get("content") or "")
            elif row.get("role") == "assistant" and pending:
                pairs.append((pending, str(row.get("content") or "")))
                pending = None

    turns = payload.get("turns")
    if isinstance(turns, list):
        for turn in turns:
            if not isinstance(turn, dict) or "prompt" not in turn:
                continue
            response = turn.get("response_json") or {}
            answer = response.get("content") if isinstance(response, dict) else None
            pairs.append((str(turn["prompt"]), str(answer) if answer else None))

    cases: list[GoldenBankCase] = []
    for position, (question, observed) in enumerate(pairs):
        if not question.strip():
            continue
        cases.append(
            GoldenBankCase(
                case_id=f"gap{primary}_{_slug(thread_id, 32)}_t{position}_{_slug(question)}",
                question=question,
                expectation_kind=KIND_OBSERVED_POST_FIX if (post_fix and observed) else KIND_NONE,
                expected_answer=observed if (post_fix and observed) else None,
                source=origin,
                source_gap=primary,
                related_gaps=related,
                tenant="evidence",
                tier="thread" if len(pairs) > 1 else "trace",
                thread_id=thread_id,
                turn_index=position,
                follow_up_of=None,
                needs_review=True,
                notes=(
                    "Provisional reference answer: this is what the pipeline actually "
                    "produced on a post-fix run, not an independently authored expected "
                    "answer. Review before treating a mismatch as a regression."
                    if (post_fix and observed)
                    else "Question sequence recovered from a repro capture; no expectation "
                    "was recorded in the evidence, so one must be written."
                ),
            )
        )
    return cases


def parse_test_evidence(root: Path) -> list[GoldenBankCase]:
    if not root.exists():
        return []

    cases: list[GoldenBankCase] = []
    for directory in sorted(p for p in root.iterdir() if p.is_dir()):
        primary, related = _gaps_for_evidence_dir(directory)
        for json_path in sorted(directory.glob("*.json")):
            try:
                payload = json.loads(json_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            origin = _repo_path(json_path)
            cases.extend(_retrieval_probe_cases(payload, origin, primary, related))
            cases.extend(
                _session_capture_cases(
                    payload, origin, primary, related, thread_id=json_path.stem
                )
            )
    return cases


# ---------------------------------------------------------------------------
# 4. The one existing gap-tagged, answer-bearing case set in the repo
# ---------------------------------------------------------------------------


def parse_agent_eval_golden_sample() -> list[GoldenBankCase]:
    """`tests/agent_eval_golden_sample.py` — 9 cases, and the only source here
    that is simultaneously committed, answer-bearing *and* gap-tagged.

    Feature 23 Phase 3 built it by hand for the 36-turn eval round. Its
    `why_on_file` field names the incident each question encodes ("Gap 270 /
    rule 4a", "Gaps 263/264", "Gap 268 / rule 10"), which is exactly the
    attribution the per-tenant banks lack. Imported rather than re-parsed so the
    two cannot drift; the import is cheap (~1.7s, MOCK_EMBEDDINGS) and a failure
    degrades to "this source contributed nothing" rather than aborting the seed.
    """
    import os

    os.environ.setdefault("MOCK_EMBEDDINGS", "true")
    try:
        from tests.agent_eval_golden_sample import CASES  # noqa: PLC0415
    except Exception as exc:  # pragma: no cover - environment-dependent
        print(f"  ! agent_eval_golden_sample not importable, skipped: {exc}", file=sys.stderr)
        return []

    out: list[GoldenBankCase] = []
    for case in CASES:
        gaps = extract_gap_numbers(f"{case.source} {case.why_on_file}")
        out.append(
            GoldenBankCase(
                case_id=f"sage_sample_{case.case_id}",
                question=case.question,
                expectation_kind=(
                    KIND_REFERENCE_ANSWER if case.expected_answer else KIND_NONE
                ),
                expected_answer=case.expected_answer,
                source=f"tests/agent_eval_golden_sample.py ({case.source})",
                source_gap=gaps[0] if gaps else None,
                related_gaps=gaps,
                tenant="sage_fixture",
                tier="trace",
                notes=case.why_on_file,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Dedup
# ---------------------------------------------------------------------------


def deduplicate(cases: list[GoldenBankCase]) -> tuple[list[GoldenBankCase], int]:
    """Collapse repeats, keeping the most-informative copy.

    The evidence folders hold 7-8 statistical repeats of the same session
    (`raw_turns_run0..run6`, `raw_turns_before/after/fixed_0..7`), so the same
    question recurs a dozen times. Keyed on (question, turn position, gap) with
    a case carrying an expectation always beating one that does not.
    """
    ranked = {
        KIND_REFERENCE_ANSWER: 3,
        KIND_EXPECTED_ENTITIES: 2,
        KIND_OBSERVED_POST_FIX: 1,
        KIND_NONE: 0,
    }
    best: dict[tuple, GoldenBankCase] = {}
    dropped = 0
    for case in cases:
        key = (case.question.strip().lower(), case.turn_index, case.source_gap, case.tenant)
        incumbent = best.get(key)
        if incumbent is None:
            best[key] = case
            continue
        dropped += 1
        if ranked[case.expectation_kind] > ranked[incumbent.expectation_kind]:
            best[key] = case
    return list(best.values()), dropped


# ---------------------------------------------------------------------------
# Coverage against the real tracker
# ---------------------------------------------------------------------------

#: Words that mark a gap as answer-quality — the population a *question* bank
#: could possibly cover. Listed explicitly so the coverage number below is
#: auditable rather than a black box: a gap about OAuth redirect URIs, a billing
#: sweep or a readiness probe is not something a chat question can regress.
#:
#: `chroma`/`embedding` are deliberately absent. Retrieval *infrastructure*
#: (per-tenant collection isolation, re-embedding) is not observable from a
#: question's answer, so counting it would inflate the denominator with gaps a
#: golden bank structurally cannot cover.
CHAT_GAP_KEYWORDS = (
    "chat",
    " rag",
    "rag ",
    "sql",
    "query agent",
    "retriev",
    "sage",
    "answer",
    "question",
    "citation",
    "follow-up",
    "clarif",
    "summar",
    "prompt",
)

_TRACKER_GAP = re.compile(r"`\[(.)\]`\s*\*\*(Gap\s+(\d+).*?)\*\*", re.DOTALL)


def tracker_gap_index(path: Path) -> dict[int, tuple[str, str, str]]:
    """`{gap_number: (status, title, full_entry_line)}` — read-only, never written.

    Title and full line are kept separately because they give materially
    different coverage denominators, and the difference is worth reporting
    rather than picking one silently — see `build_coverage`.
    """
    if not path.exists():
        return {}
    index: dict[int, tuple[str, str, str]] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = _TRACKER_GAP.search(line)
        if match:
            index[int(match.group(3))] = (match.group(1), match.group(2), line)
    return index


def _matches(text: str) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in CHAT_GAP_KEYWORDS)


def build_coverage(cases: list[GoldenBankCase], tracker: dict[int, tuple[str, str, str]]) -> dict:
    covered = sorted(
        {case.source_gap for case in cases if case.source_gap}
        | {gap for case in cases for gap in case.related_gaps}
    )
    closed = {number for number, (status, _, _) in tracker.items() if status == "x"}

    # Two denominators, because a keyword classifier over hand-written prose is
    # not exact and pretending otherwise would be the dishonest part:
    #   strict = the gap's own *title* is about chat/answers
    #   loose  = the word appears anywhere in the entry, including in the fix
    #            narrative (which sweeps in e.g. "the readiness probe broke chat")
    strict = {
        number
        for number, (status, title, _) in tracker.items()
        if status == "x" and _matches(title)
    }
    loose = {
        number
        for number, (status, _, line) in tracker.items()
        if status == "x" and _matches(line)
    }
    return {
        "tracker_gap_entries": len(tracker),
        "tracker_closed_gaps": len(closed),
        "closed_answer_quality_gaps_strict_title_match": len(strict),
        "closed_answer_quality_gaps_loose_anywhere_in_entry": len(loose),
        "gaps_with_a_recovered_case": len(covered),
        "covered_gap_numbers": covered,
        "strict_answer_quality_gaps_with_a_recovered_case": len(strict & set(covered)),
        "strict_answer_quality_gaps_without_a_case": sorted(strict - set(covered)),
        "keywords_used_to_classify_answer_quality_gaps": list(CHAT_GAP_KEYWORDS),
        "classifier_caveat": (
            "Keyword classification over hand-written tracker prose. The strict "
            "figure matches the gap's own title only; the loose figure matches "
            "anywhere in the entry and over-counts (a billing or readiness-probe "
            "gap whose narrative mentions chat). Neither is exact — they bracket "
            "the real population."
        ),
    }


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def collect_cases() -> tuple[list[GoldenBankCase], dict]:
    cases: list[GoldenBankCase] = []
    per_source: dict[str, int] = {}
    gap_attributions = 0

    for tenant, directory in QUESTION_BANK_DIRS.items():
        bank = parse_question_bank(directory / "chat_question_bank.md", tenant)
        verdicts = parse_live_test_results(directory / "live_test_results.md")
        gap_attributions += attach_live_verdicts(bank, tenant, verdicts)
        per_source[f"chat_question_bank[{tenant}]"] = len(bank)
        per_source[f"live_test_results[{tenant}]"] = len(verdicts)
        cases.extend(bank)

    evidence = parse_test_evidence(TEST_EVIDENCE_DIR)
    per_source["docs/test_evidence"] = len(evidence)
    cases.extend(evidence)

    sample = parse_agent_eval_golden_sample()
    per_source["tests/agent_eval_golden_sample.py"] = len(sample)
    gap_attributions += sum(1 for case in sample if case.source_gap)
    cases.extend(sample)

    cases, dropped = deduplicate(cases)
    cases.sort(key=lambda c: (c.tenant, c.turn_index if c.turn_index is not None else 0, c.case_id))

    stats = {
        "cases_by_source_before_dedup": per_source,
        "duplicate_cases_dropped": dropped,
        "questions_given_a_gap_number_by_a_live_run": gap_attributions,
    }
    return cases, stats


def summarise(cases: list[GoldenBankCase]) -> dict:
    by_kind: dict[str, int] = {}
    by_tier: dict[str, int] = {}
    by_tenant: dict[str, int] = {}
    for case in cases:
        by_kind[case.expectation_kind] = by_kind.get(case.expectation_kind, 0) + 1
        by_tier[case.tier] = by_tier.get(case.tier, 0) + 1
        by_tenant[case.tenant] = by_tenant.get(case.tenant, 0) + 1
    return {
        "total_cases": len(cases),
        "directly_scorable_by_services_agent_eval": by_kind.get(KIND_REFERENCE_ANSWER, 0),
        "deterministic_retrieval_cases": by_kind.get(KIND_EXPECTED_ENTITIES, 0),
        "provisional_needs_human_review": sum(1 for c in cases if c.needs_review),
        "no_expectation_recorded_must_be_written": by_kind.get(KIND_NONE, 0),
        "by_expectation_kind": by_kind,
        "by_tier": by_tier,
        "by_tenant": by_tenant,
        "multi_turn_links": sum(1 for c in cases if c.follow_up_of),
    }


PROVENANCE = {
    "source_directories_are_gitignored": [
        "tests/us", "tests/india", "tests/eu", "tests/realworld_tenant",
    ],
    "note": (
        "Every per-tenant question bank this fixture is built from lives in a "
        "gitignored directory (tests/.gitignore, Prod_Invoice_LLM/.gitignore). "
        "The four tenants are synthetic/generated corpora, not real customer "
        "data, so committing this file is a repo-hygiene decision rather than a "
        "PII one — but it is a decision, and it is the founder's. Regenerate "
        "with `uv run python scripts/seed_golden_bank.py` at any time."
    ),
    "scrubbing": (
        "Deliberately NOT scrubbed. utils/trace_scrubbing.py would replace every "
        "reference figure with <AMOUNT_n>, which destroys the reference answers "
        "that make this bank gradeable. An answer-bearing bank must come from a "
        "safe corpus; scrubbing is for production traces, which are a different "
        "artefact."
    ),
}


def build_fixture() -> dict:
    cases, stats = collect_cases()
    coverage = build_coverage(cases, tracker_gap_index(TRACKER))
    return {
        "generated_by": "scripts/seed_golden_bank.py",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "feature": "Feature 23 — AI Control Tower, golden question bank seed",
        "consumed_by": "services/agent_eval.py::score_answer(question=..., expected_answer=...)",
        "provenance": PROVENANCE,
        "extraction_stats": stats,
        "summary": summarise(cases),
        "gap_coverage": coverage,
        "cases": [asdict(case) for case in cases],
    }


def _print_report(fixture: dict) -> None:
    summary = fixture["summary"]
    coverage = fixture["gap_coverage"]
    stats = fixture["extraction_stats"]

    print("=" * 72)
    print("Golden question bank seed — what was actually recovered")
    print("=" * 72)
    print(f"  total cases                              : {summary['total_cases']}")
    print(f"  directly scorable (reference answer)     : {summary['directly_scorable_by_services_agent_eval']}")
    print(f"  deterministic retrieval cases            : {summary['deterministic_retrieval_cases']}")
    print(f"  provisional, need human review           : {summary['provisional_needs_human_review']}")
    print(f"  no expectation recorded, must be written : {summary['no_expectation_recorded_must_be_written']}")
    print(f"  multi-turn (follow-up) links             : {summary['multi_turn_links']}")
    print()
    print("  by source (pre-dedup):")
    for name, count in stats["cases_by_source_before_dedup"].items():
        print(f"    {name:<36}: {count}")
    print(f"    duplicates dropped                  : {stats['duplicate_cases_dropped']}")
    print()
    print("  gap coverage (tracker read-only):")
    print(f"    tracker gap entries                 : {coverage['tracker_gap_entries']}")
    print(f"    closed gaps                         : {coverage['tracker_closed_gaps']}")
    print(f"    closed answer-quality gaps (strict) : {coverage['closed_answer_quality_gaps_strict_title_match']}")
    print(f"    closed answer-quality gaps (loose)  : {coverage['closed_answer_quality_gaps_loose_anywhere_in_entry']}")
    print(f"    strict gaps with a recovered case   : {coverage['strict_answer_quality_gaps_with_a_recovered_case']}")
    print(f"    strict gaps needing a fresh case    : {len(coverage['strict_answer_quality_gaps_without_a_case'])}")
    print(f"    gaps referenced by any case         : {coverage['gaps_with_a_recovered_case']} -> {coverage['covered_gap_numbers']}")
    print("=" * 72)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="print the fixture to stdout and write nothing to disk",
    )
    args = parser.parse_args(argv)

    fixture = build_fixture()

    if args.stdout:
        json.dump(fixture, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(fixture, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    _print_report(fixture)
    print(f"\nwrote {args.out.relative_to(BE_ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
