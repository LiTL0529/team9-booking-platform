from pathlib import Path

from platform_common.app_factory import create_service_app
from platform_common.config import ServiceSettings

from .api import router
from .inbox import build_handlers

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"


class Settings(ServiceSettings):
    service_name: str = "notification-service"
    notification_processing_delay_ms: int = 0


def create_app(settings: Settings | None = None, **overrides):
    settings = settings or Settings()
    return create_service_app(
        settings=settings,
        title="Notification Service",
        description="Booking confirmations and cancellations in each customer's in-app inbox.",
        routers=[router],
        migrations_dir=MIGRATIONS,
        event_handlers=build_handlers(settings.notification_processing_delay_ms),
        **overrides,
    )
