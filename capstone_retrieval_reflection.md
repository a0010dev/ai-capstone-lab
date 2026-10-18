# Capstone progress: from deterministic retrieval to a reporting agent

Week 3 update — 18 October 2026

## What I started

I am building a read-only reporting agent for company operational data. The
idea is to help users answer business questions that would otherwise require
asking IT to retrieve data and prepare a report.

My first domain is manufacturing defects and rejection. Today, the project is
a Python prototype using synthetic data. I started with deterministic
retrieval: loading structured records and selecting them with explicit filters.
This week, I added an LLM that chooses reporting tools and uses their results
to answer questions. The reporting workflow uses structured data and does not
require RAG; the original RAG notebook remains available as a baseline.

## What is working

`load_defects` loads the synthetic JSON dataset using its default location or
an explicit path, and
`filter_defects` selects controls by section and date range. Filters combine
with AND, date boundaries are inclusive, and the results keep the original
defect records attached to each control.

For example, selecting section TE for September 2026 returns three of the six
synthetic controls. One has no defects, and it remains in the result. Keeping
that control matters because a reporting dataset should also represent
inspections where nothing went wrong.

The retrieval demonstration is in
[03-defect-retrieval.ipynb](notebooks/03-defect-retrieval.ipynb).

This week's agent exposes three deterministic tools: `get_defect_summary`,
`get_defect_detail` and `get_defect_pareto`. A Responses API loop lets the model
choose tools, while Python validates arguments, restricts execution to approved
functions and calculates totals and percentages. Each result retains filters,
synthetic dataset metadata and provisional metric semantics. The loop preserves
tool traces and has a limit on model rounds.

For TE in September 2026, the summary returns 3 controls, a sample quantity of
220, 23 errors, 19 affected boards, 4 repaired boards and 12 removed boards.
Board counts represent recorded occurrences, not unique physical boards.
The removal Pareto ranks defect codes C=8, A=3 and B=1, with cumulative shares
of 66.67%, 91.67% and 100%. These shares describe contributions to the selected
metric; they are not defect rates or evidence of business causes. All four
Pareto metrics reconcile with the summary and original detail rows.

I evaluated eleven business queries with `gpt-4o-mini`, covering summaries,
detail, Pareto metrics, comparisons, relative dates, clarification, empty
selections and an unsupported rate request. The saved execution is in
[04-reporting-agent.ipynb](notebooks/04-reporting-agent.ipynb).
The [English submission copy](notebooks/04-reporting-agent-en.ipynb) translates
the saved prompts and answers; it is not a new execution with English prompts.
The reference date is fixed at 16 October 2026 to make “last month” reproducible.
All eleven cases passed the notebook's tool-call and result checks, and all
28 automated tests passed. These checks do not certify every statement in the
model's answers.

## What I learned this week

The most useful failure was a Pareto query with a zero total. The tool returned
an existing record with zero removals and undefined percentages (`null`). The
model listed that record but also said there were no matching records. A zero
metric and an empty selection require different interpretations.

Other answers exposed similar gaps between correct tool results and prose:
the detail answer reported 3 removals for a control whose rows sum to 4, and
the comparison omitted the unknown-coverage warning for an empty period.
The rate answer avoided inventing a number but did not explain the missing
validated denominator. Correct routing and deterministic calculations are
necessary, but the final answer still needs validation against the tool trace.

## What I plan to improve

Next, I want to validate answers structurally and present filters, source,
metric semantics and coverage information directly from Python. I will make
the distinction between zero totals and empty selections explicit and expand
the evaluation with reference reports and expected answers.

The project still has no ERP connection, validated rate denominator,
aggregation by job or memory between queries. Manufacturing rules and data
coverage must be validated before connecting a real read-only source. This
week's progress demonstrates orchestration over a synthetic fixture; the next
milestone is making the final presentation as reliable as the underlying tools.
