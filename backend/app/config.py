from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./data/leadengine360.db"
    jwt_secret: str = "local-development-secret-change-before-deploy"
    openrouter_api_key: str | None = None
    openrouter_model: str = "google/gemini-2.5-flash"
    upload_dir: str = "./data/uploads"
    max_upload_mb: int = 20
    frontend_origin: str = "http://localhost:3000"
    redis_url: str = "redis://localhost:6379/0"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
