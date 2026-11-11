"""Local console exporters; AgentCore exporters are configured by the ADOT launcher."""

import logging
import os
import sys

from opentelemetry import _logs, metrics, trace
from opentelemetry.instrumentation.logging.handler import LoggingHandler
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import ConsoleLogRecordExporter, SimpleLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import ConsoleMetricExporter, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor


def configure_observability() -> None:
    logging.disable(logging.NOTSET)
    # The original process stderr is None only when Python starts without one.
    stderr = sys.__stderr__ or sys.stderr
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=stderr,
    )
    logging.getLogger().setLevel(os.environ.get("LOG_LEVEL", "INFO"))
    # Preserve providers already configured by opentelemetry-instrument/ADOT or an earlier call.
    if isinstance(trace.get_tracer_provider(), TracerProvider):
        return
    resource = Resource.create({"service.name": "exploration-mcp"})
    tracer = TracerProvider(resource=resource)
    # Background/shutdown exporters must not retain temporary capture streams.
    tracer.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter(out=stderr)))
    trace.set_tracer_provider(tracer)
    metrics.set_meter_provider(
        MeterProvider(
            resource=resource,
            metric_readers=[PeriodicExportingMetricReader(ConsoleMetricExporter(out=stderr))],
        )
    )
    logs = LoggerProvider(resource=resource)
    logs.add_log_record_processor(SimpleLogRecordProcessor(ConsoleLogRecordExporter(out=stderr)))
    _logs.set_logger_provider(logs)
    logging.getLogger().addHandler(LoggingHandler(logger_provider=logs))
