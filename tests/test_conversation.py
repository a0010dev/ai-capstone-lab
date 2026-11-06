"""Session context, clarification replies and domain metric distinctions."""
import copy
import json
import re

import pytest
from pydantic_ai.messages import ModelResponse, TextPart, ToolReturnPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel

from est_prog.capstone_reporting.agent import run_agent
from tests.test_reporting_agent import summary_model

pytestmark = pytest.mark.asyncio


async def test_short_clarification_keeps_original_period_and_does_not_mutate_history():
    first = await run_agent(
        "Compara les plaques afectades de setembre i octubre de 2026.",
        model=FunctionModel(lambda messages, info: ModelResponse(parts=[TextPart("De quina secció?")])),
    )
    saved = copy.deepcopy(first["message_history"])
    async def respond(messages, info):
        questions = [p.content for m in messages for p in m.parts if isinstance(p, UserPromptPart)]
        assert questions == ["Compara les plaques afectades de setembre i octubre de 2026.", "te"]
        assert any(isinstance(p, TextPart) and p.content == "De quina secció?"
                   for m in messages for p in m.parts)
        return ModelResponse(parts=[TextPart("TE: setembre i octubre de 2026.")])
    second = await run_agent("te", model=FunctionModel(respond), message_history=first["message_history"])
    assert first["message_history"] == saved
    second["message_history"][0]["parts"][0]["content"] = "Changed returned copy"
    assert first["message_history"] == saved


async def test_followup_replays_tool_evidence_and_final_answer():
    first = await run_agent("TE setembre 2026", model=summary_model())
    json.dumps(first["message_history"])
    def respond(messages, info):
        results = [p.content for m in messages for p in m.parts if isinstance(p, ToolReturnPart)]
        assert results[0]["totals"]["affected_boards"] == 19
        assert any(isinstance(p, TextPart) and p.content == first["answer"]
                   for m in messages for p in m.parts)
        assert messages[-1].parts[0].content == "I a l'octubre?"
        return ModelResponse(parts=[TextPart("Comparació amb octubre.")])
    await run_agent("I a l'octubre?", model=FunctionModel(respond), message_history=first["message_history"])


async def test_separate_calls_without_history_do_not_share_context():
    def respond(messages, info):
        assert len(messages) == 1
        return ModelResponse(parts=[TextPart("Quina mètrica?")])
    model = FunctionModel(respond)
    await run_agent("TE setembre", model=model)
    await run_agent("TV octubre", model=model)


async def test_failed_turn_does_not_change_supplied_history():
    history = [{"role": "user", "content": "TE setembre de 2026"},
               {"role": "assistant", "content": "Quina mètrica?"}]
    saved = copy.deepcopy(history)
    def fail(messages, info):
        raise ConnectionError("offline")
    with pytest.raises(ConnectionError):
        await run_agent("Plaques afectades", model=FunctionModel(fail), message_history=history)
    assert history == saved


@pytest.mark.parametrize("history", [{}, "TE", ["invalid item"]])
async def test_invalid_history_fails_before_model_call(history):
    def unexpected(messages, info):
        raise AssertionError("Model must not run")
    with pytest.raises(ValueError, match="message_history"):
        await run_agent("Summary", model=FunctionModel(unexpected), message_history=history)


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
    # Use streaming, as in the UI, to verify replay of native PydanticAI messages.
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
