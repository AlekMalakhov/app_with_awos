"""Configuration module for AI service settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class AISettings(BaseSettings):
    """Pydantic Settings class for AI service configuration.

    Environment Variables:
        ANTHROPIC_API_KEY: Anthropic API key (empty string = AI disabled)
        AI_MODEL: Claude model to use (default: claude-sonnet-4-20250514)
        AI_MAX_TOKENS: Maximum tokens for AI response (default: 1024)
        AI_TEMPERATURE: Temperature for AI response (default: 0.3)
    """

    model_config = SettingsConfigDict(env_prefix="")

    anthropic_api_key: str = ""  # Empty string = AI disabled
    ai_model: str = "claude-sonnet-4-20250514"
    ai_max_tokens: int = 1024
    ai_temperature: float = 0.3

    @property
    def is_enabled(self) -> bool:
        """Check if AI is enabled based on API key presence.

        Returns:
            True if anthropic_api_key is set and non-empty, False otherwise.
        """
        return bool(self.anthropic_api_key)
