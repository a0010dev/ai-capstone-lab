# PydanticAI runtime exploration

Date: 2026-11-06. Baseline: `9ca0e81` on `main`.
Experimental branch: `explore/pydanticai`.

## Result

The alternative runtime works with the current Streamlit interface and real
OpenAI Responses calls. It is opt-in through `REPORTING_AGENT_BACKEND=pydanticai`
or `run_agent(..., backend="pydanticai")`. The default remains `manual` so that
both implementations can be compared from this branch.

The main gain is explicit boundaries: typed tool definitions and framework-owned
validation, retries, conversation messages and telemetry. This exploration does
**not** establish lower latency, lower cost, better answers overall or fewer lines
of application code. Keeping the existing streaming/cost contract requires a
substantial adapter; both runtimes currently coexist.

## Implementation

- Shared reporting policy extracted verbatim to `instructions.py`.
- `pydantic_agent.py` defines three typed async tools, an agent with a typed
  reference-date dependency, and an adapter to the existing result/event contract.
- The tools still call `tools.py` and `defects.py`; calculations and source data
  are unchanged. Tool schemas come from Python types, including a Literal metric.
- Invalid arguments and backend ValueErrors request model correction. Model
  calls are bounded by the existing `max_rounds` parameter, including streaming.
- Native serialized history retains tool results and supports follow-ups. It is
  a different format from the baseline: the UI resets history on runtime changes.
  Direct callers should start a new history when switching runtimes. Plain UI
  error messages can be appended to native history for a subsequent retry.
- PydanticAI instrumentation emits model/tool spans under the existing session.
  The adapter preserves per-run and cumulative costs without double counting.
- Internally owned OpenAI clients close on exit; injected clients remain owned
  by the caller. The Responses API is explicitly configured with `store=False`.
- The dependency is `pydantic-ai-slim[openai]`, locked to 2.66.0. Resolution also
  updates OpenAI from 3.16.2 to 3.46.0; the manual runtime tests still pass.

## Evidence and behavior found

The initial five-case real-model check passed four cases. The count-only summary
called the right tool and returned the right quantities, but omitted
`synthetic-defects-v1` despite the shared instructions requiring it.

Added an output validator that checks dataset IDs in this turn's tool results
and requests a corrected answer if any are absent. A deterministic offline test
proves this recovery adds a model request without repeating the successful tool.
It is a narrow source-label check, not a guarantee of numerical or semantic
correctness. Retries can increase usage and latency.

After that change:

- Local suite: **83 passed, 30 deselected, 18 subtests passed** (7.85 s).
  This includes the existing manual-runtime tests, 18 new PydanticAI cases and
  a new UI runtime-switch case. Offline PydanticAI tests disable external model
  requests and exercise the real fixture tools through `FunctionModel`.
- Selected existing integration tests with the PydanticAI backend:
  **5 passed** (43.58 s): count-only summary, empty Pareto without controls,
  nonempty zero Pareto, a short section clarification preserving the comparison,
  and streaming tool/text events through completion.
- Native telemetry is checked with an actual in-memory OpenTelemetry exporter:
  model and tool spans share the session trace. This experiment does not verify
  remote Logfire ingestion for the new runtime.

Reproduce the local suite:

```sh
uv run --locked pytest -m 'not integration and not judge_calibration' -q
```

Reproduce the selected integration check (paid model requests; requires `.env`):

```sh
REPORTING_AGENT_BACKEND=pydanticai uv run --locked pytest -q \
  tests/test_agent.py::test_summary_reports_removed_boards \
  tests/test_agent.py::test_empty_pareto_without_controls_reports_unknown_coverage \
  tests/test_agent.py::test_zero_removals_with_existing_defect_is_not_missing_data \
  tests/test_conversation.py::test_real_short_section_reply_resolves_pending_comparison \
  tests/test_streaming_agent.py::test_real_stream_emits_tools_and_text_before_final_result
```

## Assessment

PydanticAI makes agent-specific responsibilities clearer and provides useful
validation/test extension points. The migration is feasible, but preserving all
current UI behavior means it is not a dramatic reduction in code at this stage.
Business rules still need explicit instructions or application checks: zero
quantities, unknown coverage and inspected sample versus production do not become
correct merely because tool arguments are typed.

Before adopting it as the sole runtime, run the full behavioral/judge suite,
compare representative conversations and request/token totals with the baseline,
and inspect remote Logfire traces. If the comparison is satisfactory, remove the
manual loop and its SDK-specific tests, then consider whether the UI should use
native PydanticAI events to reduce the adapter. Structured final reports and a
real company-API dependency remain separate design decisions.
