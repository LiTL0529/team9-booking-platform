from pathlib import Path

from platform_common.app_factory import create_service_app

from .api import router
from .config import Settings
from .identity import build_directory

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"


def create_app(settings: Settings | None = None, *, identity=None, **overrides):
    settings = settings or Settings()
    app = create_service_app(
        settings=settings,
        title="Merchant Service",
        description="Merchant onboarding, merchant users and roles.",
        routers=[router],
        migrations_dir=MIGRATIONS,
        publishes_events=True,
        **overrides,
    )
    app.state.identity = identity or build_directory(settings)
    return app
