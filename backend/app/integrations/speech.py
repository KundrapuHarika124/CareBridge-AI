"""Speech provider. The backend only issues short-lived tokens; audio never passes through it.

The browser uses the token to talk to the speech service directly, so the subscription key
stays on the server and no audio is stored by this application.
"""
import logging

import httpx

from app.core.config import get_settings

log = logging.getLogger("carebridge.speech")


class SpeechUnavailable(Exception):
    pass


class NoneSpeech:
    name = "none"
    available = False

    def issue_token(self) -> dict:
        raise SpeechUnavailable("No speech provider is configured")


class MockSpeech(NoneSpeech):
    """Development and tests only. The token is not usable with any real service."""

    name = "mock"
    available = True

    def issue_token(self) -> dict:
        return {"token": "mock-token-not-valid", "region": "mock", "expires_in": 540, "provider": "mock"}


class AzureSpeech:
    name = "azure"
    available = True

    def __init__(self, key: str, region: str):
        self._key = key
        self._region = region

    def issue_token(self) -> dict:
        url = f"https://{self._region}.api.cognitive.microsoft.com/sts/v1.0/issueToken"
        try:
            response = httpx.post(url, headers={"Ocp-Apim-Subscription-Key": self._key}, timeout=6.0)
        except httpx.HTTPError as exc:
            log.warning("speech_token_failed", extra={"reason": type(exc).__name__})
            raise SpeechUnavailable("network error")
        if response.status_code != 200:
            log.warning("speech_token_failed", extra={"reason": f"status {response.status_code}"})
            raise SpeechUnavailable(f"provider returned status {response.status_code}")
        # Azure tokens are valid for 10 minutes; tell the client to renew a little earlier.
        return {"token": response.text, "region": self._region, "expires_in": 540, "provider": "azure"}


_instance = None


def get_speech():
    global _instance
    if _instance is None:
        settings = get_settings()
        if settings.speech_provider == "azure":
            _instance = AzureSpeech(settings.azure_speech_key, settings.azure_speech_region)
        elif settings.speech_provider == "mock" and not settings.is_production:
            _instance = MockSpeech()
        else:
            _instance = NoneSpeech()
    return _instance


def set_speech(provider) -> None:
    global _instance
    _instance = provider
