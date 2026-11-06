"""Exercise the alternative runtime with real tools and offline model responses."""
import json
from calendar import monthrange
from copy import deepcopy

import pytest
from pydantic_ai import models
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import RequestUsage

from est_prog.capstone_reporting.agent import run_agent
from est_prog.capstone_reporting.monitoring import configure_monitoring, monitoring_session

FILTERS = dict(section="TE", date_from="2026-09-01", date_to="2026-09-30")
pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(models, 'ALLOW_MODEL_REQUESTS', False)
    configure_monitoring(send_to_logfire=False)


def summary_model():
    def respond(messages, info):
        returns = [p for m in messages for p in m.parts if isinstance(p, ToolReturnPart)]
        if not returns:
            return ModelResponse(parts=[ToolCallPart('get_defect_summary', FILTERS,
                                                     tool_call_id='summary')],
                                 usage=RequestUsage(input_tokens=100, output_tokens=20))
        assert returns[-1].content['totals']['removed_boards'] == 12
        return ModelResponse(parts=[TextPart('Dades sintètiques: 12 plaques retirades. synthetic-defects-v1')],
                             usage=RequestUsage(input_tokens=200, output_tokens=30))
    return FunctionModel(respond, model_name='gpt-4o-mini')


async def test_real_tools_result_history_and_cost_contract():
    result = await run_agent('Resum TE setembre 2026', backend='pydanticai',
                             model=summary_model(), today='2026-10-16')
    assert result['answer'] == 'Dades sintètiques: 12 plaques retirades. synthetic-defects-v1'
    assert result['reference_date'] == '2026-10-16'
    assert len(result['tool_calls']) == 1
    assert json.loads(result['tool_calls'][0]['arguments']) == FILTERS
    assert result['tool_calls'][0]['result']['totals']['removed_boards'] == 12
    assert result['usage']['requests'] == 2
    assert result['usage']['input_tokens'] == 300
    assert result['usage']['output_tokens'] == 50
    assert result['usage']['estimated_cost_usd'] == pytest.approx(.000075)
    assert result['session_usage'] == result['usage']
    json.dumps(result)  # Streamlit stores serializable dictionaries.


async def test_followup_replays_evidence_without_mutating_input_and_groups_costs():
    model = summary_model()
    with monitoring_session('gpt-4o-mini') as costs:
        first = await run_agent('Resum', backend='pydanticai', model=model)
        original = deepcopy(first['message_history'])
        second = await run_agent('I el detall?', backend='pydanticai', model=model,
                                 message_history=first['message_history'])
    assert first['message_history'] == original
    assert len(second['message_history']) > len(original)
    assert first['trace_id'] == second['trace_id']
    assert second['usage']['requests'] == 1
    assert costs.requests == 3
    assert costs.input_tokens == 500


@pytest.mark.parametrize('month,quantity,items', [('09', 12, 3), ('10', 0, 1), ('08', 0, 0)])
async def test_pareto_preserves_zero_rows_null_shares_and_empty_results(month, quantity, items):
    arguments = dict(FILTERS, date_from=f'2026-{month}-01', date_to=f'2026-{month}-{monthrange(2026, int(month))[1]}',
                     metric='removed_boards')
    def respond(messages, info):
        if len(messages) == 1:
            return ModelResponse(parts=[ToolCallPart('get_defect_pareto', arguments)])
        result = next(p.content for p in messages[-1].parts if isinstance(p, ToolReturnPart))
        assert result['total_quantity'] == quantity
        assert len(result['items']) == items
        if items and quantity == 0:
            assert result['items'][0]['percentage'] is None
        return ModelResponse(parts=[TextPart('Dades sintètiques: synthetic-defects-v1')])
    await run_agent('Pareto', backend='pydanticai', model=FunctionModel(respond))


