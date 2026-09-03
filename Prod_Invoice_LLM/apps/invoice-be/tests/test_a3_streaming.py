"""Feature 6.1 item A3 — the phrasing calls stream their text as progress.

Four calls in a chat turn produce prose the user reads: the SQL summary, the RAG
answer, and the two Feature 26 narrations. The model writes each one token by
token and nothing between the model and the browser needs the whole answer
first. A3 streams them as `streaming` progress events carrying the partial
text; the browser renders the answer as it is written.

Only those four. SQL generation is structured output, and every figure a
summary can state was computed by the deterministic blocks before the call
began (hard rule 3) — streaming changes WHEN text arrives, never what it says.

Off by default (`ENABLE_CHAT_STREAMING`), and inert without a listener: the
synchronous HTTP path has no SSE channel, so it never streams regardless.
"""
import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("MOCK_EMBEDDINGS", "true")

import config  # noqa: E402
from agents import query_agent  # noqa: E402
from agents.query_agent import _answer_text, _content_text, _progress_emitter  # noqa: E402


class _FakeChunk:
    def __init__(self, content):
        self.content = content


class _StreamingLLM:
    """A model that can stream. `.invoke` must NOT be called when streaming."""

    def __init__(self, pieces):
        self.pieces = list(pieces)
        self.invoked = 0
        self.streamed = 0

    def stream(self, prompt):
        self.streamed += 1
        for p in self.pieces:
            yield _FakeChunk(p)

    def invoke(self, prompt):
        self.invoked += 1
        return MagicMock(content="".join(self.pieces))


class _InvokeOnlyLLM:
    """A model with no `.stream` — a mock, or a recording LLM in a test."""

    def __init__(self, text):
        self.text = text
        self.invoked = 0

    def invoke(self, prompt):
        self.invoked += 1
        return MagicMock(content=self.text)


def _listener():
    events = []
    progress = _progress_emitter(lambda step, details: events.append((step, details)))
    return progress, events


@pytest.fixture
def streaming_on(monkeypatch):
    monkeypatch.setattr(config.settings, "ENABLE_CHAT_STREAMING", True, raising=False)


@pytest.fixture
def streaming_off(monkeypatch):
    monkeypatch.setattr(config.settings, "ENABLE_CHAT_STREAMING", False, raising=False)


# ---------------------------------------------------------------------------
# When it streams
# ---------------------------------------------------------------------------


def test_streams_and_emits_growing_partials_then_a_final_event(streaming_on):
    llm = _StreamingLLM(["Hardware spend ", "is $45,000.00 ", "across three invoices, ", "all in USD."])
    progress, events = _listener()

    res = _answer_text(llm, "prompt", progress)

    assert res.content == "Hardware spend is $45,000.00 across three invoices, all in USD."
    assert llm.streamed == 1 and llm.invoked == 0
    streaming = [d for s, d in events if s == "streaming"]
    assert streaming, "no streaming events were emitted"
    partials = [d["partial"] for d in streaming]
    # Monotonic: every partial is a prefix of the next, and the last is the whole.
    for a, b in zip(partials, partials[1:]):
        assert b.startswith(a)
    assert partials[-1] == res.content
    assert streaming[-1].get("final") is True
    assert streaming[-1]["chars"] == len(res.content)


def test_flushes_at_most_every_flush_window_not_per_token(streaming_on):
    """Each event is a Redis publish; per-token publishes would be noise."""
    pieces = ["a"] * 200  # 200 one-char chunks
    llm = _StreamingLLM(pieces)
    progress, events = _listener()

    _answer_text(llm, "prompt", progress)

    n = len([1 for s, _ in events if s == "streaming"])
    # 200 chars / 48 per flush = 4 interim flushes + 1 final
    assert n == 5, f"expected 5 streaming events, got {n}"


def test_list_shaped_content_blocks_are_joined(streaming_on):
    llm = _StreamingLLM([[{"type": "text", "text": "Total: "}], ["$1", {"text": "00"}], ""])
    progress, _ = _listener()
    assert _answer_text(llm, "p", progress).content == "Total: $100"


def test_an_exception_mid_stream_propagates_unchanged(streaming_on):
    """The call sites' own error handling must see the same exception it always did."""

    class _Boom(_StreamingLLM):
        def stream(self, prompt):
            yield _FakeChunk("partial ")
            raise RuntimeError("upstream 503")

    progress, events = _listener()
    with pytest.raises(RuntimeError, match="upstream 503"):
        _answer_text(_Boom([]), "p", progress)


# ---------------------------------------------------------------------------
# When it must NOT stream — each of the three conditions alone is enough
# ---------------------------------------------------------------------------


def test_flag_off_invokes_and_emits_nothing(streaming_off):
    llm = _StreamingLLM(["a", "b"])
    progress, events = _listener()
    res = _answer_text(llm, "p", progress)
    assert res.content == "ab"
    assert llm.invoked == 1 and llm.streamed == 0
    assert events == []


def test_no_listener_invokes_even_with_the_flag_on(streaming_on):
    """The synchronous HTTP path: `on_progress` is None, so streaming has no reader."""
    llm = _StreamingLLM(["a", "b"])
    progress = _progress_emitter(None)
    res = _answer_text(llm, "p", progress)
    assert res.content == "ab"
    assert llm.invoked == 1 and llm.streamed == 0


def test_a_model_without_stream_invokes(streaming_on):
    """Mocks and recording LLMs in the test suite never grow a `.stream`."""
    llm = _InvokeOnlyLLM("mocked")
    progress, events = _listener()
    res = _answer_text(llm, "p", progress)
    assert res.content == "mocked"
    assert llm.invoked == 1
    assert events == []


def test_the_emitter_advertises_whether_anyone_is_listening():
    assert _progress_emitter(None).enabled is False
    assert _progress_emitter(lambda s, d: None).enabled is True


def test_content_text_handles_every_provider_shape():
    assert _content_text("x") == "x"
    assert _content_text(None) == ""
    assert _content_text(["a", {"text": "b"}, {"type": "image"}]) == "ab"
    assert _content_text(42) == "42"


# ---------------------------------------------------------------------------
# The four sites, and nothing else
# ---------------------------------------------------------------------------


def test_exactly_the_four_phrasing_sites_stream_and_generation_does_not():
    import inspect

    src = inspect.getsource(query_agent)
    assert src.count("_answer_text(llm, system_prompt, progress)") == 2, "the two F26 narrations"
    assert "_answer_text(fast_llm, summary_prompt, progress)" in src, "chat.sql_summary"
    assert '_answer_text(fast_llm, f"{system_prompt}\\nUser Query: {wrapped_user_message}", progress)' in src, "chat.rag_answer"
    # SQL generation is structured output and must never go through here.
    loop_src = inspect.getsource(query_agent.run_sql_generation_loop)
    assert "_answer_text(" not in loop_src
    assert "with_structured_output" in loop_src


def test_build_llm_asks_azure_to_report_usage_on_streamed_calls():
    """Without this every streamed call logs tokens_in=0 and B1's cached/reasoning
    counts go dark on exactly the calls A1/A2/A4 are measured by."""
    from utils import llm as llm_module

    captured = {}

    class _FakeAzure:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    with patch.object(llm_module, "AzureChatOpenAI", _FakeAzure), \
         patch.object(config.settings, "AZURE_OPENAI_API_KEY", "real-looking-key"), \
         patch.object(config.settings, "LLM_PROVIDER", "azure"):
        llm_module.build_llm("azure", model="gpt-4o")

    assert captured.get("stream_usage") is True
