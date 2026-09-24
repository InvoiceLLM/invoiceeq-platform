"""Business-scenario harness (see D:\\testllm\\BUSINESS_SCENARIO_TEST_PLAN.md).

One VPI tenant, real Postgres, the real handlers and routers — with exactly two seams:

  * **OCR** is replaced by text rendered from the ground-truth file, so a run is
    deterministic and costs nothing.
  * **Extraction** is replaced by the ground-truth record in the default (mock) mode.
    With `SCENARIO_REAL_AI=1` the real agent runs instead and extraction accuracy is
    what is being graded.

Everything else is the product: persistence, duplicate detection, alerts, statuses,
permissions, webhooks, sweeps.

Scope of each mode, stated so a green run is not over-read:
  * mock mode  -> the business plumbing is correct (what the ledger, alerts and
                  screens do with a known extraction).
  * real mode  -> the extraction itself is correct (Level 6 of the plan).

Postgres only (CONVENTIONS hard rule 2): `TEST_DATABASE_URL` must name a throwaway
database whose name contains "test", on localhost. Without it every scenario skips.
"""
from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlmodel import Session, select

# This conftest lives one level deeper than the other suites, so pytest puts
# `tests/scenarios` on sys.path rather than the app root. Put the app root back so
# `tests.*` and the application packages import the same way everywhere else does.
_APP_ROOT = str(Path(__file__).resolve().parents[2])
if _APP_ROOT not in sys.path:
    sys.path.insert(0, _APP_ROOT)

from dependencies import (
    TenantContext,
    get_db_session,
    get_tenant_context,
    get_tenant_or_api_key_context,
)
from main import app
from models import Invoice, Tenant


