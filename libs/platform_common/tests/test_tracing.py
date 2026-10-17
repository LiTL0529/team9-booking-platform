"""Tracing is switched on only in AWS, so exercise that code path here: a service built from the
template with OpenTelemetry enabled must still start and serve requests (an instrumentation that
does not support the installed FastAPI/Starlette would fail at startup or on the first request)."""

from pathlib import Path

from fastapi import APIRouter
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider

from platform_common.app_factory import create_service_app
from platform_common.config import ServiceSettings
from platform_common.testing import TestKeys


def test_service_serves_requests_with_tracing_enabled(tmp_path: Path):
    router = APIRouter()

    @router.get("/v1/ping")
    def ping():
        with trace.get_tracer("test").start_as_current_span("inside-handler"):
            return {"pong": True}

    settings = ServiceSettings(
        service_name="tracing-test",
        database_url=f"sqlite:///{tmp_path / 'unused.db'}",
        run_migrations=False,
        otel_enabled=True,
        otel_exporter_otlp_endpoint="http://127.0.0.1:9",  # nothing listens: export fails quietly
        otel_id_generator="xray",
    )
    app = create_service_app(
        settings=settings,
        title="tracing test",
        description="",
        routers=[router],
        migrations_dir=tmp_path,
        verifier=TestKeys().verifier,
        start_background=False,
    )
    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
        response = client.get("/v1/ping")
    assert response.status_code == 200
    assert response.json() == {"pong": True}
    provider = trace.get_tracer_provider()
    assert isinstance(provider, TracerProvider)
    provider.shutdown()  # stop the background exporter before the test run ends
