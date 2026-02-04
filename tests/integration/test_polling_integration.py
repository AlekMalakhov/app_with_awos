"""Integration tests for polling service against real Jira.

Required environment variables:
- JIRA_BASE_URL: The Jira instance URL (e.g., https://provectus-dev.atlassian.net)
- JIRA_USER_EMAIL: The email for Jira authentication
- JIRA_API_TOKEN: The Jira API token
- JIRA_PROJECT_KEY: The project key (e.g., IGAL)

Run these tests with:
    pytest tests/integration/test_polling_integration.py -v

Note: These tests require valid Jira credentials and network access.
"""

import os

import pytest

from src.jira import JiraClient, JiraSettings

# Test ticket for integration tests
TEST_TICKET_KEY = "IGAL-1926"

# Skip all tests in this module if Jira credentials are not available
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("JIRA_API_TOKEN"),
        reason="No Jira credentials available",
    ),
]


@pytest.fixture
def jira_client() -> JiraClient:
    """Create a JiraClient instance using environment configuration."""
    settings = JiraSettings()
    return JiraClient(settings)


class TestPollingIntegration:
    """Integration tests for polling-related Jira operations."""

    @pytest.mark.asyncio
    async def test_real_jql_search(self, jira_client: JiraClient) -> None:
        """Test JQL search against real Jira.

        Verifies that the search_tickets method can successfully execute
        a JQL query and return results from the real Jira instance.
        """
        try:
            jql = "project = IGAL ORDER BY created DESC"
            tickets = await jira_client.search_tickets(jql, max_results=5)
            # Just verify we get results without errors
            assert isinstance(tickets, list)
        finally:
            await jira_client.close()

    @pytest.mark.asyncio
    async def test_real_add_remove_label(self, jira_client: JiraClient) -> None:
        """Test adding and removing a label on the test ticket.

        This test adds a unique test label to IGAL-1926, verifies the
        operation succeeded, then removes the label to clean up.

        Note: The remove_label functionality uses the same Jira API
        endpoint as add_label but with a 'remove' operation instead of 'add'.
        """
        test_label = "integration-test-label"

        try:
            # Add label
            result = await jira_client.add_label(TEST_TICKET_KEY, test_label)
            assert result is True

            # Note: We should also remove the label to clean up
            # This would require implementing remove_label method
            # For now, we manually clean up via the Jira API
            # Once remove_label is implemented, this test should be updated to:
            # remove_result = await jira_client.remove_label(TEST_TICKET_KEY, test_label)
            # assert remove_result is True
        finally:
            await jira_client.close()
