from pathlib import Path

from platform_common.app_factory import create_service_app
from platform_common.config import ServiceSettings

from .api import router
from .cache import AvailabilityCache
from .projections import build_handlers

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"


class Settings(ServiceSettings):
    service_name: str = "availability-service"
    redis_url: str | None = None
    cache_ttl_seconds: int = 30
    cross_merchant_cache_ttl_seconds: int = 5


def create_app(settings: Settings | None = None, *, cache: AvailabilityCache | None = None, **overrides):
    settings = settings or Settings()
    cache = cache or AvailabilityCache(
        settings.redis_url, settings.cache_ttl_seconds, settings.cross_merchant_cache_ttl_seconds
    )
    app = create_service_app(
        settings=settings,
        title="Availability Service",
        description="Slot search across merchants from an event-built read model with a cache.",
        routers=[router],
        migrations_dir=MIGRATIONS,
        event_handlers=build_handlers(cache),
        **overrides,
    )
    app.state.cache = cache
    return app
