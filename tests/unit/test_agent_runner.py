"""Tests for the pure agent-result summarizer."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from gaa.agent.runner import summarize_messages


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
