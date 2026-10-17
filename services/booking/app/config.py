from platform_common.config import ServiceSettings


class Settings(ServiceSettings):
    service_name: str = "booking-service"
    # Used only when a booking request arrives before the SlotPublished event (read-through).
    catalogue_url: str = "http://catalogue:8000"
    catalogue_timeout_seconds: float = 2.0
