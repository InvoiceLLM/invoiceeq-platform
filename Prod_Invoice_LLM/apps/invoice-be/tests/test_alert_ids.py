"""BE Gap 566: every alert is stored with its own id (utils/alert_ids.py)."""
import re
from pathlib import Path
from uuid import uuid4

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from models import Invoice
from services.invoice_reconciliation import mark_invoice_failed
from utils.alert_ids import with_alert_ids


def test_every_dict_alert_gets_an_id_and_an_existing_id_is_kept():
    alerts = with_alert_ids([
        {"type": "tax_mismatch", "field": "tax_amount", "message": "m"},
        {"type": "duplicate_invoice", "message": "n", "id": "keep-me"},
        "Math mismatch",
    ])
    assert re.fullmatch(r"[0-9a-f]{32}", alerts[0]["id"])
    assert alerts[1]["id"] == "keep-me"
    assert alerts[2] == "Math mismatch"


def test_two_identical_alerts_get_different_ids_and_the_input_is_not_modified():
    same = {"type": "line_item_calculation_mismatch", "field": "items", "message": "m"}
    original = [same, same]
    first, second = with_alert_ids(original)
    assert first["id"] != second["id"]
    assert "id" not in same
    assert with_alert_ids(None) == []


def test_a_failed_invoice_keeps_its_alert_ids_and_the_failure_alert_gets_one():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        invoice = Invoice(
            id=uuid4(), tenant_id=uuid4(), file_path="mock/invoice.pdf", status="EXTRACTING_DATA",
            sa_alerts=[{"id": "a1", "type": "tax_mismatch", "message": "m"}],
        )
        session.add(invoice)
        session.commit()

        mark_invoice_failed(session, invoice, "processing gave up")

        session.refresh(invoice)
        assert invoice.sa_alerts[0]["id"] == "a1"
        assert invoice.sa_alerts[1]["type"] == "processing_failed"
        assert re.fullmatch(r"[0-9a-f]{32}", invoice.sa_alerts[1]["id"])


# Places that assign `sa_alerts` without storing newly produced alerts, each with its reason.
_NOT_NEW_ALERTS = {
    # The resolve keeps the stored alerts minus the dismissed ones; alerts raised by a correction
    # already carry ids (utils/correction_recheck.py).
    ("routers/audit.py", "new_alerts"),
    ("routers/outbound_audit.py", "new_alerts"),
    # A response model built from a stored row.
    ("routers/documents.py", "list(row.sa_alerts or [])"),
}
_ALERT_ASSIGNMENT = re.compile(r"\bsa_alerts\s*=(?!=)\s*(?P<value>[^\n]+)")


def test_every_place_that_stores_alerts_gives_them_ids():
    """A new storage point that forgets `with_alert_ids` fails here, instead of silently storing id-less alerts."""
    root = Path(__file__).resolve().parents[1]
    offenders = []
    for folder in ("agents", "queue_worker", "routers", "services", "utils"):
        for path in sorted((root / folder).rglob("*.py")):
            relative = path.relative_to(root).as_posix()
            for match in _ALERT_ASSIGNMENT.finditer(path.read_text(encoding="utf-8")):
                value = match.group("value").split("#")[0].strip().rstrip(",").strip()
                if value.startswith("with_alert_ids(") or (relative, value) in _NOT_NEW_ALERTS:
                    continue
                offenders.append(f"{relative}: sa_alerts = {value}")
    assert offenders == []
