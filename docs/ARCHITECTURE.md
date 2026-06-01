# How the Grafana Alert Agent works

An AI on-call agent that watches a Grafana / VictoriaMetrics stack (over VPN,
read-only) and talks to humans on Discord. It does two jobs:

1. **Autonomous alerting** — a daemon polls metrics on a schedule, evaluates alert
   rules, and when something fires it enriches the event, asks Claude for a
   root-cause analysis, screenshots the relevant Grafana panel, and posts an
   incident to a Discord thread.
2. **Conversational investigation** — a Discord bot where you can chat with a
   LangGraph agent that queries Prometheus/Loki, inspects dashboards, captures
   screenshots, and reasons about incidents on demand.

Everything is **read-only** against Grafana by design.

---

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.13 | async-first |
| Config | `pydantic` + `pydantic-settings` | schema-validated settings from `.env` |
| HTTP | `httpx` (async) | Grafana datasource-proxy queries, Discord webhooks |
| Agent runtime | `langgraph` (ReAct) + `langchain-core` | tool-calling loop with per-thread memory |
| LLM | AWS Bedrock via `langchain-aws` (Claude) | analysis + chat (Bedrock bearer key) |
| Tool servers | `langchain-mcp-adapters` + `mcp` (mcp-grafana) | read-only Grafana MCP tools |
| Chat surface | `discord.py` (gateway) | two-way bot + one-way webhook alerts |
| Screenshots | `playwright` (headless Chromium) | render real Grafana panels to PNG |
| Storage | SQLite (stdlib, WAL) | incident history + alert state machine |
| Tests | `pytest`, `pytest-asyncio`, `respx` | unit + integration; ~88% coverage |

Entry point: the `gaa` CLI (`gaa.cli:main`) exposes `check`, `once`, `daemon`, and
`bot` subcommands.

---

## High-level architecture

```
                        ┌─────────────────────────────────────────────┐
                        │           Grafana (read-only, VPN)           │
                        │  datasource proxy → VictoriaMetrics / Loki   │
                        └───────▲───────────────▲───────────────▲──────┘
                                │ httpx         │ httpx         │ headless
                                │ (metrics)     │ (logs)        │ browser (PNG)
            ┌───────────────────┴───┐   ┌───────┴────────┐   ┌──┴──────────────┐
            │  MetricsClient /       │   │   LogsClient   │   │ PlaywrightCapturer│
            │  GrafanaClient         │   │                │   │  (d-solo render) │
            └───────────┬────────────┘   └───────┬────────┘   └──┬──────────────┘
                        │                         │              │
        ┌───────────────┴─────────────────────────┴──────────────┴───────────────┐
        │                         gaa.bootstrap.Core (DI root)                    │
        └───────┬───────────────────────────────────────────────┬────────────────┘
                │                                                 │
   ┌────────────┴─────────────┐                    ┌──────────────┴────────────────┐
   │  Orchestrator (daemon)   │                    │     Discord bot (gateway)      │
   │  poll → evaluate → enrich│                    │  chat / !investigate / !shot   │
   │  → analyze (Claude)      │                    │  → LangGraph ReAct agent       │
   │  → notify (thread+PNG)   │                    │  → MCP + local + capture tools │
   └────────────┬─────────────┘                    └──────────────┬────────────────┘
                │                                                  │
                └──────────────► SQLite incident store ◄───────────┘
                                 (history, rule state, dedup)
```

The two modes share one object graph built by `build_core()` (`bootstrap.py`) — the
HTTP clients, rule set, SQLite store, Claude analyzer, etc. The MCP subprocess and the
LangGraph agents are built separately in the `bot` command so the deterministic daemon
never depends on the LLM/MCP being available.

---

## Mode 1 — Autonomous alerting pipeline

Run with `gaa daemon`. The loop (`orchestrator/daemon.py` + `pipeline.py`):

1. **Poll** — every `GAA_POLL_INTERVAL_SECONDS`, query each rule's PromQL via the
   Grafana datasource proxy (`MetricsClient`).
2. **Evaluate** — the pure rule-evaluation logic (`domain/evaluation.py`) compares the
   value to the threshold and advances a small per-rule **state machine**
   (`ok → pending → firing → resolved`), persisted in SQLite (`rule_state`). Dedup +
   cooldown prevent duplicate notifications.
