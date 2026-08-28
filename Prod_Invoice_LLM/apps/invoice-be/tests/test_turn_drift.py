"""Gap 324 (BE): online turn-sequence drift heuristic.

Pure unit tests -- `detect_turn_drift()` is deterministic regex over SQL text
and question text, no DB, no LLM, no network.
"""
from services.turn_drift import DROPPED_FILTER, STALE_ENTITY, detect_turn_drift


def test_no_prior_sql_means_no_flags():
    """A first turn, or a turn following a RAG-route turn, has nothing to
    compare against -- must not flag anything."""
    flags = detect_turn_drift(
        prev_sql="", curr_sql="SELECT * FROM invoice WHERE grand_total > 1000",
        curr_question="which of those is oldest",
    )
    assert flags == []


def test_dropped_filter_on_pronoun_followup():
    prev_sql = "SELECT * FROM invoice WHERE tenant_id = 't1' AND grand_total > 20000"
    curr_sql = "SELECT * FROM invoice WHERE tenant_id = 't1' ORDER BY invoice_date ASC LIMIT 1"
    flags = detect_turn_drift(prev_sql=prev_sql, curr_sql=curr_sql, curr_question="which of those is oldest")
    assert DROPPED_FILTER in flags


def test_dropped_filter_not_flagged_on_a_genuinely_fresh_question():
    """A follow-up phrase absent -- this reads as a new, unrelated question,
    not a filter silently lost off an existing one."""
    prev_sql = "SELECT * FROM invoice WHERE tenant_id = 't1' AND grand_total > 20000"
    curr_sql = "SELECT * FROM invoice WHERE tenant_id = 't1' AND status = 'PAID'"
    flags = detect_turn_drift(
        prev_sql=prev_sql, curr_sql=curr_sql, curr_question="how many invoices are marked paid"
    )
    assert DROPPED_FILTER not in flags


def test_filter_retained_is_not_flagged():
    prev_sql = "SELECT * FROM invoice WHERE grand_total > 20000"
    curr_sql = "SELECT * FROM invoice WHERE grand_total > 20000 ORDER BY invoice_date ASC LIMIT 1"
    flags = detect_turn_drift(prev_sql=prev_sql, curr_sql=curr_sql, curr_question="which of those is oldest")
    assert flags == []


def test_stale_entity_on_topic_switch():
    prev_sql = "SELECT * FROM invoice WHERE vendor_name = 'Acme Corp'"
    curr_sql = "SELECT * FROM invoice WHERE vendor_name = 'Acme Corp' AND status = 'PAID'"
    flags = detect_turn_drift(
        prev_sql=prev_sql, curr_sql=curr_sql, curr_question="how about for Beta Industries"
    )
    assert STALE_ENTITY in flags


def test_stale_entity_not_flagged_when_question_names_the_same_vendor():
    prev_sql = "SELECT * FROM invoice WHERE vendor_name = 'Acme Corp'"
    curr_sql = "SELECT * FROM invoice WHERE vendor_name = 'Acme Corp' AND status = 'PAID'"
    flags = detect_turn_drift(
        prev_sql=prev_sql, curr_sql=curr_sql, curr_question="show only the paid ones from Acme Corp"
    )
    assert STALE_ENTITY not in flags


def test_stale_entity_not_flagged_when_no_proper_noun_in_question():
    prev_sql = "SELECT * FROM invoice WHERE vendor_name = 'Acme Corp'"
    curr_sql = "SELECT * FROM invoice WHERE vendor_name = 'Acme Corp' AND status = 'PAID'"
    flags = detect_turn_drift(prev_sql=prev_sql, curr_sql=curr_sql, curr_question="just the paid ones")
    assert flags == []


def test_both_flags_can_fire_on_the_same_turn():
    prev_sql = "SELECT * FROM invoice WHERE vendor_name = 'Acme Corp' AND grand_total > 20000"
    curr_sql = "SELECT * FROM invoice WHERE vendor_name = 'Acme Corp'"
    flags = detect_turn_drift(
        prev_sql=prev_sql, curr_sql=curr_sql, curr_question="which of those is from Beta Industries"
    )
    assert set(flags) == {DROPPED_FILTER, STALE_ENTITY}
