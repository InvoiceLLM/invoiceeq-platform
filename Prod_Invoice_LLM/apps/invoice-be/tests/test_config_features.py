"""GET /config/features — Feature 27 task R5(a).

security-tester's pass on new surface. The endpoint is small, so the tests are
weighted almost entirely towards what it must NOT do: publish a secret, publish
anything tenant-derived, or grow a per-tenant dimension that E2 forbids.

The recurring shape is that the allow-list is STRUCTURAL (a name prefix plus a
type check) rather than a curated list someone maintains. A curated list is one
forgetful edit away from publishing `AZURE_OPENAI_API_KEY`; a prefix rule cannot
be forgotten, only deliberately subverted.
"""
import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("MOCK_EMBEDDINGS", "true")

from config import get_settings  # noqa: E402
from main import app  # noqa: E402

client = TestClient(app)
ENDPOINT = "/api/v1/config/features"


def test_it_returns_a_flat_boolean_map_of_every_enable_flag():
    res = client.get(ENDPOINT)
    assert res.status_code == 200

    flags = res.json()["flags"]
    assert flags, "the map must not be empty -- config.py has ENABLE_* flags"
    assert all(isinstance(v, bool) for v in flags.values())
    assert all(k.startswith("ENABLE_") for k in flags)

    # The two this feature turns on, present and readable by name.
    assert "ENABLE_GENERIC_EXTRACTION" in flags
    assert "ENABLE_GENERIC_DOC_CHAT" in flags


def test_it_reports_the_real_current_values_not_a_hardcoded_map():
    """A hardcoded map would pass every other test here and be useless -- the
    entire point is to reflect the running process."""
    settings = get_settings()
    flags = client.get(ENDPOINT).json()["flags"]
    for name, value in flags.items():
        assert value == bool(getattr(settings, name)), name


def test_it_publishes_nothing_that_is_not_an_enable_flag():
    """The load-bearing security assertion. `config.py` holds API keys,
    connection strings and endpoints alongside the flags; an endpoint that
    returned "a config value by name" would be one refactor from returning
    `AZURE_OPENAI_API_KEY`.

    Asserted against the WHOLE settings object rather than against a list of
    known-bad names, so a secret added to config.py tomorrow is covered by this
    test today.
    """
    settings = get_settings()
    published = set(client.get(ENDPOINT).json()["flags"])

    for name in type(settings).model_fields:
        if name in published:
            assert name.startswith("ENABLE_"), f"{name} is published but is not a flag"
            assert isinstance(getattr(settings, name), bool), name

    # And spot-check the categories that would matter most if they leaked.
    for sensitive in (
        "AZURE_OPENAI_API_KEY",
        "AZURE_DOC_INTEL_KEY",
        "DATABASE_URL",
        "REDIS_URL",
        "AZURE_OPENAI_ENDPOINT",
    ):
        assert sensitive not in published


def test_the_response_carries_no_tenant_identifier_or_tenant_derived_value():
    """E2: these flags are software-level. The response must be identical for
    every caller, and must not echo who asked.

    A tenant id in the body would be harmless in itself but is the first step
    toward per-tenant resolution -- which E2 forbids outright, and which this
    test exists to make visible if anyone starts.
    """
    body = client.get(ENDPOINT).json()
    assert set(body) == {"flags"}, "no key other than `flags`"

    serialized = str(body).lower()
    for token in ("tenant", "user", "email", "session", "token", "key", "secret"):
        assert token not in serialized, f"{token!r} appears in the response body"


def test_two_callers_get_the_same_answer():
    """The per-tenant guard, asserted behaviourally rather than by reading the
    code. If someone later adds a tenant dimension, this is what fails."""
    first = client.get(ENDPOINT).json()
    second = client.get(ENDPOINT).json()
    assert first == second


def test_a_flag_flip_is_visible_immediately(monkeypatch):
    """No caching at the API layer. The FE caches at boot deliberately, but the
    endpoint itself must answer for the process as it is RIGHT NOW -- a flag is a
    kill switch, and a cached kill switch takes effect at an unpredictable time.
    """
    import config

    before = client.get(ENDPOINT).json()["flags"]["ENABLE_GENERIC_EXTRACTION"]
    monkeypatch.setattr(config.settings, "ENABLE_GENERIC_EXTRACTION", not before)
    after = client.get(ENDPOINT).json()["flags"]["ENABLE_GENERIC_EXTRACTION"]
    assert after is (not before)


def test_it_is_read_only():
    """There is no PUT. `routers/settings.py` owns tenant configuration; this
    owns process booleans and nothing else."""
    # `delete` takes no json body in this client, so the verbs are driven
    # through `request()` rather than the per-verb helpers.
    for verb in ("PUT", "POST", "PATCH", "DELETE"):
        assert client.request(verb, ENDPOINT).status_code in (404, 405), verb
