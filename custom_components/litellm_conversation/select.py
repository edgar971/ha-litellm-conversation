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
    from .config_flow import _get_models  # reuse the same live model fetch

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
