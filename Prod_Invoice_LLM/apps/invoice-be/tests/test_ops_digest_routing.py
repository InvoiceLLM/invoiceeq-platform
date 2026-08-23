"""Tests for services/ops_digest_routing.py (Feature 24, 2026-08-23)."""
from services.ops_digest_routing import classify


def test_azure_alert_critical_action_group_is_critical():
    assert classify({"source": "azure_alert", "action_group": "critical"}) == "critical"


def test_azure_alert_info_action_group_is_digest():
    assert classify({"source": "azure_alert", "action_group": "info"}) == "digest"


def test_ai_eval_audit_job_failure_is_always_critical():
    assert classify({"source": "ai_eval", "finding_type": "audit_job_failed"}) == "critical"


def test_ai_eval_sharp_quality_drop_is_critical():
    assert classify(
        {"source": "ai_eval", "finding_type": "quality_score_drop", "is_sharp_drop": True}
    ) == "critical"


def test_ai_eval_gradual_quality_drift_is_digest():
    assert classify(
        {"source": "ai_eval", "finding_type": "quality_score_drift", "is_sharp_drop": False}
    ) == "digest"


def test_ai_eval_drop_without_is_sharp_drop_flag_defaults_to_digest():
    # Missing flag is treated as "not confirmed sharp" -- default to the
    # quieter tier rather than assume urgency from an absent field.
    assert classify({"source": "ai_eval", "finding_type": "quality_score_drop"}) == "digest"


def test_ai_eval_unrecognized_finding_type_defaults_to_digest():
    assert classify({"source": "ai_eval", "finding_type": "something_new"}) == "digest"


def test_full_outage_exception_fires_when_replica_data_supplied():
    assert classify({"replica_count": 0, "expected_min_replicas": 1}) == "critical"


def test_full_outage_exception_does_not_fire_on_partial_restart():
    # 1 of 5 replicas down -- not a full outage.
    assert classify({"replica_count": 4, "expected_min_replicas": 5}) == "digest"


def test_full_outage_exception_absent_when_replica_data_not_supplied():
    # Honest limitation: no source computes this yet, so a signal with
    # neither field falls through to digest rather than crashing or
    # silently assuming "fine."
    assert classify({}) == "digest"


def test_unknown_source_falls_back_to_digest_not_dropped_or_paged():
    assert classify({"source": "something_unrecognized"}) == "digest"
