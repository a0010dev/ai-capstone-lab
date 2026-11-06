"""UI streaming rendering and real-model event contract."""
import json
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.asyncio


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
