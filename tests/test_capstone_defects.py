# -*- coding: utf-8 -*-
import json
import unittest

from est_prog.capstone_reporting import (
    get_defect_summary, get_defect_detail, get_defect_pareto)


class CapstoneDefectsTest(unittest.TestCase):
    def check_reconciliation(self, filters, expected):
        summary = get_defect_summary(**filters)
        detail = get_defect_detail(**filters)
        self.assertEqual(summary['filters'], detail['filters'])
        self.assertEqual(summary['source'], detail['source'])
        controls = detail['controls']
        observed = [len(controls), sum(row['sample_quantity'] for row in controls)]
        metrics = ('errors', 'affected_boards', 'repaired_boards', 'removed_boards')
        observed.extend(sum(row[metric] for control in controls
                            for row in control['defects']) for metric in metrics)
        self.assertEqual(observed, expected)
        self.assertEqual(summary['totals'], dict(zip(
            ('control_count', 'sample_quantity') + metrics, expected)))
        self.assertNotIn('defect_rate', summary['totals'])
        json.dumps(summary)
        json.dumps(detail)
        for metric in metrics:
            pareto = get_defect_pareto(metric=metric, **filters)
            self.assertEqual(pareto['filters'], summary['filters'])
            self.assertEqual(pareto['source'], summary['source'])
            self.assertEqual(pareto['metric'], metric)
            self.assertEqual(pareto['schema_version'], summary['schema_version'])
            self.assertEqual(pareto['metric_semantics']['percentage_basis'],
                             'share_of_selected_metric_not_defect_rate')
            self.assertEqual(pareto['items'], sorted(pareto['items'],
                key=lambda row: (-row['quantity'], row['defect_code'])))
            self.assertEqual(pareto['total_quantity'], summary['totals'][metric])
            self.assertEqual(sum(row['quantity'] for row in pareto['items']),
                             summary['totals'][metric])
            originals = dict(((c['job_id'], c['control_id'], d['record_id']), d)
                             for c in controls for d in c['defects'])
            seen = []
            cumulative = 0
            for item in pareto['items']:
                self.assertEqual(item['records'], sorted(item['records'], key=lambda ref:
                    (ref['job_id'], ref['control_id'], ref['record_id'])))
                self.assertEqual(item['quantity'], sum(
                    ref['quantity'] for ref in item['records']))
                for ref in item['records']:
                    key = (ref['job_id'], ref['control_id'], ref['record_id'])
                    self.assertEqual(originals[key]['defect_code'], item['defect_code'])
                    self.assertEqual(originals[key][metric], ref['quantity'])
                    seen.append(key)
                cumulative += item['quantity']
                if pareto['total_quantity']:
                    self.assertAlmostEqual(item['percentage'],
                        100.0 * item['quantity'] / pareto['total_quantity'])
                    self.assertAlmostEqual(item['cumulative_percentage'],
                        100.0 * cumulative / pareto['total_quantity'])
                else:
                    self.assertIsNone(item['percentage'])
                    self.assertIsNone(item['cumulative_percentage'])
            self.assertEqual(sorted(seen), sorted(originals))
            json.dumps(pareto, allow_nan=False)

    def test_all_data(self):
        self.check_reconciliation({}, [258, 33197, 4604, 3555, 2046, 560])

    def test_one_section(self):
        self.check_reconciliation({'section': 'TE'}, [130, 16679, 2340, 1807, 1032, 287])

    def test_date_range(self):
        self.check_reconciliation(dict(date_from='2026-09-01', date_to='2026-09-30'),
                                  [4, 280, 30, 26, 4, 17])

    def test_demo_filters_and_boundaries(self):
        filters = dict(section='TE', date_from='2026-09-01', date_to='2026-09-30')
        self.check_reconciliation(filters, [3, 220, 23, 19, 4, 12])
        self.assertEqual([r['control_id'] for r in get_defect_detail(**filters)['controls']],
                         ['DEMO-CTRL-001', 'DEMO-CTRL-002', 'DEMO-CTRL-004'])

    def test_healthy_control(self):
        self.check_reconciliation(dict(date_from='2026-09-01', date_to='2026-09-01'),
                                  [1, 100, 0, 0, 0, 0])
        self.assertEqual(get_defect_detail(date_to='2026-09-01')['controls'][0]['defects'], [])

    def test_empty_selection(self):
        self.check_reconciliation({'section': 'DEMO-UNKNOWN'}, [0, 0, 0, 0, 0, 0])
        self.check_reconciliation({'date_from': '2027-01-01'}, [0, 0, 0, 0, 0, 0])

    def test_open_date_boundaries(self):
        self.check_reconciliation({'date_from': '2026-10-01'}, [5, 516, 59, 46, 29, 4])
        self.check_reconciliation({'date_to': '2026-08-31'}, [249, 32401, 4515, 3483, 2013, 539])

    def test_invalid_filters(self):
        bad_filters = [dict(section=2), dict(section=''), dict(date_from='2026-9-01'),
                       dict(date_to='2026-02-30'), dict(date_from=20260901),
                       dict(date_from='2026-10-01', date_to='2026-09-01')]
        for tool in (get_defect_summary, get_defect_detail, get_defect_pareto):
            for filters in bad_filters:
                with self.assertRaises(ValueError):
                    tool(**filters)

    def test_determinism_and_isolation(self):
        original = get_defect_detail()
        changed = get_defect_detail()
        changed['controls'][1]['defects'][0]['removed_boards'] = 999
        self.assertEqual(original, get_defect_detail())
        self.assertEqual(get_defect_summary(), get_defect_summary())
        self.assertEqual(get_defect_summary()['totals']['removed_boards'], 560)

    def test_fixture_identifiers_and_relationships(self):
        controls = get_defect_detail()['controls']
        self.assertEqual(len(set(row['control_id'] for row in controls)), len(controls))
        record_ids = [row['record_id'] for c in controls for row in c['defects']]
        self.assertEqual(len(set(record_ids)), len(record_ids))
        for control in controls:
            self.assertTrue(control['job_id'].startswith('DEMO-JOB-'))
            self.assertTrue(control['control_id'].startswith('DEMO-CTRL-'))
            self.assertTrue(control['operation'].startswith('DEMO-'))
            self.assertGreater(control['sample_quantity'], 0)
            for defect in control['defects']:
                self.assertTrue(defect['record_id'].startswith('DEMO-DEF-'))
                self.assertTrue(defect['defect_code'].startswith('DEMO-CODE-'))
                for metric in ('errors', 'affected_boards', 'repaired_boards', 'removed_boards'):
                    self.assertIsInstance(defect[metric], int)
                    self.assertGreaterEqual(defect[metric], 0)
                self.assertLessEqual(defect['affected_boards'], control['sample_quantity'])
                self.assertGreaterEqual(defect['errors'], defect['affected_boards'])
                self.assertLessEqual(defect['repaired_boards'] + defect['removed_boards'],
                                     defect['affected_boards'])

    def test_pareto_demo_ranking_and_percentages(self):
        pareto = get_defect_pareto(section='TE', date_from='2026-09-01',
                                   date_to='2026-09-30')
        self.assertEqual(pareto['metric'], 'removed_boards')
        self.assertEqual(pareto['total_quantity'], 12)
        self.assertEqual([row['defect_code'] for row in pareto['items']],
                         ['DEMO-CODE-C', 'DEMO-CODE-A', 'DEMO-CODE-B'])
        self.assertEqual([row['quantity'] for row in pareto['items']], [8, 3, 1])
        self.assertAlmostEqual(pareto['items'][0]['percentage'], 200.0 / 3)
        self.assertAlmostEqual(pareto['items'][1]['cumulative_percentage'], 275.0 / 3)
        self.assertEqual(pareto['items'][-1]['cumulative_percentage'], 100.0)
        self.assertEqual(pareto['items'][0]['records'], [{
            'job_id': 'DEMO-JOB-C', 'control_id': 'DEMO-CTRL-004',
            'record_id': 'DEMO-DEF-004', 'quantity': 8}])

    def test_pareto_ties_and_multiple_records(self):
        items = get_defect_pareto(date_from='2026-08-01', date_to='2026-10-31')['items']
        self.assertEqual([row['defect_code'] for row in items],
                         ['DEMO-CODE-A', 'DEMO-CODE-C', 'DEMO-CODE-B'])
        self.assertEqual([row['quantity'] for row in items], [8, 8, 1])
        self.assertEqual(len(items[0]['records']), 2)

    def test_pareto_zero_and_empty(self):
        pareto = get_defect_pareto(date_from='2026-10-01', date_to='2026-10-31')
        self.assertEqual(pareto['total_quantity'], 0)
        self.assertEqual(len(pareto['items']), 1)
        self.assertEqual(pareto['items'][0]['quantity'], 0)
        self.assertEqual(pareto['items'][0]['records'][0]['record_id'], 'DEMO-DEF-006')
        self.assertIsNone(pareto['items'][0]['percentage'])
        self.assertIsNone(pareto['items'][0]['cumulative_percentage'])
        self.assertEqual(get_defect_pareto(section='DEMO-UNKNOWN')['items'], [])
        self.assertEqual(get_defect_pareto(date_from='2026-09-01',
                                         date_to='2026-09-01')['items'], [])

    def test_pareto_invalid_metric(self):
        for metric in ('sample_quantity', 'control_count', 'defect_rate', '',
                       'REMOVED_BOARDS', None, 1, [], {}):
            with self.assertRaises(ValueError):
                get_defect_pareto(metric=metric)

    def test_pareto_determinism_and_isolation(self):
        original = get_defect_pareto()
        changed = get_defect_pareto()
        changed['items'][0]['records'][0]['quantity'] = 999
        changed['items'][0]['quantity'] = 999
        self.assertEqual(original, get_defect_pareto())
        self.assertEqual(get_defect_summary()['totals']['removed_boards'], 560)


if __name__ == '__main__':
    unittest.main()
