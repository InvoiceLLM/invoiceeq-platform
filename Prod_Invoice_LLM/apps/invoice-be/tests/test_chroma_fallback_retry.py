"""Gap 415 — the Chroma fallback must be temporary, and must never read as healthy.

What was live before this: `_build_chroma_client()` fell back to a local
PersistentClient on any exception and `get_chroma_client()` cached that object for
the process lifetime with no retry anywhere. On `ca-invoice-be-dev` the connect
timed out at startup on **every** revision from `--0000116` to `--0000120` (~3.1 s
against a 3.0 s budget), so vector search ran against an empty in-container store
until the next deploy — while `warm_rag_dependencies()` logged `chroma=ok`,
because a PersistentClient answers `heartbeat()` perfectly well.

These tests pin both halves: the retry, and the honest status.
"""
import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("MOCK_EMBEDDINGS", "true")

import chroma_client  # noqa: E402


@pytest.fixture(autouse=True)
def reset_chroma_singleton():
    """Every test starts from an uninitialised module."""
    chroma_client._chroma_client = None
    chroma_client._chroma_client_kind = None
    chroma_client._chroma_fallback_at = None
    yield
    chroma_client._chroma_client = None
    chroma_client._chroma_client_kind = None
    chroma_client._chroma_fallback_at = None


def _http_client_ok():
    client = MagicMock(name="HttpClient")
    client.heartbeat.return_value = 1
    return client


class _Boom(Exception):
    pass


def test_a_successful_connect_is_recorded_as_http():
    with patch.object(chroma_client.chromadb, "HttpClient", return_value=_http_client_ok()):
        chroma_client.get_chroma_client()
    assert chroma_client.get_chroma_client_kind() == "http"


def test_a_failed_connect_is_recorded_as_fallback_not_as_ok():
    with patch.object(chroma_client.chromadb, "HttpClient", side_effect=_Boom("timed out")), \
         patch.object(chroma_client.chromadb, "PersistentClient", return_value=MagicMock()):
        chroma_client.get_chroma_client()
    assert chroma_client.get_chroma_client_kind() == "persistent-fallback"


def test_kind_is_uninitialised_before_any_call():
    assert chroma_client.get_chroma_client_kind() == "uninitialised"


def test_within_the_cooldown_the_fallback_is_reused_without_a_retry():
    """A down Chroma must not put a connect attempt in front of every request."""
    http = MagicMock(side_effect=_Boom("timed out"))
    with patch.object(chroma_client.chromadb, "HttpClient", http), \
         patch.object(chroma_client.chromadb, "PersistentClient", return_value=MagicMock()):
        first = chroma_client.get_chroma_client()
        assert http.call_count == 1
        for _ in range(5):
            assert chroma_client.get_chroma_client() is first
        assert http.call_count == 1, "retried inside the cooldown"


def test_after_the_cooldown_a_retry_promotes_the_process_back_to_http():
    """The defect: before this, the first failure decided RAG for the whole process."""
    recovered = _http_client_ok()
    http = MagicMock(side_effect=[_Boom("timed out"), recovered])
    with patch.object(chroma_client.chromadb, "HttpClient", http), \
         patch.object(chroma_client.chromadb, "PersistentClient", return_value=MagicMock()):
        fallback = chroma_client.get_chroma_client()
        assert chroma_client.get_chroma_client_kind() == "persistent-fallback"

        # Age the fallback past the cooldown.
        chroma_client._chroma_fallback_at -= (
            chroma_client.CHROMA_FALLBACK_RETRY_COOLDOWN_SECONDS + 1
        )

        promoted = chroma_client.get_chroma_client()

    assert promoted is recovered
    assert promoted is not fallback
    assert chroma_client.get_chroma_client_kind() == "http"
    assert http.call_count == 2


def test_a_failed_retry_keeps_the_existing_fallback_and_restarts_the_cooldown():
    http = MagicMock(side_effect=[_Boom("timed out"), _Boom("still down")])
    with patch.object(chroma_client.chromadb, "HttpClient", http), \
         patch.object(chroma_client.chromadb, "PersistentClient", side_effect=lambda **kw: MagicMock()):
        first = chroma_client.get_chroma_client()
        chroma_client._chroma_fallback_at -= (
            chroma_client.CHROMA_FALLBACK_RETRY_COOLDOWN_SECONDS + 1
        )
        second = chroma_client.get_chroma_client()
        aged = chroma_client._chroma_fallback_at

        # The cooldown restarted, so the next call must not retry again.
        third = chroma_client.get_chroma_client()

    assert second is first, "swapped in a second, equally empty fallback"
    assert third is first
    assert chroma_client.get_chroma_client_kind() == "persistent-fallback"
    assert http.call_count == 2, "retried again immediately after a failed retry"
    assert aged is not None


def test_warm_up_reports_degraded_when_it_is_on_the_fallback():
    """The false-green line: `chroma=ok` three seconds after `HttpClient failed`."""
    with patch.object(chroma_client.chromadb, "HttpClient", side_effect=_Boom("timed out")), \
         patch.object(chroma_client.chromadb, "PersistentClient", return_value=MagicMock()), \
         patch.object(chroma_client, "get_embedding_model", return_value=None):
        results = chroma_client.warm_rag_dependencies()

    assert results["chroma"].startswith("degraded"), results["chroma"]
    assert "PersistentClient" in results["chroma"]


def test_warm_up_reports_ok_only_for_a_real_server():
    with patch.object(chroma_client.chromadb, "HttpClient", return_value=_http_client_ok()), \
         patch.object(chroma_client, "get_embedding_model", return_value=None):
        results = chroma_client.warm_rag_dependencies()

    assert results["chroma"] == "ok"


def test_warm_up_uses_the_longer_connect_budget():
    """3 s is a request-path budget; warm-up blocks no request and must wait properly."""
    seen = {}

    real_timeout = chroma_client._chroma_http_timeout

    def _spy(connect_timeout=None):
        seen["connect_timeout"] = connect_timeout
        return real_timeout(connect_timeout)

    with patch.object(chroma_client, "_chroma_http_timeout", _spy), \
         patch.object(chroma_client.chromadb, "HttpClient", return_value=_http_client_ok()), \
         patch.object(chroma_client, "get_embedding_model", return_value=None):
        chroma_client.warm_rag_dependencies()

    assert seen["connect_timeout"] == chroma_client.CHROMA_WARMUP_CONNECT_TIMEOUT_SECONDS
    assert (
        chroma_client.CHROMA_WARMUP_CONNECT_TIMEOUT_SECONDS
        > chroma_client.CHROMA_CONNECT_TIMEOUT_SECONDS
    )


def test_the_request_path_budget_is_unchanged():
    """Gap 278's guarantee: a live chat turn never waits longer than 3 s to connect."""
    assert chroma_client.CHROMA_CONNECT_TIMEOUT_SECONDS == 3.0
    timeout = chroma_client._chroma_http_timeout()
    assert timeout.connect == 3.0
    assert timeout.read == chroma_client.CHROMA_READ_TIMEOUT_SECONDS
