"""Collect real interactions through Streamlit AppTest (no fake model or UI runner).

Run from the repository root: uv run python submissions/week5-usage-data/collect.py
Existing query IDs are skipped to avoid duplicate paid calls on resumption.
Each query opens a fresh Streamlit conversation and creates one monitored session.
"""
import json
import os
from pathlib import Path
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import logfire
from dotenv import load_dotenv
from streamlit.testing.v1 import AppTest
from est_prog.capstone_reporting.monitoring import configure_monitoring

OUT = Path(__file__).resolve().parent


def main():
    load_dotenv(ROOT / '.env')
    for key in ('OPENAI_API_KEY', 'LOGFIRE_TOKEN', 'LOGFIRE_READ_TOKEN'):
        if not os.getenv(key):
            raise RuntimeError(f'{key} is required')
    queries = json.loads((OUT / 'queries.json').read_text())
    path = OUT / 'interactions.json'
    records = json.loads(path.read_text()) if path.exists() else []
    prior = {record['id']: record for record in records}
    trace_file = ROOT / 'tmp/monitoring/week5-usage-data.jsonl'
    configure_monitoring(trace_file=trace_file)
    try:
        for item in queries:
            if item['id'] in prior:
                if prior[item['id']]['query'] != item['query']:
                    raise RuntimeError('Query changed after collection; use a new ID')
                continue
            started = datetime.now(timezone.utc).isoformat()
            print(f"Starting {item['id']}: {item['case']}", flush=True)
            app = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=180).run()
            if app.exception or app.chat_input[0].disabled:
                raise RuntimeError('App did not initialize successfully')
            app.chat_input[0].set_value(item['query']).run(timeout=180)
            messages = app.session_state['messages']
            last = messages[-1] if messages else {}
            result = last.get('result')
            record = {
                **item, 'started_at_utc': started,
                'completed_at_utc': datetime.now(timezone.utc).isoformat(),
                'collection_method': 'Streamlit AppTest driving real app.py; real model; no mocks',
                'fresh_conversation': True,
                'ui_exception_count': len(app.exception),
                'ui_error_count': len(app.error),
                'status': 'completed' if result else 'failed',
                'answer': last.get('content'),
                'result': result,
            }
            records.append(record)
            path.write_text(json.dumps(records, ensure_ascii=False, indent=2) + '\n')
            logfire.force_flush()
            print(json.dumps({
                'id': item['id'], 'status': record['status'],
                'trace_id': result.get('trace_id') if result else None,
                'usage': result.get('usage') if result else None,
                'tools': [c['name'] for c in result['tool_calls']] if result else [],
            }), flush=True)
            if app.exception:
                raise RuntimeError('App raised an exception; saved available evidence')
    finally:
        logfire.force_flush()


if __name__ == '__main__':
    main()
