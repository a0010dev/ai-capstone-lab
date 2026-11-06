"""Read collected traces back from Logfire and calculate per-session statistics.

No model calls. Run after collect.py: uv run python submissions/week5-usage-data/verify.py
"""
from collections import Counter
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import re
import statistics
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
from logfire.query_client import LogfireQueryClient

OUT = Path(__file__).resolve().parent


def attributes(row):
    value = row['attributes']
    return json.loads(value) if isinstance(value, str) else value


def main():
    load_dotenv(ROOT / '.env')
    records = json.loads((OUT / 'interactions.json').read_text())
    successful = [r for r in records if r['status'] == 'completed']
    ids = [r['result']['trace_id'] for r in successful]
    if not ids or any(re.fullmatch('[0-9a-f]{32}', value) is None for value in ids):
        raise RuntimeError('Missing or invalid trace IDs')
    if len(set(ids)) != len(ids):
        raise RuntimeError('Queries did not create distinct monitored sessions')
    earliest = min(datetime.fromisoformat(r['started_at_utc']) for r in records)
    quoted = ', '.join("'" + value + "'" for value in ids)
    with LogfireQueryClient(read_token=os.environ['LOGFIRE_READ_TOKEN']) as client:
        remote = client.query_json_rows(
            'SELECT trace_id, span_name, span_id, parent_span_id, start_timestamp, '
            'end_timestamp, level, is_exception, attributes FROM records '
            f"WHERE trace_id IN ({quoted}) AND kind = 'span' ORDER BY start_timestamp",
            min_timestamp=earliest - timedelta(minutes=1), limit=2000,
        )
    rows = remote['rows']
    if len(rows) >= 2000:
        raise RuntimeError('Query limit reached; verification would be incomplete')
    (ROOT / 'tmp/monitoring/week5-usage-remote.json').write_text(
        json.dumps(remote, ensure_ascii=False, indent=2, default=str) + '\n')
    sessions = []
    for record in successful:
        trace_id = record['result']['trace_id']
        spans = [r for r in rows if r['trace_id'] == trace_id]
        roots = [r for r in spans if r['span_name'] == 'reporting_session']
        if len(roots) != 1:
            raise RuntimeError(f"{record['id']}: expected one remote session, got {len(roots)}")
        root = roots[0]
        usage = attributes(root)
        for key, value in record['result']['usage'].items():
            if usage.get(key) != value:
                raise RuntimeError(f"{record['id']}: remote accounting differs for {key}")
        model_spans = [r for r in spans if attributes(r).get('gen_ai.operation.name') == 'chat']
        tool_spans = [r for r in spans if attributes(r).get('gen_ai.operation.name') == 'execute_tool']
        for key in ('input_tokens', 'output_tokens'):
            if sum(attributes(r).get('gen_ai.usage.' + key, 0) for r in model_spans) != usage[key]:
                raise RuntimeError(f"{record['id']}: model token counts differ from session")
        if len(model_spans) != usage['requests']:
            raise RuntimeError('Model request count differs from session usage')
        session = {
            'id': record['id'], 'case': record['case'], 'trace_id': trace_id,
            'input_tokens': usage['input_tokens'], 'output_tokens': usage['output_tokens'],
            'total_tokens': usage['input_tokens'] + usage['output_tokens'],
            'estimated_cost_usd': usage['estimated_cost_usd'],
            'model_requests': len(model_spans), 'tool_calls': len(tool_spans),
            'tools': [c['name'] for c in record['result']['tool_calls']],
            'remote_span_count': len(spans),
            'exception_span_count': sum(bool(r['is_exception']) for r in spans),
            'source_validation_retry_seen': any(
                'Include the source dataset_id in the answer:' in str(attributes(r).get('gen_ai.input.messages', ''))
                for r in model_spans),
        }
        sessions.append(session)
    metrics = ('input_tokens', 'output_tokens', 'total_tokens', 'estimated_cost_usd',
               'model_requests', 'tool_calls')
    summary = {
        'collection_method': 'Automated Streamlit AppTest interactions with real app.py and model; no mocks',
        'session_definition': 'One fresh Streamlit conversation and one reporting_session per query',
        'attempted_queries': len(records), 'completed_sessions': len(sessions),
        'failed_queries': len(records) - len(sessions),
        'unique_queries': len({r['query'] for r in records}),
        'model': os.getenv('OPENAI_MODEL', 'gpt-4o-mini'),
        'dataset': 'synthetic-defects-v1',
        'dashboard_verification': 'Stored traces read back using LogfireQueryClient; no dashboard UI inspection',
        'remote_spans_verified': len(rows),
        'statistics': {key: {
            'sum': sum(s[key] for s in sessions),
            'mean': statistics.mean(s[key] for s in sessions),
            'median': statistics.median(s[key] for s in sessions),
            'min': min(s[key] for s in sessions), 'max': max(s[key] for s in sessions),
        } for key in metrics},
        'tool_frequency': dict(Counter(tool for s in sessions for tool in s['tools'])),
        'sessions': sessions,
    }
    (OUT / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
