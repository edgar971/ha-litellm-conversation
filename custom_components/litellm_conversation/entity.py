"""LiteLLM Conversation entity base."""

from __future__ import annotations

from collections.abc import AsyncGenerator
import json
import logging
import time
from typing import TYPE_CHECKING, Any

import openai
from openai._streaming import AsyncStream
from openai.types.responses import (
    ResponseFunctionCallArgumentsDeltaEvent,
    ResponseOutputItemAddedEvent,
    ResponseOutputItemDoneEvent,
    ResponseStreamEvent,
    ResponseTextDeltaEvent,
)
from openai.types.responses.response_input_param import FunctionCallOutput
import voluptuous as vol
from voluptuous_openapi import convert

from homeassistant.components import conversation
from homeassistant.config_entries import ConfigSubentry
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import llm
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.json import json_dumps

from .const import (
    CONF_CHAT_MODEL,
    CONF_MAX_TOKENS,
    CONF_REASONING_EFFORT,
    CONF_TEMPERATURE,
    CONF_TOP_P,
    DOMAIN,
    MAX_TOOL_ITERATIONS,
    RECOMMENDED_CHAT_MODEL,
    RECOMMENDED_MAX_TOKENS,
    RECOMMENDED_TEMPERATURE,
    RECOMMENDED_TOP_P,
)

if TYPE_CHECKING:
    from . import LiteLLMConfigEntry

_LOGGER = logging.getLogger(__name__)


def _format_tool(tool: llm.Tool) -> dict[str, Any]:
    """Format tool specification."""
    schema = convert(tool.parameters)
    return {
        "type": "function",
        "name": tool.name,
        "description": tool.description,
        "parameters": schema,
        "strict": False,
    }


def _convert_content_to_param(
    chat_content: list[conversation.Content],
) -> list[dict[str, Any]]:
    """Convert entire chat log content to list of Responses API input params."""
    messages: list[dict[str, Any]] = []

    for content in chat_content:
        if isinstance(content, conversation.ToolResultContent):
            messages.append(
                FunctionCallOutput(
                    type="function_call_output",
                    call_id=content.tool_call_id,
                    output=json_dumps(content.tool_result),
                )
            )
            continue

        if content.content:
            role = content.role
            if role == "system":
                role = "developer"
            messages.append(
                {
                    "type": "message",
                    "role": role,
                    "content": content.content,
                }
            )

        if isinstance(content, conversation.AssistantContent) and content.tool_calls:
            for tool_call in content.tool_calls:
                messages.append(
                    {
                        "type": "function_call",
                        "call_id": tool_call.id,
                        "name": tool_call.tool_name,
                        "arguments": json.dumps(tool_call.tool_args),
                    }
                )

    return messages


async def _transform_stream(
    chat_log: conversation.ChatLog,
    result: AsyncStream[ResponseStreamEvent],
) -> AsyncGenerator[conversation.AssistantContentDeltaDict]:
    """Transform an OpenAI Responses API stream into HA chat log delta dicts."""
    current_tool_call: dict[str, Any] | None = None

    async for event in result:
        if isinstance(event, ResponseTextDeltaEvent):
            yield {"type": "text", "text": event.delta}
        elif isinstance(event, ResponseOutputItemAddedEvent):
            item = event.item
            if item.type == "function_call":
                current_tool_call = {
                    "tool_call_id": item.call_id,
                    "tool_name": item.name,
                    "tool_args_json": "",
                }
        elif isinstance(event, ResponseFunctionCallArgumentsDeltaEvent):
            if current_tool_call is not None:
                current_tool_call["tool_args_json"] += event.delta
        elif isinstance(event, ResponseOutputItemDoneEvent):
            item = event.item
            if item.type == "function_call" and current_tool_call is not None:
                _LOGGER.debug(
                    "Tool call completed: %s (call_id=%s)",
                    current_tool_call["tool_name"],
                    current_tool_call["tool_call_id"],
                )
                yield {
                    "type": "tool_call",
                    "tool_call_id": current_tool_call["tool_call_id"],
                    "tool_name": current_tool_call["tool_name"],
                    "tool_args": json.loads(current_tool_call["tool_args_json"]),
                }
                current_tool_call = None


