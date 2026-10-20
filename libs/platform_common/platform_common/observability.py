"""Structured JSON logs to standard output and OpenTelemetry tracing.

Locally traces go to Jaeger; in AWS the ADOT collector sidecar forwards them to X-Ray,
and the awslogs driver ships standard output to CloudWatch Logs.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime

from opentelemetry import trace

_RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def __init__(self, service_name: str):
        super().__init__()
        self._service = service_name

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "service": self._service,
            "logger": record.name,
            "message": record.getMessage(),
        }
        span = trace.get_current_span().get_span_context()
        if span.is_valid:
            entry["trace_id"] = format(span.trace_id, "032x")
            entry["span_id"] = format(span.span_id, "016x")
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                entry[key] = value
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def configure_logging(service_name: str, level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service_name))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    for noisy in ("botocore", "boto3", "urllib3", "httpx", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


_tracing_configured = False


def configure_aws_propagation() -> None:
    """Continue API Gateway's X-Ray parent, retaining W3C context for local clients."""
    from opentelemetry.baggage.propagation import W3CBaggagePropagator
    from opentelemetry.propagate import set_global_textmap
    from opentelemetry.propagators.aws import AwsXRayPropagator
    from opentelemetry.propagators.composite import CompositePropagator
    from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

    # The gateway's X-Ray context is authoritative when both formats arrive.
    set_global_textmap(CompositePropagator([
        TraceContextTextMapPropagator(), W3CBaggagePropagator(), AwsXRayPropagator(),
    ]))


def configure_tracing(app, settings, engine) -> None:
    global _tracing_configured
    if not settings.otel_enabled or _tracing_configured:
        return
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    kwargs = {}
    if settings.otel_id_generator == "xray":
        from opentelemetry.sdk.extension.aws.trace import AwsXRayIdGenerator

        configure_aws_propagation()
        kwargs["id_generator"] = AwsXRayIdGenerator()
    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": settings.service_name,
                "service.version": settings.service_version,
                "deployment.environment": settings.environment,
            }
        ),
        **kwargs,
    )
    endpoint = settings.otel_exporter_otlp_endpoint.rstrip("/") + "/v1/traces"
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app, excluded_urls="health/.*")
    SQLAlchemyInstrumentor().instrument(engine=engine)
    HTTPXClientInstrumentor().instrument()
    _tracing_configured = True
