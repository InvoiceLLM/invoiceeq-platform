"""BE Gaps 537/538: removing dismissed alerts (utils/alert_dismissal.py). Pure functions, no database."""
from utils.alert_dismissal import dismiss_alerts

SUBTOTAL = {"type": "subtotal_not_verified_in_source", "field": "subtotal", "message": "1,250.00"}
TOTAL = {"type": "grand_total_not_verified_in_source", "field": "grand_total", "message": "1,250.00"}


def test_an_object_dismissal_removes_only_the_alert_it_describes():
    assert dismiss_alerts([SUBTOTAL, TOTAL], [SUBTOTAL]) == ([TOTAL], [SUBTOTAL], [])


def test_an_id_dismissal_picks_that_alert_among_otherwise_identical_ones():
    first, second = {**SUBTOTAL, "id": "a"}, {**SUBTOTAL, "id": "b"}
    assert dismiss_alerts([first, second], [{"id": "b"}]) == ([first], [second], [])


def test_a_string_removes_one_alert_per_entry_by_id_then_text_then_message_then_type():
    with_id = {**TOTAL, "id": "x"}
    remaining, dismissed, unmatched = dismiss_alerts(
        ["Math mismatch", SUBTOTAL, TOTAL, with_id],
        ["x", "Math mismatch", "1,250.00", "grand_total_not_verified_in_source"],
    )
    assert dismissed == [with_id, "Math mismatch", SUBTOTAL, TOTAL]
    assert (remaining, unmatched) == ([], [])


def test_the_same_dismissal_twice_removes_two_identical_alerts():
    assert dismiss_alerts([SUBTOTAL, SUBTOTAL], [SUBTOTAL, SUBTOTAL]) == ([], [SUBTOTAL, SUBTOTAL], [])


def test_dismissals_that_match_nothing_are_returned_unmatched():
    assert dismiss_alerts([SUBTOTAL], ["nope", {"type": "fake"}, 7]) == ([SUBTOTAL], [], ["nope", {"type": "fake"}, 7])


def test_a_message_only_object_can_dismiss_a_plain_text_alert():
    assert dismiss_alerts(["Math mismatch"], [{"message": "Math mismatch"}]) == ([], ["Math mismatch"], [])
