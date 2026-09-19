"""BE Gap 675: which vendor's trained rules apply to an extracted vendor name.

Postgres only (CONVENTIONS hard rule 2) -- these are lookups over real
`ExtractionTemplate`, `Vendor` and `VendorAlias` rows. The first version of this file
used a MagicMock session, so a missing direction filter or a wrong query could not fail.

Rules verified here:
  * exact, normalized (legal suffix / punctuation / case), and CONFIRMED-alias matches apply;
  * an OUTBOUND template never applies to an inbound invoice (BE Gap 568);
  * an unconfirmed alias and a merely similar name (typo) do NOT apply -- no fuzzy match;
  * two templates normalising to the same name resolve deterministically, with a warning;
  * a miss is logged.
"""
import logging
from datetime import datetime, timedelta
from uuid import uuid4

from sqlmodel import Session

from models import ExtractionTemplate, Vendor, VendorAlias
from queue_worker.handlers import _get_template_rules
from services.vendor_master import normalise_vendor_name
from tests.pg_gap_fixtures import pg_engine, pg_only  # noqa: F401  (pytest fixture)

TENANT = uuid4()


def _template(session, vendor_name, rule, direction="INBOUND", updated_at=None):
    session.add(ExtractionTemplate(
        tenant_id=TENANT, vendor_name=vendor_name, flow_direction=direction,
        rules={"constraints": [rule]}, updated_at=updated_at or datetime.utcnow(),
    ))
    session.commit()


def _alias(session, canonical, alias, confirmed):
    vendor = Vendor(tenant_id=TENANT, canonical_name=canonical)
    session.add(vendor)
    session.commit()
    session.add(VendorAlias(tenant_id=TENANT, vendor_id=vendor.id, alias=normalise_vendor_name(alias),
                            raw_alias=alias, confirmed_by="admin@test" if confirmed else None))
    session.commit()


@pg_only
def test_exact_and_normalized_names_apply(pg_engine):
    with Session(pg_engine) as s:
        _template(s, "Acme Private Limited", "acme rule")
        assert _get_template_rules(s, str(TENANT), "Acme Private Limited") == ["acme rule"]
        assert _get_template_rules(s, str(TENANT), "ACME Ltd.") == ["acme rule"]


@pg_only
def test_outbound_template_never_applies_to_inbound(pg_engine):
    with Session(pg_engine) as s:
        _template(s, "Vertex Industries Pvt Ltd", "outbound-only rule", direction="OUTBOUND")
        assert _get_template_rules(s, str(TENANT), "VERTEX INDUSTRIES") == []


@pg_only
def test_confirmed_alias_applies_and_unconfirmed_does_not(pg_engine):
    with Session(pg_engine) as s:
        _template(s, "Shree Packaging", "shree rule")
        _alias(s, "Shree Packaging", "SP Packers", confirmed=True)
        _template(s, "Kaveri Logistics", "kaveri rule")
        _alias(s, "Kaveri Logistics", "KL Transport", confirmed=False)
        assert _get_template_rules(s, str(TENANT), "SP Packers") == ["shree rule"]
        assert _get_template_rules(s, str(TENANT), "KL Transport") == []


@pg_only
def test_a_similar_but_different_name_does_not_apply(pg_engine, caplog):
    """The removed fuzzy match would have applied TechSolutions' rules here."""
    with Session(pg_engine) as s:
        _template(s, "TechSolutions", "tech rule")
        with caplog.at_level(logging.INFO, logger="queue_worker.handlers"):
            assert _get_template_rules(s, str(TENANT), "TechSolutioons") == []
    assert "No vendor template matched for extracted vendor 'TechSolutioons'" in caplog.text


@pg_only
def test_duplicate_normalized_templates_resolve_to_the_newest_and_warn(pg_engine, caplog):
    with Session(pg_engine) as s:
        _template(s, "Rajesh Traders", "old rule", updated_at=datetime.utcnow() - timedelta(days=5))
        _template(s, "RAJESH TRADERS PVT LTD", "new rule", updated_at=datetime.utcnow())
        with caplog.at_level(logging.WARNING, logger="queue_worker.handlers"):
            first = _get_template_rules(s, str(TENANT), "Rajesh Traders Ltd")
            second = _get_template_rules(s, str(TENANT), "Rajesh Traders Ltd")
    assert first == second == ["new rule"]
    assert "normalise to 'rajesh traders'" in caplog.text


@pg_only
def test_global_template_is_the_inbound_one(pg_engine):
    with Session(pg_engine) as s:
        _template(s, None, "global inbound")
        _template(s, None, "global outbound", direction="OUTBOUND")
        assert _get_template_rules(s, str(TENANT), None) == ["global inbound"]
