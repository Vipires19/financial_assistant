from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = "development"
    database_url: str
    session_ttl_seconds: int = Field(default=604800, gt=0)
    session_cookie_name: str = "leozera_session"
    csrf_cookie_name: str = "leozera_csrf"
    cors_origins: str = "http://localhost:3000"
    frontend_origin: str = "http://localhost:3000"
    app_timezone: str = "America/Sao_Paulo"

    @property
    def allowed_origins(self) -> list[str]:
        origins = [item.strip() for item in self.cors_origins.split(",") if item.strip()]
        if self.frontend_origin.strip() and self.frontend_origin.strip() not in origins:
            origins.append(self.frontend_origin.strip())
        return origins

    @property
    def cookie_secure(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
