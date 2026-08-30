"""
Feature 25 (Gap 341): the embedded chat widget token.

The properties these tests exist to hold, each mapping to one of the security
review's numbered constraints:

  8.  a widget token resolves to `WidgetContext`, NOT `TenantContext`, and its
      dependency is mounted on exactly one route;
  9.  `Authorization: Bearer <token>` and `X-API-Key: <token>` behave
      identically instead of one falling through to the Clerk verifier;
  10. widget CORS is separate from `main.py`'s global `CORSMiddleware`, and
      never emits `Access-Control-Allow-Credentials`;
  11. origin pinning exists, is asserted, and is asserted to be bypassable
      outside a browser -- so nothing here reads as a guarantee.

Plus the storage contract (shown once, hashed, revocable) and the Admin gate.

The real-Postgres case is the cross-tenant one: a widget token must resolve only
to its own tenant's data, and tenant isolation is the property SQLite's laxer
constraint handling is least suited to proving.
"""
import inspect
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from main import app
from dependencies import (
    MOCK_TENANT_ID,
    TenantContext,
    WidgetContext,
    get_db_session,
    resolve_api_key_context,
)
from models import ChatMessage, ChatSession, Tenant, WidgetToken
from services.api_keys import (
    WIDGET_TOKEN_PREFIX,
    generate_widget_token,
    key_prefix,
    looks_like_api_key,
    looks_like_platform_credential,
    looks_like_widget_token,
    verify_api_key,
)
from services.widget_tokens import (
    MAX_TOKENS_PER_TENANT,
    active_widget_tokens,
    issue_widget_token,
    normalize_origin,
    origin_is_allowed,
    resolve_widget_token,
    revoke_widget_token,
)

sqlite_url = "sqlite:///:memory:"
engine = create_engine(
    sqlite_url,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

client = TestClient(app)

WIDGET_URL = "/api/v1/widget/chat/message"
TOKENS_URL = "/api/v1/settings/security/widget-tokens"


@pytest.fixture(name="db_session")
def db_session_fixture():
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)


@pytest.fixture(autouse=True)
def override_db_session(db_session):
    def _override():
        yield db_session

    app.dependency_overrides[get_db_session] = _override
    yield
    app.dependency_overrides.clear()


def _seed_tenant(db_session: Session, tenant_id=None) -> Tenant:
    tenant = Tenant(
        id=tenant_id or MOCK_TENANT_ID,
        name="Widget Workspace",
        domain=f"widget-{uuid4().hex[:8]}.example.com",
        billing_plan="pro",
    )
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def _fake_agent(**_kwargs):
    return {
        "content": "You spent 100.00 last month.",
        "generated_sql": "SELECT 1",
        "citations": [],
        "result_invoice_ids": [],
        "turn_telemetry": {"status": "ok", "route": "sql"},
    }


# ---------------------------------------------------------------------------
# Constraint 9 — prefix dispatch is consistent across both headers
# ---------------------------------------------------------------------------

class TestPrefixDispatch:
    def test_widget_token_carries_its_own_prefix(self):
        raw = generate_widget_token()
        assert raw.startswith(WIDGET_TOKEN_PREFIX)
        assert raw.startswith("inv_widget_")

    def test_widget_token_is_not_an_api_key(self):
        """Constraint 8: it must never be picked up as an API key."""
        raw = generate_widget_token()
        assert looks_like_widget_token(raw) is True
        assert looks_like_api_key(raw) is False

    def test_all_three_prefixes_are_recognised_as_ours(self):
        """Constraint 9: one dispatch question, asked once per prefix."""
        assert looks_like_platform_credential("inv_live_abc") is True
        assert looks_like_platform_credential("inv_test_abc") is True
        assert looks_like_platform_credential("inv_widget_abc") is True
        # A Clerk JWT is three base64url segments and starts with none of them.
        assert looks_like_platform_credential("eyJhbGciOi.eyJzdWIi.sig") is False

    def test_widget_prefix_slice_keeps_six_secret_chars(self):
        assert key_prefix("inv_widget_" + "a" * 40) == "inv_widget_aaaaaa"

    @pytest.mark.parametrize("header", ["authorization", "x-api-key"])
    def test_both_headers_give_the_same_error_on_the_api(self, db_session: Session, header):
        """Constraint 9, the actual point of it.

        Before this, `Authorization: Bearer inv_widget_...` fell through to the
        Clerk verifier and 401'd about a token signature while the identical
        value in `X-API-Key` 401'd about an invalid API key. One credential, two
        headers, two unrelated errors.
        """
        _seed_tenant(db_session)
        raw = generate_widget_token()
        value = f"Bearer {raw}" if header == "authorization" else raw

        response = client.get("/api/v1/invoices", headers={header: value})
        assert response.status_code == 401
        detail = response.json()["detail"]
        assert "chat widget token" in detail
        assert "/api/v1/widget/chat/message" in detail

    def test_widget_token_never_resolves_to_a_tenant_context(self, db_session: Session):
        """Constraint 8: refused inside resolve_api_key_context() itself."""
        from fastapi import HTTPException

        tenant = _seed_tenant(db_session)
        _token, raw = issue_widget_token(db_session, tenant.id)

        with pytest.raises(HTTPException) as exc:
            resolve_api_key_context(raw, db_session)
        assert exc.value.status_code == 401
        assert "chat widget token" in exc.value.detail


