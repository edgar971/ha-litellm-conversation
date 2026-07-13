"""Tests for the STT and TTS platforms."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import openai

from custom_components.litellm_conversation.stt import LiteLLMSTTEntity, _wav_header
from custom_components.litellm_conversation.tts import LiteLLMTTSEntity
from homeassistant.components.stt import (
    AudioBitRates,
    AudioChannels,
    AudioCodecs,
    AudioFormats,
    AudioSampleRates,
    SpeechMetadata,
    SpeechResultState,
)
from homeassistant.components.tts import ATTR_VOICE


def _entry_and_subentry(data: dict | None = None):
    entry = MagicMock()
    entry.runtime_data = MagicMock()
    subentry = MagicMock()
    subentry.subentry_id = "sub1"
    subentry.title = "Test"
    subentry.data = data or {}
    return entry, subentry


def _stt_entity(data: dict | None = None) -> LiteLLMSTTEntity:
    return LiteLLMSTTEntity(*_entry_and_subentry(data))


def _tts_entity(data: dict | None = None) -> LiteLLMTTSEntity:
    return LiteLLMTTSEntity(*_entry_and_subentry(data))


def _metadata(fmt: AudioFormats = AudioFormats.WAV) -> SpeechMetadata:
    return SpeechMetadata(
        language="en-US",
        format=fmt,
        codec=AudioCodecs.PCM,
        bit_rate=AudioBitRates.BITRATE_16,
        sample_rate=AudioSampleRates.SAMPLERATE_16000,
        channel=AudioChannels.CHANNEL_MONO,
    )


async def _stream(chunks: list[bytes]):
    for c in chunks:
        yield c


# --- STT ---


async def test_stt_wav_transcription() -> None:
    """WAV path prepends a RIFF header and returns the transcription."""
    entity = _stt_entity()
    entity.entry.runtime_data.audio.transcriptions.create = AsyncMock(
        return_value=SimpleNamespace(text="hello world")
    )

    result = await entity.async_process_audio_stream(_metadata(), _stream([b"pcm1", b"pcm2"]))

    assert result.result is SpeechResultState.SUCCESS
    assert result.text == "hello world"
    kwargs = entity.entry.runtime_data.audio.transcriptions.create.call_args.kwargs
    filename, file_data = kwargs["file"]
    assert filename == "audio.wav"
    assert file_data.startswith(b"RIFF")
    assert file_data.endswith(b"pcm1pcm2")
    assert kwargs["language"] == "en"  # region stripped


async def test_stt_ogg_passthrough() -> None:
    """OGG audio is sent as-is (no WAV header)."""
    entity = _stt_entity()
    entity.entry.runtime_data.audio.transcriptions.create = AsyncMock(
        return_value=SimpleNamespace(text="ok")
    )

    result = await entity.async_process_audio_stream(
        _metadata(AudioFormats.OGG), _stream([b"OggS..."])
    )

    assert result.result is SpeechResultState.SUCCESS
    filename, file_data = entity.entry.runtime_data.audio.transcriptions.create.call_args.kwargs[
        "file"
    ]
    assert filename == "audio.ogg"
    assert file_data == b"OggS..."


async def test_stt_empty_stream_errors() -> None:
    """No audio -> ERROR result, no API call."""
    entity = _stt_entity()
    entity.entry.runtime_data.audio.transcriptions.create = AsyncMock()

    result = await entity.async_process_audio_stream(_metadata(), _stream([]))

    assert result.result is SpeechResultState.ERROR
    entity.entry.runtime_data.audio.transcriptions.create.assert_not_awaited()


async def test_stt_api_error_returns_error_result() -> None:
    """openai errors surface as ERROR results, not exceptions."""
    entity = _stt_entity()
    entity.entry.runtime_data.audio.transcriptions.create = AsyncMock(
        side_effect=openai.APIConnectionError(request=MagicMock())
    )

    result = await entity.async_process_audio_stream(_metadata(), _stream([b"x"]))

    assert result.result is SpeechResultState.ERROR


def test_wav_header_fields() -> None:
    """WAV header encodes sizes and rates correctly."""
    header = _wav_header(1000, 16000, 1, 16)
    assert header[:4] == b"RIFF"
    assert int.from_bytes(header[4:8], "little") == 1036  # 36 + audio_len
    assert header[8:16] == b"WAVEfmt "
    assert int.from_bytes(header[24:28], "little") == 16000  # sample rate
    assert int.from_bytes(header[28:32], "little") == 32000  # byte rate
    assert int.from_bytes(header[-4:], "little") == 1000  # data length


# --- TTS ---


async def test_tts_audio_generated() -> None:
    """TTS returns mp3 bytes from the speech endpoint."""
    entity = _tts_entity({"tts_model": "tts-1", "tts_voice": "nova"})
    entity.entry.runtime_data.audio.speech.create = AsyncMock(
        return_value=SimpleNamespace(content=b"mp3bytes")
    )

    ext, data = await entity.async_get_tts_audio("hello", "en", {})

    assert (ext, data) == ("mp3", b"mp3bytes")
    kwargs = entity.entry.runtime_data.audio.speech.create.call_args.kwargs
    assert kwargs["model"] == "tts-1"
    assert kwargs["voice"] == "nova"  # subentry default used
    assert kwargs["extra_body"] == {"drop_params": True}


async def test_tts_voice_option_overrides_subentry() -> None:
    """A per-call voice option wins over the subentry default."""
    entity = _tts_entity({"tts_voice": "nova"})
    entity.entry.runtime_data.audio.speech.create = AsyncMock(
        return_value=SimpleNamespace(content=b"x")
    )

    await entity.async_get_tts_audio("hi", "en", {ATTR_VOICE: "onyx"})

    assert entity.entry.runtime_data.audio.speech.create.call_args.kwargs["voice"] == "onyx"


async def test_tts_api_error_returns_none() -> None:
    """openai errors return (None, None) rather than raising."""
    entity = _tts_entity()
    entity.entry.runtime_data.audio.speech.create = AsyncMock(
        side_effect=openai.APIConnectionError(request=MagicMock())
    )

    ext, data = await entity.async_get_tts_audio("hi", "en", {})

    assert ext is None and data is None
