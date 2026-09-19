"""
Unit tests for BE Gap 688: Extraction quality sweep script.
Pure mock unit tests — DB-free, network-free.
"""
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

from scripts.sweep_extraction_quality import sweep_tenant_quality, main


def test_gap688_sweep_tenant_quality_critical_field_alert():
    """Verify sweep_tenant_quality alerts when a critical field exceeds the 15% correction threshold."""
    tenant_id = uuid4()
    mock_session = MagicMock()
    since = datetime.utcnow() - timedelta(days=7)

    field_data = [
        {"field": "grand_total", "correction_count": 4, "total_resolves": 10, "correction_rate": 0.40},
        {"field": "tax_amount", "correction_count": 0, "total_resolves": 10, "correction_rate": 0.0},
    ]
    alert_data = [
        {"alert_type": "tax_mismatch", "confirmed_count": 8, "total_reviewed": 10, "precision": 0.80},
    ]

    with patch("scripts.sweep_extraction_quality.field_correction_rollup", return_value=field_data), \
         patch("scripts.sweep_extraction_quality.alert_precision_rollup", return_value=alert_data), \
         patch("scripts.sweep_extraction_quality.track_extraction_quality_rollup") as mock_track:

        res = sweep_tenant_quality(
            mock_session,
            tenant_id,
            since=since,
            dry_run=False,
            alert_threshold=0.15,
        )

        assert res["tenant_id"] == str(tenant_id)
        assert len(res["high_correction_alerts"]) == 1
        assert "grand_total" in res["high_correction_alerts"][0]
        assert "40.0%" in res["high_correction_alerts"][0]

        # Verify telemetry was emitted for both fields
        assert mock_track.call_count == 2
        mock_track.assert_any_call(
            tenant_id=str(tenant_id),
            field="grand_total",
            correction_count=4,
            total_resolves=10,
            correction_rate=0.40,
        )
        mock_track.assert_any_call(
            tenant_id=str(tenant_id),
            field="tax_amount",
            correction_count=0,
            total_resolves=10,
            correction_rate=0.0,
        )


def test_gap688_sweep_tenant_quality_dry_run_suppresses_telemetry():
    """Verify dry_run=True does not call track_extraction_quality_rollup."""
    tenant_id = uuid4()
    mock_session = MagicMock()
    since = datetime.utcnow() - timedelta(days=7)

    field_data = [
        {"field": "grand_total", "correction_count": 2, "total_resolves": 10, "correction_rate": 0.20},
    ]

    with patch("scripts.sweep_extraction_quality.field_correction_rollup", return_value=field_data), \
         patch("scripts.sweep_extraction_quality.alert_precision_rollup", return_value=[]), \
         patch("scripts.sweep_extraction_quality.track_extraction_quality_rollup") as mock_track:

        res = sweep_tenant_quality(
            mock_session,
            tenant_id,
            since=since,
            dry_run=True,
            alert_threshold=0.15,
        )

        assert len(res["high_correction_alerts"]) == 1
        mock_track.assert_not_called()


def test_gap688_main_cli_execution():
    """Verify CLI main() parses arguments and sweeps discovered tenants."""
    tenant_id = uuid4()
    mock_session = MagicMock()
    mock_session.exec.return_value.all.return_value = [tenant_id]

    with patch("scripts.sweep_extraction_quality.Session") as mock_session_cls, \
         patch("scripts.sweep_extraction_quality.sweep_tenant_quality") as mock_sweep, \
         patch("sys.argv", ["sweep_extraction_quality.py", "--days", "14"]):

        mock_session_cls.return_value.__enter__.return_value = mock_session
        mock_sweep.return_value = {"high_correction_alerts": []}

        exit_code = main()
        assert exit_code == 0
        mock_sweep.assert_called_once()
        assert mock_sweep.call_args[0][1] == tenant_id


# --- Postgres: the real rollups over real AuditLog rows (review 2026-09-17) ---------
from sqlmodel import Session  # noqa: E402

from models import AuditLog  # noqa: E402
from tests.pg_gap_fixtures import pg_engine, pg_only  # noqa: E402,F401  (pytest fixture)


def _resolve(session, tenant_id, when, corrected_fields=()):
    session.add(AuditLog(
        tenant_id=tenant_id, invoice_id=uuid4(), actor_role="Admin", action="RESOLVE_INVOICE", timestamp=when,
        details={"corrections": {f: {"old": "a", "new": "b"} for f in corrected_fields}},
    ))


@pg_only
def test_gap688_sweep_on_postgres_uses_the_window_and_the_tenant(pg_engine):
    tenant, other = uuid4(), uuid4()
    now = datetime.utcnow()
    with Session(pg_engine) as session:
        for i in range(10):
            _resolve(session, tenant, now - timedelta(days=1), ["grand_total"] if i < 4 else [])
        _resolve(session, tenant, now - timedelta(days=30), ["grand_total"])  # outside the 7-day window
        _resolve(session, other, now - timedelta(days=1), ["grand_total"])  # another tenant
        session.commit()

        with patch("scripts.sweep_extraction_quality.track_extraction_quality_rollup") as track:
            res = sweep_tenant_quality(session, tenant, since=now - timedelta(days=7), alert_threshold=0.15)

    grand_total = next(r for r in res["field_rollups"] if r["field"] == "grand_total")
    assert (grand_total["correction_count"], grand_total["total_resolves"]) == (4, 10)
    assert len(res["high_correction_alerts"]) == 1
    track.assert_called_once_with(tenant_id=str(tenant), field="grand_total",
                                  correction_count=4, total_resolves=10, correction_rate=0.4)


@pg_only
def test_gap688_main_discovers_tenants_with_recent_audit_activity(pg_engine):
    recent, stale = uuid4(), uuid4()
    now = datetime.utcnow()
    with Session(pg_engine) as session:
        _resolve(session, recent, now - timedelta(days=2), ["vendor_name"])
        _resolve(session, stale, now - timedelta(days=40), ["vendor_name"])
        session.commit()

    with patch("scripts.sweep_extraction_quality.engine", pg_engine), \
         patch("scripts.sweep_extraction_quality.sweep_tenant_quality", return_value={"high_correction_alerts": []}) as sweep, \
         patch("sys.argv", ["sweep_extraction_quality.py", "--days", "7", "--dry-run"]):
        assert main() == 0

    assert [c.args[1] for c in sweep.call_args_list] == [recent]
