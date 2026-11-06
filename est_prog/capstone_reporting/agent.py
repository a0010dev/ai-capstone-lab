"""Python 3 conversational layer over the existing read-only fixture tools."""
import json
from contextlib import AsyncExitStack, ExitStack
from copy import deepcopy
from datetime import date

import logfire

from .cost_tracker import CostAccumulator
from .monitoring import (annotate_usage, current_session, monitoring_session, trace_id)
from .tools import get_defect_detail, get_defect_summary, get_defect_pareto


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
                   "null percentages; observed zero-quantity rows are retained. "
                   "If items is empty, you MUST call get_defect_summary with the "
                   "same filters before answering; the Pareto alone cannot tell "
                   "whether any controls exist.",
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
BEFORE ANY TOOL CALL: the user must have selected a section somewhere in the
conversation, or explicitly requested all sections. TE/TV mentioned in these
instructions are available codes, NOT a user selection. If the user has not
selected a section, ask for it and make NO tool calls. Do not default to both.
Interpret user-written 'te'/'tv' case-insensitively as exact codes TE/TV.
Use the supplied conversation history to resolve follow-ups and clarification
answers. Carry forward the established sections, dates/year and requested metric.
Explicit changes in the latest user message override the earlier selection.
If the previous question covered TE and TV, a follow-up about another month
still covers BOTH sections unless the user narrows it. A reply such as 'TE' to
a section clarification fills that field; keep the period and metric already
provided. Ask only for information absent or genuinely ambiguous in the ENTIRE
conversation. Never ask again for a known section or period. For a comparison,
retrieve each needed period not already supported by tool results in this history.
CRITICAL METRIC MEANING: sample_quantity is the inspected sample, NOT total
production, completed boards or boards manufactured. Never label it 'plaques
fetes', 'plaques produïdes' or 'plaques completes'. No production-total tool exists.
errors counts defect/error occurrences, NOT boards with errors. For 'plaques amb
error', report affected_boards as recorded affected-board occurrences, not errors
or unique boards. If production and defects are requested together, explain that
production is unavailable and provide the supported sample/affected quantities.
When production and affected boards are requested together, the user has ALREADY
asked for defect data: call get_defect_summary for the selected sections/period
immediately to answer that supported part. Do NOT ask permission to retrieve it.
In a 'more or less' follow-up to that request, compare the supported affected-board
occurrences, keeping the sections/year; explain that production cannot be compared.
Prior assistant wording is not evidence: correct any earlier metric mislabelling
against tool results instead of repeating it.
CRITICAL TOOL-RESULT CHECK: inspect Pareto items BEFORE looking at total_quantity.
If items=[], your next action MUST be a get_defect_summary call with the same
section/date_from/date_to, unless that exact summary was already retrieved.
Do not give a final answer before this summary. An empty items list supplies NO
evidence about whether controls exist; do not claim defect records exist either.
If items contains rows, those defect records exist even when every quantity is 0.
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
Only when a summary explicitly returns totals.control_count=0, say 'no matching records; coverage unknown'
(in Catalan: 'sense registres coincidents; cobertura desconeguda'), including comparisons.
An absent control_count field is NOT a zero count. Never infer missing records
or unknown coverage from total_quantity=0, quantity=0 or null percentages.
Never describe zero matching controls as a defect-free period or an improvement.
Counts of boards are recorded occurrences, not unique physical boards. Sample is summed once
per control. Errors, affected, repaired and removed quantities are independent sums.
For Pareto or ranking defect codes, use get_defect_pareto with the same filters.
Select the requested metric; use removed_boards when unspecified. Use the returned
quantities, percentages and cumulative percentages, without computing them yourself.
Percentages are contributions to that metric, not defect rates. Null percentages
mean undefined because the total is zero. Never infer business causes from a ranking.
Interpret Pareto results using this decision table:
1. items is NON-EMPTY: defect records exist, even if total_quantity=0 and every
   item has quantity=0. Keep the observed codes and their zero quantities in a
   table. Explicitly acknowledge the existing defect records. For removed_boards,
   say 'Hi ha registres de defecte, però zero plaques retirades' when the total
   is zero (translate when needed). NEVER append a no-matching-records or
   unknown-coverage statement to this result. A non-empty zero Pareto is valid data.
