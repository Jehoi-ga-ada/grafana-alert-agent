"""Composition root — build the shared object graph from Settings.

Sync + HTTP-only: shared by `gaa check/once/daemon/bot`. The MCP subprocess and
LangGraph agent are built separately in `cmd_bot` (see cli.py), not here, so the
deterministic daemon never depends on MCP.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from gaa.agent.model import build_chat_model, model_configured
from gaa.analyzer.claude import LLMAnalyzer
from gaa.anomaly.config_loader import load_anomaly_checks
from gaa.anomaly.models import AnomalyCheck
from gaa.analyzer.models import Analyzer
from gaa.clients.discord import DiscordNotifier
from gaa.clients.grafana import GrafanaClient
from gaa.clients.loki import LogsClient
from gaa.clients.victoriametrics import MetricsClient
from gaa.config.rule_loader import load_rules
from gaa.config.rule_models import Rule
from gaa.config.settings import Settings
from gaa.enrichment.enricher import Enricher
from gaa.state.sqlite_store import SqliteStore


@dataclass
class Core:
    settings: Settings
    rules: tuple[Rule, ...]
    grafana: GrafanaClient
    metrics: MetricsClient
    logs: LogsClient
    store: SqliteStore
    notifier: DiscordNotifier
    analyzer: Analyzer
    enricher: Enricher
    anomaly_checks: tuple[AnomalyCheck, ...]
    model: object | None  # LangChain chat model (None if no credentials)
    model_configured: bool

    async def aclose(self) -> None:
        await self.grafana.aclose()
        await self.notifier.aclose()
        self.store.close()


def build_core(settings: Settings, clock=time.time) -> Core:
    grafana = GrafanaClient(settings.grafana_url, settings.grafana_sa_token, verify=settings.verify)
    metrics = MetricsClient(grafana)
    logs = LogsClient(grafana)
    store = SqliteStore(settings.state_db_path)
    notifier = DiscordNotifier(settings.discord_webhook_url)

    configured = model_configured(settings)
    model = build_chat_model(settings) if configured else None
    analyzer = LLMAnalyzer(model, configured)
    enricher = Enricher(metrics, logs)
    rules = load_rules(settings.rules_path)
    anomaly_checks = load_anomaly_checks(settings.anomalies_path)
    return Core(
        settings=settings,
        rules=rules,
        grafana=grafana,
        metrics=metrics,
        logs=logs,
        store=store,
        notifier=notifier,
        analyzer=analyzer,
        enricher=enricher,
        anomaly_checks=anomaly_checks,
        model=model,
        model_configured=configured,
    )


async def resolve_dashboard_uid(core: Core) -> str:
    """Return the configured dashboard UID, or look it up by slug."""
    if core.settings.dashboard_uid:
        return core.settings.dashboard_uid
    uid = await core.grafana.search_dashboard_uid(core.settings.dashboard_slug)
    return uid or ""
