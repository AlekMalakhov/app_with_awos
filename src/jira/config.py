"""Configuration module for Jira API connection settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class JiraSettings(BaseSettings):
    """Pydantic Settings class for Jira API configuration.

    Environment Variables:
        JIRA_BASE_URL: Jira Cloud instance URL (e.g., https://company.atlassian.net)
        JIRA_USER_EMAIL: API user email
        JIRA_API_TOKEN: API token (from Atlassian account)
        JIRA_ISSUE_TYPES: Comma-separated issue types to process (default: "Story,Task")
        JIRA_MAX_RETRIES: Maximum retry attempts (default: 3)
        JIRA_PROJECT_KEY: Jira project key (e.g., "IGAL") - required if polling enabled
        JIRA_POLLING_ENABLED: Enable/disable polling service (default: false)
        JIRA_POLLING_INTERVAL_SECONDS: Polling interval in seconds (default: 300)
        JIRA_POLLING_LOOKBACK_DAYS: How far back to look for tickets (default: 7)
        JIRA_POLLING_MAX_FAILURES: Failures before adding ac-generation-failed label (default: 3)
    """

    model_config = SettingsConfigDict(env_prefix="JIRA_")

    base_url: str
    user_email: str
    api_token: str
    issue_types: str = "Story,Task"
    max_retries: int = 3

    # Polling configuration
    project_key: str = ""
    polling_enabled: bool = False
    polling_interval_seconds: int = 300
    polling_lookback_days: int = 7
    polling_max_failures: int = 3

    @property
    def issue_types_list(self) -> list[str]:
        """Parse the comma-separated issue_types string into a list.

        Returns:
            List of issue type strings with whitespace stripped.
        """
        return [t.strip() for t in self.issue_types.split(",")]
