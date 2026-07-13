"""Tests for LiteLLMBaseLLMEntity._async_handle_chat_log (the tool loop)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.litellm_conversation.const import (
    MAX_TOOL_ITERATIONS,
    SIGNAL_USAGE_UPDATED,
)
from custom_components.litellm_conversation.entity import LiteLLMBaseLLMEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError


class _FakeChatLog:
    """Minimal stand-in for conversation.ChatLog.

    `script` is a list of per-iteration behaviours: each entry is a dict
    with `adds` (how many content items the stream appends) and
    `unresponded` (value of unresponded_tool_results after the iteration).
    """

    def __init__(self, script: list[dict]) -> None:
        self.llm_api = None
        self.content: list = [SimpleNamespace(role="user", content="hi", attachments=None)]
        self._script = script
        self._iteration = -1

    @property
    def unresponded_tool_results(self):
        return self._script[self._iteration]["unresponded"]

    async def async_add_delta_content_stream(self, entity_id, stream):
        self._iteration += 1
        step = self._script[self._iteration]
        # Drain the transform stream so usage_out gets populated.
        async for _ in stream:
            pass
        for _ in range(step["adds"]):
            self.content.append(SimpleNamespace(role="assistant", content="x", attachments=None))
        return
        yield  # pragma: no cover — make this an async generator


def _usage_chunk(total: int = 30):
    """A stream chunk carrying only usage (include_usage final chunk)."""
    return SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=20, total_tokens=total),
        choices=[],
    )


def _content_chunk(text: str = "hello"):
    return SimpleNamespace(
        usage=None,
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(content=text, tool_calls=None),
                finish_reason="stop",
            )
        ],
    )


class _Stream:
    """Async-iterable fake of openai.AsyncStream."""

    def __init__(self, chunks: list) -> None:
        self._chunks = chunks

    def __aiter__(self):
        self._it = iter(self._chunks)
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration from None


def _make_entity(hass: HomeAssistant, responses: list) -> LiteLLMBaseLLMEntity:
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.runtime_data = MagicMock()
    entry.runtime_data.chat.completions.create = AsyncMock(side_effect=responses)
    subentry = MagicMock()
    subentry.subentry_id = "sub1"
    subentry.title = "Test"
    subentry.data = {"chat_model": "test-model"}
    entity = LiteLLMBaseLLMEntity(entry, subentry)
    entity.hass = hass
    entity.entity_id = "conversation.test"
    return entity


async def test_single_turn_completes(hass: HomeAssistant) -> None:
    """One response with no tool calls finishes in one iteration."""
    chat_log = _FakeChatLog([{"adds": 1, "unresponded": False}])
    entity = _make_entity(hass, [_Stream([_content_chunk(), _usage_chunk()])])

    await entity._async_handle_chat_log(chat_log)

    assert entity.entry.runtime_data.chat.completions.create.await_count == 1


async def test_usage_dispatched_to_sensors(hass: HomeAssistant) -> None:
    """Token usage from the final chunk is dispatched with the model name."""
    chat_log = _FakeChatLog([{"adds": 1, "unresponded": False}])
    entity = _make_entity(hass, [_Stream([_content_chunk(), _usage_chunk(42)])])

    received = []
    with patch(
        "custom_components.litellm_conversation.entity.async_dispatcher_send",
        side_effect=lambda hass, signal, data: received.append((signal, data)),
    ):
        await entity._async_handle_chat_log(chat_log)

    assert received
    signal, data = received[0]
    assert signal == f"{SIGNAL_USAGE_UPDATED}_test_entry"
    assert data["model"] == "test-model"
    assert data["total_tokens"] == 42


async def test_empty_response_raises(hass: HomeAssistant) -> None:
    """A stream that adds nothing to the chat log raises a clear error."""
    chat_log = _FakeChatLog([{"adds": 0, "unresponded": False}])
    entity = _make_entity(hass, [_Stream([])])

    with pytest.raises(HomeAssistantError, match="returned no response"):
        await entity._async_handle_chat_log(chat_log)


async def test_tool_loop_iterates_then_completes(hass: HomeAssistant) -> None:
    """Unresponded tool results trigger another request; loop ends when done."""
    chat_log = _FakeChatLog(
        [
            {"adds": 2, "unresponded": True},  # tool call + result appended
            {"adds": 1, "unresponded": False},  # final answer
        ]
    )
    entity = _make_entity(
        hass,
        [
            _Stream([_content_chunk("calling tool")]),
            _Stream([_content_chunk("done")]),
        ],
    )

    await entity._async_handle_chat_log(chat_log)

    assert entity.entry.runtime_data.chat.completions.create.await_count == 2


async def test_tool_loop_exhaustion_raises(hass: HomeAssistant) -> None:
    """A model stuck calling tools forever hits the iteration limit."""
    limit = 3
    chat_log = _FakeChatLog([{"adds": 1, "unresponded": True}] * limit)
    entity = _make_entity(hass, [_Stream([_content_chunk()]) for _ in range(limit)])

    with pytest.raises(HomeAssistantError, match="did not finish after"):
        await entity._async_handle_chat_log(chat_log, max_iterations=limit)

    assert entity.entry.runtime_data.chat.completions.create.await_count == limit


async def test_api_error_mapped(hass: HomeAssistant) -> None:
    """openai errors are mapped to translated HomeAssistantErrors."""
    import openai

    chat_log = _FakeChatLog([{"adds": 1, "unresponded": False}])
    entity = _make_entity(
        hass,
        [openai.RateLimitError("slow down", response=MagicMock(status_code=429), body=None)],
    )

    with pytest.raises(HomeAssistantError):
        await entity._async_handle_chat_log(chat_log)


def test_default_iteration_limit_is_sane() -> None:
    """Guard against reintroducing an unbounded tool loop."""
    assert 1 < MAX_TOOL_ITERATIONS <= 25
