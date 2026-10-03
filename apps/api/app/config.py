from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Stockcast API"
    env: str = "development"
    database_url: str = "postgresql+psycopg://stockcast:stockcast@localhost:5432/stockcast"
    redis_url: str = "redis://localhost:6379/0"
    cors_origins: str = "http://localhost:3000"
    # Fernet key for encrypting channel credentials. Generate with:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    credentials_key: str = "dev-only-key-replace-me-8chars-xxxxxxxxxxxxxxx="


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