3. **Enrich** — on a firing transition, gather supporting context (related metrics +
   recent Loki log lines) via `enrichment/`.
4. **Analyze** — hand the firing event + context to Claude (`analyzer/claude.py`),
   which returns a structured summary: likely cause, evidence, remediation,
   confidence.
5. **Screenshot** — render the relevant panel/dashboard to a PNG (see below).
6. **Notify** — post a rich Discord embed with the PNG attached to a **per-incident
   thread** (`notify/gateway.py`, `notify/embed.py`), and record the incident in
   SQLite. Replies in that thread are later routed back to the agent with the
   incident's context.

There are also scheduled side-tasks: an **anomaly sweep** (`anomaly/`) and an optional
**daily digest** (`digest.py`).

---

## Mode 2 — Conversational agent (Discord bot)

Run with `gaa bot`. A `discord.py` gateway client (`discord_bot/bot.py`) handles:

- **`!help`, `!incidents`, `!status`, `!anomalies`, `!dashboards`, `!panels`** —
  deterministic commands answered directly from the store / clients (no LLM).
- **`!shot`** — direct screenshot capture via Playwright.
- **`!compare`** — current-vs-baseline metric comparison.
- **`!investigate <id>` / `!report <id>`** — kick off the LangGraph agent on an
  incident.
- **Free-form chat / replies in an incident thread** — routed to the LangGraph agent.

### The agent itself

Built in `agent/graph.py` with LangGraph's `create_react_agent`:

- **Model** — Claude on Bedrock (`agent/model.py`), system prompt from `agent/prompt.py`.
- **Tools** (three sources, merged):
  - **MCP Grafana tools** (`agent/mcp.py`) — `query_prometheus`, `query_loki_logs`,
    `get_dashboard_by_uid`, label/metric listing, Sift, etc. Served by the official
    `mcp-grafana` binary launched as a stdio subprocess. **Read-only is enforced three
    ways**: the server runs with `-disable-write`, the Grafana token is Viewer-scoped,
    and a fail-closed Python allowlist drops any non-whitelisted tool.
  - **Local tools** (`agent/local_tools.py`) — incident history from SQLite
    (`list_incidents`, `get_incident`) and dashboard discovery (`list_dashboards`,
    `list_dashboard_panels`).
  - **Capture tools** (`agent/capture_tool.py`) — `capture_panel` /
    `capture_dashboard` (the screenshot feature).
- **Memory** — a `MemorySaver` checkpointer keyed by `thread_id` (the Discord channel
  id, or `investigate-<id>` / `report-<id>`), so each thread keeps its conversation.
- **Bounds** — `recursion_limit = GAA_AGENT_MAX_STEPS` caps tool/LLM rounds.
- **Resilience** — tool failures are converted to recoverable `ToolMessage`s instead
  of crashing the run, and dangling tool-calls are healed before each invoke (see
  `POSTMORTEM.md` for why).

The `runner.answer()` adapter runs the agent and returns `{text, tools}`; the bot
posts the text and attaches any screenshots the agent captured.

---

## How screenshots are created and attached

This is the most interesting plumbing, because **a LangChain tool cannot return image
bytes through the LLM** — the model only sees text. The agent solves this with a
side-channel: a per-request collector bound to a `ContextVar`.

### Step 1 — Rendering the PNG (Playwright)

`PlaywrightCapturer` (`screenshot/capture.py`) drives a headless Chromium that's
launched once and reused (`screenshot/browser.py`):

- The browser context authenticates every page load with the Grafana
  **service-account token** as an `Authorization: Bearer …` header — so there's **no
  login form** to automate. `ignore_https_errors=True` tolerates the internal CA.
- For a single panel it navigates to Grafana's **`d-solo`** URL (one isolated panel),
  built by `clients/links.dsolo_url(...)` with the dashboard uid/slug, panel id, time
  window, and theme. For a whole dashboard it uses the normal dashboard URL with
  `full_page=True`.
- It waits for `networkidle`, waits for a panel-content selector
  (`canvas, .panel-content, …`), lets the chart settle, **hides Grafana's nav/header
  and dismisses any modal/backdrop** via injected CSS (`_HIDE_CHROME_CSS`) for a clean
  shot, then calls `page.screenshot(type="png")` and returns the **raw PNG bytes**.
- If anything fails (panel not readable by the Viewer token, wrong id, timeout) it
  returns `None` rather than throwing. When screenshots are disabled, a `NullCapturer`
  returns `None` for everything.

