"""Verify actual exported span trees and accounting, without external APIs."""
import json

import pytest
from logfire.testing import TestExporter
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import DeltaToolCall, FunctionModel
from pydantic_ai.usage import RequestUsage

from est_prog.capstone_reporting.agent import run_agent
from est_prog.capstone_reporting.cost_tracker import CostAccumulator, cost_usd
from est_prog.capstone_reporting.monitoring import configure_monitoring, monitoring_session

FILTERS = dict(section="TE", date_from="2026-09-01", date_to="2026-09-30")


@pytest.fixture
def exporter():
    exporter = TestExporter()
    configure_monitoring(send_to_logfire=False,
                         additional_span_processors=[SimpleSpanProcessor(exporter)])
    yield exporter
    configure_monitoring(send_to_logfire=False)


def test_course_cost_formula_and_unpriced_or_missing_usage():
    assert cost_usd("openai:gpt-4o-mini", 5692, 816) == pytest.approx(0.00134340)
    assert cost_usd("unpriced-model", 100, 20) is None
    costs = CostAccumulator("gpt-4o-mini")
    costs.add(None)
    assert costs.total_cost is None
    assert costs.missing_usage == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
async def test_two_turn_session_has_one_trace_and_counts_each_response_once(exporter, streaming):
    responses = iter([
        ModelResponse(parts=[ToolCallPart("get_defect_summary", FILTERS)],
                      usage=RequestUsage(input_tokens=100, output_tokens=20)),
        ModelResponse(parts=[TextPart("12 synthetic-defects-v1")],
                      usage=RequestUsage(input_tokens=100, output_tokens=20)),
        ModelResponse(parts=[TextPart("Follow-up")],
                      usage=RequestUsage(input_tokens=200, output_tokens=30)),
    ])

    def respond(messages, info):
        return next(responses)

    async def stream(messages, info):
        for part in next(responses).parts:
            if isinstance(part, ToolCallPart):
                yield {0: DeltaToolCall(name=part.tool_name, json_args=part.args_as_json_str())}
            else:
                yield part.content

    model = FunctionModel(respond, stream_function=stream, model_name="gpt-4o-mini")

    async def collect(event):
        pass

    with monitoring_session() as costs:
        first = await run_agent("Summary", model=model, on_event=collect if streaming else None)
        second = await run_agent("Follow-up", model=model,
                                 message_history=first["message_history"],
                                 on_event=collect if streaming else None)
    assert first["trace_id"] == second["trace_id"]
    # Compare accounting with native response usage, including the streaming path.
    native_usage = [m["usage"] for m in second["message_history"] if m["kind"] == "response"]
    assert len(native_usage) == costs.requests == 3
    assert first["usage"]["requests"] == 2
    assert second["usage"]["requests"] == 1
    assert costs.input_tokens == sum(u["input_tokens"] for u in native_usage)
    assert costs.output_tokens == sum(u["output_tokens"] for u in native_usage)
    assert costs.total_cost == pytest.approx(cost_usd("gpt-4o-mini", costs.input_tokens, costs.output_tokens))
    assert second["session_usage"] == costs.as_dict()
    spans = [s for s in exporter.exported_spans
             if s.attributes.get("logfire.span_type") == "span"]
    sessions = [s for s in spans if s.name == "reporting_session"]
    runs = [s for s in spans if s.name == "agent_run"]
    models = [s for s in spans if s.attributes.get("gen_ai.operation.name") == "chat"]
    tools = [s for s in spans if s.attributes.get("gen_ai.tool.name") == "get_defect_summary"]
    assert len(sessions) == 1 and len(runs) == 2 and len(models) == 3 and len(tools) == 1
    assert len({s.context.trace_id for s in spans}) == 1
    assert all(s.parent.span_id == sessions[0].context.span_id for s in runs)
    assert sessions[0].attributes["input_tokens"] == costs.input_tokens
    assert all(s.parent is not None for s in models + tools)


@pytest.mark.asyncio
async def test_partial_failure_keeps_known_usage_and_marks_unknown_cost(exporter):
    calls = 0

    def respond(messages, info):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ConnectionError("offline")
        return ModelResponse(parts=[ToolCallPart("get_defect_summary", FILTERS)],
                             usage=RequestUsage(input_tokens=100, output_tokens=20))

    with pytest.raises(ConnectionError):
        await run_agent("Summary", model=FunctionModel(respond))
    session = next(s for s in exporter.exported_spans if s.name == "reporting_session"
                   and s.attributes.get("logfire.span_type") == "span")
    assert session.attributes["input_tokens"] == 100
    assert session.attributes["output_tokens"] == 20
    assert session.attributes["missing_usage"] == 1
    assert json.loads(session.attributes["estimated_cost_usd"]) is None
    assert session.events  # Exception recorded, rather than a successful trace.


def test_local_export_contains_only_completed_spans(tmp_path):
    path = tmp_path / "trace.jsonl"
    configure_monitoring(trace_file=path, send_to_logfire=False)
    try:
        with monitoring_session():
            pass
        spans = [json.loads(line) for line in path.read_text().splitlines()]
        assert len(spans) == 1
        assert spans[0]["name"] == "reporting_session"
        assert spans[0]["attributes"]["logfire.span_type"] == "span"
        assert spans[0]["end_time"] >= spans[0]["start_time"]
    finally:
        configure_monitoring(send_to_logfire=False)
