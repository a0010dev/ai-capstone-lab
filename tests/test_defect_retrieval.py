import json
import tempfile
import unittest
from pathlib import Path

from est_prog.capstone_reporting import (
    filter_defects, get_defect_detail, load_defects,
)


class DefectRetrievalTests(unittest.TestCase):
    def setUp(self):
        self.dataset = load_defects()

    def test_load_and_independent_reads(self):
        self.assertEqual(self.dataset['dataset_id'], 'synthetic-defects-v1')
        self.assertEqual(len(self.dataset['controls']), 6)
        self.dataset['controls'][0]['section'] = 'changed'
        self.assertEqual(load_defects()['controls'][0]['section'], 'TE')

    def test_combined_filters_preserve_records_and_inclusive_boundaries(self):
        before = json.dumps(self.dataset)
        records = filter_defects(self.dataset, section='TE',
                                 date_from='2026-09-01', date_to='2026-09-30')
        self.assertEqual([r['control_id'] for r in records],
                         ['DEMO-CTRL-001', 'DEMO-CTRL-002', 'DEMO-CTRL-004'])
        self.assertEqual(records[0]['defects'], [])
        self.assertEqual(len(records[1]['defects']), 2)
        self.assertEqual(json.dumps(self.dataset), before)
        self.assertEqual(get_defect_detail('TE', '2026-09-01',
                                           '2026-09-30')['controls'], records)

    def test_optional_filters_and_empty_selection(self):
        self.assertEqual(filter_defects(self.dataset), self.dataset['controls'])
        self.assertEqual(len(filter_defects(self.dataset, section='TV')), 2)
        self.assertEqual(len(filter_defects(self.dataset,
                                           date_to='2026-08-31')), 1)
        self.assertEqual(len(filter_defects(self.dataset,
                                           date_from='2026-10-01')), 1)
        self.assertEqual(filter_defects(self.dataset, section='te'), [])
        self.assertEqual(filter_defects(self.dataset,
                                        date_from='2027-01-01'), [])

    def test_invalid_filters(self):
        for filters in [dict(section=''), dict(section=2),
                        dict(date_from='2026-9-01'),
                        dict(date_to='2026-02-30'),
                        dict(date_from='2026-10-01', date_to='2026-09-01')]:
            with self.subTest(filters=filters), self.assertRaises(ValueError):
                filter_defects(self.dataset, **filters)

    def test_custom_path_and_bad_input(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'defects.json'
            path.write_text(json.dumps(self.dataset))
            self.assertEqual(load_defects(path), self.dataset)
            path.write_text('{}')
            with self.assertRaises(ValueError):
                load_defects(path)
            path.write_text('invalid json')
            with self.assertRaises(json.JSONDecodeError):
                load_defects(path)
            with self.assertRaises(FileNotFoundError):
                load_defects(Path(directory) / 'missing.json')
