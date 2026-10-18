"""Python 3 conversational layer over the existing read-only fixture tools."""
import json
from datetime import date

from .defects import get_defect_detail, get_defect_summary, get_defect_pareto


TOOL_FUNCTIONS = {
    "get_defect_summary": get_defect_summary,
    "get_defect_detail": get_defect_detail,
    "get_defect_pareto": get_defect_pareto,
}
FILTER_NAMES = ("section", "date_from", "date_to")
TOOLS = [
    {
        "type": "function",
        "name": name,
        "description": description,
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "section": {"type": ["string", "null"],
                            "description": "Exact section code; null means all sections."},
                "date_from": {"type": ["string", "null"],
                              "description": "Inclusive ISO date YYYY-MM-DD, or null for no lower limit."},
                "date_to": {"type": ["string", "null"],
                            "description": "Inclusive ISO date YYYY-MM-DD, or null for no upper limit."},
            },
            "required": list(FILTER_NAMES),
            "additionalProperties": False,
        },
    }
    for name, description in [
        ("get_defect_summary", "Retrieve deterministic totals for a section and period. "
         "Use for counts and summaries; returns totals, filters, source and metric semantics."),
        ("get_defect_detail", "Retrieve original controls and nested defect rows, including healthy controls. "
         "Use to explain totals with job, control and defect record IDs; returns records, filters, source and semantics."),
    ]
]
TOOLS.append({
    "type": "function",
    "name": "get_defect_pareto",
    "description": "Rank observed defect codes by a selected metric, with original "
                   "job/control/record references. Percentages are contributions to "
                   "that metric, not defect rates or evidence of causes. Quantities "
                   "are recorded occurrences, not unique boards. Zero totals have "
                   "null percentages; observed zero-quantity rows are retained.",
    "strict": True,
    "parameters": {
        "type": "object",
        "properties": dict(TOOLS[0]["parameters"]["properties"], metric={
            "type": "string",
            "enum": ["errors", "affected_boards", "repaired_boards", "removed_boards"],
            "description": "Metric to rank; use removed_boards when unspecified.",
        }),
        "required": list(FILTER_NAMES) + ["metric"],
        "additionalProperties": False,
    },
})

INSTRUCTIONS = """You are a read-only industrial reporting assistant. Answer concisely in the user's language.
In Catalan use 'plaques afectades', 'plaques reparades', 'plaques retirades', and 'mostra'.
Use the tools for every claim about operational data. Never invent numbers or records.
This backend contains SYNTHETIC fixture data, not production ERP data. Say so in answers.
Start EVERY data answer with 'Dades sintètiques' (or its translation).
Show the selected section, explicit inclusive dates and dataset_id.
Only show individual record IDs when the user asks for detail or explanations;
do not call the detail tool for a summary-only request.
For summaries use get_defect_summary; for supporting jobs/records use get_defect_detail
with the same filters. Comparisons need a separate summary call for each period.
The synthetic fixture's section codes are TE and TV. In a question, 'TE' by itself
already specifies section='TE'; 'TV' specifies section='TV'. Never ask for the section
again when either code appears. Other explicit codes may be queried and return no records.
For example, 'resum de TE del mes passat' specifies TE and the previous calendar
month; 'resum de TE de gener de 2027' specifies TE, 2027-01-01 through 2027-01-31.
Use exact section codes. Ask for clarification only when section or period is missing or ambiguous;
do not silently choose all data. Ask directly, without inventing example section codes.
Do not ask permission or confirmation when section and period are already clear.
Use null filters only when the user explicitly wants
all sections or unrestricted dates. Resolve relative calendar months using today's date below.
Always call the tools for explicit periods, INCLUDING FUTURE DATES; do not assume data
coverage from today's date. Today is only the reference for relative dates.
When control_count is zero, ALWAYS explicitly say 'no matching records; coverage unknown'
(in Catalan: 'sense registres coincidents; cobertura desconeguda'), including comparisons.
Never describe zero matching controls as a defect-free period or an improvement.
Counts of boards are recorded occurrences, not unique physical boards. Sample is summed once
per control. Errors, affected, repaired and removed quantities are independent sums.
For Pareto or ranking defect codes, use get_defect_pareto with the same filters.
Select the requested metric; use removed_boards when unspecified. Use the returned
quantities, percentages and cumulative percentages, without computing them yourself.
Percentages are contributions to that metric, not defect rates. Null percentages
mean undefined because the total is zero. Never infer business causes from a ranking.
An empty Pareto does not distinguish healthy controls from no matching controls;
call get_defect_summary with the same filters before interpreting an empty result.
No defect rate, production denominator or job aggregation tool is available.
Do not calculate rates or invent manufacturing rules. Explain this limit for rate requests.
For removal explanations list the source rows with their job IDs and recorded quantities;
use the summary tool for the total. Do not invent job subtotals.
If a tool returns an error, correct arguments or ask the user; do not treat it as data.
Never execute SQL, code, writes or tools outside the provided list.
"""


def execute_tool(name, arguments):
    """Validate model-supplied arguments and dispatch only approved functions."""
    if name not in TOOL_FUNCTIONS:
        return {"error": "unknown_tool", "message": "Use an approved reporting tool."}
    try:
        values = json.loads(arguments)
        names = FILTER_NAMES + (("metric",) if name == "get_defect_pareto" else ())
        if not isinstance(values, dict) or set(values) != set(names):
            raise ValueError("Provide exactly: " + ", ".join(names) + ".")
        if any(values[key] is not None and not isinstance(values[key], str)
               for key in FILTER_NAMES):
            raise ValueError("Filters must be strings or null.")
        return TOOL_FUNCTIONS[name](**values)
    except (ValueError, TypeError) as exc:
        return {"error": "invalid_arguments", "message": str(exc)}


def run_agent(query, *, client=None, model="gpt-4o-mini", today=None, max_rounds=8):
    """Return answer and tool trace; each call is an independent conversation.

    Pass a follow-up as a new, self-contained query after clarification.
    API/transport failures propagate; exhausting the loop raises RuntimeError.
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")
    if not isinstance(max_rounds, int) or max_rounds < 1:
        raise ValueError("max_rounds must be a positive integer")
    reference_date = date.today() if today is None else date.fromisoformat(today)
    if client is None:
        from openai import OpenAI
        client = OpenAI(timeout=60.0, max_retries=1)
    instructions = INSTRUCTIONS + "\nToday's date: " + reference_date.isoformat()
    messages = [{"role": "user", "content": query}]
    trace = []
    for _ in range(max_rounds):
        response = client.responses.create(
            model=model, instructions=instructions, input=list(messages),
            tools=TOOLS, store=False,
        )
        if response.status != "completed":
            raise RuntimeError("Model response did not complete: " + response.status)
        # Preserve all output items, including reasoning items, for subsequent calls.
        messages.extend(response.output)
        calls = [item for item in response.output if item.type == "function_call"]
        if not calls:
            if not response.output_text.strip():
                raise RuntimeError("Model returned neither tool calls nor an answer")
            return {"answer": response.output_text, "tool_calls": trace,
                    "model": model, "reference_date": reference_date.isoformat()}
        for call in calls:
            result = execute_tool(call.name, call.arguments)
            trace.append({"name": call.name, "arguments": call.arguments, "result": result})
            messages.append({"type": "function_call_output", "call_id": call.call_id,
                             "output": json.dumps(result, ensure_ascii=False)})
    raise RuntimeError("Agent exceeded max_rounds without a final answer")
