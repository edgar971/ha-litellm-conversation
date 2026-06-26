"""Diagnostics support for LiteLLM Conversation."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant

from . import LiteLLMConfigEntry

TO_REDACT = {CONF_API_KEY}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: LiteLLMConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    return async_redact_data(
        {
            "entry_data": dict(entry.data),
            "subentries": {
                subentry_id: dict(subentry.data)
                for subentry_id, subentry in entry.subentries.items()
            },
        },
        TO_REDACT,
    )
