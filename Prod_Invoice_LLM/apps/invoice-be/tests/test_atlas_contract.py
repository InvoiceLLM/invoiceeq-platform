"""Feature 34 (ATLAS) Slice A — tasks 34.1 and 34.2.

Spec: `docs/feature_34_atlas.md` §11, "Verification plan". Each invariant there is
a sentence; each sentence is a test here.

* A user with no grants receives **zero** lines (§2.1)
* A line whose capability the user lacks is **absent**, not disabled (§2.1)
* An uncertain recommendation is **never** in a batch (§5.1)
* No response blends currencies (§7.4)
* Every figure in a rendered line appears verbatim in a document or a computed
  value (§5.3)
* An outbound message cannot be sent by a batch endpoint (§5.3)

The last one is asserted against `assert_batch_acceptable`, the guard a batch
endpoint must call, because **there is no batch endpoint**: task 34.8 is blocked
on Q6 (how a batch acceptance is undone) and D8 cannot ship without it.

CONVENTIONS hard rule 2: the capability half runs against real Postgres at
`localhost:5433/invoice_db`, resolving grants from real `users` rows through the
same `RoleMapper.resolve_permissions()` a request uses. BE Gap 666 is the
standing warning -- a skip guard reading an env var the app never exports hid 23
tests behind a green report -- so the guard below reads `get_settings()`.
"""

from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlmodel import Session, SQLModel, create_engine, select

from config import get_settings
from models import User
from services.atlas_capabilities import AtlasCapability, GrantSet, visible_to
from services.atlas_contract import (
    Action,
    Certainty,
    CurrencyBlendError,
    Figure,
    FigureSource,
    InventedNumberError,
    AttachmentPromiseError,
    NotBatchableError,
    Recommendation,
    Reversibility,
    UnwitnessedFigureError,
    Verify,
    What,
    Why,
    assert_batch_acceptable,
    assert_single_currency,
    assert_verify_does_not_promise_attachment,
    numeric_tokens,
    sum_figures,
    validate_recommendation,
)

RUPEE = "₹"


# ═════════════════════════════════════════════════════════════════════════════
# Builders — a valid line, so every test below varies exactly one thing
# ═════════════════════════════════════════════════════════════════════════════

def _figure(rendered="2,41,300", value="241300", currency="INR"):
    return Figure(
        rendered=rendered,
        value=Decimal(value),
        currency=currency,
        source=FigureSource.DOCUMENT,
        document_id="doc-1",
        quote=f"Grand Total {RUPEE}{rendered}",
    )


def _rec(**overrides) -> Recommendation:
    base = dict(
        id="rec-1",
        capability=AtlasCapability.AUDIT,
        skill="duplicate_payment",
        what=What(
            headline="Kumar Supplies invoice #1041",
            entity_kind="invoice",
            entity_id="inv-1041",
        ),
        why=Why(
            text=f"This vendor has never billed above {RUPEE}2,41,300.",
            figures=[_figure()],
            references=["#1041"],
        ),
        action=Action(kind="approve_invoice", label="Approve", target_id="inv-1041"),
        verify=Verify(
            # D47: a question naming a document must tell the user to attach it.
            # ATLAS never attaches anything -- `assert_verify_does_not_promise_
            # attachment()` is what stops an emitter implying otherwise.
            question="Attach it here — is this the same invoice as #1041?",
            document_id="doc-1",
        ),
        currency="INR",
    )
    base.update(overrides)
    return Recommendation(**base)


# ═════════════════════════════════════════════════════════════════════════════
# §1 / D7 — the four parts. A line missing any of them is a defect.
# ═════════════════════════════════════════════════════════════════════════════

def test_a_valid_line_carries_what_why_action_and_verify():
    rec = validate_recommendation(_rec())
    assert rec.what.headline and rec.why.text and rec.action.label and rec.verify.question


