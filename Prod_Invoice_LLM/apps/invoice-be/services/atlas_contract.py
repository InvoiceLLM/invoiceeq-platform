"""Feature 34 (ATLAS) task 34.2 — the recommendation contract.

Spec: `docs/feature_34_atlas.md` §1, §5.1, §5.3, §7.4 · decisions D7, D26, D28,
D29, D32.

**This module owns the contract between invoice-be and invoice-fe.** Field
names, enum values and payload shape are defined here and nowhere else; FE
Feature 23 consumes them and never restates them. The seam between BE Feature 33
and FE Feature 22 is where this session's worst defects lived -- a live event
promised by two specs and published by neither, a field the FE read that the BE
never emitted, capabilities in a registry that no surface emitted. One contract,
one owner.

The four parts (§1, D7)
-----------------------
Every line ATLAS produces carries four things, and **a line missing any of them
is a defect**:

===========  =============================================================
``what``     the invoice, the alert, the correction
``why``      the reason in the user's terms -- "this vendor has never
             billed above Rs 20,000"
``action``   a single click, batchable when certain
``verify``   opens chat with the document attached and the question
             pre-seeded
===========  =============================================================

They are required fields, not a convention, so "missing" is a construction-time
`ValidationError` rather than a blank area of a screen. The fourth is the one
that looks droppable and is not: trust is not built by telling a user ATLAS is
reliable, it is built by letting them check it once, cheaply, on the line in
front of them (D24).

Why the boundaries are code and not prompt text
-----------------------------------------------
CONVENTIONS hard rule 3: any check that decides correctness is deterministic
code. Prompt rules alone are not a control -- BE Gaps 220-225 and 253 all share
that failure mode. Three of §5.3's boundaries decide correctness, so all three
are assertions here:

* **"never invents a number"** -- `assert_figures_are_witnessed()` and
  `assert_no_undeclared_numbers()`. The spec calls this "the easiest rule to
  break by accident, because prose comes from a model and models round"; an
  instruction not to round is exactly the kind of control that fails silently,
  and a wrong number is the most damaging failure mode there is because trust in
  numbers is binary and does not recover (§5.2).
* **"never blends currencies"** (§7.4, D32) -- `assert_single_currency()` and
  `sum_figures()`. A mixed-currency total is a wrong number under §5.3, so
  addition across currencies raises rather than returning something plausible.
* **"batching is a claim of certainty"** (§5.1, D26) and "reversible may be
  batched, irreversible is individual, anything leaving the company is
  individual and read in full" (D29) -- `Recommendation.batchable` is
  **computed from certainty and reversibility, never supplied by a caller**, and
  `assert_batch_acceptable()` is the guard any batch endpoint must call.

What is deliberately not here
-----------------------------
* **No batch endpoint.** Task 34.8 is blocked on Q6 ("how is a batch acceptance
  undone?") and D8 cannot ship without it -- nothing that cannot be unwound as a
  batch may be offered as one. `assert_batch_acceptable()` exists so that the
  endpoint, when Q6 is answered, has one guard to call rather than re-deriving
  the rule.
* **No persistence.** Slice A defines the shape; the skills that emit
  recommendations are tasks 34.3-34.5. A table with no writer would be
  speculative, so there is no migration.
* **No ranking field.** Ranking is money at stake x how soon it stops being
  fixable (§7.3, D30) and belongs with the screen that applies it.
* **No confidence number.** §5.1/D26: uncertainty is stated in words, never a
  number. "87% confident" is meaningless to a finance user, which is why
  `Certainty` is two words and `doubt` is prose.
"""

from __future__ import annotations

import re
from decimal import Decimal
from enum import Enum
from typing import Iterable, Sequence

from pydantic import BaseModel, Field, computed_field, field_validator, model_validator

from services.atlas_capabilities import AtlasCapability

