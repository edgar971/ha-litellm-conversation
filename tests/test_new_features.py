"""Tests for usage capture, web search / guardrails params, and new platforms."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from custom_components.litellm_conversation.entity import _transform_stream


def _chunk(
    *,
    content: str | None = None,
    finish_reason: str | None = None,
    usage: SimpleNamespace | None = None,
    choices: bool = True,
) -> SimpleNamespace:
    """Build a fake ChatCompletionChunk (optionally usage-only)."""
    if not choices:
        return SimpleNamespace(choices=[], usage=usage)
    delta = SimpleNamespace(content=content, tool_calls=None, reasoning_content=None)
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=delta, finish_reason=finish_reason)],
        usage=usage,
    )


async def _stream(chunks: list) -> Any:
    for c in chunks:
        yield c


async def test_usage_captured_from_final_chunk() -> None:
    """Token usage from the include_usage final chunk lands in usage_out."""
    usage_chunk = _chunk(
        choices=False,
        usage=SimpleNamespace(prompt_tokens=120, completion_tokens=30, total_tokens=150),
    )
    usage_out: dict[str, Any] = {}
    deltas = [
        d
        async for d in _transform_stream(
            _stream([_chunk(content="hi"), _chunk(finish_reason="stop"), usage_chunk]),
            usage_out,
        )
    ]
    assert deltas == [{"content": "hi"}]
    assert usage_out == {
        "prompt_tokens": 120,
        "completion_tokens": 30,
        "total_tokens": 150,
    }


async def test_usage_out_optional() -> None:
    """Streaming works without a usage_out dict (default None)."""
    deltas = [
        d
        async for d in _transform_stream(
            _stream([_chunk(content="ok"), _chunk(finish_reason="stop")])
        )
    ]
    assert deltas == [{"content": "ok"}]


def test_web_search_and_guardrails_constants() -> None:
    """New config keys exist and defaults are sane."""
    from custom_components.litellm_conversation import const

    assert const.CONF_WEB_SEARCH == "web_search"
    assert const.CONF_WEB_SEARCH_CONTEXT_SIZE == "web_search_context_size"
    assert const.CONF_GUARDRAILS == "guardrails"
    assert const.DEFAULT_WEB_SEARCH_CONTEXT_SIZE in const.WEB_SEARCH_CONTEXT_OPTIONS
    assert const.CONF_STT_MODEL == "stt_model"
    assert const.CONF_TTS_MODEL == "tts_model"
    assert const.DEFAULT_TTS_VOICE in const.TTS_VOICES


def test_clean_conversation_data_strips_new_fields() -> None:
    """Disabled web search / empty guardrails are removed from subentry data."""
    from custom_components.litellm_conversation.config_flow import (
        _clean_conversation_data,
    )

    data = {
        "chat_model": "gpt-4o-mini",
        "web_search": False,
        "web_search_context_size": "medium",
        "guardrails": "",
    }
    cleaned = _clean_conversation_data(dict(data))
    assert "web_search" not in cleaned
    assert "web_search_context_size" not in cleaned
    assert "guardrails" not in cleaned

    enabled = _clean_conversation_data(
        {"chat_model": "gpt-4o-mini", "web_search": True, "guardrails": "pii-mask"}
    )
    assert enabled["web_search"] is True
    assert enabled["guardrails"] == "pii-mask"


def test_subentry_types_registered() -> None:
    """STT and TTS subentry flows are registered."""
    from custom_components.litellm_conversation.config_flow import LiteLLMConfigFlow

    types = LiteLLMConfigFlow.async_get_supported_subentry_types(None)
    assert set(types) == {"conversation", "ai_task_data", "stt", "tts"}


def test_wav_header() -> None:
    """WAV header math is correct for 16kHz mono 16-bit PCM."""
    from custom_components.litellm_conversation.stt import _wav_header

    header = _wav_header(1000, 16000, 1, 16)
    assert header[:4] == b"RIFF"
    assert header[8:12] == b"WAVE"
    assert int.from_bytes(header[4:8], "little") == 1036
    assert int.from_bytes(header[24:28], "little") == 16000
    assert int.from_bytes(header[40:44], "little") == 1000