class LiteLLMBaseLLMEntity(Entity):
    """Base class for LiteLLM LLM entities."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        entry: LiteLLMConfigEntry,
        subentry: ConfigSubentry,
    ) -> None:
        """Initialize the entity."""
        self.entry = entry
        self.subentry = subentry
        self._attr_unique_id = subentry.subentry_id
        self._attr_name = subentry.title

    @property
    def client(self) -> openai.AsyncOpenAI:
        """Return the OpenAI client."""
        return self.entry.runtime_data

    async def _async_handle_chat_log(
        self,
        chat_log: conversation.ChatLog,
        structure_name: str | None = None,
        structure: vol.Schema | None = None,
        max_iterations: int = MAX_TOOL_ITERATIONS,
    ) -> None:
        """Handle a chat log using the OpenAI Responses API."""
        tools: list[dict[str, Any]] = []
        if chat_log.llm_api is not None:
            tools = [_format_tool(tool) for tool in chat_log.llm_api.tools]

        model = self.subentry.data.get(CONF_CHAT_MODEL, RECOMMENDED_CHAT_MODEL)
        temperature = self.subentry.data.get(CONF_TEMPERATURE, RECOMMENDED_TEMPERATURE)
        top_p = self.subentry.data.get(CONF_TOP_P, RECOMMENDED_TOP_P)
        max_tokens = self.subentry.data.get(CONF_MAX_TOKENS, RECOMMENDED_MAX_TOKENS)
        reasoning_effort = self.subentry.data.get(CONF_REASONING_EFFORT)

        create_params: dict[str, Any] = {
            "model": model,
            "input": _convert_content_to_param(chat_log.content),
            "stream": True,
            "max_output_tokens": max_tokens,
        }

        # Only send temperature OR top_p (not both) to avoid Bedrock errors.
        # Prefer temperature; only send top_p if temperature is at default and top_p isn't.
        if temperature != RECOMMENDED_TEMPERATURE:
            create_params["temperature"] = temperature
        elif top_p != RECOMMENDED_TOP_P:
            create_params["top_p"] = top_p
        else:
            create_params["temperature"] = temperature

        if reasoning_effort and reasoning_effort != "none":
            create_params["reasoning"] = {"effort": reasoning_effort}

        if tools:
            create_params["tools"] = tools

        if structure is not None and structure_name is not None:
            output_schema = convert(structure)
            create_params["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": structure_name,
                    "schema": output_schema,
                    "strict": True,
                }
            }

        for _iteration in range(max_iterations):
            _LOGGER.debug(
                "LiteLLM request: model=%s temperature=%s top_p=%s max_tokens=%s tools=%d",
                model,
                temperature,
                top_p,
                max_tokens,
                len(tools),
            )
            t0 = time.monotonic()
            try:
                response = await self.client.responses.create(**create_params)
            except openai.AuthenticationError as err:
                _LOGGER.error(
                    "Authentication error calling LiteLLM (model=%s): %s",
                    model,
                    err,
                )
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="authentication_error",
                ) from err
            except openai.RateLimitError as err:
                _LOGGER.error(
                    "Rate limit error calling LiteLLM (model=%s): %s",
                    model,
                    err,
                )
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="rate_limit_error",
                ) from err
            except openai.APIConnectionError as err:
                _LOGGER.error(
                    "Connection error calling LiteLLM (model=%s): %s",
                    model,
                    err,
                )
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="connection_error",
                ) from err
            except openai.APIStatusError as err:
                _LOGGER.error(
                    "API status error calling LiteLLM (model=%s, status=%s): %s",
                    model,
                    err.status_code,
                    err,
                )
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="api_error",
                    translation_placeholders={"status_code": str(err.status_code)},
                ) from err

            async for _ in chat_log.async_add_delta_content_stream(
                self.entity_id, _transform_stream(chat_log, response)
            ):
                pass

            latency_ms = (time.monotonic() - t0) * 1000
            _LOGGER.info(
                "LiteLLM response received: model=%s latency=%.0fms iteration=%d",
                model,
                latency_ms,
                _iteration + 1,
            )

            # Verify we got a response
            if not chat_log.content or not isinstance(
                chat_log.content[-1], conversation.AssistantContent
            ):
                _LOGGER.error(
                    "LiteLLM model returned no content (model=%s). Check proxy logs for errors.",
                    model,
                )
                raise HomeAssistantError(
                    f"LiteLLM model '{model}' returned no response. Check your LiteLLM proxy logs."
                )

            if not chat_log.unresponded_tool_results:
                break

            # Update input for next iteration with full conversation
            create_params["input"] = _convert_content_to_param(chat_log.content)
