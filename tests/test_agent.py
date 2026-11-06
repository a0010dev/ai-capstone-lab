"""Week 4 behavioral tests: real query, tool trace, and response assertions.

These tests intentionally use the model rather than scripted FakeClient answers.
Run: uv run pytest tests/test_agent.py -v -s
Each case starts an independent conversation and makes paid API calls.
"""
import json
import re
import unicodedata

import pytest


pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

SEPTEMBER = dict(section="TE", date_from="2026-09-01", date_to="2026-09-30")
OCTOBER = dict(section="TE", date_from="2026-10-01", date_to="2026-10-31")
AUGUST = dict(section="TE", date_from="2026-08-01", date_to="2026-08-31")
FIRST_DAY = dict(section="TE", date_from="2026-09-01", date_to="2026-09-01")


def plain(answer):
    """Ignore accents and Markdown emphasis, without changing response meaning."""
    text = unicodedata.normalize("NFKD", answer.casefold())
    return "".join(c for c in text if not unicodedata.combining(c)).replace("*", "").replace("`", "")


def calls_for(result, name, filters, **extra):
    calls = [call for call in result["tool_calls"] if call["name"] == name]
    assert calls, f"Missing {name}: {result['tool_calls']}"
    for call in calls:
        assert json.loads(call["arguments"]) == dict(filters, **extra)
        assert "error" not in call["result"], call["result"]
    return calls


def data_answer(result):
    answer = plain(result["answer"])
    assert answer.lstrip().startswith("dades sintetiques")
    assert re.search(r"\bte\b", answer)
    return answer


def assert_no_missing_records_claim(answer):
    # Catch the historical wording and common paraphrases of the same error.
    assert not re.search(
        r"sense registres|no (?:hi ha|hi havia|existeixen|s'han trobat|s'han retornat) "
        r"(?:cap |registres)|cap registre", answer
    ), answer


async def test_summary_reports_removed_boards(agent):
    result = await agent("Quantes plaques hem retirat a TE durant setembre de 2026?")
    calls_for(result, "get_defect_summary", SEPTEMBER)
    assert [c["name"] for c in result["tool_calls"]] == ["get_defect_summary"]
    answer = data_answer(result)
    assert re.search(
        r"\b12\s+plaques\s+retirades\b|retir(?:ades|at)[^\d\n]*\b12\b", answer
    ), answer
    assert "synthetic-defects-v1" in answer
    assert "%" not in answer


async def test_pareto_uses_removals_and_descending_order(agent):
    result = await agent("Quins defectes han provocat mes retirades a TE durant setembre de 2026?")
    calls_for(result, "get_defect_pareto", SEPTEMBER, metric="removed_boards")
    answer = data_answer(result)
    for code, quantity in [("c", 8), ("a", 3), ("b", 1)]:
        assert re.search(rf"demo-code-{code}(?:(?!demo-code-)[\s\S])*?\b{quantity}\b", answer), answer
    assert answer.index("demo-code-c") < answer.index("demo-code-a") < answer.index("demo-code-b")


async def test_removal_explanation_includes_source_identifiers(agent):
    result = await agent(
        "Mostra'm el total i els controls i les fitxes que expliquen les retirades "
        "a TE durant setembre de 2026."
    )
    calls_for(result, "get_defect_summary", SEPTEMBER)
    calls_for(result, "get_defect_detail", SEPTEMBER)
    answer = data_answer(result)
    for identifier in ["demo-job-b", "demo-job-c", "demo-ctrl-002", "demo-ctrl-004",
                       "demo-def-001", "demo-def-002", "demo-def-004"]:
        assert identifier in answer
    assert re.search(r"\b12\b", answer)


async def test_pareto_honors_explicit_errors_metric(agent):
    result = await agent("Fes un Pareto pel nombre d'errors de TE durant setembre de 2026.")
    calls_for(result, "get_defect_pareto", SEPTEMBER, metric="errors")
    answer = data_answer(result)
    for code, quantity in [("c", 10), ("a", 8), ("b", 5)]:
        assert re.search(rf"demo-code-{code}(?:(?!demo-code-)[\s\S])*?\b{quantity}\b", answer), answer


async def test_comparison_queries_both_periods(agent):
    result = await agent("Compara les plaques retirades de TE entre setembre i octubre de 2026.")
    calls = [c for c in result["tool_calls"] if c["name"] == "get_defect_summary"]
    assert len(calls) == 2
    assert sorted(json.loads(c["arguments"])["date_from"] for c in calls) == ["2026-09-01", "2026-10-01"]
    for call in calls:
        args = json.loads(call["arguments"])
        assert args == (SEPTEMBER if args["date_from"] == "2026-09-01" else OCTOBER)
        assert "error" not in call["result"]
    answer = data_answer(result)
    assert re.search(r"setembre(?:(?!octubre)[\s\S])*?\b12\b", answer), answer
    assert re.search(r"octubre(?:(?!setembre)[\s\S])*?\b0\b", answer), answer
    assert_no_missing_records_claim(answer)


async def test_summary_uses_inclusive_boundaries(agent):
    result = await agent(
        "Mostra el nombre de controls, la mostra i les plaques retirades de TE "
        "entre l'1 i el 30 de setembre de 2026, inclosos."
    )
    summary = calls_for(result, "get_defect_summary", SEPTEMBER)[0]["result"]
    assert summary["totals"]["control_count"] == 3
    assert summary["totals"]["sample_quantity"] == 220
    answer = data_answer(result)
    for quantity in (3, 220, 12):
        assert re.search(rf"\b{quantity}\b", answer), answer


