"""Shared pytest fixtures for unit and integration tests.

This module provides common fixtures for testing Jira API integration:
- JiraSettings fixture that loads from environment variables
- JiraClient async fixture with proper cleanup
- Credential availability checking fixture
"""

import os

import pytest

from src.jira import JiraClient, JiraSettings

# Register pytest-asyncio plugin for async test support
pytest_plugins = ["pytest_asyncio"]


@pytest.fixture
def jira_settings_from_env():
    """Load JiraSettings from environment variables.

    Returns:
        JiraSettings: Configuration loaded from JIRA_* environment variables.

    Note:
        Requires JIRA_BASE_URL, JIRA_USER_EMAIL, and JIRA_API_TOKEN to be set.
    """
    return JiraSettings()


@pytest.fixture
async def jira_client(jira_settings_from_env):
    """Create a JiraClient instance and ensure cleanup.

    This fixture provides an async JiraClient that will be properly
    closed after the test completes, regardless of test success or failure.

    Args:
        jira_settings_from_env: JiraSettings fixture with loaded configuration.

    Yields:
        JiraClient: An initialized Jira client ready for API calls.
    """
    client = JiraClient(jira_settings_from_env)
    yield client
    await client.close()


@pytest.fixture
def requires_jira_credentials():
    """Skip test if Jira credentials are not available.

    Use this fixture in tests that require real Jira credentials
    to ensure they are skipped gracefully in environments without
    the necessary configuration.

    Usage:
        def test_something(requires_jira_credentials, jira_client):
            # This test will be skipped if JIRA_API_TOKEN is not set
            ...
    """
    if not os.getenv("JIRA_API_TOKEN"):
        pytest.skip("Jira credentials not available")
