"""Opt-in PydanticAI runtime with the application's existing result/event contract."""
import json
from contextlib import AsyncExitStack, ExitStack
from copy import deepcopy
from dataclasses import dataclass
from datetime import date
from typing import Literal

import logfire
from pydantic_ai import Agent, ModelRetry, RunContext, Tool
from pydantic_ai.capabilities import Instrumentation
from pydantic_ai.messages import (
    FunctionToolCallEvent, FunctionToolResultEvent, ModelMessagesTypeAdapter,
    ModelRequest, ModelResponse, TextPart, ToolReturnPart, UserPromptPart,
)
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import UsageLimits

from . import tools
from .cost_tracker import CostAccumulator
from .instructions import INSTRUCTIONS
from .monitoring import annotate_usage, current_session, monitoring_session, trace_id


@dataclass
class ReportingDeps:
    reference_date: date


async def _retrieve(function, **arguments):
    try:
        return await function(**arguments)
    except ValueError as exc:
        raise ModelRetry(str(exc)) from exc


async def get_defect_summary(section: str | None, date_from: str | None,
                             date_to: str | None) -> dict:
    """Retrieve deterministic totals, filters, source and metric semantics.

    Use for counts and summaries. Dates are inclusive ISO YYYY-MM-DD;
    null means an explicitly requested unrestricted filter.
    """
    return await _retrieve(tools.get_defect_summary, section=section,
                           date_from=date_from, date_to=date_to)


async def get_defect_detail(section: str | None, date_from: str | None,
                            date_to: str | None) -> dict:
    """Retrieve original controls and defect rows, including healthy controls.

    Use for supporting job/control/record IDs, not summary-only requests.
    Dates are inclusive ISO YYYY-MM-DD; null means unrestricted.
    """
    return await _retrieve(tools.get_defect_detail, section=section,
                           date_from=date_from, date_to=date_to)


async def get_defect_pareto(section: str | None, date_from: str | None,
                           date_to: str | None,
                           metric: Literal['errors', 'affected_boards',
                                           'repaired_boards', 'removed_boards']) -> dict:
    """Rank defect codes by metric; default interpretation is removed_boards.

    Quantities are recorded occurrences, not unique boards. Shares are not
    defect rates or causes. Zero totals have null shares; retain zero rows.
    If items is empty, call get_defect_summary with the same filters before
    answering: Pareto alone cannot establish whether controls exist.
    Dates are inclusive ISO YYYY-MM-DD; null means unrestricted.
    """
    return await _retrieve(tools.get_defect_pareto, section=section,
                           date_from=date_from, date_to=date_to, metric=metric)


def create_agent():
    agent = Agent(
        deps_type=ReportingDeps, output_type=str, instructions=INSTRUCTIONS,
        tools=[Tool(function, strict=True, sequential=True) for function in (
            get_defect_summary, get_defect_detail, get_defect_pareto)],
        retries=2, capabilities=[Instrumentation()], name="industrial_reporting",
    )

    @agent.instructions
    def reference_date(ctx: RunContext[ReportingDeps]) -> str:
        return "Today's date: " + ctx.deps.reference_date.isoformat()

    @agent.output_validator
    def require_source(ctx: RunContext[ReportingDeps], answer: str) -> str:
        # Check only evidence retrieved in this turn; clarification has no data.
        sources = set()
        for message in reversed(ctx.messages):
            if any(isinstance(part, UserPromptPart) for part in message.parts):
                break
            for part in message.parts:
                if isinstance(part, ToolReturnPart) and isinstance(part.content, dict):
                    dataset = part.content.get("source", {}).get("dataset_id")
                    if dataset:
                        sources.add(dataset)
        missing = sorted(dataset for dataset in sources if dataset not in answer)
        if missing:
            raise ModelRetry("Include the source dataset_id in the answer: " + ", ".join(missing))
        return answer

    return agent


def _history(items):
    """Accept native serialized history plus the UI's plain failed-turn messages."""
    if items is None:
        return []
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise ValueError("message_history must be a list of dictionaries")
    messages = []
    for item in deepcopy(items):
        if item.get('kind') in ('request', 'response'):
            messages.extend(ModelMessagesTypeAdapter.validate_python([item]))
        elif item.get('role') == 'user' and isinstance(item.get('content'), str):
            messages.append(ModelRequest(parts=[UserPromptPart(item['content'])]))
        elif item.get('role') == 'assistant' and isinstance(item.get('content'), str):
            messages.append(ModelResponse(parts=[TextPart(item['content'])]))
        else:
            raise ValueError("Incompatible history: clear the conversation when changing backend")
    return messages


