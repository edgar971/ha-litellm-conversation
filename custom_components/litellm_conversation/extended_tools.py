"""Extended LLM tools for LiteLLM Conversation.

Registers a custom Home Assistant LLM API ("LiteLLM Extended Tools") that
layers power-user tools on top of the built-in Assist API:

- call_service: call any HA service directly (with domain/service validation)
- get_history: query recorder state history for an entity over a time range
- fetch_url: HTTP GET an external URL (JSON/text, size-capped)

Users opt in by selecting "LiteLLM Extended Tools" as the agent's LLM API.
"""

from __future__ import annotations

from datetime import timedelta
import ipaddress
import socket
from typing import Any
from urllib.parse import urlparse

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import llm
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.httpx_client import get_async_client
from homeassistant.util import dt as dt_util

from .const import CONF_CHAT_MODEL, DEFAULT_CHAT_MODEL, DOMAIN, LOGGER, SIGNAL_USAGE_UPDATED
from .memory import async_get_memory_store

EXTENDED_API_ID = f"{DOMAIN}_extended"
EXTENDED_API_NAME = "LiteLLM Extended Tools"

FETCH_URL_MAX_BYTES = 100_000
HISTORY_MAX_HOURS = 168  # 7 days
ANALYZE_CAMERA_MAX_TOKENS = 500
CALENDAR_MAX_DAYS = 30
CALENDAR_MAX_EVENTS = 50

# Domains the LLM may never call services on. call_service is a power tool,
# but a prompt-injected model must not be able to stop/restart HA, run
# arbitrary shell commands or Python, or wipe the recorder.
BLOCKED_SERVICE_DOMAINS = frozenset(
    {
        "hassio",
        "homeassistant",
        "python_script",
        "recorder",
        "shell_command",
    }
)


class CallServiceTool(llm.Tool):
    """Call any Home Assistant service."""

    name = "call_service"
    description = (
        "Call a Home Assistant service. Use for actions not covered by other "
        "tools, e.g. 'light.turn_on' with entity_id and brightness. "
        "domain is the service domain (light, switch, script...), service is "
        "the service name (turn_on, toggle...), data is the service payload "
        "including entity_id/area_id targets. System domains (homeassistant, "
        "hassio, shell_command, python_script, recorder) are not allowed."
    )
    parameters = vol.Schema(
        {
            vol.Required("domain"): str,
            vol.Required("service"): str,
            vol.Optional("data"): dict,
        }
    )

    async def async_call(
        self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext
    ) -> Any:
        """Execute the service call."""
        domain = tool_input.tool_args["domain"]
        service = tool_input.tool_args["service"]
        data = tool_input.tool_args.get("data") or {}

        if domain in BLOCKED_SERVICE_DOMAINS:
            return {"error": f"Services in the {domain} domain are not allowed"}

        if not hass.services.has_service(domain, service):
            return {"error": f"Service {domain}.{service} does not exist"}

        LOGGER.debug("Extended tool call_service: %s.%s data=%s", domain, service, data)
        supports_response = (
            hass.services.supports_response(domain, service) != SupportsResponse.NONE
        )
        try:
            response = await hass.services.async_call(
                domain,
                service,
                data,
                blocking=True,
                return_response=supports_response,
            )
        except (HomeAssistantError, vol.Invalid) as err:
            return {"error": str(err)}
        if supports_response and response:
            return {"success": True, "response": response}
        return {"success": True}


class GetHistoryTool(llm.Tool):
    """Query recorder history for an entity."""

    name = "get_history"
    description = (
        "Get the state history of an entity over a time range. hours_ago is "
        "how far back to look (max 168 = 7 days, default 24). Returns a list "
        "of state changes with timestamps."
    )
    parameters = vol.Schema(
        {
            vol.Required("entity_id"): str,
            vol.Optional("hours_ago"): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=HISTORY_MAX_HOURS)
            ),
        }
    )

    async def async_call(
        self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext
    ) -> Any:
        """Fetch history from the recorder."""
        from homeassistant.components.recorder import get_instance, history

        entity_id = tool_input.tool_args["entity_id"]
        hours = tool_input.tool_args.get("hours_ago", 24)

        if hass.states.get(entity_id) is None:
            return {"error": f"Entity {entity_id} not found"}

        start = dt_util.utcnow() - timedelta(hours=hours)
        states = await get_instance(hass).async_add_executor_job(
            lambda: history.state_changes_during_period(
                hass, start, None, entity_id, no_attributes=True
            )
        )

        return {
            "entity_id": entity_id,
            "hours": hours,
            "changes": [
                {"state": s.state, "when": s.last_changed.isoformat()}
                for s in states.get(entity_id, [])
            ][-100:],
        }


