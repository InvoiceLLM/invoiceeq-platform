"""Feature 17 — Invoice Builder (Clone & Edit).

Two halves:

* Pure units — `services/invoice_builder.py`, `services/pdf_substitute.py`,
  `services/pdf_render.py`, `utils/verification_tools.verify_builder_readback`
  — run against the committed fixtures in `tests/fixtures/invoice_builder/`
  (five source PDFs plus the `Invoice.coordinates` Document Intelligence would
  have stored for each). No Azure call, no database.
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
    BuildItem,
    BuildRequest,
    builder_intent,
    compute_totals,
    default_build_from_source,
    next_invoice_number,
    plan_render_mode,
    plan_substitutions,
)
from services.pdf_render import harvest_branding, render_invoice
from services.pdf_substitute import format_like, locate_field, substitute
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


def test_plan_substitutions_is_empty_for_an_unchanged_request():
    source = _source_row("us_style")
    req = default_build_from_source(source, source.invoice_date)
    req.invoice_number = source.invoice_number
    req.due_date = source.due_date
    totals = compute_totals(req.items, req.tax_amount)
    assert plan_substitutions(source, req, totals) == []


def test_plan_substitutions_touches_only_what_changed():
    source = _source_row("us_style")
    req = default_build_from_source(source, date(2026, 9, 1))
    totals = compute_totals(req.items, req.tax_amount)
    fields = {s.field for s in plan_substitutions(source, req, totals)}
    assert fields == {"invoice_number", "invoice_date", "due_date"}


def test_plan_render_mode_follows_the_line_count():
    source = _source_row("us_style")  # two lines
    req = default_build_from_source(source, date(2026, 9, 1))
    assert plan_render_mode(source, req) == "substitute"

    req.items.append(BuildItem(description="new", quantity=Decimal("1"), unit_price=Decimal("5")))
    assert plan_render_mode(source, req) == "rerender"

    del req.items[0:2]
    assert plan_render_mode(source, req) == "rerender"


# ═════════════════════════════════════════════════════════════════════════════
# 17.2 — substitution
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


def test_every_planned_field_is_located_within_its_di_polygon():
    """The header fields carry a Document Intelligence polygon; the rect
    `locate_field` returns must be the one that polygon points at."""
    source = _source_row("us_style")
    req = default_build_from_source(source, date(2026, 9, 1))
    totals = compute_totals(req.items, req.tax_amount)
    subs = plan_substitutions(source, req, totals)

    with fitz.open(stream=_pdf("us_style"), filetype="pdf") as doc:
        page = doc[0]
        pw, ph = page.rect.width, page.rect.height
        by_field = {
            "invoice_number": "InvoiceId",
            "invoice_date": "InvoiceDate",
            "due_date": "DueDate",
        }
        for sub in subs:
            di = next(
                c for c in source.coordinates if c["field"] == by_field[sub.field]
            )
            target = fitz.Rect(
                di["x"] / 100 * pw, di["y"] / 100 * ph,
                (di["x"] + di["width"]) / 100 * pw, (di["y"] + di["height"]) / 100 * ph,
            )
            printed = sub.old_text if sub.kind == "text" else sub.old_value.isoformat()
            rect = locate_field(page, sub.field, printed, source.coordinates)
            assert rect is not None, sub.field
            assert not (rect & target).is_empty, sub.field


def test_substitute_rewrites_the_new_values_and_removes_the_old():
    source = _source_row("us_style")
    req = default_build_from_source(source, date(2026, 9, 1))
    req.items[0].quantity = Decimal("6")
    totals = compute_totals(req.items, req.tax_amount)
    subs = plan_substitutions(source, req, totals)

    out, unlocated = substitute(_pdf("us_style"), subs, source.coordinates)
    assert unlocated == []

    with fitz.open(stream=out, filetype="pdf") as doc:
        text = doc[0].get_text()

    # New values printed…
    for expected in ("INV-0043", "2026-09-01", "2026-10-01", "1,500.00", "1,850.00", "2,170.00"):
        assert expected in text, expected
    # …and the old ones gone.
    for gone in ("INV-0042", "2026-07-15", "2026-08-14", "1,250.00", "1,600.00", "1,920.00"):
        assert gone not in text, gone


def test_substitute_keeps_the_sources_own_number_and_date_format():
    """The EU fixture prints `1.250,00` and `15.07.2026`; the clone must too."""
    source = _source_row("eu_style")
    req = default_build_from_source(source, date(2026, 9, 1))
    req.items[0].quantity = Decimal("6")
    totals = compute_totals(req.items, req.tax_amount)

    out, unlocated = substitute(_pdf("eu_style"), plan_substitutions(source, req, totals), source.coordinates)
    assert unlocated == []

    with fitz.open(stream=out, filetype="pdf") as doc:
        text = doc[0].get_text()
    assert "1.500,00" in text
    assert "1.850,00" in text
    assert "01.09.2026" in text
    assert "1,500.00" not in text


def test_substitute_uses_the_di_polygon_when_the_date_is_printed_twice():
    """`date_twice` repeats the invoice date in two footer sentences. Only the
    header occurrence carries the `InvoiceDate` polygon, and only it changes."""
    source = _source_row("date_twice")
    req = default_build_from_source(source, date(2026, 9, 1))
    totals = compute_totals(req.items, req.tax_amount)

    out, unlocated = substitute(_pdf("date_twice"), plan_substitutions(source, req, totals), source.coordinates)
    assert unlocated == []

    with fitz.open(stream=out, filetype="pdf") as doc:
        text = doc[0].get_text()
    assert "01/09/2026" in text
    assert text.count("15/07/2026") == 2  # both footer repetitions survive
    assert "Invoice Date: 15/07/2026" not in text


def test_substitute_reports_an_unlocatable_field_instead_of_raising():
    """The stored customer name does not match what the page prints, so the
    substitution cannot be placed. The field name comes back; the endpoint
    turns that into the 422 the builder screen renders."""
    source = _source_row("us_style", customer_name="A Name Never Printed Here")
    req = default_build_from_source(source, date(2026, 9, 1))
    req.customer_name = "Someone Else Entirely"
    totals = compute_totals(req.items, req.tax_amount)

    _out, unlocated = substitute(_pdf("us_style"), plan_substitutions(source, req, totals), source.coordinates)
    assert unlocated == ["customer_name"]


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
    return builder_intent(req, totals, "substitute")


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


def test_preview_renders_the_edited_values_into_the_source_layout(db_session):
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
    assert "Precision machining" in text   # the source layout survived


def test_preview_422s_with_the_unlocated_fields_at_the_top_level(db_session):
    """The FE reads `unlocated_fields` off the body, not out of `detail`."""
    source = _seed_source(db_session)
    source.customer_name = "A Name Never Printed Here"
    db_session.add(source)
    db_session.commit()

    body = _build_body(source)
    body["customer_name"] = "Someone Else Entirely"
    res = client.post("/api/v1/outbound-invoices/build/preview", json=body)

    assert res.status_code == 422
    assert res.json() == {"unlocated_fields": ["customer_name"]}


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
    assert intent["render_mode"] == "substitute"
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
    # The customer name is not printed on the source page, so the substitute
    # path cannot place it — a different customer is a re-render case in
    # practice; here we only assert the D5 gate does not fire.
    res = client.post("/api/v1/outbound-invoices/build", json=body)
    assert res.status_code in (201, 422)
    if res.status_code == 422:
        assert res.json() == {"unlocated_fields": ["customer_name"]}


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
