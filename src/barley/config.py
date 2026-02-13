"""Configuration module for Barley API connection settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class BarleySettings(BaseSettings):
    """Pydantic Settings class for Barley API configuration.

    Environment Variables:
        BARLEY_ENABLED: Feature toggle (default: false)
        BARLEY_API_URL: Base URL for Barley API
        BARLEY_API_TOKEN: Bearer token for authentication
        BARLEY_TIMEOUT: Request timeout in seconds (default: 30)
    """

    model_config = SettingsConfigDict(env_prefix="BARLEY_")

    enabled: bool = False
    api_url: str
    api_token: str
    timeout: int = 30
    max_retries: int = 3
    project_name: str = ""