def _resolve_is_private(host: str) -> bool:
    """Return True if host resolves only to private/loopback/link-local addresses.

    Runs blocking DNS resolution — call via executor.
    """
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        # Unresolvable — let the HTTP client produce the real error.
        return False
    addresses = [ipaddress.ip_address(info[4][0]) for info in infos]
    return all(addr.is_private or addr.is_loopback or addr.is_link_local for addr in addresses)


class FetchUrlTool(llm.Tool):
    """Fetch content from an external URL."""

    name = "fetch_url"
    description = (
        "HTTP GET an external URL and return its body (JSON or text, "
        "truncated to 100KB). Only public http/https URLs are allowed — "
        "private/LAN addresses are blocked. Use for external APIs like "
        "weather, transit, or stock data."
    )
    parameters = vol.Schema({vol.Required("url"): str})

    async def async_call(
        self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext
    ) -> Any:
        """Fetch the URL."""
        url = tool_input.tool_args["url"]
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return {"error": "Only http/https URLs are allowed"}

        # SSRF guard: refuse URLs resolving to private/loopback ranges so the
        # model can't probe the LAN, the HA supervisor API, or router admin
        # pages through this tool.
        if await hass.async_add_executor_job(_resolve_is_private, parsed.hostname):
            return {"error": "URLs resolving to private or local addresses are not allowed"}

        client = get_async_client(hass)
        try:
            response = await client.get(url, timeout=15, follow_redirects=True)
        except Exception as err:
            return {"error": f"Fetch failed: {err}"}

        body = response.text[:FETCH_URL_MAX_BYTES]
        return {
            "status": response.status_code,
            "content_type": response.headers.get("content-type", ""),
            "body": body,
        }


def _guard_entity(hass: HomeAssistant, entity_id: str, domain: str) -> dict[str, Any] | None:
    """Common entity guards for entity-targeting tools.

    Returns an error dict if the entity is invalid, missing, or not exposed
    to Assist; None when the entity is OK to use. The exposure check keeps a
    prompt-injected model from reaching entities the user chose not to
    expose (e.g. unexposed cameras).
    """
    from homeassistant.components.homeassistant.exposed_entities import (
        async_should_expose,
    )

    if not entity_id.startswith(f"{domain}."):
        return {"error": f"entity_id must be a {domain} entity"}
    if hass.states.get(entity_id) is None:
        return {"error": f"Entity {entity_id} not found"}
    if not async_should_expose(hass, "conversation", entity_id):
        return {"error": f"Entity {entity_id} is not exposed to Assist"}
    return None


