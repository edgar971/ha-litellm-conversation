"""Tests for the usage sensor restore behaviour."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import openai
import pytest

from custom_components.litellm_conversation import sensor as sensor_module
from custom_components.litellm_conversation.sensor import (
    LiteLLMBudgetSensor,
    LiteLLMKeyInfoCoordinator,
    LiteLLMSpendSensor,
    LiteLLMUsageSensor,
    budget_usage_percent,
    parse_key_info,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util


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


# ---------------------------------------------------------------------------
# /key/info parsing (pure functions, no network)
# ---------------------------------------------------------------------------

_LIVE_PAYLOAD = {
    "key": "sk-cAG...4gEA",
    "info": {
        "key_name": "sk-...",
        "key_alias": "hermes",
        "spend": 3.5686,
        "total_spend": 37.98,
        "max_budget": 50.0,
        "rpm_limit": 120,
        "models": ["gpt-4o-mini"],
        "metadata": {},
    },
}


def test_parse_key_info_live_shape() -> None:
    """A real-shaped /key/info body parses into all fields."""
    info = parse_key_info(_LIVE_PAYLOAD)
    assert info.spend == 3.5686
    assert info.max_budget == 50.0
    assert info.total_spend == 37.98
    assert info.key_alias == "hermes"


def test_parse_key_info_alias_falls_back_to_key_name() -> None:
    """No key_alias -> key_name is used; non-string alias degrades to None."""
    payload = {"info": {"key_name": "fallback-name"}}
    assert parse_key_info(payload).key_alias == "fallback-name"
    payload = {"info": {"key_alias": 123, "key_name": None}}
    assert parse_key_info(payload).key_alias is None


def test_parse_key_info_missing_fields_degrade_to_none() -> None:
    """Missing or non-numeric fields become None (endpoint evolves gracefully)."""
    info = parse_key_info({"info": {"spend": "not-a-number", "max_budget": True}})
    assert info.spend is None
    assert info.max_budget is None
    assert info.total_spend is None


@pytest.mark.parametrize("payload", [{}, {"info": None}, [], "nope", None])
def test_parse_key_info_malformed_raises(payload: object) -> None:
    """Structurally malformed payloads raise ValueError (-> UpdateFailed upstream)."""
    with pytest.raises(ValueError):
        parse_key_info(payload)


@pytest.mark.parametrize(
    ("spend", "max_budget", "expected"),
    [
        (3.5686, 50.0, 7.1),
        (50.0, 50.0, 100.0),
        (75.0, 50.0, 150.0),  # overspend is shown, not clamped
        (None, 50.0, None),
        (3.5, None, None),
        (3.5, 0.0, None),
        (3.5, -1.0, None),
    ],
)
def test_budget_usage_percent(
    spend: float | None, max_budget: float | None, expected: float | None
) -> None:
    """Utilization is rounded to 0.1%; absent/zero budget yields None."""
    assert budget_usage_percent(spend, max_budget) == expected


# ---------------------------------------------------------------------------
# Coordinator fetch behaviour (mocked client, no network)
# ---------------------------------------------------------------------------


def _coordinator(hass: HomeAssistant, get_mock: AsyncMock) -> LiteLLMKeyInfoCoordinator:
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.runtime_data.with_options.return_value.get = get_mock
    return LiteLLMKeyInfoCoordinator(hass, entry)


async def test_coordinator_update_parses_payload(hass: HomeAssistant) -> None:
    """_async_update_data returns parsed KeySpendInfo from the client response."""
    coordinator = _coordinator(hass, AsyncMock(return_value=_LIVE_PAYLOAD))
    info = await coordinator._async_update_data()
    assert info.spend == 3.5686
    assert info.key_alias == "hermes"


async def test_coordinator_auth_error_raises_reauth(hass: HomeAssistant) -> None:
    """A revoked key surfaces as ConfigEntryAuthFailed (reauth flow), not retry."""
    err = openai.AuthenticationError("gone", response=MagicMock(status_code=401), body=None)
    coordinator = _coordinator(hass, AsyncMock(side_effect=err))
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_coordinator_connection_error_raises_update_failed(hass: HomeAssistant) -> None:
    """Proxy unreachable -> UpdateFailed (entity unavailable, entry stays loaded)."""
    err = openai.APIConnectionError(request=MagicMock())
    coordinator = _coordinator(hass, AsyncMock(side_effect=err))
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_coordinator_malformed_payload_raises_update_failed(hass: HomeAssistant) -> None:
    """A 200 with junk body is an UpdateFailed, not a crash."""
    coordinator = _coordinator(hass, AsyncMock(return_value={"unexpected": True}))
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


def test_spend_sensor_state_and_attributes() -> None:
    """Spend sensor exposes window spend + lifetime/alias context attributes."""
    entry = MagicMock()
    entry.entry_id = "test_entry"
    coordinator = MagicMock(spec=LiteLLMKeyInfoCoordinator)
    coordinator.entry = entry
    coordinator.last_update_success = True
    coordinator.data = parse_key_info(_LIVE_PAYLOAD)

    spend = LiteLLMSpendSensor(coordinator)
    budget = LiteLLMBudgetSensor(coordinator)

    assert spend.native_value == 3.5686
    assert budget.native_value == 7.1
    assert spend.unique_id == "test_entry_proxy_spend"
    assert budget.unique_id == "test_entry_budget_utilization"
    assert spend.extra_state_attributes == {
        "key_alias": "hermes",
        "max_budget": 50.0,
        "total_spend": 37.98,
    }


def test_budget_sensor_unknown_without_max_budget() -> None:
    """No max_budget configured -> utilization is unknown (None), spend still shows."""
    coordinator = MagicMock(spec=LiteLLMKeyInfoCoordinator)
    coordinator.entry = MagicMock(entry_id="test_entry")
    coordinator.last_update_success = True
    coordinator.data = parse_key_info({"info": {"spend": 1.0}})

    assert LiteLLMBudgetSensor(coordinator).native_value is None
    assert LiteLLMSpendSensor(coordinator).native_value == 1.0


def test_sensors_unavailable_when_fetch_failing() -> None:
    """After a failed poll, availability is False and states are None."""
    coordinator = MagicMock(spec=LiteLLMKeyInfoCoordinator)
    coordinator.entry = MagicMock(entry_id="test_entry")
    coordinator.last_update_success = False
    coordinator.data = parse_key_info(_LIVE_PAYLOAD)  # stale data must not be shown

    spend = LiteLLMSpendSensor(coordinator)
    assert spend.available is False
    assert spend.native_value is None
    assert spend.extra_state_attributes == {}


async def test_coordinator_logs_failure_once_and_recovery(hass: HomeAssistant) -> None:
    """Fetch errors log once per transition; recovery logs once (quality scale)."""
    get_mock = AsyncMock(side_effect=openai.APIConnectionError(request=MagicMock()))
    coordinator = _coordinator(hass, get_mock)

    with (
        patch.object(sensor_module.LOGGER, "error") as mock_error,
        patch.object(sensor_module.LOGGER, "info") as mock_info,
    ):
        await coordinator._async_refresh()
        await coordinator._async_refresh()  # still failing -> no second error log
        assert mock_error.call_count == 1

        get_mock.side_effect = None
        get_mock.return_value = _LIVE_PAYLOAD
        await coordinator._async_refresh()
        assert any("recovered" in str(call) for call in mock_info.call_args_list)
