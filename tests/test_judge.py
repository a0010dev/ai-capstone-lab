"""LLM evaluation of the week 3 zero-removal interpretation regression."""
import pytest

from tests.judge import assert_criteria
from tests.judge_criteria import ZERO_REMOVAL_CRITERIA


pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_zero_removals_with_existing_records_judge(agent):
    result = await agent("Fes un Pareto de retirades de TE durant octubre de 2026.")

    await assert_criteria(result, criteria=ZERO_REMOVAL_CRITERIA)
