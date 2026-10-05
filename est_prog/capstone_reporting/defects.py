# -*- coding: utf-8 -*-
"""Fixture-only arithmetic, not validated ERP business rules."""
import json
import os
import re
from datetime import datetime

try:
    _STRING_TYPES = (basestring,)
except NameError:
    _STRING_TYPES = (str,)

_DATA_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                        '..', '..', 'data',
                                        'synthetic_defects.json'))
_DEFECT_METRICS = ('errors', 'affected_boards', 'repaired_boards',
                   'removed_boards')


def _validate_date(value, name):
    if value is None:
        return
    if not isinstance(value, _STRING_TYPES) or not re.match(
            r'^\d{4}-\d{2}-\d{2}\Z', value):
        raise ValueError('%s must be an ISO date YYYY-MM-DD' % name)
    try:
        datetime.strptime(value, '%Y-%m-%d')
    except ValueError:
        raise ValueError('%s must be a valid calendar date' % name)


def load_defects(path=None):
    """Load the synthetic JSON dataset; default path is independent of cwd.

    Return a dict with dataset_id and controls (including nested defect rows).
    Each call reads fresh objects. File and JSON errors propagate to the caller.
    """
    with open(_DATA_PATH if path is None else path, 'r') as stream:
        dataset = json.load(stream)
    if not isinstance(dataset, dict) or not isinstance(
            dataset.get('dataset_id'), _STRING_TYPES) or not isinstance(
            dataset.get('controls'), list):
        raise ValueError('dataset must contain dataset_id and a controls list')
    for row in dataset['controls']:
        if not isinstance(row, dict) or not isinstance(
                row.get('section'), _STRING_TYPES) or not isinstance(
                row.get('defects'), list) or row.get('date') is None:
            raise ValueError('each control must contain section, date and defects')
        _validate_date(row['date'], 'control date')
    return dataset


def filter_defects(dataset, section=None, date_from=None, date_to=None):
    """Return matching controls in source order, using AND and inclusive dates.

    Preserve nested defect rows and controls without defects. Does not mutate
    the dataset; returned controls reference the loaded records.
    """
    if section is not None and (
            not isinstance(section, _STRING_TYPES) or not section.strip()):
        raise ValueError('section must be a non-empty string or None')
    _validate_date(date_from, 'date_from')
    _validate_date(date_to, 'date_to')
    if date_from is not None and date_to is not None and date_from > date_to:
        raise ValueError('date_from must not be after date_to')
    return [row for row in dataset['controls']
                if (section is None or row['section'] == section)
                and (date_from is None or row['date'] >= date_from)
                and (date_to is None or row['date'] <= date_to)]


def _select_controls(section, date_from, date_to):
    dataset = load_defects()
    controls = filter_defects(dataset, section, date_from, date_to)
    return dataset['dataset_id'], controls


def _response(dataset_id, section, date_from, date_to):
    return {
        'schema_version': 1,
        'source': {'kind': 'synthetic', 'dataset_id': dataset_id},
        'filters': {'section': section, 'date_from': date_from,
                    'date_to': date_to},
        'metric_semantics': {
            'status': 'prototype_only_not_validated_erp_rules',
            'date_basis': 'synthetic_control_date_inclusive',
            'sample_quantity': 'sum_once_per_control_not_unique_boards',
            'board_counts': 'sum_of_recorded_occurrences_not_unique_boards',
        },
    }


def get_defect_detail(section=None, date_from=None, date_to=None):
    """Return controls (including healthy ones) and their original defect rows."""
    dataset_id, controls = _select_controls(section, date_from, date_to)
    result = _response(dataset_id, section, date_from, date_to)
    result['controls'] = controls
    return result


def get_defect_summary(section=None, date_from=None, date_to=None):
    """Sum fixture quantities separately; no ratios or inferred ERP rules."""
    dataset_id, controls = _select_controls(section, date_from, date_to)
    totals = dict((metric, 0) for metric in _DEFECT_METRICS)
    totals['control_count'] = len(controls)
    totals['sample_quantity'] = sum(row['sample_quantity'] for row in controls)
    for control in controls:
        for defect in control['defects']:
            for metric in _DEFECT_METRICS:
                totals[metric] += defect[metric]
    result = _response(dataset_id, section, date_from, date_to)
    result['totals'] = totals
    return result
