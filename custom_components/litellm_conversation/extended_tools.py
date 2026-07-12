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

from homeassistant.core import HomeAssistant, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import llm
from homeassistant.helpers.httpx_client import get_async_client
from homeassistant.util import dt as dt_util

from .const import DOMAIN, LOGGER

EXTENDED_API_ID = f"{DOMAIN}_extended"
EXTENDED_API_NAME = "LiteLLM Extended Tools"

FETCH_URL_MAX_BYTES = 100_000
HISTORY_MAX_HOURS = 168  # 7 days

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


class ExtendedToolsAPI(llm.API):
    """LLM API bundling the built-in Assist tools with the extended tools."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the API."""
        super().__init__(hass=hass, id=EXTENDED_API_ID, name=EXTENDED_API_NAME)

    async def async_get_api_instance(self, llm_context: llm.LLMContext) -> llm.APIInstance:
        """Return the API instance: Assist tools + extended tools."""
        assist_instance = None
        for api in llm.async_get_apis(self.hass):
            if api.id == llm.LLM_API_ASSIST:
                assist_instance = await api.async_get_api_instance(llm_context)
                break

        extended_tools: list[llm.Tool] = [
            CallServiceTool(),
            GetHistoryTool(),
            FetchUrlTool(),
        ]

        if assist_instance is not None:
            return llm.APIInstance(
                api=self,
                api_prompt=assist_instance.api_prompt
                + "\nYou also have power tools: call_service (any HA service), "
                "get_history (entity state history), fetch_url (external HTTP GET). "
                "Prefer the standard intent tools for simple device control.",
                llm_context=llm_context,
                tools=[*assist_instance.tools, *extended_tools],
                custom_serializer=assist_instance.custom_serializer,
            )

        return llm.APIInstance(
            api=self,
            api_prompt=(
                "You can interact with Home Assistant using these tools: "
                "call_service (any HA service), get_history (entity state "
                "history), fetch_url (external HTTP GET)."
            ),
            llm_context=llm_context,
            tools=extended_tools,
        )


def async_register_extended_api(hass: HomeAssistant) -> None:
    """Register the extended tools API once per HA instance."""
    if any(api.id == EXTENDED_API_ID for api in llm.async_get_apis(hass)):
        return
    llm.async_register_api(hass, ExtendedToolsAPI(hass))
    LOGGER.info("Registered %s LLM API", EXTENDED_API_NAME)
