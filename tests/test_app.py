"""UI regression checks with fake model calls; no network or API costs."""

import json
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from est_prog.capstone_reporting.defects import get_defect_summary


APP = str(Path(__file__).resolve().parents[1] / "app.py")
FILTERS = dict(section="TE", date_from="2026-09-01", date_to="2026-09-30")
QUESTION = "Quantes plaques hem retirat a TE durant setembre de 2026?"


def result():
    return {
        "answer": "Dades sintètiques: 12 plaques retirades.",
        "tool_calls": [{"name": "get_defect_summary", "arguments": json.dumps(FILTERS),
                        "result": get_defect_summary(**FILTERS)}],
        "model": "test-model", "reference_date": "2026-11-02",
    }


def test_chat_followup_history_and_clear(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    with patch("est_prog.capstone_reporting.agent.run_agent", return_value=result()) as run:
        app = AppTest.from_file(APP).run()
        assert not app.exception
        app.chat_input[0].set_value(QUESTION).run()
        assert not app.exception
        assert run.await_count == 1
        assert len(app.chat_message) == 2
        assert app.status[0].label == "Consulta completada"
        assert any("synthetic-defects-v1" in item.value for item in app.caption)
        assert len(app.button) == 4  # clear + three shortcuts
        app.button(key="followup_2_1").click().run()
        assert not app.exception
        assert run.call_count == 2
        assert run.await_count == 2
        question = run.call_args.args[0]
        assert "registres" in question
        assert all(value in question for value in FILTERS.values())
        assert len(app.chat_message) == 4
        assert len(app.status) == 2
        app.run()
        assert run.call_count == 2  # a rerun must never repeat a model request
        app.button(key="clear_conversation").click().run()
        assert not app.chat_message
        assert len(app.button) == 1


def test_manual_question_removes_previous_suggestions(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    clarification = dict(result(), answer="De quina secció i període?", tool_calls=[])
    with patch("est_prog.capstone_reporting.agent.run_agent", side_effect=[result(), clarification]):
        app = AppTest.from_file(APP).run()
        app.chat_input[0].set_value(QUESTION).run()
        app.chat_input[0].set_value("Vull un resum").run()
        assert not app.exception
        assert len(app.chat_message) == 4
        assert len(app.button) == 1


def test_error_persists_without_repeating_request_or_exposing_details(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    with patch("est_prog.capstone_reporting.agent.run_agent", side_effect=RuntimeError("secret-provider-detail")) as run:
        app = AppTest.from_file(APP).run()
        app.chat_input[0].set_value(QUESTION).run()
        assert not app.exception
        assert len(app.error) == 1
        assert "secret-provider-detail" not in app.error[0].value
        app.run()
        assert len(app.error) == 1
        assert run.call_count == 1


def test_missing_key_disables_requests(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with patch("dotenv.load_dotenv"), patch("est_prog.capstone_reporting.agent.run_agent") as run:
        app = AppTest.from_file(APP).run()
        assert not app.exception
        assert app.chat_input[0].disabled
        assert app.warning
        run.assert_not_called()


def test_streamed_answer_and_live_tools_persist_without_duplicate_run(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    final = result()
    recorded = final["tool_calls"][0]

    async def stream_question(prompt, *, on_event, **kwargs):
        await on_event({"type": "round_start", "round": 1})
        await on_event({"type": "text_delta", "delta": "Consulto les dades…", "round": 1})
        await on_event(dict(type="tool_start", call_id="call_1", name=recorded["name"],
                            arguments=recorded["arguments"]))
        await on_event({"type": "tool_end", "call_id": "call_1", "call": recorded})
        await on_event({"type": "round_start", "round": 2})
        for fragment in ["Dades sintètiques: ", "12 plaques retirades."]:
            await on_event({"type": "text_delta", "delta": fragment, "round": 2})
        await on_event({"type": "completed", "result": final})
        return final

    with patch("est_prog.capstone_reporting.agent.run_agent", side_effect=stream_question) as run:
        app = AppTest.from_file(APP).run()
        app.chat_input[0].set_value(QUESTION).run()
        assert not app.exception
        assert app.status[0].label == "Consulta completada"
        assert sum(item.value == final["answer"] for item in app.markdown) == 1
        assert all("Consulto les dades" not in item.value for item in app.markdown)
        assert len(app.chat_message) == 2
        app.run()
        run.assert_awaited_once()
        assert len(app.status) == 1
        assert any("get_defect_summary" in item.value for item in app.markdown)


def test_interrupted_stream_discards_partial_answer_and_keeps_tool_trace(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    recorded = result()["tool_calls"][0]

    async def interrupted(prompt, *, on_event, **kwargs):
        await on_event({"type": "round_start", "round": 1})
        await on_event(dict(type="tool_start", call_id="call_1", name=recorded["name"],
                            arguments=recorded["arguments"]))
        await on_event({"type": "tool_end", "call_id": "call_1", "call": recorded})
        await on_event({"type": "text_delta", "delta": "Unfinished answer", "round": 1})
        raise ConnectionError("private-provider-detail")

    with patch("est_prog.capstone_reporting.agent.run_agent", side_effect=interrupted) as run:
        app = AppTest.from_file(APP).run()
        app.chat_input[0].set_value(QUESTION).run()
        assert not app.exception
        assert app.status[0].label == "Consulta fallida"
        assert len(app.error) == 1
        assert all("Unfinished answer" not in item.value for item in app.markdown)
        assert "private-provider-detail" not in app.error[0].value
        assert any("get_defect_summary" in item.value for item in app.markdown)
        app.run()
        run.assert_awaited_once()


def test_ui_passes_context_for_short_replies_and_clear_starts_new_conversation(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    histories = []

    async def answer(prompt, *, message_history, **kwargs):
        histories.append(message_history)
        text = "Quina secció?" if len(histories) == 1 else "Comparació de TE."
        return dict(result(), answer=text, tool_calls=[], message_history=[
            *message_history, {"role": "user", "content": prompt},
            {"role": "assistant", "content": text},
        ])

    with patch("est_prog.capstone_reporting.agent.run_agent", side_effect=answer):
        app = AppTest.from_file(APP).run()
        app.chat_input[0].set_value("Compara setembre i octubre de 2026").run()
        app.chat_input[0].set_value("te").run()
        assert not app.exception
        assert histories[0] == []
        assert histories[1] == [
            {"role": "user", "content": "Compara setembre i octubre de 2026"},
            {"role": "assistant", "content": "Quina secció?"},
        ]
        app.button(key="clear_conversation").click().run()
        app.chat_input[0].set_value("Nou resum").run()
        assert histories[2] == []


def test_failed_ui_turn_keeps_question_context_without_partial_tool_calls(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    histories = []

    async def answer(prompt, *, message_history, on_event, **kwargs):
        histories.append(message_history)
        if len(histories) == 1:
            await on_event({"type": "tool_start", "call_id": "unfinished",
                            "name": "get_defect_summary", "arguments": json.dumps(FILTERS)})
            raise ConnectionError("private-error")
        return dict(result(), tool_calls=[])

    with patch("est_prog.capstone_reporting.agent.run_agent", side_effect=answer):
        app = AppTest.from_file(APP).run()
        app.chat_input[0].set_value(QUESTION).run()
        assert not app.exception
        app.chat_input[0].set_value("Torna-ho a provar").run()
        assert not app.exception
        assert histories[1][0] == {"role": "user", "content": QUESTION}
        assert histories[1][1]["role"] == "assistant"
        assert "private-error" not in histories[1][1]["content"]
        assert not any(item.get("type") == "function_call" for item in histories[1])


def test_switching_runtime_clears_incompatible_conversation_history(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'test-key')
    monkeypatch.setenv('REPORTING_AGENT_BACKEND', 'manual')
    with patch('est_prog.capstone_reporting.agent.run_agent', return_value=result()) as run:
        app = AppTest.from_file(APP).run()
        app.chat_input[0].set_value(QUESTION).run()
        assert len(app.chat_message) == 2
        monkeypatch.setenv('REPORTING_AGENT_BACKEND', 'pydanticai')
        app.run()
        assert not app.exception
        assert not app.chat_message
        assert app.session_state.agent_history == []
        run.assert_awaited_once()