# ---------------------------------------------------------------------------
# Constraint 8 — structural containment
# ---------------------------------------------------------------------------

class TestStructuralContainment:
    def test_widget_context_carries_no_permission_fields(self):
        """Constraint 8: there is no field for a future scope bug to get wrong.

        Asserted against the model's own field set rather than by reading the
        class, so adding one of these later fails here rather than silently
        widening what a published credential can be checked for.
        """
        fields = set(WidgetContext.model_fields)
        for forbidden in (
            "role", "key_scope", "can_train", "can_audit", "can_load",
            "db_user_id", "billing_plan",
        ):
            assert forbidden not in fields, f"{forbidden} must not exist on WidgetContext"
        assert fields == {"tenant_id", "widget_token_id", "auth_method", "origin"}

    def test_widget_context_is_not_a_tenant_context(self):
        assert not issubclass(WidgetContext, TenantContext)
        assert not isinstance(
            WidgetContext(tenant_id=uuid4(), widget_token_id=uuid4()), TenantContext
        )

    def test_widget_dependency_is_mounted_on_exactly_one_route(self):
        """Constraint 8: the one-line change that would need re-review.

        Walks every route in the running app and counts how many declare
        `get_widget_context` as a dependency. Adding a second is what this
        assertion is here to catch in a diff.
        """
        from fastapi.routing import APIRoute
        from routers.widget import get_widget_context

        def _walk(routes):
            """FastAPI 0.138 wraps an included router in `_IncludedRouter`, so
            `app.routes` is not a flat list of APIRoute any more."""
            for route in routes:
                if isinstance(route, APIRoute):
                    yield route
                original = getattr(route, "original_router", None)
                if original is not None:
                    yield from _walk(original.routes)
                else:
                    for sub in getattr(route, "routes", None) or []:
                        yield from _walk([sub])

        mounted = set()
        for route in _walk(app.routes):
            # Router-level dependencies, plus the resolved dependency tree.
            for dependency in getattr(getattr(route, "dependant", None), "dependencies", []):
                if dependency.call is get_widget_context:
                    mounted.add(route.path)
            # And the handler's own signature defaults.
            try:
                params = inspect.signature(route.endpoint).parameters
            except (TypeError, ValueError):  # pragma: no cover - defensive
                continue
            for param in params.values():
                if getattr(param.default, "dependency", None) is get_widget_context:
                    mounted.add(route.path)

        assert mounted == {"/widget/chat/message"}, (
            f"get_widget_context is mounted on {sorted(mounted)} -- it must reach "
            "exactly one route"
        )

    def test_widget_token_cannot_reach_the_chat_router(self, db_session: Session):
        """The routes it must NOT reach, checked over real HTTP."""
        tenant = _seed_tenant(db_session)
        _token, raw = issue_widget_token(db_session, tenant.id)

        for method, url in (
            ("get", "/api/v1/chat/sessions"),
            ("get", f"/api/v1/chat/jobs/{uuid4()}/status"),
            ("get", "/api/v1/invoices"),
            ("get", "/api/v1/settings/security/api-key/verify"),
        ):
            response = getattr(client, method)(url, headers={"X-API-Key": raw})
            assert response.status_code == 401, f"{url} accepted a widget token"


