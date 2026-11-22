"""Application settings, read from environment variables (or backend/.env)."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"  # development | test | production
    database_url: str
    jwt_secret_key: str
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    password_reset_expire_minutes: int = 30
    email_provider: str = "none"  # none | mock
    cors_origins: str = "http://localhost:5173"
    log_level: str = "INFO"
    run_jobs: bool = True

    llm_provider: str = "none"  # none | gemini | mock
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.1-flash-lite"

    speech_provider: str = "none"  # none | azure | mock
    azure_speech_key: str = ""
    azure_speech_region: str = ""

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def sqlalchemy_url(self) -> str:
        url = self.database_url
        for prefix in ("postgresql://", "postgres://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix):]
        return url

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def validate_runtime(self) -> None:
        """Fail fast on unsafe configuration."""
        if len(self.jwt_secret_key) < 32:
            raise RuntimeError("JWT_SECRET_KEY must be at least 32 characters long")
        if self.is_production and "mock" in (self.llm_provider, self.speech_provider):
            raise RuntimeError("Mock providers are not allowed when APP_ENV=production")
        if self.llm_provider == "gemini" and not self.gemini_api_key:
            raise RuntimeError("LLM_PROVIDER=gemini requires GEMINI_API_KEY")
        if self.speech_provider == "azure" and not (self.azure_speech_key and self.azure_speech_region):
            raise RuntimeError("SPEECH_PROVIDER=azure requires AZURE_SPEECH_KEY and AZURE_SPEECH_REGION")
        if self.email_provider not in ("none", "mock"):
            raise RuntimeError("EMAIL_PROVIDER must be none or mock")
        if self.is_production and self.email_provider == "mock":
            raise RuntimeError("Mock email provider is not allowed when APP_ENV=production")


@lru_cache
def get_settings() -> Settings:
    return Settings()
