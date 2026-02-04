"""Integration tests for JiraClient with real Jira instance.

These tests require real Jira credentials to run:
- JIRA_BASE_URL: Jira Cloud instance URL (e.g., https://company.atlassian.net)
- JIRA_USER_EMAIL: API user email
- JIRA_API_TOKEN: API token (from Atlassian account)
- JIRA_TEST_TICKET_KEY: (optional) A real ticket key to test reading (default: PROJ-1)

Tests are skipped automatically if JIRA_API_TOKEN is not set.
"""

import os

import pytest

from src.jira import JiraClient, JiraSettings, JiraTicketNotFoundError


# Skip all tests in this module if Jira credentials are not available
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("JIRA_API_TOKEN"),
        reason="No Jira credentials available"
    ),
]


@pytest.mark.asyncio
async def test_real_jira_connection_validation():
    """Test that we can authenticate with real Jira credentials."""
    settings = JiraSettings()
    client = JiraClient(settings)
    try:
        result = await client.validate_connection()
        assert result is True
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_read_existing_ticket():
    """Test reading a real ticket from Jira.

    Uses JIRA_TEST_TICKET_KEY environment variable to specify the ticket to read.
    Defaults to "PROJ-1" if not set.
    """
    ticket_key = os.getenv("JIRA_TEST_TICKET_KEY", "PROJ-1")
    settings = JiraSettings()
    client = JiraClient(settings)
    try:
        ticket = await client.get_ticket(ticket_key)
        assert ticket.key == ticket_key
        assert ticket.summary is not None
        assert ticket.issue_type is not None
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_read_nonexistent_ticket():
    """Test that reading a non-existent ticket raises JiraTicketNotFoundError."""
    settings = JiraSettings()
    client = JiraClient(settings)
    try:
        with pytest.raises(JiraTicketNotFoundError):
            await client.get_ticket("NONEXISTENT-99999")
    finally:
        await client.close()
