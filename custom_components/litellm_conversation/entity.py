"""LiteLLM Conversation entity base."""

from __future__ import annotations

from collections.abc import AsyncGenerator
import json
import logging
import time
from typing import TYPE_CHECKING, Any

import openai
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
    """Format tool specification for Chat Completions API."""
    schema = convert(tool.parameters)
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": schema,
        },
    }


def _convert_content_to_messages(
    chat_content: list[conversation.Content],
) -> list[dict[str, Any]]:
    """Convert chat log content to Chat Completions API messages."""
    messages: list[dict[str, Any]] = []

    for content in chat_content:
        if isinstance(content, conversation.ToolResultContent):
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": content.tool_call_id,
                    "content": json_dumps(content.tool_result),
                }
            )
            continue

        if isinstance(content, conversation.AssistantContent):
            msg: dict[str, Any] = {"role": "assistant"}
            if content.content:
                msg["content"] = content.content
            if content.tool_calls:
                msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.tool_name,
                            "arguments": json.dumps(tc.tool_args),
                        },
                    }
                    for tc in content.tool_calls
                ]
            messages.append(msg)
        elif content.content:
            messages.append(
                {
                    "role": content.role,
                    "content": content.content,
                }
            )

    return messages


async def _transform_stream(
    result: openai.AsyncStream,
) -> AsyncGenerator[conversation.AssistantContentDeltaDict]:
    """Transform a Chat Completions stream into HA chat log delta dicts."""
    current_tool_calls: dict[int, dict[str, Any]] = {}

    async for chunk in result:
        choice = chunk.choices[0] if chunk.choices else None
        if choice is None:
            _LOGGER.debug("Stream chunk with no choices: %s", chunk)
            continue

        delta = choice.delta
        if delta is None:
            _LOGGER.debug("Stream chunk with no delta: finish_reason=%s", choice.finish_reason)
            continue

        # Text content
        if delta.content:
            _LOGGER.debug("Stream text delta: %s", repr(delta.content[:80]))
            yield {"content": delta.content}

        # Tool calls
        if delta.tool_calls:
            for tc_delta in delta.tool_calls:
                idx = tc_delta.index
                if idx not in current_tool_calls:
                    current_tool_calls[idx] = {
                        "tool_call_id": tc_delta.id or "",
                        "tool_name": "",
                        "tool_args_json": "",
                    }
                tc = current_tool_calls[idx]
                if tc_delta.id:
                    tc["tool_call_id"] = tc_delta.id
                if tc_delta.function:
                    if tc_delta.function.name:
                        tc["tool_name"] = tc_delta.function.name
                    if tc_delta.function.arguments:
                        tc["tool_args_json"] += tc_delta.function.arguments

        # When the stream signals stop, emit any accumulated tool calls
        if choice.finish_reason == "tool_calls":
            tool_inputs = []
            for tc in current_tool_calls.values():
                if tc["tool_call_id"] and tc["tool_name"]:
                    _LOGGER.debug(
                        "Tool call completed: %s (call_id=%s)",
                        tc["tool_name"],
                        tc["tool_call_id"],
                    )
                    tool_inputs.append(
                        llm.ToolInput(
                            id=tc["tool_call_id"],
                            tool_name=tc["tool_name"],
                            tool_args=json.loads(tc["tool_args_json"] or "{}"),
                        )
                    )
            if tool_inputs:
                yield {"tool_calls": tool_inputs}
            current_tool_calls.clear()

        # Log finish reason
        if choice.finish_reason:
            _LOGGER.debug("Stream finished: reason=%s", choice.finish_reason)


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
        """Handle a chat log using the Chat Completions API."""
        tools: list[dict[str, Any]] | None = None
        if chat_log.llm_api is not None:
            tools = [_format_tool(tool) for tool in chat_log.llm_api.tools]

        model = self.subentry.data.get(CONF_CHAT_MODEL, RECOMMENDED_CHAT_MODEL)
        temperature = self.subentry.data.get(CONF_TEMPERATURE, RECOMMENDED_TEMPERATURE)
        top_p = self.subentry.data.get(CONF_TOP_P, RECOMMENDED_TOP_P)
        max_tokens = self.subentry.data.get(CONF_MAX_TOKENS, RECOMMENDED_MAX_TOKENS)
        reasoning_effort = self.subentry.data.get(CONF_REASONING_EFFORT)

        messages = _convert_content_to_messages(chat_log.content)

        create_params: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
            "max_tokens": max_tokens,
        }

        # Only send temperature OR top_p (not both) to avoid Bedrock errors.
        if temperature != RECOMMENDED_TEMPERATURE:
            create_params["temperature"] = temperature
        elif top_p != RECOMMENDED_TOP_P:
            create_params["top_p"] = top_p
        else:
            create_params["temperature"] = temperature

        if tools:
            create_params["tools"] = tools

        if structure is not None and structure_name is not None:
            output_schema = convert(structure)
            create_params["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": structure_name,
                    "schema": output_schema,
                    "strict": True,
                },
            }

        # Pass reasoning effort as extra header for models that support it
        extra_headers: dict[str, str] = {}
        if reasoning_effort and reasoning_effort != "none":
            # LiteLLM passes this through for compatible models
            extra_headers["x-litellm-reasoning-effort"] = reasoning_effort

        for _iteration in range(max_iterations):
            _LOGGER.debug(
                "LiteLLM request: model=%s temperature=%s top_p=%s max_tokens=%s tools=%d",
                model,
                create_params.get("temperature", "unset"),
                create_params.get("top_p", "unset"),
                max_tokens,
                len(tools) if tools else 0,
            )
            t0 = time.monotonic()
            try:
                response = await self.client.chat.completions.create(
                    **create_params,
                    **({"extra_headers": extra_headers} if extra_headers else {}),
                )
            except openai.AuthenticationError as err:
                _LOGGER.error("Authentication error (model=%s): %s", model, err)
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="authentication_error",
                ) from err
            except openai.RateLimitError as err:
                _LOGGER.error("Rate limit error (model=%s): %s", model, err)
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="rate_limit_error",
                ) from err
            except openai.APIConnectionError as err:
                _LOGGER.error("Connection error (model=%s): %s", model, err)
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="connection_error",
                ) from err
            except openai.APIStatusError as err:
                _LOGGER.error(
                    "API status error (model=%s, status=%s): %s",
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
                self.entity_id, _transform_stream(response)
            ):
                pass

            latency_ms = (time.monotonic() - t0) * 1000
            _LOGGER.info(
                "LiteLLM response: model=%s latency=%.0fms iteration=%d",
                model,
                latency_ms,
                _iteration + 1,
            )

            # Verify we got a response
            if not chat_log.content or not isinstance(
                chat_log.content[-1], conversation.AssistantContent
            ):
                _LOGGER.error(
                    "Model returned no content (model=%s). Check proxy logs.",
                    model,
                )
                raise HomeAssistantError(
                    f"LiteLLM model '{model}' returned no response. Check your LiteLLM proxy logs."
                )

            if not chat_log.unresponded_tool_results:
                break

            # Update messages for next iteration
            create_params["messages"] = _convert_content_to_messages(chat_log.content)
