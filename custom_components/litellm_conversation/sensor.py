"""Usage tracking sensors for LiteLLM Conversation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import openai

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.util import dt as dt_util

from .const import DOMAIN, KEY_INFO_UPDATE_INTERVAL, LOGGER, SIGNAL_USAGE_UPDATED

if TYPE_CHECKING:
    from . import LiteLLMConfigEntry


@dataclass(frozen=True)
class KeySpendInfo:
    """Proxy-side spend data parsed from a LiteLLM /key/info response."""

    spend: float | None
    max_budget: float | None
    total_spend: float | None
    key_alias: str | None


def _as_float(value: Any) -> float | None:
    """Coerce a JSON numeric to float; anything else (incl. bool) is None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def parse_key_info(payload: Any) -> KeySpendInfo:
    """Parse a /key/info response body into KeySpendInfo.

    Pure function so the parsing contract is unit-testable without network.
    Raises ValueError on structurally malformed payloads (missing 'info'
    object) so the coordinator can surface them as UpdateFailed; individual
    missing/non-numeric fields degrade to None instead.
    """
    info = payload.get("info") if isinstance(payload, dict) else None
    if not isinstance(info, dict):
        raise ValueError("missing 'info' object in /key/info response")
    alias = info.get("key_alias") or info.get("key_name")
    return KeySpendInfo(
        spend=_as_float(info.get("spend")),
        max_budget=_as_float(info.get("max_budget")),
        total_spend=_as_float(info.get("total_spend")),
        key_alias=alias if isinstance(alias, str) else None,
    )


def budget_usage_percent(spend: float | None, max_budget: float | None) -> float | None:
    """Percent of the key's budget window consumed; None when no usable budget."""
    if spend is None or max_budget is None or max_budget <= 0:
        return None
    return round(spend / max_budget * 100.0, 1)


class LiteLLMKeyInfoCoordinator(DataUpdateCoordinator[KeySpendInfo]):
    """Poll the proxy's self-info endpoint (GET /key/info) for key spend/budget.

    Works with a plain virtual key — no admin key required. HA's coordinator
    already logs fetch errors only once per failure transition and logs a
    'recovered' message on success, matching how the request-driven entities
    log proxy connectivity; entity availability follows last_update_success.
    """

    def __init__(self, hass: HomeAssistant, entry: LiteLLMConfigEntry) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            LOGGER,
            name="LiteLLM key info",
            config_entry=entry,
            update_interval=KEY_INFO_UPDATE_INTERVAL,
        )
        self.entry = entry

    async def _async_update_data(self) -> KeySpendInfo:
        """Fetch and parse /key/info with the entry's own virtual key."""
        client: openai.AsyncOpenAI = self.entry.runtime_data
        try:
            payload = await client.with_options(timeout=15.0).get("/key/info", cast_to=dict)
        except openai.AuthenticationError as err:
            # Key revoked/rotated → surface as reauth, same as setup validation.
            raise ConfigEntryAuthFailed(err) from err
        except openai.OpenAIError as err:
            raise UpdateFailed(f"LiteLLM /key/info request failed: {err}") from err
        try:
            return parse_key_info(payload)
        except ValueError as err:
            raise UpdateFailed(f"Unexpected LiteLLM /key/info response: {err}") from err


class LiteLLMKeyInfoSensor(CoordinatorEntity[LiteLLMKeyInfoCoordinator], SensorEntity):
    """Base for the proxy-reported spend/budget sensors."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: LiteLLMKeyInfoCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        entry_id = coordinator.entry.entry_id
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry_id)},
            "name": "LiteLLM Proxy",
            "entry_type": "service",
        }

    @property
    def _info(self) -> KeySpendInfo | None:
        """Return the latest parsed key info, or None while unavailable."""
        if self.coordinator.last_update_success and self.coordinator.data is not None:
            return self.coordinator.data
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return proxy-reported context (alias, budget window totals)."""
        info = self._info
        if info is None:
            return {}
        return {
            "key_alias": info.key_alias,
            "max_budget": info.max_budget,
            "total_spend": info.total_spend,
        }


