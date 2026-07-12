"""Tests for the usage sensor restore behaviour."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.litellm_conversation.sensor import LiteLLMUsageSensor


def _sensor(hass: HomeAssistant) -> LiteLLMUsageSensor:
    entry = MagicMock()
    entry.entry_id = "test_entry"
    sensor = LiteLLMUsageSensor(entry, "requests_today", "Requests today")
    sensor.hass = hass
    sensor.entity_id = "sensor.litellm_requests_today"
    sensor.async_on_remove = MagicMock()
    return sensor


async def _added_with_restore(
    hass: HomeAssistant, native_value, last_updated
) -> LiteLLMUsageSensor:
    sensor = _sensor(hass)
    last_data = SimpleNamespace(native_value=native_value)
    last_state = SimpleNamespace(last_updated=last_updated)
    with (
        patch.object(sensor, "async_get_last_sensor_data", AsyncMock(return_value=last_data)),
        patch.object(sensor, "async_get_last_state", AsyncMock(return_value=last_state)),
    ):
        await sensor.async_added_to_hass()
    return sensor


async def test_restores_same_day_value(hass: HomeAssistant) -> None:
    """A value from earlier today is restored."""
    sensor = await _added_with_restore(hass, 42, dt_util.utcnow())
    assert sensor.native_value == 42


async def test_discards_previous_day_value(hass: HomeAssistant) -> None:
    """A value from yesterday is not restored (missed midnight reset)."""
    sensor = await _added_with_restore(hass, 42, dt_util.utcnow() - timedelta(days=2))
    assert sensor.native_value == 0


async def test_no_previous_state(hass: HomeAssistant) -> None:
    """No stored state -> counter starts at 0."""
    sensor = _sensor(hass)
    with (
        patch.object(sensor, "async_get_last_sensor_data", AsyncMock(return_value=None)),
        patch.object(sensor, "async_get_last_state", AsyncMock(return_value=None)),
    ):
        await sensor.async_added_to_hass()
    assert sensor.native_value == 0


async def test_garbage_restore_value(hass: HomeAssistant) -> None:
    """Unparseable stored value falls back to 0."""
    sensor = await _added_with_restore(hass, "not-a-number", dt_util.utcnow())
    assert sensor.native_value == 0


async def test_usage_accumulates(hass: HomeAssistant) -> None:
    """Usage events increment the counter."""
    sensor = _sensor(hass)
    sensor.async_write_ha_state = MagicMock()
    sensor._handle_usage({"total_tokens": 100, "model": "gpt-4o-mini"})
    sensor._handle_usage({"total_tokens": 50, "model": "gpt-4o-mini"})
    assert sensor.native_value == 2  # requests_today counts requests
    assert sensor.extra_state_attributes["last_model"] == "gpt-4o-mini"


async def test_midnight_reset(hass: HomeAssistant) -> None:
    """Midnight callback zeroes the counter."""
    sensor = _sensor(hass)
    sensor.async_write_ha_state = MagicMock()
    sensor._attr_native_value = 99
    sensor._handle_midnight(None)
    assert sensor.native_value == 0
