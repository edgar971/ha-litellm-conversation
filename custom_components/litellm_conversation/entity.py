"""LiteLLM Conversation entity base."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Callable
import json
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
    DEFAULT_CHAT_MODEL,
    DEFAULT_MAX_TOKENS,
    DEFAULT_TEMPERATURE,
    DEFAULT_TOP_P,
    DOMAIN,
    LOGGER,
    MAX_TOOL_ITERATIONS,
)

if TYPE_CHECKING:
    from . import LiteLLMConfigEntry


def _format_tool(tool: llm.Tool, custom_serializer: Callable[[Any], Any] | None) -> dict[str, Any]:
    """Format tool specification for Chat Completions API."""
    schema = convert(tool.parameters, custom_serializer=custom_serializer)
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

    def _flush_tool_calls() -> list[llm.ToolInput]:
        """Build ToolInput list from accumulated tool calls and clear the buffer."""
        tool_inputs: list[llm.ToolInput] = []
        for tc in current_tool_calls.values():
            if tc["tool_call_id"] and tc["tool_name"]:
                LOGGER.debug(
                    "Tool call completed: %s (call_id=%s)",
                    tc["tool_name"],
                    tc["tool_call_id"],
                )
                args_json = tc["tool_args_json"] or "{}"
                try:
                    tool_args = json.loads(args_json)
                except (ValueError, TypeError) as err:
                    LOGGER.warning(
                        "Failed to parse tool arguments for %s (call_id=%s): %s -- raw=%s",
                        tc["tool_name"],
                        tc["tool_call_id"],
                        err,
                        repr(args_json),
                    )
                    tool_args = {}
                tool_inputs.append(
                    llm.ToolInput(
                        id=tc["tool_call_id"],
                        tool_name=tc["tool_name"],
                        tool_args=tool_args,
                    )
                )
        current_tool_calls.clear()
        return tool_inputs

    async for chunk in result:
        choice = chunk.choices[0] if chunk.choices else None
        if choice is None:
            continue

        delta = choice.delta

        if delta is not None:
            # Reasoning/thinking content (LiteLLM surfaces this for reasoning models)
            if reasoning := getattr(delta, "reasoning_content", None):
                yield {"thinking_content": reasoning}

            # Text content
            if delta.content:
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

        # On any terminal finish_reason, emit accumulated tool calls (we already
        # have them buffered, regardless of the specific reason reported).
        if choice.finish_reason:
            tool_inputs = _flush_tool_calls()
            if tool_inputs:
                yield {"tool_calls": tool_inputs}

    # Safety net: flush any leftover tool calls if the stream ended without a
    # terminal finish_reason being observed.
    tool_inputs = _flush_tool_calls()
    if tool_inputs:
        yield {"tool_calls": tool_inputs}


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
            tools = [
                _format_tool(tool, chat_log.llm_api.custom_serializer)
                for tool in chat_log.llm_api.tools
            ]

        model = self.subentry.data.get(CONF_CHAT_MODEL, DEFAULT_CHAT_MODEL)
        temperature = self.subentry.data.get(CONF_TEMPERATURE)
        top_p = self.subentry.data.get(CONF_TOP_P)
        max_tokens = self.subentry.data.get(CONF_MAX_TOKENS, DEFAULT_MAX_TOKENS)
        reasoning_effort = self.subentry.data.get(CONF_REASONING_EFFORT)

        messages = _convert_content_to_messages(chat_log.content)

        create_params: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
            "max_tokens": max_tokens,
        }

        # Only send temperature OR top_p (not both) — Bedrock rejects requests
        # containing both. Prefer temperature; omit both when unset so the
        # provider default applies.
        if temperature is not None and temperature != DEFAULT_TEMPERATURE:
            create_params["temperature"] = temperature
            if top_p is not None and top_p != DEFAULT_TOP_P:
                LOGGER.warning(
                    "Both temperature and top_p are set; sending only temperature "
                    "(some providers reject both)"
                )
        elif top_p is not None and top_p != DEFAULT_TOP_P:
            create_params["top_p"] = top_p

        if tools:
            create_params["tools"] = tools

        if structure is not None and structure_name is not None:
            output_schema = convert(structure)
            # Omit `strict` — not supported by Bedrock and many non-OpenAI providers.
            create_params["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": structure_name,
                    "schema": output_schema,
                },
            }

        # Ask the proxy to silently drop any params unsupported by the target provider.
        extra_body: dict[str, Any] = {"drop_params": True}
        # reasoning_effort is a LiteLLM body param (not a header); drop_params
        # strips it for models that don't support reasoning.
        if reasoning_effort and reasoning_effort != "none":
            extra_body["reasoning_effort"] = reasoning_effort

        for _iteration in range(max_iterations):
            LOGGER.debug(
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
                    extra_body=extra_body,
                )
            except openai.AuthenticationError as err:
                LOGGER.error("Authentication error (model=%s): %s", model, err)
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="authentication_error",
                ) from err
            except openai.RateLimitError as err:
                LOGGER.error("Rate limit error (model=%s): %s", model, err)
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="rate_limit_error",
                ) from err
            except openai.APIConnectionError as err:
                LOGGER.error("Connection error (model=%s): %s", model, err)
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="connection_error",
                ) from err
            except openai.APIStatusError as err:
                LOGGER.error(
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

            content_len_before = len(chat_log.content)

            async for _ in chat_log.async_add_delta_content_stream(
                self.entity_id, _transform_stream(response)
            ):
                pass

            latency_ms = (time.monotonic() - t0) * 1000
            LOGGER.info(
                "LiteLLM response: model=%s latency=%.0fms iteration=%d",
                model,
                latency_ms,
                _iteration + 1,
            )

            # Verify the stream actually added something to the chat log.
            if len(chat_log.content) == content_len_before:
                LOGGER.error(
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
