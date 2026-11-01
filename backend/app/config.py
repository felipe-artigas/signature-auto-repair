from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Configuración leída exclusivamente desde variables de entorno / archivo .env."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    database_url: str = "sqlite:///./data/signature.db"

    # Orígenes permitidos para CORS (solo necesarios si el frontend se sirve desde otro origen).
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["http://localhost:5173"])
    public_base_url: str = "http://localhost:5173"

    # Sesiones administrativas
    session_cookie_name: str = "sar_session"
    csrf_cookie_name: str = "sar_csrf"
    session_ttl_hours: int = 12
    cookie_secure: bool = True

    # Token de un solo uso para crear la primera cuenta administrativa. Vacío = deshabilitado.
    admin_setup_token: str = ""

    # Clave para derivar hashes no reversibles (IP, tokens de conversación). Obligatoria en producción.
    secret_key: str = "dev-only-change-me"

    # Inteligencia artificial
    ai_mode: Literal["mock", "openai"] = "mock"
    openai_api_key: str = ""
    openai_model: str = "gpt-6.1-terra"
    openai_reasoning_effort: str = "low"
    openai_timeout_seconds: float = 45.0
    ai_max_output_tokens: int = 900
    ai_max_tool_rounds: int = 6
    ai_daily_request_budget: int = 1500
    ai_daily_token_budget: int = 2_000_000

    # Límites del asistente público
    chat_max_message_chars: int = 1000
    chat_max_messages_per_conversation: int = 80
    chat_max_tool_calls_per_conversation: int = 60

    # Límites generales
    max_request_body_bytes: int = 64 * 1024

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value):
        if isinstance(value, str):
            return [o.strip() for o in value.split(",") if o.strip()]
        return value

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def ai_enabled(self) -> bool:
        return self.ai_mode == "openai" and bool(self.openai_api_key)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if settings.is_production:
        if settings.secret_key == "dev-only-change-me" or len(settings.secret_key) < 32:
            raise RuntimeError("SECRET_KEY debe definirse con al menos 32 caracteres en producción.")
        if not settings.cookie_secure:
            raise RuntimeError("COOKIE_SECURE debe ser true en producción.")
    return settings
