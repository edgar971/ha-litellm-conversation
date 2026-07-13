"""Tests for the LiteLLM Extended Tools LLM API."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import voluptuous as vol

from custom_components.litellm_conversation.extended_tools import (
    EXTENDED_API_ID,
    CallServiceTool,
    ExtendedToolsAPI,
    FetchUrlTool,
    GetHistoryTool,
    _resolve_is_private,
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


def _mock_entry() -> MagicMock:
    """Mock LiteLLM config entry (loaded, with a client and one subentry)."""
    entry = MagicMock()
    entry.runtime_data = MagicMock()
    return entry


# --- registration ---


async def test_register_extended_api(hass: HomeAssistant) -> None:
    """Registering adds the API exactly once (idempotent)."""
    async_register_extended_api(hass, _mock_entry())
    apis = [api.id for api in llm.async_get_apis(hass)]
    assert EXTENDED_API_ID in apis

    # Second call must not raise or duplicate
    async_register_extended_api(hass, _mock_entry())
    apis = [api.id for api in llm.async_get_apis(hass)]
    assert apis.count(EXTENDED_API_ID) == 1


async def test_api_instance_without_assist(hass: HomeAssistant) -> None:
    """API instance falls back to extended tools only when Assist is unavailable."""
    api = ExtendedToolsAPI(hass, _mock_entry())
    with patch(
        "custom_components.litellm_conversation.extended_tools.llm.async_get_apis",
        return_value=[],
    ):
        instance = await api.async_get_api_instance(_llm_context())
    names = {tool.name for tool in instance.tools}
    assert names == {
        "call_service",
        "get_history",
        "fetch_url",
        "analyze_camera",
        "get_calendar_events",
        "add_todo_item",
    }


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

    api = ExtendedToolsAPI(hass, _mock_entry())
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


async def test_call_service_blocked_domains(hass: HomeAssistant) -> None:
    """System domains are refused even if the service exists."""
    hass.services.async_register("homeassistant", "restart", lambda call: None)
    tool = CallServiceTool()
    for domain in ("homeassistant", "hassio", "shell_command", "python_script", "recorder"):
        result = await tool.async_call(
            hass,
            _tool_input("call_service", {"domain": domain, "service": "restart"}),
            _llm_context(),
        )
        assert "not allowed" in result["error"], domain


async def test_call_service_returns_response_data(hass: HomeAssistant) -> None:
    """Services that support responses return their data to the model."""
    from homeassistant.core import ServiceResponse, SupportsResponse

    def _handler(call) -> ServiceResponse:
        return {"forecast": "sunny"}

    hass.services.async_register(
        "weather", "get_forecasts", _handler, supports_response=SupportsResponse.ONLY
    )
    tool = CallServiceTool()
    result = await tool.async_call(
        hass,
        _tool_input("call_service", {"domain": "weather", "service": "get_forecasts"}),
        _llm_context(),
    )
    assert result["success"] is True
    assert result["response"] == {"forecast": "sunny"}


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
    with pytest.raises(vol.Invalid):
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


async def test_fetch_url_rejects_private_addresses(hass: HomeAssistant) -> None:
    """URLs resolving to private/loopback ranges are blocked (SSRF guard)."""
    tool = FetchUrlTool()
    for url in (
        "http://192.168.1.1/admin",
        "http://127.0.0.1:8123/api",
        "http://10.0.0.5/",
        "http://[::1]/",
    ):
        result = await tool.async_call(hass, _tool_input("fetch_url", {"url": url}), _llm_context())
        assert result == {
            "error": "URLs resolving to private or local addresses are not allowed"
        }, url


def test_resolve_is_private() -> None:
    """IP literal classification for the SSRF guard."""
    assert _resolve_is_private("192.168.1.1") is True
    assert _resolve_is_private("127.0.0.1") is True
    assert _resolve_is_private("169.254.10.10") is True
    assert _resolve_is_private("8.8.8.8") is False


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


# --- new tools (v1.4.0): analyze_camera, get_calendar_events, add_todo_item ---

from custom_components.litellm_conversation.extended_tools import (  # noqa: E402
    AddTodoItemTool,
    AnalyzeCameraTool,
    GetCalendarEventsTool,
    _guard_entity,
)

EXPOSE_PATH = "homeassistant.components.homeassistant.exposed_entities.async_should_expose"


def _loaded_entry(model: str = "test-model") -> MagicMock:
    from homeassistant.config_entries import ConfigEntryState

    entry = _mock_entry()
    entry.state = ConfigEntryState.LOADED
    sub = MagicMock()
    sub.subentry_type = "conversation"
    sub.data = {"chat_model": model}
    entry.subentries = {"sub1": sub}
    return entry


# --- _guard_entity ---


async def test_guard_entity_wrong_domain(hass: HomeAssistant) -> None:
    """Non-matching domain is rejected."""
    result = _guard_entity(hass, "light.kitchen", "camera")
    assert "must be a camera entity" in result["error"]


async def test_guard_entity_missing(hass: HomeAssistant) -> None:
    """Missing entity is rejected."""
    result = _guard_entity(hass, "camera.nope", "camera")
    assert "not found" in result["error"]


async def test_guard_entity_not_exposed(hass: HomeAssistant) -> None:
    """Entities not exposed to Assist are rejected."""
    hass.states.async_set("camera.hidden", "idle")
    with patch(EXPOSE_PATH, return_value=False):
        result = _guard_entity(hass, "camera.hidden", "camera")
    assert "not exposed" in result["error"]


async def test_guard_entity_ok(hass: HomeAssistant) -> None:
    """Exposed, existing, domain-matching entity passes."""
    hass.states.async_set("camera.front", "idle")
    with patch(EXPOSE_PATH, return_value=True):
        assert _guard_entity(hass, "camera.front", "camera") is None


# --- analyze_camera ---


async def test_analyze_camera_happy_path(hass: HomeAssistant) -> None:
    """Snapshot -> nested vision call -> answer passthrough."""
    hass.states.async_set("camera.driveway", "idle")
    entry = _loaded_entry()
    completion = MagicMock()
    completion.choices = [MagicMock(message=MagicMock(content="A red car."))]
    entry.runtime_data.chat.completions.create = AsyncMock(return_value=completion)

    image = SimpleNamespace(content=b"jpegbytes", content_type="image/jpeg")
    tool = AnalyzeCameraTool(entry)
    with (
        patch(EXPOSE_PATH, return_value=True),
        patch(
            "homeassistant.components.camera.async_get_image",
            AsyncMock(return_value=image),
        ),
    ):
        result = await tool.async_call(
            hass,
            _tool_input(
                "analyze_camera",
                {"entity_id": "camera.driveway", "question": "What do you see?"},
            ),
            _llm_context(),
        )

    assert result == {"camera": "camera.driveway", "answer": "A red car."}
    call_kwargs = entry.runtime_data.chat.completions.create.call_args.kwargs
    assert call_kwargs["model"] == "test-model"
    user_msg = call_kwargs["messages"][1]
    assert user_msg["content"][0] == {"type": "text", "text": "What do you see?"}
    assert user_msg["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


async def test_analyze_camera_not_exposed(hass: HomeAssistant) -> None:
    """Unexposed cameras are refused (prompt-injection snooping guard)."""
    hass.states.async_set("camera.secret", "idle")
    tool = AnalyzeCameraTool(_loaded_entry())
    with patch(EXPOSE_PATH, return_value=False):
        result = await tool.async_call(
            hass,
            _tool_input("analyze_camera", {"entity_id": "camera.secret", "question": "?"}),
            _llm_context(),
        )
    assert "not exposed" in result["error"]


async def test_analyze_camera_entry_not_loaded(hass: HomeAssistant) -> None:
    """Unloaded config entry produces an error dict, not a crash."""
    from homeassistant.config_entries import ConfigEntryState

    hass.states.async_set("camera.front", "idle")
    entry = _loaded_entry()
    entry.state = ConfigEntryState.NOT_LOADED
    tool = AnalyzeCameraTool(entry)
    with patch(EXPOSE_PATH, return_value=True):
        result = await tool.async_call(
            hass,
            _tool_input("analyze_camera", {"entity_id": "camera.front", "question": "?"}),
            _llm_context(),
        )
    assert "not loaded" in result["error"]


async def test_analyze_camera_snapshot_error(hass: HomeAssistant) -> None:
    """Camera errors surface as an error dict."""
    hass.states.async_set("camera.front", "idle")
    tool = AnalyzeCameraTool(_loaded_entry())
    with (
        patch(EXPOSE_PATH, return_value=True),
        patch(
            "homeassistant.components.camera.async_get_image",
            AsyncMock(side_effect=HomeAssistantError("offline")),
        ),
    ):
        result = await tool.async_call(
            hass,
            _tool_input("analyze_camera", {"entity_id": "camera.front", "question": "?"}),
            _llm_context(),
        )
    assert "Could not get camera image" in result["error"]


# --- get_calendar_events ---


async def test_get_calendar_events(hass: HomeAssistant) -> None:
    """Events come back from the calendar.get_events response service."""
    from homeassistant.core import SupportsResponse

    hass.states.async_set("calendar.family", "off")
    events = [{"summary": "Dentist", "start": "2026-07-14T10:00:00"}]

    def _handler(call):
        return {"calendar.family": {"events": events}}

    hass.services.async_register(
        "calendar", "get_events", _handler, supports_response=SupportsResponse.ONLY
    )
    tool = GetCalendarEventsTool()
    with patch(EXPOSE_PATH, return_value=True):
        result = await tool.async_call(
            hass,
            _tool_input(
                "get_calendar_events",
                {"entity_id": "calendar.family", "days_ahead": 3},
            ),
            _llm_context(),
        )
    assert result["calendar"] == "calendar.family"
    assert result["days_ahead"] == 3
    assert result["events"] == events


async def test_get_calendar_events_wrong_domain(hass: HomeAssistant) -> None:
    """Non-calendar entity is rejected."""
    tool = GetCalendarEventsTool()
    result = await tool.async_call(
        hass,
        _tool_input("get_calendar_events", {"entity_id": "light.kitchen"}),
        _llm_context(),
    )
    assert "must be a calendar entity" in result["error"]


# --- add_todo_item ---


async def test_add_todo_item(hass: HomeAssistant) -> None:
    """Item is added via todo.add_item."""
    hass.states.async_set("todo.shopping_list", "3")
    calls = []
    hass.services.async_register("todo", "add_item", lambda call: calls.append(call.data))
    tool = AddTodoItemTool()
    with patch(EXPOSE_PATH, return_value=True):
        result = await tool.async_call(
            hass,
            _tool_input(
                "add_todo_item",
                {"entity_id": "todo.shopping_list", "item": "milk"},
            ),
            _llm_context(),
        )
    assert result == {"success": True, "list": "todo.shopping_list", "item": "milk"}
    assert calls[0]["item"] == "milk"


async def test_add_todo_item_optional_fields(hass: HomeAssistant) -> None:
    """description and due_date pass through when provided."""
    hass.states.async_set("todo.chores", "0")
    calls = []
    hass.services.async_register("todo", "add_item", lambda call: calls.append(call.data))
    tool = AddTodoItemTool()
    with patch(EXPOSE_PATH, return_value=True):
        await tool.async_call(
            hass,
            _tool_input(
                "add_todo_item",
                {
                    "entity_id": "todo.chores",
                    "item": "mow lawn",
                    "description": "back yard too",
                    "due_date": "2026-07-20",
                },
            ),
            _llm_context(),
        )
    assert calls[0]["description"] == "back yard too"
    assert calls[0]["due_date"] == "2026-07-20"


async def test_new_tools_registered_in_api(hass: HomeAssistant) -> None:
    """The API instance includes the new tools."""
    api = ExtendedToolsAPI(hass, _loaded_entry())
    with patch(
        "custom_components.litellm_conversation.extended_tools.llm.async_get_apis",
        return_value=[],
    ):
        instance = await api.async_get_api_instance(_llm_context())
    names = {tool.name for tool in instance.tools}
    assert {"analyze_camera", "get_calendar_events", "add_todo_item"} <= names
