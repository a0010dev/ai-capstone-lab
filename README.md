# Industrial Reporting Agent

A read-only reporting agent over company data, built as an AI Engineering Buildcamp capstone project. It helps industrial company users answer business questions while keeping data access and calculations controlled and deterministic.

## The Problem

When industrial company users need information that is not covered by an existing report, they often have to describe their needs to IT, which retrieves the data and builds a report. This project aims to let users ask those questions directly and receive reliable answers from company data.

## What It Does

The agent interprets business questions and uses approved, read-only tools to query the ERP and potentially other company sources. The tools control data access and perform deterministic calculations; the agent returns a structured answer with relevant totals and supporting detail.

For example, a user might ask: “Show me the defect rate for this production section this month and compare it with the previous month.” The agent would identify the section and periods, request clarification when needed, and retrieve production and defect totals using the appropriate tools. Its answer would show the defect rate for each month, the comparison, and the underlying totals and calculation definition so users can check the result.

Existing report requests and their expected results will form an evaluation set to test whether the agent returns the information users actually need and matches the established calculations.

## Setup

1. Install uv if you don't have it yet: https://docs.astral.sh/uv/getting-started/installation/

2. Clone this repository (or download the zip and extract it).

3. Create a `.env` file from the template and add your API key:

       cp .env.example .env

4. Install dependencies:

       uv sync

5. Start Jupyter:

       uv run jupyter notebook

## Notebooks

- `notebooks/01-setup.ipynb` - smoke test that confirms your environment works
- `notebooks/02-rag.ipynb` - original minimal RAG baseline
- `notebooks/03-defect-retrieval.ipynb` - deterministic retrieval of synthetic defect records; no RAG or LLM
- `notebooks/04-reporting-agent.ipynb` - week 3 tool-calling agent with eleven business queries including Pareto, visible tool traces and checks against the synthetic fixture

## Week 3: tool-calling agent

Three deterministic tools are implemented: `get_defect_summary` for totals,
`get_defect_detail` for source controls and defect rows, and `get_defect_pareto`
for ranking defect codes by a selected metric. All three take `section`,
`date_from`, and `date_to`, and return the applied filters,
synthetic source, and provisional metric semantics. A document search tool
would not add value for these structured reporting queries.

`est_prog/capstone_reporting/agent.py` adds a Python 3 Responses API loop over
these functions, following the [official function-calling protocol](https://developers.openai.com/api/docs/guides/function-calling).
The model selects tools; an allowlisted dispatcher validates the arguments,
executes the functions, and returns their results to the model. The loop keeps
a tool trace and stops after at most eight model rounds. The original RAG
notebook remains available as a baseline; the deterministic backend has no
OpenAI dependency. This capstone requires Python 3.13 or later. Python 2.7 is
a constraint of the external ERP environment, not a local runtime or test requirement.

Open notebook 04 and run all cells with `OPENAI_API_KEY` configured in `.env`.
It uses the baseline model `gpt-4o-mini`; set `OPENAI_MODEL` to override it.
Running the notebook makes paid API calls. The evaluation fixes the reference
date at `2026-10-16` to make relative-month queries reproducible.

```python
from dotenv import load_dotenv
from est_prog.capstone_reporting.agent import run_agent

load_dotenv()
result = run_agent("Show the defect summary for TE in September 2026.")
print(result["answer"])
print(result["tool_calls"])
```

Each call starts a fresh conversation. If the agent asks for clarification,
submit the complete clarified question in a new call. API failures propagate;
invalid tool arguments are returned to the model for correction. No matching
records do not establish zero production or complete data coverage. Rates
and job aggregation remain unsupported until their definitions and
dedicated deterministic tools are validated. Natural-language answers still
need review against the traces; the notebook checks routing, filters and facts,
not every claim in the prose. No ERP connection is made.

## Defect Pareto

```python
from est_prog.capstone_reporting import get_defect_pareto

pareto = get_defect_pareto(
    section="TE", date_from="2026-09-01", date_to="2026-09-30",
    metric="removed_boards",
)
```

Allowed metrics are `errors`, `affected_boards`, `repaired_boards`, and
`removed_boards` (the default). The response includes the common metadata,
`metric`, `total_quantity`, and `items` ranked by descending quantity, with
ascending defect codes breaking ties. Each item includes its quantity, share,
cumulative share, and original job/control/record references. Shares are
contributions to the selected metric, not defect rates or evidence of causes.
Percentages are unrounded; zero totals produce `null` percentages and retain
observed codes and source rows. No defect rows produces an empty list.
For TE in September 2026, removals rank C=8, A=3, B=1 (total 12).
The Python function defaults to `removed_boards`; the agent's strict tool
schema requires an explicit `metric` and instructs the model to select that
default when the user does not specify one.

Run the summary → Pareto → detail demonstration without API calls:

```sh
python3 -m est_prog.capstone_reporting
python3 -m unittest discover -s tests -v
```

## Data

The fixed synthetic fixture is
`data/synthetic_defects.json`. Load and filter it
with the standard-library retrieval functions:

```python
from est_prog.capstone_reporting import load_defects, filter_defects

dataset = load_defects()  # or load_defects("path/to/dataset.json")
records = filter_defects(
    dataset, section="TE", date_from="2026-09-01", date_to="2026-09-30"
)
```

This returns three controls with their nested defect rows, including the control
without defects. Filters combine with AND, section matches exactly, and date
limits are inclusive. Empty selections return `[]`; invalid filters raise
`ValueError`. Records retain source order. Loading reads fresh objects; filtering
does not mutate them, but the returned records reference the loaded dataset.
The default data path works independently of the current working directory.
No API key is needed for this notebook. Existing summary/detail functions remain
available; the retrieval layer itself does not calculate metrics.

Run the retrieval checks with:

```sh
uv run python -m unittest discover -s tests -v
```