2. items is EMPTY: call get_defect_summary with exactly the same filters before
   answering. If totals.control_count>0, controls exist without defect rows;
   report that distinction. Only totals.control_count=0 establishes no matching
   controls and requires the unknown-coverage wording above.
For a zero-total Pareto, percentage=null and cumulative_percentage=null mean
undefined shares, not 0%. If you show percentages, label them 'no definit';
you may omit percentages entirely. Do not turn absolute zero quantities into rates.
No defect rate, production denominator or job aggregation tool is available.
Do not calculate rates or invent manufacturing rules. Explain this limit for rate requests.
For removal explanations list the source rows with their job IDs and recorded quantities;
use the summary tool for the total. Do not invent job subtotals.
If a tool returns an error, correct arguments or ask the user; do not treat it as data.
Never execute SQL, code, writes or tools outside the provided list.
Before submitting a data answer, verify that its record-existence statements
agree with items/records and, if obtained, totals.control_count. Verify that zero
quantities remain visible and null percentages are never presented as numeric
percentages. Correct contradictions before responding; do not print this checklist.
When the user asked how many boards were made, explicitly state that total
production is unavailable before giving inspected-sample and defect quantities.
"""


async def execute_tool(name, arguments):
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
        return await TOOL_FUNCTIONS[name](**values)
    except (ValueError, TypeError) as exc:
        return {"error": "invalid_arguments", "message": str(exc)}


def _input_items(output):
    """Drop SDK-only parsed fields before reusing outputs as API input."""
    for item in output:
        if hasattr(item, "model_dump"):
            item = item.model_dump(mode="json", exclude_none=True)
        elif not isinstance(item, dict):
            item = vars(item)
        item = deepcopy(item)
        item.pop("parsed_arguments", None)
        for part in item.get("content", []):
            if isinstance(part, dict):
                part.pop("parsed", None)
        yield item


async def _run_agent(query, *, client=None, model="gpt-4o-mini", today=None,
                     max_rounds=8, on_event=None, message_history=None, costs):
    """Return answer, tool trace and replayable message_history.

    Pass the previous result's message_history for follow-ups; without history
    a call starts a new conversation. Caller-provided history is not mutated.
    API/transport failures propagate; exhausting the loop raises RuntimeError.
    An injected async client belongs to the caller; internally created clients
    are closed on success, failure and cancellation.
    Supply an async on_event(dict) callback to enable streaming. Events are
    round_start, text_delta, tool_start, tool_end and completed. Text in a tool
    round is provisional; only the returned result is the completed answer.
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")
    if not isinstance(max_rounds, int) or max_rounds < 1:
        raise ValueError("max_rounds must be a positive integer")
    if message_history is not None and (
            not isinstance(message_history, list)
            or any(not isinstance(item, dict) for item in message_history)):
        raise ValueError("message_history must be a list of API input-item dictionaries")
    reference_date = date.today() if today is None else date.fromisoformat(today)
    async with AsyncExitStack() as resources:
        if client is None:
            from openai import AsyncOpenAI
            client = await resources.enter_async_context(
                AsyncOpenAI(timeout=60.0, max_retries=1)
            )
        instructions = INSTRUCTIONS + "\nToday's date: " + reference_date.isoformat()
        messages = list(_input_items(message_history or []))
        messages.append({"role": "user", "content": query})
        trace = []
        for round_number in range(1, max_rounds + 1):
            options = dict(model=model, instructions=instructions, input=list(messages),
                           tools=TOOLS, store=False)
            with logfire.span("llm_call", **{
                "gen_ai.operation.name": "chat", "gen_ai.provider.name": "openai",
                "gen_ai.request.model": model, "round": round_number,
                "instructions": instructions, "input": options["input"],
            }) as model_span:
                try:
                    if on_event is None:
                        response = await client.responses.create(**options)
                    else:
                        await on_event({"type": "round_start", "round": round_number})
                        async with client.responses.stream(**options) as stream:
                            async for event in stream:
                                if event.type == "response.output_text.delta":
                                    await on_event({"type": "text_delta", "delta": event.delta,
                                                    "round": round_number})
                            # The SDK assembles complete tool arguments and output items,
                            # including reasoning. Never execute argument fragments.
                            response = await stream.get_final_response()
                except BaseException:
                    costs.add(None)
                    current_session().add(None)
                    raise
                usage = getattr(response, "usage", None)
                costs.add(usage)
                current_session().add(usage)
                request_cost = CostAccumulator(model)
                request_cost.add(usage)
                annotate_usage(model_span, request_cost)
                model_span.set_attribute("response_id", getattr(response, "id", None))
                model_span.set_attribute("status", response.status)
                model_span.set_attribute("output", list(_input_items(response.output)))
                model_span.set_attribute("output_text", getattr(response, "output_text", ""))
            if response.status != "completed":
                raise RuntimeError("Model response did not complete: " + response.status)
            # Preserve all output items, including reasoning items, for subsequent calls.
            output_items = list(_input_items(response.output))
            messages.extend(output_items)
            calls = [item for item in response.output if item.type == "function_call"]
            if not calls:
                if not response.output_text.strip():
                    raise RuntimeError("Model returned neither tool calls nor an answer")
                if not any(item.get("role") == "assistant" for item in output_items):
                    messages.append({"role": "assistant", "content": response.output_text})
                result = {"answer": response.output_text, "tool_calls": trace,
                          "model": model, "reference_date": reference_date.isoformat(),
                          "message_history": deepcopy(messages),
                          "usage": costs.as_dict(), "trace_id": trace_id(),
                          "session_usage": current_session().as_dict()}
                if on_event is not None:
                    await on_event({"type": "completed", "result": result})
                return result
            for call in calls:
                if on_event is not None:
                    await on_event({"type": "tool_start", "call_id": call.call_id,
                                    "name": call.name, "arguments": call.arguments})
                with logfire.span("tool_call", tool_name=call.name,
                                  call_id=call.call_id, arguments=call.arguments) as tool_span:
                    result = await execute_tool(call.name, call.arguments)
                    tool_span.set_attribute("result", result)
                    if "error" in result:
                        tool_span.set_level("error")
                recorded_call = {"name": call.name, "arguments": call.arguments,
                                 "result": result}
                trace.append(recorded_call)
                if on_event is not None:
                    await on_event({"type": "tool_end", "call_id": call.call_id,
                                    "call": recorded_call})
                messages.append({"type": "function_call_output", "call_id": call.call_id,
                                 "output": json.dumps(result, ensure_ascii=False)})
        raise RuntimeError("Agent exceeded max_rounds without a final answer")


async def run_agent(query, *, client=None, model="gpt-4o-mini", today=None,
                    max_rounds=8, on_event=None, message_history=None):
    """Run a monitored query; optionally group turns with monitoring_session().

    Returns the answer, tool calls, replayable history, trace_id, per-run usage
    and cumulative session_usage. Streaming and non-streaming share accounting.
    """
    with ExitStack() as scopes:
        if current_session() is None:
            scopes.enter_context(monitoring_session(model))
        elif current_session().model != model:
            raise ValueError("All turns in a monitoring session must use the same model")
        costs = CostAccumulator(model)
        with logfire.span("agent_run", model=model, query=query) as span:
            try:
                result = await _run_agent(
                    query, client=client, model=model, today=today,
                    max_rounds=max_rounds, on_event=on_event,
                    message_history=message_history, costs=costs,
                )
                span.set_attribute("answer", result["answer"])
                return result
            finally:
                annotate_usage(span, costs)