class LiteLLMSpendSensor(LiteLLMKeyInfoSensor):
    """Proxy-reported cumulative spend for this integration's virtual key.

    state_class is MEASUREMENT, deliberately NOT TOTAL_INCREASING: the
    proxy's `spend` field accumulates within the key's *budget window* and
    drops back toward 0 when that window rolls over (daily/weekly/monthly,
    proxy-configured). Marking it total_increasing would make long-term
    statistics treat those legitimate resets as corrupted state and discard
    them; MEASUREMENT keeps every sample so dashboards can compute increases
    themselves. The never-resetting lifetime figure (`total_spend`) is
    exposed as an attribute for strictly monotonic charting.
    """

    _attr_translation_key = "proxy_spend"
    # Native unit is a literal "$": LiteLLM reports spend in USD and this HA
    # build has no MONETARY device-class/currency infrastructure to convert
    # against (it also restricts MONETARY to state_class=TOTAL, which would
    # forbid the MEASUREMENT choice documented above).
    _attr_native_unit_of_measurement = "$"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: LiteLLMKeyInfoCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_proxy_spend"

    @property
    def native_value(self) -> float | None:
        """Return the key's spend in USD for the current budget window."""
        return self._info.spend if self._info is not None else None


class LiteLLMBudgetSensor(LiteLLMKeyInfoSensor):
    """Budget utilization percent (spend / max_budget) for the virtual key.

    State is unknown (not unavailable) when the key has no max_budget set —
    the endpoint works fine, there is simply nothing to compute against.
    """

    _attr_translation_key = "budget_utilization"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: LiteLLMKeyInfoCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_budget_utilization"

    @property
    def native_value(self) -> float | None:
        """Return budget utilization percent, or None without a max_budget."""
        info = self._info
        return budget_usage_percent(info.spend, info.max_budget) if info is not None else None


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: LiteLLMConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up usage sensors for a LiteLLM config entry."""
    coordinator = LiteLLMKeyInfoCoordinator(hass, config_entry)
    await coordinator.async_config_entry_first_refresh()

    async_add_entities(
        [
            LiteLLMUsageSensor(config_entry, "requests_today", "Requests today"),
            LiteLLMUsageSensor(config_entry, "tokens_today", "Tokens today"),
            LiteLLMUsageSensor(config_entry, "input_tokens_today", "Input tokens today"),
            LiteLLMUsageSensor(config_entry, "output_tokens_today", "Output tokens today"),
            LiteLLMSpendSensor(coordinator),
            LiteLLMBudgetSensor(coordinator),
        ]
    )


class LiteLLMUsageSensor(RestoreSensor):
    """Counter sensor for LiteLLM usage, resetting daily at midnight.

    State is restored across HA restarts (RestoreSensor) so a midday
    restart doesn't zero the daily counters — which would also corrupt
    long-term statistics for a TOTAL_INCREASING sensor.
    """

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
        await super().async_added_to_hass()

        # Restore the previous value unless it is from an earlier day
        # (in which case the midnight reset it missed applies now).
        if (last_data := await self.async_get_last_sensor_data()) is not None and (
            last_state := await self.async_get_last_state()
        ) is not None:
            last_updated = dt_util.as_local(last_state.last_updated)
            if last_updated.date() == dt_util.now().date():
                try:
                    self._attr_native_value = int(last_data.native_value or 0)
                except (TypeError, ValueError):
                    self._attr_native_value = 0

        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{SIGNAL_USAGE_UPDATED}_{self.entry.entry_id}",
                self._handle_usage,
            )
        )
        self.async_on_remove(
            async_track_time_change(self.hass, self._handle_midnight, hour=0, minute=0, second=0)
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
