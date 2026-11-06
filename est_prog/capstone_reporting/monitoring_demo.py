"""Run one real, monitored query: python -m est_prog.capstone_reporting.monitoring_demo."""
import argparse
import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import logfire
from dotenv import load_dotenv

from .agent import run_agent
from .monitoring import configure_monitoring


async def demo(args):
    async def on_event(event):
        # Enable the same streaming path used by Streamlit, without printing fragments.
        pass

    return await run_agent(
        args.query, model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        today=datetime.now(ZoneInfo("Europe/Madrid")).date().isoformat(),
        on_event=on_event if args.stream else None,
    )


def main():
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", default=(
        "Quantes plaques retirades consten a TE entre el 2026-09-01 i el 2026-09-30?"
    ))
    parser.add_argument("--trace-file", default="tmp/monitoring/trace.jsonl")
    parser.add_argument("--stream", action="store_true")
    args = parser.parse_args()
    configure_monitoring(trace_file=args.trace_file)
    try:
        result = asyncio.run(demo(args))
        print(json.dumps({key: value for key, value in result.items()
                          if key != "message_history"}, ensure_ascii=False, indent=2))
        print("Local spans: " + args.trace_file)
        if not os.getenv("LOGFIRE_TOKEN"):
            print("LOGFIRE_TOKEN is absent: this run was verified locally; no dashboard export is configured.")
    finally:
        logfire.force_flush()


if __name__ == "__main__":
    main()