@pytest.mark.parametrize("missing", ["what", "why", "action", "verify"])
def test_a_line_missing_any_of_the_four_parts_cannot_be_constructed(missing):
    fields = {
        "id": "rec-x",
        "capability": AtlasCapability.AUDIT,
        "skill": "s",
        "what": What(headline="h", entity_kind="invoice", entity_id="i"),
        "why": Why(text="w"),
        "action": Action(kind="k", label="l", target_id="i"),
        "verify": Verify(question="q"),
        "currency": "INR",
    }
    del fields[missing]
    with pytest.raises(ValidationError):
        Recommendation(**fields)


def test_verify_may_omit_the_document_but_never_the_question():
    # Day-one findings -- arithmetic, validity, in-batch duplicates (§7.1) --
    # are checkable with no document to attach.
    Verify(question="Do these line items sum to the total?")
    with pytest.raises(ValidationError):
        Verify(question="", document_id="doc-1")


# ═════════════════════════════════════════════════════════════════════════════
# §2.1 / D1, D2, D3, D6 — capability, not clearance
# ═════════════════════════════════════════════════════════════════════════════

def _line(capability):
    return _rec(id=f"rec-{capability.value}", capability=capability)


ALL_LINES = [_line(c) for c in AtlasCapability]


def test_a_user_with_no_grants_receives_zero_lines():
    ungranted = GrantSet()
    assert ungranted.is_ungranted()
    assert visible_to(ALL_LINES, ungranted) == []


def test_a_line_whose_capability_the_user_lacks_is_absent_not_disabled():
    auditor = GrantSet(can_audit=True)
    visible = visible_to(ALL_LINES, auditor)

    assert [r.capability for r in visible] == [AtlasCapability.AUDIT]
    # Absent, not present-and-flagged: nothing in the response mentions the
    # train / load / admin lines at all, so no vendor or amount leaks through a
    # greyed-out row.
    assert all(r.capability is AtlasCapability.AUDIT for r in visible)
    assert len(visible) < len(ALL_LINES)


def test_grants_stack_into_one_merged_list_not_tabs():
    both = GrantSet(can_audit=True, can_load=True)
    assert [r.capability for r in visible_to(ALL_LINES, both)] == [
        AtlasCapability.AUDIT,
        AtlasCapability.LOAD,
    ]


def test_cash_and_forecast_are_admin_only_even_with_all_three_grants():
    # D2. The one thing the old `exec` clearance genuinely protected, kept as a
    # capability rule rather than as a column on six tables.
    everything_but_admin = GrantSet(can_audit=True, can_train=True, can_load=True)
    assert not everything_but_admin.holds(AtlasCapability.ADMIN)
    assert AtlasCapability.ADMIN not in {
        r.capability for r in visible_to(ALL_LINES, everything_but_admin)
    }


def test_the_admin_is_the_superset():
    admin = GrantSet(is_admin=True)
    assert [r.capability for r in visible_to(ALL_LINES, admin)] == list(AtlasCapability)


def test_a_no_role_user_with_can_load_is_a_loader():
    # D3 is about grants, not roles.
    loader = GrantSet(can_load=True)
    assert not loader.is_ungranted()
    assert [r.capability for r in visible_to(ALL_LINES, loader)] == [AtlasCapability.LOAD]


def test_can_send_invoices_is_not_a_separate_audience():
    # D6: outbound folds into can_audit. GrantSet has no field for it, so there
    # is nothing to branch on -- asserted here so a future edit cannot quietly
    # reintroduce the audience.
    assert not hasattr(GrantSet(), "can_send_invoices")
    outbound = _rec(id="rec-chase", capability=AtlasCapability.AUDIT, skill="chase_overdue")
    assert visible_to([outbound], GrantSet(can_audit=True)) == [outbound]
    assert visible_to([outbound], GrantSet()) == []