__all__ = [
    "AtlasContractError",
    "CurrencyBlendError",
    "UnwitnessedFigureError",
    "InventedNumberError",
    "NotBatchableError",
    "Certainty",
    "Reversibility",
    "FigureSource",
    "Figure",
    "What",
    "Why",
    "Action",
    "Verify",
    "Correction",
    "Recommendation",
    "assert_single_currency",
    "assert_figures_are_witnessed",
    "assert_no_undeclared_numbers",
    "assert_batch_acceptable",
    "validate_recommendation",
    "sum_figures",
    "numeric_tokens",
]


# ─────────────────────────────────────────────────────────────────────────────
# Errors — one per boundary, so a caller can tell which rule it broke
# ─────────────────────────────────────────────────────────────────────────────

class AtlasContractError(Exception):
    """Base for every §5.3 boundary violation."""


class CurrencyBlendError(AtlasContractError):
    """§7.4 / D32: cash and forecast are per currency and never blended."""


class UnwitnessedFigureError(AtlasContractError):
    """§5.3: every figure traces to a document or a computation."""


class InventedNumberError(AtlasContractError):
    """§5.3: a money-shaped number appears in prose that no figure declares."""


class NotBatchableError(AtlasContractError):
    """§5.1 / D29: this line may only be accepted individually."""


class AttachmentPromiseError(AtlasContractError):
    """D47: a Verify question promised an attachment ATLAS cannot make."""


# ─────────────────────────────────────────────────────────────────────────────
# Enums — the wire vocabulary FE Feature 23 switches on
# ─────────────────────────────────────────────────────────────────────────────

class Certainty(str, Enum):
    """Words, never a number (§5.1, D26)."""

    CERTAIN = "certain"
    #: Carries `Why.doubt` in plain language: "this might be a duplicate -- same
    #: amount and vendor, different invoice number."
    UNCERTAIN = "uncertain"


class Reversibility(str, Enum):
    """D29, the organising principle that decides every future case.

    Reversible may be batched. Irreversible is individual. Anything leaving the
    company is individual **and read in full** -- including every chase email,
    because a wrong email costs a relationship and the draft already removed the
    expensive part.
    """

    REVERSIBLE = "reversible"
    IRREVERSIBLE = "irreversible"
    LEAVES_COMPANY = "leaves_company"


class FigureSource(str, Enum):
    """Where a number came from. There is no third option (§5.3)."""

    DOCUMENT = "document"
    COMPUTED = "computed"


# ─────────────────────────────────────────────────────────────────────────────
# Number handling
# ─────────────────────────────────────────────────────────────────────────────

#: A run of digits with optional grouping separators and decimals. Matches the
#: Indian grouping the product renders ("2,41,300") as readily as "241300.00".
#:
#: **A separator only counts when a digit follows it** (BE Gap 692). The first
#: form of this pattern ended `[\d,  ']*`, which swallowed a trailing comma: in
#: the prose "...that their statement does not list: #1043, #1044" the token came
#: out as "1043," while the declared reference tokenised as "1043", so a line
#: whose numbers were correctly declared failed `assert_no_undeclared_numbers`
#: and the whole response 500'd. A comma that ends a clause is punctuation, not
#: part of the number, and the tokeniser has to be able to tell -- every emitter
#: that writes a list of invoice numbers depends on it.
_NUMBER_RE = re.compile(r"\d(?:[\d,  ']*\d)?(?:\.\d+)?")

#: Symbols and codes that make an adjacent number money-shaped.
_CURRENCY_MARKS = ("₹", "$", "€", "£", "¥", "INR", "USD", "EUR", "GBP", "Rs", "Rs.")


def _numeric_tokens(text: str) -> list[str]:
    return _NUMBER_RE.findall(text or "")


