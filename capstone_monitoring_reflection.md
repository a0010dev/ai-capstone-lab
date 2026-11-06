# Monitoring the industrial reporting agent with Logfire

Week 5 update — 6 November 2026

## Why I added monitoring

I am building a read-only industrial reporting agent over synthetic inspection
data. Previous tests showed that correct tool results can still lead to an
incorrect explanation. This week, I added monitoring to inspect each interaction,
understand its token usage and cost, and collect examples for evaluation next week.

I used Pydantic Logfire, following the course's monitoring and cost-tracking
references. My trivia homework already used Logfire with PydanticAI. The capstone
initially called OpenAI through a custom loop, so its monitoring started with
explicit spans. The current implementation uses PydanticAI's native model and
tool instrumentation, with application spans for the reporting session and run.

## Connecting monitoring to the existing app

I reused the [Streamlit interface](app.py) from the previous submission. It now
supports streaming responses and preserves conversation context. Each answer
shows the tools called, their arguments and results, token usage, estimated cost
and trace ID. This lets me connect what appears in the chat with the corresponding
Logfire trace.

Each submitted question creates a `reporting_session` containing the agent run
and its model and tool operations. A Streamlit conversation can contain several
of these traces. For this collection, I started a fresh conversation for every
query, so each session represents one question and its complete execution.

I checked ingestion by retrieving the stored spans with `LogfireQueryClient`.
The trace shows the sequence of requests, tool inputs and outputs, and the final
answer. Usage appears at several levels of the trace, so I count each model
response once and reconcile those counts with the session total. Adding parent
and child usage together would overcount tokens.

## Collecting ten real interactions

With help from my coding assistant, I collected ten different queries through
Streamlit's `AppTest`. These were automated interactions with the real app and
real `gpt-4o-mini` requests, without mocked responses. The reporting data remained
synthetic; this was not production-user traffic.

The [query set](submissions/week5-usage-data/queries.json) covered summaries,
supporting records, Pareto rankings, comparisons between months, relative dates,
lowercase section codes, zero removals, controls without defect rows, future
periods without records, unsupported production totals and a missing section.

The [verified results](submissions/week5-usage-data/summary.json) were:

| Measure | Observed result |
|---|---:|
| Completed sessions | 10 |
| Stored spans retrieved from Logfire | 65 |
| Model requests | 23 |
| Tool calls | 12 |
| Total input tokens | 47,089 |
| Total output tokens | 2,374 |
| Total estimated cost | $0.00848775 USD |

An average session used approximately 4,709 input tokens and 237 output tokens,
costing $0.00085 USD. The median session cost was approximately $0.00082 USD.
These estimates use the project's rates of $0.15 per million input tokens and
$0.60 per million output tokens, without cache discounts. They are estimates
rather than reconciled invoice charges. Because every conversation started
fresh, these figures do not measure the cost of growing conversation history.

## Patterns visible in the traces

Simple data requests generally needed two model calls and one tool call: one
request to select the tool and another to answer using its result. The incomplete
question needed only one model call and no tools, because the agent asked which
section to use.

Three sessions needed an additional model request because the first answer
omitted the source dataset ID. The output validator requested a correction, and
the final answer included it. This showed me that validation affects both cost
and the number of requests, even when no additional reporting tool is needed.

The edge cases also showed useful behavior. The agent resolved “last month” to
October 2026 using the November reference date. A Pareto with existing defect
records and zero removals retained the zero quantity and described its shares
as undefined. When a Pareto returned no items, the agent requested a summary
before explaining whether controls existed.

## Two answer errors despite successful execution

All ten interactions completed without an exception, but reviewing the answers
against the tool evidence exposed two quality problems. The
[saved observations](submissions/week5-usage-data/findings.json) preserve both.

In the detailed removal answer, the summary correctly reported 12. The original
records contained removal quantities of 3, 1 and 8. However, the answer assigned
3 to a control containing the first two records and 8 to the other control.
Its displayed breakdown therefore summed to 11. The model mentioned both
records under the first control but failed to preserve their quantities. The
answer should have shown the original record values, which reconcile as
3 + 1 + 8 = 12.

In the comparison between August and September, the August summary returned
zero matching controls. The answer displayed that count but went on to describe
greater defect activity in September without clearly warning that August's
coverage was unknown. An empty selection cannot establish a defect-free month
or support a conclusion about operational change. The answer should have stated
the missing coverage and reported September's quantities without inferring a
trend.

Both problems occurred after the tools returned correct data. A completed trace
therefore tells me that the execution finished; assessing correctness still
requires comparing the explanation with its evidence.

## What I will evaluate next

I now have [interaction records](submissions/week5-usage-data/interactions.json)
and [serialized messages](submissions/week5-usage-data/messages.json) for the ten
sessions. I can use these to build evaluation examples for whether the selected
filters match the question, supporting quantities reconcile with totals, and
missing controls are distinguished from observed zero values.

The two observed failures remain examples to fix and retest. I also want to
measure longer conversations, where retained history may change tool reuse and
token consumption. Monitoring gives me the execution evidence and usage data;
evaluation will help determine whether the agent uses that evidence correctly.
