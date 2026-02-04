"""Unit tests for Jira configuration settings."""

import pytest
from pydantic import ValidationError

from src.jira.config import JiraSettings


class TestJiraSettings:
    """Test suite for JiraSettings configuration class."""

    def test_valid_configuration(self, monkeypatch):
        """Test that all required env vars provided loads settings successfully."""
        monkeypatch.setenv("JIRA_BASE_URL", "https://test.atlassian.net")
        monkeypatch.setenv("JIRA_USER_EMAIL", "test@example.com")
        monkeypatch.setenv("JIRA_API_TOKEN", "test-token")

        settings = JiraSettings()

        assert settings.base_url == "https://test.atlassian.net"
        assert settings.user_email == "test@example.com"
        assert settings.api_token == "test-token"

    def test_missing_base_url_raises_validation_error(self, monkeypatch):
        """Test that missing JIRA_BASE_URL raises ValidationError."""
        monkeypatch.delenv("JIRA_BASE_URL", raising=False)
        monkeypatch.setenv("JIRA_USER_EMAIL", "test@example.com")
        monkeypatch.setenv("JIRA_API_TOKEN", "test-token")

        with pytest.raises(ValidationError) as exc_info:
            JiraSettings()

        errors = exc_info.value.errors()
        assert any(error["loc"] == ("base_url",) for error in errors)

    def test_missing_user_email_raises_validation_error(self, monkeypatch):
        """Test that missing JIRA_USER_EMAIL raises ValidationError."""
        monkeypatch.setenv("JIRA_BASE_URL", "https://test.atlassian.net")
        monkeypatch.delenv("JIRA_USER_EMAIL", raising=False)
        monkeypatch.setenv("JIRA_API_TOKEN", "test-token")

        with pytest.raises(ValidationError) as exc_info:
            JiraSettings()

        errors = exc_info.value.errors()
        assert any(error["loc"] == ("user_email",) for error in errors)

    def test_missing_api_token_raises_validation_error(self, monkeypatch):
        """Test that missing JIRA_API_TOKEN raises ValidationError."""
        monkeypatch.setenv("JIRA_BASE_URL", "https://test.atlassian.net")
        monkeypatch.setenv("JIRA_USER_EMAIL", "test@example.com")
        monkeypatch.delenv("JIRA_API_TOKEN", raising=False)

        with pytest.raises(ValidationError) as exc_info:
            JiraSettings()

        errors = exc_info.value.errors()
        assert any(error["loc"] == ("api_token",) for error in errors)

    def test_default_issue_types(self, monkeypatch):
        """Test that issue_types defaults to 'Story,Task' when not set."""
        monkeypatch.setenv("JIRA_BASE_URL", "https://test.atlassian.net")
        monkeypatch.setenv("JIRA_USER_EMAIL", "test@example.com")
        monkeypatch.setenv("JIRA_API_TOKEN", "test-token")
        monkeypatch.delenv("JIRA_ISSUE_TYPES", raising=False)

        settings = JiraSettings()

        assert settings.issue_types == "Story,Task"

    def test_default_max_retries(self, monkeypatch):
        """Test that max_retries defaults to 3 when not set."""
        monkeypatch.setenv("JIRA_BASE_URL", "https://test.atlassian.net")
        monkeypatch.setenv("JIRA_USER_EMAIL", "test@example.com")
        monkeypatch.setenv("JIRA_API_TOKEN", "test-token")
        monkeypatch.delenv("JIRA_MAX_RETRIES", raising=False)

        settings = JiraSettings()

        assert settings.max_retries == 3

    def test_custom_issue_types(self, monkeypatch):
        """Test that custom issue_types value like 'Bug,Epic' is loaded correctly."""
        monkeypatch.setenv("JIRA_BASE_URL", "https://test.atlassian.net")
        monkeypatch.setenv("JIRA_USER_EMAIL", "test@example.com")
        monkeypatch.setenv("JIRA_API_TOKEN", "test-token")
        monkeypatch.setenv("JIRA_ISSUE_TYPES", "Bug,Epic")

        settings = JiraSettings()

        assert settings.issue_types == "Bug,Epic"

    def test_issue_types_list_property(self, monkeypatch):
        """Test that issue_types_list parses 'Story,Task' into ['Story', 'Task']."""
        monkeypatch.setenv("JIRA_BASE_URL", "https://test.atlassian.net")
        monkeypatch.setenv("JIRA_USER_EMAIL", "test@example.com")
        monkeypatch.setenv("JIRA_API_TOKEN", "test-token")
        monkeypatch.setenv("JIRA_ISSUE_TYPES", "Story,Task")

        settings = JiraSettings()

        assert settings.issue_types_list == ["Story", "Task"]

    def test_issue_types_list_with_whitespace(self, monkeypatch):
        """Test that issue_types_list trims whitespace from items."""
        monkeypatch.setenv("JIRA_BASE_URL", "https://test.atlassian.net")
        monkeypatch.setenv("JIRA_USER_EMAIL", "test@example.com")
        monkeypatch.setenv("JIRA_API_TOKEN", "test-token")
        monkeypatch.setenv("JIRA_ISSUE_TYPES", "Story, Task , Bug")

        settings = JiraSettings()

        assert settings.issue_types_list == ["Story", "Task", "Bug"]

    def test_custom_max_retries(self, monkeypatch):
        """Test that custom max_retries value like 5 is loaded correctly."""
        monkeypatch.setenv("JIRA_BASE_URL", "https://test.atlassian.net")
        monkeypatch.setenv("JIRA_USER_EMAIL", "test@example.com")
        monkeypatch.setenv("JIRA_API_TOKEN", "test-token")
        monkeypatch.setenv("JIRA_MAX_RETRIES", "5")

        settings = JiraSettings()

        assert settings.max_retries == 5

    def test_polling_config_defaults(self, monkeypatch):
        """Test that polling configuration fields have correct defaults when no env vars are set."""
        monkeypatch.setenv("JIRA_BASE_URL", "https://test.atlassian.net")
        monkeypatch.setenv("JIRA_USER_EMAIL", "test@example.com")
        monkeypatch.setenv("JIRA_API_TOKEN", "test-token")
        # Ensure polling env vars are not set
        monkeypatch.delenv("JIRA_PROJECT_KEY", raising=False)
        monkeypatch.delenv("JIRA_POLLING_ENABLED", raising=False)
        monkeypatch.delenv("JIRA_POLLING_INTERVAL_SECONDS", raising=False)
        monkeypatch.delenv("JIRA_POLLING_LOOKBACK_DAYS", raising=False)
        monkeypatch.delenv("JIRA_POLLING_MAX_FAILURES", raising=False)

        settings = JiraSettings()

        assert settings.project_key == ""
        assert settings.polling_enabled is False
        assert settings.polling_interval_seconds == 300
        assert settings.polling_lookback_days == 7
        assert settings.polling_max_failures == 3

    def test_polling_config_from_env_vars(self, monkeypatch):
        """Test that polling configuration fields are loaded correctly from env vars."""
        monkeypatch.setenv("JIRA_BASE_URL", "https://test.atlassian.net")
        monkeypatch.setenv("JIRA_USER_EMAIL", "test@example.com")
        monkeypatch.setenv("JIRA_API_TOKEN", "test-token")
        monkeypatch.setenv("JIRA_PROJECT_KEY", "IGAL")
        monkeypatch.setenv("JIRA_POLLING_ENABLED", "true")
        monkeypatch.setenv("JIRA_POLLING_INTERVAL_SECONDS", "600")
        monkeypatch.setenv("JIRA_POLLING_LOOKBACK_DAYS", "14")
        monkeypatch.setenv("JIRA_POLLING_MAX_FAILURES", "5")

        settings = JiraSettings()

        assert settings.project_key == "IGAL"
        assert settings.polling_enabled is True
        assert settings.polling_interval_seconds == 600
        assert settings.polling_lookback_days == 14
        assert settings.polling_max_failures == 5
