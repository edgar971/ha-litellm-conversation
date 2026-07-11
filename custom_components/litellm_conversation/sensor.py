"""Usage tracking sensors for LiteLLM Conversation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_time_change

from .const import DOMAIN, SIGNAL_USAGE_UPDATED

if TYPE_CHECKING:
    from . import LiteLLMConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: LiteLLMConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up usage sensors for a LiteLLM config entry."""
    async_add_entities(
        [
            LiteLLMUsageSensor(config_entry, "requests_today", "Requests today"),
            LiteLLMUsageSensor(config_entry, "tokens_today", "Tokens today"),
            LiteLLMUsageSensor(config_entry, "input_tokens_today", "Input tokens today"),
            LiteLLMUsageSensor(config_entry, "output_tokens_today", "Output tokens today"),
        ]
    )


class LiteLLMUsageSensor(SensorEntity):
    """Counter sensor for LiteLLM usage, resetting daily at midnight."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_value = 0

    def __init__(self, entry: LiteLLMConfigEntry, key: str, name: str) -> None:
        """Initialize the sensor."""
        self.entry = entry
        self._key = key
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "LiteLLM Proxy",
            "entry_type": "service",
        }
        self._last_model: str | None = None

    async def async_added_to_hass(self) -> None:
        """Subscribe to usage updates and the midnight reset."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{SIGNAL_USAGE_UPDATED}_{self.entry.entry_id}",
                self._handle_usage,
            )
        )
        self.async_on_remove(
            async_track_time_change(
                self.hass, self._handle_midnight, hour=0, minute=0, second=0
            )
        )

    @callback
    def _handle_usage(self, usage: dict[str, Any]) -> None:
        """Accumulate usage from a completed request."""
        increment = {
            "requests_today": 1,
            "tokens_today": usage.get("total_tokens", 0),
            "input_tokens_today": usage.get("prompt_tokens", 0),
            "output_tokens_today": usage.get("completion_tokens", 0),
        }[self._key]
        self._attr_native_value = (self._attr_native_value or 0) + increment
        self._last_model = usage.get("model")
        self.async_write_ha_state()

    @callback
    def _handle_midnight(self, _now) -> None:
        """Reset the counter at midnight."""
        self._attr_native_value = 0
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes."""
        return {"last_model": self._last_model}
