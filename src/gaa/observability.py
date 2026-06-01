"""LangSmith tracing wiring.

LangChain/LangGraph emit traces automatically when the native ``LANGSMITH_*``
environment variables are set. We keep the values in ``Settings`` (GAA_-prefixed,
``.env``-driven) so the API key never lives in source, and export them into the
process environment here, once, before any LangChain call is made.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def configure_langsmith(settings) -> bool:
    """Export ``LANGSMITH_*`` env vars from settings so LangChain auto-traces.

    Returns ``True`` when tracing was enabled. Fail-safe: a no-op when the toggle
    is off or the API key is missing — tracing must never crash startup.
    """
    if not settings.langsmith_tracing:
        return False
    if not settings.langsmith_api_key:
        logger.warning(
            "GAA_LANGSMITH_TRACING is on but GAA_LANGSMITH_API_KEY is empty; tracing disabled."
        )
        return False

    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_ENDPOINT"] = settings.langsmith_endpoint
    os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
    logger.info("LangSmith tracing enabled (project=%s)", settings.langsmith_project)
    return True
