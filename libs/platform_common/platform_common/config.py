from pydantic_settings import BaseSettings, SettingsConfigDict


class ServiceSettings(BaseSettings):
    """Twelve-factor configuration: every value comes from the environment."""

    model_config = SettingsConfigDict(extra="ignore")

    service_name: str = "service"
    service_version: str = "dev"
    environment: str = "local"
    log_level: str = "INFO"

    # Database (one database and one login per service)
    database_url: str = ""
    db_pool_size: int = 5
    db_max_overflow: int = 5
    run_migrations: bool = True

    # Authentication: Cognito in AWS, the dev-auth stand-in locally
    jwt_issuer: str = "http://dev-auth:8000"
    jwt_audience: str | None = None
    jwks_url: str = "http://dev-auth:8000/.well-known/jwks.json"

    # Messaging: SNS topic the service publishes to, SQS queue it consumes from
    aws_region: str = "ap-southeast-1"
    aws_endpoint_url: str | None = None
    publish_topic_arn: str | None = None
    consume_queue_url: str | None = None
    consumer_concurrency: int = 1
    consumer_wait_seconds: int = 20  # SQS long polling; use 1 against moto, which blocks on long polls
    outbox_poll_interval_seconds: float = 0.2
    outbox_batch_size: int = 100

    # Observability
    otel_enabled: bool = False
    otel_exporter_otlp_endpoint: str = "http://jaeger:4318"
    otel_id_generator: str = "random"  # "xray" in AWS so traces show up in X-Ray
