# Capstone progress: a testable reporting project with a browser interface

Week 4 update — 3 November 2026

## What I started

I am building a read-only industrial reporting agent for quality, production
and other company staff who need information about manufacturing defects
without asking IT to prepare a report. The prototype uses synthetic data and
three deterministic tools: `get_defect_summary`, `get_defect_detail` and
`get_defect_pareto`.

Last week, I found that correct tool calls and calculations did not always
produce a correct final answer. This week, I turned those observations into
tests, following the course's reference project with help from my coding
assistant. My main goal was to test how the agent interprets tool results,
especially the difference between zero removals and missing records.

## Project structure and browser interface

I also applied the week's lessons on Python project structure and the optional
Streamlit frontend. The reporting backend was already extracted into modules
in week 3. This week, I checked that the same modules could be used by tests
and the UI without executing notebook cells or duplicating the reporting logic.

| Responsibility from the course | Implementation in my project |
|---|---|
| Data access and tools | [defects.py](est_prog/capstone_reporting/defects.py) |
| Agent configuration and execution | [agent.py](est_prog/capstone_reporting/agent.py) |
| Terminal demonstration | [__main__.py](est_prog/capstone_reporting/__main__.py), run with `python -m est_prog.capstone_reporting` |
| Browser entry point | [app.py](app.py), run with `uv run streamlit run app.py` |
| Dependencies and tests | `pyproject.toml`, `uv.lock` and `tests/` |

This follows the lesson's separation of responsibilities with names suited to
my existing package. The terminal entry point demonstrates the deterministic
tools without an API call; the Streamlit app runs the conversational agent.
The notebooks remain demonstrations rather than runtime dependencies. I added
an [.env.example](.env.example) to make the README's setup instructions usable
and checked that local secrets, environments and caches are ignored by Git.

The Catalan Streamlit app wraps the existing agent. It keeps session chat
history, provides a clear-conversation button, preserves completed tool traces
with arguments and results, and shows the model, reference date and dataset.
Related-question buttons reuse explicit section and date filters and disappear
after the next submission. Missing credentials disable queries, and failed
requests remain visible without being repeated on a page rerun.

I adapted the optional UI example to the current agent's capabilities. The app
shows a progress indicator and then the complete response; it does not stream
tokens or show tool events live. It displays real source metadata instead of
inventing confidence scores, and its related questions are deterministic
shortcuts rather than model-generated suggestions. Session history is displayed
but is not passed to the model, so queries remain independent. No search-index
loading or cache is needed for the small local JSON fixture.

## What I implemented

I identified scenarios covering normal requests, tool selection, missing
filters, comparisons and misleading interpretations. I implemented 14 pytest
cases in [test_agent.py](tests/test_agent.py). Each case calls the real agent,
inspects its tool trace and checks specific response content. The tests cover
the tool names and arguments, including section, inclusive dates and the
requested Pareto metric.

The shared [agent fixture](tests/conftest.py) loads the API configuration and
fixes the reference date at 16 October 2026. Queries use absolute dates where
possible, and each call starts an independent conversation. Integration tests
are marked separately from tests that run without API calls.

The highest-priority regression test asks for the removal Pareto for TE in
October 2026. The expected call is `get_defect_pareto` with
`section="TE"`, `date_from="2026-10-01"`, `date_to="2026-10-31"` and
`metric="removed_boards"`. The tool returns `DEMO-CODE-C` with zero removals
and an existing source record. Its percentages are `null` because the total
is zero. The response must preserve that distinction.

I also added an [LLM judge test](tests/test_judge.py) using `assert_criteria`.
Its [three criteria](tests/judge_criteria.py) check the exact tool call,
acknowledgement of existing defect records despite zero removals, and the
absence of an unsupported defect rate or numeric Pareto percentage. Omitting
percentages is acceptable; if discussed, they must be described as undefined.

## What failed and what I changed