def test_no_clearance_rank_exists_anywhere_in_the_capability_vocabulary():
    # D1, and spec §8's removal is satisfied by never building it: there is no
    # ops/exec value, and capabilities are a set, never an ordered rank.
    values = {c.value for c in AtlasCapability}
    assert "ops" not in values and "exec" not in values
    assert isinstance(GrantSet(can_audit=True).capabilities(), frozenset)


# ═════════════════════════════════════════════════════════════════════════════
# §5.1 / §5.3 / D26 / D29 — batching is a claim of certainty
# ═════════════════════════════════════════════════════════════════════════════

def test_an_uncertain_recommendation_is_never_in_a_batch():
    uncertain = _rec(
        certainty=Certainty.UNCERTAIN,
        why=Why(
            text=f"This vendor has never billed above {RUPEE}2,41,300.",
            figures=[_figure()],
            references=["#1041"],
            doubt="This might be a duplicate -- same amount and vendor, different invoice number.",
        ),
    )
    assert uncertain.batchable is False
    with pytest.raises(NotBatchableError):
        assert_batch_acceptable([_rec(), uncertain])


def test_an_outbound_message_cannot_be_sent_by_a_batch_endpoint():
    # D29: anything leaving the company is individual and read in full --
    # including every chase email -- even when ATLAS is certain about it.
    chase = _rec(
        id="rec-chase",
        skill="chase_overdue",
        certainty=Certainty.CERTAIN,
        reversibility=Reversibility.LEAVES_COMPANY,
        action=Action(kind="send_chase_email", label="Send", target_id="inv-1041"),
    )
    assert chase.batchable is False
    with pytest.raises(NotBatchableError):
        assert_batch_acceptable([chase])


def test_irreversible_is_individual():
    irreversible = _rec(reversibility=Reversibility.IRREVERSIBLE)
    assert irreversible.batchable is False
    with pytest.raises(NotBatchableError):
        assert_batch_acceptable([irreversible])


def test_reversible_and_certain_may_be_batched():
    assert _rec().batchable is True
    assert_batch_acceptable([_rec(), _rec(id="rec-2")])


def test_batchable_is_computed_and_cannot_be_asserted_by_a_caller():
    # An emitter claiming certainty is the failure this closes: "wrong
    # recommendation, accepted" is §5.2's dangerous mode.
    rec = _rec(certainty=Certainty.UNCERTAIN, why=Why(text="hmm", doubt="not sure"))
    assert rec.batchable is False
    with pytest.raises((AttributeError, ValueError)):
        rec.batchable = True


def test_uncertainty_is_stated_in_words_and_is_required():
    with pytest.raises(ValidationError):
        _rec(certainty=Certainty.UNCERTAIN)  # no doubt stated
    with pytest.raises(ValidationError):
        _rec(why=Why(text="t", doubt="but maybe not"))  # doubt without UNCERTAIN


# ═════════════════════════════════════════════════════════════════════════════
# §7.4 / D32 — multi-currency, never blended
# ═════════════════════════════════════════════════════════════════════════════

def test_no_response_blends_currencies():
    blended = _rec(
        why=Why(
            text=f"This vendor has never billed above {RUPEE}2,41,300.",
            figures=[_figure(currency="USD")],
            references=["#1041"],
        )
    )
    with pytest.raises(CurrencyBlendError):
        assert_single_currency(blended)
    with pytest.raises(CurrencyBlendError):
        validate_recommendation(blended)


def test_totalling_across_currencies_raises_rather_than_returning_a_wrong_number():
    with pytest.raises(CurrencyBlendError):
        sum_figures([_figure(), _figure(rendered="1,000", value="1000", currency="USD")])
    total, currency = sum_figures([_figure(), _figure(rendered="1,000", value="1000")])
    assert (total, currency) == (Decimal("242300"), "INR")


def test_an_empty_set_has_no_currency_to_report():
    with pytest.raises(CurrencyBlendError):
        sum_figures([])


