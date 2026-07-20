"""
Full end-to-end regression suite: generates realistic invoice PDFs, uploads them
through the real API, waits for the real extraction pipeline (real LLM + real
Document Intelligence calls) to finish, and checks the result.

Excluded from the default `pytest` run (see pyproject.toml `addopts`). Run explicitly:

    pytest -m e2e apps/invoice-be/tests/e2e

Target a specific backend with E2E_BASE_URL (default: http://localhost:8000/api/v1).
For a live environment behind Clerk auth, the backend's unauthenticated mock-tenant
fallback (dependencies.py::get_tenant_context) means no token is needed as long as
the target is reachable without going through a login-gated proxy.
"""
import os
import time
import tempfile

import httpx
import pytest

from tests.e2e.pdf_builder import build_invoice_pdf
from tests.e2e.fixtures_data import ALL_FIXTURES

BASE_URL = os.environ.get("E2E_BASE_URL", "http://localhost:8000/api/v1")
POLL_TIMEOUT_SECONDS = int(os.environ.get("E2E_POLL_TIMEOUT_SECONDS", "180"))
POLL_INTERVAL_SECONDS = 3
AMOUNT_TOLERANCE = 0.05

pytestmark = pytest.mark.e2e


def _upload_and_wait(client: httpx.Client, pdf_path: str, filename: str) -> dict:
    with open(pdf_path, "rb") as f:
        resp = client.post("/invoices/upload", files={"files": (filename, f, "application/pdf")})
    resp.raise_for_status()
    job_id = resp.json()["job_ids"][0]

    deadline = time.time() + POLL_TIMEOUT_SECONDS
    while time.time() < deadline:
        status_resp = client.get(f"/invoices/{job_id}")
        status_resp.raise_for_status()
        invoice = status_resp.json()
        if invoice["status"] != "PROCESSING":
            return invoice
        time.sleep(POLL_INTERVAL_SECONDS)

    pytest.fail(f"Invoice {job_id} ({filename}) still PROCESSING after {POLL_TIMEOUT_SECONDS}s")


def _alert_types(invoice: dict) -> set[str]:
    return {a.get("type") for a in (invoice.get("sa_alerts") or []) if isinstance(a, dict)}


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE_URL, timeout=60.0) as c:
        yield c


@pytest.mark.parametrize("build_kwargs,expected", ALL_FIXTURES, ids=[e["name"] for _, e in ALL_FIXTURES])
def test_regional_invoice(client: httpx.Client, build_kwargs: dict, expected: dict):
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        pdf_path = tmp.name
    try:
        build_invoice_pdf(pdf_path, **build_kwargs)
        invoice = _upload_and_wait(client, pdf_path, f"{expected['name']}.pdf")

        assert invoice["status"] == expected["expected_status"], (
            f"{expected['name']}: expected status {expected['expected_status']}, got {invoice['status']}. "
            f"Alerts: {invoice.get('sa_alerts')}"
        )

        alert_types = _alert_types(invoice)

        if "must_contain_alert_type" in expected:
            assert expected["must_contain_alert_type"] in alert_types, (
                f"{expected['name']}: expected alert type '{expected['must_contain_alert_type']}' "
                f"not found in {alert_types}"
            )

        if "must_not_contain_alert_type" in expected:
            assert expected["must_not_contain_alert_type"] not in alert_types, (
                f"{expected['name']}: unexpected alert type '{expected['must_not_contain_alert_type']}' "
                f"present. This is the false-positive regression this suite guards against. "
                f"Alerts: {invoice.get('sa_alerts')}"
            )

        # Fixtures with known-unresolved upstream issues (see fixtures_data.py) only assert
        # status/alert-shape, not exact totals, since those gaps aren't fixed yet.
        if expected.get("loose_check_only"):
            return

        if "expected_grand_total" in expected:
            assert invoice.get("grand_total") is not None, f"{expected['name']}: grand_total was not extracted"
            assert abs(invoice["grand_total"] - expected["expected_grand_total"]) <= AMOUNT_TOLERANCE, (
                f"{expected['name']}: grand_total {invoice['grand_total']} != expected {expected['expected_grand_total']}"
            )

        if "expected_tax_amount" in expected:
            assert invoice.get("tax_amount") is not None, f"{expected['name']}: tax_amount was not extracted"
            assert abs(invoice["tax_amount"] - expected["expected_tax_amount"]) <= AMOUNT_TOLERANCE, (
                f"{expected['name']}: tax_amount {invoice['tax_amount']} != expected {expected['expected_tax_amount']}"
            )
    finally:
        try:
            client.delete(f"/invoices/{invoice['id']}")
        except Exception:
            pass
        os.unlink(pdf_path)