The agent reproduced the week 3 error: it listed a defect record with zero
removals, then said there were no matching records and coverage was unknown.
The tool result was correct, but the explanation contradicted it. I preserved
three failing executions in the [original evidence report](submissions/week4-llm-judge-evidence.md).

The judge also made a mistake. It sometimes rejected answers for not explaining
undefined percentages, even though the criterion only required this explanation
when percentages were mentioned. A quantity of zero boards is not a percentage.

The course notes discuss improving unreliable judge evaluations, including
presenting the answer as readable text. I added fixed-answer calibration tests
to verify the judge after observing inconsistent verdicts.

Before changing the agent, I calibrated the judge against six fixed examples
with human-assigned expected labels. These included valid answers, the
historical missing-records error, a numeric `0%`, an invented defect rate and
an incorrect date filter. The expected labels were not sent to the judge.

The first calibration passed only 6 of 12 tests. Clarifying the conditional
criterion and presenting the answer as readable text was insufficient: the
judge still let errors in one criterion affect another. I changed the
[judge helper](tests/judge.py) to evaluate each criterion in a separate request,
made the scope of each criterion explicit and placed the explanation before
the boolean verdict in the structured output. The final calibration matched
the expected labels in all 12 tests, with each example repeated twice.

I then updated the [agent instructions](est_prog/capstone_reporting/agent.py)
and the Pareto tool description to distinguish three situations:

- Nonempty Pareto items with a zero total: defect records exist, but the
  selected metric totals zero.
- Empty Pareto items with matching controls: controls exist without defect
  rows. The agent must obtain the summary before making this interpretation.
- A summary with zero matching controls: no matching records; coverage unknown.

I added a final consistency check to the instructions without changing the
agent's public response format. The deterministic calculations stayed unchanged.

One test assertion also needed correction: it rejected “no defect records”
even when the response correctly acknowledged a control without defects. I
narrowed it to detect claims that controls were absent or coverage was unknown.

## What is working now

The saved validation results are:

| Check | Observed result |
|---|---|
| Tests without API calls | 32 passed, including 4 Streamlit UI tests |
| Fixed-answer judge calibration | 12 passed; 36 criterion verdicts matched the expected labels |
| Three zero/missing-data scenarios with the real agent | 3 passed |
| Complete agent-and-judge regression test | Passed in three independent repetitions |

Both the agent and judge remained on `gpt-4o-mini`. Evaluating criteria separately
increases API usage: the three-criterion judge test now makes three judge calls
in addition to the agent's calls.

The [correction report](submissions/week4-judge-improvements.md) preserves the
iterations, full logs and final configuration. The original failure evidence
remains unchanged. I did not rerun all 14 behavioral scenarios after the final
prompt changes, so these results describe the targeted validation rather than
a fully passing integration suite.

The four [UI tests](tests/test_app.py) use Streamlit's `AppTest` and mocked
agent calls. They exercise session history, related questions, clearing the
conversation, errors, missing credentials and avoiding duplicate requests on
reruns. These tests do not validate a live model response or browser styling.
I also checked the dependency lock and the terminal demonstration independently
of the notebooks. The project follows the course's modular structure and core
chat interaction pattern; optional streaming remains future work.

## What I learned and what comes next

A failed test can reveal a problem in the agent, the assertion or the judge.
I need to compare the final answer with the tool evidence and the exact
criterion before deciding which component to change. Tests should accept
equivalent wording while still rejecting factual contradictions.

The calibration examples were used during the judge adjustments. Their success
does not measure general judge accuracy, and repeated passes do not guarantee
future consistency. Next, I want to add unseen calibration examples, rerun the
remaining behavioral scenarios and move more source, filter and coverage
presentation into deterministic code.

The project still uses synthetic data, has no ERP connection or conversational
memory, and does not support a validated defect rate or aggregation by job.
This week's progress gives me reproducible tests and evidence for improving
the interpretation layer before connecting real company data.
