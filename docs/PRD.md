# PRD — Grafana Alert Agent

## Summary
An AI on-call assistant for the **url-shortener** stack. It polls the private-subnet
Grafana/VictoriaMetrics stack over the operator's OpenVPN tunnel, evaluates PromQL alert
rules, and when something breaks it posts a **rich Discord alert** with a **Grafana panel
screenshot** and a **Claude-generated root-cause explanation + concrete remediation steps**.
It also exposes a **web console** with an incident feed, incident detail, and a **read-only
chat agent** for ad-hoc investigation.

The agent is **strictly read-only** against infrastructure: it never restarts services, runs
SSM, or mutates Grafana. The only outbound writes are the Discord webhook and the Claude API.

## Problem
The stack already collects metrics, logs, and traces, but has **no alerting and no notifier**.
Detection and triage depend on a human watching dashboards. When Postgres dies or latency
spikes, nobody is told, and time-to-resolution suffers.

## Goals & success metrics
- **Time-to-notify** < 1 poll interval (default 30s) + pipeline (~15–30s) once a condition holds.
- Every alert includes a **screenshot**, a **plain-language explanation**, and **≥1 actionable step**.
- **Zero false-resolves** during a backend outage (absence of data ≠ healthy).
- **≤ 1 Discord message** per incident per cooldown window (no flapping spam).

## Users
- **Primary:** the operator / on-call engineer.
- **Secondary:** teammates reading the Discord channel and the web console.

## Scope (v1)
- Local poll over VPN; PromQL rule evaluation with for-duration + severity.
- Loki log + correlated-metric enrichment.
- Claude explanation + remediation (graceful fallback when no API key / API error).
- Playwright panel screenshot (best-effort).
- Discord embed with screenshot.
- Firing / resolved / cooldown state; SQLite incident history; self-heartbeat.
- FastAPI backend + React web console; read-only chat agent (SSE).

## Out of scope (v1)
- Auto-remediation / SSM actions (deliberately excluded to keep the agent read-only).
- Webhook-push mode (the core supports it; not wired in v1).
- Multi-channel routing (PagerDuty/Slack), anomaly/baseline detection, trace drill-down.

## Functional requirements
| ID | Requirement |
|----|-------------|
| FR1 | Gate every poll on Grafana reachability; never fire/resolve when the source is unreachable. |
| FR2 | Evaluate each rule via instant PromQL through the Grafana datasource proxy; apply threshold + `for`. |
| FR3 | On a new firing, capture the rule's panel screenshot for the firing time window. |
| FR4 | Enrich with correlated PromQL + Loki logs for the affected window. |
| FR5 | Analyze with Claude → summary, likely cause, remediation steps, severity, confidence. |
| FR6 | Post a Discord embed (severity colour, summary, cause, steps, deep links) + screenshot. |
| FR7 | Track state; send a resolved embed when the alert clears; enforce per-rule cooldown. |
| FR8 | Degrade gracefully — screenshot/Loki/Claude failures attach a note but still notify. |
| FR9 | Heartbeat / liveness so a dead agent is noticeable. |

## Non-functional
- Secrets only via env / `.env` (gitignored).
- TLS verified via the internal CA (`~/myca/ca.crt`); insecure-skip is an opt-in toggle.
- Immutable domain core; small focused modules; ≥80% test coverage (currently ~88%).

## "Resolve-fast" features
1. **Root-cause correlation** — each rule declares correlated metrics/logs so Claude sees the cause.
2. **Remediation playbook** — known failure modes + real fix commands fed to Claude for specific advice.
3. **Right-panel, right-window screenshot** — the image shows exactly the spike that fired.
4. **Severity + confidence scoring** — colour-coded, with the AI's own confidence.
5. **Deep links** — straight to the panel at the firing time range.
6. **Incident history + recurrence** — "fired N times recently" context (SQLite).
7. **Read-only chat agent** — ask questions; it queries live metrics/logs/incidents to answer.

## Architecture (verified against the live environment)
- Grafana **v13.0.1** at `https://grafana10.private.devopsinstitute.id`, reachable only via the
  operator's OpenVPN tunnel (OpenVPN Connect). The agent **detects** the tunnel; it does not manage it.
- VictoriaMetrics `:8428` and Loki are **firewalled** from the VPN client, so the agent queries both
  through the **Grafana datasource proxy** on `:443` with a Viewer service-account token.
- Metrics confirmed live: `up{job="url-shortener"}`, `http_requests_total{status_code}`,
  `http_request_duration_seconds{quantile}`, `http_requests_in_flight`, `go_goroutines`,
  `process_resident_memory_bytes`, and node_exporter series.
