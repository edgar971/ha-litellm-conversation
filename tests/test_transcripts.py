"""Tests for the transcript buffer and capture switch."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

from custom_components.litellm_conversation.switch import LiteLLMTranscriptCaptureSwitch
from custom_components.litellm_conversation.transcripts import (
    MAX_EXCHANGES,
    TranscriptBuffer,
    async_get_transcript_buffer,
)
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util


async def _buffer(hass: HomeAssistant) -> TranscriptBuffer:
    buffer = TranscriptBuffer(hass)
    await buffer.async_load()
    return buffer


async def test_add_and_read_exchanges(hass: HomeAssistant) -> None:
    """Exchanges are recorded with text and conversation id."""
    buffer = await _buffer(hass)
    buffer.add_exchange("turn on the lights", "Done, lights are on.", "conv1")
    assert buffer.exchange_count == 1
    e = buffer.exchanges_since_last_dream()[0]
    assert e.user_text == "turn on the lights"
    assert e.assistant_text == "Done, lights are on."
    assert e.conversation_id == "conv1"


async def test_capture_disabled_is_noop(hass: HomeAssistant) -> None:
    """No exchanges are recorded while capture is off."""
    buffer = await _buffer(hass)
    buffer.set_capture_enabled(False)
    buffer.add_exchange("secret chat", "reply", "conv1")
    assert buffer.exchange_count == 0
    # Re-enabling resumes capture; prior buffer preserved semantics
    buffer.set_capture_enabled(True)
    buffer.add_exchange("hello", "hi", "conv2")
    assert buffer.exchange_count == 1


async def test_empty_text_skipped(hass: HomeAssistant) -> None:
    """Blank user or assistant text is not recorded."""
    buffer = await _buffer(hass)
    buffer.add_exchange("   ", "reply", "c")
    buffer.add_exchange("hi", "", "c")
    assert buffer.exchange_count == 0


async def test_count_trim(hass: HomeAssistant) -> None:
    """The ring buffer keeps only the newest MAX_EXCHANGES."""
    buffer = await _buffer(hass)
    for i in range(MAX_EXCHANGES + 25):
        buffer.add_exchange(f"q{i}", f"a{i}", "c")
    assert buffer.exchange_count == MAX_EXCHANGES
    assert buffer.exchanges_since_last_dream()[0].user_text == "q25"


async def test_age_trim(hass: HomeAssistant) -> None:
    """Exchanges older than the age cap are dropped on trim."""
    buffer = await _buffer(hass)
    buffer.add_exchange("old", "old answer", "c")
    buffer._exchanges[0].when = (dt_util.now() - timedelta(days=8)).isoformat()
    buffer.add_exchange("new", "new answer", "c")  # triggers trim
    texts = [e.user_text for e in buffer.exchanges_since_last_dream()]
    assert texts == ["new"]


async def test_watermark(hass: HomeAssistant) -> None:
    """mark_dreamed hides older exchanges from the next dream."""
    buffer = await _buffer(hass)
    buffer.add_exchange("before", "a", "c")
    buffer.mark_dreamed()
    assert buffer.exchanges_since_last_dream() == []
    buffer.add_exchange("after", "a", "c")
    texts = [e.user_text for e in buffer.exchanges_since_last_dream()]
    assert texts == ["after"]


async def test_clear(hass: HomeAssistant) -> None:
    """clear() wipes and reports the count."""
    buffer = await _buffer(hass)
    buffer.add_exchange("a", "b", "c")
    buffer.add_exchange("d", "e", "f")
    assert buffer.clear() == 2
    assert buffer.exchange_count == 0


async def test_persistence_roundtrip(hass: HomeAssistant) -> None:
    """Buffer state (exchanges, capture flag, watermark) survives reload."""
    buffer = await _buffer(hass)
    buffer.add_exchange("durable", "answer", "c")
    buffer.set_capture_enabled(False)
    buffer.mark_dreamed()
    await buffer._store.async_save(
        {
            "exchanges": [e.as_dict() for e in buffer._exchanges],
            "capture_enabled": buffer.capture_enabled,
            "last_dream_at": buffer.last_dream_at,
        }
    )

    fresh = TranscriptBuffer(hass)
    await fresh.async_load()
    assert fresh.exchange_count == 1
    assert fresh.capture_enabled is False
    assert fresh.last_dream_at is not None


async def test_singleton(hass: HomeAssistant) -> None:
    """async_get_transcript_buffer returns the same instance."""
    assert async_get_transcript_buffer(hass) is async_get_transcript_buffer(hass)


async def test_switch_toggles_capture(hass: HomeAssistant) -> None:
    """The switch controls the buffer's capture flag and exposes stats."""
    buffer = await _buffer(hass)
    entry = MagicMock()
    entry.entry_id = "e1"
    switch = LiteLLMTranscriptCaptureSwitch(entry, buffer)
    switch.hass = hass
    switch.entity_id = "switch.test_capture"

    assert switch.is_on is True
    await switch.async_turn_off()
    assert buffer.capture_enabled is False
    await switch.async_turn_on()
    assert buffer.capture_enabled is True

    buffer.add_exchange("q", "a", "c")
    attrs = switch.extra_state_attributes
    assert attrs["buffered_exchanges"] == 1
