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

logger = logging.getLogger(__name__)


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
    resource = Resource.create({"service.name": "exploration-agent"})
    tracer = TracerProvider(resource=resource)
    # Keep background/shutdown exporters attached to the process stderr, rather than
    # a temporary capture stream that a test runner or embedding caller may close.
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


def log_callback(**event) -> None:
    """Emit Strands callback output through logging."""
    if isinstance(event.get("data"), str):
        logger.info("model_output %s", event["data"])
    if event.get("current_tool_use"):
        logger.info("tool_use %s", event["current_tool_use"])
