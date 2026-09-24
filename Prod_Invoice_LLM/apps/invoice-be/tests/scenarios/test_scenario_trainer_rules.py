"""
BS-P5-02  a rule taught on one invoice reaches the vendor's next invoice

Covers QA finding F-13 (`docs/qa_findings_2026-09.md`): a standing rule taught by
correcting the vendor name is stored under the *corrected* name and looked up by
the *printed* one. `_get_template_rules` bridges that with a normalized-name pass,
which works -- until an older template already sits under the printed name, at
which point the exact-match branch returns first and the newer rule is never seen.

The two tests below are deliberately a pair. The first proves the matching logic
is sound; the second proves the ordering around it is not. Without the first,
a reader of the second would reasonably conclude that "LIMITED" simply does not
match "Ltd", and go fix the wrong thing.
"""
from uuid import uuid4

import pytest
from sqlmodel import Session

from models import ExtractionTemplate
from queue_worker.handlers import _get_template_rules

MISREAD = "ACME SUPPLIES LIMITED"   # what the paper says
TAUGHT = "Acme Supplies Ltd"        # what the auditor corrected it to

VENDOR_RULE = f"For vendor name, extract the value as '{TAUGHT}', not '{MISREAD}'."
CURRENCY_RULE = "For currency, extract the value as 'GBP', not 'EUR'."


def _template(tenant_id, vendor_name: str, *constraints: str) -> ExtractionTemplate:
    return ExtractionTemplate(
        id=uuid4(),
        tenant_id=tenant_id,
        vendor_name=vendor_name,
        flow_direction="INBOUND",
        rules={"constraints": list(constraints)},
    )


@pytest.mark.scenario("BS-P5-02")
def test_a_taught_vendor_name_rule_is_found_on_the_next_invoice(vpi):
    """The ordinary case: this vendor has been taught exactly one thing.

    The rule lives under the corrected spelling; the next invoice arrives
    printed with the original. `normalise_vendor_name` reduces both to
    'acme supplies', so the normalized pass finds it.
    """
    with Session(vpi.engine) as s:
        s.add(_template(vpi.tenant_id, TAUGHT, VENDOR_RULE))
        s.commit()

        found = _get_template_rules(s, str(vpi.tenant_id), MISREAD)

    assert VENDOR_RULE in found, (
        "a vendor-name rule taught on the previous invoice did not reach this one; "
        f"lookup by the printed name {MISREAD!r} returned {found!r}"
    )


@pytest.mark.scenario("BS-P5-02")
@pytest.mark.xfail(
    strict=True,
    reason=(
        "QA finding F-13: the exact-match branch (queue_worker/handlers.py:617-621) returns the "
        "stale template keyed by the printed name and never reaches the normalized pass on line "
        "623, so the rule taught second is invisible. Remove this marker when F-13 is fixed."
    ),
)
def test_a_taught_vendor_name_rule_is_found_even_when_an_older_template_shadows_it(vpi):
    """The case a real tenant reaches: this vendor was taught something before.

    An earlier currency correction created a template under the printed name.
    Correcting the vendor name then creates a *second* template under the
    corrected name -- the unique key is (tenant, vendor_name, flow_direction),
    so the two cannot merge. Both belong to one vendor, and the lookup must
    honour the rule the auditor taught most recently, not the row whose key
    happens to be checked first.
    """
    with Session(vpi.engine) as s:
        s.add(_template(vpi.tenant_id, MISREAD, CURRENCY_RULE))
        s.add(_template(vpi.tenant_id, TAUGHT, VENDOR_RULE))
        s.commit()

        found = _get_template_rules(s, str(vpi.tenant_id), MISREAD)

    # The currency rule is expected either way -- it is keyed by the printed name.
    # What must not happen is the vendor rule going missing because of it.
    assert CURRENCY_RULE in found, f"the pre-existing currency rule was lost: {found!r}"
    assert VENDOR_RULE in found, (
        "the vendor-name rule was shadowed by an older template under the printed name; "
        f"lookup returned only {found!r}"
    )
