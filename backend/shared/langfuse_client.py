"""Lightweight Langfuse client helper for backend agents."""

from __future__ import annotations

import os
import threading
from typing import Optional

from dotenv import load_dotenv
from langfuse import Langfuse

load_dotenv()

_client_lock = threading.Lock()
_langfuse_client: Optional[Langfuse] = None
_initialization_failed: Optional[str] = None


def _normalize(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    trimmed = value.strip().strip('"').strip("'")
    return trimmed or None


def get_langfuse_client() -> Optional[Langfuse]:
    """Return a shared Langfuse client or ``None`` when disabled."""

    global _langfuse_client, _initialization_failed

    if _langfuse_client is not None:
        return _langfuse_client

    if _initialization_failed is not None:
        return None

    with _client_lock:
        if _langfuse_client is not None:
            return _langfuse_client

        if _initialization_failed is not None:
            return None

        public_key = _normalize(os.getenv("LANGFUSE_PUBLIC_KEY"))
        secret_key = _normalize(os.getenv("LANGFUSE_SECRET_KEY"))

        if not public_key or not secret_key:
            _initialization_failed = "missing-credentials"
            return None

        try:
            client = Langfuse(public_key=public_key, secret_key=secret_key)
            client.api.health.health()
        except Exception:
            _initialization_failed = "init-error"
            return None

        _langfuse_client = client
        return _langfuse_client
