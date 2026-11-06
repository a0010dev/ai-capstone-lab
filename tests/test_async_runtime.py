"""Async tool boundaries and structured judge output through PydanticAI."""
import threading

import pytest
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel

from est_prog.capstone_reporting import defects, tools
from est_prog.capstone_reporting.agent import run_agent
from tests.judge import assert_criteria, evaluate_criteria

pytestmark = pytest.mark.asyncio
FILTERS = dict(section="TE", date_from="2026-09-01", date_to="2026-09-30")


@pytest.mark.parametrize("name", ["get_defect_summary", "get_defect_detail", "get_defect_pareto"])
async def test_fixture_tools_run_off_event_loop_and_preserve_results(monkeypatch, name):
    original = getattr(defects, name)
    expected = original(**FILTERS)
    loop_thread = threading.get_ident()
    threads = []

    def read_fixture(**kwargs):
        threads.append(threading.get_ident())
        return original(**kwargs)

    monkeypatch.setattr(defects, name, read_fixture)
    assert await getattr(tools, name)(**FILTERS) == expected
    assert threads and threads[0] != loop_thread


async def test_agent_awaits_future_api_tool_before_next_model_round(monkeypatch):
    events = []

    async def api_summary(**kwargs):
        events.append("tool")
        assert kwargs == FILTERS
        return {"totals": {"removed_boards": 12}}

    async def respond(messages, info):
        if not events:
            events.append("first-model-round")
            return ModelResponse(parts=[ToolCallPart("get_defect_summary", FILTERS)])
        assert events == ["first-model-round", "tool"]
        result = next(p.content for p in messages[-1].parts if isinstance(p, ToolReturnPart))
        assert result["totals"]["removed_boards"] == 12
        events.append("second-model-round")
        return ModelResponse(parts=[TextPart("12")])

    monkeypatch.setattr(tools, "get_defect_summary", api_summary)
    assert (await run_agent("Summary", model=FunctionModel(respond)))["answer"] == "12"
    assert events == ["first-model-round", "tool", "second-model-round"]


async def test_judge_awaits_independent_structured_verdicts_and_rejects_failed_criterion():
    criteria = ["Use the selected section.", "Preserve zero-quantity records."]
    calls = []

    async def respond(messages, info):
        # Each criterion starts a fresh run, without another criterion's verdict.
        assert len(messages) == 1
        criterion = criteria[len(calls) % 2]
        calls.append(criterion)
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {
            "criteria": [{"criterion_description": criterion,
                          "judgement": "Fixed evidence", "passed": criterion == criteria[0]}],
            "feedback": "Fixed evaluation",
        })])

    model = FunctionModel(respond)
    result = {"answer": "Fixed answer", "tool_calls": []}
    feedback = await evaluate_criteria(result, criteria, model=model)
    assert [item.passed for item in feedback.criteria] == [True, False]
    with pytest.raises(AssertionError, match="Preserve zero-quantity records"):
        await assert_criteria(result, criteria, model=model)
    assert calls == criteria + criteria


async def test_judge_rejects_missing_or_duplicate_verdicts():
    def respond(messages, info):
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name,
                                               {"criteria": [], "feedback": "Missing"})])
    with pytest.raises(UnexpectedModelBehavior):
        await evaluate_criteria({"answer": "Fixed answer", "tool_calls": []}, ["Criterion"],
                                model=FunctionModel(respond))