def _is_money_shaped(text: str, match_start: int, token: str) -> bool:
    """Whether a numeric token in prose is a figure rather than an incidental.

    The §5.3 boundary is about figures -- amounts, rates, balances. "the 20th",
    "12 days late" and "fixes 60 invoices a month" are prose a recommendation is
    supposed to contain, and forcing every one of them through a `Figure` would
    make the rule so noisy that emitters would route around it, which is how a
    control stops being one.

    So a token counts as a figure when any of these holds:

    * a currency symbol or code sits immediately before it ("Rs 2.4 lakh" -- and
      this is the exact shape of the rounding defect the rule exists to catch),
    * it carries a grouping separator or a decimal point ("2,41,300", "1200.50"),
    * it is four or more digits long ("241300").
    """
    if "," in token or "." in token or " " in token or " " in token or "'" in token:
        return True
    if len(token.replace(",", "").replace(".", "")) >= 4:
        return True
    prefix = text[:match_start].rstrip()
    return any(prefix.endswith(mark) for mark in _CURRENCY_MARKS)


def numeric_tokens(text: str) -> list[str]:
    """Every numeric token in a string, by the **contract's own** definition.

    Public because Slice B's emitters need it for one narrow job: declaring the
    numbers inside a string ATLAS reproduces verbatim rather than composes (an
    extraction alert copied character for character onto a line). Exposing the
    same tokeniser the checks use is the point -- an emitter that re-implemented
    "what counts as a number" would drift from the rule it is declaring against,
    and the drift would show up as a line that passes validation and reads wrong.
    """
    return _numeric_tokens(text)


def _money_tokens(text: str) -> list[str]:
    out: list[str] = []
    for m in _NUMBER_RE.finditer(text or ""):
        if _is_money_shaped(text, m.start(), m.group()):
            out.append(m.group())
    return out


# ─────────────────────────────────────────────────────────────────────────────
# The four parts
# ─────────────────────────────────────────────────────────────────────────────

class Figure(BaseModel):
    """One number, with the witness that makes it real (§5.3).

    `rendered` is the **only** form that may appear in prose. If the invoice says
    Rs 2,41,300 then `rendered` is "2,41,300" and the line says 2,41,300 -- never
    "about 2.4 lakh". `value` exists for arithmetic; it is never what a user
    reads, so a formatting change cannot quietly become a different number.
    """

    rendered: str = Field(min_length=1)
    value: Decimal
    currency: str = Field(min_length=3, max_length=3)
    source: FigureSource
    #: Required when `source` is DOCUMENT: which document, and the text in it.
    document_id: str | None = None
    quote: str | None = None
    #: Required when `source` is COMPUTED: what was computed, in words a user can
    #: check ("sum of the 14 line items", "invoice total minus payments received").
    computation: str | None = None

    @field_validator("currency")
    @classmethod
    def _iso_4217(cls, v: str) -> str:
        if not (v.isalpha() and v.isupper()):
            raise ValueError("currency must be an uppercase ISO 4217 code, e.g. INR")
        return v

    @model_validator(mode="after")
    def _witnessed(self) -> "Figure":
        if self.source is FigureSource.DOCUMENT:
            if not self.document_id or not self.quote:
                raise ValueError(
                    "a DOCUMENT figure needs document_id and the verbatim quote it came from"
                )
            in_rendered = set(_numeric_tokens(self.rendered))
            if in_rendered and not in_rendered <= set(_numeric_tokens(self.quote)):
                raise ValueError(
                    f"figure {self.rendered!r} does not appear verbatim in its quote {self.quote!r}"  # hardcode-ok: developer-facing exception text, not a rendered figure -- `rendered` is already the formatted form and re-formatting it here would hide the very mismatch being reported
                )
        else:
            if not self.computation:
                raise ValueError("a COMPUTED figure needs the computation it came from")
        return self


class What(BaseModel):
    """The invoice, the alert, the correction (§1)."""

    headline: str = Field(min_length=1)
    #: "invoice", "payment", "vendor", "rule", "document" -- open on purpose:
    #: the skills in Slice B decide their own subjects, and closing this set now
    #: would be guessing at them.
    entity_kind: str = Field(min_length=1)
    entity_id: str = Field(min_length=1)


