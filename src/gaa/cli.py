"""Command-line entrypoints. Excluded from the coverage gate (thin glue).

  gaa check    verify VPN/Grafana/datasource reachability + Discord webhook
  gaa once     run a single evaluation tick (use --dry-run to skip notifications)
  gaa daemon   run the continuous poll loop (with screenshots)
  gaa serve    run the FastAPI backend + frontend
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import time

from gaa.bootstrap import build_core, resolve_dashboard_uid
from gaa.config.settings import Settings
from gaa.notify.embed import build_heartbeat_embed
from gaa.orchestrator.daemon import Daemon
from gaa.orchestrator.pipeline import AlertPipeline
from gaa.orchestrator.timeutil import iso

logger = logging.getLogger(__name__)


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )


async def cmd_check(settings: Settings, send_discord: bool) -> int:
    core = build_core(settings)
    ok = True
    try:
        try:
            health = await core.grafana.health()
            print(f"✅ Grafana reachable: v{health.get('version')} (db={health.get('database')})")
        except Exception as exc:
            print(f"❌ Grafana unreachable: {exc}  (is the VPN up?)")
            ok = False

        try:
            result = await core.metrics.query_instant('up{job="url-shortener"}')
            print(f"✅ Datasource proxy OK: 'up' returned {len(result.samples)} series")
        except Exception as exc:
            print(f"❌ Metrics query failed: {exc}")
            ok = False

        uid = await resolve_dashboard_uid(core)
        print(f"{'✅' if uid else '⚠️ '} Dashboard UID: {uid or '(not found — set GAA_DASHBOARD_UID)'}")

        print(f"{'✅' if settings.llm_configured else '⚠️ '} LLM ({settings.llm_provider}) "
              f"{'configured' if settings.llm_configured else 'MISSING credentials (analysis will be degraded)'}")

        if send_discord:
            try:
                await core.notifier.send(embed=build_heartbeat_embed(0, iso(time.time())))
                print("✅ Discord webhook: test message sent")
            except Exception as exc:
                print(f"❌ Discord webhook failed: {exc}")
                ok = False
        else:
            print("⏭️  Discord webhook: skipped (--no-discord)")
    finally:
        await core.aclose()
    return 0 if ok else 1


async def _build_daemon(settings: Settings, with_screenshots: bool, notifier=None):
    core = build_core(settings)
    uid = await resolve_dashboard_uid(core)
    capturer, browser = await _make_capturer(settings, uid, with_screenshots)
    pipeline = AlertPipeline(
        enricher=core.enricher,
        analyzer=core.analyzer,
        capturer=capturer,
        notifier=notifier or core.notifier,
        store=core.store,
        grafana_base_url=settings.grafana_url,
        dashboard_uid=uid,
        dashboard_slug=settings.dashboard_slug,
    )
    daemon = Daemon(
        rules=core.rules,
        metrics=core.metrics,
        store=core.store,
        pipeline=pipeline,
        clock=time.time,
        poll_interval=settings.poll_interval_seconds,
        health_check=lambda: _grafana_reachable(core),
    )
    return core, daemon, browser, capturer


async def _grafana_reachable(core) -> bool:
    try:
        await core.grafana.health()
        return True
    except Exception:
        return False


async def _make_capturer(settings: Settings, uid: str, with_screenshots: bool):
    if not with_screenshots:
        from gaa.screenshot.capture import NullCapturer

        return NullCapturer(), None
    from gaa.screenshot.browser import BrowserManager
    from gaa.screenshot.capture import PlaywrightCapturer

    browser = BrowserManager(settings.grafana_sa_token)
    await browser.start()
    capturer = PlaywrightCapturer(browser, settings.grafana_url, uid, settings.dashboard_slug)
    return capturer, browser


async def cmd_once(settings: Settings, dry_run: bool) -> int:
    core, daemon, browser, _ = await _build_daemon(settings, with_screenshots=not dry_run)
    try:
        if dry_run:
            for rule in core.rules:
                try:
                    result = await core.metrics.query_instant(rule.expr)
                    values = [s.value for s in result.samples]
                    print(f"{rule.name:22} expr→{values}")
                except Exception as exc:
                    print(f"{rule.name:22} ERROR: {exc}")
        else:
            report = await daemon.run_once(time.time())
            print(f"fired={report.fired} resolved={report.resolved} errors={report.errors}")
    finally:
        if browser:
            await browser.stop()
        await core.aclose()
    return 0


async def cmd_daemon(settings: Settings) -> int:
    core, daemon, browser, _ = await _build_daemon(settings, with_screenshots=True)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, daemon.request_stop)
    try:
        await daemon.serve()
    finally:
        if browser:
            await browser.stop()
        await core.aclose()
    return 0


async def cmd_bot(settings: Settings) -> int:
    """Run the chat bot + alert poll loop together (shared browser + MCP)."""
    if not settings.discord_bot_token:
        print("❌ GAA_DISCORD_BOT_TOKEN is not set — create a Discord bot and add its token to .env")
        return 1

    from contextlib import AsyncExitStack

    import discord
    from langgraph.checkpoint.memory import MemorySaver

    from gaa.agent.capture_tool import build_capture_dashboard_tool, build_capture_tool
    from gaa.agent.graph import build_chat_agent
    from gaa.agent.local_tools import build_local_tools
    from gaa.agent.mcp import open_grafana_tools
    from gaa.agent.prompt import chat_system, investigate_system
    from gaa.anomaly.sweep import AnomalySweeper
    from gaa.digest import DigestService
    from gaa.discord_bot.bot import AlertBot
    from gaa.notify.gateway import GatewayNotifier

    # One Discord client shared by the bot + the gateway notifier (per-incident threads).
    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)
    gateway = GatewayNotifier(client, settings.discord_channel_id) if settings.discord_channel_id else None

    core, daemon, browser, capturer = await _build_daemon(settings, with_screenshots=True, notifier=gateway)
    sweeper = AnomalySweeper(
        checks=core.anomaly_checks,
        metrics=core.metrics,
        notifier=gateway or core.notifier,
        store=core.store,
        clock=time.time,
        interval=settings.sweep_interval_seconds,
    )
    digest = DigestService(
        core=core, notifier=gateway or core.notifier, clock=time.time,
        interval=settings.digest_interval_seconds,
    )
    stack = AsyncExitStack()
    bot = None
    try:
        chat_agent = investigate_agent = None
        if core.model_configured:
            mcp_tools: list = []
            try:
                mcp_tools = await stack.enter_async_context(open_grafana_tools(settings))
            except Exception as exc:
                logger.warning("mcp-grafana unavailable (%s); chat limited to incident tools", exc)
            tools = (
                list(mcp_tools)
                + build_local_tools(core.store, core.grafana)
                + [build_capture_tool(capturer), build_capture_dashboard_tool(capturer)]
            )
            chat_agent = build_chat_agent(core.model, tools, chat_system(), MemorySaver())
            investigate_agent = build_chat_agent(core.model, tools, investigate_system(), MemorySaver())
        else:
            logger.warning("LLM not configured; chat disabled (alerts still run)")

        bot = AlertBot(
            token=settings.discord_bot_token,
            chat_agent=chat_agent,
            investigate_agent=investigate_agent,
            capturer=capturer,
            store=core.store,
            grafana=core.grafana,
            metrics=core.metrics,
            rules=core.rules,
            anomaly_checks=core.anomaly_checks,
            client=client,
            channel_id=settings.discord_channel_id,
            agent_max_steps=settings.agent_max_steps,
        )
        loop = asyncio.get_running_loop()

        def _stop() -> None:
            daemon.request_stop()
            sweeper.request_stop()
            digest.request_stop()
            loop.create_task(bot.close())

        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, _stop)

        logger.info("starting Discord bot + alert daemon + anomaly sweeper + digest")
        await asyncio.gather(daemon.serve(), bot.start(), sweeper.serve(), digest.serve())
    finally:
        if bot is not None:
            await bot.close()
        await stack.aclose()
        if browser:
            await browser.stop()
        await core.aclose()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="gaa", description="Grafana Alert Agent (read-only)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("check", help="verify connectivity")
    sub.choices["check"].add_argument("--no-discord", action="store_true", help="skip the Discord test message")

    once = sub.add_parser("once", help="run a single evaluation tick")
    once.add_argument("--dry-run", action="store_true", help="evaluate only; no screenshots/notifications")

    sub.add_parser("daemon", help="run the continuous alert poll loop (alerts only)")
    sub.add_parser("bot", help="run the Discord chat bot + alert poll loop")

    args = parser.parse_args()
    settings = Settings()
    _configure_logging(settings.log_level)

    if args.command == "check":
        raise SystemExit(asyncio.run(cmd_check(settings, send_discord=not args.no_discord)))
    if args.command == "once":
        raise SystemExit(asyncio.run(cmd_once(settings, dry_run=args.dry_run)))
    if args.command == "daemon":
        raise SystemExit(asyncio.run(cmd_daemon(settings)))
    if args.command == "bot":
        raise SystemExit(asyncio.run(cmd_bot(settings)))
