from pathlib import Path

from platform_common.app_factory import create_service_app
from platform_common.config import ServiceSettings

from .api import resources, slots

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"


class Settings(ServiceSettings):
    service_name: str = "catalogue-service"


def create_app(settings: Settings | None = None, **overrides):
    return create_service_app(
        settings=settings or Settings(),
        title="Catalogue Service",
        description="Merchant resources and publication of fixed one-hour time slots.",
        routers=[resources, slots],
        migrations_dir=MIGRATIONS,
        publishes_events=True,
        **overrides,
    )