class Why(BaseModel):
    """The reason in the user's terms (§1).

    **The completeness test**: if a user has to go and look something up to judge
    the line, the line was incomplete (D33). "4x their usual Rs 40-60k" *is* the
    history, and that is why the history belongs in `text` rather than behind a
    link.
    """

    text: str = Field(min_length=1)
    #: Every number `text` (or any other prose on the line) uses. Enforced by
    #: `assert_figures_are_witnessed` / `assert_no_undeclared_numbers`.
    figures: list[Figure] = Field(default_factory=list)
    #: Literal identifiers the prose may name -- invoice numbers, GSTINs, cheque
    #: numbers. They are references, not figures: "#1041" has no currency and no
    #: arithmetic, but it is four digits long and would otherwise trip the
    #: money-shape test.
    references: list[str] = Field(default_factory=list)
    #: Required when the line is UNCERTAIN, and forbidden otherwise. Plain
    #: language, no percentage (§5.1).
    doubt: str | None = None


class Action(BaseModel):
    """A single click (§1).

    `kind` is the identifier FE Feature 23 dispatches on; the endpoint that
    performs it is declared by the skill that emits the line (tasks 34.3-34.5).
    No URL is carried here on purpose -- Slice A would be inventing routes that
    do not exist yet, and a field the FE reads that the BE never emits is the
    precise defect class this contract was written to end.
    """

    kind: str = Field(min_length=1)
    label: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    params: dict = Field(default_factory=dict)


class Verify(BaseModel):
    """The way the user checks ATLAS themselves (§1, D24).

    Opens chat with the question pre-seeded. The document is optional because
    day-one findings -- arithmetic, validity, in-batch duplicates (§7.1) -- are
    checkable without one; the question never is, because a chat box opened with
    nothing in it asks the user to do the work the line was supposed to have
    done.

    **D47 (2026-09-18): ATLAS does not attach the document, and the question
    must not imply that it does.** `POST /chat/sessions/{id}/attachments` takes
    an uploaded file and has no by-id path for a document the tenant already
    holds (FE Gap 640), so the only way to honour an "attached" promise today
    would be to re-upload a second copy of the customer's own document to make
    the UI look right. The founder ruled the promise changes, not the plumbing:
    **a question that names a `document_id` tells the user to attach that
    document in chat and compare there**, and `document_id` names which one.

    That rule is enforced as code rather than left to an emitter's phrasing --
    see `assert_verify_does_not_promise_attachment()` below, which is called by
    `validate_recommendation()` on every line before it reaches the wire.
    """

    question: str = Field(min_length=1)
    document_id: str | None = None


class Correction(BaseModel):
    """The invoice **before and after** the fix (D45) — Slice B, task 34.3.

    **A deliberate extension to the Slice A contract, added for one ruling.**
    D45 is the concrete single-document form of §2.3/D21's "proof the teaching
    worked": a Trainer's correction line shows what the field reads now and what
    it would read once the fix is applied, on the line, before they click.

    It is a typed block rather than two sentences in `why.text` because the FE
    renders it as a before/after pair. Prose that has to be parsed to be laid out
    is a field the two sides agree about by accident, which is the defect class
    this contract exists to prevent.

    `before_rendered` and `after_rendered` are **rendered strings a user reads**,
    so they go through `Recommendation.prose()` and are held to §5.3's number
    rules exactly like `why.text`: a rounded "after" is the same defect as a
    rounded explanation, and it would be a worse one, because that is the value
    the click writes.

    `before_rendered` is nullable and `after_rendered` is not: a field that was
    never extracted has no before ("" and "not extracted" are different things,
    and NULL is the honest one), while a correction with no after is not a
    correction.
    """

    #: The field this fixes, in the user's words -- "Invoice total", "GSTIN".
    field_label: str = Field(min_length=1)
    #: The machine name the accept endpoint writes -- "grand_total".
    field_name: str = Field(min_length=1)
    before_rendered: str | None = None
    after_rendered: str = Field(min_length=1)


