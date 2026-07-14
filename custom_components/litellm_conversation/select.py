"""Select platform: dream model, a live dropdown of proxy models.

Mirrors the config-flow model dropdown (same live /v1/models fetch) so the
nightly dreaming pass can use a cheap model without hand-typing a model id
into a blueprint text field. Selection persists across restarts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.select import SelectEntity
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import CONF_BASE_URL, DOMAIN

if TYPE_CHECKING:
    from . import LiteLLMConfigEntry

USE_DEFAULT_OPTION = "Use AI Task default"


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: LiteLLMConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the dream model select entity."""
    # Reuse the model list fetched during entry setup's connection check
    # (async_setup_entry in __init__.py) instead of a second live call.
    models = hass.data.get(DOMAIN, {}).get(f"{config_entry.entry_id}_models")
    if models is None:
        from .config_flow import _get_models  # fallback: live fetch

        models = await _get_models(
            hass, config_entry.data[CONF_BASE_URL], config_entry.data[CONF_API_KEY]
        )
    async_add_entities([LiteLLMDreamModelSelect(config_entry, models)])


class LiteLLMDreamModelSelect(SelectEntity, RestoreEntity):
    """Dropdown of live proxy models used to override the dream call's model.

    Defaults to "Use AI Task default" (the previous behavior). Pick a
    cheap/fast model here to keep nightly dreams inexpensive without editing
    any automation — the dream service call reads this entity automatically
    when no explicit model is passed.
    """

    _attr_has_entity_name = True
    _attr_name = "Dream model"
    _attr_icon = "mdi:sleep"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_should_poll = False

    def __init__(self, entry: LiteLLMConfigEntry, models: list[str]) -> None:
        """Initialize the select entity."""
        self._attr_unique_id = f"{entry.entry_id}_dream_model"
        self._attr_options = [USE_DEFAULT_OPTION, *models]
        self._attr_current_option = USE_DEFAULT_OPTION
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "LiteLLM Proxy",
            "entry_type": "service",
        }

    async def async_added_to_hass(self) -> None:
        """Restore the previously selected model and register for lookup."""
        await super().async_added_to_hass()
        if (
            last_state := await self.async_get_last_state()
        ) is not None and last_state.state in self._attr_options:
            self._attr_current_option = last_state.state
        self.hass.data.setdefault(DOMAIN, {})["dream_model_entity"] = self

    async def async_will_remove_from_hass(self) -> None:
        """Deregister on removal."""
        domain_data = self.hass.data.get(DOMAIN, {})
        if domain_data.get("dream_model_entity") is self:
            domain_data.pop("dream_model_entity", None)

    async def async_select_option(self, option: str) -> None:
        """Change the selected dream model."""
        self._attr_current_option = option
        self.async_write_ha_state()

    async def async_refresh_models(self, models: list[str]) -> None:
        """Update the option list from a fresh /v1/models fetch.

        The model list is otherwise a startup snapshot — a model added to
        the proxy after HA started wouldn't appear here until reload/restart.
        Called by the litellm_conversation.refresh_models service.
        """
        current = self._attr_current_option
        self._attr_options = [USE_DEFAULT_OPTION, *models]
        if current not in self._attr_options:
            # The previously selected model disappeared from the proxy —
            # fall back rather than keep an invalid current_option.
            current = USE_DEFAULT_OPTION
        self._attr_current_option = current
        self.async_write_ha_state()

    @property
    def selected_model(self) -> str | None:
        """Return the model id to use for dreaming, or None for the default."""
        if self._attr_current_option in (None, USE_DEFAULT_OPTION):
            return None
        return self._attr_current_option


def async_get_selected_dream_model(hass: HomeAssistant) -> str | None:
    """Return the currently selected dream model, if the select entity exists."""
    entity = hass.data.get(DOMAIN, {}).get("dream_model_entity")
    if entity is None:
        return None
    return entity.selected_model


async def async_refresh_dream_model_options(hass: HomeAssistant, entry: LiteLLMConfigEntry) -> bool:
    """Refetch the proxy's model list and update the dream-model select entity.

    Returns True if the select entity was found and refreshed, False if no
    entity is registered yet (e.g. select platform hasn't finished loading).
    """
    from .config_flow import _get_models

    entity = hass.data.get(DOMAIN, {}).get("dream_model_entity")
    if entity is None:
        return False

    models = await _get_models(hass, entry.data[CONF_BASE_URL], entry.data[CONF_API_KEY])
    if models:
        # Also refresh the cached list __init__.py seeded at startup, so any
        # future select-platform reload picks up the same fresh data.
        hass.data.setdefault(DOMAIN, {})[f"{entry.entry_id}_models"] = models
    await entity.async_refresh_models(models)
    return True
