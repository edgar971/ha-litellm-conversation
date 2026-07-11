"""LiteLLM text-to-speech platform."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

import openai

from homeassistant.components.tts import (
    ATTR_VOICE,
    TextToSpeechEntity,
    TtsAudioType,
    Voice,
)
from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    CONF_TTS_MODEL,
    CONF_TTS_VOICE,
    DEFAULT_TTS_MODEL,
    DEFAULT_TTS_VOICE,
    LOGGER,
    TTS_VOICES,
)
from .entity import LiteLLMBaseLLMEntity

if TYPE_CHECKING:
    from . import LiteLLMConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: LiteLLMConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up TTS entities from a config entry."""
    for subentry in config_entry.subentries.values():
        if subentry.subentry_type != "tts":
            continue
        async_add_entities(
            [LiteLLMTTSEntity(config_entry, subentry)],
            config_subentry_id=subentry.subentry_id,
        )


class LiteLLMTTSEntity(TextToSpeechEntity, LiteLLMBaseLLMEntity):
    """LiteLLM text-to-speech entity (OpenAI-compatible /v1/audio/speech)."""

    _attr_supported_options: ClassVar[list[str]] = [ATTR_VOICE]

    def __init__(self, entry: LiteLLMConfigEntry, subentry: ConfigSubentry) -> None:
        """Initialize the TTS entity."""
        super().__init__(entry, subentry)

    @property
    def supported_languages(self) -> list[str]:
        """Return supported languages (OpenAI TTS is multilingual)."""
        return ["en", "es", "fr", "de", "it", "pt", "nl", "pl", "ru", "ja", "ko", "zh"]

    @property
    def default_language(self) -> str:
        """Return the default language."""
        return "en"

    @callback
    def async_get_supported_voices(self, language: str) -> list[Voice] | None:
        """Return supported voices for a language."""
        return [Voice(v, v.capitalize()) for v in TTS_VOICES]

    async def async_get_tts_audio(
        self, message: str, language: str, options: dict[str, Any]
    ) -> TtsAudioType:
        """Generate speech audio via the LiteLLM proxy."""
        model = self.subentry.data.get(CONF_TTS_MODEL, DEFAULT_TTS_MODEL)
        voice = options.get(
            ATTR_VOICE, self.subentry.data.get(CONF_TTS_VOICE, DEFAULT_TTS_VOICE)
        )

        try:
            response = await self.client.audio.speech.create(
                model=model,
                voice=voice,
                input=message,
                response_format="mp3",
                extra_body={"drop_params": True},
            )
        except openai.OpenAIError as err:
            LOGGER.error("TTS generation failed (model=%s): %s", model, err)
            return None, None

        return "mp3", response.content
