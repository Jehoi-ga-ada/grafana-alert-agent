# Postmortem — Agent crashes & poisoned conversation memory (2026-06-01)

## Summary

The Discord chat/investigate agent began throwing two recurring errors:

1. `ToolException: ... API request returned status code 404: {"message":"Plugin not found"}`
2. `Found AIMessages with tool_calls that do not have a corresponding ToolMessage`

Both were ultimately **one chain of cause and effect**: a Grafana Sift tool had no
backend (404), the failure crashed the agent run mid-tool, and that crash left a
"dangling" tool-call in per-thread memory that poisoned every subsequent message in
the same thread until the bot was restarted.

We fixed it by making tool failures degrade gracefully instead of crashing, and by
healing any dangling tool-call before each run. We also (separately) wired LangSmith
tracing for observability.

---

## What broke, in order

### Symptom 1 — `Found AIMessages with tool_calls that do not have a corresponding ToolMessage`

The provider (Bedrock/Anthropic, via LangChain) enforces an invariant: **every
`AIMessage` that requests a tool must be followed by a `ToolMessage` answering that
exact `tool_call_id`.** The agent was sending conversation history where a
`query_prometheus` call had no answer, so the request was rejected before the model
ever ran.

### Symptom 2 — `404 {"message":"Plugin not found"}` from Sift tools

The agent's MCP toolset included Grafana **Sift** tools (`find_error_pattern_logs`,
`find_slow_requests`, `list_sift_investigations`, …). Sift is served by the Grafana
Machine Learning app (`grafana-ml-app`), which **is not installed** on the
self-hosted Grafana instance. Every Sift call returned `404 Plugin not found`.

### The link between them

These were not two bugs — Symptom 2 *caused* Symptom 1:

1. The model emits a tool call (e.g. a Sift tool, or `query_prometheus`). LangGraph
   checkpoints that step into the thread's memory.
2. The tools node runs the call. The Sift tool raises a `ToolException` (the 404).
3. LangGraph's **default** tool-error handler (`_default_handle_tool_errors`) only
   swallows `ToolInvocationError` and **re-raises everything else** — including this
   `ToolException`. The exception propagated and **crashed the whole run**.
4. The crash happened *after* the tool-call was checkpointed but *before* a
   `ToolMessage` answered it → the saved thread state now ends with a **dangling
   tool-call**.
5. On the **next** message in that thread, the agent replays the poisoned history →
   the provider rejects it (Symptom 1). The bot's handler caught the exception and
   echoed `⚠ error: ...` to Discord.

It was also self-reinforcing: once a thread was poisoned, *every* later message in it
failed identically until the process restarted (memory is in-RAM — see below).

---

## Why the problem happened (root causes)

1. **A failing tool crashed the run instead of being reported to the model.**
   `create_react_agent`, given a plain tool list, builds a `ToolNode` whose default
   error handler re-raises any non-`ToolInvocationError`. So a remote 404 inside a
   tool became a fatal, run-ending exception.

2. **Conversation memory persisted the crash.** The agents use a `MemorySaver`
   checkpointer keyed by `thread_id` (the Discord channel id, or `investigate-<id>` /
   `report-<id>`). It lives in process RAM and is reused across messages. So a
   half-finished, invalid turn was saved and replayed on the next message — and only
   a bot restart cleared it.

3. **A second, independent path could also poison a thread:** hitting the LangGraph
   recursion limit (`recursion_limit = agent_max_steps`) right after the model emitted
   a tool-call, or an `asyncio` cancellation mid-tool, leaves the same dangling
   tool-call — without any tool error at all.

4. **Sift was enabled against a Grafana that doesn't have it.** `GAA_ALLOW_SIFT`
   defaults to on, but the instance has no `grafana-ml-app` plugin, guaranteeing 404s.

---

## A detour worth recording

Mid-investigation, `state.db` was deleted in the hope it would clear the error. It did
**not** — `state.db` is the SQLite **incident store** (incident history, rule
state-machine, anomaly dedup), completely unrelated to the agent's conversation
memory, which is the in-RAM `MemorySaver`. The deletion:

- did not fix either error,
- wiped incident history and the incident→thread mapping,
- reset the alert dedup state (risking duplicate alert notifications on the next poll).

The file is auto-recreated empty on next start, so nothing crashed — but it was lost
data for no benefit. **Lesson: identify *which* state store is involved before
deleting anything.**

---

## How we resolved it

### Fix 1 — Tools fail soft (`src/gaa/agent/graph.py`)

Tools now run inside an explicit `ToolNode(tools, handle_tool_errors=tool_error_message)`.
`tool_error_message(exc)` converts **any** tool exception into a short, recoverable
`ToolMessage` ("this tool failed, don't retry, continue with the others"). The Sift
404 now becomes a normal tool result the model can read and route around — the run no
longer crashes, and no dangling tool-call is ever produced by a tool error.

### Fix 2 — Heal dangling tool-calls before each run (`src/gaa/agent/runner.py`)

Before every `ainvoke`, `_heal_thread` reads the thread's checkpoint and backfills a
synthetic error `ToolMessage` for any tool-call left unanswered (via the pure,
unit-tested `unanswered_tool_messages`). This covers the *other* poisoning paths
(recursion limit, cancellation) and repairs any thread already poisoned in a running
process.

### Operational lever — disable Sift if unavailable

If Grafana has no Sift backend, set `GAA_ALLOW_SIFT=false` so the agent never loads or
attempts those tools (no wasted tool-call, no log noise). To *enable* Sift instead,
the Grafana side needs the ML app — realistically a Grafana Cloud stack.

### Separately — LangSmith tracing (`src/gaa/observability.py`)

Added opt-in LangSmith tracing. Values live in `Settings` (`GAA_LANGSMITH_*`, sourced
from the gitignored `.env`); `configure_langsmith` exports the native `LANGSMITH_*`
env vars at startup so the API key never lives in source. Tracing is off by default
and fail-safe (a bad key logs a warning and is skipped; a tracing outage never breaks
the agent).

---

## Verification

- Full unit + integration suite green (`pytest`), including new tests for the
  dangling-tool-call healer, the tool-error handler, and the LangSmith wiring.
- Confirmed in production logs after the fix: the agent queries Prometheus and gets
  Bedrock responses across multiple turns with no crash and no replay error.

---

## Follow-ups / prevention

- [ ] Decide Sift: connect a Grafana Cloud stack (enables Sift) **or** set
      `GAA_ALLOW_SIFT=false` on self-hosted.
- [ ] Resolve the LangSmith `403 Forbidden` (rotate the leaked key; verify
      US-vs-EU endpoint via `GAA_LANGSMITH_ENDPOINT`).
- [ ] Consider a persistent checkpointer (e.g. SQLite saver) for thread memory — the
      healer already makes that safe by repairing dangling calls on load.
- [ ] **Rotate the LangSmith API key that was shared in plaintext.**