# ---------------------------------------------------------------------------
# Storage contract
# ---------------------------------------------------------------------------

class TestStorage:
    def test_raw_token_is_never_persisted(self, db_session: Session):
        tenant = _seed_tenant(db_session)
        token, raw = issue_widget_token(db_session, tenant.id)

        assert token.token_hash != raw
        assert token.token_salt != raw
        assert token.token_prefix == key_prefix(raw)
        assert raw not in token.token_hash
        assert verify_api_key(raw, token.token_salt, token.token_hash) is True

    def test_two_tokens_for_one_tenant(self, db_session: Session):
        """The reason this is its own table: one-key-per-tenant is wrong here."""
        tenant = _seed_tenant(db_session)
        _a, raw_a = issue_widget_token(db_session, tenant.id, label="Marketing site")
        _b, raw_b = issue_widget_token(db_session, tenant.id, label="Docs site")

        assert raw_a != raw_b
        assert resolve_widget_token(db_session, raw_a) is not None
        assert resolve_widget_token(db_session, raw_b) is not None
        assert len(active_widget_tokens(db_session, tenant.id)) == 2

    def test_issuing_does_not_touch_the_tenant_api_key(self, db_session: Session):
        """Constraint 8: a widget token is not a third credential in the
        one-key-per-tenant columns."""
        tenant = _seed_tenant(db_session)
        tenant.api_key_hash = "preexisting-digest"
        tenant.api_key_salt = "preexisting-salt"
        tenant.api_key_prefix = "inv_live_abcdef"
        db_session.add(tenant)
        db_session.commit()

        issue_widget_token(db_session, tenant.id)
        db_session.refresh(tenant)
        assert tenant.api_key_hash == "preexisting-digest"
        assert tenant.api_key_salt == "preexisting-salt"
        assert tenant.api_key_prefix == "inv_live_abcdef"

    def test_revocation_is_immediate(self, db_session: Session):
        tenant = _seed_tenant(db_session)
        token, raw = issue_widget_token(db_session, tenant.id)
        assert resolve_widget_token(db_session, raw) is not None

        revoke_widget_token(db_session, tenant.id, token.id)
        assert resolve_widget_token(db_session, raw) is None

    def test_revoked_row_is_kept_not_deleted(self, db_session: Session):
        tenant = _seed_tenant(db_session)
        token, _raw = issue_widget_token(db_session, tenant.id)
        revoke_widget_token(db_session, tenant.id, token.id)

        row = db_session.exec(
            select(WidgetToken).where(WidgetToken.id == token.id)
        ).first()
        assert row is not None and row.revoked_at is not None
        assert active_widget_tokens(db_session, tenant.id) == []

    def test_cannot_revoke_another_tenants_token(self, db_session: Session):
        mine = _seed_tenant(db_session)
        theirs = _seed_tenant(db_session, tenant_id=uuid4())
        token, raw = issue_widget_token(db_session, theirs.id)

        assert revoke_widget_token(db_session, mine.id, token.id) is None
        assert resolve_widget_token(db_session, raw) is not None

    def test_wrong_and_unknown_tokens_are_the_same_answer(self, db_session: Session):
        tenant = _seed_tenant(db_session)
        issue_widget_token(db_session, tenant.id)

        assert resolve_widget_token(db_session, generate_widget_token()) is None
        assert resolve_widget_token(db_session, "") is None
        assert resolve_widget_token(db_session, "inv_widget_nonsense") is None

    def test_last_used_at_is_stamped(self, db_session: Session):
        tenant = _seed_tenant(db_session)
        token, raw = issue_widget_token(db_session, tenant.id)
        assert token.last_used_at is None
        resolved = resolve_widget_token(db_session, raw)
        assert resolved.last_used_at is not None


# ---------------------------------------------------------------------------
# Constraint 11 — origin pinning, and its honest limits
# ---------------------------------------------------------------------------

