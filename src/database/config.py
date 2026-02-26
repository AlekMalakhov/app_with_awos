"""Configuration module for database settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    """Pydantic Settings class for database configuration.

    Environment Variables:
        DATABASE_PATH: Path to SQLite database file (default: data/conversations.db)
    """

    model_config = SettingsConfigDict(env_prefix="", env_file=".env", extra="ignore")

    database_path: str = "data/conversations.db"
