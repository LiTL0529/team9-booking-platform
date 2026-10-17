from platform_common.config import ServiceSettings


class Settings(ServiceSettings):
    service_name: str = "merchant-service"
    # Where merchant roles are written so they travel as token claims: "dev" or "cognito"
    identity_provider: str = "dev"
    dev_auth_url: str = "http://dev-auth:8000"
    dev_auth_admin_secret: str = ""
    cognito_user_pool_id: str | None = None
