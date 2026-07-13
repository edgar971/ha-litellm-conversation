"""Tests for ai_task result handling, util helpers, and diagnostics."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.litellm_conversation.ai_task import LiteLLMAITaskEntity
from custom_components.litellm_conversation.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.litellm_conversation.util import normalize_base_url
from homeassistant.components import conversation
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

# --- util.normalize_base_url ---


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://llm.example.com", "https://llm.example.com/v1"),
        ("https://llm.example.com/", "https://llm.example.com/v1"),
        ("https://llm.example.com/v1", "https://llm.example.com/v1"),
        ("https://llm.example.com/v1/", "https://llm.example.com/v1"),
        ("http://192.168.1.10:4000", "http://192.168.1.10:4000/v1"),
    ],
)
def test_normalize_base_url(raw: str, expected: str) -> None:
    """Trailing slashes stripped, /v1 appended exactly once."""
    assert normalize_base_url(raw) == expected


# --- ai_task result handling ---


def _ai_task_entity() -> LiteLLMAITaskEntity:
    entry = MagicMock()
    subentry = MagicMock()
    subentry.subentry_id = "sub1"
    subentry.title = "AI Task"
    subentry.data = {}
    return LiteLLMAITaskEntity(entry, subentry)


def _chat_log(last_text: str) -> MagicMock:
    chat_log = MagicMock()
    chat_log.conversation_id = "conv1"
    chat_log.content = [conversation.AssistantContent(agent_id="x", content=last_text)]
    return chat_log


def _task(structure=None) -> SimpleNamespace:
    return SimpleNamespace(name="task", structure=structure)


async def test_ai_task_plain_text_result() -> None:
    """Without a structure, raw text is returned."""
    entity = _ai_task_entity()
    with patch.object(entity, "_async_handle_chat_log", AsyncMock()):
        result = await entity._async_generate_data(_task(), _chat_log("plain answer"))
    assert result.data == "plain answer"
    assert result.conversation_id == "conv1"


async def test_ai_task_structured_result_parsed() -> None:
    """With a structure, the model's JSON text is parsed."""
    entity = _ai_task_entity()
    with patch.object(entity, "_async_handle_chat_log", AsyncMock()):
        result = await entity._async_generate_data(
            _task(structure={"x": "schema"}), _chat_log('{"package": true}')
        )
    assert result.data == {"package": True}


async def test_ai_task_invalid_json_raises() -> None:
    """Malformed JSON from the model raises a clear error."""
    entity = _ai_task_entity()
    with (
        patch.object(entity, "_async_handle_chat_log", AsyncMock()),
        pytest.raises(HomeAssistantError, match="structured response"),
    ):
        await entity._async_generate_data(
            _task(structure={"x": "schema"}), _chat_log("not json {{{")
        )


async def test_ai_task_non_assistant_tail_raises() -> None:
    """A chat log not ending in AssistantContent is an error."""
    entity = _ai_task_entity()
    chat_log = MagicMock()
    chat_log.content = [conversation.UserContent(content="hi")]
    with (
        patch.object(entity, "_async_handle_chat_log", AsyncMock()),
        pytest.raises(HomeAssistantError, match="not an AssistantContent"),
    ):
        await entity._async_generate_data(_task(), chat_log)


# --- diagnostics ---


async def test_diagnostics_redacts_api_key(hass: HomeAssistant) -> None:
    """The API key is redacted; other data passes through."""
    entry = MagicMock()
    entry.data = {"api_key": "sk-secret", "base_url": "https://llm.example.com/v1"}
    sub = MagicMock()
    sub.data = {"chat_model": "test-model"}
    entry.subentries = {"sub1": sub}

    diag = await async_get_config_entry_diagnostics(hass, entry)

    assert diag["entry_data"]["api_key"] == "**REDACTED**"
    assert diag["entry_data"]["base_url"] == "https://llm.example.com/v1"
    assert diag["subentries"]["sub1"]["chat_model"] == "test-model"