class AnalyzeCameraTool(llm.Tool):
    """Snapshot a camera and answer a question about the image."""

    name = "analyze_camera"
    description = (
        "Take a snapshot from a camera and answer a question about what it "
        "currently shows (e.g. 'Is there a package by the front door?'). "
        "entity_id must be a camera entity exposed to Assist; question is "
        "what you want to know about the image."
    )
    parameters = vol.Schema(
        {
            vol.Required("entity_id"): str,
            vol.Required("question"): str,
        }
    )

    def __init__(self, entry: ConfigEntry) -> None:
        """Store the owning config entry (LiteLLM client + model config)."""
        self._entry = entry

    def _vision_model(self) -> str:
        """Model for the nested vision call: first conversation subentry's model."""
        for subentry in self._entry.subentries.values():
            if subentry.subentry_type == "conversation":
                return subentry.data.get(CONF_CHAT_MODEL, DEFAULT_CHAT_MODEL)
        return DEFAULT_CHAT_MODEL

    async def async_call(
        self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext
    ) -> Any:
        """Snapshot the camera and run a one-shot vision request."""
        import base64

        from homeassistant.components import camera
        from homeassistant.config_entries import ConfigEntryState

        entity_id = tool_input.tool_args["entity_id"]
        question = tool_input.tool_args["question"]

        if error := _guard_entity(hass, entity_id, "camera"):
            return error
        if self._entry.state is not ConfigEntryState.LOADED:
            return {"error": "LiteLLM config entry is not loaded"}

        try:
            image = await camera.async_get_image(hass, entity_id)
        except HomeAssistantError as err:
            return {"error": f"Could not get camera image: {err}"}

        b64 = await hass.async_add_executor_job(
            lambda: base64.b64encode(image.content).decode("utf-8")
        )

        model = self._vision_model()
        LOGGER.debug("analyze_camera: %s question=%r model=%s", entity_id, question, model)
        try:
            response = await self._entry.runtime_data.chat.completions.create(
                model=model,
                max_tokens=ANALYZE_CAMERA_MAX_TOKENS,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You analyze security camera snapshots. Answer the "
                            "question concisely based only on what the image shows."
                        ),
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": question},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:{image.content_type};base64,{b64}"},
                            },
                        ],
                    },
                ],
                extra_body={"drop_params": True},
            )
        except Exception as err:  # openai errors -> readable tool result
            return {"error": f"Vision analysis failed: {err}"}

        # Feed the nested call's token usage to the usage sensors, same
        # signal the conversation/AI Task entities use.
        if usage := getattr(response, "usage", None):
            async_dispatcher_send(
                hass,
                f"{SIGNAL_USAGE_UPDATED}_{self._entry.entry_id}",
                {
                    "model": model,
                    "prompt_tokens": usage.prompt_tokens,
                    "completion_tokens": usage.completion_tokens,
                    "total_tokens": usage.total_tokens,
                },
            )

        return {"camera": entity_id, "answer": response.choices[0].message.content}


class GetCalendarEventsTool(llm.Tool):
    """Read upcoming events from a calendar entity."""

    name = "get_calendar_events"
    description = (
        "Get upcoming events from a calendar. entity_id must be a calendar "
        "entity; days_ahead is how many days to look ahead (default 7, max 30)."
    )
    parameters = vol.Schema(
        {
            vol.Required("entity_id"): str,
            vol.Optional("days_ahead"): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=CALENDAR_MAX_DAYS)
            ),
        }
    )

    async def async_call(
        self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext
    ) -> Any:
        """Query calendar.get_events."""
        entity_id = tool_input.tool_args["entity_id"]
        days = tool_input.tool_args.get("days_ahead", 7)

        if error := _guard_entity(hass, entity_id, "calendar"):
            return error

        now = dt_util.now()
        try:
            result = await hass.services.async_call(
                "calendar",
                "get_events",
                {
                    "entity_id": entity_id,
                    "start_date_time": now.isoformat(),
                    "end_date_time": (now + timedelta(days=days)).isoformat(),
                },
                blocking=True,
                return_response=True,
            )
        except (HomeAssistantError, vol.Invalid) as err:
            return {"error": str(err)}

        events = (result or {}).get(entity_id, {}).get("events", [])
        return {
            "calendar": entity_id,
            "days_ahead": days,
            "events": events[:CALENDAR_MAX_EVENTS],
        }


class AddTodoItemTool(llm.Tool):
    """Add an item to a todo/shopping list."""

    name = "add_todo_item"
    description = (
        "Add an item to a to-do or shopping list. entity_id must be a todo "
        "entity (e.g. todo.shopping_list); item is the item text. Optional: "
        "description, due_date (YYYY-MM-DD)."
    )
    parameters = vol.Schema(
        {
            vol.Required("entity_id"): str,
            vol.Required("item"): str,
            vol.Optional("description"): str,
            vol.Optional("due_date"): str,
        }
    )

    async def async_call(
        self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext
    ) -> Any:
        """Call todo.add_item."""
        entity_id = tool_input.tool_args["entity_id"]
        item = tool_input.tool_args["item"]

        if error := _guard_entity(hass, entity_id, "todo"):
            return error

        data: dict[str, Any] = {"entity_id": entity_id, "item": item}
        if description := tool_input.tool_args.get("description"):
            data["description"] = description
        if due_date := tool_input.tool_args.get("due_date"):
            data["due_date"] = due_date

        try:
            await hass.services.async_call("todo", "add_item", data, blocking=True)
        except (HomeAssistantError, vol.Invalid) as err:
            return {"error": str(err)}
        return {"success": True, "list": entity_id, "item": item}


