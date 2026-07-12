"""Tests for the LiteLLM Extended Tools LLM API."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.litellm_conversation.extended_tools import (
    EXTENDED_API_ID,
    CallServiceTool,
    ExtendedToolsAPI,
    FetchUrlTool,
    GetHistoryTool,
    async_register_extended_api,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import llm


def _llm_context() -> llm.LLMContext:
    return llm.LLMContext(
        platform="litellm_conversation",
        context=None,
        language="en",
        assistant=None,
        device_id=None,
    )


def _tool_input(name: str, args: dict) -> llm.ToolInput:
    return llm.ToolInput(tool_name=name, tool_args=args)


# --- registration ---


async def test_register_extended_api(hass: HomeAssistant) -> None:
    """Registering adds the API exactly once (idempotent)."""
    async_register_extended_api(hass)
    apis = [api.id for api in llm.async_get_apis(hass)]
    assert EXTENDED_API_ID in apis

    # Second call must not raise or duplicate
    async_register_extended_api(hass)
    apis = [api.id for api in llm.async_get_apis(hass)]
    assert apis.count(EXTENDED_API_ID) == 1


async def test_api_instance_without_assist(hass: HomeAssistant) -> None:
    """API instance falls back to extended tools only when Assist is unavailable."""
    api = ExtendedToolsAPI(hass)
    with patch(
        "custom_components.litellm_conversation.extended_tools.llm.async_get_apis",
        return_value=[],
    ):
        instance = await api.async_get_api_instance(_llm_context())
    names = {tool.name for tool in instance.tools}
    assert names == {"call_service", "get_history", "fetch_url"}


async def test_api_instance_merges_assist_tools(hass: HomeAssistant) -> None:
    """API instance layers extended tools on top of Assist tools."""
    assist_tool = MagicMock(spec=llm.Tool)
    assist_tool.name = "HassTurnOn"
    assist_instance = MagicMock(spec=llm.APIInstance)
    assist_instance.tools = [assist_tool]
    assist_instance.api_prompt = "Assist prompt."
    assist_instance.custom_serializer = None

    assist_api = MagicMock()
    assist_api.id = llm.LLM_API_ASSIST
    assist_api.async_get_api_instance = AsyncMock(return_value=assist_instance)

    api = ExtendedToolsAPI(hass)
    with patch(
        "custom_components.litellm_conversation.extended_tools.llm.async_get_apis",
        return_value=[assist_api],
    ):
        instance = await api.async_get_api_instance(_llm_context())

    names = {tool.name for tool in instance.tools}
    assert {"HassTurnOn", "call_service", "get_history", "fetch_url"} <= names
    assert instance.api_prompt.startswith("Assist prompt.")
    assert "call_service" in instance.api_prompt


# --- call_service ---


async def test_call_service_success(hass: HomeAssistant) -> None:
    """A valid service call succeeds."""
    calls = []
    hass.services.async_register("light", "turn_on", lambda call: calls.append(call.data))
    tool = CallServiceTool()
    result = await tool.async_call(
        hass,
        _tool_input(
            "call_service",
            {"domain": "light", "service": "turn_on", "data": {"brightness": 128}},
        ),
        _llm_context(),
    )
    assert result == {"success": True}
    assert calls and calls[0]["brightness"] == 128


async def test_call_service_unknown_service(hass: HomeAssistant) -> None:
    """Unknown services return an error dict instead of raising."""
    tool = CallServiceTool()
    result = await tool.async_call(
        hass,
        _tool_input("call_service", {"domain": "nope", "service": "missing"}),
        _llm_context(),
    )
    assert "error" in result
    assert "nope.missing" in result["error"]


async def test_call_service_ha_error(hass: HomeAssistant) -> None:
    """HomeAssistantError from the service surfaces as an error dict."""

    def _boom(call):
        raise HomeAssistantError("kaboom")

    hass.services.async_register("script", "fail", _boom)
    tool = CallServiceTool()
    result = await tool.async_call(
        hass,
        _tool_input("call_service", {"domain": "script", "service": "fail"}),
        _llm_context(),
    )
    assert result == {"error": "kaboom"}


# --- get_history ---


async def test_get_history_entity_not_found(hass: HomeAssistant) -> None:
    """Missing entity returns an error dict."""
    tool = GetHistoryTool()
    result = await tool.async_call(
        hass,
        _tool_input("get_history", {"entity_id": "sensor.nonexistent"}),
        _llm_context(),
    )
    assert "error" in result


async def test_get_history_returns_changes(hass: HomeAssistant) -> None:
    """History states are mapped to state/when dicts."""
    hass.states.async_set("sensor.temp", "21.5")
    fake_state = SimpleNamespace(
        state="21.5",
        last_changed=datetime(2026, 7, 12, 10, 0, tzinfo=UTC),
    )
    fake_instance = MagicMock()
    fake_instance.async_add_executor_job = AsyncMock(return_value={"sensor.temp": [fake_state]})
    with patch(
        "homeassistant.components.recorder.get_instance",
        return_value=fake_instance,
    ):
        tool = GetHistoryTool()
        result = await tool.async_call(
            hass,
            _tool_input("get_history", {"entity_id": "sensor.temp", "hours_ago": 48}),
            _llm_context(),
        )
    assert result["entity_id"] == "sensor.temp"
    assert result["hours"] == 48
    assert result["changes"] == [{"state": "21.5", "when": "2026-07-12T10:00:00+00:00"}]


def test_get_history_hours_schema() -> None:
    """hours_ago is capped at 168 by the schema."""
    tool = GetHistoryTool()
    with pytest.raises(Exception):  # noqa: B017 - vol.Invalid subclass
        tool.parameters({"entity_id": "sensor.x", "hours_ago": 9999})
    validated = tool.parameters({"entity_id": "sensor.x", "hours_ago": "24"})
    assert validated["hours_ago"] == 24


# --- fetch_url ---


async def test_fetch_url_rejects_non_http(hass: HomeAssistant) -> None:
    """Non-http(s) schemes are rejected."""
    tool = FetchUrlTool()
    result = await tool.async_call(
        hass,
        _tool_input("fetch_url", {"url": "file:///etc/passwd"}),
        _llm_context(),
    )
    assert result == {"error": "Only http/https URLs are allowed"}


async def test_fetch_url_success(hass: HomeAssistant) -> None:
    """Successful fetch returns status, content type and truncated body."""
    response = MagicMock()
    response.status_code = 200
    response.headers = {"content-type": "application/json"}
    response.text = '{"ok": true}'
    client = MagicMock()
    client.get = AsyncMock(return_value=response)
    with patch(
        "custom_components.litellm_conversation.extended_tools.get_async_client",
        return_value=client,
    ):
        tool = FetchUrlTool()
        result = await tool.async_call(
            hass,
            _tool_input("fetch_url", {"url": "https://api.example.com/data"}),
            _llm_context(),
        )
    assert result == {
        "status": 200,
        "content_type": "application/json",
        "body": '{"ok": true}',
    }


async def test_fetch_url_error(hass: HomeAssistant) -> None:
    """Network errors surface as error dicts."""
    client = MagicMock()
    client.get = AsyncMock(side_effect=OSError("connection refused"))
    with patch(
        "custom_components.litellm_conversation.extended_tools.get_async_client",
        return_value=client,
    ):
        tool = FetchUrlTool()
        result = await tool.async_call(
            hass,
            _tool_input("fetch_url", {"url": "https://down.example.com"}),
            _llm_context(),
        )
    assert "error" in result
    assert "connection refused" in result["error"]
