"""Feature 17 — Invoice Builder (Clone & Edit).

Two halves:

* Pure units — `services/invoice_builder.py`, `services/pdf_render.py`,
  `utils/verification_tools.verify_builder_readback` — run against the
  committed fixtures in `tests/fixtures/invoice_builder/` (four source PDFs
  plus the `Invoice.coordinates` Document Intelligence would have stored for
  each). No Azure call, no database.

BE Gap 462 (2026-09-05) deleted `services/pdf_substitute.py` and every test
that exercised it, along with the `date_twice` fixture, which existed only to
prove substitution could disambiguate a date printed twice. There is one
renderer now, so there is no render-mode planning to test and no 422 to assert.
* The three endpoints and the worker hook, against **real Postgres**
  (CONVENTIONS hard rule 2). The quota path under test here goes through
  `SELECT … FOR UPDATE` in `services/billing_quota.charge_free_quota()`, which
  SQLite does not implement — a SQLite run would exercise a different code path
  and prove nothing about the one that ships.

Test-tenant hazard (documented in `feature_28_image_upload_pdf_boundary.md` §6):
mock auth resolves through the `user_test_default` User row bound to whichever
tenant a seeding script created, NOT `MOCK_TENANT_ID`. This file therefore
creates its own tenant and overrides the auth dependencies, so the assertions
read the same rows the router wrote.
"""
import io
import json
import pathlib
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import fitz
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

from config import get_settings
from dependencies import (
    TenantContext,
    get_db_session,
    get_tenant_context,
    require_can_load,
    require_can_send_invoices,
)
from main import app
from models import Invoice, Tenant
from services.invoice_builder import (
    BuildDeduction,
    BuildDiscount,
    BuildItem,
    BuildRequest,
    BuildTax,
    builder_intent,
    compute_totals,
    default_build_from_source,
    next_invoice_number,
    totals_for,
)
from services.pdf_render import format_like, harvest_branding, render_invoice
from utils.verification_tools import verify_builder_readback

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "invoice_builder"

#: A tenant of this file's own — never `dependencies.MOCK_TENANT_ID`.
TEST_TENANT_ID = uuid4()

client = TestClient(app)


# ── Fixture loading ──────────────────────────────────────────────────────────

