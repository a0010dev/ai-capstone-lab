"""Async boundaries and resource ownership, without external API calls."""
import asyncio
import json
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from est_prog.capstone_reporting import defects, tools
from est_prog.capstone_reporting.agent import TOOL_FUNCTIONS, run_agent
from tests.judge import JudgeCriterion, JudgeFeedback, assert_criteria, evaluate_criteria


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


@pytest.mark.parametrize("fails", [False, True], ids=["success", "transport-error"])
async def test_agent_closes_owned_client_on_success_and_failure(monkeypatch, fails):
    client = MagicMock()
    client.responses.create = AsyncMock(
        return_value=SimpleNamespace(status="completed", output=[], output_text="Done"),
        side_effect=ConnectionError("offline") if fails else None,
    )
    client.__aenter__.return_value = client
    monkeypatch.setattr("openai.AsyncOpenAI", MagicMock(return_value=client))
    if fails:
        with pytest.raises(ConnectionError):
            await run_agent("Summary")
    else:
        assert (await run_agent("Summary"))["answer"] == "Done"
    client.responses.create.assert_awaited_once()
    client.__aexit__.assert_awaited_once()


async def test_agent_cancellation_closes_owned_client(monkeypatch):
    entered = asyncio.Event()

    async def wait_for_response(**kwargs):
        entered.set()
        await asyncio.Event().wait()

    client = MagicMock()
    client.__aenter__.return_value = client
    client.responses.create = AsyncMock(side_effect=wait_for_response)
    monkeypatch.setattr("openai.AsyncOpenAI", MagicMock(return_value=client))
    task = asyncio.create_task(run_agent("Summary"))
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    client.__aexit__.assert_awaited_once()


async def test_agent_awaits_future_api_tool_before_next_model_round(monkeypatch):
    """An async HTTP implementation can occupy the same allowlisted tool slot."""
    events = []

    async def api_summary(**kwargs):
        events.append("tool")
        assert kwargs == FILTERS
        return {"totals": {"removed_boards": 12}}

    async def model_response(**kwargs):
        if not events:
            events.append("first-model-round")
            call = SimpleNamespace(type="function_call", name="get_defect_summary",
                                   arguments=json.dumps(FILTERS), call_id="call_1")
            return SimpleNamespace(status="completed", output=[call])
        assert events == ["first-model-round", "tool"]
        output = kwargs["input"][-1]
        assert json.loads(output["output"])["totals"]["removed_boards"] == 12
        events.append("second-model-round")
        return SimpleNamespace(status="completed", output=[], output_text="12")

    monkeypatch.setitem(TOOL_FUNCTIONS, "get_defect_summary", api_summary)
    client = MagicMock()
    client.responses.create = AsyncMock(side_effect=model_response)
    assert (await run_agent("Summary", client=client))["answer"] == "12"
    assert events == ["first-model-round", "tool", "second-model-round"]
    client.__aexit__.assert_not_called()  # Injected clients belong to the caller.


async def test_judge_awaits_separate_verdicts_and_rejects_failed_criterion():
    criteria = ["Use the selected section.", "Preserve zero-quantity records."]
    replies = [
        SimpleNamespace(status="completed", output_parsed=JudgeFeedback(
            criteria=[JudgeCriterion(criterion_description=criterion,
                                     judgement="Fixed evidence", passed=index == 0)],
            feedback="Fixed evaluation",
        )) for index, criterion in enumerate(criteria)
    ]
    client = MagicMock()
    client.responses.parse = AsyncMock(side_effect=replies + replies)
    result = {"answer": "Fixed answer", "tool_calls": []}
    feedback = await evaluate_criteria(result, criteria, client=client)
    assert [item.passed for item in feedback.criteria] == [True, False]
    with pytest.raises(AssertionError, match="Preserve zero-quantity records"):
        await assert_criteria(result, criteria, client=client)
    assert client.responses.parse.await_count == 4
    client.__aexit__.assert_not_called()


async def test_judge_closes_owned_client_when_verdict_is_missing(monkeypatch):
    client = MagicMock()
    client.__aenter__.return_value = client
    client.responses.parse = AsyncMock(return_value=SimpleNamespace(
        status="completed", output_parsed=None,
    ))
    monkeypatch.setattr("tests.judge.AsyncOpenAI", MagicMock(return_value=client))
    with pytest.raises(AssertionError, match="no structured verdict"):
        await evaluate_criteria({"answer": "Fixed answer", "tool_calls": []}, ["Criterion"])
    client.__aexit__.assert_awaited_once()
