"""Tests for the LiteLLM Extended Tools LLM API."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import voluptuous as vol

from custom_components.litellm_conversation.const import DOMAIN
from custom_components.litellm_conversation.entity import _format_tool
from custom_components.litellm_conversation.extended_tools import (
    EXTENDED_API_ID,
    EXTENDED_API_UNREGISTER_KEY,
    CallServiceTool,
    ExtendedToolsAPI,
    FetchUrlTool,
    GetHistoryTool,
    _resolve_is_private,
    async_register_extended_api,
    async_release_extended_api,
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
    entry.runtime_data.with_options.return_value = entry.runtime_data
    return entry


EXPOSE_PATH = "homeassistant.components.homeassistant.exposed_entities.async_should_expose"


@pytest.fixture
def public_host():
    """Treat fetch_url hosts as public; tests must not perform real DNS lookups."""
    with patch(
        "custom_components.litellm_conversation.extended_tools._resolve_is_private",
        return_value=False,
    ):
        yield


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


async def test_register_extended_api_stores_unregister_handle(hass: HomeAssistant) -> None:
    """The unregister handle from llm.async_register_api is kept in hass.data (C3)."""
    unregister = MagicMock()
    with patch(
        "custom_components.litellm_conversation.extended_tools.llm.async_register_api",
        return_value=unregister,
    ):
        async_register_extended_api(hass, _mock_entry())
    assert hass.data[DOMAIN][EXTENDED_API_UNREGISTER_KEY] is unregister


def _entry_with_state(entry_id: str, state: object) -> MagicMock:
    entry = MagicMock()
    entry.entry_id = entry_id
    entry.state = state
    return entry


async def test_release_extended_api_unregisters_last_entry(hass: HomeAssistant) -> None:
    """Unloading the last config entry unregisters the API for real (C3)."""
    from homeassistant.config_entries import ConfigEntryState

    async_register_extended_api(hass, _mock_entry())
    assert EXTENDED_API_ID in [api.id for api in llm.async_get_apis(hass)]
    # Spy on the real unregister handle so we can assert both the call and
    # the actual de-registration.
    unregister = MagicMock(side_effect=hass.data[DOMAIN].pop(EXTENDED_API_UNREGISTER_KEY))
    hass.data[DOMAIN][EXTENDED_API_UNREGISTER_KEY] = unregister

    entry = _entry_with_state("a", ConfigEntryState.LOADED)
    stale = _entry_with_state("b", ConfigEntryState.NOT_LOADED)
    with patch.object(hass.config_entries, "async_entries", return_value=[entry, stale]):
        async_release_extended_api(hass, entry)

    unregister.assert_called_once()
    assert EXTENDED_API_UNREGISTER_KEY not in hass.data[DOMAIN]
    assert EXTENDED_API_ID not in [api.id for api in llm.async_get_apis(hass)]


async def test_release_extended_api_keeps_api_while_entries_remain(
    hass: HomeAssistant,
) -> None:
    """While another entry is still loaded the API must stay registered (C3)."""
    from homeassistant.config_entries import ConfigEntryState

    unregister = MagicMock()
    hass.data[DOMAIN] = {EXTENDED_API_UNREGISTER_KEY: unregister}
    entry = _entry_with_state("a", ConfigEntryState.LOADED)
    other = _entry_with_state("b", ConfigEntryState.LOADED)
    with patch.object(hass.config_entries, "async_entries", return_value=[entry, other]):
        async_release_extended_api(hass, entry)
    unregister.assert_not_called()


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
    """A valid service call on an exposed entity succeeds."""
    hass.states.async_set("light.kitchen", "off")
    calls = []
    hass.services.async_register("light", "turn_on", lambda call: calls.append(call.data))
    tool = CallServiceTool()
    with patch(EXPOSE_PATH, return_value=True):
        result = await tool.async_call(
            hass,
            _tool_input(
                "call_service",
                {
                    "domain": "light",
                    "service": "turn_on",
                    "data": {"entity_id": "light.kitchen", "brightness": 128},
                },
            ),
            _llm_context(),
        )
    assert result == {"success": True}
    assert calls and calls[0]["brightness"] == 128


async def test_call_service_requires_entity_id(hass: HomeAssistant) -> None:
    """A payload without an explicit entity_id target is refused (C2)."""
    hass.services.async_register("light", "turn_on", lambda call: None)
    tool = CallServiceTool()
    result = await tool.async_call(
        hass,
        _tool_input("call_service", {"domain": "light", "service": "turn_on", "data": {}}),
        _llm_context(),
    )
    assert "entity_id" in result["error"]


async def test_call_service_rejects_area_and_device_targets(hass: HomeAssistant) -> None:
    """area_id/device_id targets bypass per-entity exposure and are refused (C2)."""
    hass.services.async_register("light", "turn_on", lambda call: None)
    tool = CallServiceTool()
    for key in ("area_id", "device_id"):
        result = await tool.async_call(
            hass,
            _tool_input(
                "call_service",
                {"domain": "light", "service": "turn_on", "data": {key: "kitchen"}},
            ),
            _llm_context(),
        )
        assert "entity_id" in result["error"], key


async def test_call_service_blocks_unexposed_entity(hass: HomeAssistant) -> None:
    """Entities not exposed to Assist cannot be reached via call_service (C2)."""
    hass.states.async_set("light.hidden", "off")
    calls = []
    hass.services.async_register("light", "turn_on", lambda call: calls.append(call.data))
    tool = CallServiceTool()
    with patch(EXPOSE_PATH, return_value=False):
        result = await tool.async_call(
            hass,
            _tool_input(
                "call_service",
                {"domain": "light", "service": "turn_on", "data": {"entity_id": "light.hidden"}},
            ),
            _llm_context(),
        )
    assert "not exposed" in result["error"]
    assert not calls


async def test_call_service_blocks_missing_entity(hass: HomeAssistant) -> None:
    """An entity_id that does not exist is refused before the service call."""
    hass.services.async_register("light", "turn_on", lambda call: None)
    tool = CallServiceTool()
    with patch(EXPOSE_PATH, return_value=True):
        result = await tool.async_call(
            hass,
            _tool_input(
                "call_service",
                {
                    "domain": "light",
                    "service": "turn_on",
                    "data": {"entity_id": ["light.kitchen", "light.nope"]},
                },
            ),
            _llm_context(),
        )
    assert "not found" in result["error"]


async def test_call_service_list_entity_ids_all_must_be_exposed(hass: HomeAssistant) -> None:
    """A list target is only allowed when every entity is exposed (C2)."""
    hass.states.async_set("light.a", "off")
    hass.states.async_set("light.b", "off")
    calls = []
    hass.services.async_register("light", "turn_on", lambda call: calls.append(call.data))
    tool = CallServiceTool()
    exposed = {"light.a": True, "light.b": False}
    with patch(EXPOSE_PATH, side_effect=lambda h, a, e: exposed[e]):
        result = await tool.async_call(
            hass,
            _tool_input(
                "call_service",
                {
                    "domain": "light",
                    "service": "turn_on",
                    "data": {"entity_id": ["light.a", "light.b"]},
                },
            ),
            _llm_context(),
        )
    assert "light.b is not exposed" in result["error"]
    assert not calls


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

    hass.states.async_set("scene.movie", "scening")
    hass.services.async_register("scene", "activate", _boom)
    tool = CallServiceTool()
    with patch(EXPOSE_PATH, return_value=True):
        result = await tool.async_call(
            hass,
            _tool_input(
                "call_service",
                {"domain": "scene", "service": "activate", "data": {"entity_id": "scene.movie"}},
            ),
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


async def test_call_service_blocked_restricted_domains_even_exposed(hass: HomeAssistant) -> None:
    """Security-sensitive domains are refused even for exposed entities (C2)."""
    states = {
        "lock": "lock.front",
        "alarm_control_panel": "alarm_control_panel.house",
        "automation": "automation.vacate",
        "script": "script.exfil",
        "notify": "notify.mobile",
    }
    for domain, entity_id in states.items():
        hass.states.async_set(entity_id, "on")
        hass.services.async_register(domain, "any_action", lambda call: None)
        tool = CallServiceTool()
        with patch(EXPOSE_PATH, return_value=True):
            result = await tool.async_call(
                hass,
                _tool_input(
                    "call_service",
                    {"domain": domain, "service": "any_action", "data": {"entity_id": entity_id}},
                ),
                _llm_context(),
            )
        assert "not allowed" in result["error"], domain


async def test_call_service_returns_response_data(hass: HomeAssistant) -> None:
    """Services that support responses return their data to the model."""
    from homeassistant.core import ServiceResponse, SupportsResponse

    hass.states.async_set("weather.home", "sunny")

    def _handler(call) -> ServiceResponse:
        return {"forecast": "sunny"}

    hass.services.async_register(
        "weather", "get_forecasts", _handler, supports_response=SupportsResponse.ONLY
    )
    tool = CallServiceTool()
    with patch(EXPOSE_PATH, return_value=True):
        result = await tool.async_call(
            hass,
            _tool_input(
                "call_service",
                {
                    "domain": "weather",
                    "service": "get_forecasts",
                    "data": {"entity_id": "weather.home"},
                },
            ),
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


async def test_fetch_url_success(hass: HomeAssistant, public_host: None) -> None:
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


async def test_fetch_url_error(hass: HomeAssistant, public_host: None) -> None:
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


# --- fetch_url redirect chain (SSRF regression, C1) ---
#
# These deliberately do NOT use the `public_host` fixture (which stubs the
# whole guard off): they exercise the REAL guard classification, stubbing
# only DNS itself for public-looking names (no real DNS in tests).


def _redirect_response(location: str, status: int = 302) -> SimpleNamespace:
    return SimpleNamespace(status_code=status, headers={"location": location}, text="")


def _final_response(body: str = '{"ok": true}') -> SimpleNamespace:
    return SimpleNamespace(status_code=200, headers={"content-type": "application/json"}, text=body)


def _public_dns(public_names: set[str], resolutions: list[str]):
    """getaddrinfo stand-in: public IPs for `public_names`, real answers for IP literals."""
    import socket as socket_module

    real_getaddrinfo = socket_module.getaddrinfo

    def fake_getaddrinfo(host, port, *args, **kwargs):
        if host in public_names:
            resolutions.append(host)
            return [(2, 1, 6, "", ("93.184.216.34", 0))]
        return real_getaddrinfo(host, port, *args, **kwargs)

    return fake_getaddrinfo


async def test_fetch_url_blocks_redirect_to_loopback(hass: HomeAssistant) -> None:
    """A public URL that 302s to loopback is blocked by the real guard (C1)."""
    resolutions: list[str] = []
    client = MagicMock()
    client.get = AsyncMock(return_value=_redirect_response("http://127.0.0.1:8123/admin"))
    with (
        patch(
            "custom_components.litellm_conversation.extended_tools.socket.getaddrinfo",
            side_effect=_public_dns({"redirect.example.com"}, resolutions),
        ),
        patch(
            "custom_components.litellm_conversation.extended_tools.get_async_client",
            return_value=client,
        ),
    ):
        tool = FetchUrlTool()
        result = await tool.async_call(
            hass,
            _tool_input("fetch_url", {"url": "http://redirect.example.com/go"}),
            _llm_context(),
        )
    assert result == {"error": "URLs resolving to private or local addresses are not allowed"}
    # The loopback hop was validated and refused before it was ever requested.
    assert client.get.await_count == 1
    assert client.get.await_args.kwargs["follow_redirects"] is False


async def test_fetch_url_blocks_redirect_to_non_http(hass: HomeAssistant) -> None:
    """A redirect off the http/https schemes is rejected on the hop, not followed."""
    resolutions: list[str] = []
    client = MagicMock()
    client.get = AsyncMock(return_value=_redirect_response("file:///etc/passwd"))
    with (
        patch(
            "custom_components.litellm_conversation.extended_tools.socket.getaddrinfo",
            side_effect=_public_dns({"jump.example.com"}, resolutions),
        ),
        patch(
            "custom_components.litellm_conversation.extended_tools.get_async_client",
            return_value=client,
        ),
    ):
        tool = FetchUrlTool()
        result = await tool.async_call(
            hass,
            _tool_input("fetch_url", {"url": "http://jump.example.com/go"}),
            _llm_context(),
        )
    assert result == {"error": "Only http/https URLs are allowed"}
    assert client.get.await_count == 1


async def test_fetch_url_follows_legitimate_public_redirects(hass: HomeAssistant) -> None:
    """A legit 2-hop public chain still works, and the guard ran on every hop."""
    resolutions: list[str] = []
    client = MagicMock()
    client.get = AsyncMock(
        side_effect=[
            _redirect_response("https://b.example.com/go", status=301),
            _redirect_response("https://b.example.com/final", status=302),
            _final_response(),
        ]
    )
    with (
        patch(
            "custom_components.litellm_conversation.extended_tools.socket.getaddrinfo",
            side_effect=_public_dns({"a.example.com", "b.example.com"}, resolutions),
        ),
        patch(
            "custom_components.litellm_conversation.extended_tools.get_async_client",
            return_value=client,
        ),
    ):
        tool = FetchUrlTool()
        result = await tool.async_call(
            hass,
            _tool_input("fetch_url", {"url": "http://a.example.com/start"}),
            _llm_context(),
        )
    assert result["status"] == 200
    assert result["body"] == '{"ok": true}'
    assert client.get.await_count == 3
    # Validator ran per hop: initial host + each redirect target before use.
    assert len(resolutions) >= 2
    assert resolutions[0] == "a.example.com"


async def test_fetch_url_stops_after_too_many_redirects(hass: HomeAssistant) -> None:
    """Redirect loops are capped instead of following forever."""
    resolutions: list[str] = []
    client = MagicMock()
    client.get = AsyncMock(return_value=_redirect_response("http://a.example.com/again"))
    with (
        patch(
            "custom_components.litellm_conversation.extended_tools.socket.getaddrinfo",
            side_effect=_public_dns({"a.example.com"}, resolutions),
        ),
        patch(
            "custom_components.litellm_conversation.extended_tools.get_async_client",
            return_value=client,
        ),
    ):
        tool = FetchUrlTool()
        result = await tool.async_call(
            hass,
            _tool_input("fetch_url", {"url": "http://a.example.com/loop"}),
            _llm_context(),
        )
    assert "Too many redirects" in result["error"]
    assert client.get.await_count == 4  # initial + 3 followed hops


def test_resolve_is_private_rejects_any_private_record() -> None:
    """A DNS pool mixing public and private answers is blocked (any, not all)."""
    mixed = [
        (2, 1, 6, "", ("93.184.216.34", 0)),
        (2, 1, 6, "", ("10.1.2.3", 0)),
    ]
    with patch("socket.getaddrinfo", return_value=mixed):
        assert _resolve_is_private("rebind.example.com") is True


def test_resolve_is_private_blocks_mapped_loopback_and_multicast() -> None:
    """IPv4-mapped IPv6 and multicast answers are guarded like the rest."""
    assert _resolve_is_private("::ffff:127.0.0.1") is True
    assert _resolve_is_private("224.0.0.251") is True
    assert _resolve_is_private("0.0.0.0") is True


# --- new tools (v1.4.0): analyze_camera, get_calendar_events, add_todo_item ---

from custom_components.litellm_conversation.extended_tools import (  # noqa: E402
    AddTodoItemTool,
    AnalyzeCameraTool,
    GetCalendarEventsTool,
    _guard_entity,
)


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
    assert call_kwargs["extra_body"]["metadata"] == {
        "tags": ["home-assistant", "ha-litellm-conversation"]
    }
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


async def test_analyze_camera_dispatches_usage(hass: HomeAssistant) -> None:
    """The nested vision call's token usage feeds the usage sensors."""
    hass.states.async_set("camera.driveway", "idle")
    entry = _loaded_entry()
    entry.entry_id = "entryX"
    completion = MagicMock()
    completion.choices = [MagicMock(message=MagicMock(content="clear"))]
    completion.usage = SimpleNamespace(prompt_tokens=100, completion_tokens=20, total_tokens=120)
    entry.runtime_data.chat.completions.create = AsyncMock(return_value=completion)

    image = SimpleNamespace(content=b"jpg", content_type="image/jpeg")
    received = []
    tool = AnalyzeCameraTool(entry)
    with (
        patch(EXPOSE_PATH, return_value=True),
        patch(
            "homeassistant.components.camera.async_get_image",
            AsyncMock(return_value=image),
        ),
        patch(
            "custom_components.litellm_conversation.extended_tools.async_dispatcher_send",
            side_effect=lambda hass, signal, data: received.append((signal, data)),
        ),
    ):
        await tool.async_call(
            hass,
            _tool_input("analyze_camera", {"entity_id": "camera.driveway", "question": "?"}),
            _llm_context(),
        )

    assert received
    signal, data = received[0]
    assert signal.endswith("_entryX")
    assert data["total_tokens"] == 120


# --- HA contract ---

_ALL_TOOLS = [
    AddTodoItemTool,
    AnalyzeCameraTool,
    CallServiceTool,
    FetchUrlTool,
    GetCalendarEventsTool,
    GetHistoryTool,
]


def _build_tool(tool_cls: type[llm.Tool]) -> llm.Tool:
    return tool_cls(_mock_entry()) if tool_cls is AnalyzeCameraTool else tool_cls()


@pytest.mark.parametrize("tool_cls", _ALL_TOOLS)
def test_tool_schema_serializes_to_json(tool_cls: type[llm.Tool]) -> None:
    """Every tool schema must reach the wire as JSON (regression: HA 2026.9 probatio move)."""
    spec = _format_tool(_build_tool(tool_cls), llm.selector_serializer)
    assert json.loads(json.dumps(spec))["function"]["parameters"]["type"] == "object"


@pytest.mark.parametrize("tool_cls", _ALL_TOOLS)
def test_tool_records_its_integration(tool_cls: type[llm.Tool]) -> None:
    """HA requires tools to name their integration (enforced from 2027.10)."""
    assert _build_tool(tool_cls).integration == DOMAIN