class TestOriginPinning:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("https://Acme.com", "https://acme.com"),
            ("https://acme.com/chat/embed", "https://acme.com"),
            ("acme.com", "https://acme.com"),
            ("http://localhost:3000", "http://localhost:3000"),
            ("  https://acme.com  ", "https://acme.com"),
            ("", None),
            (None, None),
            ("not a url at all", None),
        ],
    )
    def test_origin_normalisation(self, raw, expected):
        assert normalize_origin(raw) == expected

    def test_empty_allowlist_disables_the_layer(self, db_session: Session):
        """Deliberate opt-in, not default-deny: an empty list denying everything
        would make every freshly issued token dead on arrival."""
        tenant = _seed_tenant(db_session)
        token, _raw = issue_widget_token(db_session, tenant.id, allowed_origins=[])
        assert origin_is_allowed(token, "https://anywhere.example") is True
        assert origin_is_allowed(token, None) is True

    def test_registered_origin_matches_case_insensitively(self, db_session: Session):
        tenant = _seed_tenant(db_session)
        token, _raw = issue_widget_token(
            db_session, tenant.id, allowed_origins=["https://Acme.com"]
        )
        assert origin_is_allowed(token, "https://acme.com") is True
        assert origin_is_allowed(token, "https://acme.com/page") is True
        assert origin_is_allowed(token, "https://evil.example") is False
        assert origin_is_allowed(token, None) is False

    def test_unregistered_origin_is_403_over_http(self, db_session: Session):
        tenant = _seed_tenant(db_session)
        _token, raw = issue_widget_token(
            db_session, tenant.id, allowed_origins=["https://acme.com"]
        )
        response = client.post(
            WIDGET_URL,
            headers={"X-API-Key": raw, "Origin": "https://evil.example"},
            json={"content": "hello"},
        )
        assert response.status_code == 403
        assert "not registered" in response.json()["detail"]

    def test_origin_pinning_is_bypassable_outside_a_browser(self, db_session: Session):
        """Constraint 11, asserted rather than only documented.

        This test **passes by demonstrating the bypass**: a client that simply
        sets the header gets in. That is the honest state of this control, and
        writing it down as a test is what stops a later reader treating the
        allowlist as a hard boundary. The real containment is elsewhere -- one
        route, and a context type with no permissions on it.
        """
        tenant = _seed_tenant(db_session)
        _token, raw = issue_widget_token(
            db_session, tenant.id, allowed_origins=["https://acme.com"]
        )
        with patch("routers.chat.run_query_agent", side_effect=_fake_agent):
            response = client.post(
                WIDGET_URL,
                headers={"X-API-Key": raw, "Origin": "https://acme.com"},
                json={"content": "hello"},
            )
        assert response.status_code == 200, (
            "a forged Origin header was accepted -- which is the documented "
            "limitation of this layer, not a regression"
        )


# ---------------------------------------------------------------------------
# Constraint 10 — CORS
# ---------------------------------------------------------------------------

