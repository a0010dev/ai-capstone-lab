"""Real-agent fixture, following the course's module-scoped agent pattern."""
import json
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

from est_prog.capstone_reporting.agent import run_agent


@pytest.fixture(scope="session")
def api_access():
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY is required for real-agent integration tests")


@pytest.fixture(scope="module")
def agent(api_access):
    async def run(user_prompt, *, on_event=None, message_history=None, today="2026-10-16"):
        result = await run_agent(
            user_prompt,
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            today=today,
            on_event=on_event,
            message_history=message_history,
        )
        # Visible with pytest -s, or captured with a failing assertion.
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return result

    return run