# ═════════════════════════════════════════════════════════════════════════════
# §5.3 — ATLAS never invents a number
# ═════════════════════════════════════════════════════════════════════════════

def test_every_figure_traces_to_a_document_or_a_computation():
    with pytest.raises(ValidationError):
        Figure(
            rendered="2,41,300",
            value=Decimal("241300"),
            currency="INR",
            source=FigureSource.DOCUMENT,
        )  # no document_id, no quote
    with pytest.raises(ValidationError):
        Figure(
            rendered="2,41,300",
            value=Decimal("241300"),
            currency="INR",
            source=FigureSource.COMPUTED,
        )  # no computation
    Figure(
        rendered="2,41,300",
        value=Decimal("241300"),
        currency="INR",
        source=FigureSource.COMPUTED,
        computation="sum of the 14 line items",
    )


def test_a_document_figure_must_appear_verbatim_in_its_quote():
    with pytest.raises(ValidationError):
        Figure(
            rendered="2,41,300",
            value=Decimal("241300"),
            currency="INR",
            source=FigureSource.DOCUMENT,
            document_id="doc-1",
            quote=f"Grand Total {RUPEE}2,41,299",
        )


def test_a_rounded_figure_in_prose_is_rejected():
    # The defect the rule exists for: the invoice says 2,41,300 and the model
    # wrote "about Rs 2.4 lakh".
    rounded = _rec(
        why=Why(
            text=f"They have billed about {RUPEE}2.4 lakh.",
            figures=[_figure()],
            references=["#1041"],
        )
    )
    with pytest.raises(InventedNumberError):
        validate_recommendation(rounded)


def test_a_money_figure_in_any_rendered_string_must_be_declared():
    # Not just `why.text`: a rounded figure in a button label is the same defect.
    with pytest.raises(InventedNumberError):
        validate_recommendation(
            _rec(action=Action(kind="pay", label=f"Approve {RUPEE}2,41,301", target_id="i"))
        )


def test_a_declared_figure_that_the_line_never_shows_is_rejected():
    with pytest.raises(UnwitnessedFigureError):
        validate_recommendation(
            _rec(
                what=What(
                    headline="Kumar Supplies", entity_kind="invoice", entity_id="inv-a"
                ),
                why=Why(
                    text="This looks like a duplicate.",
                    figures=[_figure()],
                ),
                action=Action(kind="k", label="Review", target_id="inv-a"),
                verify=Verify(question="Is this a duplicate?"),
            )
        )


def test_dates_and_counts_are_prose_not_figures():
    # "the 20th", "12 days late", "60 invoices a month" must not have to be
    # declared, or emitters would route around the rule entirely.
    validate_recommendation(
        _rec(
            why=Why(
                text="Sharma pays 12 days late every time, so expect it after the 20th; "
                "this rule fixes 60 invoices a month.",
            ),
            verify=Verify(question="Is that right?"),
            what=What(headline="Sharma", entity_kind="vendor", entity_id="v-1"),
            action=Action(kind="k", label="Accept", target_id="v-1"),
        )
    )


def test_an_invoice_number_is_a_reference_not_a_figure():
    validate_recommendation(_rec())  # "#1041" is declared in references
    with pytest.raises(InventedNumberError):
        validate_recommendation(
            _rec(
                what=What(
                    headline="Kumar Supplies invoice #9999",
                    entity_kind="invoice",
                    entity_id="inv-9999",
                )
            )
        )


