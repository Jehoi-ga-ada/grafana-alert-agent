# Grafana Alert Agent (GAA)

An AI on-call assistant for the **url-shortener** stack. It polls the private-subnet
Grafana/VictoriaMetrics stack over your OpenVPN tunnel, and when a PromQL alert rule fires it
posts a **rich Discord alert** with a **Grafana panel screenshot** and a **Claude root-cause
explanation + concrete remediation steps**. You **chat with it directly in Discord** — @mention
the bot to ask questions (it queries live metrics, logs & incidents) or run `!shot <panel>` to
pull a screenshot on demand.

> **Read-only by design.** The agent never restarts services, runs SSM, or mutates Grafana.
> The only outbound writes are the Discord messages/webhook and the LLM API. Claude *suggests*
> fixes; you run them. The chat bot's tools are query-only.

## How it works

```
OpenVPN Connect (you run it)  ──►  private subnet
        │  poll every 30s, gated on Grafana reachability
        ▼
  VictoriaMetrics + Loki  (via the Grafana datasource proxy on :443, Viewer token)
        ▼
  evaluate rules (threshold + for-duration)  ─►  on firing:
        ├─ screenshot the panel (Playwright, headless Chromium, over the VPN)
        ├─ enrich with correlated metrics + Loki logs
        ├─ Claude → summary, root cause, remediation steps
        ├─ Discord embed + screenshot
        └─ record incident (SQLite)
```

VictoriaMetrics `:8428` and Loki are firewalled from the VPN client, so all queries go through
the **Grafana datasource proxy**. TLS is verified with the internal CA (`~/myca/ca.crt`).

The **chat agent** is a LangGraph ReAct agent (`ChatBedrockConverse`, your Bedrock bearer key) whose
Grafana tools come from the official **`mcp-grafana`** MCP server, plus local incident tools and a
`capture_panel` screenshot tool. It explores dashboards **dynamically** (search → inspect → query →
screenshot whatever it needs). The deterministic alert daemon stays on the HTTP clients — it never
depends on the LLM or MCP.

It also runs a **proactive anomaly sweeper** (current value vs a PromQL `offset` baseline,
edge-triggered + cooldown) and an optional **daily digest**, both posting to Discord. A **`!status`**
verdict reuses the rule engine for a point-in-time 🟢/🟡/🔴, and **`!report`** runs an agentic
multi-dashboard investigation (Sift traces/logs) with screenshots + a markdown export.

**Read-only enforcement:** mcp-grafana is launched with a category whitelist and a fail-closed Python
allowlist — only read tools + Grafana **Sift** analysis (`find_slow_requests`, `find_error_pattern_logs`,
which create harmless analysis artifacts) load; every dashboard/datasource/alert write tool is dropped.

## Setup

```bash
uv sync
uv run playwright install chromium        # for screenshots
cp config/settings.example.env .env       # then fill in secrets
```

Required env (see `config/settings.example.env`):

| Var | Purpose |
|-----|---------|
| `GAA_GRAFANA_URL` | Grafana base URL |
| `GAA_GRAFANA_SA_TOKEN` | Viewer-scoped service-account token |
| `GAA_GRAFANA_CA_CERT` | internal CA bundle (e.g. `~/myca/ca.crt`) |
| `GAA_DISCORD_WEBHOOK_URL` | Discord incoming webhook (one-way alert delivery) |
| `GAA_DISCORD_BOT_TOKEN` | Discord **bot** token (two-way chat) |
| `GAA_DISCORD_CHANNEL_ID` | channel for posting alerts + opening per-incident threads (0 = webhook only, no threads) |
| `GAA_DASHBOARD_UID` | default dashboard for screenshots (the agent can target any dashboard dynamically) |
| `GAA_ALLOW_SIFT` | `true` (default) enables Grafana Sift analysis tools |
| `GAA_SWEEP_INTERVAL_SECONDS` | anomaly sweep cadence (default 900) |
| `GAA_DIGEST_INTERVAL_SECONDS` | daily digest cadence (0 = off) |
| `GAA_ANOMALIES_PATH` | anomaly checks file (default `config/anomalies.yaml`) |

> **Dashboard permissions:** the Viewer service account may only see some dashboards. To let the
> agent explore/screenshot all of them (e.g. Overview, Traces), raise the SA role to Editor in
> Grafana → Administration → Service accounts, or grant per-dashboard/folder Viewer. Metric/log
> queries work regardless of dashboard visibility.

### Discord bot setup

1. Create an application at <https://discord.com/developers/applications> → **Bot** → copy the token.
2. Under **Bot → Privileged Gateway Intents**, enable **Message Content Intent**.
3. Invite the bot to your server (OAuth2 URL with the `bot` scope + Send Messages / Attach Files).
4. Put the token in `GAA_DISCORD_BOT_TOKEN`. Then `@mention` the bot or DM it.

### LLM provider

