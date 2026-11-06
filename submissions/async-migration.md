# Async migration of the industrial reporting agent

This increment follows the week 4 testing commit. It changes how requests are
executed, while retaining the existing model, instructions, criteria, tool
schemas, filters, calculations and answer/trace result shape.

## Changes

- `agent.run_agent` is a coroutine using `AsyncOpenAI` and awaited Responses API
  calls. `execute_tool` awaits the allowlisted reporting function.
- `tools.py` exposes async summary, detail and Pareto functions. The current
  local JSON backend runs through `asyncio.to_thread` so file reads do not
  block the event loop. Deterministic calculations remain in `defects.py`.
- A future API implementation can replace these tool bodies with awaited HTTP
  requests. No real API URL, authentication or endpoint contract is configured
  in this increment, and no ERP connection is claimed.
- Internally created model/judge clients use an async context manager, closing
  on success, errors or cancellation. Injected clients remain caller-owned.
- Judge helpers and their callers are asynchronous. Each criterion still gets
  its own request; model rounds and tool execution retain their sequential order.
- Pytest integration tests use `pytest-asyncio`; existing unittest agent tests
  use `IsolatedAsyncioTestCase` with an async fake client.
- Streamlit remains the synchronous entry point and runs a fresh coroutine with
  `asyncio.run` for each question. It does not cache clients across event loops.
  UI tests verify the patched async agent is actually awaited.
- Both notebook 04 variants now use top-level `await`. Their saved outputs and
  execution counts are unchanged and labelled as historical. The legacy RAG
  notebook has not been included in this migration.

The synchronous functions exported from the package root are still available
for offline calculations and `python -m est_prog.capstone_reporting`.

## Validation

| Check | Observed result |
|---|---|
| Offline suite, with runtime warnings treated as errors | **41 passed**, 27 integration cases deselected |
| Selected live integration cases | **6 passed, 2 failed**, 19 other integration cases deselected |
| Dependency lock | `uv lock --check --offline` passed |
| Deterministic terminal demo | Completed successfully |
| Call-site inspection | Coroutine calls are awaited or explicitly scheduled |
| Notebook saved outputs | Unchanged from the preceding commit |

The nine new offline cases check fixture tools running outside the event-loop
thread, result equivalence, client cleanup on success/failure/cancellation,
awaiting a simulated future API tool before the next model round, and async
judge verdict handling and resource ownership. The existing tests continue
to check filters, dispatch validation, tool-result round trips and the UI.

In this managed execution environment, sandboxed thread/event-loop shutdown
stalled; the same offline suite completed outside that sandbox in 2.94 seconds.
The stalled diagnostic processes were stopped. This did not require a change
to the application behavior.

The [complete live integration log](async-migration-integration.txt) records
the following selected cases:

| Live case | Result |
|---|---|
| Empty Pareto without matching controls | PASS |
| Empty Pareto with an existing healthy control | FAIL |
| Nonempty Pareto with zero removals | PASS |
| Complete agent-and-judge zero-removal test | FAIL |
| Correct fixed answer without percentages, two repetitions | PASS / PASS |
| Historical incorrect missing-records answer, two repetitions | PASS / PASS |

The calibration tests pass when the judge matches the expected labels, including
expected rejections. All twelve criterion verdicts in these four fixed-answer
checks matched the human labels.

## Remaining behavioral findings

In the healthy-control case, the tools return one control and no defects. The
answer acknowledges the control, but then incorrectly concludes that matching
records are absent and coverage is unknown. The existing assertion correctly
rejects this contradiction.

In the complete judge test, the answer identifies the existing zero-removal
defect and displays percentages as `no definit`. The judge passes the tool and
record criteria but rejects the percentage criterion, claiming the percentage
column itself violates the prohibition on numeric percentages. That reasoning
does not distinguish a column label from a numeric percentage. The answer also
does not explicitly spell out the zero-total reason, so a manual review of the
full conditional criterion is still needed; this run does not establish that
the entire answer satisfies it.

Both failures occur after awaited requests complete and return ordinary results.
The business instructions and criteria are unchanged from the preceding commit.
These findings concern content and evaluation rather than unawaited coroutines
or transport errors. They are recorded without weakening tests or rerunning
until a passing model sample appears. The full behavioral suite and all six
calibration examples have not been rerun in this increment.

## Usage

```python
# Inside Jupyter or an async function:
result = await run_agent(question)

# At a synchronous script boundary:
result = asyncio.run(run_agent(question))

# Awaitable reporting interface:
from est_prog.capstone_reporting.tools import get_defect_summary
summary = await get_defect_summary(
    section="TE", date_from="2026-09-01", date_to="2026-09-30",
)
```

```sh
uv run pytest -m "not integration" -q -W error::RuntimeWarning
uv run streamlit run app.py
```

This migration does not add streaming, parallel tool calls, conversational
memory or the real reporting API. Historical week 4 reflections and evidence
remain records of their original executions. Async client usage and cleanup
follow the [official OpenAI Python SDK documentation](https://developers.openai.com/api/reference/python).
