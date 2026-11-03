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
    def run(user_prompt):
        result = run_agent(
            user_prompt,
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            today="2026-10-16",
        )
        # Visible with pytest -s, or captured with a failing assertion.
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return result

    return run