# ─────────────────────────────────────────────────────────────────────────────
# The recommendation
# ─────────────────────────────────────────────────────────────────────────────

class Recommendation(BaseModel):
    """One line on the work screen. The unit of everything ATLAS produces.

    It is a *recommendation*, not a finding (D7): ATLAS notices, recommends the
    next action, explains why, does it on one click, and teaches the person to
    verify it. Non-actionable lines are not lines at all (D4) -- which is why
    `action` is required and there is no `actionable` flag to splice on.
    """

    id: str = Field(min_length=1)
    #: Task 34.1: the capability required to act on this line. The work screen
    #: filters on it via `services.atlas_capabilities.visible_to`.
    capability: AtlasCapability
    #: Which skill produced it (§3.1). Free text here; the skill registry lands
    #: with the skills themselves in Slice B.
    skill: str = Field(min_length=1)

    what: What
    why: Why
    action: Action
    verify: Verify
    #: Slice B / task 34.3 (D45): present only on a line that proposes a concrete
    #: field fix -- the Trainer's correction lines. Optional because most lines
    #: are not corrections; a line that carries one is held to the same number
    #: rules on both halves of it (see `prose()`).
    correction: Correction | None = None

    certainty: Certainty = Certainty.CERTAIN
    reversibility: Reversibility = Reversibility.REVERSIBLE
    #: The one currency this line speaks. Every figure on it must agree (§7.4).
    currency: str = Field(min_length=3, max_length=3)

    @field_validator("currency")
    @classmethod
    def _iso_4217(cls, v: str) -> str:
        if not (v.isalpha() and v.isupper()):
            raise ValueError("currency must be an uppercase ISO 4217 code, e.g. INR")
        return v

    @model_validator(mode="after")
    def _doubt_matches_certainty(self) -> "Recommendation":
        if self.certainty is Certainty.UNCERTAIN and not (self.why.doubt or "").strip():
            raise ValueError(
                "an UNCERTAIN recommendation must state the doubt in words (§5.1)"
            )
        if self.certainty is Certainty.CERTAIN and (self.why.doubt or "").strip():
            raise ValueError(
                "a CERTAIN recommendation must not carry a doubt -- set certainty=UNCERTAIN (§5.1)"
            )
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def batchable(self) -> bool:
        """Whether this line may be accepted as part of a batch.

        **Computed, never supplied.** Batching is a claim of certainty (D26) and
        "approve all 8" means the user delegated judgment -- a wrong
        recommendation accepted in a batch is the dangerous failure mode (§5.2).
        Making this an input would put the claim in the hands of whichever
        emitter is being written that week; making it a function of certainty and
        reversibility means D29 is enforced once, here, for every line type that
        will ever exist.
        """
        return (
            self.certainty is Certainty.CERTAIN
            and self.reversibility is Reversibility.REVERSIBLE
        )

    def prose(self) -> list[str]:
        """Every string a user reads on this line.

        The number checks run over all of them, not only `why.text`: a rounded
        figure in a button label is the same defect as a rounded figure in the
        explanation.
        """
        strings = [
            self.what.headline,
            self.why.text,
            self.why.doubt or "",
            self.action.label,
            self.verify.question,
        ]
        if self.correction is not None:
            # Task 34.3 / D45: the before/after pair is read by the user and is
            # the value the click writes, so it is prose for every purpose this
            # method serves. A rounded `after_rendered` that skipped these checks
            # would be the worst instance of §5.3's "never invents a number":
            # the number that gets saved.
            strings.extend(
                [
                    self.correction.field_label,
                    self.correction.before_rendered or "",
                    self.correction.after_rendered,
                ]
            )
        return strings


# ─────────────────────────────────────────────────────────────────────────────
# The deterministic assertions (CONVENTIONS hard rule 3)
# ─────────────────────────────────────────────────────────────────────────────

