import json
import unittest
from types import SimpleNamespace

from est_prog.capstone_reporting.agent import TOOLS, execute_tool, run_agent


FILTERS = dict(section="TE", date_from="2026-09-01", date_to="2026-09-30")


def call(name="get_defect_summary", arguments=None, call_id="call_1"):
    return SimpleNamespace(type="function_call", name=name, call_id=call_id,
                           arguments=json.dumps(FILTERS) if arguments is None else arguments)


def response(output, text="", status="completed"):
    return SimpleNamespace(output=output, output_text=text, status=status)


class FakeClient:
    def __init__(self, responses):
        self.pending = iter(responses)
        self.requests = []
        self.responses = self

    async def create(self, **kwargs):
        self.requests.append(kwargs)
        return next(self.pending)


class ReportingAgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_pareto_dispatch_and_strict_argument_contract(self):
        for metric, total in [('errors', 23), ('affected_boards', 19),
                              ('repaired_boards', 4), ('removed_boards', 12)]:
            result = await execute_tool('get_defect_pareto', json.dumps(dict(FILTERS, metric=metric)))
            self.assertEqual(result['total_quantity'], total)
            self.assertEqual(result['metric'], metric)
        invalid = [FILTERS, dict(FILTERS, metric=None), dict(FILTERS, metric=1),
                   dict(FILTERS, metric=[]), dict(FILTERS, metric='defect_rate'),
                   dict(FILTERS, metric='removed_boards', sql='select 1'),
                   dict(FILTERS, metric='removed_boards', date_to='2026-02-30')]
        for arguments in invalid:
            with self.subTest(arguments=arguments):
                self.assertEqual((await execute_tool('get_defect_pareto', json.dumps(arguments)))['error'],
                                 'invalid_arguments')
        self.assertEqual((await execute_tool('get_defect_summary',
            json.dumps(dict(FILTERS, metric='errors'))))['error'], 'invalid_arguments')

    async def test_pareto_schema_and_output_round_trip(self):
        arguments = dict(FILTERS, metric='removed_boards')
        client = FakeClient([response([call('get_defect_pareto', json.dumps(arguments))]),
                             response([], 'Dades sintètiques: C=8, A=3, B=1')])
        result = await run_agent('Pareto de retirades de TE de setembre de 2026',
                           client=client, today='2026-10-16')
        registered = {tool['name']: tool for tool in client.requests[0]['tools']}
        self.assertEqual(set(registered),
                         {'get_defect_summary', 'get_defect_detail', 'get_defect_pareto'})
        for tool in TOOLS:
            self.assertTrue(tool['strict'])
            self.assertFalse(tool['parameters']['additionalProperties'])
            self.assertEqual(set(tool['parameters']['required']),
                             set(tool['parameters']['properties']))
        self.assertEqual(registered['get_defect_pareto']['parameters']['properties']['metric']['enum'],
                         ['errors', 'affected_boards', 'repaired_boards', 'removed_boards'])
        self.assertEqual(result['tool_calls'][0]['result']['total_quantity'], 12)
        output = client.requests[1]['input'][-1]
        self.assertEqual(output['call_id'], 'call_1')
        self.assertEqual(json.loads(output['output'])['items'][0]['quantity'], 8)

    async def test_real_tools_reconcile_and_keep_healthy_controls(self):
        summary = await execute_tool("get_defect_summary", json.dumps(FILTERS))
        detail = await execute_tool("get_defect_detail", json.dumps(FILTERS))
        self.assertEqual(summary["totals"], dict(control_count=3, sample_quantity=220,
            errors=23, affected_boards=19, repaired_boards=4, removed_boards=12))
        self.assertEqual(detail["controls"][0]["defects"], [])
        self.assertEqual(sum(d["removed_boards"] for c in detail["controls"]
                             for d in c["defects"]), 12)

    async def test_dispatch_rejects_unapproved_tools_and_invalid_arguments(self):
        self.assertEqual((await execute_tool("run_sql", "{}"))['error'], 'unknown_tool')
        for args in ['bad json', '[]', '{}', json.dumps(dict(FILTERS, sql='select 1')),
                     json.dumps(dict(FILTERS, section=1)),
                     json.dumps(dict(FILTERS, date_to='2026-02-30'))]:
            with self.subTest(args=args):
                self.assertEqual((await execute_tool('get_defect_summary', args))['error'],
                                 'invalid_arguments')

    async def test_multiple_calls_and_full_output_round_trip(self):
        reasoning = SimpleNamespace(type="reasoning")
        client = FakeClient([response([reasoning, call(), call('get_defect_detail', call_id='call_2')]),
                             response([], "Synthetic result: 12")])
        result = await run_agent("Explain removals", client=client, today="2026-10-16")
        self.assertEqual(len(result['tool_calls']), 2)
        self.assertEqual(result['answer'], 'Synthetic result: 12')
        request = client.requests[1]
        self.assertIn({"type": "reasoning"}, request['input'])
        outputs = [x for x in request['input'] if isinstance(x, dict)
                   and x.get('type') == 'function_call_output']
        self.assertEqual([x['call_id'] for x in outputs], ['call_1', 'call_2'])
        self.assertEqual(json.loads(outputs[0]['output'])['totals']['removed_boards'], 12)
        self.assertIn("2026-10-16", request['instructions'])
        self.assertFalse(request['store'])

    async def test_error_is_returned_to_model_for_recovery(self):
        client = FakeClient([response([call(arguments='{}')]), response([call()]),
                             response([], 'Recovered')])
        result = await run_agent('Summary', client=client)
        self.assertEqual(result['tool_calls'][0]['result']['error'], 'invalid_arguments')
        self.assertEqual(result['tool_calls'][1]['result']['totals']['control_count'], 3)

    async def test_clarification_needs_no_tool(self):
        client = FakeClient([response([], 'Which section and period?')])
        self.assertEqual((await run_agent('Summary', client=client))['tool_calls'], [])

    async def test_loop_limit_and_incomplete_responses_fail_explicitly(self):
        with self.assertRaisesRegex(RuntimeError, 'max_rounds'):
            await run_agent('Summary', client=FakeClient([response([call()])]), max_rounds=1)
        with self.assertRaisesRegex(RuntimeError, 'did not complete'):
            await run_agent('Summary', client=FakeClient([response([], status='incomplete')]))
        with self.assertRaisesRegex(RuntimeError, 'neither'):
            await run_agent('Summary', client=FakeClient([response([])]))


if __name__ == '__main__':
    unittest.main()
