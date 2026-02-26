"""Configuration module for Slack API connection settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class SlackSettings(BaseSettings):
    """Pydantic Settings class for Slack API configuration.

    Environment Variables:
        SLACK_BOT_TOKEN: Bot OAuth token (starts with xoxb-)
        SLACK_APP_TOKEN: App-level token for Socket Mode (starts with xapp-)
        SLACK_SIGNING_SECRET: Secret for verifying webhook requests
        SLACK_MAX_RETRIES: Maximum retry attempts (default: 3)
        SLACK_SOCKET_MODE_ENABLED: Enable Socket Mode connection (default: True)
        SLACK_ESCALATION_CONTACT_EMAIL: Email of PO/DM for low-confidence escalation DMs (default: "amalakhov@provectus.com")
        SLACK_CONFIDENCE_THRESHOLD: ACs below this confidence score trigger escalation (default: 0.7)
    """

    model_config = SettingsConfigDict(env_prefix="SLACK_", env_file=".env", extra="ignore")

    bot_token: str
    app_token: str
    signing_secret: str = ""
    max_retries: int = 3
    socket_mode_enabled: bool = True
    escalation_contact_email: str | None = "amalakhov@provectus.com"
    confidence_threshold: float = 0.7
