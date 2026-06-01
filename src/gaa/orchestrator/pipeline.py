"""Per-firing pipeline: screenshot → enrich → analyze → notify → persist.

Every external step is best-effort: a screenshot/analysis/log failure degrades
the message but never prevents the Discord notification.
"""

from __future__ import annotations

import logging

from gaa.analyzer.models import Analyzer
from gaa.clients.links import panel_url
from gaa.clients.protocols import Capturer, Notifier
from gaa.config.rule_models import Rule
from gaa.domain.models import Incident, RuleState
from gaa.enrichment.enricher import Enricher
from gaa.notify.embed import build_firing_embed, build_resolved_embed
from gaa.orchestrator.timeutil import SECONDS_PER_DAY, iso
from gaa.state.store import StateStore

logger = logging.getLogger(__name__)


class AlertPipeline:
    def __init__(
        self,
        *,
        enricher: Enricher,
        analyzer: Analyzer,
        capturer: Capturer,
        notifier: Notifier,
        store: StateStore,
        grafana_base_url: str,
        dashboard_uid: str,
        dashboard_slug: str,
    ) -> None:
        self._enricher = enricher
        self._analyzer = analyzer
        self._capturer = capturer
        self._notifier = notifier
        self._store = store
        self._base_url = grafana_base_url
        self._uid = dashboard_uid
        self._slug = dashboard_slug

    async def handle_firing(self, rule: Rule, state: RuleState, now: float) -> int:
        """Run the full firing pipeline. Returns the recorded incident id."""
        window = state.window
        recent = await self._store.count_recent(rule.name, now - SECONDS_PER_DAY)

        screenshot = None
        if rule.panel_id is not None and window is not None:
            screenshot = await self._capturer.capture_panel(rule.panel_id, window)

        bundle = await self._enricher.enrich(rule, state.last_value, window, recent)
        analysis = await self._analyzer.analyze(bundle)

        link = self._panel_link(rule, window)
        embed = build_firing_embed(
            rule, analysis, state.last_value, link, recent_count=recent, iso_timestamp=iso(now)
        )

        incident = Incident(
            rule_name=rule.name,
            title=rule.title,
            severity=rule.severity,
            fired_at=state.firing_since or now,
            value=state.last_value,
            summary=analysis.summary,
            likely_cause=analysis.likely_cause,
            remediation=analysis.remediation,
            confidence=analysis.confidence,
            dashboard_url=link,
        )
        incident_id = await self._store.record_incident(incident, screenshot)

        # Per-incident thread when the notifier supports it (GatewayNotifier under `gaa bot`).
        image_name = f"{rule.name}.png"
        try:
            if hasattr(self._notifier, "post_alert"):
                thread_id = await self._notifier.post_alert(
                    embed=embed, image_png=screenshot, image_name=image_name,
                    thread_name=f"#{incident_id} {rule.title}",
                )
                if thread_id:
                    await self._store.set_incident_thread(incident_id, thread_id)
            else:
                await self._notifier.send(embed=embed, image_png=screenshot, image_name=image_name)
        except Exception as exc:
            logger.error("failed to send Discord notification for %s: %s", rule.name, exc)
        return incident_id

    async def handle_resolved(self, rule: Rule, prev: RuleState, now: float) -> None:
        duration = None
        if prev.firing_since is not None:
            duration = now - prev.firing_since

        incident_id = await self._store.open_incident_id(rule.name)
        if incident_id is not None:
            await self._store.resolve_incident(incident_id, now)

        embed = build_resolved_embed(rule, duration_seconds=duration, iso_timestamp=iso(now))
        try:
            await self._notifier.send(embed=embed)
        except Exception as exc:
            logger.error("failed to send resolved notification for %s: %s", rule.name, exc)

    def _panel_link(self, rule: Rule, window) -> str:
        if self._uid and rule.panel_id is not None and window is not None:
            return panel_url(self._base_url, self._uid, self._slug, rule.panel_id, window)
        return self._base_url
