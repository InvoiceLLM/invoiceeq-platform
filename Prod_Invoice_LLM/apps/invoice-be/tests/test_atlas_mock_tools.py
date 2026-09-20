"""Feature 35 task 35.2 — `MockInvoiceLLM.bind_tools()`'s scripted tool calls.

Spec: `docs/feature_35_atlas_intelligence.md` §2 (the `utils/llm.py` row), §6
(task 35.2's proof).

No database and no Azure: what is under test is the *shape* the mock returns,
because task 35.4's loop reads `.tool_calls`, `.content` and `.usage_metadata`
off a real `AIMessage` and must not need a branch for the mock. The tests
therefore assert against LangChain's own class, not against a stand-in — if the
mock ever stopped producing a genuine `AIMessage`, a loop that passed here would
still fail against Azure, which is the failure this file exists to prevent.

A small hand-rolled loop stands in for task 35.4's, deliberately: it is the
*consumer contract* being pinned (call, dispatch, feed results back, stop when
the model writes), and pinning it before the real loop exists is what makes
35.4 a loop someone can write against a known-good fake.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

from services.atlas_capabilities import GrantSet
from services.atlas_tools import tool_schemas
from utils.llm import MockInvoiceLLM

TRAINER = GrantSet(can_train=True)
ADMIN = GrantSet(can_audit=True, can_train=True, can_load=True, is_admin=True)


def test_bind_tools_returns_a_bound_model_carrying_the_schemas():
    llm = MockInvoiceLLM()
    schemas = tool_schemas(ADMIN)
    bound = llm.bind_tools(schemas)
    assert bound.tools == schemas
    assert bound.invocations == 0


def test_a_scripted_round_returns_a_real_aimessage_with_tool_calls():
    """The shape 35.4's loop reads. `AIMessage`, not a look-alike."""
    llm = MockInvoiceLLM()
    bound = llm.bind_tools(
        tool_schemas(ADMIN),
        script=[[{"name": "list_lines", "args": {}, "id": "call_1"}], "the briefing"],
    )

    first = bound.invoke([("system", "brief me")])
    assert isinstance(first, AIMessage)
    assert first.content == ""
    assert [c["name"] for c in first.tool_calls] == ["list_lines"]
    assert first.tool_calls[0]["id"] == "call_1"
    assert first.tool_calls[0]["args"] == {}

    second = bound.invoke([("system", "brief me")])
    assert isinstance(second, AIMessage)
    assert second.tool_calls == []
    assert second.content == "the briefing"


def test_an_id_is_generated_when_the_script_omits_one():
    """A tool call with no id cannot be matched to its ToolMessage."""
    llm = MockInvoiceLLM()
    bound = llm.bind_tools([], script=[[{"name": "orientation", "args": {}}]])
    call = bound.invoke([]).tool_calls[0]
    assert call["id"]
    assert call["type"] == "tool_call"


def test_an_exhausted_script_terminates_rather_than_looping():
    """An empty or spent script must stop the loop, not feed it another call.

    If exhaustion produced another tool call, an off-by-one in 35.4's cap would
    be invisible: the loop would run forever and the test would time out instead
    of failing on the cap.
    """
    llm = MockInvoiceLLM()
    bound = llm.bind_tools([], script=[])
    for _ in range(3):
        message = bound.invoke([])
        assert message.tool_calls == []
        assert message.content == MockInvoiceLLM.SCRIPT_EXHAUSTED_TEXT


def test_the_script_can_be_set_on_the_class_or_the_instance(monkeypatch):
    """A route builds the model deep inside itself; a test must still script it."""
    monkeypatch.setattr(
        MockInvoiceLLM, "tool_script", [[{"name": "memory_rules", "args": {}}], "done"]
    )
    class_scripted = MockInvoiceLLM().bind_tools([])
    assert [c["name"] for c in class_scripted.invoke([]).tool_calls] == ["memory_rules"]

    instance = MockInvoiceLLM(tool_script=[[{"name": "orientation", "args": {}}]])
    assert [c["name"] for c in instance.bind_tools([]).invoke([]).tool_calls] == [
        "orientation"
    ]
    # The per-bind script is the most specific and wins over both.
    per_bind = instance.bind_tools([], script=["straight to prose"])
    assert per_bind.invoke([]).content == "straight to prose"


def test_every_invocation_is_recorded_in_order():
    """35.2's proof: a test can assert the loop's dispatch order."""
    llm = MockInvoiceLLM()
    bound = llm.bind_tools(
        [],
        script=[
            [{"name": "list_lines", "args": {}}],
            [{"name": "cash_position", "args": {}}, {"name": "forecast", "args": {}}],
            "the briefing",
        ],
    )
    dispatched: list[str] = []
    messages: list = [("system", "brief me")]

    for _ in range(5):
        message = bound.invoke(messages)
        if not message.tool_calls:
            break
        for call in message.tool_calls:
            dispatched.append(call["name"])
            messages.append(("tool", call["name"]))

    assert dispatched == ["list_lines", "cash_position", "forecast"]
    assert bound.invocations == 3
    # The loop fed its tool results back: the last call saw more messages than
    # the first, which is what distinguishes a loop from three lone calls.
    assert len(bound.calls[-1]) > len(bound.calls[0])


def test_usage_metadata_is_present_so_the_loop_can_count_tokens():
    bound = MockInvoiceLLM().bind_tools([], script=["text"])
    usage = bound.invoke([]).usage_metadata
    assert set(usage) >= {"input_tokens", "output_tokens", "total_tokens"}


def test_a_trainers_bound_model_is_never_given_the_admin_tools():
    """The two halves of task 35.1 and 35.2 meeting: the mock binds what it is given."""
    bound = MockInvoiceLLM().bind_tools(tool_schemas(TRAINER))
    names = {s["function"]["name"] for s in bound.tools}
    assert "cash_position" not in names and "forecast" not in names


def test_the_plain_mock_still_answers_prompts_unchanged():
    """35.2 is additive: nothing about the existing `invoke()` moved."""
    reply = MockInvoiceLLM().invoke("hello there")
    assert "SAGE" in reply.content
