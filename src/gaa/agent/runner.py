"""Adapter between the LangGraph agent and the Discord bot.

`summarize_messages` is pure and unit-tested; `answer` is the thin live call.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage


def _extract_text(content) -> str:
    """Flatten LangChain message content (str or list of blocks) to text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "".join(parts)
    return str(content or "")


def summarize_messages(messages: list) -> dict:
    """Extract the final answer text + the tool names invoked along the way. Pure."""
    tools_used: list[str] = []
    final_text = ""
    for msg in messages:
        if isinstance(msg, AIMessage):
            for call in getattr(msg, "tool_calls", None) or []:
                name = call.get("name") if isinstance(call, dict) else getattr(call, "name", None)
                if name and name not in tools_used:
                    tools_used.append(name)
            text = _extract_text(msg.content)
            if text.strip():
                final_text = text
    return {"text": final_text.strip(), "tools": tools_used}


async def answer(agent, thread_id: str, query: str, max_steps: int = 16) -> dict:  # pragma: no cover - live call
    """Run the agent to completion and return {text, tools}.

    ``max_steps`` is the LangGraph recursion limit — a hard cap on tool/LLM rounds so
    the loop can't consume tokens unboundedly. On hitting it we stop gracefully.
    """
    from langgraph.errors import GraphRecursionError

    try:
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": query}]},
            config={"configurable": {"thread_id": thread_id}, "recursion_limit": max_steps},
        )
        return summarize_messages(result["messages"])
    except GraphRecursionError:
        return {
            "text": "⚠ I reached my step limit before finishing — try a narrower question "
            "(e.g. a specific dashboard/panel or metric).",
            "tools": [],
        }
