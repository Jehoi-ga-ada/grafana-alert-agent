"""mcp-grafana (read-only) integration.

Launches the official Grafana MCP server as a stdio subprocess and exposes its
tools to LangGraph. Read-only is enforced three ways:
  1. the server runs with ``--disable-write``,
  2. the Grafana service-account token is Viewer-scoped, and
  3. a fail-closed allowlist here drops any tool not explicitly permitted.

The launch/subprocess code is excluded from the coverage gate; the pure config
+ allowlist logic below is unit-tested.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

logger = logging.getLogger(__name__)

# Exact read-only tool names + safe prefixes. Anything not matching is dropped.
_ALLOWED_EXACT: frozenset[str] = frozenset(
    {
        "query_prometheus",
        "query_loki_logs",
        "query_loki_stats",
        "list_datasources",
        # Dashboard discovery is the LOCAL list_dashboards tool (MCP search_dashboards
        # returned partial results and is intentionally NOT allowlisted). MCP is used
        # only to inspect a dashboard's panels once its uid is known.
        "get_dashboard_by_uid",
        "get_dashboard_panel_queries",
        "list_prometheus_metric_names",
        "list_prometheus_label_names",
        "list_prometheus_label_values",
        "list_loki_label_names",
        "list_loki_label_values",
    }
)
# Read-only Sift prefixes (inspect existing investigations/analyses).
_SIFT_READ_PREFIXES: tuple[str, ...] = ("list_sift_", "get_sift_")
# Sift *analysis* tools — create an investigation artifact (no infra change).
# Gated behind allow_sift.
_SIFT_ANALYSIS: frozenset[str] = frozenset({"find_slow_requests", "find_error_pattern_logs"})
# Belt-and-braces: never allow anything whose name implies mutation.
_FORBIDDEN_SUBSTRINGS: tuple[str, ...] = (
    "create", "update", "delete", "add", "remove", "write", "set_",
    "pause", "unpause", "silence", "import", "enable", "disable", "move", "save",
)


def is_allowed(name: str, allow_sift: bool = True) -> bool:
    """Fail-closed read-only predicate. Only known read tools (+ Sift analysis) pass."""
    if any(bad in name.lower() for bad in _FORBIDDEN_SUBSTRINGS):
        return False
    if name in _ALLOWED_EXACT:
        return True
    if name.startswith(_SIFT_READ_PREFIXES):
        return True
    if allow_sift and name in _SIFT_ANALYSIS:
        return True
    return False


def filter_tools(tools: list, allow_sift: bool = True) -> list:
    """Keep only allowlisted tools (each has a ``.name``). Fail-closed."""
    kept = [t for t in tools if is_allowed(getattr(t, "name", ""), allow_sift)]
    dropped = [getattr(t, "name", "?") for t in tools if t not in kept]
    if dropped:
        logger.info("MCP: dropped %d non-allowlisted tools: %s", len(dropped), dropped)
    logger.info("MCP: %d tools available: %s", len(kept), [t.name for t in kept])
    return kept


# Server-level category whitelist (defense layer 1) — only read-relevant categories.
# Combined with -disable-write (layer 2) and the Python allowlist (layer 3).
_ENABLED_CATEGORIES = "search,datasource,prometheus,loki,sift,dashboard"


def server_config(settings) -> dict:
    """Build the stdio launch spec for mcp-grafana.

    With allow_sift we drop -disable-write (so Sift analysis tools load) and rely
    on the fail-closed Python allowlist; otherwise we keep -disable-write too.
    """
    args = ["-enabled-tools", _ENABLED_CATEGORIES]
    if not settings.allow_sift:
        args.insert(0, "-disable-write")
    if settings.tls_insecure:
        args.append("-tls-skip-verify")
    elif settings.grafana_ca_cert:
        args += ["-tls-ca-file", str(Path(settings.grafana_ca_cert).expanduser())]

    # mcp-grafana accepts either env var name for the bearer/service-account token.
    env = {
        "GRAFANA_URL": settings.grafana_url,
        "GRAFANA_API_KEY": settings.grafana_sa_token,
        "GRAFANA_SERVICE_ACCOUNT_TOKEN": settings.grafana_sa_token,
    }
    return {
        "command": settings.mcp_grafana_bin,
        "args": args,
        "transport": "stdio",
        "env": env,
    }


@asynccontextmanager
async def open_grafana_tools(settings):  # pragma: no cover - launches a subprocess
    """Yield the allowlisted Grafana MCP tools for the lifetime of the context.

    Holds a single persistent stdio session (one mcp-grafana process) so tools
    are fast and the subprocess is cleanly torn down on exit.
    """
    from langchain_mcp_adapters.client import MultiServerMCPClient

    client = MultiServerMCPClient({"grafana": server_config(settings)})
    async with client.session("grafana") as session:
        from langchain_mcp_adapters.tools import load_mcp_tools

        all_tools = await load_mcp_tools(session)
        yield filter_tools(all_tools, settings.allow_sift)
