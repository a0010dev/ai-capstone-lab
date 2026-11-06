"""Session context, clarification replies and domain metric distinctions."""
import copy
import json
import re

import pytest

from est_prog.capstone_reporting.agent import run_agent
from tests.test_reporting_agent import FakeClient, call, response


pytestmark = pytest.mark.asyncio


async def test_short_clarification_keeps_original_period_and_does_not_mutate_history():
    first = await run_agent(
        "Compara les plaques afectades de setembre i octubre de 2026.",
        client=FakeClient([response([], "De quina secció?")]),
    )
    history = first["message_history"]
    saved = copy.deepcopy(history)
    client = FakeClient([response([], "TE: setembre i octubre de 2026.")])
    second = await run_agent("te", client=client, message_history=history)
    assert client.requests[0]["input"] == saved + [{"role": "user", "content": "te"}]
    assert history == saved
    assert second["message_history"][-1]["content"] == second["answer"]
    second["message_history"][0]["content"] = "Changed returned copy"
    assert history == saved


async def test_followup_replays_tool_evidence_and_final_answer():
    first = await run_agent(
        "Mostra les plaques afectades de TE durant setembre de 2026.",
        client=FakeClient([response([call()]), response([], "19 plaques afectades.")]),
        today="2026-11-03",
    )
    history = first["message_history"]
    json.dumps(history)  # Replayable items are serializable, not SDK objects.
    source = next(item for item in history if item.get("type") == "function_call_output")
    assert json.loads(source["output"])["totals"]["affected_boards"] == 19
    client = FakeClient([response([], "Comparació amb octubre.")])
    await run_agent("I a l'octubre?", client=client, message_history=history)
    assert client.requests[0]["input"][:-1] == history
    assert client.requests[0]["input"][-1] == {"role": "user", "content": "I a l'octubre?"}
    assert client.requests[0]["store"] is False


async def test_separate_calls_without_history_do_not_share_context():
    await run_agent("TE setembre", client=FakeClient([response([], "First")]))
    client = FakeClient([response([], "Second")])
    await run_agent("TV octubre", client=client)
    assert client.requests[0]["input"] == [{"role": "user", "content": "TV octubre"}]


async def test_failed_turn_does_not_change_supplied_history():
    history = [{"role": "user", "content": "TE setembre de 2026"},
               {"role": "assistant", "content": "Quina mètrica?"}]
    before = copy.deepcopy(history)
    with pytest.raises(RuntimeError, match="did not complete"):
        await run_agent("Plaques afectades", message_history=history,
                        client=FakeClient([response([], status="incomplete")]))
    assert history == before


@pytest.mark.parametrize("history", [{}, "TE", ["invalid item"]])
async def test_invalid_history_fails_before_model_call(history):
    client = FakeClient([])
    with pytest.raises(ValueError, match="message_history"):
        await run_agent("Summary", client=client, message_history=history)
    assert client.requests == []


@pytest.mark.integration
async def test_real_short_section_reply_resolves_pending_comparison(agent):
    # Seed the clarification state to test reply resolution independently of
    # whether the model reliably asks the initial clarification (a separate test).
    history = [
        {"role": "user", "content": "Compara les plaques afectades de setembre i octubre de 2026."},
        {"role": "assistant", "content": "De quina secció vols la comparació?"},
    ]
    second = await agent("te", message_history=history, today="2026-11-03")
    summaries = [call for call in second["tool_calls"] if call["name"] == "get_defect_summary"]
    assert summaries
    selections = [json.loads(call["arguments"]) for call in summaries]
    assert {item["section"] for item in selections} == {"TE"}
    assert {item["date_from"] for item in selections} == {"2026-09-01", "2026-10-01"}
    assert {item["date_to"] for item in selections} == {"2026-09-30", "2026-10-31"}
    assert re.search(r"\b19\b", second["answer"])
    assert re.search(r"\b3\b", second["answer"])


@pytest.mark.integration
async def test_real_month_followup_keeps_two_sections_and_does_not_invent_production(agent):
    # Use streaming, as in the UI, to verify replay of normalized SDK items.
    async def observe(event):
        pass

    first = await agent(
        "Quantes plaques s'han fet a TE i a TV el setembre de 2026? Quantes amb error?",
        on_event=observe,
        today="2026-11-03",
    )
    second = await agent(
        "I a l'octubre, n'hi ha més o menys?",
        on_event=observe, message_history=first["message_history"],
        today="2026-11-03",
    )
    october = [json.loads(call["arguments"]) for call in second["tool_calls"]
               if json.loads(call["arguments"])["date_from"] == "2026-10-01"]
    assert {item["section"] for item in october} == {"TE", "TV"}
    assert all(item["date_to"] == "2026-10-31" for item in october)
    # Exact missing-coverage wording is checked by the existing empty-data
    # behavioral tests; here we isolate inherited scope and metric meanings.
    assert {json.loads(call["arguments"])["section"] for call in first["tool_calls"]} == {"TE", "TV"}
    # Accept equivalent wording for inspected samples without relabelling them
    # as production, or using errors=23 as affected boards instead of 19.
    answer = first["answer"].casefold().replace("*", "")
    assert re.search(r"mostra|examinad|inspeccionad", answer)
    assert "afectad" in answer and re.search(r"\b19\b", answer)
    assert not re.search(r"plaques (?:completes|produïdes|fabricades)\s*[:|]\s*(?:220|60)", answer)
    assert not re.search(r"plaques (?:afectades|amb error)\s*[:|]\s*23\b", answer)
