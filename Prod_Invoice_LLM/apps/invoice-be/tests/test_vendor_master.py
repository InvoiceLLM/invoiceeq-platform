"""Feature 30 task 30.0f — the per-tenant vendor master, against REAL Postgres.

Verification plan 30.0f: "'Shree Packaging Pvt Ltd' and 'SHREE PACKAGING'
resolve to one vendor after one confirmation; an unconfirmed alias never
auto-binds."

The last clause is the one that matters and the one the tests are built around:
a fuzzy name match may PROPOSE, never bind. Everything else in this module is
string normalisation.
"""
import os
from uuid import uuid4

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

os.environ.setdefault("MOCK_EMBEDDINGS", "true")

from models import Invoice, Vendor, VendorAlias  # noqa: E402
from services import vendor_master as vm  # noqa: E402


@pytest.fixture(name="pg_session")
def pg_session_fixture():
    psycopg2 = pytest.importorskip("psycopg2")
    from config import get_settings

    url = get_settings().DATABASE_URL
    if not url.startswith("postgresql"):
        pytest.skip("DATABASE_URL is not PostgreSQL")
    try:
        psycopg2.connect(url, connect_timeout=5).close()
    except psycopg2.OperationalError as exc:  # pragma: no cover - env dependent
        pytest.skip(f"local Postgres not reachable: {exc}")

    engine = create_engine(url)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture(name="tenants")
def tenants_fixture(pg_session):
    a, b = uuid4(), uuid4()
    yield a, b
    for model in (VendorAlias, Vendor, Invoice):
        for row in pg_session.exec(select(model).where(model.tenant_id.in_([a, b]))).all():
            pg_session.delete(row)
        pg_session.commit()


# --- normalisation ---------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Shree Packaging Pvt Ltd", "shree packaging"),
        ("SHREE PACKAGING", "shree packaging"),
        ("Shree Packaging Private Limited", "shree packaging"),
        ("Shree  Packaging,  Pvt. Ltd.", "shree packaging"),
        ("Acme Corp", "acme"),
        ("", ""),
        (None, ""),
    ],
)
def test_normalisation_drops_legal_form_and_punctuation(raw, expected):
    assert vm.normalise_vendor_name(raw) == expected


def test_two_unnamed_vendors_do_not_collide(pg_session, tenants):
    """"" must never match "" -- that would merge every nameless vendor."""
    tenant_a, _ = tenants
    res = vm.resolve_vendor("   ", tenant_a, pg_session)
    assert res.status == "none"
    assert res.is_bound is False


# --- resolution ------------------------------------------------------------


def test_canonical_name_binds(pg_session, tenants):
    tenant_a, _ = tenants
    vendor = vm.get_or_create_vendor("Shree Packaging Pvt Ltd", tenant_a, pg_session)

    res = vm.resolve_vendor("shree packaging pvt. ltd.", tenant_a, pg_session)
    assert res.status == "canonical"
    assert res.is_bound is True
    assert res.vendor.id == vendor.id


def test_a_close_name_is_proposed_and_never_bound(pg_session, tenants):
    """The rule the whole module exists for."""
    tenant_a, _ = tenants
    vm.get_or_create_vendor("Shree Packaging Pvt Ltd", tenant_a, pg_session)

    res = vm.resolve_vendor("Shree Packagng", tenant_a, pg_session)
    assert res.status == "proposed"
    assert res.is_bound is False
    assert res.requires_confirmation is True
    assert [v.canonical_name for v in res.candidates] == ["Shree Packaging Pvt Ltd"]


def test_an_unconfirmed_alias_never_auto_binds(pg_session, tenants):
    tenant_a, _ = tenants
    vendor = vm.get_or_create_vendor("Shree Packaging Pvt Ltd", tenant_a, pg_session)
    vm.propose_alias("Shree Pkg Works", vendor.id, tenant_a, pg_session)

    res = vm.resolve_vendor("Shree Pkg Works", tenant_a, pg_session)
    assert res.status == "proposed"
    assert res.is_bound is False


def test_one_confirmation_makes_the_two_spellings_one_vendor(pg_session, tenants):
    tenant_a, _ = tenants
    vendor = vm.get_or_create_vendor("Shree Packaging Pvt Ltd", tenant_a, pg_session)
    vm.confirm_alias(
        "Shree Pkg Works", vendor.id, tenant_a, pg_session, confirmed_by="owner@example.com"
    )

    res = vm.resolve_vendor("SHREE PKG WORKS", tenant_a, pg_session)
    assert res.status == "alias"
    assert res.is_bound is True
    assert res.vendor.id == vendor.id