class RememberTool(llm.Tool):
    """Save a durable fact to long-term memory."""

    name = "remember"
    description = (
        "Save a durable fact to long-term memory so it is available in "
        "future conversations (e.g. 'the water shutoff is behind the "
        "basement panel'). Use for stable facts the user states or asks you "
        "to remember — not for transient chit-chat. Keep it short."
    )
    parameters = vol.Schema({vol.Required("text"): str})

    async def async_call(
        self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext
    ) -> Any:
        """Store the memory."""
        store = async_get_memory_store(hass)
        await store.async_load()
        try:
            memory = store.remember(tool_input.tool_args["text"])
        except ValueError as err:
            return {"error": str(err)}
        return {"success": True, "id": memory.id, "remembered": memory.text}


class ForgetTool(llm.Tool):
    """Remove memories matching a text fragment."""

    name = "forget"
    description = (
        "Delete long-term memories whose text contains the given fragment "
        "(case-insensitive). Use when the user says a remembered fact is "
        "wrong or no longer needed."
    )
    parameters = vol.Schema({vol.Required("text"): str})

    async def async_call(
        self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext
    ) -> Any:
        """Forget matching memories."""
        store = async_get_memory_store(hass)
        await store.async_load()
        removed = store.forget_matching(tool_input.tool_args["text"])
        if not removed:
            return {"error": "No memories matched that text"}
        return {"success": True, "removed": removed}


class ListMemoriesTool(llm.Tool):
    """List everything currently remembered."""

    name = "list_memories"
    description = "List all facts currently stored in long-term memory."
    parameters = vol.Schema({})

    async def async_call(
        self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext
    ) -> Any:
        """Return all memories."""
        store = async_get_memory_store(hass)
        await store.async_load()
        return {
            "count": len(store.memories),
            "memories": [{"id": m.id, "text": m.text} for m in store.memories],
        }


class ExtendedToolsAPI(llm.API):
    """LLM API bundling the built-in Assist tools with the extended tools."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the API.

        The owning config entry provides the LiteLLM client (runtime_data)
        and model configuration for tools that make nested LLM calls
        (analyze_camera).
        """
        super().__init__(hass=hass, id=EXTENDED_API_ID, name=EXTENDED_API_NAME)
        self._entry = entry

    async def async_get_api_instance(self, llm_context: llm.LLMContext) -> llm.APIInstance:
        """Return the API instance: Assist tools + extended tools."""
        assist_instance = None
        for api in llm.async_get_apis(self.hass):
            if api.id == llm.LLM_API_ASSIST:
                assist_instance = await api.async_get_api_instance(llm_context)
                break

        # Memories are injected fresh on every turn (this method runs
        # per-request) so a fact remembered in turn 1 is visible in turn 2.
        memory_store = async_get_memory_store(self.hass)
        await memory_store.async_load()
        memory_section = memory_store.prompt_section()

        extended_tools: list[llm.Tool] = [
            CallServiceTool(),
            GetHistoryTool(),
            FetchUrlTool(),
            AnalyzeCameraTool(self._entry),
            GetCalendarEventsTool(),
            AddTodoItemTool(),
            RememberTool(),
            ForgetTool(),
            ListMemoriesTool(),
        ]

        tools_blurb = (
            "call_service (any HA service), "
            "get_history (entity state history), fetch_url (external HTTP GET), "
            "analyze_camera (look at a camera and answer a question), "
            "get_calendar_events (upcoming calendar events), add_todo_item "
            "(add to a to-do/shopping list), remember/forget/list_memories "
            "(long-term memory for durable facts)."
        )

        if assist_instance is not None:
            return llm.APIInstance(
                api=self,
                api_prompt=assist_instance.api_prompt
                + "\nYou also have power tools: "
                + tools_blurb
                + " Prefer the standard intent tools for simple device control."
                + memory_section,
                llm_context=llm_context,
                tools=[*assist_instance.tools, *extended_tools],
                custom_serializer=assist_instance.custom_serializer,
            )

        return llm.APIInstance(
            api=self,
            api_prompt=(
                "You can interact with Home Assistant using these tools: "
                + tools_blurb
                + memory_section
            ),
            llm_context=llm_context,
            tools=extended_tools,
        )


def async_register_extended_api(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Register the extended tools API once per HA instance."""
    if any(api.id == EXTENDED_API_ID for api in llm.async_get_apis(hass)):
        return
    llm.async_register_api(hass, ExtendedToolsAPI(hass, entry))
    LOGGER.info("Registered %s LLM API", EXTENDED_API_NAME)
