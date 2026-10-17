from pathlib import Path

from platform_common.app_factory import create_service_app
from platform_common.resilience import ResilientClient

from .api import router
from .config import Settings
from .domain import CatalogueClient, on_slot_published

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"


def create_app(settings: Settings | None = None, *, catalogue: CatalogueClient | None = None, **overrides):
    settings = settings or Settings()
    app = create_service_app(
        settings=settings,
        title="Booking Service",
        description="Slot inventory, booking creation and cancellation with idempotency keys.",
        routers=[router],
        migrations_dir=MIGRATIONS,
        publishes_events=True,
        event_handlers={"SlotPublished": on_slot_published},
        **overrides,
    )
    app.state.catalogue = catalogue or CatalogueClient(
        ResilientClient(
            settings.catalogue_url,
            name="catalogue",
            timeout=settings.catalogue_timeout_seconds,
            attempts=2,
            failure_threshold=5,
            reset_timeout=15,
        )
    )
    return app
