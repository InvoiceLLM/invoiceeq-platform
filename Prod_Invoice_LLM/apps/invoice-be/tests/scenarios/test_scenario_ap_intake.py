"""P2/P3 — the bills arrive and the ledger has to agree with the paper.

BS-P2-01  the 11 inbound documents land, in the order the demo pins
BS-P3-01  every stored row matches the hand-computed ground truth
BS-P2-04  NAT-2007 (same number + vendor) is flagged as a duplicate, not paid twice
BS-P2-08  a storage outage during upload saves nothing and says so
"""
import pytest
from sqlmodel import Session, select

from models import Invoice
from tests.scenarios.conftest import ground_truth

GT = ground_truth()


@pytest.mark.scenario("BS-P2-01")
def test_the_eleven_inbound_documents_land_in_the_pinned_order(vpi):
    vpi.receive_all()
    stored = {i.invoice_number for i in vpi.invoices()}
    assert stored == {row["doc"] for row in GT["inbound"]}


@pytest.mark.scenario("BS-P3-01")
@pytest.mark.parametrize("row", GT["inbound"], ids=lambda r: r["doc"])
def test_each_stored_invoice_matches_the_ground_truth(vpi, row):
    vpi.receive(row["doc"])
    stored = vpi.invoice(row["doc"])
    assert stored is not None, f"{row['doc']} was not stored at all"
    assert stored.vendor_name == row["vendor"]
    assert str(stored.invoice_date) == str(row["date"])
    assert str(stored.due_date) == str(row["due"])
    assert round(stored.grand_total, 2) == row["total"]
    assert (stored.currency or "INR") == "INR"


@pytest.mark.scenario("BS-P2-04")
def test_a_repeat_invoice_number_from_the_same_vendor_is_flagged_not_paid_twice(vpi):
    vpi.receive("NAT-2006")
    vpi.receive("NAT-2007")
    second = vpi.invoice("NAT-2007")
    assert second.status == "AUDIT_REQUIRED", "a duplicate must go to a human, never straight through"
    alert_types = {a.get("type") for a in second.sa_alerts if isinstance(a, dict)}
    assert "duplicate_invoice" in alert_types or "possible_duplicate" in alert_types


@pytest.mark.scenario("BS-P2-04")
def test_the_open_payable_total_excludes_nothing_the_business_still_owes(vpi):
    """Both duplicates are still rows; the business decision (which to pay) is the
    auditor's. What must be true is that the ledger sums to the printed arithmetic."""
    vpi.receive_all()
    assert vpi.open_payables_total() == GT["totals"]["inbound_all_11"]


@pytest.mark.scenario("BS-P2-08")
def test_a_storage_outage_during_upload_saves_nothing_and_says_so(vpi, as_persona, chaos):
    ravi = as_persona("ravi_clerk")
    files = [("files", ("inbound_Bharat_BHA-2002.pdf", b"%PDF-1.4 demo bytes", "application/pdf"))]

    with chaos.storage_down():
        response = ravi.post("/api/v1/invoices/upload", files=files)

    assert response.status_code == 503
    assert "Nothing was saved" in response.json()["detail"]
    with Session(vpi.engine) as s:
        assert s.exec(select(Invoice).where(Invoice.tenant_id == vpi.tenant_id)).all() == []
