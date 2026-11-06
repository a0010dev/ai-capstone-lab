# Conversation context and metric interpretation

## Reported problem

The UI displayed chat history, but `run_agent` started every query with only
the latest user message. A follow-up such as “And in October?” lost the sections
and metric, and a reply such as “te” lost the period from the pending question.
The previous UI caption explicitly described this independent-query design.

The reported first answer also labelled `sample_quantity=220` as completed
boards and `errors=23` as boards with errors. In the synthetic TE September
fixture, 220 is the inspected sample, 23 is error occurrences and 19 is recorded
affected-board occurrences. None establishes total production or unique boards.

## Implementation

- `run_agent` accepts optional `message_history` and returns replayable history
  alongside the existing answer, trace, model and reference date.
- Caller history is copied, the current question is appended once, and completed
  assistant outputs, reasoning items, tool calls and outputs are preserved in
  order. SDK-only parsed fields are removed before API replay.
- Clarification answers are retained even when no tools were called. A short
  reply can therefore complete an earlier request.
- Streamlit keeps this state per session. “Esborra la conversa” clears both
  visible messages and model context. Old UI sessions can recover their visible
  transcript; new turns retain full tool evidence.
- On a failed request, session context retains the question and a generic error,
  not unfinished tool calls, partial answer text or provider exception details.
- The visible message results omit repeated copies of the whole conversation;
  the full current history is stored separately in session state.
- Requests still use `store=False`. No server-side conversation IDs or durable
  history store are introduced. API callers remain independent unless they pass
  history explicitly.

The instructions now use conversation context to resolve sections, dates/year
and metrics, including multi-section follow-ups and explicit scope changes.
They distinguish inspected samples, error occurrences, affected-board occurrences
and unavailable production totals. They also instruct the model to answer the
supported defect part without requesting permission just because production
totals are unavailable.

## Validation

| Check | Observed result |
|---|---|
| Offline suite with runtime warnings treated as errors | **59 passed**, 30 integration cases deselected |
| Two focused live conversation tests | **2 passed**, 7 offline conversation cases deselected |

The new offline checks cover history replay without mutation, serializable tool
evidence, no cross-call context without explicit history, failed-turn rollback,
invalid histories, passing context from the UI, clearing it and excluding
unfinished tool calls after errors. Existing streaming and async tests continue
to pass. Logs: [offline](conversation-context/offline.txt),
[final live integration](conversation-context/final-integration.txt).

The live tests use a fixed reference date of **2026-11-03** and `gpt-4o-mini`:

1. A fixed pending clarification asks for the section for a September/October
   2026 affected-board comparison. The user replies “te”. The agent queries
   both complete months for TE and reports 19 versus 3 affected-board occurrences.
   The pending question is seeded to isolate clarification resolution from the
   separate question of whether the model reliably asks it initially.
2. A streamed first question asks about manufactured boards and boards with
   errors in TE and TV in September 2026, followed by “I a l'octubre, n'hi ha
   més o menys?”. The agent retains both sections and the year, retrieves October
   with complete-month filters, and distinguishes sample quantities from the
   affected-board quantities. Earlier tool evidence is available to the follow-up.

The final tests target carried scope and metric labels. Exact missing-coverage
wording remains covered by the existing empty-data behavioral tests; those
assertions have not been weakened or removed.

## Iterations and remaining limitations

Earlier attempts exposed additional model and test issues:

- The model sometimes queried TE and TV without an explicit section selection
  rather than asking for clarification. Instructions were reinforced, but this
  increment does not establish that the initial clarification behavior is fully
  reliable. [Initial integration log](conversation-context/initial-integration.txt).
- Early assertions were overly literal about “mostra” and failed equivalent
  inspected-board wording, and one failed to accept “No es disposa”. The final
  metric checks accept inspected/examined sample wording while still rejecting
  labels that present these values as production or 23 errors as affected boards.
- One run explained that production was unavailable but unnecessarily asked
  permission before retrieving the supported defect data. The instructions were
  clarified. [Log](conversation-context/clarification-pass-permission-failure.txt).
- A run carried both sections into October correctly but omitted the exact
  “cobertura desconeguda” phrase for TV. It did say there were no records and that
  no comparison could be made. This is a separate coverage-wording issue, recorded
  in the [broader earlier check](conversation-context/context-with-coverage-warning-failure.txt).

The context transport is now explicit and tested; it does not guarantee that
the model always interprets every follow-up or metric correctly. The full
behavioral and judge-calibration suites have not been rerun in this increment.
Session history grows without automatic truncation or summarization and is not
durable across devices or disconnected sessions. Existing evidence reports remain
records of their original executions.

## Usage

```python
first = await run_agent("Mostra les plaques afectades de TE i TV de setembre de 2026.")
second = await run_agent("I a l'octubre?", message_history=first["message_history"])
```

```sh
uv run pytest -m "not integration" -q -W error::RuntimeWarning
uv run pytest tests/test_conversation.py -m integration -v -s
uv run streamlit run app.py
```

History replay follows the [official Responses conversation-state guide](https://developers.openai.com/api/docs/guides/conversation-state).
