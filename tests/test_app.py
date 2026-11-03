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
        assert len(app.chat_message) == 2
        assert app.status[0].label == "Consulta completada"
        assert any("synthetic-defects-v1" in item.value for item in app.caption)
        assert len(app.button) == 4  # clear + three shortcuts
        app.button(key="followup_2_1").click().run()
        assert not app.exception
        assert run.call_count == 2
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
