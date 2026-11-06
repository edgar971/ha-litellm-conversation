"""Shared helpers for the LiteLLM Conversation integration."""

from __future__ import annotations

# Decision models (ai_task.evaluate via the proxy's /v1/systemone endpoint)
# need HA 2026.11+, where homeassistant.components.ai_task.evaluation landed.
# On older cores we degrade gracefully: the config flow hides the subentry
# type and any pre-existing decision subentries are skipped at setup, so an
# install downgraded below 2026.11 keeps working for every other platform.
# This lives here so the config flow can read it without loading the platform.
try:
    from homeassistant.components.ai_task import evaluation as evaluation_module
except ImportError:  # HA < 2026.11: no ai_task.evaluation module
    evaluation_module = None

HAS_EVALUATION = evaluation_module is not None


def normalize_base_url(base_url: str) -> str:
    """Normalize a proxy base URL: strip trailing slashes, ensure /v1 suffix."""
    normalized = base_url.rstrip("/")
    if not normalized.endswith("/v1"):
        normalized = f"{normalized}/v1"
    return normalized
