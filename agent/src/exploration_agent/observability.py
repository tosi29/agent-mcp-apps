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

_configured = False
logger = logging.getLogger(__name__)


def configure_observability() -> None:
    global _configured
    logging.disable(logging.NOTSET)
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.__stderr__,
    )
    logging.getLogger().setLevel(os.environ.get("LOG_LEVEL", "INFO"))
    if _configured:
        return
    _configured = True
    # Preserve providers already configured by opentelemetry-instrument/ADOT.
    if isinstance(trace.get_tracer_provider(), TracerProvider):
        return
    resource = Resource.create({"service.name": "exploration-agent"})
    tracer = TracerProvider(resource=resource)
    # Keep background/shutdown exporters attached to the process stderr, rather than
    # a temporary capture stream that a test runner or embedding caller may close.
    tracer.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter(out=sys.__stderr__)))
    trace.set_tracer_provider(tracer)
    metrics.set_meter_provider(
        MeterProvider(
            resource=resource,
            metric_readers=[
                PeriodicExportingMetricReader(ConsoleMetricExporter(out=sys.__stderr__))
            ],
        )
    )
    logs = LoggerProvider(resource=resource)
    logs.add_log_record_processor(
        SimpleLogRecordProcessor(ConsoleLogRecordExporter(out=sys.__stderr__))
    )
    _logs.set_logger_provider(logs)
    logging.getLogger().addHandler(LoggingHandler(logger_provider=logs))


def log_callback(**event) -> None:
    """Emit Strands callback output on stderr, keeping CLI JSON/SSE valid on stdout."""
    if isinstance(event.get("data"), str):
        logger.info("model_output %s", event["data"])
    if event.get("current_tool_use"):
        logger.info("tool_use %s", event["current_tool_use"])
