"""Low-level Grafana transport: datasource-proxy queries + read APIs.

All metrics and logs flow through Grafana's datasource proxy on :443 because
VictoriaMetrics/Loki are firewalled from the VPN client. Authentication is a
Viewer-scoped service-account token. Read-only.
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = httpx.Timeout(15.0, connect=8.0)


def _panel_summary(panel: dict) -> dict:
    return {"id": panel.get("id"), "title": panel.get("title", ""), "type": panel.get("type", "")}


class GrafanaError(RuntimeError):
    """Raised on a failed Grafana API call."""


class GrafanaClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        verify: str | bool = True,
        timeout: httpx.Timeout | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            verify=verify,
            timeout=timeout or _DEFAULT_TIMEOUT,
        )
        self._ds_cache: dict[str, str] = {}

    @property
    def base_url(self) -> str:
        return self._base_url

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "GrafanaClient":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    async def health(self) -> dict:
        resp = await self._client.get("/api/health")
        resp.raise_for_status()
        return resp.json()

    async def datasources(self) -> list[dict]:
        resp = await self._client.get("/api/datasources")
        resp.raise_for_status()
        return resp.json()

    async def resolve_datasource_uid(self, ds_type: str) -> str:
        """Find the UID of the first datasource of ``ds_type`` (cached)."""
        if ds_type in self._ds_cache:
            return self._ds_cache[ds_type]
        for ds in await self.datasources():
            if ds.get("type") == ds_type:
                uid = ds["uid"]
                self._ds_cache[ds_type] = uid
                return uid
        raise GrafanaError(f"no datasource of type '{ds_type}' found")

    async def proxy_get(self, ds_uid: str, path: str, params: dict | None = None) -> dict:
        """GET through the datasource proxy and return parsed JSON."""
        url = f"/api/datasources/proxy/uid/{ds_uid}/{path.lstrip('/')}"
        try:
            resp = await self._client.get(url, params=params)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise GrafanaError(f"proxy GET {path} failed: {exc}") from exc
        return resp.json()

    async def search_dashboard_uid(self, slug_or_title: str) -> str | None:
        """Best-effort lookup of a dashboard UID by title/slug substring."""
        resp = await self._client.get("/api/search", params={"type": "dash-db", "query": slug_or_title})
        resp.raise_for_status()
        for item in resp.json():
            return item.get("uid")
        return None

    async def get_dashboard_panels(self, uid: str) -> list[dict]:
        """Return a dashboard's panels as {id, title, type} (rows flattened, skipped)."""
        resp = await self._client.get(f"/api/dashboards/uid/{uid}")
        resp.raise_for_status()
        panels = resp.json().get("dashboard", {}).get("panels", [])
        out: list[dict] = []
        for panel in panels:
            if panel.get("type") == "row":
                for child in panel.get("panels", []) or []:  # panels nested in a row
                    out.append(_panel_summary(child))
                continue
            out.append(_panel_summary(panel))
        return out

    async def list_dashboards(self) -> list[dict]:
        """List all dashboards as {uid, title, slug}."""
        resp = await self._client.get("/api/search", params={"type": "dash-db"})
        resp.raise_for_status()
        dashboards = []
        for item in resp.json():
            uri = item.get("uri", "")  # "db/<slug>"
            dashboards.append(
                {
                    "uid": item.get("uid", ""),
                    "title": item.get("title", ""),
                    "slug": uri.split("/")[-1] if uri else "",
                    "tags": item.get("tags", []),
                }
            )
        return dashboards