async def test_validation_retries_invalid_metric_before_executing_tool(monkeypatch):
    from est_prog.capstone_reporting import tools
    original = tools.get_defect_pareto
    executed = []
    async def record(**kwargs):
        executed.append(kwargs)
        return await original(**kwargs)
    monkeypatch.setattr(tools, 'get_defect_pareto', record)
    calls = 0
    def respond(messages, info):
        nonlocal calls
        calls += 1
        if calls < 3:
            return ModelResponse(parts=[ToolCallPart('get_defect_pareto',
                dict(FILTERS, metric='invalid' if calls == 1 else 'removed_boards'))])
        return ModelResponse(parts=[TextPart('Recovered synthetic-defects-v1')])
    result = await run_agent('Pareto', backend='pydanticai', model=FunctionModel(respond))
    assert result['answer'] == 'Recovered synthetic-defects-v1'
    assert len(executed) == 1
    assert result['tool_calls'][0]['result']['error'] == 'invalid_arguments'
    assert 'items' in result['tool_calls'][1]['result']
    assert result['usage']['requests'] == 3


async def test_failed_model_call_keeps_known_usage(monkeypatch):
    from logfire.testing import TestExporter
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    exporter = TestExporter()
    configure_monitoring(send_to_logfire=False,
                         additional_span_processors=[SimpleSpanProcessor(exporter)])
    calls = 0
    def respond(messages, info):
        nonlocal calls
        calls += 1
        if calls == 1:
            return ModelResponse(parts=[ToolCallPart('get_defect_summary', FILTERS)],
                                 usage=RequestUsage(input_tokens=100, output_tokens=20))
        raise ConnectionError('offline')
    try:
        with pytest.raises(ConnectionError):
            await run_agent('Summary', backend='pydanticai', model=FunctionModel(respond))
        sessions = [s for s in exporter.exported_spans if s.name == 'reporting_session'
                    and s.attributes.get('logfire.span_type') == 'span']
        assert sessions[-1].attributes['input_tokens'] == 100
        assert sessions[-1].attributes['missing_usage'] == 1
    finally:
        configure_monitoring(send_to_logfire=False)


async def test_request_limit_stops_before_extra_model_call():
    calls = 0
    def respond(messages, info):
        nonlocal calls
        calls += 1
        return ModelResponse(parts=[ToolCallPart('get_defect_summary', FILTERS)])
    with pytest.raises(RuntimeError, match='max_rounds'):
        await run_agent('Summary', backend='pydanticai', model=FunctionModel(respond), max_rounds=1)
    assert calls == 1


@pytest.mark.parametrize('query,kwargs', [('', {}), ('ok', {'max_rounds': 0}),
                                        ('ok', {'message_history': [{}]})])
async def test_invalid_input_fails_before_model_call(query, kwargs):
    def unexpected(messages, info):
        raise AssertionError('Model must not run')
    with pytest.raises(ValueError):
        await run_agent(query, backend='pydanticai', model=FunctionModel(unexpected), **kwargs)


async def test_streaming_executes_complete_arguments_and_resets_provisional_text():
    from pydantic_ai.models.function import DeltaToolCall
    events = []
    async def stream(messages, info):
        if not any(isinstance(p, ToolReturnPart) for m in messages for p in m.parts):
            yield 'Consulto les dades…'
            yield {0: DeltaToolCall(name='get_defect_summary', json_args='{"section":',
                                   tool_call_id='summary')}
            yield {0: DeltaToolCall(json_args='"TE","date_from":"2026-09-01",')}
            yield {0: DeltaToolCall(json_args='"date_to":"2026-09-30"}')}
        else:
            yield 'Dades sintètiques: '
            yield '12 plaques retirades. synthetic-defects-v1'
    async def collect(event):
        if event['type'] == 'tool_start':
            assert json.loads(event['arguments']) == FILTERS
        events.append(event)
    result = await run_agent('Resum', backend='pydanticai',
        model=FunctionModel(stream_function=stream), on_event=collect)
    assert result['answer'] == 'Dades sintètiques: 12 plaques retirades. synthetic-defects-v1'
    assert [e['round'] for e in events if e['type'] == 'round_start'] == [1, 2]
    assert [e['type'] for e in events].count('tool_start') == 1
    assert [e['type'] for e in events].count('tool_end') == 1
    assert events[-1] == {'type': 'completed', 'result': result}
    assert ''.join(e['delta'] for e in events if e['type'] == 'text_delta'
                   and e['round'] == 2) == result['answer']


