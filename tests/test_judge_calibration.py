"""Real judge, fixed answers, human labels; never calls the reporting agent."""
import copy
import json
from pathlib import Path

import pytest

from tests.judge import evaluate_criteria
from tests.judge_criteria import ZERO_REMOVAL_CRITERIA


pytestmark = [pytest.mark.integration, pytest.mark.judge_calibration, pytest.mark.asyncio]
EXAMPLES = json.loads(
    (Path(__file__).parent / "fixtures" / "judge_zero_removals.json").read_text()
)


@pytest.mark.parametrize("repeat", [1, 2], ids=["run-1", "run-2"])
@pytest.mark.parametrize("case", EXAMPLES["cases"], ids=lambda case: case["id"])
async def test_judge_agrees_with_fixed_labels(api_access, case, repeat):
    calls = copy.deepcopy(EXAMPLES["tool_calls"])
    if "arguments" in case:
        calls[0]["arguments"] = json.dumps(case["arguments"])
        calls[0]["result"]["filters"] = {
            key: value for key, value in case["arguments"].items() if key != "metric"
        }
    result = {"answer": case["answer"], "tool_calls": calls}
    print(f"Fixed example: {case['id']}; repetition: {repeat}")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    # Expected labels are deliberately NOT sent to the judge.
    feedback = await evaluate_criteria(result, ZERO_REMOVAL_CRITERIA)
    observed = [criterion.passed for criterion in feedback.criteria]
    print(f"Human labels: {case['expected']}; judge labels: {observed}")
    assert observed == case["expected"], feedback.model_dump_json(indent=2)
