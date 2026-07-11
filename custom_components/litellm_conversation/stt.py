"""LiteLLM speech-to-text platform."""

from __future__ import annotations

from collections.abc import AsyncIterable
from typing import TYPE_CHECKING

import openai

from homeassistant.components.stt import (
    AudioBitRates,
    AudioChannels,
    AudioCodecs,
    AudioFormats,
    AudioSampleRates,
    SpeechMetadata,
    SpeechResult,
    SpeechResultState,
    SpeechToTextEntity,
)
from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONF_STT_MODEL, DEFAULT_STT_MODEL, LOGGER
from .entity import LiteLLMBaseLLMEntity

if TYPE_CHECKING:
    from . import LiteLLMConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: LiteLLMConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up STT entities from a config entry."""
    for subentry in config_entry.subentries.values():
        if subentry.subentry_type != "stt":
            continue
        async_add_entities(
            [LiteLLMSTTEntity(config_entry, subentry)],
            config_subentry_id=subentry.subentry_id,
        )


def _wav_header(audio_len: int, sample_rate: int, channels: int, bit_rate: int) -> bytes:
    """Build a WAV/RIFF header for raw PCM data."""
    byte_rate = sample_rate * channels * bit_rate // 8
    block_align = channels * bit_rate // 8
    return (
        b"RIFF"
        + (36 + audio_len).to_bytes(4, "little")
        + b"WAVEfmt "
        + (16).to_bytes(4, "little")
        + (1).to_bytes(2, "little")  # PCM
        + channels.to_bytes(2, "little")
        + sample_rate.to_bytes(4, "little")
        + byte_rate.to_bytes(4, "little")
        + block_align.to_bytes(2, "little")
        + bit_rate.to_bytes(2, "little")
        + b"data"
        + audio_len.to_bytes(4, "little")
    )


class LiteLLMSTTEntity(SpeechToTextEntity, LiteLLMBaseLLMEntity):
    """LiteLLM speech-to-text entity (Whisper-compatible)."""

    def __init__(self, entry: LiteLLMConfigEntry, subentry: ConfigSubentry) -> None:
        """Initialize the STT entity."""
        super().__init__(entry, subentry)

    @property
    def supported_languages(self) -> list[str]:
        """Return a list of supported languages (Whisper is multilingual)."""
        return [
            "af", "ar", "az", "be", "bg", "bs", "ca", "cs", "cy", "da", "de",
            "el", "en", "es", "et", "fa", "fi", "fr", "gl", "he", "hi", "hr",
            "hu", "hy", "id", "is", "it", "ja", "kk", "kn", "ko", "lt", "lv",
            "mi", "mk", "mr", "ms", "ne", "nl", "no", "pl", "pt", "ro", "ru",
            "sk", "sl", "sr", "sv", "sw", "ta", "th", "tl", "tr", "uk", "ur",
            "vi", "zh",
        ]

    @property
    def supported_formats(self) -> list[AudioFormats]:
        """Return supported audio formats."""
        return [AudioFormats.WAV, AudioFormats.OGG]

    @property
    def supported_codecs(self) -> list[AudioCodecs]:
        """Return supported audio codecs."""
        return [AudioCodecs.PCM, AudioCodecs.OPUS]

    @property
    def supported_bit_rates(self) -> list[AudioBitRates]:
        """Return supported bit rates."""
        return [AudioBitRates.BITRATE_16]

    @property
    def supported_sample_rates(self) -> list[AudioSampleRates]:
        """Return supported sample rates."""
        return [AudioSampleRates.SAMPLERATE_16000]

    @property
    def supported_channels(self) -> list[AudioChannels]:
        """Return supported channels."""
        return [AudioChannels.CHANNEL_MONO]

    async def async_process_audio_stream(
        self, metadata: SpeechMetadata, stream: AsyncIterable[bytes]
    ) -> SpeechResult:
        """Transcribe an audio stream via the LiteLLM proxy."""
        audio = b""
        async for chunk in stream:
            audio += chunk

        if not audio:
            return SpeechResult(None, SpeechResultState.ERROR)

        if metadata.format == AudioFormats.WAV:
            filename = "audio.wav"
            file_data = (
                _wav_header(
                    len(audio),
                    metadata.sample_rate,
                    metadata.channel,
                    metadata.bit_rate,
                )
                + audio
            )
        else:
            filename = "audio.ogg"
            file_data = audio

        model = self.subentry.data.get(CONF_STT_MODEL, DEFAULT_STT_MODEL)

        try:
            transcription = await self.client.audio.transcriptions.create(
                model=model,
                file=(filename, file_data),
                language=metadata.language.split("-")[0],
                extra_body={"drop_params": True},
            )
        except openai.OpenAIError as err:
            LOGGER.error("STT transcription failed (model=%s): %s", model, err)
            return SpeechResult(None, SpeechResultState.ERROR)

        return SpeechResult(transcription.text, SpeechResultState.SUCCESS)