async def test_ui_failed_turn_messages_are_accepted_after_native_history():
    first = await run_agent('Summary', backend='pydanticai', model=summary_model())
    history = first['message_history'] + [
        {'role': 'user', 'content': 'Follow-up'},
        {'role': 'assistant', 'content': 'No s’ha pogut completar la consulta.'},
    ]
    result = await run_agent('Torna-hi', backend='pydanticai', model=summary_model(),
                             message_history=history)
    assert result['answer'].startswith('Dades sintètiques')


async def test_callback_failure_and_cancellation_never_emit_completed():
    import asyncio
    async def stream(messages, info):
        yield 'Partial'
        yield ' answer'
    for failure in (RuntimeError('consumer failed'), asyncio.CancelledError()):
        events = []
        async def collect(event):
            events.append(event)
            if event['type'] == 'text_delta':
                raise failure
        with pytest.raises(type(failure)):
            await run_agent('Summary', backend='pydanticai',
                model=FunctionModel(stream_function=stream), on_event=collect)
        assert not any(e['type'] == 'completed' for e in events)


async def test_output_validator_recovers_missing_dataset_without_repeating_tools():
    calls = 0
    def respond(messages, info):
        nonlocal calls
        calls += 1
        if calls == 1:
            return ModelResponse(parts=[ToolCallPart('get_defect_summary', FILTERS)])
        text = 'Dades sintètiques: 12' if calls == 2 else 'Dades sintètiques: 12 synthetic-defects-v1'
        return ModelResponse(parts=[TextPart(text)])
    result = await run_agent('Summary', backend='pydanticai', model=FunctionModel(respond))
    assert calls == 3
    assert len(result['tool_calls']) == 1
    assert 'synthetic-defects-v1' in result['answer']


@pytest.mark.parametrize('fails', [False, True])
async def test_owned_client_closes_on_success_and_failure(monkeypatch, fails):
    from unittest.mock import MagicMock
    from est_prog.capstone_reporting import pydantic_agent
    def respond(messages, info):
        if fails:
            raise ConnectionError('offline')
        return ModelResponse(parts=[TextPart('Quina secció?')])
    client = MagicMock()
    client.__aenter__.return_value = client
    monkeypatch.setattr('openai.AsyncOpenAI', MagicMock(return_value=client))
    monkeypatch.setattr(pydantic_agent, 'OpenAIProvider', lambda **kw: object())
    monkeypatch.setattr(pydantic_agent, 'OpenAIResponsesModel',
                        lambda *a, **kw: FunctionModel(respond))
    if fails:
        with pytest.raises(ConnectionError):
            await run_agent('Resum', backend='pydanticai')
    else:
        await run_agent('Resum', backend='pydanticai')
    client.__aexit__.assert_awaited_once()


async def test_native_instrumentation_exports_model_and_tool_spans():
    from logfire.testing import TestExporter
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    exporter = TestExporter()
    configure_monitoring(send_to_logfire=False,
                         additional_span_processors=[SimpleSpanProcessor(exporter)])
    try:
        result = await run_agent('Summary', backend='pydanticai', model=summary_model())
        spans = [s for s in exporter.exported_spans
                 if s.attributes.get('logfire.span_type') != 'pending_span']
        model_spans = [s for s in spans if s.attributes.get('gen_ai.operation.name') == 'chat']
        assert len(model_spans) == 2
        assert any(s.attributes.get('gen_ai.tool.name') == 'get_defect_summary' for s in spans)
        assert len({s.context.trace_id for s in spans}) == 1
        assert f'{spans[0].context.trace_id:032x}' == result['trace_id']
    finally:
        configure_monitoring(send_to_logfire=False)
