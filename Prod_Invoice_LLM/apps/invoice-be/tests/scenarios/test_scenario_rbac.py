"""P13 — who is allowed to do what, as a matrix rather than one test per case.

BS-P13-01  each persona reaches exactly the surfaces their role grants
"""
import pytest

# (persona, method, path, allowed?) -- "allowed" means "not refused for permission reasons".
#
# The invoice list is deliberately NOT permission-gated: `list_invoices` depends on
# `get_tenant_or_api_key_context`, which answers "who is calling" and checks no
# permission. So an invited-but-ungranted member (RoleMapper.NO_ROLE, the
# zero-permission fallback) can still READ the ledger. The matrix below records the
# code's actual contract rather than an assumed one -- whether reading should require
# a grant is founder decision D-6 in BUSINESS_SCENARIO_TEST_PLAN.md, not something a
# test may decide on its own.
MATRIX = [
    ("priya_admin", "GET", "/api/v1/invoices", True),
    ("ravi_clerk", "GET", "/api/v1/invoices", True),
    ("anita_auditor", "GET", "/api/v1/invoices", True),
    ("nobody", "GET", "/api/v1/invoices", True),   # see D-6 above
    ("priya_admin", "GET", "/api/v1/admin/users", True),
    ("anita_auditor", "GET", "/api/v1/admin/users", False),
    ("ravi_clerk", "GET", "/api/v1/admin/users", False),
    ("nobody", "GET", "/api/v1/admin/users", False),
    ("sanjay_trainer", "GET", "/api/v1/trainer/vendors", True),
    ("ravi_clerk", "GET", "/api/v1/trainer/vendors", False),
    ("nobody", "GET", "/api/v1/trainer/vendors", False),
]


@pytest.mark.scenario("BS-P13-01")
@pytest.mark.parametrize("persona,method,path,allowed", MATRIX,
                         ids=[f"{p}-{m}-{path.strip('/').replace('/', '_')}-{'allow' if a else 'deny'}"
                              for p, m, path, a in MATRIX])
def test_permission_matrix(as_persona, persona, method, path, allowed):
    client = as_persona(persona)
    response = client.request(method, path)

    if allowed:
        assert response.status_code != 403, f"{persona} should be allowed {method} {path}"
    else:
        assert response.status_code == 403, f"{persona} must be refused {method} {path}, got {response.status_code}"
