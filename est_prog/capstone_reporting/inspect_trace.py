"""Inspect a local or Logfire trace, following the course query-client pattern."""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re

from dotenv import load_dotenv


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace_id")
    parser.add_argument("--trace-file", default="tmp/monitoring/trace.jsonl")
    parser.add_argument("--remote", action="store_true", help="Query Logfire with LOGFIRE_READ_TOKEN")
    args = parser.parse_args()
    if re.fullmatch(r"[0-9a-fA-F]{32}", args.trace_id) is None:
        parser.error("trace_id must contain exactly 32 hexadecimal characters")
    trace_id = args.trace_id.lower()
    if args.remote:
        from logfire.query_client import LogfireQueryClient
        load_dotenv(Path(__file__).resolve().parents[2] / ".env")
        with LogfireQueryClient(read_token=os.environ["LOGFIRE_READ_TOKEN"]) as client:
            # Identifier is validated above before interpolation; no arbitrary SQL.
            result = client.query_json_rows(
                "SELECT start_timestamp, span_name, span_id, parent_span_id, attributes "
                f"FROM records WHERE trace_id = '{trace_id}' AND kind = 'span' "
                "ORDER BY start_timestamp",
                min_timestamp=datetime.now(timezone.utc) - timedelta(days=2),
                limit=1000,
            )
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        spans = [json.loads(line) for line in Path(args.trace_file).read_text().splitlines() if line]
        spans = [span for span in spans
                 if span["context"]["trace_id"].removeprefix("0x").lower() == trace_id]
        spans.sort(key=lambda span: span["start_time"])
        print(json.dumps(spans, ensure_ascii=False, indent=2))
        if not spans:
            parser.exit(1, "No spans found for this trace.\n")


if __name__ == "__main__":
    main()
