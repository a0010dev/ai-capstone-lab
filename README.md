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
