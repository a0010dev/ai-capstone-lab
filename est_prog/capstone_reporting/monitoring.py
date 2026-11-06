"""Logfire/OpenTelemetry spans for the custom Responses API agent loop."""
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

import logfire
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.trace import get_current_span

from .cost_tracker import CostAccumulator

_current_session = ContextVar("reporting_monitoring_session", default=None)
_configured = False


class JsonlSpanExporter(SpanExporter):
    """Optional local trace artifact, using OpenTelemetry's standard JSON format."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def export(self, spans):
        with self.path.open("a") as output:
            for span in spans:
                if span.attributes.get("logfire.span_type") != "pending_span":
                    output.write(span.to_json(indent=None) + "\n")
        return SpanExportResult.SUCCESS


def configure_monitoring(*, trace_file=None, send_to_logfire="if-token-present",
                         additional_span_processors=()):
    global _configured
    processors = list(additional_span_processors)
    if trace_file is not None:
        processors.append(SimpleSpanProcessor(JsonlSpanExporter(trace_file)))
    logfire.configure(
        service_name="industrial-reporting-agent", send_to_logfire=send_to_logfire,
        console=False, inspect_arguments=False, additional_span_processors=processors,
    )
    _configured = True


def current_session():
    return _current_session.get()


def trace_id():
    return format(get_current_span().get_span_context().trace_id, "032x")


def annotate_usage(span, costs):
    for key, value in costs.as_dict().items():
        span.set_attribute(key, value)
    span.set_attribute("gen_ai.usage.input_tokens", costs.input_tokens)
    span.set_attribute("gen_ai.usage.output_tokens", costs.output_tokens)


@contextmanager
def monitoring_session(model="gpt-4o-mini"):
    """Wrap multiple awaited turns here to share one trace and cost accumulator.

    Without an explicit session, run_agent creates a session for its single query.
    A session uses one model. Usage is added once per returned API response,
    including responses received before a later failure. Failed requests without
    returned usage cannot be costed and are marked as missing usage.
    """
    if not _configured:
        configure_monitoring()
    costs = CostAccumulator(model)
    with logfire.span("reporting_session", model=model) as span:
        token = _current_session.set(costs)
        try:
            yield costs
        finally:
            annotate_usage(span, costs)
            _current_session.reset(token)
