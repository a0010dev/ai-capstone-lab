"""Verify actual exported span trees and accounting, without external APIs."""
import json
from types import SimpleNamespace

import pytest
from logfire.testing import TestExporter
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

from est_prog.capstone_reporting.agent import run_agent
from est_prog.capstone_reporting.cost_tracker import CostAccumulator, cost_usd
from est_prog.capstone_reporting.monitoring import configure_monitoring, monitoring_session
from tests.test_reporting_agent import FakeClient, call, response
from tests.test_streaming_agent import FakeStream, client_with_streams


@pytest.fixture
def exporter():
    exporter = TestExporter()
    configure_monitoring(send_to_logfire=False,
                         additional_span_processors=[SimpleSpanProcessor(exporter)])
    yield exporter
    configure_monitoring(send_to_logfire=False)


def priced_response(output, text="", input_tokens=100, output_tokens=20):
    result = response(output, text)
    result.usage = SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens)
    return result


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
    replies = [priced_response([call()]), priced_response([], "12"),
               priced_response([], "Follow-up", input_tokens=200, output_tokens=30)]
    client = (client_with_streams(*(FakeStream([], reply) for reply in replies))
              if streaming else FakeClient(replies))

    async def collect(event):
        pass

    with monitoring_session() as costs:
        first = await run_agent("Summary", client=client, on_event=collect if streaming else None)
        second = await run_agent("Follow-up", client=client,
                                 message_history=first["message_history"],
                                 on_event=collect if streaming else None)
    assert first["trace_id"] == second["trace_id"]
    assert first["usage"]["input_tokens"] == 200
    assert second["usage"]["input_tokens"] == 200
    assert costs.input_tokens == 400 and costs.output_tokens == 70
    assert costs.total_cost == pytest.approx(0.000102)
    assert second["session_usage"] == costs.as_dict()
    spans = [s for s in exporter.exported_spans
             if s.attributes.get("logfire.span_type") == "span"]
    sessions = [s for s in spans if s.name == "reporting_session"]
    runs = [s for s in spans if s.name == "agent_run"]
    models = [s for s in spans if s.name == "llm_call"]
    tools = [s for s in spans if s.name == "tool_call"]
    assert len(sessions) == 1 and len(runs) == 2 and len(models) == 3 and len(tools) == 1
    assert len({s.context.trace_id for s in spans}) == 1
    assert all(s.parent.span_id == sessions[0].context.span_id for s in runs)
    assert all(s.parent.span_id in {r.context.span_id for r in runs} for s in models + tools)
    assert sessions[0].attributes["input_tokens"] == 400
    assert tools[0].attributes["tool_name"] == "get_defect_summary"
    assert "result" in tools[0].attributes


@pytest.mark.asyncio
async def test_partial_failure_keeps_known_usage_and_marks_unknown_cost(exporter):
    class FailedClient(FakeClient):
        async def create(self, **kwargs):
            if self.requests:
                raise ConnectionError("offline")
            return await super().create(**kwargs)

    with pytest.raises(ConnectionError):
        await run_agent("Summary", client=FailedClient([priced_response([call()])]))
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