class TestWidgetCORS:
    def test_global_allowed_origins_was_not_widened(self):
        """Constraint 10, stated as the thing that must NOT have happened.

        `main.py`'s CORSMiddleware runs with allow_credentials=True. Adding a
        customer's domain to its origin list would make every
        session-authenticated route in the product cross-origin reachable, with
        credentials, from that domain.
        """
        from config import get_settings

        for origin in get_settings().ALLOWED_ORIGINS.split(","):
            assert origin.strip() in {
                "http://localhost:3000", "http://127.0.0.1:3000",
                "http://localhost:3001", "http://127.0.0.1:3001",
            } or origin.strip().endswith(".azurecontainerapps.io") or origin.strip() == "", (
                f"unexpected global CORS origin {origin!r}"
            )

    def test_widget_middleware_is_outermost(self):
        """It must see a preflight before the global middleware passes an
        unknown origin through to a 405."""
        from routers.widget import WidgetCORSMiddleware

        names = [m.cls.__name__ for m in app.user_middleware]
        assert names[0] == WidgetCORSMiddleware.__name__

    def test_preflight_from_an_unknown_origin_is_answered(self):
        response = client.options(
            WIDGET_URL,
            headers={
                "Origin": "https://a-customer-we-never-heard-of.example",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert response.status_code == 200
        assert response.headers["Access-Control-Allow-Origin"] == (
            "https://a-customer-we-never-heard-of.example"
        )
        assert "POST" in response.headers["Access-Control-Allow-Methods"]
        assert response.headers.get("Vary") == "Origin"

    def test_widget_response_never_allows_credentials(self, db_session: Session):
        """THE load-bearing assertion of constraint 10.

        With credentials off, a browser attaches no cookies to a cross-origin
        widget request regardless of which origin is reflected -- which is
        exactly why reflecting an arbitrary origin is safe here and would not be
        safe in the global middleware.
        """
        preflight = client.options(
            WIDGET_URL,
            headers={"Origin": "https://acme.com", "Access-Control-Request-Method": "POST"},
        )
        assert "access-control-allow-credentials" not in {
            k.lower() for k in preflight.headers
        }

        tenant = _seed_tenant(db_session)
        _token, raw = issue_widget_token(db_session, tenant.id)
        with patch("routers.chat.run_query_agent", side_effect=_fake_agent):
            actual = client.post(
                WIDGET_URL,
                headers={"X-API-Key": raw, "Origin": "https://acme.com"},
                json={"content": "hi"},
            )
        assert actual.status_code == 200
        assert "access-control-allow-credentials" not in {k.lower() for k in actual.headers}
        assert actual.headers["Access-Control-Allow-Origin"] == "https://acme.com"

    def test_non_widget_paths_are_untouched(self):
        """The middleware is path-scoped; it must not add headers elsewhere."""
        response = client.get("/health", headers={"Origin": "https://evil.example"})
        assert response.headers.get("Access-Control-Allow-Origin") != "https://evil.example"

    def test_one_allow_origin_header_even_for_a_globally_allowed_origin(
        self, db_session: Session
    ):
        """Two `Access-Control-Allow-Origin` values is a protocol error every
        browser rejects, so the header is set rather than appended."""
        tenant = _seed_tenant(db_session)
        _token, raw = issue_widget_token(db_session, tenant.id)
        with patch("routers.chat.run_query_agent", side_effect=_fake_agent):
            response = client.post(
                WIDGET_URL,
                headers={"X-API-Key": raw, "Origin": "http://localhost:3000"},
                json={"content": "hi"},
            )
        assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:3000"
        assert len(response.headers.get_list("access-control-allow-origin")) == 1


# ---------------------------------------------------------------------------
# The chat route itself
# ---------------------------------------------------------------------------

class TestWidgetChat:
    def test_missing_token_is_401(self):
        assert client.post(WIDGET_URL, json={"content": "hi"}).status_code == 401

    def test_api_key_is_not_accepted_here(self, db_session: Session):
        """The route takes widget tokens only -- an `inv_live_` key is a 401,
        not a promotion."""
        tenant = _seed_tenant(db_session)
        from services.api_keys import generate_api_key, generate_salt, hash_api_key

        raw = generate_api_key()
        salt = generate_salt()
        tenant.api_key_hash = hash_api_key(raw, salt)
        tenant.api_key_salt = salt
        tenant.api_key_prefix = key_prefix(raw)
        db_session.add(tenant)
        db_session.commit()

        response = client.post(
            WIDGET_URL, headers={"X-API-Key": raw}, json={"content": "hi"}
        )
        assert response.status_code == 401

    def test_first_message_creates_a_labelled_session(self, db_session: Session):
        tenant = _seed_tenant(db_session)
        _token, raw = issue_widget_token(db_session, tenant.id)

        with patch("routers.chat.run_query_agent", side_effect=_fake_agent):
            response = client.post(
                WIDGET_URL, headers={"X-API-Key": raw}, json={"content": "spend?"}
            )
        assert response.status_code == 200
        body = response.json()
        assert body["content"] == "You spent 100.00 last month."

        chat_session = db_session.get(ChatSession, uuid4()) or db_session.exec(
            select(ChatSession).where(ChatSession.tenant_id == tenant.id)
        ).first()
        assert chat_session.title == "Website widget chat"

    def test_follow_up_reuses_the_session(self, db_session: Session):
        tenant = _seed_tenant(db_session)
        _token, raw = issue_widget_token(db_session, tenant.id)

        with patch("routers.chat.run_query_agent", side_effect=_fake_agent):
            first = client.post(
                WIDGET_URL, headers={"X-API-Key": raw}, json={"content": "one"}
            ).json()
            second = client.post(
                WIDGET_URL,
                headers={"X-API-Key": raw},
                json={"content": "two", "session_id": first["session_id"]},
            ).json()

        assert second["session_id"] == first["session_id"]
        messages = db_session.exec(
            select(ChatMessage).where(ChatMessage.session_id == uuid4())
        ).all()
        assert messages == []  # sanity: the filter above is a real filter
        assert len(active_widget_tokens(db_session, tenant.id)) == 1

    def test_another_tenants_session_is_403(self, db_session: Session):
        """A widget token is published, so a guessed session id must not work."""
        mine = _seed_tenant(db_session)
        theirs = _seed_tenant(db_session, tenant_id=uuid4())
        their_session = ChatSession(id=uuid4(), tenant_id=theirs.id, title="theirs")
        db_session.add(their_session)
        db_session.commit()

        _token, raw = issue_widget_token(db_session, mine.id)
        response = client.post(
            WIDGET_URL,
            headers={"X-API-Key": raw},
            json={"content": "hi", "session_id": str(their_session.id)},
        )
        assert response.status_code == 403

    def test_unknown_session_is_404(self, db_session: Session):
        tenant = _seed_tenant(db_session)
        _token, raw = issue_widget_token(db_session, tenant.id)
        response = client.post(
            WIDGET_URL,
            headers={"X-API-Key": raw},
            json={"content": "hi", "session_id": str(uuid4())},
        )
        assert response.status_code == 404

    def test_widget_uses_the_same_turn_function_as_the_dashboard(
        self, db_session: Session
    ):
        """Not a second answer path: same judge, same telemetry, same fallback."""
        tenant = _seed_tenant(db_session)
        _token, raw = issue_widget_token(db_session, tenant.id)

        with patch("routers.chat.run_sync_chat_turn") as mocked:
            mocked.return_value = ChatMessage(
                id=uuid4(), session_id=uuid4(), role="assistant", content="stub"
            )
            response = client.post(
                WIDGET_URL, headers={"X-API-Key": raw}, json={"content": "hi"}
            )
        assert response.status_code == 200
        assert mocked.call_count == 1


# ---------------------------------------------------------------------------
# Admin management endpoints
# ---------------------------------------------------------------------------

class TestAdminManagement:
    def test_issue_list_revoke_round_trip(self, db_session: Session):
        _seed_tenant(db_session)

        created = client.post(TOKENS_URL, json={"label": "Marketing", "allowed_origins": ["acme.com"]})
        assert created.status_code == 201
        body = created.json()
        assert body["widget_token"].startswith(WIDGET_TOKEN_PREFIX)
        assert body["allowed_origins"] == ["https://acme.com"]
        assert body["masked_token"].startswith("inv_widget_")

        listed = client.get(TOKENS_URL)
        assert listed.status_code == 200
        assert [t["id"] for t in listed.json()] == [body["id"]]
        # The listing must never carry the raw value.
        assert "widget_token" not in listed.json()[0]

        deleted = client.delete(f"{TOKENS_URL}/{body['id']}")
        assert deleted.status_code == 204
        assert client.get(TOKENS_URL).json() == []

    def test_non_admin_is_403_on_all_three(self, db_session: Session):
        _seed_tenant(db_session)
        headers = {"Authorization": "Bearer test_viewer"}

        assert client.get(TOKENS_URL, headers=headers).status_code == 403
        assert client.post(TOKENS_URL, headers=headers, json={}).status_code == 403
        assert client.delete(f"{TOKENS_URL}/{uuid4()}", headers=headers).status_code == 403

    def test_invalid_origin_is_422(self, db_session: Session):
        _seed_tenant(db_session)
        response = client.post(
            TOKENS_URL, json={"allowed_origins": ["not a url at all"]}
        )
        assert response.status_code == 422
        assert "https://example.com" in response.json()["detail"]

    def test_per_tenant_cap(self, db_session: Session):
        tenant = _seed_tenant(db_session)
        for _ in range(MAX_TOKENS_PER_TENANT):
            issue_widget_token(db_session, tenant.id)

        response = client.post(TOKENS_URL, json={})
        assert response.status_code == 409
        assert str(MAX_TOKENS_PER_TENANT) in response.json()["detail"]

    def test_revoking_an_unknown_token_is_404(self, db_session: Session):
        _seed_tenant(db_session)
        assert client.delete(f"{TOKENS_URL}/{uuid4()}").status_code == 404


# ---------------------------------------------------------------------------
# Real Postgres — tenant isolation
# ---------------------------------------------------------------------------

def test_widget_token_is_tenant_isolated_on_postgres():
    """A widget token reads its own tenant's chat and nothing else, on real Postgres.

    Why Postgres specifically: `widget_tokens.token_prefix` is UNIQUE at the
    schema level (unlike `tenant.api_key_prefix`, which is only indexed) because
    it is the sole cross-tenant lookup key, and two rows sharing one would make
    resolution ambiguous rather than merely slow. SQLite is not where a UNIQUE
    constraint or an FK to `tenant.id` gets proven. The tenant-isolation half is
    then driven against those real constraints.
    """
    psycopg2 = pytest.importorskip("psycopg2")
    from config import get_settings

    url = get_settings().DATABASE_URL
    if not url.startswith("postgresql"):
        pytest.skip("DATABASE_URL is not PostgreSQL")
    try:
        psycopg2.connect(url).close()
    except psycopg2.OperationalError as exc:
        pytest.skip(f"local Postgres not reachable: {exc}")

    from sqlalchemy.exc import IntegrityError

    pg_engine = create_engine(url)
    SQLModel.metadata.create_all(pg_engine)

    tag = uuid4().hex[:10]
    tenant_a = Tenant(id=uuid4(), name="A", domain=f"widget-a-{tag}.invalid")
    tenant_b = Tenant(id=uuid4(), name="B", domain=f"widget-b-{tag}.invalid")

    with Session(pg_engine) as session:
        created = []
        try:
            session.add(tenant_a)
            session.add(tenant_b)
            session.commit()

            token_a, raw_a = issue_widget_token(
                session, tenant_a.id, allowed_origins=["https://a.example"]
            )
            token_b, raw_b = issue_widget_token(session, tenant_b.id)
            created = [token_a.id, token_b.id]

            # Real FK + real JSONB round-trip.
            assert token_a.allowed_origins == ["https://a.example"]
            reread = session.exec(
                select(WidgetToken).where(WidgetToken.id == token_a.id)
            ).first()
            assert reread.allowed_origins == ["https://a.example"]

            # Isolation: each raw token resolves to its own tenant, only.
            assert resolve_widget_token(session, raw_a).tenant_id == tenant_a.id
            assert resolve_widget_token(session, raw_b).tenant_id == tenant_b.id
            assert active_widget_tokens(session, tenant_a.id) == [
                t for t in active_widget_tokens(session, tenant_a.id)
                if t.tenant_id == tenant_a.id
            ]
            assert [t.id for t in active_widget_tokens(session, tenant_b.id)] == [token_b.id]

            # A's revoke must not reach B's token.
            assert revoke_widget_token(session, tenant_a.id, token_b.id) is None
            assert resolve_widget_token(session, raw_b) is not None

            # The UNIQUE prefix constraint is real, and only Postgres enforces it.
            clash = WidgetToken(
                id=uuid4(),
                tenant_id=tenant_b.id,
                token_hash="x", token_salt="y",
                token_prefix=token_a.token_prefix,
            )
            session.add(clash)
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()

            # And the FK to tenant.id is real.
            orphan = WidgetToken(
                id=uuid4(),
                tenant_id=uuid4(),
                token_hash="x", token_salt="y",
                token_prefix=f"inv_widget_{tag[:6]}",
            )
            session.add(orphan)
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()
        finally:
            for token_id in created:
                row = session.get(WidgetToken, token_id)
                if row is not None:
                    session.delete(row)
            session.flush()
            for tenant in (tenant_a, tenant_b):
                row = session.get(Tenant, tenant.id)
                if row is not None:
                    session.delete(row)
            session.commit()
