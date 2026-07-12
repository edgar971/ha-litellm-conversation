"""Shared helpers for the LiteLLM Conversation integration."""

from __future__ import annotations


def normalize_base_url(base_url: str) -> str:
    """Normalize a proxy base URL: strip trailing slashes, ensure /v1 suffix."""
    normalized = base_url.rstrip("/")
    if not normalized.endswith("/v1"):
        normalized = f"{normalized}/v1"
    return normalized