@pytest.mark.parametrize("query,required,not_missing", [
    ("Fes-me un resum dels defectes.", ("seccio", "periode"), ()),
    ("Fes-me un resum dels defectes de TE.", ("periode",), ("seccio",)),
    ("Fes-me un resum dels defectes de setembre de 2026.", ("seccio",), ("periode",)),
], ids=["missing-both", "missing-period", "missing-section"])
async def test_clarification_asks_only_for_missing_filters(agent, query, required, not_missing):
    result = await agent(query)
    assert result["tool_calls"] == []
    answer = plain(result["answer"])
    assert re.search(r"\?|indiqu|indica|especific|necessito|cal que", answer), answer
    for concept in required:
        alternatives = r"periode|dates|mes|interval" if concept == "periode" else "seccio"
        assert re.search(alternatives, answer), answer
    for concept in not_missing:
        # Check questions rather than rejecting a mention of known context.
        assert not re.search(rf"(?:quina?|quines|quin)\s+{concept}", answer), answer


async def test_empty_pareto_without_controls_reports_unknown_coverage(agent):
    result = await agent("Fes un Pareto de retirades de TE durant agost de 2026.")
    pareto = calls_for(result, "get_defect_pareto", AUGUST, metric="removed_boards")[0]["result"]
    summary = calls_for(result, "get_defect_summary", AUGUST)[0]["result"]
    assert pareto["items"] == []
    assert summary["totals"]["control_count"] == 0
    answer = data_answer(result)
    assert re.search(r"sense registres coincidents|no hi (?:ha|havia) registres coincidents", answer)
    assert "cobertura desconeguda" in answer


async def test_empty_pareto_with_healthy_control_is_not_missing_data(agent):
    result = await agent("Fes un Pareto de retirades de TE del dia 1 de setembre de 2026.")
    pareto = calls_for(result, "get_defect_pareto", FIRST_DAY, metric="removed_boards")[0]["result"]
    summary = calls_for(result, "get_defect_summary", FIRST_DAY)[0]["result"]
    assert pareto["items"] == []
    assert summary["totals"]["control_count"] == 1
    answer = data_answer(result)
    assert re.search(r"\b(?:1|un)\s+control\b|controls?[^\n\d]*\b1\b", answer), answer
    # No defect rows is correct here; the control itself must not be denied.
    assert "cobertura desconeguda" not in answer
    assert not re.search(r"sense controls|no (?:hi ha|existeixen) (?:cap )?controls?", answer), answer


async def test_zero_removals_with_existing_defect_is_not_missing_data(agent):
    """Regression: the week 3 agent called a nonempty zero Pareto 'no records'."""
    result = await agent("Fes un Pareto de retirades de TE durant octubre de 2026.")
    pareto = calls_for(result, "get_defect_pareto", OCTOBER, metric="removed_boards")[0]["result"]
    assert pareto["total_quantity"] == 0
    assert len(pareto["items"]) == 1
    item = pareto["items"][0]
    assert item["defect_code"] == "DEMO-CODE-C"
    assert item["quantity"] == 0
    assert item["percentage"] is None
    assert item["cumulative_percentage"] is None
    answer = data_answer(result)
    assert_no_missing_records_claim(answer)
    assert re.search(r"demo-code-c(?:(?!demo-code-)[\s\S])*?\b0\b", answer), answer
    assert not re.search(r"(?<![\d.,])0\s*%", answer), answer
    if "percentatge" in answer:
        assert re.search(r"no defin|indefin|no aplic|n/[ad]\b|nul|total (?:es |de )?zero|total (?:es |de )?0", answer), answer


async def test_unvalidated_defect_rate_is_not_calculated(agent):
    result = await agent("Quina es la taxa de defectuositat de TE durant setembre de 2026?")
    for call in result["tool_calls"]:
        assert call["name"] == "get_defect_summary"
        assert json.loads(call["arguments"]) == SEPTEMBER
    answer = plain(result["answer"])
    assert "taxa" in answer
    assert re.search(r"definicio|denominador|valid|eina", answer), answer
    assert re.search(r"no (?:puc|es pot|dispos|tenim|hi ha)|sense", answer), answer
    assert not re.search(r"\d+(?:[.,]\d+)?\s*(?:%|per cent)", answer), answer


async def test_comparison_without_records_does_not_claim_improvement(agent):
    result = await agent("Han disminuit les retirades a TE entre setembre de 2026 i gener de 2027?")
    january = dict(section="TE", date_from="2027-01-01", date_to="2027-01-31")
    calls = [c for c in result["tool_calls"] if c["name"] == "get_defect_summary"]
    assert len(calls) == 2
    assert {json.dumps(json.loads(c["arguments"]), sort_keys=True) for c in calls} == {
        json.dumps(SEPTEMBER, sort_keys=True), json.dumps(january, sort_keys=True)
    }
    answer = data_answer(result)
    assert "sense registres coincidents" in answer
    assert "cobertura desconeguda" in answer
    assert re.search(r"no (?:es pot|podem|puc)|no .*concl|no .*determ", answer), answer
    assert not re.search(r"100\s*%", answer), answer