def _sidecar(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _pdf(name: str) -> bytes:
    return (FIXTURES / f"{name}.pdf").read_bytes()


def _source_row(name: str, **overrides) -> SimpleNamespace:
    """The `Invoice` row a real extraction of this fixture would have written,
    as a plain object — the pure functions never touch the ORM."""
    data = _sidecar(name)
    row = SimpleNamespace(
        id=overrides.pop("id", uuid4()),
        customer_name=data["customer_name"],
        invoice_number=data["invoice_number"],
        invoice_date=date.fromisoformat(data["invoice_date"]),
        due_date=date.fromisoformat(data["due_date"]),
        currency=data["currency"],
        subtotal=data["subtotal"],
        tax_amount=data["tax_amount"],
        grand_total=data["grand_total"],
        items=data["items"],
        coordinates=data["coordinates"],
    )
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


# ═════════════════════════════════════════════════════════════════════════════
# 17.1 — the pure core
# ═════════════════════════════════════════════════════════════════════════════

def test_compute_totals_rounds_half_up_per_line():
    """The spec's own case: 3 × 19.99 and 1 × 0.005. Banker's rounding (what
    Python's `round()` does) would make the second line 0.00."""
    totals = compute_totals(
        [
            BuildItem(description="a", quantity=Decimal("3"), unit_price=Decimal("19.99")),
            BuildItem(description="b", quantity=Decimal("1"), unit_price=Decimal("0.005")),
        ],
        None,
    )
    assert totals.line_amounts == [Decimal("59.97"), Decimal("0.01")]
    assert totals.subtotal == Decimal("59.98")
    assert totals.grand_total == Decimal("59.98")


def test_compute_totals_adds_tax_to_subtotal():
    totals = compute_totals(
        [BuildItem(description="a", quantity=Decimal("2"), unit_price=Decimal("100"))],
        Decimal("40"),
    )
    assert (totals.subtotal, totals.tax_amount, totals.grand_total) == (
        Decimal("200.00"), Decimal("40.00"), Decimal("240.00"),
    )


def test_compute_totals_tolerates_a_half_typed_row():
    totals = compute_totals([BuildItem(description="", quantity=None, unit_price=None)], None)
    assert totals.line_amounts == [Decimal("0.00")]


@pytest.mark.parametrize(
    "source,expected",
    [
        ("INV-0099", "INV-0100"),
        ("INV-0042", "INV-0043"),
        ("2026/07", "2026/08"),
        ("ACME", None),
        (None, None),
        ("INV-0042-A", "INV-0043-A"),
    ],
)
def test_next_invoice_number(source, expected):
    assert next_invoice_number(source) == expected


def test_default_build_from_source_rolls_the_due_date_by_the_payment_term():
    source = _source_row("us_style")  # 2026-07-15 → 2026-08-14, a 30-day term
    today = date(2026, 9, 1)
    defaults = default_build_from_source(source, today)

    assert defaults.invoice_number == "INV-0043"
    assert defaults.invoice_date == today
    assert defaults.due_date == today + timedelta(days=30)
    assert defaults.customer_name == "Northwind Traders"
    assert defaults.currency == "USD"
    assert [i.description for i in defaults.items] == [i["description"] for i in source.items]


def test_default_build_from_source_leaves_due_date_none_without_a_term():
    source = _source_row("us_style", due_date=None)
    assert default_build_from_source(source, date(2026, 9, 1)).due_date is None


# ═════════════════════════════════════════════════════════════════════════════
# 17.2 — number formatting (the surviving half of the deleted substitute path)
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize(
    "sample,value,expected",
    [
        ("1.250,00", Decimal("2000"), "2.000,00"),
        ("1,250.00", Decimal("2000"), "2,000.00"),
        ("1250.00", Decimal("2000"), "2000.00"),
        ("1250", Decimal("2000"), "2000"),
        ("$1,250.00", Decimal("2000.5"), "$2,000.50"),
        ("5", Decimal("6"), "6"),
    ],
)
def test_format_like(sample, value, expected):
    assert format_like(sample, value) == expected


# ═════════════════════════════════════════════════════════════════════════════
# 17.2b — branding harvest and structured re-render
# ═════════════════════════════════════════════════════════════════════════════

def test_harvest_branding_finds_the_raster_logo():
    branding = harvest_branding(_pdf("raster_logo"))
    assert branding.logo_bytes is not None
    assert branding.logo_pixels == (240, 80)
    assert branding.page_size[0] == pytest.approx(595.27, abs=0.5)  # A4


def test_harvest_branding_on_a_vector_only_source_returns_no_logo_and_does_not_raise():
    branding = harvest_branding(_pdf("vector_text_only"))
    assert branding.logo_bytes is None
    assert branding.header_lines  # the letterhead text is still harvested


def test_harvest_branding_drops_the_sources_own_invoice_metadata():
    """Otherwise the re-rendered PDF prints last month's invoice number in the
    letterhead, above the new one."""
    branding = harvest_branding(_pdf("us_style"), exclude_texts=["Northwind Traders"])
    joined = " ".join(branding.header_lines)
    assert "INV-0042" not in joined
    assert "2026-07-15" not in joined
    assert "Northwind Traders" not in joined
    assert "ACME Engineering Ltd" in joined


def test_render_invoice_paginates_a_40_row_request_with_the_totals_on_the_last_page():
    source = _source_row("eu_style")
    branding = harvest_branding(_pdf("eu_style"))
    req = BuildRequest(
        source_invoice_id=source.id,
        customer_name="Blaue See GmbH",
        invoice_number="RE-2026-0118",
        invoice_date=date(2026, 9, 1),
        due_date=date(2026, 10, 1),
        currency="EUR",
        items=[
            BuildItem(description=f"Position {i}", quantity=Decimal("2"), unit_price=Decimal("123.45"))
            for i in range(40)
        ],
        tax_amount=Decimal("100"),
    )
    totals = compute_totals(req.items, req.tax_amount)

    pdf_bytes = render_invoice(req, totals, branding, "1.904,00")
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        assert doc.page_count == 2
        last = doc[-1].get_text()
        whole = "".join(page.get_text() for page in doc)

    # Totals block is on the last page, in the source's separator style.
    assert "9.876,00" in last            # subtotal  40 × 246.90
    assert "9.976,00" in last            # grand total
    assert "Total Due (EUR)" in last
    # Every description and every line amount re-extracts.
    for i in range(40):
        assert f"Position {i}" in whole
    assert whole.count("246,90") == 40


def test_render_invoice_places_the_harvested_logo():
    source = _source_row("raster_logo")
    branding = harvest_branding(_pdf("raster_logo"))
    req = default_build_from_source(source, date(2026, 9, 1))
    req.items.append(BuildItem(description="Extra", quantity=Decimal("1"), unit_price=Decimal("10")))
    totals = compute_totals(req.items, req.tax_amount)

    pdf_bytes = render_invoice(req, totals, branding, "1,800.00")
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        assert doc[0].get_images()
        assert "Extra" in doc[0].get_text()


# ═════════════════════════════════════════════════════════════════════════════
# 17.6 — read-back check
# ═════════════════════════════════════════════════════════════════════════════

def _intent_for(source_name: str = "us_style") -> dict:
    source = _source_row(source_name)
    req = default_build_from_source(source, date(2026, 9, 1))
    totals = compute_totals(req.items, req.tax_amount)
    return builder_intent(req, totals)


def _extracted_from(intent: dict, **overrides) -> dict:
    totals = intent["totals"]
    extracted = {
        "customer_name": intent["customer_name"],
        "invoice_number": intent["invoice_number"],
        "invoice_date": intent["invoice_date"],
        "due_date": intent["due_date"],
        "subtotal": float(totals["subtotal"]),
        "tax_amount": float(totals["tax_amount"]),
        "grand_total": float(totals["grand_total"]),
        "items": [{"amount": float(a)} for a in totals["line_amounts"]],
    }
    extracted.update(overrides)
    return extracted


def test_verify_builder_readback_passes_on_an_exact_read_back():
    intent = _intent_for()
    assert verify_builder_readback(intent, _extracted_from(intent)) == []


def test_verify_builder_readback_ignores_whitespace_and_a_timestamped_date():
    intent = _intent_for()
    extracted = _extracted_from(
        intent,
        customer_name="  northwind   traders ",
        invoice_date=intent["invoice_date"] + "T00:00:00",
    )
    assert verify_builder_readback(intent, extracted) == []


def test_verify_builder_readback_catches_a_two_cent_grand_total_drift():
    intent = _intent_for()
    drifted = float(intent["totals"]["grand_total"]) + 0.02
    mismatches = verify_builder_readback(intent, _extracted_from(intent, grand_total=drifted))
    assert [m["field"] for m in mismatches] == ["grand_total"]


def test_verify_builder_readback_catches_a_wrong_line_amount_and_a_lost_line():
    intent = _intent_for()
    bad_line = _extracted_from(intent)
    bad_line["items"][0]["amount"] = float(intent["totals"]["line_amounts"][0]) + 5
    assert [m["field"] for m in verify_builder_readback(intent, bad_line)] == ["items[0].amount"]

    lost_line = _extracted_from(intent)
    lost_line["items"] = lost_line["items"][:1]
    assert [m["field"] for m in verify_builder_readback(intent, lost_line)] == ["items"]


def test_verify_builder_readback_is_inert_without_an_intent():
    assert verify_builder_readback(None, {"grand_total": 1.0}) == []


# ═════════════════════════════════════════════════════════════════════════════
# Postgres — the endpoints
# ═════════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def pg_engine():
    psycopg2 = pytest.importorskip("psycopg2")
    url = get_settings().DATABASE_URL
    if not url.startswith("postgresql"):
        pytest.skip("DATABASE_URL is not PostgreSQL — see .claude/skills/verify-postgres")
    try:
        psycopg2.connect(url).close()
    except psycopg2.OperationalError as exc:
        pytest.skip(f"local Postgres not reachable: {exc}")

    engine = create_engine(url)
    SQLModel.metadata.create_all(engine)
    return engine


def _purge(session: Session) -> None:
    rows = session.exec(select(Invoice).where(Invoice.tenant_id == TEST_TENANT_ID)).all()
    for row in rows:
        # Both self-referencing FKs have to be broken before the batch delete,
        # or the clone's pointer at its source blocks the source's DELETE.
        if row.duplicate_of_invoice_id is not None or row.source_invoice_id is not None:
            row.duplicate_of_invoice_id = None
            row.source_invoice_id = None
            session.add(row)
    session.commit()
    for row in session.exec(select(Invoice).where(Invoice.tenant_id == TEST_TENANT_ID)).all():
        session.delete(row)
    session.commit()


@pytest.fixture
def db_session(pg_engine):
    with Session(pg_engine) as session:
        _purge(session)
        stale = session.get(Tenant, TEST_TENANT_ID)
        if stale:
            session.delete(stale)
            session.commit()
        session.add(
            Tenant(
                id=TEST_TENANT_ID,
                name="F17 Invoice Builder",
                domain=f"f17-{TEST_TENANT_ID.hex[:12]}.example.com",
                billing_plan="free",
                free_invoices_remaining=50,
                send_invoices_enabled=True,
            )
        )
        session.commit()
        try:
            yield session
        finally:
            session.rollback()
            _purge(session)
            tenant = session.get(Tenant, TEST_TENANT_ID)
            if tenant:
                session.delete(tenant)
            session.commit()


@pytest.fixture(autouse=True)
def override_auth(db_session):
    context = TenantContext(
        tenant_id=TEST_TENANT_ID,
        user_id="f17-test-user",
        role="Admin",
        billing_plan="free",
    )

    def _session_override():
        yield db_session

    app.dependency_overrides[get_db_session] = _session_override
    # `get_tenant_context` is overridden as well as the two permission gates:
    # `routers/outbound_dashboard.py::list_outbound_invoices` depends on the
    # bare context, and without this the lineage assertion below reads whatever
    # tenant the mock-auth `user_test_default` row happens to point at rather
    # than this file's own (feature_28 §6's test-tenant hazard).
    for dependency in (require_can_load, require_can_send_invoices, get_tenant_context):
        app.dependency_overrides[dependency] = lambda: context
    yield
    app.dependency_overrides.clear()


def _seed_source(
    db_session: Session,
    name: str = "us_style",
    status: str = "VERIFIED",
    tenant_id: UUID | None = None,
    columns: dict | None = None,
) -> Invoice:
    """A source invoice whose `file_path` points straight at the fixture PDF on
    disk — `download_pdf_from_storage()` reads a local path unchanged, so the
    builder gets a real source document with no blob storage in the loop."""
    data = _sidecar(name)
    invoice = Invoice(
        tenant_id=tenant_id or TEST_TENANT_ID,
        batch_id=uuid4(),
        file_path=str(FIXTURES / f"{name}.pdf"),
        flow_direction="OUTBOUND",
        status=status,
        customer_name=data["customer_name"],
        invoice_number=data["invoice_number"],
        invoice_date=date.fromisoformat(data["invoice_date"]),
        due_date=date.fromisoformat(data["due_date"]),
        currency=data["currency"],
        subtotal=data["subtotal"],
        tax_amount=data["tax_amount"],
        grand_total=data["grand_total"],
        items=data["items"],
        coordinates=data["coordinates"],
    )
    # BE Gap 463: the widened columns (addresses, taxes, tax_ids…) an extraction
    # of a fuller invoice would have written.
    for key, value in (columns or {}).items():
        setattr(invoice, key, value)
    db_session.add(invoice)
    db_session.commit()
    db_session.refresh(invoice)
    return invoice


@pytest.fixture
def stored_blobs():
    store: dict[str, bytes] = {}

    def _fake_upload(file_data: bytes, tenant_id: str, invoice_id: str) -> str:
        store[invoice_id] = file_data
        return f"tenants/{tenant_id}/invoices/{invoice_id}.pdf"

    with patch("routers.outbound_invoices.upload_pdf_to_blob_storage", side_effect=_fake_upload), \
         patch("routers.outbound_invoices.QueueClient") as queue_cls:
        queue_cls.from_connection_string.return_value.send_message = MagicMock()
        yield store


def _build_body(source: Invoice, **overrides) -> dict:
    res = client.get(f"/api/v1/outbound-invoices/{source.id}/build-defaults")
    assert res.status_code == 200, res.text
    body = res.json()
    body.update(overrides)
    return body


# ── GET /build-defaults ──────────────────────────────────────────────────────

def test_build_defaults_returns_the_incremented_number_and_rolled_dates(db_session):
    source = _seed_source(db_session)
    res = client.get(f"/api/v1/outbound-invoices/{source.id}/build-defaults")

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["source_invoice_id"] == str(source.id)
    assert body["invoice_number"] == "INV-0043"
    assert body["customer_name"] == "Northwind Traders"
    assert body["invoice_date"] == date.today().isoformat()
    assert body["due_date"] == (date.today() + timedelta(days=30)).isoformat()
    assert len(body["items"]) == 2
    assert "amount" not in body["items"][0]  # the client never receives a line total


def test_build_defaults_404s_for_another_tenants_invoice(db_session):
    other = _seed_source(db_session, tenant_id=uuid4())
    try:
        res = client.get(f"/api/v1/outbound-invoices/{other.id}/build-defaults")
        assert res.status_code == 404
    finally:
        db_session.delete(other)
        db_session.commit()


def test_build_defaults_409s_on_a_needs_review_source(db_session):
    source = _seed_source(db_session, status="NEEDS_REVIEW")
    res = client.get(f"/api/v1/outbound-invoices/{source.id}/build-defaults")
    assert res.status_code == 409
    assert "NEEDS_REVIEW" in res.json()["detail"]


@pytest.mark.parametrize("status_value", ["VERIFIED", "SENT", "PAID"])
def test_build_defaults_accepts_every_eligible_status(db_session, status_value):
    source = _seed_source(db_session, status=status_value)
    assert client.get(f"/api/v1/outbound-invoices/{source.id}/build-defaults").status_code == 200


# ── POST /build/preview ──────────────────────────────────────────────────────

def test_preview_returns_a_pdf_and_persists_nothing(db_session):
    source = _seed_source(db_session)
    tenant_before = db_session.get(Tenant, TEST_TENANT_ID).free_invoices_remaining

    res = client.post("/api/v1/outbound-invoices/build/preview", json=_build_body(source))

    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == "application/pdf"
    assert res.content.startswith(b"%PDF")

    db_session.expire_all()
    rows = db_session.exec(select(Invoice).where(Invoice.tenant_id == TEST_TENANT_ID)).all()
    assert [r.id for r in rows] == [source.id]          # no new Invoice row
    assert db_session.get(Tenant, TEST_TENANT_ID).free_invoices_remaining == tenant_before


def test_preview_renders_the_edited_values_with_the_sources_branding(db_session):
    source = _seed_source(db_session)
    body = _build_body(source)
    body["items"][0]["quantity"] = "6"

    res = client.post("/api/v1/outbound-invoices/build/preview", json=body)
    assert res.status_code == 200, res.text
    with fitz.open(stream=res.content, filetype="pdf") as doc:
        text = doc[0].get_text()
    assert "INV-0043" in text
    assert "1,500.00" in text          # 6 × 250.00, in the source's separator style
    assert "1,250.00" not in text
    assert "Precision machining" in text   # the source's line survived the re-render


def test_preview_and_build_both_succeed_on_a_same_row_count_clone(db_session):
    """BE Gap 462 — the exact case the founder hit in the live UI.

    An ordinary clone keeps the row count and changes the dates and the totals.
    The old `plan_render_mode()` read that row count, committed to substitution,
    then could not find the source's printed `invoice_date` / `due_date` /
    `subtotal` and answered 422 on BOTH endpoints — which is why Preview failed
    and the Create button appeared to do nothing. Neither may refuse now.
    """
    source = _seed_source(db_session)
    body = _build_body(source)
    assert len(body["items"]) == len(source.items)     # same row count
    body["invoice_date"] = "2026-09-05"
    body["due_date"] = "2026-10-05"
    body["items"][0]["unit_price"] = "275.00"          # moves subtotal and total

    preview = client.post("/api/v1/outbound-invoices/build/preview", json=body)
    assert preview.status_code == 200, preview.text
    assert preview.content.startswith(b"%PDF")

    created = client.post("/api/v1/outbound-invoices/build", json=body)
    assert created.status_code == 201, created.text

    db_session.expire_all()
    row = db_session.get(Invoice, UUID(created.json()["invoice_id"]))
    assert row.builder_intent["render_mode"] == "rerender"


def test_preview_re_renders_when_a_row_was_added(db_session):
    source = _seed_source(db_session)
    body = _build_body(source)
    body["items"].append({"description": "Rush delivery", "quantity": "1", "unit_price": "99.00"})

    res = client.post("/api/v1/outbound-invoices/build/preview", json=body)
    assert res.status_code == 200, res.text
    with fitz.open(stream=res.content, filetype="pdf") as doc:
        text = doc[0].get_text()
    assert "Rush delivery" in text
    assert "1,699.00" in text          # 1,600.00 + 99.00, source separators


# ── POST /build ──────────────────────────────────────────────────────────────

def test_build_creates_an_outbound_invoice_like_an_upload(db_session, stored_blobs):
    source = _seed_source(db_session)
    before = db_session.get(Tenant, TEST_TENANT_ID).free_invoices_remaining

    res = client.post("/api/v1/outbound-invoices/build", json=_build_body(source))
    assert res.status_code == 201, res.text
    payload = res.json()

    db_session.expire_all()
    created = db_session.get(Invoice, UUID(payload["invoice_id"]))
    assert created.flow_direction == "OUTBOUND"
    assert created.status == "UPLOADED"
    assert created.source_invoice_id == source.id
    assert created.file_path.endswith(".pdf")
    assert created.last_enqueued_at is not None
    assert created.batch_id == UUID(payload["batch_id"])

    intent = created.builder_intent
    assert intent["invoice_number"] == "INV-0043"
    assert intent["render_mode"] == "rerender"
    assert intent["totals"]["grand_total"] in ("1920.00", 1920.0)

    # D2: billable exactly like an upload, and the stored blob is the PDF.
    assert db_session.get(Tenant, TEST_TENANT_ID).free_invoices_remaining == before - 1
    assert stored_blobs[str(created.id)].startswith(b"%PDF")


def test_build_refuses_a_number_already_used_for_the_same_customer(db_session, stored_blobs):
    """Founder decision D5 — refused before anything is rendered or charged."""
    source = _seed_source(db_session)
    before = db_session.get(Tenant, TEST_TENANT_ID).free_invoices_remaining

    body = _build_body(source, invoice_number=source.invoice_number)
    res = client.post("/api/v1/outbound-invoices/build", json=body)

    assert res.status_code == 409
    assert res.json()["detail"] == "Invoice number already used for this customer"

    db_session.expire_all()
    rows = db_session.exec(select(Invoice).where(Invoice.tenant_id == TEST_TENANT_ID)).all()
    assert [r.id for r in rows] == [source.id]
    assert db_session.get(Tenant, TEST_TENANT_ID).free_invoices_remaining == before
    assert stored_blobs == {}


def test_the_same_number_for_a_different_customer_is_allowed(db_session, stored_blobs):
    source = _seed_source(db_session)
    body = _build_body(source, invoice_number=source.invoice_number, customer_name="Someone Else Ltd")
    res = client.post("/api/v1/outbound-invoices/build", json=body)
    # BE Gap 462: this used to be `in (201, 422)` because a customer name that
    # is not printed on the source page could not be substituted. There is no
    # substitute path left, so a re-target to a new customer simply succeeds.
    assert res.status_code == 201, res.text


def test_build_from_a_needs_review_source_is_refused(db_session, stored_blobs):
    source = _seed_source(db_session)
    body = _build_body(source)
    source.status = "NEEDS_REVIEW"
    db_session.add(source)
    db_session.commit()

    res = client.post("/api/v1/outbound-invoices/build", json=body)
    assert res.status_code == 409
    assert stored_blobs == {}


# ── 17.7: the outbound list carries the lineage ──────────────────────────────

def test_outbound_list_exposes_source_invoice_id(db_session, stored_blobs):
    source = _seed_source(db_session)
    res = client.post("/api/v1/outbound-invoices/build", json=_build_body(source))
    assert res.status_code == 201, res.text
    built_id = res.json()["invoice_id"]

    listed = client.get("/api/v1/outbound-dashboard/invoices?limit=50")
    assert listed.status_code == 200, listed.text
    rows = {row["id"]: row for row in listed.json()}
    assert rows[built_id]["source_invoice_id"] == str(source.id)
    assert rows[str(source.id)]["source_invoice_id"] is None


# ── 17.6: the worker hook, on a real row ─────────────────────────────────────

def _run_outbound_handler(invoice: Invoice, extracted: dict, status: str = "VERIFIED"):
    from queue_worker import outbound_handlers

    agent_result = {"status": status, "alerts": [], "extracted_data": extracted}
    with patch.object(outbound_handlers, "_run_ocr", return_value={"content": "text", "coordinates": [], "field_confidence": {}}), \
         patch.object(outbound_handlers, "run_outbound_extraction_agent", return_value=agent_result), \
         patch.object(outbound_handlers, "_publish_sse_events"), \
         patch("chroma_client.index_invoice_document"), \
         patch("services.staff_notify.notify_processing_complete"):
        return outbound_handlers.handle_process_outbound_invoice(
            str(invoice.batch_id), invoice.file_path, str(invoice.tenant_id),
        )


def _built_invoice(db_session: Session, stored_blobs) -> Invoice:
    source = _seed_source(db_session)
    res = client.post("/api/v1/outbound-invoices/build", json=_build_body(source))
    assert res.status_code == 201, res.text
    db_session.expire_all()
    return db_session.get(Invoice, UUID(res.json()["invoice_id"]))


def test_a_clean_read_back_leaves_the_graphs_own_verdict(db_session, stored_blobs):
    built = _built_invoice(db_session, stored_blobs)
    intent = built.builder_intent
    result = _run_outbound_handler(built, _extracted_from(intent))

    assert result["status"] == "VERIFIED"
    assert not any(a["type"] == "builder_render_mismatch" for a in result["alerts"])


def test_a_two_cent_read_back_drift_forces_needs_review(db_session, stored_blobs):
    built = _built_invoice(db_session, stored_blobs)
    intent = built.builder_intent
    drifted = _extracted_from(intent, grand_total=float(intent["totals"]["grand_total"]) + 0.02)

    result = _run_outbound_handler(built, drifted)

    assert result["status"] == "NEEDS_REVIEW"
    alert = next(a for a in result["alerts"] if a["type"] == "builder_render_mismatch")
    assert "grand_total" in alert["message"]

    db_session.expire_all()
    reloaded = db_session.get(Invoice, built.id)
    assert reloaded.status == "NEEDS_REVIEW"
    assert any(a["type"] == "builder_render_mismatch" for a in reloaded.sa_alerts)


def test_an_uploaded_invoice_is_untouched_by_the_read_back_check(db_session, stored_blobs):
    """`builder_intent` is NULL on every upload, so the hook is inert."""
    uploaded = _seed_source(db_session, status="UPLOADED")
    result = _run_outbound_handler(
        uploaded,
        {"customer_name": "Whoever", "invoice_number": "X-1", "grand_total": 1.0, "items": []},
    )
    assert result["status"] == "VERIFIED"
    assert not any(a["type"] == "builder_render_mismatch" for a in result["alerts"])


# ═════════════════════════════════════════════════════════════════════════════
# BE Gap 463 — the widened editable set
# ═════════════════════════════════════════════════════════════════════════════
#
# Everything an invoice prints is now editable and, crucially, RE-PRINTED. Since
# BE Gap 462 deleted substitution, a field `BuildRequest` does not carry is not
# inherited from the source page any more — it is lost. These tests are the
# guard on that: what the source row holds, the clone prints.

#: The columns an extraction of a full Indian GST invoice writes, which before
#: Gap 463 the builder read none of.
_RICH_COLUMNS = {
    "vendor_name": "ACME Engineering Ltd",
    "po_number": "PO-77219",
    "addresses": [
        {"address_type": "billing", "text": "12 Park Road, Andheri", "country": "India"},
        {"address_type": "shipping", "text": "Warehouse 4, Bhiwandi"},
        {"address_type": "vendor", "text": "9 Mill Street, Pune"},
    ],
    "references": [{"ref_type": "Sales Order", "value": "SO-9912"}],
    "payment_instructions": [{"method_type": "UPI", "details": "acme@bank"}],
    "tax_ids": [{"id_type": "GSTIN", "value": "27ABCDE1234F1Z5", "party": "vendor"}],
    "taxes": [
        {"tax_type": "CGST", "rate_percent": 9.0, "amount": 72.0},
        {"tax_type": "SGST", "rate_percent": 9.0, "amount": 72.0},
    ],
    "discounts": [{"discount_type": "Trade discount", "percent": 2.0, "amount": 32.0}],
    "deductions": [{"deduction_type": "Retention", "amount": 25.0}],
    "compliance_metadata": [{"key": "IRN", "value": "a1b2c3d4"}],
    "discount_percent": 2.0,
    "discount_amount": 32.0,
    # BE Gap 467: a real `Invoice.notes` column, so the notes block is now one
    # of the extractor-written columns a clone reads from.
    "notes": "Goods once sold are not returnable.",
}


def _rich_source_row(**overrides) -> SimpleNamespace:
    row = _source_row("us_style", **_RICH_COLUMNS, **overrides)
    row.items = [
        {
            "description": "TMT reinforcement bars",
            "quantity": 8.0,
            "unit_price": 5400.0,
            "amount": 43200.0,
            "hsn_sac_code": "7214",
            "uom": "kg",
            "tax_percent": 18.0,
        },
    ]
    return row


def test_default_build_from_source_copies_every_printable_field():
    """Gap 463's whole claim: the prefill carries the source's addresses, PO
    number, references, payment instructions, tax IDs, tax/discount/deduction
    lines and compliance metadata — not just customer, number, dates and rows."""
    req = default_build_from_source(_rich_source_row(), date(2026, 9, 1))

    assert req.vendor_name == "ACME Engineering Ltd"
    assert req.po_number == "PO-77219"
    assert [a.address_type for a in req.addresses] == ["billing", "shipping", "vendor"]
    assert req.addresses[0].country == "India"
    assert [(r.ref_type, r.value) for r in req.references] == [("Sales Order", "SO-9912")]
    assert [(p.method_type, p.details) for p in req.payment_instructions] == [("UPI", "acme@bank")]
    assert [(t.id_type, t.value, t.party) for t in req.tax_ids] == [
        ("GSTIN", "27ABCDE1234F1Z5", "vendor")
    ]
    assert [(t.tax_type, t.rate_percent, t.amount) for t in req.taxes] == [
        ("CGST", Decimal("9"), Decimal("72")),
        ("SGST", Decimal("9"), Decimal("72")),
    ]
    assert [(d.discount_type, d.percent, d.amount) for d in req.discounts] == [
        ("Trade discount", Decimal("2"), Decimal("32"))
    ]
    assert [(d.deduction_type, d.amount) for d in req.deductions] == [("Retention", Decimal("25"))]
    assert [(c.key, c.value) for c in req.compliance_metadata] == [("IRN", "a1b2c3d4")]
    assert (req.discount_percent, req.discount_amount) == (Decimal("2"), Decimal("32"))
    # The per-line half of the widening.
    assert (req.items[0].hsn_sac_code, req.items[0].uom) == ("7214", "kg")
    assert req.items[0].tax_percent == Decimal("18")
    # BE Gap 467: `Invoice.notes` exists now, so the notes block is copied off
    # the source row like everything else above. Gap 463 asserted `is None` here
    # because there was no column to copy from.
    assert req.notes == "Goods once sold are not returnable."


def test_default_build_from_source_survives_a_malformed_json_column():
    """These are extractor-written JSON columns, not typed ones. A junk row must
    be dropped, not turn the prefill endpoint into a 500."""
    row = _source_row(
        "us_style",
        addresses=["not a dict", {"address_type": "billing", "text": "12 Park Road"}],
        taxes=[{"tax_type": "IGST", "rate_percent": "18"}],
        references=None,
    )
    req = default_build_from_source(row, date(2026, 9, 1))

    assert [a.text for a in req.addresses] == ["12 Park Road"]
    assert req.taxes[0].rate_percent == Decimal("18")
    assert req.taxes[0].amount is None
    assert req.references == []


def test_compute_totals_applies_a_per_line_discount_then_a_per_line_tax():
    totals = compute_totals(
        [
            BuildItem(
                description="a",
                quantity=Decimal("10"),
                unit_price=Decimal("100"),
                discount_percent=Decimal("10"),
                tax_percent=Decimal("18"),
            )
        ],
        None,
    )
    # gross 1000.00 − 100.00 discount = 900.00 printed amount; 18% of that.
    assert totals.line_discounts == [Decimal("100.00")]
    assert totals.line_amounts == [Decimal("900.00")]
    assert totals.line_taxes == [Decimal("162.00")]
    assert totals.subtotal == Decimal("900.00")
    assert totals.tax_amount == Decimal("162.00")
    assert totals.grand_total == Decimal("1062.00")


def test_compute_totals_charges_each_rate_on_the_discounted_base():
    totals = compute_totals(
        [BuildItem(description="a", quantity=Decimal("1"), unit_price=Decimal("1000"))],
        None,
        discounts=[BuildDiscount(discount_type="Trade", percent=Decimal("10"))],
        taxes=[
            BuildTax(tax_type="CGST", rate_percent=Decimal("9")),
            BuildTax(tax_type="SGST", rate_percent=Decimal("9")),
        ],
        deductions=[BuildDeduction(deduction_type="Retention", amount=Decimal("50"))],
    )
    assert totals.discount_lines == [Decimal("100.00")]
    assert totals.discount_total == Decimal("100.00")
    assert totals.tax_lines == [Decimal("81.00"), Decimal("81.00")]   # 9% of 900
    assert totals.tax_amount == Decimal("162.00")
    assert totals.deduction_total == Decimal("50.00")
    # 1000 − 100 + 162 − 50
    assert totals.grand_total == Decimal("1012.00")


def test_compute_totals_prefers_the_printed_amount_over_the_printed_rate():
    """Invoices print figures that do not reconcile with their own stated rate.
    The builder transcribes what was entered; it never corrects it."""
    totals = compute_totals(
        [BuildItem(description="a", quantity=Decimal("1"), unit_price=Decimal("1000"))],
        None,
        taxes=[BuildTax(tax_type="VAT", rate_percent=Decimal("9"), amount=Decimal("100"))],
    )
    assert totals.tax_lines == [Decimal("100.00")]
    assert totals.grand_total == Decimal("1100.00")


def test_compute_totals_is_digit_for_digit_unchanged_without_the_new_fields():
    """Backward compatibility, asserted rather than assumed: a pre-Gap-463 body
    (no discounts, no deductions, no `taxes`) totals exactly as it always did."""
    items = [
        BuildItem(description="a", quantity=Decimal("5"), unit_price=Decimal("250")),
        BuildItem(description="b", quantity=Decimal("2"), unit_price=Decimal("175")),
    ]
    totals = compute_totals(items, Decimal("40"))
    assert totals.line_amounts == [Decimal("1250.00"), Decimal("350.00")]
    assert (totals.subtotal, totals.tax_amount, totals.grand_total) == (
        Decimal("1600.00"), Decimal("40.00"), Decimal("1640.00"),
    )
    assert totals.discount_total == Decimal("0.00")
    assert totals.deduction_total == Decimal("0.00")


def test_render_invoice_prints_every_widened_field():
    req = default_build_from_source(_rich_source_row(), date(2026, 9, 1))
    req.notes = "Payment within 30 days of the invoice date."
    totals = totals_for(req)

    pdf_bytes = render_invoice(req, totals, harvest_branding(_pdf("us_style")), "1,234.56")
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        text = "".join(page.get_text() for page in doc)

    assert "PO Number: PO-77219" in text
    assert "Sales Order: SO-9912" in text
    # The three party blocks, each with its own address.
    assert "ACME Engineering Ltd" in text and "9 Mill Street, Pune" in text
    assert "12 Park Road, Andheri" in text and "India" in text
    assert "Warehouse 4, Bhiwandi" in text
    # Line-item columns that only appear when a row uses them.
    assert "HSN/SAC" in text and "7214" in text
    assert "kg" in text
    # Two tax rates, each on its own row, plus the discount and the deduction.
    assert "CGST (9%)" in text and "SGST (9%)" in text
    assert "Trade discount (2%)" in text
    assert "Retention" in text
    assert "UPI: acme@bank" in text
    assert "Payment within 30 days of the invoice date." in text
    assert "GSTIN (vendor): 27ABCDE1234F1Z5" in text
    assert "IRN: a1b2c3d4" in text


def test_render_invoice_omits_the_blocks_a_plain_invoice_has_nothing_for():
    """No addresses, no references, no per-line HSN — the same four-column
    table and the same three-row totals block the renderer printed before."""
    req = default_build_from_source(_source_row("us_style"), date(2026, 9, 1))
    pdf_bytes = render_invoice(req, totals_for(req), harvest_branding(_pdf("us_style")), "1,234.56")
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        text = "".join(page.get_text() for page in doc)

    for absent in ("HSN/SAC", "UOM", "Ship To", "Payment Instructions", "Notes", "PO Number"):
        assert absent not in text, absent
    assert "Bill To" in text and "Subtotal" in text


def test_verify_builder_readback_checks_the_discount_and_the_rate_count():
    intent = _intent_for()
    intent["totals"]["discount_total"] = "40.00"
    intent["totals"]["tax_lines"] = ["20.00", "20.00"]

    # A discount read back with the opposite sign is the same claim.
    agreed = _extracted_from(intent, discount_amount=-40.0, taxes=[{"amount": 20.0}, {"amount": 20.0}])
    assert verify_builder_readback(intent, agreed) == []

    # A dropped rate line and a wrong discount are both real render defects.
    drifted = _extracted_from(intent, discount_amount=25.0, taxes=[{"amount": 40.0}])
    fields = [m["field"] for m in verify_builder_readback(intent, drifted)]
    assert fields == ["discount_total", "taxes"]


# ═════════════════════════════════════════════════════════════════════════════
# BE Gap 467 — the read-back set widened to the outbound schema
# ═════════════════════════════════════════════════════════════════════════════

def _widened_intent() -> dict:
    """An intent carrying every field Gap 463 printed and Gap 463's read-back
    check could not look at."""
    intent = _intent_for()
    intent.update({
        "vendor_name": "ACME Engineering Ltd",
        "po_number": "PO-77219",
        "currency": "USD",
        "notes": "Goods once sold are not returnable.",
        "addresses": [{"address_type": "billing", "text": "12 Park Road, Andheri"}],
        "references": [{"ref_type": "Sales Order", "value": "SO-9912"}],
        "payment_instructions": [{"method_type": "UPI", "details": "acme@bank"}],
        "tax_ids": [{"id_type": "GSTIN", "value": "27ABCDE1234F1Z5", "party": "vendor"}],
        "compliance_metadata": [{"key": "IRN", "value": "a1b2c3d4"}],
        "items": [{"description": "TMT bars", "hsn_sac_code": "7214", "uom": "kg"}] * len(
            intent["totals"]["line_amounts"]
        ),
    })
    return intent


def _widened_extraction(intent: dict, **overrides) -> dict:
    extracted = _extracted_from(intent)
    extracted.update({
        "vendor_name": "ACME Engineering Ltd",
        "po_number": "PO-77219",
        "currency": "USD",
        "notes": "Goods once sold are not returnable.",
        "addresses": [{"address_type": "billing", "text": "12 Park Road, Andheri"}],
        "references": [{"ref_type": "Sales Order", "value": "SO-9912"}],
        "payment_instructions": [{"method_type": "UPI", "details": "acme@bank"}],
        "tax_ids": [{"id_type": "GSTIN", "value": "27ABCDE1234F1Z5"}],
        "compliance_metadata": [{"key": "IRN", "value": "a1b2c3d4"}],
    })
    for index, item in enumerate(extracted["items"]):
        item.update({"hsn_sac_code": "7214", "uom": "kg"})
    extracted.update(overrides)
    return extracted


def test_a_faithful_read_back_of_every_widened_field_agrees():
    intent = _widened_intent()
    assert verify_builder_readback(intent, _widened_extraction(intent)) == []


def test_a_silent_extractor_still_asserts_nothing_on_the_widened_fields():
    """The soft rule `currency` has always used, now applied to every field the
    schema gained: a reader that returned nothing for a field is not evidence
    that the render is wrong, and must never put a correct invoice on
    NEEDS_REVIEW. This is the exact behaviour Gap 463 got by excluding these
    fields; Gap 467 keeps it while making a WRONG value catchable."""
    intent = _widened_intent()
    assert verify_builder_readback(intent, _extracted_from(intent)) == []


def test_a_wrong_vendor_name_po_number_or_currency_is_now_caught():
    intent = _widened_intent()
    wrong = _widened_extraction(
        intent, vendor_name="Someone Else Ltd", po_number="PO-00000", currency="EUR",
    )
    assert [m["field"] for m in verify_builder_readback(intent, wrong)] == [
        "currency", "vendor_name", "po_number",
    ]


def test_a_dropped_address_reference_payment_tax_id_or_irn_is_now_caught():
    """Each list is checked by containment against everything the reader
    returned for that field — so a value the renderer failed to print is a
    mismatch, while a reader that merges or re-labels rows is not."""
    intent = _widened_intent()
    dropped = _widened_extraction(
        intent,
        addresses=[{"address_type": "billing", "text": "somewhere else entirely"}],
        references=[{"ref_type": "Sales Order", "value": "SO-0000"}],
        payment_instructions=[{"method_type": "UPI", "details": "someone@else"}],
        tax_ids=[{"id_type": "GSTIN", "value": "99ZZZZZ0000Z0Z0"}],
        compliance_metadata=[{"key": "IRN", "value": "deadbeef"}],
    )
    assert [m["field"] for m in verify_builder_readback(intent, dropped)] == [
        "addresses[0]", "references[0]", "payment_instructions[0]",
        "tax_ids[0]", "compliance_metadata[0]",
    ]


def test_a_reader_that_merges_or_adds_an_address_block_is_not_a_render_fault():
    """The renderer prints From / Bill To / Ship To separately; a reader that
    returns them as one block, in another order, or adds the letterhead's own
    address, has still read back everything that was printed. Counting rows
    would fail all three."""
    intent = _widened_intent()
    merged = _widened_extraction(intent, addresses=[
        {"address_type": "vendor", "text": "9 Mill Street, Pune"},
        {"address_type": "billing", "text": "ACME Engineering Ltd, 12 Park Road, Andheri, India"},
    ])
    assert verify_builder_readback(intent, merged) == []


def test_a_notes_block_read_back_with_a_heading_still_agrees_but_a_lost_one_does_not():
    intent = _widened_intent()
    wrapped = _widened_extraction(
        intent, notes="Notes:  Goods once sold\n are not returnable.",
    )
    assert verify_builder_readback(intent, wrapped) == []

    lost = _widened_extraction(intent, notes="Thank you for your business.")
    assert [m["field"] for m in verify_builder_readback(intent, lost)] == ["notes"]


def test_a_wrong_hsn_or_uom_on_a_line_is_now_caught():
    intent = _widened_intent()
    bad = _widened_extraction(intent)
    bad["items"][0]["hsn_sac_code"] = "9999"
    bad["items"][0]["uom"] = "each"
    assert [m["field"] for m in verify_builder_readback(intent, bad)] == [
        "items[0].hsn_sac_code", "items[0].uom",
    ]

    # …and a reader that simply did not fill the cells is still silent.
    silent = _widened_extraction(intent)
    for item in silent["items"]:
        item.pop("hsn_sac_code"), item.pop("uom")
    assert verify_builder_readback(intent, silent) == []


# ── the endpoints, on a real row ─────────────────────────────────────────────

def test_build_defaults_returns_the_widened_field_set(db_session):
    source = _seed_source(db_session, columns=_RICH_COLUMNS)
    res = client.get(f"/api/v1/outbound-invoices/{source.id}/build-defaults")

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["vendor_name"] == "ACME Engineering Ltd"
    assert body["po_number"] == "PO-77219"
    assert [a["address_type"] for a in body["addresses"]] == ["billing", "shipping", "vendor"]
    assert [t["tax_type"] for t in body["taxes"]] == ["CGST", "SGST"]
    assert body["compliance_metadata"] == [{"key": "IRN", "value": "a1b2c3d4"}]


def test_preview_prints_the_widened_fields_the_user_edited(db_session):
    source = _seed_source(db_session, columns=_RICH_COLUMNS)
    body = _build_body(
        source,
        po_number="PO-99999",
        notes="Late payment attracts 1.5% per month.",
        addresses=[{"address_type": "billing", "text": "New Buyer Road 7", "country": "India"}],
    )
    res = client.post("/api/v1/outbound-invoices/build/preview", json=body)

    assert res.status_code == 200, res.text
    with fitz.open(stream=res.content, filetype="pdf") as doc:
        text = "".join(page.get_text() for page in doc)
    assert "PO Number: PO-99999" in text
    assert "New Buyer Road 7" in text
    assert "Late payment attracts 1.5% per month." in text
    assert "CGST (9%)" in text


def test_build_stores_the_widened_intent_on_the_created_row(db_session, stored_blobs):
    source = _seed_source(db_session, columns=_RICH_COLUMNS)
    res = client.post("/api/v1/outbound-invoices/build", json=_build_body(source, notes="Thank you."))

    assert res.status_code == 201, res.text
    db_session.expire_all()
    built = db_session.get(Invoice, UUID(res.json()["invoice_id"]))
    intent = built.builder_intent
    assert intent["po_number"] == "PO-77219"
    assert intent["notes"] == "Thank you."
    assert [t["tax_type"] for t in intent["taxes"]] == ["CGST", "SGST"]
    # The server's own arithmetic, not the client's: 1600 subtotal, the 32.00
    # trade discount, CGST+SGST at 72.00 each, 25.00 retention.
    totals = intent["totals"]
    assert totals["subtotal"] == "1600.00"
    assert totals["discount_total"] == "32.00"
    assert totals["tax_amount"] == "144.00"
    assert totals["deduction_total"] == "25.00"
    assert totals["grand_total"] == "1687.00"


# ── BE Gap 467: the outbound row now carries what the outbound reader read ───

def _widened_readback(intent: dict) -> dict:
    """What `OutboundInvoiceExtractionSchema` now returns for a generated PDF —
    the money and dates from the intent, plus every field the schema gained."""
    extracted = _extracted_from(intent)
    extracted.update({
        "vendor_name": intent["vendor_name"],
        "po_number": intent["po_number"],
        "currency": intent["currency"],
        "notes": intent["notes"],
        "addresses": intent["addresses"],
        "references": intent["references"],
        "payment_instructions": intent["payment_instructions"],
        "tax_ids": intent["tax_ids"],
        "compliance_metadata": intent["compliance_metadata"],
        # A rich source prints a trade discount and two tax rates; both are
        # hard-asserted by the Gap 463 half of the check.
        "discount_amount": float(intent["totals"]["discount_total"]),
        "taxes": [{"amount": float(a)} for a in intent["totals"]["tax_lines"]],
    })
    return extracted


def test_the_outbound_handler_persists_the_widened_columns(db_session, stored_blobs):
    """Gap 467's first half: the outbound schema reads these, and the outbound
    worker writes them to the same columns the inbound worker already does. The
    read-back check must also stay clean on a faithful reading."""
    source = _seed_source(db_session, columns=_RICH_COLUMNS)
    res = client.post("/api/v1/outbound-invoices/build", json=_build_body(source))
    assert res.status_code == 201, res.text
    db_session.expire_all()
    built = db_session.get(Invoice, UUID(res.json()["invoice_id"]))

    result = _run_outbound_handler(built, _widened_readback(built.builder_intent))
    assert result["status"] == "VERIFIED"
    assert not any(a["type"] == "builder_render_mismatch" for a in result["alerts"])

    db_session.expire_all()
    row = db_session.get(Invoice, built.id)
    assert row.vendor_name == "ACME Engineering Ltd"
    assert row.po_number == "PO-77219"
    assert [a["text"] for a in row.addresses] == [
        "12 Park Road, Andheri", "Warehouse 4, Bhiwandi", "9 Mill Street, Pune",
    ]
    assert [r["value"] for r in row.references] == ["SO-9912"]
    assert [p["details"] for p in row.payment_instructions] == ["acme@bank"]
    assert [t["value"] for t in row.tax_ids] == ["27ABCDE1234F1Z5"]
    assert [c["value"] for c in row.compliance_metadata] == ["a1b2c3d4"]
    assert row.notes == "Goods once sold are not returnable."


def test_a_silent_reader_cannot_erase_the_notes_the_builder_printed(db_session, stored_blobs):
    """The one field the builder stamps at creation. A model that did not return
    the free-text block is not evidence the invoice has none, so the column
    keeps what was printed."""
    source = _seed_source(db_session, columns=_RICH_COLUMNS)
    body = _build_body(source, notes="Late payment attracts 1.5% per month.")
    built_id = UUID(client.post("/api/v1/outbound-invoices/build", json=body).json()["invoice_id"])
    db_session.expire_all()
    built = db_session.get(Invoice, built_id)
    assert built.notes == "Late payment attracts 1.5% per month."

    _run_outbound_handler(built, _extracted_from(built.builder_intent))

    db_session.expire_all()
    assert db_session.get(Invoice, built_id).notes == "Late payment attracts 1.5% per month."


def test_a_clone_of_a_clone_inherits_the_address_po_number_and_notes(db_session, stored_blobs):
    """Gap 467's second half, end to end. Generation 1 is an extracted invoice;
    generation 2 is built from it and processed by the outbound worker, which
    before this gap left every one of these columns empty on the new row; so
    generation 3's prefill had nothing to copy and the user's address, PO number
    and notes were lost one generation after they were typed."""
    gen1 = _seed_source(db_session, columns=_RICH_COLUMNS)

    gen2_body = _build_body(
        gen1,
        po_number="PO-88888",
        notes="Late payment attracts 1.5% per month.",
        addresses=[{"address_type": "billing", "text": "New Buyer Road 7", "country": "India"}],
    )
    gen2_id = UUID(client.post("/api/v1/outbound-invoices/build", json=gen2_body).json()["invoice_id"])
    db_session.expire_all()
    gen2 = db_session.get(Invoice, gen2_id)

    # The worker reads the generated PDF back and writes the columns.
    _run_outbound_handler(gen2, _widened_readback(gen2.builder_intent))
    db_session.expire_all()
    assert db_session.get(Invoice, gen2_id).status == "VERIFIED"

    # Generation 3's prefill, taken off generation 2's own row.
    gen3 = client.get(f"/api/v1/outbound-invoices/{gen2_id}/build-defaults")
    assert gen3.status_code == 200, gen3.text
    prefill = gen3.json()
    assert prefill["po_number"] == "PO-88888"
    assert prefill["notes"] == "Late payment attracts 1.5% per month."
    assert [a["text"] for a in prefill["addresses"]] == ["New Buyer Road 7"]
    assert prefill["vendor_name"] == "ACME Engineering Ltd"
    assert [t["value"] for t in prefill["tax_ids"]] == ["27ABCDE1234F1Z5"]
    assert [c["value"] for c in prefill["compliance_metadata"]] == ["a1b2c3d4"]

    # …and generation 3 actually prints them. The source PDF for this render is
    # the one generation 2's build wrote into the fake blob store, so the read
    # is pointed there rather than at Azure.
    with patch(
        "routers.outbound_invoices.download_pdf_from_storage",
        return_value=stored_blobs[str(gen2_id)],
    ):
        printed = client.post("/api/v1/outbound-invoices/build/preview", json=prefill)
    assert printed.status_code == 200, printed.text
    with fitz.open(stream=printed.content, filetype="pdf") as doc:
        text = "".join(page.get_text() for page in doc)
    assert "PO Number: PO-88888" in text
    assert "New Buyer Road 7" in text
    assert "Late payment attracts 1.5% per month." in text


def test_the_notes_column_is_a_migrated_column_on_a_single_head(db_session):
    """BE Gap 467's migration: `upgrade head` succeeded and left one head.

    `SQLModel.metadata.create_all()` does not ALTER an existing table, so the
    column this reads can only have come from `e7f8a9b0c1d2`. The head check is
    what catches a second migration branching off the same parent, which is how
    two agents working the same day produce a database nobody can upgrade.

    Nothing here asserts a downgrade path: the founder ruled on 2026-09-05 that
    this is a dev database in a dev phase and no existing data is migrated."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import text

    heads = ScriptDirectory.from_config(Config("alembic.ini")).get_heads()
    assert heads == ["e7f8a9b0c1d2"], heads

    column = db_session.exec(
        text(
            "SELECT data_type, is_nullable FROM information_schema.columns "
            "WHERE table_name = 'invoice' AND column_name = 'notes'"
        )
    ).one()
    assert column == ("character varying", "YES")