def make_pg_engine():
    """A throwaway-database engine, with the Gap 525 guard repeated locally.

    The scenario suite deliberately does not import `tests/pg_gap_fixtures.py`: that
    helper only exists on the extraction branch, and these scenarios must run on any
    branch. The guard itself is the part that matters and is reproduced verbatim —
    the fixtures below drop every table, so a non-throwaway URL must be impossible.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url

    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("needs TEST_DATABASE_URL (Postgres) -- CONVENTIONS hard rule 2")
    parsed = make_url(url)
    if parsed.host not in ("localhost", "127.0.0.1"):
        pytest.fail(f"TEST_DATABASE_URL must be local, got host {parsed.host!r}")
    if "test" not in (parsed.database or ""):
        pytest.fail(f"TEST_DATABASE_URL database must be a throwaway whose name contains 'test', got {parsed.database!r}")
    return create_engine(url, pool_pre_ping=True)

GROUND_TRUTH_PATH = Path(__file__).parent / "ground_truth" / "vpi.yaml"
REAL_AI = os.getenv("SCENARIO_REAL_AI") == "1"


# ---------------------------------------------------------------------------
# Ground truth
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def gt() -> dict:
    """The hand-computed VPI figures. Read-only: a test never writes back to this."""
    return yaml.safe_load(GROUND_TRUTH_PATH.read_text(encoding="utf-8"))


def ground_truth() -> dict:
    """Module-level access for `@pytest.mark.parametrize` (fixtures cannot be used there)."""
    return yaml.safe_load(GROUND_TRUTH_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# The tenant and the people in it
# ---------------------------------------------------------------------------
@dataclass
class Persona:
    name: str
    role: str
    clearance: str = "ops"
    can_load: bool = False
    can_audit: bool = False
    can_train: bool = False


PERSONAS = {
    "priya_admin": Persona("Priya (Owner/Admin)", "Admin", clearance="exec", can_load=True, can_audit=True, can_train=True),
    "ravi_clerk": Persona("Ravi (Accounts clerk)", "Clerk", can_load=True),
    "anita_auditor": Persona("Anita (Auditor)", "Auditor", can_audit=True),
    "sanjay_trainer": Persona("Sanjay (Trainer)", "Trainer", can_train=True),
    "nobody": Persona("Invited, ungranted", "NO_ROLE"),
}


@dataclass
class VPI:
    """The VPI world: one tenant, its ledger, and the actions people take on it."""

    engine: object
    tenant_id: UUID
    gt: dict
    _by_doc: dict = field(default_factory=dict)

    # ---- reading -----------------------------------------------------------
    def invoice(self, doc: str) -> Invoice | None:
        with Session(self.engine) as s:
            return s.exec(select(Invoice).where(Invoice.tenant_id == self.tenant_id, Invoice.invoice_number == doc)).first()

    def invoices(self) -> list[Invoice]:
        with Session(self.engine) as s:
            return list(s.exec(select(Invoice).where(Invoice.tenant_id == self.tenant_id)).all())

    def open_payables_total(self) -> float:
        return round(sum(i.grand_total or 0 for i in self.invoices()
                         if i.status not in ("PAID", "REJECTED", "DUPLICATE", "FAILED")), 2)

    # ---- acting ------------------------------------------------------------
    def receive(self, doc: str) -> Invoice | None:
        """One inbound document goes through the real worker handler.

        The placeholder row is what the upload door writes; `handle_process_invoice`
        then does OCR -> extraction -> verification -> persistence, with the two seams
        described in the module docstring.
        """
        row = next(r for r in self.gt["inbound"] if r["doc"] == doc)
        file_path = f"tenants/{self.tenant_id}/invoices/{uuid4()}.pdf"
        with Session(self.engine) as s:
            s.add(Invoice(id=uuid4(), tenant_id=self.tenant_id, file_path=file_path, status="PROCESSING"))
            s.commit()

        from queue_worker.handlers import handle_process_invoice

        ocr_text = _render_ocr(row)
        agent_result = _ground_truth_extraction(row)
        patches = [
            patch("queue_worker.handlers.engine", self.engine),
            patch("queue_worker.handlers._publish_sse_events"),
            patch("queue_worker.handlers._run_ocr", return_value=ocr_text),
            patch("chroma_client.index_invoice_document"),
        ]
        if not REAL_AI:
            patches.append(patch("queue_worker.handlers.run_extraction_agent", return_value=agent_result))
        with _all(patches):
            handle_process_invoice(str(uuid4()), file_path, str(self.tenant_id))

        self._by_doc[doc] = file_path
        return self.invoice(doc)

    def receive_all(self, docs: list[str] | None = None) -> None:
        for doc in docs or self.gt["upload_order_inbound"]:
            self.receive(doc)


def _render_ocr(row: dict) -> str:
    """The document as text, from the ground truth — the same shape the benchmark renders."""
    subtotal = round(row["total"] / 1.18, 2)
    tax = round((row["total"] - subtotal) / 2, 2)
    return (
        f"TAX INVOICE\n{row['vendor']}\nInvoice No: {row['doc']}\n"
        f"Invoice Date: {row['date']}\nDue Date: {row['due']}\n"
        f"Subtotal {subtotal:.2f}\nCGST 9% {tax:.2f}\nSGST 9% {tax:.2f}\n"
        f"Total {row['total']:.2f}\n"
    )


def _ground_truth_extraction(row: dict) -> dict:
    subtotal = round(row["total"] / 1.18, 2)
    tax = round((row["total"] - subtotal) / 2, 2)
    return {
        "status": "COMPLETED",
        "alerts": [],
        "extracted_data": {
            "vendor_name": row["vendor"],
            "invoice_number": row["doc"],
            "invoice_date": str(row["date"]),
            "due_date": str(row["due"]),
            "subtotal": subtotal,
            "tax_amount": round(tax * 2, 2),
            "grand_total": row["total"],
            "currency": "INR",
            "items": [],
        },
    }


@contextmanager
def _all(patches):
    started = [p.start() for p in patches]
    try:
        yield started
    finally:
        for p in reversed(patches):
            p.stop()


@pytest.fixture
def vpi(gt):
    """A fresh VPI tenant on real Postgres, empty ledger."""
    if not os.getenv("TEST_DATABASE_URL"):
        pytest.skip("needs TEST_DATABASE_URL (Postgres) -- CONVENTIONS hard rule 2")
    from sqlmodel import SQLModel

    engine = make_pg_engine()
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
    tenant_id = uuid4()
    with Session(engine) as s:
        s.add(Tenant(id=tenant_id, name=gt["tenant"]["name"], domain=f"vpi-{tenant_id.hex[:8]}.test",
                     billing_plan="pro", send_invoices_enabled=True))
        s.commit()
    world = VPI(engine=engine, tenant_id=tenant_id, gt=gt)
    yield world
    SQLModel.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def as_persona(vpi):
    """`as_persona("anita_auditor")` -> a TestClient acting as that person."""
    clients = []

    def _make(key: str) -> TestClient:
        p = PERSONAS[key]

        def _tenant_override():
            return TenantContext(
                tenant_id=vpi.tenant_id, user_id=key, role=p.role, billing_plan="pro",
                can_load=p.can_load, can_audit=p.can_audit, can_train=p.can_train,
                clearance=p.clearance,
            )

        def _session_override():
            with Session(vpi.engine) as s:
                yield s

        # Both context providers must be overridden. `get_tenant_or_api_key_context`
        # calls `get_tenant_context` as a plain function, not through Depends, so
        # overriding only the latter leaves every dual-credential route (the invoice
        # list among them) running the real dependency — which, with no credential
        # and ALLOW_MOCK_AUTH on, falls back to a mock ADMIN. A permission test that
        # silently runs as admin proves nothing.
        app.dependency_overrides[get_tenant_context] = _tenant_override
        app.dependency_overrides[get_tenant_or_api_key_context] = _tenant_override
        app.dependency_overrides[get_db_session] = _session_override
        client = TestClient(app)
        clients.append(client)
        return client

    yield _make
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Adverse events (the DOWN half of every scenario)
# ---------------------------------------------------------------------------
class Chaos:
    """Failure injection, one context manager per real-world outage."""

    @contextmanager
    def storage_down(self):
        try:
            from services.storage import StorageUploadError
        except ImportError:  # pragma: no cover - branch guard, not a code path
            pytest.skip(
                "services.storage.StorageUploadError does not exist on this checkout -- "
                "the fail-fast upload path is BE Gap 673, which lives on "
                "be-gaps-670-688-extraction-production-readiness. Run this scenario there."
            )

        with patch("services.storage.upload_pdf_to_blob_storage", side_effect=StorageUploadError("Azure Blob unavailable")), \
             patch("routers.invoices.upload_pdf_to_blob_storage", side_effect=StorageUploadError("Azure Blob unavailable")):
            yield

    @contextmanager
    def document_intelligence_down(self):
        with patch("queue_worker.handlers._run_ocr", side_effect=TimeoutError("Document Intelligence timed out")):
            yield

    @contextmanager
    def document_intelligence_returns_no_fields(self):
        with patch("queue_worker.handlers._run_ocr", return_value={"content": "unreadable scan", "coordinates": [],
                                                                   "field_confidence": {}, "source_document_json": None,
                                                                   "vendor_name": None}):
            yield

    @contextmanager
    def llm_down(self):
        with patch("queue_worker.handlers.run_extraction_agent", side_effect=RuntimeError("model unavailable")):
            yield

    @contextmanager
    def queue_unavailable(self):
        with patch("queue_worker.handlers._enqueue_process_invoice", return_value=False):
            yield

    @contextmanager
    def webhook_subscriber_down(self):
        with patch("services.webhooks.dispatch_webhook_event", side_effect=RuntimeError("subscriber 500")):
            yield

    @contextmanager
    def email_provider_down(self):
        with patch("services.staff_notify.notify_processing_complete", side_effect=RuntimeError("SendGrid unavailable")):
            yield

    @contextmanager
    def indexing_down(self):
        with patch("chroma_client.index_invoice_document", side_effect=RuntimeError("Chroma unreachable")):
            yield


@pytest.fixture
def chaos() -> Chaos:
    return Chaos()


# ---------------------------------------------------------------------------
# Scenario report: which BS-* ids ran, and how they ended
# ---------------------------------------------------------------------------
_RESULTS: dict[str, str] = {}


def pytest_runtest_makereport(item, call):
    if call.when != "call":
        return
    marker = item.get_closest_marker("scenario")
    if not marker:
        return
    for scenario_id in marker.args:
        outcome = "passed" if call.excinfo is None else ("skipped" if call.excinfo.errisinstance(pytest.skip.Exception) else "FAILED")
        # a failure anywhere in a parametrized scenario fails the scenario
        if _RESULTS.get(scenario_id) != "FAILED":
            _RESULTS[scenario_id] = outcome


def pytest_sessionfinish(session, exitstatus):
    if not _RESULTS:
        return
    out = Path(__file__).parent / "scenario_report.md"
    lines = [
        "# Business scenario run",
        "",
        f"- when: {datetime.utcnow().isoformat(timespec='seconds')}Z",
        f"- mode: {'REAL AI' if REAL_AI else 'mock extraction (business plumbing)'}",
        f"- database: {'Postgres' if os.getenv('TEST_DATABASE_URL') else 'NOT SET -> scenarios skipped'}",
        "",
        "| scenario | result |",
        "|---|---|",
    ]
    lines += [f"| {sid} | {result} |" for sid, result in sorted(_RESULTS.items())]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
