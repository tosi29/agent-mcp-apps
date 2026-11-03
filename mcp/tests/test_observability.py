"""Exercise the standalone MCP package's local exporters without network access."""

import os
import subprocess
import sys
from pathlib import Path


def test_local_signals_use_stderr_without_network():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import io, logging, socket, sys
from opentelemetry import _logs, metrics, trace
from exploration_mcp.observability import configure_observability
def reject_network(*args, **kwargs):
    raise AssertionError('Local telemetry must not open a connection')
socket.socket.connect = reject_network
logging.disable(logging.CRITICAL)
temporary = io.StringIO()
sys.stderr = temporary
configure_observability()
configure_observability()
temporary.close()
sys.stderr = sys.__stderr__
with trace.get_tracer('test').start_as_current_span('local-span'):
    logging.getLogger('test').error('local-log')
metrics.get_meter('test').create_counter('local-counter').add(1)
metrics.get_meter_provider().force_flush()
_logs.get_logger_provider().force_flush()
print('{"type":"done"}')
""",
        ],
        env={**os.environ, "LOG_LEVEL": "INFO"},
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == '{"type":"done"}'
    for marker in ["local-span", "local-log", "local-counter", "exploration-mcp"]:
        assert marker in result.stderr
    assert result.stderr.count('"name": "local-span"') == 1


def test_instrumented_providers_are_preserved():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import logging
from opentelemetry import _logs, metrics, trace
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.trace import TracerProvider
from exploration_mcp.observability import configure_observability
tracer, meter, logs = TracerProvider(), MeterProvider(), LoggerProvider()
trace.set_tracer_provider(tracer)
metrics.set_meter_provider(meter)
_logs.set_logger_provider(logs)
logging.getLogger().addHandler(logging.NullHandler())
configure_observability()
assert trace.get_tracer_provider() is tracer
assert metrics.get_meter_provider() is meter
assert _logs.get_logger_provider() is logs
assert logging.getLogger().isEnabledFor(logging.INFO)
""",
        ],
        env={**os.environ, "LOG_LEVEL": "INFO"},
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr


def test_adot_launcher_initializes_without_external_export():
    result = subprocess.run(
        [
            str(Path(sys.executable).with_name("opentelemetry-instrument")),
            sys.executable,
            "-c",
            """
from opentelemetry import trace
from exploration_mcp.observability import configure_observability
from opentelemetry.sdk.trace import TracerProvider
provider = trace.get_tracer_provider()
assert isinstance(provider, TracerProvider)
configure_observability()
assert trace.get_tracer_provider() is provider
with trace.get_tracer('test').start_as_current_span('adot-startup-check'):
    pass
""",
        ],
        env={
            "PATH": os.environ["PATH"],
            "AWS_REGION": "ap-northeast-1",
            "AWS_EC2_METADATA_DISABLED": "true",
            "AGENT_OBSERVABILITY_ENABLED": "true",
            "OTEL_PYTHON_DISTRO": "aws_distro",
            "OTEL_PYTHON_CONFIGURATOR": "aws_configurator",
            "OTEL_TRACES_EXPORTER": "console",
            "OTEL_LOGS_EXPORTER": "console",
            "OTEL_METRICS_EXPORTER": "console",
            "OTEL_SERVICE_NAME": "instrumented-test",
        },
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "Failed to auto initialize" not in result.stderr
    assert "adot-startup-check" in result.stdout
