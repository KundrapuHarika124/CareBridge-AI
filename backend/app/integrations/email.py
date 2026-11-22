"""Password-reset email delivery interface."""
import logging

from app.core.config import get_settings

log = logging.getLogger("carebridge.email")


class EmailDeliveryUnavailable(Exception):
    pass


class NoneEmail:
    name = "none"
    available = False

    def send_password_reset(self, email: str, token: str) -> bool:
        # Deliberately do not send or expose the token when no provider is configured.
        return False


class MockEmail(NoneEmail):
    """Development/test provider that keeps delivery in memory, never in API/log output."""

    name = "mock"
    available = True

    def __init__(self):
        self.deliveries: list[dict[str, str]] = []

    def send_password_reset(self, email: str, token: str) -> bool:
        self.deliveries.append({"email": email, "token": token})
        return True

    def clear(self) -> None:
        self.deliveries.clear()


_instance = None


def get_email():
    global _instance
    if _instance is None:
        settings = get_settings()
        if settings.email_provider == "mock" and not settings.is_production:
            _instance = MockEmail()
        else:
            _instance = NoneEmail()
    return _instance


def set_email(provider) -> None:
    global _instance
    _instance = provider