### Step 2 — The agent stashes the PNG (ContextVar side-channel)

When the model calls `capture_panel`, the tool (`agent/capture_tool.py`):

1. calls `capturer.capture_panel(...)` → gets PNG bytes (or `None`),
2. fetches the **current** `ScreenshotCollector` via `get_collector()`
   (`agent/screenshots.py`),
3. `collector.add("<uid>-panel<id>.png", png)` to stash the bytes,
4. returns a **text** result to the model: *"Captured panel N; image attached to the
   reply."*

The collector is a tiny dataclass holding `list[(filename, png_bytes)]`, bound to the
request through a `ContextVar`. ContextVars propagate across the agent's async tasks,
so the once-built agent still sees the *per-message* collector.

### Step 3 — The bot drains and attaches to Discord

In `discord_bot/bot.py`, `_run_agent()` wraps each agent run:

```python
collector = ScreenshotCollector()
token = set_collector(collector)          # bind to this request's context
try:
    result = await answer(agent, thread_id, query, max_steps=...)
finally:
    reset_collector(token)                # always unbind
return result, collector.drain()          # (text+tools, [(name, png), ...])
```

Then `_post_agent_result()` turns the drained bytes into Discord attachments:

```python
files = [discord.File(io.BytesIO(png), filename=name) for name, png in images][:10]
# message text is chunked; the images are attached to the final chunk
await message.channel.send(chunk, files=files)
```

So the data flow for an attached screenshot is:

```
model: "call capture_panel(uid, id)"
        │
        ▼
capture_panel tool ── Playwright ──► PNG bytes
        │                              │
        │ returns TEXT to the model    └─► collector.add(name, png)   (ContextVar)
        ▼                                          │
agent finishes, returns text  ◄────────────────────┘
        │
bot: collector.drain() ──► [discord.File(...)] ──► channel.send(text, files=...)
```

The daemon path is simpler: it captures the panel directly and passes the PNG to
`Notifier.send(embed=..., image_png=...)`, which attaches it to the incident embed —
no collector needed, because there's no LLM tool indirection.

---

## State & storage

- **SQLite** (`state/sqlite_store.py`, WAL) is the single persistent store:
  `incidents` (history, AI analysis, `thread_id` mapping, screenshot BLOB),
  `rule_state` (per-rule alert state machine + dedup/cooldown), `anomaly_state`.
- **Conversation memory** is the in-RAM `MemorySaver` — **not** persisted to disk and
  cleared on restart. (It is unrelated to `state.db`.)

---

## Configuration & security posture

- All config comes from `Settings` (`GAA_`-prefixed env vars / gitignored `.env`),
  schema-validated and frozen. Secrets (Grafana token, Bedrock key, Discord token,
  LangSmith key) live only in `.env`.
- **Read-only by construction**: Viewer-scoped Grafana token, `mcp-grafana
  -disable-write`, and the fail-closed tool allowlist.
- **Network**: Grafana is reached over VPN; metrics/logs go through Grafana's
  datasource proxy via `httpx` (verifying the internal CA), while the screenshot
  browser tolerates the CA at the context level.
- **Observability**: optional LangSmith tracing (`GAA_LANGSMITH_*`), off by default and
  fail-safe.

---

## Where things live

| Area | Module |
|---|---|
| CLI / commands | `gaa/cli.py`, `gaa/__main__.py` |
| DI composition root | `gaa/bootstrap.py` |
| Settings | `gaa/config/settings.py` |
| Grafana / metrics / logs clients | `gaa/clients/` |
| Alert rules + evaluation | `gaa/config/`, `gaa/domain/` |
| Daemon pipeline | `gaa/orchestrator/` |
| Enrichment + analysis | `gaa/enrichment/`, `gaa/analyzer/` |
| Anomaly detection / digest | `gaa/anomaly/`, `gaa/digest.py` |
| LangGraph agent | `gaa/agent/` |
| Screenshots | `gaa/screenshot/`, `gaa/agent/capture_tool.py`, `gaa/agent/screenshots.py` |
| Discord bot + notifications | `gaa/discord_bot/`, `gaa/notify/` |
| Persistence | `gaa/state/` |

See also `docs/PRD.md` (product requirements) and `docs/POSTMORTEM.md` (the tool-error
incident and fixes).