def test_a_comma_that_ends_a_clause_is_not_part_of_the_number():
    """**BE Gap 692**, found by the first live call this contract ever served.

    `recon_recommendations()` writes a list of invoice numbers -- "…does not
    list: #1043, #1044" -- and declares each as a reference. The tokeniser used
    to swallow the trailing comma, so the prose token was "1043," while the
    declared reference tokenised as "1043": a line whose numbers were all
    correctly declared failed `assert_no_undeclared_numbers`, and
    `POST /atlas/recon` answered 500 on a perfectly ordinary statement.

    Both halves are asserted, because a tokeniser that stopped seeing grouping
    separators would "fix" this by making the rule blind to 2,41,300.
    """
    assert numeric_tokens("#1043, #1044") == ["1043", "1044"]
    assert numeric_tokens("2,41,300.00 and 1,00,000.00, together") == [
        "2,41,300.00",
        "1,00,000.00",
    ]

    validate_recommendation(
        _rec(
            why=Why(
                text="Two invoices are not on their statement: #1043, #1044.",
                figures=[],
                # "#1041" is the default line's own subject, declared by the
                # builder; the two new references are what this test is about.
                references=["#1041", "#1043", "#1044"],
            )
        )
    )


# ═════════════════════════════════════════════════════════════════════════════
# Hard rule 2 — the capability half against real Postgres
# ═════════════════════════════════════════════════════════════════════════════

_SETTINGS = get_settings()

postgres_only = pytest.mark.skipif(
    not str(_SETTINGS.DATABASE_URL or "").startswith("postgresql"),
    reason=(
        "Hard rule 2: grant resolution is only evidence on Postgres. "
        "Set DATABASE_URL to the dev Postgres (localhost:5433/invoice_db) and re-run. "
        "Read through get_settings(), never a bare env var -- BE Gap 666."
    ),
)


@pytest.fixture(scope="module")
def pg_session():
    """Deliberate deviation from the house fixture, and the reason for it.

    `tests/test_invoice_builder.py` (and its neighbours) skip on
    `psycopg2.OperationalError`, i.e. "Postgres is configured but unreachable"
    silently becomes a green report. That is BE Gap 666's exact failure mode,
    and it fired here during this very build: one run of this file reported
    `31 passed`, and a re-run of the same test on the same healthy container
    reported it SKIPPED on a transient `server closed the connection
    unexpectedly` over `::1`. Filed as BE Gap 697.

    So: the URL not being Postgres is a legitimate skip -- that developer asked
    for SQLite and hard rule 2 says their run is not evidence either way. A
    Postgres URL that will not connect is a **failure**, after one retry for the
    transient above. A test that hides itself is worse than a test that is red.
    """
    import time

    psycopg2 = pytest.importorskip("psycopg2")
    url = get_settings().DATABASE_URL
    if not str(url).startswith("postgresql"):
        pytest.skip("DATABASE_URL is not PostgreSQL - see .claude/skills/verify-postgres")

    last: Exception | None = None
    for attempt in range(2):
        try:
            psycopg2.connect(url).close()
            last = None
            break
        except psycopg2.OperationalError as exc:
            last = exc
            time.sleep(1)
    if last is not None:
        pytest.fail(
            f"DATABASE_URL points at Postgres but it did not connect after 2 attempts: {last}"
        )

    engine = create_engine(url)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _persist(pg_session, role, **flags):
    tag = uuid4().hex[:12]
    user = User(
        email=f"atlas-{tag}@example.test",
        clerk_user_id=f"user_atlas_{tag}",
        role=role,
        **flags,
    )
    pg_session.add(user)
    pg_session.commit()
    return pg_session.exec(select(User).where(User.id == user.id)).one()


