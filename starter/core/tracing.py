"""Tracing: OpenTelemetry spans written as JSON lines, secrets redacted. No collector needed.

Every finished span becomes one dict (name, trace_id, span_id, parent_id, start, end, status,
error, attributes). The app sets EXPORTER.echo, so a server prints each span to stdout, where
Cloud Run logs it. collect() hands a caller every span of its own trace: the agent loop uses it
to give each case run its spans, which run_cases writes to ANSWERS/<case>/spans.jsonl.
"""

import json
import re
import sys
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager

from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult

SECRET_KEY = re.compile(r"api[_-]?key|token|password|secret", re.IGNORECASE)
SECRET_VALUE = re.compile(r"sk-ant-[A-Za-z0-9_-]*")
REDACTED = "[REDACTED]"


def redact(value):
    """A copy with every secret-named key's value, and every sk-ant- key, replaced."""
    if isinstance(value, dict):
        return {k: REDACTED if SECRET_KEY.search(str(k)) else redact(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return SECRET_VALUE.sub(REDACTED, value)
    return value


def span_dict(span: ReadableSpan) -> dict:
    return {
        "name": span.name,
        "trace_id": trace.format_trace_id(span.context.trace_id),
        "span_id": trace.format_span_id(span.context.span_id),
        "parent_id": trace.format_span_id(span.parent.span_id) if span.parent else None,
        "start": span.start_time / 1e9,
        "end": span.end_time / 1e9,
        "status": "ERROR" if span.status.status_code.name == "ERROR" else "OK",
        "error": redact(span.status.description),
        "attributes": redact(dict(span.attributes or {})),
    }


class JsonLinesExporter(SpanExporter):
    def __init__(self):
        self.echo = False  # print each span to stdout; the app turns it on
        self.collecting: dict[str, list[dict]] = {}  # trace id -> where its spans go
        self.lock = threading.Lock()

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        with self.lock:
            for span in spans:
                line = span_dict(span)
                if self.echo:
                    print(json.dumps(line), file=sys.stdout, flush=True)
                if (sink := self.collecting.get(line["trace_id"])) is not None:
                    sink.append(line)
        return SpanExportResult.SUCCESS


EXPORTER = JsonLinesExporter()
_provider = TracerProvider()  # ours alone, not the global one: libraries' spans stay out
_provider.add_span_processor(SimpleSpanProcessor(EXPORTER))
tracer = _provider.get_tracer("starter")


@contextmanager
def collect(name: str, **attributes) -> Iterator[tuple[str, list[dict]]]:
    """Run the block inside span `name`; yield (trace id, list). After the block, the list holds
    every span of that trace that ended inside it, this one included."""
    spans: list[dict] = []
    trace_id = ""
    try:
        with tracer.start_as_current_span(name, attributes=attributes) as span:
            trace_id = trace.format_trace_id(span.get_span_context().trace_id)
            EXPORTER.collecting[trace_id] = spans
            yield trace_id, spans
    finally:  # the span has ended and been exported by now
        EXPORTER.collecting.pop(trace_id, None)
