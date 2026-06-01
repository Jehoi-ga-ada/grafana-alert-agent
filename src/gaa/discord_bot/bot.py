"""discord.py gateway client — conversational, read-only. (Excluded from the
coverage gate; pure logic lives in discord_bot/format.py and agent/runner.py.)

Chat + `!investigate` are powered by LangGraph agents (MCP Grafana tools + local
incident tools). `!shot` uses the Playwright capturer. Memory is per-channel via
the agent's checkpointer.
"""

from __future__ import annotations

import io
import logging
import time

import discord

from gaa.agent.runner import answer
from gaa.agent.screenshots import ScreenshotCollector, reset_collector, set_collector
from gaa.clients.protocols import Capturer
from gaa.discord_bot.format import (
    chunk_message,
    format_dashboards,
    format_help,
    format_incidents,
    parse_command,
    parse_shot,
)
from gaa.domain.models import TimeWindow
from gaa.state.store import StateStore

logger = logging.getLogger(__name__)


class AlertBot:  # pragma: no cover - exercised live, not in the gate
    def __init__(
        self,
        *,
        token: str,
        chat_agent,
        investigate_agent,
        capturer: Capturer,
        store: StateStore,
        grafana=None,
        metrics=None,
        rules: tuple = (),
        anomaly_checks: tuple = (),
        client=None,
        clock=time.time,
        channel_id: int = 0,
        agent_max_steps: int = 16,
    ) -> None:
        self._token = token
        self._chat_agent = chat_agent
        self._investigate_agent = investigate_agent
        self._capturer = capturer
        self._store = store
        self._grafana = grafana
        self._metrics = metrics
        self._rules = rules
        self._anomaly_checks = anomaly_checks
        self._clock = clock
        self._channel_id = channel_id
        self._agent_max_steps = agent_max_steps

        if client is None:
            intents = discord.Intents.default()
            intents.message_content = True
            client = discord.Client(intents=intents)
        self.client = client
        self._register()

    def _register(self) -> None:
        @self.client.event
        async def on_ready():
            logger.info("discord bot online as %s", self.client.user)

        @self.client.event
        async def on_message(message: discord.Message):
            try:
                await self._on_message(message)
            except Exception as exc:
                logger.exception("bot handler error: %s", exc)
                await self._reply(message, f"⚠ error: {exc}")

    def _should_handle(self, message: discord.Message) -> bool:
        if message.author.bot:
            return False
        is_dm = message.guild is None
        if self._channel_id and not is_dm and message.channel.id != self._channel_id:
            return False
        mentioned = self.client.user in message.mentions
        is_command = message.content.strip().startswith("!")
        return is_dm or mentioned or is_command

    async def _on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        # In an incident thread, answer every reply with that incident's context.
        if not message.content.strip().startswith("!"):
            incident = await self._incident_for_thread(message)
            if incident is not None:
                async with message.channel.typing():
                    await self._handle_chat(message, message.content, incident=incident)
                return
        if not self._should_handle(message):
            return
        cmd = parse_command(message.content)
        async with message.channel.typing():
            if cmd.name == "help":
                await self._reply(message, format_help())
            elif cmd.name == "incidents":
                incidents = await self._store.list_incidents(10)
                await self._reply(message, format_incidents(incidents, self._clock()))
            elif cmd.name == "status":
                await self._handle_status(message)
            elif cmd.name == "anomalies":
                await self._handle_anomalies(message)
            elif cmd.name == "dashboards":
                await self._handle_dashboards(message)
            elif cmd.name == "panels":
                await self._handle_panels(message, cmd.args)
            elif cmd.name == "shot":
                await self._handle_shot(message, cmd.args)
            elif cmd.name == "investigate":
                await self._handle_investigate(message, cmd.args)
            elif cmd.name == "report":
                await self._handle_report(message, cmd.args)
            elif cmd.name == "compare":
                await self._handle_compare(message, cmd.args)
            else:
                query = cmd.text if cmd.name in (None, "ask") else message.content
                await self._handle_chat(message, query)

    async def _incident_for_thread(self, message: discord.Message):
        if not isinstance(message.channel, discord.Thread):
            return None
        return await self._store.get_incident_by_thread(str(message.channel.id))

    async def _handle_chat(self, message: discord.Message, query: str, incident=None) -> None:
        if self._chat_agent is None:
            await self._reply(message, "⚠ LLM/MCP not configured — set GAA_BEDROCK_API_KEY and mcp-grafana.")
            return
        if not query.strip():
            await self._reply(message, "Ask me about the system, or try `!help`.")
            return
        if incident is not None:
            query = (
                f"(In the context of incident #{incident.id} '{incident.title}', rule "
                f"{incident.rule_name}, likely cause: {incident.likely_cause or 'unknown'}.) {query}"
            )
        result, images = await self._run_agent(self._chat_agent, str(message.channel.id), query)
        await self._post_agent_result(message, result, images)

    async def _handle_investigate(self, message: discord.Message, args: list[str]) -> None:
        if self._investigate_agent is None:
            await self._reply(message, "⚠ investigation needs the LLM + mcp-grafana configured.")
            return
        if not args or not args[0].lstrip("#").isdigit():
            await self._reply(message, "usage: `!investigate <incident_id>`")
            return
        incident_id = int(args[0].lstrip("#"))
        incident = await self._store.get_incident(incident_id)
        if incident is None:
            await self._reply(message, f"incident {incident_id} not found.")
            return
        query = (
            f"Investigate incident #{incident_id}: '{incident.title}' (rule {incident.rule_name}, "
            f"severity {incident.severity.value}, value {incident.value}). "
            f"Prior summary: {incident.summary or 'n/a'}. Find the root cause with evidence."
        )
        await self._reply(message, f"🔬 Investigating incident #{incident_id} — querying metrics, logs & traces…")
        result, images = await self._run_agent(self._investigate_agent, f"investigate-{incident_id}", query)
        await self._post_agent_result(message, result, images)

    async def _handle_report(self, message: discord.Message, args: list[str]) -> None:
        if self._investigate_agent is None:
            await self._reply(message, "⚠ reports need the LLM + mcp-grafana configured.")
            return
        if args and args[0].lstrip("#").isdigit():
            incident = await self._store.get_incident(int(args[0].lstrip("#")))
        else:
            recent = await self._store.list_incidents(1)
            incident = recent[0] if recent else None
        if incident is None:
            await self._reply(message, "no incident to report on (give an id, or wait for an alert).")
            return

        query = (
            f"Produce a full incident report for incident #{incident.id}: '{incident.title}' "
            f"(rule {incident.rule_name}, severity {incident.severity.value}, value {incident.value}). "
            "Explore the relevant dashboards (search_dashboards then get_dashboard_by_uid), capture the "
            "most relevant panels with capture_panel, query metrics/logs (and Sift for traces/errors), "
            "then give: what happened, the root cause with evidence, and concrete remediation."
        )
        await self._reply(message, f"📋 Building report for incident #{incident.id} — this may take a moment…")
        result, images = await self._run_agent(self._investigate_agent, f"report-{incident.id}", query)

        from gaa.report.markdown import render_report_markdown

        md = render_report_markdown(incident, result.get("text", ""), result.get("tools", []))
        extra = [(f"report-{incident.id}.md", md.encode("utf-8"))]
        await self._post_agent_result(message, result, list(images) + extra)

    async def _handle_compare(self, message: discord.Message, args: list[str]) -> None:
        if self._metrics is None:
            await self._reply(message, "compare unavailable (no metrics wired).")
            return
        if not args:
            await self._reply(message, "usage: `!compare <metric>` (e.g. p99, error_rate, req_rate, memory)")
            return
        from gaa.compare import baseline_expr, compute_comparison, format_comparison, resolve_metric

        label = args[0]
        lookback = args[1] if len(args) > 1 else "1d"
        expr = resolve_metric(label)
        try:
            current = await self._metrics.query_instant(expr)
            baseline = await self._metrics.query_instant(baseline_expr(expr, lookback))
        except Exception as exc:
            await self._reply(message, f"compare failed: {exc}")
            return
        await self._reply(message, format_comparison(label, lookback, compute_comparison(current, baseline)))

    async def _run_agent(self, agent, thread_id: str, query: str) -> tuple[dict, list]:
        """Run the agent with a per-request screenshot collector; return (result, images)."""
        collector = ScreenshotCollector()
        token = set_collector(collector)
        try:
            result = await answer(agent, thread_id, query, max_steps=self._agent_max_steps)
        finally:
            reset_collector(token)
        return result, collector.drain()

    async def _post_agent_result(self, message: discord.Message, result: dict, images: list | None = None) -> None:
        text = result.get("text") or "(no response)"
        tools = result.get("tools") or []
        footer = f"\n\n_queried: {', '.join(tools)}_" if tools else ""
        files = [discord.File(io.BytesIO(png), filename=name) for name, png in (images or [])][:10]
        chunks = chunk_message(text + footer)
        for i, chunk in enumerate(chunks):
            # attach images to the final chunk
            attach = files if i == len(chunks) - 1 else None
            await message.channel.send(chunk, files=attach or [])

    async def _handle_status(self, message: discord.Message) -> None:
        if self._metrics is None or not self._rules:
            await self._reply(message, "status unavailable (no metrics/rules wired).")
            return
        from gaa.notify.embed import build_status_embed
        from gaa.orchestrator.timeutil import iso
        from gaa.status.service import gather_health

        now = self._clock()
        report = await gather_health(self._metrics, self._rules, now)
        await message.channel.send(embed=discord.Embed.from_dict(build_status_embed(report, iso(now))))

    async def _handle_anomalies(self, message: discord.Message) -> None:
        if not self._anomaly_checks or self._metrics is None:
            await self._reply(message, "no anomaly checks configured.")
            return
        from gaa.anomaly.sweep import evaluate_all

        results = await evaluate_all(self._anomaly_checks, self._metrics, self._clock())
        anomalous = [r for r in results if r.is_anomalous]
        if not anomalous:
            await self._reply(message, "✅ No anomalies — checked metrics are within baseline.")
            return
        lines = ["📈 **Anomalies detected:**"] + [f"• **{r.title}** — {r.reason}" for r in anomalous]
        await self._reply(message, "\n".join(lines))

    async def _handle_dashboards(self, message: discord.Message) -> None:
        if self._grafana is None:
            await self._reply(message, "dashboard listing unavailable.")
            return
        await self._reply(message, format_dashboards(await self._grafana.list_dashboards()))

    async def _handle_panels(self, message: discord.Message, args: list[str]) -> None:
        if self._grafana is None or not args:
            await self._reply(message, "usage: `!panels <dashboard>` (uid or a word from the title)")
            return
        match = await self._resolve_dashboard(args[0])
        if match is None:
            await self._reply(message, f"no dashboard matching `{args[0]}` — try `!dashboards`.")
            return
        uid, _ = match
        panels = await self._grafana.get_dashboard_panels(uid)
        if not panels:
            await self._reply(message, "no panels found on that dashboard.")
            return
        lines = [f"**Panels on `{uid}`** (use the id with `!shot {uid} <id>`)"]
        lines += [f"`{p['id']}` · {p['title'] or '(untitled)'} [{p['type']}]" for p in panels]
        await self._reply(message, "\n".join(lines))

    async def _resolve_dashboard(self, query: str) -> tuple[str, str] | None:
        """Match a uid or a title/slug substring to (uid, slug)."""
        if self._grafana is None:
            return None
        q = query.lower()
        for d in await self._grafana.list_dashboards():
            if d["uid"] == query or q in d["title"].lower() or q in d["slug"].lower():
                return d["uid"], d["slug"]
        return None

    async def _handle_shot(self, message: discord.Message, args: list[str]) -> None:
        req = parse_shot(args)
        if req is None:
            await self._reply(
                message,
                "usage: `!shot <panel_id> [min]` · `!shot <dashboard> <panel_id> [min]` · "
                "`!shot <dashboard> [min]` (whole dashboard)",
            )
            return

        uid = slug = None
        label = "default dashboard"
        if req.dashboard is not None:
            match = await self._resolve_dashboard(req.dashboard)
            if match is None:
                await self._reply(message, f"no dashboard matching `{req.dashboard}` — try `!dashboards`.")
                return
            uid, slug = match
            label = uid

        window = TimeWindow(self._clock() - req.minutes * 60, self._clock())
        if req.panel_id is None:  # whole dashboard
            png = await self._capturer.capture_dashboard(window, dashboard_uid=uid or "", dashboard_slug=slug)
            fname, caption = f"{uid}-dashboard.png", f"📸 {label} · whole dashboard · last {req.minutes}m"
        else:
            png = await self._capturer.capture_panel(req.panel_id, window, dashboard_uid=uid, dashboard_slug=slug)
            fname, caption = f"panel-{req.panel_id}.png", f"📸 {label} · panel `{req.panel_id}` · last {req.minutes}m"

        if png is None:
            await self._reply(message, "couldn't capture that (disabled, no such panel, or dashboard not readable).")
            return
        await message.channel.send(content=caption, file=discord.File(io.BytesIO(png), filename=fname))

    async def _reply(self, message: discord.Message, text: str) -> None:
        for chunk in chunk_message(text):
            await message.channel.send(chunk)

    async def start(self) -> None:
        await self.client.start(self._token)

    async def close(self) -> None:
        await self.client.close()