@postgres_only
def test_grants_resolve_from_real_user_rows(pg_session):
    """The grant flags are real columns, not an ATLAS-only model (Feature 1.1 / Gap 73).

    Each row is written, read back from Postgres, and turned into a `GrantSet`
    through `RoleMapper.resolve_permissions()` -- the same call a request makes
    -- so an ATLAS line and an API route can never disagree about a grant.
    """
    created = []
    try:
        restricted = _persist(pg_session, "Restricted")
        created.append(restricted)
        assert GrantSet.from_user(restricted.role, restricted).is_ungranted()
        assert visible_to(ALL_LINES, GrantSet.from_user(restricted.role, restricted)) == []

        auditor = _persist(pg_session, "Auditor", can_audit=True)
        created.append(auditor)
        assert [
            r.capability for r in visible_to(ALL_LINES, GrantSet.from_user(auditor.role, auditor))
        ] == [AtlasCapability.AUDIT]

        trainer = _persist(pg_session, "Trainer", can_train=True)
        created.append(trainer)
        assert [
            r.capability for r in visible_to(ALL_LINES, GrantSet.from_user(trainer.role, trainer))
        ] == [AtlasCapability.TRAIN]

        # D3: no assigned role, but can_load granted -- a Loader, not an empty
        # state. This is the row the old clearance binary would have handed
        # every ops finding to.
        no_role_loader = _persist(pg_session, "Restricted", can_load=True)
        created.append(no_role_loader)
        grants = GrantSet.from_user(no_role_loader.role, no_role_loader)
        assert not grants.is_ungranted()
        assert [r.capability for r in visible_to(ALL_LINES, grants)] == [AtlasCapability.LOAD]

        # D6: can_send_invoices alone is not an audience.
        sender = _persist(pg_session, "Restricted", can_send_invoices=True)
        created.append(sender)
        assert GrantSet.from_user(sender.role, sender).is_ungranted()
        assert visible_to(ALL_LINES, GrantSet.from_user(sender.role, sender)) == []

        # §2.2: the Admin is the superset, even with a flag explicitly revoked.
        admin = _persist(
            pg_session, "Admin", can_audit=False, can_train=True, can_load=True
        )
        created.append(admin)
        assert [
            r.capability for r in visible_to(ALL_LINES, GrantSet.from_user(admin.role, admin))
        ] == list(AtlasCapability)
    finally:
        for row in created:
            pg_session.delete(row)
        pg_session.commit()


# ═════════════════════════════════════════════════════════════════════════════
# D47 (2026-09-18) — Verify tells the user to attach; it never claims ATLAS did
#
# Added with the D47 build. These are the deterministic half of the ruling:
# the wording change in the emitters is what users read, and this is what stops
# the next emitter re-introducing the promise. CONVENTIONS hard rule 3 -- a
# check that decides correctness is code, never a prompt rule or a reviewer's
# memory.
# ═════════════════════════════════════════════════════════════════════════════


def test_a_verify_question_may_not_claim_the_document_is_attached():
    """The promise FE Gap 640 found unkeepable, refused at the contract."""
    for claim in (
        "The invoice is attached — does the total add up?",
        "I have attached the quotation. Is the rate right?",
        "Compare with the document attached and tell me if it agrees.",
    ):
        with pytest.raises(AttachmentPromiseError):
            assert_verify_does_not_promise_attachment(
                _rec(verify=Verify(question=claim))
            )


def test_a_question_naming_a_document_must_say_to_attach_it():
    """`document_id` names which document; the question must ask for it."""
    with pytest.raises(AttachmentPromiseError):
        assert_verify_does_not_promise_attachment(
            _rec(
                verify=Verify(
                    question="Show me how you read this — is the total right?",
                    document_id="doc-1",
                )
            )
        )

    # The same line, phrased the way D47 requires, passes.
    assert_verify_does_not_promise_attachment(
        _rec(
            verify=Verify(
                question="Attach it here and show me how you read it.",
                document_id="doc-1",
            )
        )
    )


def test_a_question_with_no_document_needs_no_attach_instruction():
    """The cash position and a quiet ingestion source need no paperwork."""
    assert_verify_does_not_promise_attachment(
        _rec(verify=Verify(question="Which invoices make up this number?"))
    )


def test_validate_recommendation_runs_the_attachment_check():
    """It is on the single entry point, not a function an emitter may forget."""
    with pytest.raises(AttachmentPromiseError):
        validate_recommendation(
            _rec(
                verify=Verify(
                    question="The statement is attached — compare it.",
                    document_id="doc-1",
                )
            )
        )
