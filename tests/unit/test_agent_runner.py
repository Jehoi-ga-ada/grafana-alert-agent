"""Tests for the pure agent-result summarizer."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from gaa.agent.graph import tool_error_message
from gaa.agent.runner import summarize_messages, unanswered_tool_messages


def test_extracts_final_text_and_tools():
    messages = [
        HumanMessage(content="is the app up?"),
        AIMessage(content="", tool_calls=[{"name": "query_prometheus", "args": {"promql": "up"}, "id": "1"}]),
        AIMessage(content="Yes — all instances report up=1."),
    ]
    result = summarize_messages(messages)
    assert result["text"] == "Yes — all instances report up=1."
    assert result["tools"] == ["query_prometheus"]


def test_handles_list_content_blocks():
    messages = [AIMessage(content=[{"type": "text", "text": "hello "}, {"type": "text", "text": "world"}])]
    assert summarize_messages(messages)["text"] == "hello world"


def test_dedupes_tool_names_in_order():
    messages = [
        AIMessage(content="", tool_calls=[{"name": "query_prometheus", "args": {}, "id": "1"}]),
        AIMessage(content="", tool_calls=[{"name": "query_loki_logs", "args": {}, "id": "2"}]),
        AIMessage(content="", tool_calls=[{"name": "query_prometheus", "args": {}, "id": "3"}]),
        AIMessage(content="done"),
    ]
    result = summarize_messages(messages)
    assert result["tools"] == ["query_prometheus", "query_loki_logs"]
    assert result["text"] == "done"


def test_empty_when_no_ai_text():
    assert summarize_messages([HumanMessage(content="hi")])["text"] == ""


def test_backfills_dangling_tool_call():
    # Arrange — a run interrupted right after the model asked for query_prometheus,
    # before any ToolMessage answered it (the poisoned-thread scenario).
    messages = [
        HumanMessage(content="why is the app slow?"),
        AIMessage(content="", tool_calls=[{"name": "query_prometheus", "args": {}, "id": "abc"}]),
    ]
    # Act
    repairs = unanswered_tool_messages(messages)
    # Assert
    assert len(repairs) == 1
    assert repairs[0].tool_call_id == "abc"
    assert isinstance(repairs[0], ToolMessage)


def test_no_repairs_when_all_tool_calls_answered():
    messages = [
        AIMessage(content="", tool_calls=[{"name": "query_prometheus", "args": {}, "id": "abc"}]),
        ToolMessage(content="up=1", tool_call_id="abc"),
        AIMessage(content="all good"),
    ]
    assert unanswered_tool_messages(messages) == []


def test_backfills_only_the_unanswered_calls():
    messages = [
        AIMessage(content="", tool_calls=[{"name": "query_prometheus", "args": {}, "id": "1"}]),
        ToolMessage(content="ok", tool_call_id="1"),
        AIMessage(content="", tool_calls=[{"name": "query_loki_logs", "args": {}, "id": "2"}]),
    ]
    repairs = unanswered_tool_messages(messages)
    assert [r.tool_call_id for r in repairs] == ["2"]


def test_tool_error_message_is_recoverable_text():
    msg = tool_error_message(Exception("API request returned status code 404: Plugin not found"))
    assert "404" in msg
    assert "Plugin not found" in msg
    # Must steer the agent to keep going, not retry the dead tool.
    assert "retry" in msg.lower()
