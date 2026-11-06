# Streaming text and tool activity

This increment adds streaming on top of the async migration. The Streamlit UI
now consumes real Responses API text deltas and tool lifecycle events while
the existing final result remains available to tests and the judge.

## Behavior

`await run_agent(question, on_event=callback)` enables streaming. The callback
is asynchronous and receives `round_start`, `text_delta`, `tool_start`,
`tool_end` and `completed` dictionaries. Without a callback, the completed
response path remains available.

The model's tool-call arguments are assembled fully before a tool executes.
`tool_start` is emitted just before execution, and `tool_end` carries the
result. These events update Streamlit's expanded activity panel. Text fragments
update an answer placeholder with a cursor. A new model round resets provisional
text so a pre-tool explanation is not concatenated with the final answer.

The completed response replaces provisional text, removes the cursor and is
saved with the full trace and source metadata. History and activity panels
survive reruns without repeating the request. On failure, partial answer text
is discarded and the error and available tool trace persist. Streams and owned
clients close on completion, callback errors, transport failures or cancellation.

The application still uses deterministic related-question shortcuts and real
dataset metadata. It does not invent confidence fields or add model memory.
The business instructions, tool calculations and judge criteria are unchanged.

## API protocol issue discovered by the live test

The first streamed run exposed an SDK/API boundary issue: the SDK's assembled
function-call output includes `parsed_arguments`. Reusing that object directly
as input for the next round produced HTTP 400:

```text
Unknown parameter: 'input[1].parsed_arguments'.
```

The agent now serializes output items for reuse, removing SDK-only
`parsed_arguments` and nested `parsed` fields. Function-call IDs, complete
arguments, messages and reasoning context remain available for subsequent
rounds. Source SDK objects are not mutated. A regression test uses actual SDK
parsed-output classes to reproduce this serialization case without the API.

[Initial SDK error log](streaming/initial-sdk-error.txt).

## Validation

| Check | Observed result |
|---|---|
| Offline suite, runtime warnings treated as errors | **50 passed**, 28 integration cases deselected |
| Live streamed Pareto request | **1 passed**, 7 offline streaming cases deselected |
| Final-round text fragments in that live request | **161** |
| Model rounds in that live request | **2** |
| Tool activity in that live request | **1 start and 1 end** |

The [successful live log](streaming/pareto-stream-success.txt) records the final
answer, tool result and event sequence. The test verifies events arrive before
`run_agent` returns, complete tool arguments use the selected filters and metric,
the tool-end events match the final trace, and the final round's concatenated
text fragments equal the assembled answer.

Offline tests also cover fragmented arguments, preserving reasoning and call IDs,
equivalence with the completed-response path, round limits, cancellation,
callback and transport errors, provisional-text resets and Streamlit persistence.
The UI tests exercise an interrupted stream without presenting its partial
text as a completed answer.

## Separate behavioral observation

After fixing the protocol, an earlier smoke test asked for the number of removed
boards. The model returned a valid streamed Pareto instead of the expected
summary call, so that test failed its tool-selection assertion. This was a
completed streamed request with a routing deviation, rather than a transport
failure. The [routing observation log](streaming/summary-routing-observation.txt)
is preserved.

The final streaming smoke test uses an explicit Pareto request to make its
technical scenario unambiguous. Existing summary-routing tests remain unchanged.
This passing smoke test does not establish that all business queries or judge
evaluations are reliable; the async migration's separate findings remain recorded
in [its report](async-migration.md).

## Reproduction

```sh
# Offline protocol and UI checks.
uv run pytest -m "not integration" -q -W error::RuntimeWarning

# One live stream; requires OPENAI_API_KEY and incurs API usage.
uv run pytest tests/test_streaming_agent.py -m integration -v -s

# Browser UI.
uv run streamlit run app.py
```

The implementation follows the [official Responses streaming guide](https://developers.openai.com/api/docs/guides/streaming-responses)
and [streaming-event reference](https://developers.openai.com/api/reference/resources/responses/streaming-events).
Historical reflection, notebook outputs and previous evidence reports are retained
as records of their original executions.
