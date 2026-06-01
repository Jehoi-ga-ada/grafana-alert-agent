"""Build the LangGraph ReAct agent."""

from __future__ import annotations


def build_chat_agent(model, tools: list, system: str, checkpointer=None):  # pragma: no cover
    """Wire a tool-calling ReAct agent with optional per-thread memory."""
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.prebuilt import create_react_agent

    return create_react_agent(
        model,
        tools,
        prompt=system,
        checkpointer=checkpointer if checkpointer is not None else MemorySaver(),
    )
