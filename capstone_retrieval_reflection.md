# Capstone progress on deterministic data retrieval

## What I started

I am building a read-only reporting agent for company operational data. The
idea is to help users answer business questions that would otherwise require
asking IT to retrieve data and prepare a report.

My first domain is manufacturing defects and rejection. Today, the project is
a small Python prototype using synthetic data. I started with deterministic
retrieval: loading structured records and selecting them with explicit filters.
The future agent will call these functions to obtain facts. This increment
does not use RAG or an LLM.

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

The demonstration is in [03-defect-retrieval.ipynb](notebooks/03-defect-retrieval.ipynb).
I have also added tests for filter boundaries, empty results, invalid inputs
and independent dataset loads.

## What I plan to improve

Next, I want to expand the synthetic examples and validate the meaning of the
manufacturing quantities before treating any summary as a business rule. I
will use representative reporting questions and expected records to check the
tools. After that, I plan to add an LLM that interprets a question and chooses
the appropriate deterministic function, then eventually connect the tools to
a real read-only data source.

My main learning so far is that the first useful milestone can be small:
retrieve the right records reliably before building the conversational layer.
