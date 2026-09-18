"""Feature 34 (ATLAS) task 34.7f — the order the lines arrive in.

Spec: `docs/feature_34_atlas.md` §7.3 · `atlas_discussion.md` **D30**.

    Money at stake x how soon it stops being fixable. A Rs 2.4L duplicate before
    tomorrow's payment run beats a Rs 4,000 one from last month. Everything below
    the cut stays reachable. **ATLAS ranks; it does not hide.**

Why this is arithmetic and not a prompt
---------------------------------------
CONVENTIONS hard rule 3: anything that decides correctness is deterministic
code. Ordering decides which finding a person reads first and which one they
never scroll to, so a ranking a model produces differently on each run is not a
ranking -- it is a shuffle with an explanation attached. Every term below comes
from a field the emitter stated (`Recommendation.stake`, `.fixable_until`), and
the function is pure: same lines, same day, same order, every time. Asserted in
`tests/test_atlas_ranking.py` rather than asserted here.

What "how soon it stops being fixable" means, exactly
-----------------------------------------------------
`urgency = 1 / (days_left + 1)`, where `days_left` is whole days from today to
`fixable_until`, floored at zero.

* **Floored at zero, not negative.** An item whose date has passed is at maximum
  urgency, not at negative urgency that would sort it below everything. A missed
  deadline does not make the money stop mattering.
* **`+1` in the denominator** so that "today" is finite rather than a division by
  zero, and so the curve between today, tomorrow and next week is steep -- which
  is the whole content of D30's example.
* **No deadline means far off, never urgent** (`_NO_DEADLINE_DAYS`). Inventing
  urgency for a line that never stated any would make the ranking mean less each
  time a new emitter forgot the field. A quiet ingestion source is real work and
  it is not a thing that expires tomorrow.

Three properties this deliberately does NOT have
-------------------------------------------------
1. **It does not hide anything.** `rank()` returns every line it was given, in a
   new order. `RANK_CUT` is a number the screen uses to decide what is above the
   fold, and the lines below it are in the same payload -- D30's "everything
   below the cut stays reachable" is satisfied by the payload, not by a promise
   the client keeps.
2. **It does not convert currencies.** Two lines in different currencies are
   ordered by the raw magnitude of their stakes, with no rate applied and no
   total formed. §7.4/D32 forbids a *blended number*; this produces no number
   that anybody reads, which is why it is not a violation -- but it is also not
   a claim that one unit of one currency is worth one unit of another, and the
   honest reading is that cross-currency neighbours on the list are in an
   arbitrary order relative to each other. Stated here rather than discovered
   later.
3. **It is not a score on the line.** Nothing renders the number. §5.1 forbids
   confidence numbers on a line and the same reasoning applies: a rank of 0.83
   is meaningless to a finance user, and the only honest form of "this matters
   more" is position.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Iterable, Sequence

from services.atlas_contract import Recommendation

__all__ = ["RANK_CUT", "rank", "rank_score", "days_left"]  # hardcode-ok: this module's own public names, not domain data

#: How many lines the screen shows before "show everything".
#:
#: **A stated guess, not a measured threshold.** §13.5 names the volume at which
#: a list needs collapsing as a build-time unknown to be answered by measurement,
#: and this is the number picked until there is a customer to measure. It is a
#: display hint carried on the response; nothing is removed from the payload
#: because of it.
RANK_CUT = 7

#: What `fixable_until is None` ranks as, in days. Far off, deliberately: see
#: the module docstring on why inventing urgency degrades the whole ordering.
_NO_DEADLINE_DAYS = 90

#: What `stake is None` ranks as. Zero, so a line with no money on it sorts
#: below any line that has some -- which is D30's test read literally ("money at
#: stake x ..."), not a judgement that such lines do not matter. They keep their
#: place relative to each other through the tie-break below.
_NO_STAKE = Decimal("0")


def days_left(line: Recommendation, today: date) -> int:
    """Whole days until this stops being fixable. Floored at zero."""
    if line.fixable_until is None:
        return _NO_DEADLINE_DAYS
    return max(0, (line.fixable_until - today).days)


def rank_score(line: Recommendation, today: date) -> Decimal:
    """`money at stake x how soon it stops being fixable` (§7.3, D30).

    Returns a `Decimal`, not a float: the stakes are money amounts and float
    addition of money is the habit that produces the wrong number §5.2 says
    trust does not recover from. Nothing renders this value.
    """
    stake = line.stake if line.stake is not None else _NO_STAKE
    return Decimal(stake) / Decimal(days_left(line, today) + 1)


def rank(lines: Iterable[Recommendation], today: date) -> list[Recommendation]:
    """Every line given, in D30's order. Nothing is dropped.

    The tie-break is `(-score, -stake, id)`. The id is last and is what makes the
    function total: two lines with the same money and the same deadline would
    otherwise swap places between two recomputes of the same screen, and a list
    that reorders under the user's cursor is one they stop trusting the top of.
    `Recommendation.id` is deterministic at every emitter (D49), so it is a
    stable key rather than a coin toss.
    """
    ordered: Sequence[Recommendation] = list(lines)
    return sorted(
        ordered,
        key=lambda line: (
            -rank_score(line, today),
            -(line.stake if line.stake is not None else _NO_STAKE),
            line.id,
        ),
    )
