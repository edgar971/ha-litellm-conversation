"""Diagnostics support for LiteLLM Conversation."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant

from . import LiteLLMConfigEntry
from .memory import async_get_memory_store

TO_REDACT = {CONF_API_KEY}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: LiteLLMConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    memory_store = async_get_memory_store(hass)
    await memory_store.async_load()
    from .transcripts import async_get_transcript_buffer

    buffer = async_get_transcript_buffer(hass)
    await buffer.async_load()
    return async_redact_data(
        {
            "entry_data": dict(entry.data),
            "subentries": {
                subentry_id: dict(subentry.data)
                for subentry_id, subentry in entry.subentries.items()
            },
            "memories": [m.as_dict() for m in memory_store.memories],
            "transcripts": {
                "capture_enabled": buffer.capture_enabled,
                "buffered_exchanges": buffer.exchange_count,
                "last_dream_at": buffer.last_dream_at,
            },
        },
        TO_REDACT,
    )
