"""Unit tests for entity._transform_stream — the OpenAI stream → HA delta transform."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from custom_components.litellm_conversation.entity import _transform_stream


def _chunk(
    *,
    content: str | None = None,
    tool_calls: list | None = None,
    finish_reason: str | None = None,
    reasoning_content: str | None = None,
    choices: bool = True,
) -> SimpleNamespace:
    """Build a fake ChatCompletionChunk."""
    if not choices:
        return SimpleNamespace(choices=[])
    delta = SimpleNamespace(
        content=content,
        tool_calls=tool_calls,
        reasoning_content=reasoning_content,
    )
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta, finish_reason=finish_reason)])


def _tc_delta(
    index: int,
    call_id: str | None = None,
    name: str | None = None,
    arguments: str | None = None,
) -> SimpleNamespace:
    """Build a fake tool call delta."""
    function = SimpleNamespace(name=name, arguments=arguments)
    return SimpleNamespace(index=index, id=call_id, function=function)


async def _stream(chunks: list) -> Any:
    for c in chunks:
        yield c


async def _collect(chunks: list) -> list[dict[str, Any]]:
    return [delta async for delta in _transform_stream(_stream(chunks))]


async def test_text_only() -> None:
    """Plain text deltas pass through."""
    deltas = await _collect(
        [
            _chunk(content="Hello"),
            _chunk(content=" world"),
            _chunk(finish_reason="stop"),
        ]
    )
    assert deltas == [{"content": "Hello"}, {"content": " world"}]


async def test_empty_choices_skipped() -> None:
    """Chunks without choices (e.g. usage-only) are ignored."""
    deltas = await _collect([_chunk(choices=False), _chunk(content="hi")])
    assert deltas == [{"content": "hi"}]


async def test_reasoning_content_becomes_thinking() -> None:
    """LiteLLM reasoning_content maps to HA thinking_content."""
    deltas = await _collect(
        [
            _chunk(reasoning_content="pondering..."),
            _chunk(content="42"),
        ]
    )
    assert deltas == [{"thinking_content": "pondering..."}, {"content": "42"}]


async def test_single_tool_call_assembled_across_chunks() -> None:
    """Tool call id/name arrive first, arguments stream in fragments."""
    deltas = await _collect(
        [
            _chunk(tool_calls=[_tc_delta(0, call_id="call_1", name="turn_on")]),
            _chunk(tool_calls=[_tc_delta(0, arguments='{"entity_id":')]),
            _chunk(tool_calls=[_tc_delta(0, arguments='"light.kitchen"}')]),
            _chunk(finish_reason="tool_calls"),
        ]
    )
    assert len(deltas) == 1
    (tool_delta,) = deltas
    (tool_input,) = tool_delta["tool_calls"]
    assert tool_input.id == "call_1"
    assert tool_input.tool_name == "turn_on"
    assert tool_input.tool_args == {"entity_id": "light.kitchen"}


async def test_parallel_tool_calls() -> None:
    """Two tool calls at different indexes are kept separate."""
    deltas = await _collect(
        [
            _chunk(
                tool_calls=[
                    _tc_delta(0, call_id="a", name="tool_a", arguments="{}"),
                    _tc_delta(1, call_id="b", name="tool_b", arguments='{"x": 1}'),
                ]
            ),
            _chunk(finish_reason="tool_calls"),
        ]
    )
    (tool_delta,) = deltas
    calls = tool_delta["tool_calls"]
    assert [c.tool_name for c in calls] == ["tool_a", "tool_b"]
    assert calls[1].tool_args == {"x": 1}


async def test_malformed_tool_args_fall_back_to_empty_dict() -> None:
    """Invalid JSON arguments must not crash the stream."""
    deltas = await _collect(
        [
            _chunk(tool_calls=[_tc_delta(0, call_id="c1", name="t", arguments="{not json")]),
            _chunk(finish_reason="tool_calls"),
        ]
    )
    (tool_delta,) = deltas
    assert tool_delta["tool_calls"][0].tool_args == {}


async def test_tool_calls_flushed_without_finish_reason() -> None:
    """Safety net: stream ends with buffered tool calls but no finish_reason."""
    deltas = await _collect(
        [_chunk(tool_calls=[_tc_delta(0, call_id="c1", name="t", arguments="{}")])]
    )
    assert len(deltas) == 1
    assert deltas[0]["tool_calls"][0].tool_name == "t"


async def test_incomplete_tool_call_dropped() -> None:
    """A tool call without id or name is not emitted."""
    deltas = await _collect(
        [
            _chunk(tool_calls=[_tc_delta(0, arguments='{"x": 1}')]),
            _chunk(finish_reason="tool_calls"),
        ]
    )
    assert deltas == []


async def test_text_then_tool_call() -> None:
    """Mixed content: text deltas followed by a tool call."""
    deltas = await _collect(
        [
            _chunk(content="Turning it on."),
            _chunk(tool_calls=[_tc_delta(0, call_id="c1", name="turn_on", arguments="{}")]),
            _chunk(finish_reason="tool_calls"),
        ]
    )
    assert deltas[0] == {"content": "Turning it on."}
    assert deltas[1]["tool_calls"][0].tool_name == "turn_on"