def assert_single_currency(rec: Recommendation) -> None:
    """§7.4 / D32: one line, one currency.

    Multi-currency, single entity. A line that quotes a rupee invoice and a
    dollar payment in the same breath has already blended them in the reader's
    head even if it never added them up.
    """
    for fig in rec.why.figures:
        if fig.currency != rec.currency:
            raise CurrencyBlendError(
                f"recommendation {rec.id} is in {rec.currency} but figure "
                f"{fig.rendered!r} is in {fig.currency}"
            )


def sum_figures(figures: Sequence[Figure]) -> tuple[Decimal, str]:
    """Total a set of figures, refusing to blend currencies (§7.4, D32).

    Every cash and forecast total in ATLAS goes through here. A mixed-currency
    total is a wrong number under §5.3, so this raises instead of returning one:
    there is no safe fallback, and a plausible-looking wrong total is worse than
    an error because nobody checks it.
    """
    if not figures:
        raise CurrencyBlendError("cannot total an empty set of figures -- no currency to report")
    currencies = {f.currency for f in figures}
    if len(currencies) > 1:
        raise CurrencyBlendError(
            "refusing to total across currencies: " + ", ".join(sorted(currencies))
        )
    currency = currencies.pop()
    return sum((f.value for f in figures), Decimal("0")), currency


def assert_figures_are_witnessed(rec: Recommendation) -> None:
    """§5.3: every figure traces to a document or a computation, and is used.

    `Figure`'s own validator already enforces that a DOCUMENT figure quotes the
    text it came from and a COMPUTED figure names its computation. What this adds
    is that **a declared figure must actually appear in the prose**. Without it,
    an emitter could launder any number by adding a figure nobody reads --
    declaring is supposed to be the cost of using a number, not a way to widen
    the whitelist.
    """
    blob = " ".join(rec.prose())
    for fig in rec.why.figures:
        if fig.rendered not in blob:
            raise UnwitnessedFigureError(
                f"recommendation {rec.id} declares figure {fig.rendered!r} that no "
                f"rendered string uses -- declare only the figures the line shows"
            )


def assert_no_undeclared_numbers(rec: Recommendation) -> None:
    """§5.3, the one the spec says is easiest to break by accident.

    Every money-shaped number in the prose must be a declared figure's `rendered`
    form, or a declared reference. This is what catches "about Rs 2.4 lakh" on a
    line whose invoice says 2,41,300: the model rounded, the figure it declared
    reads 2,41,300, the prose token reads 2.4, and they do not match.

    A prompt instruction not to round cannot catch that, because the failure is
    silent and looks like good writing.
    """
    declared: set[str] = set()
    for fig in rec.why.figures:
        declared.update(_numeric_tokens(fig.rendered))
    for ref in rec.why.references:
        declared.update(_numeric_tokens(ref))

    for text in rec.prose():
        for token in _money_tokens(text):
            if token not in declared:
                raise InventedNumberError(
                    f"recommendation {rec.id} renders {token!r} in {text!r}, which no "
                    f"figure declares -- every figure traces to a document or a computation"
                )


def assert_batch_acceptable(lines: Iterable[Recommendation]) -> None:
    """The guard every batch endpoint calls before accepting anything (§5.1, §5.3).

    Three rules collapse into one test on `batchable`:

    * an uncertain recommendation is never in a batch (§5.1) -- batching is a
      claim of certainty;
    * irreversible is individual (D29);
    * **anything leaving the company is individual and read in full** (D29) --
      so an outbound message cannot be sent by a batch endpoint, which is a
      named §11 invariant. `Reversibility.LEAVES_COMPANY` fails `batchable`, so
      a chase email cannot reach a batch even if some future emitter marks it
      certain.

    There is no batch endpoint yet: task 34.8 is blocked on Q6 (how a batch
    acceptance is undone), and nothing that cannot be unwound as a batch may be
    offered as one. This exists so that endpoint has one guard to call rather
    than re-deriving the rule at the call site.
    """
    for rec in lines:
        if not rec.batchable:
            raise NotBatchableError(
                f"recommendation {rec.id} is {rec.certainty.value}/"  # hardcode-ok: developer-facing exception text; the interpolated values are enum names, not money
                f"{rec.reversibility.value} and must be accepted individually"  # hardcode-ok: developer-facing exception text; the interpolated value is an enum name, not money
            )


