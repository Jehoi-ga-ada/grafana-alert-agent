"""Build the LangGraph ReAct agent."""

from __future__ import annotations


def tool_error_message(exc: Exception) -> str:
    """Turn any tool failure into text the agent can read and recover from.

    Without this, an exception raised inside a tool (e.g. a Grafana Sift call
    hitting a 404 "Plugin not found" when the plugin isn't installed) propagates
    out of the tools node and crashes the whole run — *after* the model's
    tool-call has been checkpointed but *before* a ToolMessage answers it. That
    leaves a dangling tool-call in per-thread memory that poisons every later
    turn ("tool_calls without a corresponding ToolMessage"). Returning a string
    here makes the tools node emit an error ToolMessage instead, so one broken
    tool degrades gracefully.

    The ``Exception`` annotation tells ToolNode to route *all* tool exceptions
    here (GraphInterrupt/GraphBubbleUp still propagate, by design).
    """
    return (
        f"This tool call failed and returned no data ({exc}). "
        "Do not retry it. Continue with the other available tools, and if this "
        "prevents a complete answer, say so plainly."
    )


def build_chat_agent(model, tools: list, system: str, checkpointer=None):  # pragma: no cover
    """Wire a tool-calling ReAct agent with optional per-thread memory.

    Tools run inside a ToolNode configured to convert any tool error into an
    error ToolMessage (see ``tool_error_message``) rather than crashing the run.
    """
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.prebuilt import create_react_agent
    from langgraph.prebuilt.tool_node import ToolNode

    tool_node = ToolNode(tools, handle_tool_errors=tool_error_message)
    return create_react_agent(
        model,
        tool_node,
        prompt=system,
        checkpointer=checkpointer if checkpointer is not None else MemorySaver(),
    )
