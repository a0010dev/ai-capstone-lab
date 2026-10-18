# -*- coding: utf-8 -*-
"""Run with python3 -m est_prog.capstone_reporting from the repo root."""
from __future__ import print_function
import json

from . import get_defect_summary, get_defect_detail, get_defect_pareto


def main():
    filters = dict(section='TE', date_from='2026-09-01', date_to='2026-09-30')
    summary = get_defect_summary(**filters)
    pareto = get_defect_pareto(**filters)
    detail = get_defect_detail(**filters)
    print('SYNTHETIC DATA ONLY - TE, September 2026')
    print(json.dumps(summary, indent=2, sort_keys=True))
    print('\nPareto of removals (share of removals, not a defect rate):')
    print(json.dumps(pareto, indent=2, sort_keys=True))
    print('\nDetail: job | control | date | sample | defect record | code | removed')
    removals = []
    for control in detail['controls']:
        print('%s | %s | %s | sample=%s' % (
            control['job_id'], control['control_id'], control['date'],
            control['sample_quantity']))
        if not control['defects']:
            print('  No defects; contributes to controls and sample.')
        for defect in control['defects']:
            print('  %s | %s | removed=%s' % (
                defect['record_id'], defect['defect_code'], defect['removed_boards']))
            removals.append(defect['removed_boards'])
    print('\nRemoved boards: %s = %s (summary)' % (
        ' + '.join(str(value) for value in removals),
        summary['totals']['removed_boards']))
    assert sum(removals) == summary['totals']['removed_boards']
    assert pareto['total_quantity'] == sum(removals)
    assert sum(row['quantity'] for row in pareto['items']) == sum(removals)


if __name__ == '__main__':
    main()