def test_an_alias_is_never_shared_across_tenants(pg_session, tenants):
    """Ruling R6, explicit: one tenant's claim is not evidence for another's."""
    tenant_a, tenant_b = tenants
    vendor = vm.get_or_create_vendor("Shree Packaging Pvt Ltd", tenant_a, pg_session)
    vm.confirm_alias("Shree Pkg Works", vendor.id, tenant_a, pg_session, confirmed_by="a@x.com")

    vm.get_or_create_vendor("Shree Packaging Pvt Ltd", tenant_b, pg_session)
    res = vm.resolve_vendor("Shree Pkg Works", tenant_b, pg_session)
    assert res.is_bound is False


def test_confirming_twice_keeps_one_alias_row(pg_session, tenants):
    tenant_a, _ = tenants
    vendor = vm.get_or_create_vendor("Acme Corp", tenant_a, pg_session)
    vm.confirm_alias("Acme Industries", vendor.id, tenant_a, pg_session, confirmed_by="a@x.com")
    vm.confirm_alias("Acme Industries", vendor.id, tenant_a, pg_session, confirmed_by="b@x.com")

    rows = pg_session.exec(
        select(VendorAlias).where(VendorAlias.tenant_id == tenant_a)
    ).all()
    assert len(rows) == 1
    assert rows[0].confirmed_by == "b@x.com"


# --- what the cards actually consume ---------------------------------------


def test_vendor_invoice_names_returns_every_confirmed_spelling(pg_session, tenants):
    tenant_a, _ = tenants
    vendor = vm.get_or_create_vendor("Shree Packaging Pvt Ltd", tenant_a, pg_session)
    vm.confirm_alias("Shree Pkg Works", vendor.id, tenant_a, pg_session, confirmed_by="a@x.com")

    for i, name in enumerate(
        ["Shree Packaging Pvt Ltd", "SHREE PACKAGING", "Shree Pkg Works", "Unrelated Traders"]
    ):
        pg_session.add(
            Invoice(
                tenant_id=tenant_a,
                invoice_number=f"INV-VM-{i}",
                file_path=f"test/vm-{i}.pdf",
                vendor_name=name,
                grand_total=100.0,
            )
        )
    pg_session.commit()

    names = vm.vendor_invoice_names(vendor.id, tenant_a, pg_session)
    # "SHREE PACKAGING" normalises to the canonical key, so it comes along
    # without needing an alias of its own; "Unrelated Traders" does not.
    assert names == ["SHREE PACKAGING", "Shree Packaging Pvt Ltd", "Shree Pkg Works"]


def test_vendor_invoice_names_refuses_another_tenants_vendor(pg_session, tenants):
    tenant_a, tenant_b = tenants
    vendor = vm.get_or_create_vendor("Acme Corp", tenant_a, pg_session)
    assert vm.vendor_invoice_names(vendor.id, tenant_b, pg_session) == []


# --- 30.0f's wiring into the Feature 29 entity resolver --------------------


def test_entity_resolver_binds_every_spelling_through_the_master(pg_session, tenants):
    """The resolver must see one supplier, not two vendors with similar names."""
    from agents.entity_resolver import resolve_entities

    tenant_a, _ = tenants
    vendor = vm.get_or_create_vendor("Shree Packaging Pvt Ltd", tenant_a, pg_session)
    vm.confirm_alias("Shree Pkg Works", vendor.id, tenant_a, pg_session, confirmed_by="a@x.com")
    for i, name in enumerate(["Shree Packaging Pvt Ltd", "Shree Pkg Works"]):
        pg_session.add(
            Invoice(
                tenant_id=tenant_a,
                invoice_number=f"INV-ER-{i}",
                file_path=f"test/er-{i}.pdf",
                vendor_name=name,
                grand_total=100.0,
            )
        )
    pg_session.commit()

    result = resolve_entities(
        "what did we buy from Shree Packaging last month?", str(tenant_a), pg_session
    )
    assert sorted(result.vendor_names) == ["Shree Packaging Pvt Ltd", "Shree Pkg Works"]


def test_entity_resolver_is_unaffected_when_the_master_is_empty(pg_session, tenants):
    """Inert until the vendor master has content — every tenant, today."""
    from agents.entity_resolver import resolve_entities

    tenant_a, _ = tenants
    pg_session.add(
        Invoice(
            tenant_id=tenant_a,
            invoice_number="INV-ER-9",
            file_path="test/er-9.pdf",
            vendor_name="Bharat Steels",
            grand_total=100.0,
        )
    )
    pg_session.commit()

    result = resolve_entities("show invoices from Bharat Steels", str(tenant_a), pg_session)
    assert result.vendor_names == ["Bharat Steels"]
