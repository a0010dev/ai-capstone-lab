"""Streaming order, complete arguments, final results and cleanup; no API calls."""
import asyncio
import json
from types import SimpleNamespace as Item
from unittest.mock import AsyncMock, MagicMock

import pytest
from openai.types.responses.parsed_response import (
    ParsedResponseFunctionToolCall, ParsedResponseOutputMessage, ParsedResponseOutputText,
)

from est_prog.capstone_reporting.agent import TOOL_FUNCTIONS, run_agent
from tests.test_reporting_agent import FakeClient, call, response


pytestmark = pytest.mark.asyncio


class FakeStream:
    def __init__(self, events, final, error=None):
        self.events = events
        self.final = final
        self.error = error
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.closed = True

    async def __aiter__(self):
        for event in self.events:
            yield event
        if self.error:
            raise self.error

    async def get_final_response(self):
        return self.final


def client_with_streams(*streams):
    client = MagicMock()
    client.responses.stream = MagicMock(side_effect=streams)
    client.responses.create = AsyncMock()
    return client


def delta(text):
    return Item(type="response.output_text.delta", delta=text)


async def test_streaming_preserves_tool_protocol_and_final_result(monkeypatch):
    reasoning = Item(type="reasoning")
    tool_call = ParsedResponseFunctionToolCall(
        type="function_call", name="get_defect_summary", call_id="call_1",
        arguments=call().arguments, parsed_arguments={"sdk_only": True},
    )
    message = ParsedResponseOutputMessage(
        id="msg_1", type="message", role="assistant", status="completed",
        content=[ParsedResponseOutputText(type="output_text", text="Consulto les dades…",
                                          annotations=[], parsed={"sdk_only": True})],
    )
    first = FakeStream([
        delta("Consulto les dades…"),
        Item(type="response.function_call_arguments.delta", delta='{"section":'),
        Item(type="response.function_call_arguments.delta", delta='"TE"}'),
    ], response([reasoning, message, tool_call]))
    second = FakeStream([delta("Dades sintètiques: "), delta("12 retirades.")],
                        response([], "Dades sintètiques: 12 retirades."))
    client = client_with_streams(first, second)
    original = TOOL_FUNCTIONS["get_defect_summary"]
    tool = AsyncMock(side_effect=original)
    monkeypatch.setitem(TOOL_FUNCTIONS, "get_defect_summary", tool)
    events = []

    async def collect(event):
        if event["type"] == "text_delta" and event["round"] == 1:
            tool.assert_not_awaited()  # Argument fragments cannot execute a tool.
        if event["type"] == "tool_start":
            assert json.loads(event["arguments"])["date_to"] == "2026-09-30"
            tool.assert_not_awaited()
        if event["type"] == "tool_end":
            tool.assert_awaited_once()
        events.append(event)

    result = await run_agent("Summary", client=client, today="2026-10-16", on_event=collect)
    assert [event["type"] for event in events] == [
        "round_start", "text_delta", "tool_start", "tool_end",
        "round_start", "text_delta", "text_delta", "completed",
    ]
    second_input = client.responses.stream.call_args_list[1].kwargs["input"]
    assert {"type": "reasoning"} in second_input
    function_input = next(item for item in second_input if isinstance(item, dict)
                          and item.get("type") == "function_call")
    assert "parsed_arguments" not in function_input
    message_input = next(item for item in second_input if isinstance(item, dict)
                         and item.get("type") == "message")
    assert "parsed" not in message_input["content"][0]
    assert tool_call.parsed_arguments == {"sdk_only": True}  # Source stays intact.
    assert second_input[-1]["call_id"] == tool_call.call_id
    assert json.loads(second_input[-1]["output"])["totals"]["removed_boards"] == 12
    assert first.closed and second.closed
    assert events[-1]["result"] == result
    assert "Consulto" not in result["answer"]
    non_streamed = await run_agent(
        "Summary", client=FakeClient([first.final, second.final]), today="2026-10-16",
    )
    assert {k: v for k, v in result.items() if k != "trace_id"} == {
        k: v for k, v in non_streamed.items() if k != "trace_id"
    }
    assert result["trace_id"] != non_streamed["trace_id"]
    client.responses.create.assert_not_awaited()
    client.__aexit__.assert_not_called()  # Caller owns the injected client.


