"""Builds a FastAPI service with the platform's cross-cutting behaviour already wired in.

A new service only supplies its routers, migrations and event handlers.
"""

from __future__ import annotations

import logging
import socket
import time
import uuid
from collections.abc import Callable, Iterable, Iterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from .auth import TokenVerifier
from .config import ServiceSettings
from .db import Database, run_migrations
from .errors import register_error_handlers
from .messaging import EventHandler, EventProcessor, InMemoryPublisher, Publisher, SnsPublisher, SqsConsumer
from .observability import configure_logging, configure_tracing
from .outbox import OutboxRelay

log = logging.getLogger(__name__)
HOSTNAME = socket.gethostname()


def get_session(request: Request) -> Iterator[Session]:
    """FastAPI dependency yielding a session bound to the service's own database."""
    with request.app.state.db.session() as session:
        yield session


def create_service_app(
    *,
    settings: ServiceSettings,
    title: str,
    description: str,
    routers: Iterable[APIRouter],
    migrations_dir: Path,
    publishes_events: bool = False,
    event_handlers: dict[str, EventHandler] | None = None,
    verifier: TokenVerifier | None = None,
    publisher: Publisher | None = None,
    start_background: bool = True,
    on_startup: Callable[[FastAPI], None] | None = None,
    on_shutdown: Callable[[FastAPI], None] | None = None,
) -> FastAPI:
    configure_logging(settings.service_name, settings.log_level)
    db = Database(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        application_name=settings.service_name,
    )

    if publisher is None and publishes_events:
        publisher = (
            SnsPublisher(settings.publish_topic_arn, region=settings.aws_region, endpoint_url=settings.aws_endpoint_url)
            if settings.publish_topic_arn
            else InMemoryPublisher()
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if settings.run_migrations:
            applied = run_migrations(
                db.engine,
                migrations_dir,
                include_outbox=publishes_events,
                include_processed_events=bool(event_handlers),
            )
            if applied:
                log.info("migrations applied", extra={"migrations": applied})
        if publishes_events:
            app.state.relay = OutboxRelay(
                db,
                publisher,
                batch_size=settings.outbox_batch_size,
                poll_interval=settings.outbox_poll_interval_seconds,
            )
        if event_handlers:
            app.state.event_processor = EventProcessor(db, event_handlers, settings.service_name)
        if on_startup:
            on_startup(app)
        if start_background:
            if publishes_events:
                app.state.relay.start()
            if event_handlers and settings.consume_queue_url:
                app.state.consumer = SqsConsumer(
                    app.state.event_processor,
                    settings.consume_queue_url,
                    region=settings.aws_region,
                    endpoint_url=settings.aws_endpoint_url,
                    concurrency=settings.consumer_concurrency,
                    wait_seconds=settings.consumer_wait_seconds,
                )
                app.state.consumer.start()
        log.info("service started", extra={"host": HOSTNAME, "version": settings.service_version})
        yield
        if getattr(app.state, "consumer", None):
            app.state.consumer.stop()
        if publishes_events and start_background:
            app.state.relay.stop()
        if on_shutdown:
            on_shutdown(app)
        db.dispose()

    app = FastAPI(title=title, description=description, version=settings.service_version, lifespan=lifespan)
    app.state.settings = settings
    app.state.db = db
    app.state.publisher = publisher
    app.state.verifier = verifier or TokenVerifier(settings.jwks_url, settings.jwt_issuer, settings.jwt_audience)
    app.state.consumer = None
    register_error_handlers(app)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        response.headers["X-Served-By"] = HOSTNAME
        if not request.url.path.startswith("/health"):
            log.info(
                "request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                    "request_id": request_id,
                },
            )
        return response

    # Liveness is async on purpose: it answers on the event loop even when every worker thread is
    # busy with requests, so a saturated-but-working task is not mistaken for a dead one by the
    # load balancer (which would kill it and push its load onto the remaining tasks).
    @app.get("/health/live", include_in_schema=False)
    async def live():
        return {"status": "ok", "service": settings.service_name, "host": HOSTNAME}

    # Readiness checks the database; used for diagnostics and smoke tests, not for load balancing.
    @app.get("/health/ready", include_in_schema=False)
    def ready():
        if not db.ping():
            return JSONResponse({"status": "unavailable", "reason": "database"}, status_code=503)
        return {"status": "ok", "service": settings.service_name, "host": HOSTNAME}

    for router in routers:
        app.include_router(router)

    configure_tracing(app, settings, db.engine)
    return app
