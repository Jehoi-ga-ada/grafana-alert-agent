"""Shared TLS configuration built once from the internal CA bundle.

Verification is the default; insecure-skip is an explicit opt-in. We never
silently disable verification (security rule).
"""

from __future__ import annotations

import logging
import ssl
from pathlib import Path

logger = logging.getLogger(__name__)


def build_verify(ca_cert_path: Path | None, insecure: bool) -> str | bool:
    """Return the value httpx expects for its ``verify`` argument."""
    if insecure:
        logger.warning("TLS verification DISABLED (GAA_TLS_INSECURE=true) — discouraged")
        return False
    if ca_cert_path is not None:
        if not ca_cert_path.is_file():
            raise FileNotFoundError(f"CA cert not found: {ca_cert_path}")
        return str(ca_cert_path)
    return True


def build_ssl_context(ca_cert_path: Path | None, insecure: bool) -> ssl.SSLContext:
    """Build an SSLContext (used where a raw context is required)."""
    context = ssl.create_default_context()
    if insecure:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return context
    if ca_cert_path is not None:
        if not ca_cert_path.is_file():
            raise FileNotFoundError(f"CA cert not found: {ca_cert_path}")
        context.load_verify_locations(cafile=str(ca_cert_path))
    return context
