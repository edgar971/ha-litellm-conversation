#!/usr/bin/env python3
"""Standalone live streaming test against the LiteLLM proxy.

Mirrors what custom_components/litellm_conversation/entity.py::_transform_stream
does, so we can verify tool calling end-to-end without a running Home Assistant.

Run:
    python3 tests/test_streaming_live.py

API key resolution order:
    1. $LITELLM_API_KEY
    2. ~/.openclaw/openclaw.json at models.providers.litellm.apiKey
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import openai

BASE_URL = "https://llm.pinocasa.com/v1"
MODEL = "bedrock-claude-4-6-sonnet"

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "turn_light_on",
            "description": "Turn on a light",
            "parameters": {
                "type": "object",
                "properties": {"entity_id": {"type": "string"}},
                "required": ["entity_id"],
            },
        },
    }
]


def _load_api_key() -> str:
    key = os.environ.get("LITELLM_API_KEY")
    if key:
        return key
    cfg = Path.home() / ".openclaw" / "openclaw.json"
    data = json.loads(cfg.read_text())
    return data["models"]["providers"]["litellm"]["apiKey"]


async def _transform_stream(result: openai.AsyncStream) -> list[dict[str, Any]]:
    """Replica of entity.py::_transform_stream, collecting yielded deltas.

    Returns the list of delta dicts that would be yielded to HA's ChatLog:
    {"content": "..."} for text and {"tool_calls": [...]} for tool calls.
    """
    deltas: list[dict[str, Any]] = []
    current_tool_calls: dict[int, dict[str, Any]] = {}

    def _flush_tool_calls() -> list[dict[str, Any]]:
        tool_inputs: list[dict[str, Any]] = []
        for tc in current_tool_calls.values():
            if tc["tool_call_id"] and tc["tool_name"]:
                args_json = tc["tool_args_json"] or "{}"
                try:
                    tool_args = json.loads(args_json)
                except (ValueError, TypeError):
                    tool_args = {}
                tool_inputs.append(
                    {
                        "id": tc["tool_call_id"],
                        "tool_name": tc["tool_name"],
                        "tool_args": tool_args,
                    }
                )
        current_tool_calls.clear()
        return tool_inputs

    async for chunk in result:
        choice = chunk.choices[0] if chunk.choices else None
        if choice is None:
            continue

        delta = choice.delta
        if delta is not None:
            if delta.content:
                deltas.append({"content": delta.content})
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

        if choice.finish_reason:
            tool_inputs = _flush_tool_calls()
            if tool_inputs:
                deltas.append({"tool_calls": tool_inputs})

    tool_inputs = _flush_tool_calls()
    if tool_inputs:
        deltas.append({"tool_calls": tool_inputs})

    return deltas


def _collect_text(deltas: list[dict[str, Any]]) -> str:
    return "".join(d["content"] for d in deltas if "content" in d)


def _collect_tool_calls(deltas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for d in deltas:
        if "tool_calls" in d:
            calls.extend(d["tool_calls"])
    return calls


async def _create_stream(
    client: openai.AsyncOpenAI,
    messages: list[dict[str, Any]],
    *,
    with_tools: bool,
) -> openai.AsyncStream:
    params: dict[str, Any] = {
        "model": MODEL,
        "messages": messages,
        "stream": True,
        "max_tokens": 1024,
    }
    if with_tools:
        params["tools"] = TOOLS
    return await client.chat.completions.create(
        **params,
        extra_body={"drop_params": True},
    )


async def test_simple_text(client: openai.AsyncOpenAI) -> bool:
    print("\n=== Test A: simple text response ===")
    stream = await _create_stream(
        client,
        [{"role": "user", "content": "say hello"}],
        with_tools=False,
    )
    deltas = await _transform_stream(stream)
    text = _collect_text(deltas)
    tool_calls = _collect_tool_calls(deltas)
    print(f"  text yielded: {text!r}")
    print(f"  tool_calls:   {tool_calls}")
    ok = bool(text) and not tool_calls
    print(f"  -> {'PASS' if ok else 'FAIL'}")
    return ok


async def test_tool_call(client: openai.AsyncOpenAI) -> tuple[bool, list[dict[str, Any]]]:
    print("\n=== Test B: tool call response ===")
    stream = await _create_stream(
        client,
        [{"role": "user", "content": "Please turn on the kitchen light"}],
        with_tools=True,
    )
    deltas = await _transform_stream(stream)
    text = _collect_text(deltas)
    tool_calls = _collect_tool_calls(deltas)
    print(f"  text yielded: {text!r}")
    print(f"  tool_calls:   {json.dumps(tool_calls, indent=2)}")
    ok = (
        len(tool_calls) == 1
        and tool_calls[0]["tool_name"] == "turn_light_on"
        and isinstance(tool_calls[0]["tool_args"], dict)
        and bool(tool_calls[0]["id"])
    )
    print(f"  -> {'PASS' if ok else 'FAIL'}")
    return ok, tool_calls


async def test_tool_followup(client: openai.AsyncOpenAI, tool_calls: list[dict[str, Any]]) -> bool:
    print("\n=== Test C: tool call + follow-up loop ===")
    if not tool_calls:
        print("  no tool call from Test B to follow up on -> FAIL")
        return False

    call = tool_calls[0]
    # Replay the full conversation the way entity.py rebuilds messages:
    # user -> assistant(tool_calls) -> tool(result) -> expect final text.
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": "Please turn on the kitchen light"},
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": call["id"],
                    "type": "function",
                    "function": {
                        "name": call["tool_name"],
                        "arguments": json.dumps(call["tool_args"]),
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": call["id"],
            "content": json.dumps({"success": True, "entity_id": "light.kitchen"}),
        },
    ]
    stream = await _create_stream(client, messages, with_tools=True)
    deltas = await _transform_stream(stream)
    text = _collect_text(deltas)
    tool_calls_2 = _collect_tool_calls(deltas)
    print(f"  final text yielded: {text!r}")
    print(f"  tool_calls:         {tool_calls_2}")
    ok = bool(text)
    print(f"  -> {'PASS' if ok else 'FAIL'}")
    return ok


async def main() -> int:
    client = openai.AsyncOpenAI(api_key=_load_api_key(), base_url=BASE_URL)

    a = await test_simple_text(client)
    b, tool_calls = await test_tool_call(client)
    c = await test_tool_followup(client, tool_calls)

    print("\n=== Summary ===")
    print(f"  A (text):      {'PASS' if a else 'FAIL'}")
    print(f"  B (tool call): {'PASS' if b else 'FAIL'}")
    print(f"  C (follow-up): {'PASS' if c else 'FAIL'}")
    return 0 if (a and b and c) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