Defaults to **AWS Bedrock** with a bearer API key. Analysis + chat degrade gracefully if absent.

| Var | Purpose |
|-----|---------|
| `GAA_LLM_PROVIDER` | `bedrock` (default) or `anthropic` |
| `GAA_BEDROCK_REGION` | e.g. `ap-southeast-3` |
| `GAA_BEDROCK_MODEL_ID` | e.g. `global.anthropic.claude-haiku-4-5-20251001-v1:0` |
| `GAA_BEDROCK_API_KEY` | Bedrock bearer key (required for `bedrock`) |
| `GAA_ANTHROPIC_API_KEY` | direct Anthropic key (only for `anthropic`) |

Bedrock requests hit `POST https://bedrock-runtime.<region>.amazonaws.com/model/<modelId>/invoke`
with `Authorization: Bearer <key>` and `anthropic_version: bedrock-2023-05-31`.

Make sure your **OpenVPN Connect** tunnel is up first — the agent detects it but does not manage it.

## Usage

```bash
uv run gaa check              # verify VPN/Grafana/datasource + send a Discord test message
uv run gaa once --dry-run     # evaluate all rules against live metrics, no notifications
uv run gaa once               # one real tick (screenshots + notifications)
uv run gaa daemon             # continuous alert poll loop (alerts only)
uv run gaa bot                # Discord chat bot + alert poll loop (the main way to run it)
```

### Chatting with the bot

- **@mention** or **DM** the bot a question → the LangGraph agent queries Grafana (via MCP) and
  incidents to answer with real data.
- `!investigate <incident_id>` → deep agentic root-cause investigation using Tempo slow-requests +
  Loki error-pattern detection (Grafana Sift) via MCP.
- `!dashboards` → list your Grafana dashboards (uid + title).
- `!shot <panel_id> [minutes]` → screenshot a panel on the default dashboard (`GAA_DASHBOARD_UID`).
- `!shot <dashboard> <panel_id> [minutes]` → screenshot a panel on any dashboard (uid or a word from its title).
- `!incidents` → list recent incidents. `!help` → command list.

### Installing mcp-grafana (read-only Grafana MCP server)

The chat agent's Grafana tools come from the official `mcp-grafana` binary, launched as a stdio
subprocess in **read-only mode** (`--disable-write` + your Viewer token + a fail-closed allowlist).
On macOS it must run **natively** (Docker can't reach the host VPN tunnel):

```bash
# Apple Silicon example (pick your arch from the releases page):
mkdir -p .tools
curl -fsSL -o .tools/m.tgz \
  https://github.com/grafana/mcp-grafana/releases/download/v0.14.0/mcp-grafana_Darwin_arm64.tar.gz
tar -xzf .tools/m.tgz -C .tools && rm .tools/m.tgz && chmod +x .tools/mcp-grafana
```
Then set `GAA_MCP_GRAFANA_BIN=.tools/mcp-grafana` (or put it on your `PATH`). If the binary is
missing, chat still works for incident questions — only the Grafana query tools are unavailable.

## Rules

Alert rules live in [`config/rules.yaml`](config/rules.yaml) — committed, not secret. Each rule
has a PromQL `expr`, `comparator`, `threshold`, `for` duration, `severity`, optional `panel_id`
to screenshot, a `runbook` hint, and `correlations` (extra metrics/logs Claude should see).

To get **panel-accurate screenshots** for the metric rules, import the devops repo's
`url-shortener-public.json` dashboard into Grafana and set `GAA_DASHBOARD_UID` to its UID.
(Screenshots are best-effort, so this is optional.)

## Tests

```bash
uv run pytest --cov=gaa        # ~88% coverage
```

Pure domain logic (evaluation, dedup, prompt, embed, bot formatting) is unit-tested; clients use
`respx`; the pipeline/daemon/chat are integration-tested with in-memory fakes. Real browser/VPN/
Discord gateway are never exercised in the gate.

## Layout

```
src/gaa/
  config/        settings + rule models/loader
  domain/        pure value objects + evaluation + dedup
  clients/       grafana proxy, victoriametrics, loki, discord webhook, tls
  enrichment/    correlated metrics + logs
  analyzer/      RCA prompt + playbook + structured analyzer (LangChain)
  agent/         LangGraph chat agent: model, mcp (allowlist), tools, capture_tool, screenshots, graph, runner
  status/        pure point-in-time health verdict (reuses rule engine)
  anomaly/       baseline anomaly detection + proactive sweeper
  report/        incident report markdown rendering
  compare.py     metric now-vs-baseline · digest.py daily digest
  screenshot/    Playwright capturer (any dashboard)
  notify/        Discord embeds + webhook + gateway (per-incident threads)
  state/         SQLite incident + anomaly state
  orchestrator/  pipeline + daemon (HTTP only, no LLM/MCP)
  discord_bot/   gateway bot (chat, !status, !anomalies, !compare, !report, !investigate, !shot, !dashboards)
```