@pytest.mark.parametrize("mode", ["transport", "incomplete", "callback"])
async def test_streaming_failure_closes_stream_and_owned_client(monkeypatch, mode):
    stream = FakeStream([delta("Partial")], response([], "Partial"),
                        error=ConnectionError("offline") if mode == "transport" else None)
    if mode == "incomplete":
        stream.final.status = "incomplete"
    client = client_with_streams(stream)
    client.__aenter__.return_value = client
    monkeypatch.setattr("openai.AsyncOpenAI", MagicMock(return_value=client))
    events = []

    async def collect(event):
        events.append(event)
        if mode == "callback" and event["type"] == "text_delta":
            raise RuntimeError("consumer failed")

    with pytest.raises((ConnectionError, RuntimeError)):
        await run_agent("Summary", on_event=collect)
    assert stream.closed
    client.__aexit__.assert_awaited_once()
    assert "completed" not in [event["type"] for event in events]


async def test_streaming_cancellation_closes_stream_and_owned_client(monkeypatch):
    stream = FakeStream([delta("Partial")], response([], "Partial"))
    client = client_with_streams(stream)
    client.__aenter__.return_value = client
    monkeypatch.setattr("openai.AsyncOpenAI", MagicMock(return_value=client))
    entered = asyncio.Event()

    async def collect(event):
        if event["type"] == "text_delta":
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(run_agent("Summary", on_event=collect))
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert stream.closed
    client.__aexit__.assert_awaited_once()


async def test_streaming_round_limit_does_not_emit_completed():
    stream = FakeStream([], response([call()]))
    client = client_with_streams(stream)
    collect = AsyncMock()
    with pytest.raises(RuntimeError, match="max_rounds"):
        await run_agent("Summary", client=client, max_rounds=1, on_event=collect)
    assert stream.closed
    assert "completed" not in [entry.args[0]["type"] for entry in collect.await_args_list]


async def test_ui_renderer_updates_before_completion_and_resets_provisional_text():
    from app import LiveResponse

    answer = MagicMock()
    live = LiveResponse(MagicMock(), answer)
    await live.on_event({"type": "round_start", "round": 1})
    await live.on_event({"type": "text_delta", "delta": "Provisional", "round": 1})
    answer.markdown.assert_called_with("Provisional ▌")
    await live.on_event({"type": "round_start", "round": 2})
    assert live.text == ""
    await live.on_event({"type": "text_delta", "delta": "Final", "round": 2})
    answer.markdown.assert_called_with("Final ▌")
    await live.on_event({"type": "completed", "result": {"answer": "Final answer"}})
    answer.markdown.assert_called_with("Final answer")


@pytest.mark.integration
async def test_real_stream_emits_tools_and_text_before_final_result(agent):
    events = []
    returned = False

    async def collect(event):
        assert not returned
        events.append(event)

    result = await agent(
        "Fes un Pareto de plaques retirades per codi de defecte de TE "
        "entre el 2026-09-01 i el 2026-09-30, ambdós inclosos.",
        on_event=collect,
    )
    returned = True
    assert events[-1] == {"type": "completed", "result": result}
    starts = [event for event in events if event["type"] == "tool_start"]
    ends = [event for event in events if event["type"] == "tool_end"]
    assert starts and len(starts) == len(ends)
    assert [event["call_id"] for event in starts] == [event["call_id"] for event in ends]
    assert [event["call"] for event in ends] == result["tool_calls"]
    paretos = [event for event in starts if event["name"] == "get_defect_pareto"]
    assert paretos, starts
    assert json.loads(paretos[0]["arguments"]) == {
        "section": "TE", "date_from": "2026-09-01", "date_to": "2026-09-30",
        "metric": "removed_boards",
    }
    final_round = max(event["round"] for event in events if event["type"] == "round_start")
    fragments = [event["delta"] for event in events
                 if event["type"] == "text_delta" and event["round"] == final_round]
    assert fragments and "".join(fragments) == result["answer"]
    print(json.dumps({"event_types": [event["type"] for event in events],
                      "final_round_text_fragments": len(fragments)}, indent=2))