#: Phrases that claim the document is already in the conversation. D47: ATLAS
#: does not attach anything, so none of these may appear in a Verify question.
#: A fixed list, matched case-insensitively -- deterministic code, not a prompt
#: rule (CONVENTIONS hard rule 3), because "does this sentence over-promise" is
#: exactly the kind of judgement an LLM makes differently on each run.
_ATTACHMENT_ALREADY_MADE = (
    "i have attached",
    "i've attached",
    "i attached",
    "already attached",
    "is attached",
    "are attached",
    "attached for you",
    "attached below",
    "attached here for",
    "with the document attached",
    "document attached",
)

#: The instruction a document-bearing question must actually carry. One token,
#: because the phrasing is the emitter's and only the promise is the contract's.
_ATTACH_INSTRUCTION = "attach"


def assert_verify_does_not_promise_attachment(rec: Recommendation) -> None:
    """D47: Verify tells the user to attach and compare; it never claims ATLAS did.

    Two rules, and they are opposite halves of the same promise:

    1. **No question may say the document is already attached.** It never is.
       `POST /chat/sessions/{id}/attachments` takes an uploaded file and has no
       by-id path for a document the tenant already holds (FE Gap 640), and the
       only way to honour such a claim would be to re-upload a second copy of
       the customer's own document so the UI looked right. §5.2 -- "right flag,
       wrong reason" -- costs credibility quietly; a promise the product cannot
       keep costs it loudly.
    2. **A question that names a `document_id` must say to attach it.** The
       document id is the *only* thing that tells the user which document
       settles the question. A line that carries one and never mentions
       attaching leaves the user to guess the step, which is the same failure in
       a quieter form.

    A question with no `document_id` is unconstrained beyond rule 1 -- the cash
    position, a stuck ingestion source and a quiet Drive folder are checkable
    without any paperwork.
    """
    question = rec.verify.question
    lowered = question.lower()

    for phrase in _ATTACHMENT_ALREADY_MADE:
        if phrase in lowered:
            raise AttachmentPromiseError(
                f"recommendation {rec.id} says {phrase!r} in its verify question, "  # hardcode-ok: developer-facing exception text; the interpolated values are an id and a fixed phrase, not money
                "but ATLAS never attaches a document (D47) -- ask the user to "
                "attach it and compare in chat"
            )

    if rec.verify.document_id and _ATTACH_INSTRUCTION not in lowered:
        raise AttachmentPromiseError(
            f"recommendation {rec.id} names a verify document but its question "  # hardcode-ok: developer-facing exception text; the interpolated value is an id, not money
            "never tells the user to attach it (D47)"
        )


def validate_recommendation(rec: Recommendation) -> Recommendation:
    """Run every boundary. **The single entry point every emitter calls.**

    Construction alone enforces the four parts and the certainty/doubt pairing;
    the checks here need the whole line assembled. Returns the recommendation so
    it can be used inline: `lines.append(validate_recommendation(rec))`.

    Order is deliberate and load-bearing for the error a caller sees. A rounded
    figure fails **both** number checks -- the prose token is undeclared *and*
    the correctly-declared figure now appears nowhere -- and "you rendered 2.4,
    which nothing declares" names the actual mistake, where "you declared a
    figure the line never shows" describes its shadow.
    """
    assert_single_currency(rec)
    assert_no_undeclared_numbers(rec)
    assert_figures_are_witnessed(rec)
    assert_verify_does_not_promise_attachment(rec)
    return rec
