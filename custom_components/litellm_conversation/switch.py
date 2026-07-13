"""Switch platform: transcript capture toggle for the dreaming layer."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .transcripts import TranscriptBuffer, async_get_transcript_buffer

if TYPE_CHECKING:
    from . import LiteLLMConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: LiteLLMConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the transcript capture switch."""
    buffer = async_get_transcript_buffer(hass)
    await buffer.async_load()
    async_add_entities([LiteLLMTranscriptCaptureSwitch(config_entry, buffer)])


class LiteLLMTranscriptCaptureSwitch(SwitchEntity):
    """Toggle for conversation transcript capture (dreaming input).

    Off pauses capture; the existing buffer is kept (pausing is not
    purging — use the clear_transcripts service to wipe). Dreaming itself
    still works while capture is off, on whatever buffer exists.
    """

    _attr_has_entity_name = True
    _attr_name = "Transcript capture"
    _attr_icon = "mdi:record-rec"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_should_poll = False

    def __init__(self, entry: LiteLLMConfigEntry, buffer: TranscriptBuffer) -> None:
        """Initialize the switch."""
        self._buffer = buffer
        self._attr_unique_id = f"{entry.entry_id}_transcript_capture"

    @property
    def is_on(self) -> bool:
        """Return True when capture is enabled."""
        return self._buffer.capture_enabled

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose buffer stats for dashboards."""
        return {
            "buffered_exchanges": self._buffer.exchange_count,
            "last_dream_at": self._buffer.last_dream_at,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable capture."""
        self._buffer.set_capture_enabled(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Pause capture (buffer kept)."""
        self._buffer.set_capture_enabled(False)
        self.async_write_ha_state()
