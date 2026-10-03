from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Stockcast API"
    env: str = "development"
    database_url: str = "postgresql+psycopg://stockcast:stockcast@localhost:5432/stockcast"
    redis_url: str = "redis://localhost:6379/0"
    cors_origins: str = "http://localhost:3000"


settings = Settings()
