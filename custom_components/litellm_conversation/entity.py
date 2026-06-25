"""LiteLLM Conversation entity base."""

from __future__ import annotations

from collections.abc import AsyncGenerator
import json
from typing import Any

import openai
from openai.types.responses import (
    ResponseInputParam,
    ResponseOutputItem,
    ResponseStreamEvent,
    ResponseTextDeltaEvent,
)
from openai.types.responses.response_create_params import ResponseCreateParamsStreaming
import voluptuous as vol

from homeassistant.components.conversation import (
    ChatLog,
    ConversationEntity,
    SystemContent,
    UserContent,
)
from homeassistant.components.conversation.chat_log import (
    AssistantContent,
    AssistantContentDeltaDict,
    Content,
    ToolCallContent,
    ToolResultContent,
)
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.exceptions import HomeAssistantError

from .const import (
    CONF_CHAT_MODEL,
    CONF_MAX_TOKENS,
    CONF_TEMPERATURE,
    CONF_TOP_P,
    DOMAIN,
    MAX_TOOL_ITERATIONS,
)

type LiteLLMConfigEntry = ConfigEntry[openai.AsyncOpenAI]


def _convert_content(
    chat_content: Content,
) -> ResponseInputParam:
    """Convert HA chat log content to OpenAI Responses API input param."""
    if isinstance(chat_content, SystemContent):
        return {
            "role": "system",
            "content": chat_content.content,
        }
    if isinstance(chat_content, UserContent):
        parts: list[Any] = []
        for part in chat_content.content:
            if hasattr(part, "text"):
                parts.append({"type": "input_text", "text": part.text})
            elif hasattr(part, "media_type"):
                parts.append(
                    {
                        "type": "input_image",
                        "image_url": f"data:{part.media_type};base64,{part.data}",
                    }
                )
        return {"role": "user", "content": parts}
    if isinstance(chat_content, AssistantContent):
        return {
            "role": "assistant",
            "content": chat_content.content,
        }
    if isinstance(chat_content, ToolCallContent):
        return {
            "type": "function_call",
            "call_id": chat_content.tool_call_id,
            "name": chat_content.tool_name,
            "arguments": json.dumps(chat_content.tool_args),
        }
    if isinstance(chat_content, ToolResultContent):
        return {
            "type": "function_call_output",
            "call_id": chat_content.tool_call_id,
            "output": chat_content.tool_result
            if isinstance(chat_content.tool_result, str)
            else json.dumps(chat_content.tool_result),
        }
    raise ValueError(f"Unexpected content type: {type(chat_content)}")


def _convert_content_to_param(
    chat_log: ChatLog,
) -> list[ResponseInputParam]:
    """Convert entire chat log to list of Responses API input params."""
    return [_convert_content(c) for c in chat_log.content]


async def _transform_stream(
    chat_log: ChatLog,
    result: openai.AsyncStream[ResponseStreamEvent],
) -> AsyncGenerator[AssistantContentDeltaDict]:
    """Transform an OpenAI Responses API stream into HA chat log delta dicts."""
    current_tool_call: dict[str, Any] | None = None

    async for event in result:
        if isinstance(event, ResponseTextDeltaEvent):
            yield {"type": "text", "text": event.delta}
        elif event.type == "response.output_item.added":
            item: ResponseOutputItem = event.item
            if item.type == "function_call":
                current_tool_call = {
                    "tool_call_id": item.call_id,
                    "tool_name": item.name,
                    "tool_args_json": "",
                }
        elif event.type == "response.function_call_arguments.delta":
            if current_tool_call is not None:
                current_tool_call["tool_args_json"] += event.delta
        elif event.type == "response.output_item.done":
            item = event.item
            if item.type == "function_call" and current_tool_call is not None:
                yield {
                    "type": "tool_call",
                    "tool_call_id": current_tool_call["tool_call_id"],
                    "tool_name": current_tool_call["tool_name"],
                    "tool_args": json.loads(current_tool_call["tool_args_json"]),
                }
                current_tool_call = None


class LiteLLMBaseLLMEntity(ConversationEntity):
    """Base class for LiteLLM LLM entities."""

    _attr_has_entity_name = True

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
        self._attr_device_info = None

    @property
    def client(self) -> openai.AsyncOpenAI:
        """Return the OpenAI client."""
        return self.entry.runtime_data

    async def _async_handle_chat_log(
        self,
        chat_log: ChatLog,
        structure_name: str | None = None,
        structure: vol.Schema | None = None,
    ) -> None:
        """Handle a chat log using the OpenAI Responses API."""
        tools: list[dict[str, Any]] = []
        if chat_log.llm_api is not None:
            tools = [
                {
                    "type": "function",
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                }
                for tool in chat_log.llm_api.tools
            ]

        model = self.subentry.data.get(CONF_CHAT_MODEL, "gpt-4o-mini")
        temperature = self.subentry.data.get(CONF_TEMPERATURE, 1.0)
        top_p = self.subentry.data.get(CONF_TOP_P, 1.0)
        max_tokens = self.subentry.data.get(CONF_MAX_TOKENS, 4096)

        create_params: ResponseCreateParamsStreaming = {
            "model": model,
            "input": _convert_content_to_param(chat_log),
            "stream": True,
            "temperature": temperature,
            "top_p": top_p,
            "max_output_tokens": max_tokens,
        }

        if tools:
            create_params["tools"] = tools  # type: ignore[typeddict-item]

        if structure is not None and structure_name is not None:
            create_params["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": structure_name,
                    "schema": structure,
                    "strict": True,
                }
            }

        for _iteration in range(MAX_TOOL_ITERATIONS):
            try:
                response = await self.client.responses.create(**create_params)
            except openai.AuthenticationError as err:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="authentication_error",
                ) from err
            except openai.RateLimitError as err:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="rate_limit_error",
                ) from err
            except openai.APIConnectionError as err:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="connection_error",
                ) from err
            except openai.APIStatusError as err:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="api_error",
                    translation_placeholders={"status_code": str(err.status_code)},
                ) from err

            async for _ in chat_log.async_add_delta_content_stream(
                self.entity_id, _transform_stream(chat_log, response)
            ):
                pass

            if not chat_log.unresponded_tool_results:
                break

            # Update input for next iteration with full conversation
            create_params["input"] = _convert_content_to_param(chat_log)