async def run_agent(query, *, client=None, model="gpt-4o-mini", today=None,
                    max_rounds=8, on_event=None, message_history=None):
    """Match run_agent's UI contract; history uses PydanticAI's native JSON format.

    `model` also accepts a PydanticAI Model for offline tests. Injected clients
    belong to the caller. Internally created clients close on all exit paths.
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")
    if not isinstance(max_rounds, int) or isinstance(max_rounds, bool) or max_rounds < 1:
        raise ValueError("max_rounds must be a positive integer")
    reference_date = date.today() if today is None else date.fromisoformat(today)
    history = _history(message_history)
    model_name = model.model_name if isinstance(model, Model) else model
    costs = CostAccumulator(model_name)
    trace = []
    round_number = 0
    request_pending = False

    async def emit(event):
        if on_event is not None:
            await on_event(event)

    with ExitStack() as scopes:
        if current_session() is None:
            scopes.enter_context(monitoring_session(model_name))
        elif current_session().model != model_name:
            raise ValueError("All turns in a monitoring session must use the same model")
        with logfire.span("agent_run", model=model_name, query=query) as span:
            try:
                async with AsyncExitStack() as resources:
                    if isinstance(model, Model):
                        runtime_model = model
                    else:
                        if client is None:
                            from openai import AsyncOpenAI
                            client = await resources.enter_async_context(
                                AsyncOpenAI(timeout=60.0, max_retries=1))
                        runtime_model = OpenAIResponsesModel(
                            model.removeprefix('openai:'),
                            provider=OpenAIProvider(openai_client=client))
                    async with create_agent().iter(
                        query, model=runtime_model, deps=ReportingDeps(reference_date),
                        message_history=history, model_settings={"openai_store": False},
                        usage_limits=UsageLimits(request_limit=max_rounds),
                    ) as run:
                        async for node in run:
                            if Agent.is_model_request_node(node):
                                # Enforce before streaming too: no extra paid request.
                                if round_number >= max_rounds:
                                    raise RuntimeError("Agent exceeded max_rounds without a final answer")
                                round_number += 1
                                request_pending = True
                                await emit({"type": "round_start", "round": round_number})
                                if on_event is not None:
                                    async with node.stream(run.ctx) as stream:
                                        async for text in stream.stream_text(delta=True, debounce_by=None):
                                            await emit({"type": "text_delta", "delta": text,
                                                        "round": round_number})
                            elif Agent.is_call_tools_node(node):
                                costs.add(node.model_response.usage)
                                current_session().add(node.model_response.usage)
                                request_pending = False
                                async with node.stream(run.ctx) as events:
                                    for_calls = {}
                                    async for event in events:
                                        if isinstance(event, FunctionToolCallEvent):
                                            part = event.part
                                            for_calls[part.tool_call_id] = part.args_as_json_str()
                                            await emit({"type": "tool_start", "call_id": part.tool_call_id,
                                                        "name": part.tool_name,
                                                        "arguments": part.args_as_json_str()})
                                        elif isinstance(event, FunctionToolResultEvent):
                                            part = event.part
                                            recorded = {"name": part.tool_name,
                                                        "arguments": for_calls.get(part.tool_call_id, '{}'),
                                                        "result": (part.content if part.outcome == 'success'
                                                                   else {"error": "invalid_arguments",
                                                                         "message": str(part.content)})}
                                            trace.append(recorded)
                                            await emit({"type": "tool_end", "call_id": part.tool_call_id,
                                                        "call": recorded})
                        answer = run.result.output
                        if not answer.strip():
                            raise RuntimeError("Model returned an empty answer")
                        result = {"answer": answer, "tool_calls": trace, "model": model_name,
                                  "reference_date": reference_date.isoformat(),
                                  "message_history": json.loads(run.result.all_messages_json()),
                                  "usage": costs.as_dict(), "trace_id": trace_id(),
                                  "session_usage": current_session().as_dict()}
                        span.set_attribute("answer", answer)
                        await emit({"type": "completed", "result": result})
                        return result
            finally:
                if request_pending:
                    costs.add(None)
                    current_session().add(None)
                annotate_usage(span, costs)
