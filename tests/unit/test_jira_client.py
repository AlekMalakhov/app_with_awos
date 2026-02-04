"""Unit tests for JiraClient connection validation."""

from unittest.mock import patch

import httpx
import pytest
from pytest_httpx import HTTPXMock

from src.jira.client import JiraClient
from src.jira.config import JiraSettings
from src.jira.exceptions import (
    JiraAuthenticationError,
    JiraConnectionError,
    JiraIssueTypeNotSupportedError,
    JiraTicketNotFoundError,
)


@pytest.fixture
def jira_settings() -> JiraSettings:
    """Create JiraSettings with test values.

    Note: max_retries=1 disables retry logic for simpler testing of basic functionality.
    """
    return JiraSettings(
        base_url="https://test.atlassian.net",
        user_email="test@example.com",
        api_token="test-api-token",
        max_retries=1,
    )


@pytest.fixture
def jira_settings_with_retries() -> JiraSettings:
    """Create JiraSettings with retry logic enabled (max_retries=3)."""
    return JiraSettings(
        base_url="https://test.atlassian.net",
        user_email="test@example.com",
        api_token="test-api-token",
        max_retries=3,
    )


class TestJiraClientValidateConnection:
    """Test suite for JiraClient.validate_connection() method."""

    @pytest.mark.asyncio
    async def test_successful_connection_returns_true(
        self, httpx_mock: HTTPXMock, jira_settings: JiraSettings
    ):
        """Test that validate_connection returns True on HTTP 200 response."""
        httpx_mock.add_response(
            url="https://test.atlassian.net/rest/api/3/myself",
            method="GET",
            status_code=200,
            json={"accountId": "123", "displayName": "Test User"},
        )

        client = JiraClient(jira_settings)
        try:
            result = await client.validate_connection()
            assert result is True
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_invalid_credentials_raises_authentication_error(
        self, httpx_mock: HTTPXMock, jira_settings: JiraSettings
    ):
        """Test that validate_connection raises JiraAuthenticationError on HTTP 401."""
        httpx_mock.add_response(
            url="https://test.atlassian.net/rest/api/3/myself",
            method="GET",
            status_code=401,
            json={"message": "Unauthorized"},
        )

        client = JiraClient(jira_settings)
        try:
            with pytest.raises(JiraAuthenticationError) as exc_info:
                await client.validate_connection()

            assert "401" in str(exc_info.value)
            assert "Authentication failed" in str(exc_info.value)
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_forbidden_raises_authentication_error(
        self, httpx_mock: HTTPXMock, jira_settings: JiraSettings
    ):
        """Test that validate_connection raises JiraAuthenticationError on HTTP 403."""
        httpx_mock.add_response(
            url="https://test.atlassian.net/rest/api/3/myself",
            method="GET",
            status_code=403,
            json={"message": "Forbidden"},
        )

        client = JiraClient(jira_settings)
        try:
            with pytest.raises(JiraAuthenticationError) as exc_info:
                await client.validate_connection()

            assert "403" in str(exc_info.value)
            assert "Authentication failed" in str(exc_info.value)
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_connection_error_raises_jira_connection_error(
        self, httpx_mock: HTTPXMock, jira_settings: JiraSettings
    ):
        """Test that validate_connection raises JiraConnectionError on network failure."""
        httpx_mock.add_exception(
            httpx.ConnectError("Connection refused"),
            url="https://test.atlassian.net/rest/api/3/myself",
            method="GET",
        )

        client = JiraClient(jira_settings)
        try:
            with pytest.raises(JiraConnectionError) as exc_info:
                await client.validate_connection()

            assert "Failed to connect" in str(exc_info.value)
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_timeout_raises_jira_connection_error(
        self, httpx_mock: HTTPXMock, jira_settings: JiraSettings
    ):
        """Test that validate_connection raises JiraConnectionError on timeout."""
        httpx_mock.add_exception(
            httpx.TimeoutException("Request timed out"),
            url="https://test.atlassian.net/rest/api/3/myself",
            method="GET",
        )

        client = JiraClient(jira_settings)
        try:
            with pytest.raises(JiraConnectionError) as exc_info:
                await client.validate_connection()

            assert "timed out" in str(exc_info.value)
        finally:
            await client.close()


class TestJiraClientRetryBehavior:
    """Test suite for JiraClient retry logic with exponential backoff."""

    @pytest.mark.asyncio
    @patch("asyncio.sleep", return_value=None)
    async def test_5xx_error_retries_then_fails(
        self,
        mock_sleep,
        httpx_mock: HTTPXMock,
        jira_settings_with_retries: JiraSettings,
    ):
        """Test that 5xx errors trigger retries and fail after exhausting max_retries.

        With max_retries=3, tenacity will make 3 total attempts.
        All 3 return 500, so JiraConnectionError should be raised after retries exhausted.
        """
        # Mock 3 consecutive 500 responses (initial + 2 retries = 3 attempts)
        httpx_mock.add_response(
            url="https://test.atlassian.net/rest/api/3/myself",
            method="GET",
            status_code=500,
            json={"message": "Internal Server Error"},
        )
        httpx_mock.add_response(
            url="https://test.atlassian.net/rest/api/3/myself",
            method="GET",
            status_code=500,
            json={"message": "Internal Server Error"},
        )
        httpx_mock.add_response(
            url="https://test.atlassian.net/rest/api/3/myself",
            method="GET",
            status_code=500,
            json={"message": "Internal Server Error"},
        )

        client = JiraClient(jira_settings_with_retries)
        try:
            with pytest.raises(JiraConnectionError) as exc_info:
                await client.validate_connection()

            # Verify error message indicates retries were exhausted
            assert "after 3 retries" in str(exc_info.value)
            assert "500" in str(exc_info.value)

            # Verify exactly 3 requests were made (max_retries=3 means 3 total attempts)
            requests = httpx_mock.get_requests()
            assert len(requests) == 3
        finally:
            await client.close()

    @pytest.mark.asyncio
    @patch("asyncio.sleep", return_value=None)
    async def test_429_rate_limit_retries_then_succeeds(
        self,
        mock_sleep,
        httpx_mock: HTTPXMock,
        jira_settings_with_retries: JiraSettings,
    ):
        """Test that 429 rate limit error triggers retry and eventually succeeds.

        First request returns 429 (rate limited), second request succeeds with 200.
        """
        # First response: 429 Rate Limited
        httpx_mock.add_response(
            url="https://test.atlassian.net/rest/api/3/myself",
            method="GET",
            status_code=429,
            json={"message": "Rate limited"},
        )
        # Second response: 200 Success
        httpx_mock.add_response(
            url="https://test.atlassian.net/rest/api/3/myself",
            method="GET",
            status_code=200,
            json={"accountId": "123", "displayName": "Test User"},
        )

        client = JiraClient(jira_settings_with_retries)
        try:
            result = await client.validate_connection()

            # Verify the call eventually succeeded
            assert result is True

            # Verify exactly 2 requests were made (initial 429 + successful retry)
            requests = httpx_mock.get_requests()
            assert len(requests) == 2
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_4xx_error_fails_immediately_without_retry(
        self, httpx_mock: HTTPXMock, jira_settings_with_retries: JiraSettings
    ):
        """Test that 4xx errors (except 429) fail immediately without retry.

        A 400 Bad Request should raise JiraConnectionError immediately with no retries.
        """
        # Only one 400 response - no retries should occur
        httpx_mock.add_response(
            url="https://test.atlassian.net/rest/api/3/myself",
            method="GET",
            status_code=400,
            json={"message": "Bad Request"},
        )

        client = JiraClient(jira_settings_with_retries)
        try:
            with pytest.raises(JiraConnectionError) as exc_info:
                await client.validate_connection()

            # Verify error message mentions the status code
            assert "400" in str(exc_info.value)

            # Verify only 1 request was made (no retries for 4xx except 429)
            requests = httpx_mock.get_requests()
            assert len(requests) == 1
        finally:
            await client.close()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status_code", [500, 502, 503, 504])
    @patch("asyncio.sleep", return_value=None)
    async def test_various_5xx_errors_trigger_retry(
        self,
        mock_sleep,
        httpx_mock: HTTPXMock,
        jira_settings_with_retries: JiraSettings,
        status_code: int,
    ):
        """Test that various 5xx server errors all trigger retry behavior.

        Tests 500, 502, 503, and 504 status codes.
        """
        # First response: 5xx error
        httpx_mock.add_response(
            url="https://test.atlassian.net/rest/api/3/myself",
            method="GET",
            status_code=status_code,
            json={"message": f"Server Error {status_code}"},
        )
        # Second response: success
        httpx_mock.add_response(
            url="https://test.atlassian.net/rest/api/3/myself",
            method="GET",
            status_code=200,
            json={"accountId": "123", "displayName": "Test User"},
        )

        client = JiraClient(jira_settings_with_retries)
        try:
            result = await client.validate_connection()

            # Verify eventual success after retry
            assert result is True

            # Verify exactly 2 requests were made
            requests = httpx_mock.get_requests()
            assert len(requests) == 2
        finally:
            await client.close()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status_code", [400, 404, 405, 422])
    async def test_various_4xx_errors_do_not_retry(
        self,
        httpx_mock: HTTPXMock,
        jira_settings_with_retries: JiraSettings,
        status_code: int,
    ):
        """Test that various 4xx errors (except 429) fail immediately without retry.

        Tests 400, 404, 405, and 422 status codes.
        """
        httpx_mock.add_response(
            url="https://test.atlassian.net/rest/api/3/myself",
            method="GET",
            status_code=status_code,
            json={"message": f"Client Error {status_code}"},
        )

        client = JiraClient(jira_settings_with_retries)
        try:
            with pytest.raises(JiraConnectionError) as exc_info:
                await client.validate_connection()

            # Verify error contains status code
            assert str(status_code) in str(exc_info.value)

            # Verify only 1 request was made (no retries)
            requests = httpx_mock.get_requests()
            assert len(requests) == 1
        finally:
            await client.close()


class TestJiraClientGetTicket:
    """Test suite for JiraClient.get_ticket() method."""

    @pytest.mark.asyncio
    async def test_ticket_exists_returns_ticket_data(
        self, httpx_mock: HTTPXMock, jira_settings: JiraSettings
    ):
        """Test that get_ticket returns TicketData with correct fields on success."""
        httpx_mock.add_response(
            url="https://test.atlassian.net/rest/api/3/issue/PROJ-123?fields=summary,description,issuetype",
            method="GET",
            status_code=200,
            json={
                "key": "PROJ-123",
                "fields": {
                    "summary": "Test ticket summary",
                    "description": {
                        "type": "doc",
                        "version": 1,
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [
                                    {"type": "text", "text": "Description text here"}
                                ],
                            }
                        ],
                    },
                    "issuetype": {"name": "Story"},
                },
            },
        )

        client = JiraClient(jira_settings)
        try:
            ticket = await client.get_ticket("PROJ-123")

            assert ticket.key == "PROJ-123"
            assert ticket.summary == "Test ticket summary"
            assert ticket.description == "Description text here"
            assert ticket.issue_type == "Story"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_ticket_not_found_raises_error(
        self, httpx_mock: HTTPXMock, jira_settings: JiraSettings
    ):
        """Test that get_ticket raises JiraTicketNotFoundError on 404."""
        httpx_mock.add_response(
            url="https://test.atlassian.net/rest/api/3/issue/PROJ-999?fields=summary,description,issuetype",
            method="GET",
            status_code=404,
            json={"errorMessages": ["Issue does not exist"]},
        )

        client = JiraClient(jira_settings)
        try:
            with pytest.raises(JiraTicketNotFoundError) as exc_info:
                await client.get_ticket("PROJ-999")

            assert "PROJ-999" in str(exc_info.value)
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_null_description_returns_empty_string(
        self, httpx_mock: HTTPXMock, jira_settings: JiraSettings
    ):
        """Test that get_ticket returns empty string for null description."""
        httpx_mock.add_response(
            url="https://test.atlassian.net/rest/api/3/issue/PROJ-456?fields=summary,description,issuetype",
            method="GET",
            status_code=200,
            json={
                "key": "PROJ-456",
                "fields": {
                    "summary": "Ticket with no description",
                    "description": None,
                    "issuetype": {"name": "Task"},
                },
            },
        )

        client = JiraClient(jira_settings)
        try:
            ticket = await client.get_ticket("PROJ-456")

            assert ticket.key == "PROJ-456"
            assert ticket.summary == "Ticket with no description"
            assert ticket.description == ""
            assert ticket.issue_type == "Task"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_unsupported_issue_type_raises_error(
        self, httpx_mock: HTTPXMock, jira_settings: JiraSettings
    ):
        """Test that get_ticket raises JiraIssueTypeNotSupportedError for unsupported type."""
        httpx_mock.add_response(
            url="https://test.atlassian.net/rest/api/3/issue/PROJ-789?fields=summary,description,issuetype",
            method="GET",
            status_code=200,
            json={
                "key": "PROJ-789",
                "fields": {
                    "summary": "Bug ticket",
                    "description": None,
                    "issuetype": {"name": "Bug"},
                },
            },
        )

        client = JiraClient(jira_settings)
        try:
            with pytest.raises(JiraIssueTypeNotSupportedError) as exc_info:
                await client.get_ticket("PROJ-789")

            assert "Bug" in str(exc_info.value)
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_supported_issue_type_task_returns_ticket_data(
        self, httpx_mock: HTTPXMock, jira_settings: JiraSettings
    ):
        """Test that get_ticket succeeds for issue type 'Task' (in configured list)."""
        httpx_mock.add_response(
            url="https://test.atlassian.net/rest/api/3/issue/PROJ-101?fields=summary,description,issuetype",
            method="GET",
            status_code=200,
            json={
                "key": "PROJ-101",
                "fields": {
                    "summary": "A task ticket",
                    "description": {
                        "type": "doc",
                        "version": 1,
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [
                                    {"type": "text", "text": "Task description"}
                                ],
                            }
                        ],
                    },
                    "issuetype": {"name": "Task"},
                },
            },
        )

        client = JiraClient(jira_settings)
        try:
            ticket = await client.get_ticket("PROJ-101")

            assert ticket.key == "PROJ-101"
            assert ticket.summary == "A task ticket"
            assert ticket.description == "Task description"
            assert ticket.issue_type == "Task"
        finally:
            await client.close()


class TestJiraClientSearchTickets:
    """Test suite for JiraClient.search_tickets() method."""

    @pytest.mark.asyncio
    async def test_search_tickets_success_with_results(
        self, httpx_mock: HTTPXMock, jira_settings: JiraSettings
    ):
        """Test that search_tickets returns list of TicketData when API returns issues."""
        httpx_mock.add_response(
            url="https://test.atlassian.net/rest/api/3/search/jql?jql=project+%3D+PROJ&maxResults=50&fields=summary%2Cdescription%2Cissuetype",
            method="GET",
            status_code=200,
            json={
                "issues": [
                    {
                        "key": "PROJ-1",
                        "fields": {
                            "summary": "First ticket",
                            "description": {
                                "type": "doc",
                                "version": 1,
                                "content": [
                                    {
                                        "type": "paragraph",
                                        "content": [
                                            {"type": "text", "text": "First description"}
                                        ],
                                    }
                                ],
                            },
                            "issuetype": {"name": "Story"},
                        },
                    },
                    {
                        "key": "PROJ-2",
                        "fields": {
                            "summary": "Second ticket",
                            "description": None,
                            "issuetype": {"name": "Task"},
                        },
                    },
                ],
                "total": 2,
                "maxResults": 50,
                "startAt": 0,
            },
        )

        client = JiraClient(jira_settings)
        try:
            tickets = await client.search_tickets("project = PROJ")

            assert len(tickets) == 2

            assert tickets[0].key == "PROJ-1"
            assert tickets[0].summary == "First ticket"
            assert tickets[0].description == "First description"
            assert tickets[0].issue_type == "Story"

            assert tickets[1].key == "PROJ-2"
            assert tickets[1].summary == "Second ticket"
            assert tickets[1].description == ""
            assert tickets[1].issue_type == "Task"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_search_tickets_empty_results(
        self, httpx_mock: HTTPXMock, jira_settings: JiraSettings
    ):
        """Test that search_tickets returns empty list when API returns no issues."""
        httpx_mock.add_response(
            url="https://test.atlassian.net/rest/api/3/search/jql?jql=project+%3D+NONEXISTENT&maxResults=50&fields=summary%2Cdescription%2Cissuetype",
            method="GET",
            status_code=200,
            json={
                "issues": [],
                "total": 0,
                "maxResults": 50,
                "startAt": 0,
            },
        )

        client = JiraClient(jira_settings)
        try:
            tickets = await client.search_tickets("project = NONEXISTENT")

            assert tickets == []
            assert len(tickets) == 0
        finally:
            await client.close()

    @pytest.mark.asyncio
    @patch("asyncio.sleep", return_value=None)
    async def test_search_tickets_5xx_retry_then_success(
        self,
        mock_sleep,
        httpx_mock: HTTPXMock,
        jira_settings_with_retries: JiraSettings,
    ):
        """Test that search_tickets retries on 500 error and succeeds on subsequent 200.

        First request returns 500 (server error), second request succeeds with 200.
        """
        # First response: 500 Server Error
        httpx_mock.add_response(
            url="https://test.atlassian.net/rest/api/3/search/jql?jql=project+%3D+PROJ&maxResults=50&fields=summary%2Cdescription%2Cissuetype",
            method="GET",
            status_code=500,
            json={"message": "Internal Server Error"},
        )
        # Second response: 200 Success
        httpx_mock.add_response(
            url="https://test.atlassian.net/rest/api/3/search/jql?jql=project+%3D+PROJ&maxResults=50&fields=summary%2Cdescription%2Cissuetype",
            method="GET",
            status_code=200,
            json={
                "issues": [
                    {
                        "key": "PROJ-123",
                        "fields": {
                            "summary": "Recovered ticket",
                            "description": None,
                            "issuetype": {"name": "Task"},
                        },
                    }
                ],
                "total": 1,
                "maxResults": 50,
                "startAt": 0,
            },
        )

        client = JiraClient(jira_settings_with_retries)
        try:
            tickets = await client.search_tickets("project = PROJ")

            # Verify the call eventually succeeded
            assert len(tickets) == 1
            assert tickets[0].key == "PROJ-123"
            assert tickets[0].summary == "Recovered ticket"

            # Verify exactly 2 requests were made (initial 500 + successful retry)
            requests = httpx_mock.get_requests()
            assert len(requests) == 2
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_search_tickets_401_auth_error(
        self, httpx_mock: HTTPXMock, jira_settings: JiraSettings
    ):
        """Test that search_tickets raises JiraAuthenticationError on HTTP 401."""
        httpx_mock.add_response(
            url="https://test.atlassian.net/rest/api/3/search/jql?jql=project+%3D+PROJ&maxResults=50&fields=summary%2Cdescription%2Cissuetype",
            method="GET",
            status_code=401,
            json={"message": "Unauthorized"},
        )

        client = JiraClient(jira_settings)
        try:
            with pytest.raises(JiraAuthenticationError) as exc_info:
                await client.search_tickets("project = PROJ")

            assert "401" in str(exc_info.value)
            assert "Authentication failed" in str(exc_info.value)
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_search_tickets_403_auth_error(
        self, httpx_mock: HTTPXMock, jira_settings: JiraSettings
    ):
        """Test that search_tickets raises JiraAuthenticationError on HTTP 403."""
        httpx_mock.add_response(
            url="https://test.atlassian.net/rest/api/3/search/jql?jql=project+%3D+PROJ&maxResults=50&fields=summary%2Cdescription%2Cissuetype",
            method="GET",
            status_code=403,
            json={"message": "Forbidden"},
        )

        client = JiraClient(jira_settings)
        try:
            with pytest.raises(JiraAuthenticationError) as exc_info:
                await client.search_tickets("project = PROJ")

            assert "403" in str(exc_info.value)
            assert "Authentication failed" in str(exc_info.value)
        finally:
            await client.close()


class TestJiraClientAddLabel:
    """Test suite for JiraClient.add_label() method."""

    @pytest.mark.asyncio
    async def test_add_label_success_returns_true(
        self, httpx_mock: HTTPXMock, jira_settings: JiraSettings
    ):
        """Test that add_label returns True when API returns 204 No Content."""
        httpx_mock.add_response(
            url="https://test.atlassian.net/rest/api/3/issue/PROJ-123",
            method="PUT",
            status_code=204,
        )

        client = JiraClient(jira_settings)
        try:
            result = await client.add_label("PROJ-123", "ac-generated")

            assert result is True

            # Verify the request was made with correct payload
            requests = httpx_mock.get_requests()
            assert len(requests) == 1
            assert requests[0].method == "PUT"
            assert requests[0].url.path == "/rest/api/3/issue/PROJ-123"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_add_label_success_200_returns_true(
        self, httpx_mock: HTTPXMock, jira_settings: JiraSettings
    ):
        """Test that add_label returns True when API returns 200 OK."""
        httpx_mock.add_response(
            url="https://test.atlassian.net/rest/api/3/issue/PROJ-456",
            method="PUT",
            status_code=200,
            json={},
        )

        client = JiraClient(jira_settings)
        try:
            result = await client.add_label("PROJ-456", "test-label")

            assert result is True
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_add_label_failure_400_returns_false(
        self, httpx_mock: HTTPXMock, jira_settings: JiraSettings
    ):
        """Test that add_label returns False when API returns 400 Bad Request."""
        httpx_mock.add_response(
            url="https://test.atlassian.net/rest/api/3/issue/PROJ-123",
            method="PUT",
            status_code=400,
            json={"errorMessages": ["Invalid label"]},
        )

        client = JiraClient(jira_settings)
        try:
            result = await client.add_label("PROJ-123", "invalid label!")

            assert result is False
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_add_label_failure_404_returns_false(
        self, httpx_mock: HTTPXMock, jira_settings: JiraSettings
    ):
        """Test that add_label returns False when ticket not found (404)."""
        httpx_mock.add_response(
            url="https://test.atlassian.net/rest/api/3/issue/PROJ-999",
            method="PUT",
            status_code=404,
            json={"errorMessages": ["Issue does not exist"]},
        )

        client = JiraClient(jira_settings)
        try:
            result = await client.add_label("PROJ-999", "ac-generated")

            assert result is False
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_add_label_failure_500_returns_false(
        self, httpx_mock: HTTPXMock, jira_settings: JiraSettings
    ):
        """Test that add_label returns False when API returns 500 Server Error."""
        httpx_mock.add_response(
            url="https://test.atlassian.net/rest/api/3/issue/PROJ-123",
            method="PUT",
            status_code=500,
            json={"message": "Internal Server Error"},
        )

        client = JiraClient(jira_settings)
        try:
            result = await client.add_label("PROJ-123", "ac-generated")

            assert result is False
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_add_label_does_not_raise_on_http_error(
        self, httpx_mock: HTTPXMock, jira_settings: JiraSettings
    ):
        """Test that add_label does not raise exception on HTTP errors."""
        httpx_mock.add_response(
            url="https://test.atlassian.net/rest/api/3/issue/PROJ-123",
            method="PUT",
            status_code=403,
            json={"message": "Forbidden"},
        )

        client = JiraClient(jira_settings)
        try:
            # Should NOT raise - just return False
            result = await client.add_label("PROJ-123", "ac-generated")

            assert result is False
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_add_label_does_not_raise_on_connection_error(
        self, httpx_mock: HTTPXMock, jira_settings: JiraSettings
    ):
        """Test that add_label does not raise exception on network errors."""
        httpx_mock.add_exception(
            httpx.ConnectError("Connection refused"),
            url="https://test.atlassian.net/rest/api/3/issue/PROJ-123",
            method="PUT",
        )

        client = JiraClient(jira_settings)
        try:
            # Should NOT raise - just return False
            result = await client.add_label("PROJ-123", "ac-generated")

            assert result is False
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_add_label_does_not_raise_on_timeout(
        self, httpx_mock: HTTPXMock, jira_settings: JiraSettings
    ):
        """Test that add_label does not raise exception on timeout."""
        httpx_mock.add_exception(
            httpx.TimeoutException("Request timed out"),
            url="https://test.atlassian.net/rest/api/3/issue/PROJ-123",
            method="PUT",
        )

        client = JiraClient(jira_settings)
        try:
            # Should NOT raise - just return False
            result = await client.add_label("PROJ-123", "ac-generated")

            assert result is False
        finally:
            await client.close()


class TestJiraClientUpdateDescription:
    """Test suite for JiraClient.update_description() method."""

    @pytest.fixture
    def sample_adf(self) -> dict:
        """Create a sample ADF document for testing."""
        return {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "Test description"}],
                }
            ],
        }

    @pytest.mark.asyncio
    async def test_update_description_success_returns_true(
        self, httpx_mock: HTTPXMock, jira_settings: JiraSettings, sample_adf: dict
    ):
        """Test that update_description returns True when API returns 204 No Content."""
        httpx_mock.add_response(
            url="https://test.atlassian.net/rest/api/3/issue/PROJ-123",
            method="PUT",
            status_code=204,
        )

        client = JiraClient(jira_settings)
        try:
            result = await client.update_description("PROJ-123", sample_adf)

            assert result is True

            # Verify the request was made with correct payload
            requests = httpx_mock.get_requests()
            assert len(requests) == 1
            assert requests[0].method == "PUT"
            assert requests[0].url.path == "/rest/api/3/issue/PROJ-123"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_update_description_success_200_returns_true(
        self, httpx_mock: HTTPXMock, jira_settings: JiraSettings, sample_adf: dict
    ):
        """Test that update_description returns True when API returns 200 OK."""
        httpx_mock.add_response(
            url="https://test.atlassian.net/rest/api/3/issue/PROJ-456",
            method="PUT",
            status_code=200,
            json={},
        )

        client = JiraClient(jira_settings)
        try:
            result = await client.update_description("PROJ-456", sample_adf)

            assert result is True
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_update_description_not_found_returns_false(
        self, httpx_mock: HTTPXMock, jira_settings: JiraSettings, sample_adf: dict
    ):
        """Test that update_description returns False when ticket not found (404)."""
        httpx_mock.add_response(
            url="https://test.atlassian.net/rest/api/3/issue/PROJ-999",
            method="PUT",
            status_code=404,
            json={"errorMessages": ["Issue does not exist"]},
        )

        client = JiraClient(jira_settings)
        try:
            result = await client.update_description("PROJ-999", sample_adf)

            assert result is False
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_update_description_auth_failure_401_returns_false(
        self, httpx_mock: HTTPXMock, jira_settings: JiraSettings, sample_adf: dict
    ):
        """Test that update_description returns False on 401 auth failure."""
        httpx_mock.add_response(
            url="https://test.atlassian.net/rest/api/3/issue/PROJ-123",
            method="PUT",
            status_code=401,
            json={"message": "Unauthorized"},
        )

        client = JiraClient(jira_settings)
        try:
            result = await client.update_description("PROJ-123", sample_adf)

            assert result is False
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_update_description_auth_failure_403_returns_false(
        self, httpx_mock: HTTPXMock, jira_settings: JiraSettings, sample_adf: dict
    ):
        """Test that update_description returns False on 403 forbidden."""
        httpx_mock.add_response(
            url="https://test.atlassian.net/rest/api/3/issue/PROJ-123",
            method="PUT",
            status_code=403,
            json={"message": "Forbidden"},
        )

        client = JiraClient(jira_settings)
        try:
            result = await client.update_description("PROJ-123", sample_adf)

            assert result is False
        finally:
            await client.close()

    @pytest.mark.asyncio
    @patch("asyncio.sleep", return_value=None)
    async def test_update_description_retry_on_5xx(
        self,
        mock_sleep,
        httpx_mock: HTTPXMock,
        jira_settings_with_retries: JiraSettings,
        sample_adf: dict,
    ):
        """Test that update_description retries on 500 error and succeeds."""
        # First response: 500 Server Error
        httpx_mock.add_response(
            url="https://test.atlassian.net/rest/api/3/issue/PROJ-123",
            method="PUT",
            status_code=500,
            json={"message": "Internal Server Error"},
        )
        # Second response: 204 Success
        httpx_mock.add_response(
            url="https://test.atlassian.net/rest/api/3/issue/PROJ-123",
            method="PUT",
            status_code=204,
        )

        client = JiraClient(jira_settings_with_retries)
        try:
            result = await client.update_description("PROJ-123", sample_adf)

            assert result is True

            # Verify exactly 2 requests were made
            requests = httpx_mock.get_requests()
            assert len(requests) == 2
        finally:
            await client.close()

    @pytest.mark.asyncio
    @patch("asyncio.sleep", return_value=None)
    async def test_update_description_retry_exhausted_returns_false(
        self,
        mock_sleep,
        httpx_mock: HTTPXMock,
        jira_settings_with_retries: JiraSettings,
        sample_adf: dict,
    ):
        """Test that update_description returns False after retries exhausted."""
        # All 3 attempts return 500
        for _ in range(3):
            httpx_mock.add_response(
                url="https://test.atlassian.net/rest/api/3/issue/PROJ-123",
                method="PUT",
                status_code=500,
                json={"message": "Internal Server Error"},
            )

        client = JiraClient(jira_settings_with_retries)
        try:
            result = await client.update_description("PROJ-123", sample_adf)

            assert result is False

            # Verify exactly 3 requests were made (max_retries=3)
            requests = httpx_mock.get_requests()
            assert len(requests) == 3
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_update_description_empty_issue_key_returns_false(
        self, jira_settings: JiraSettings, sample_adf: dict
    ):
        """Test that update_description returns False for empty issue key."""
        client = JiraClient(jira_settings)
        try:
            result = await client.update_description("", sample_adf)

            assert result is False
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_update_description_empty_adf_returns_false(
        self, jira_settings: JiraSettings
    ):
        """Test that update_description returns False for empty ADF."""
        client = JiraClient(jira_settings)
        try:
            result = await client.update_description("PROJ-123", {})

            assert result is False
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_update_description_none_adf_returns_false(
        self, jira_settings: JiraSettings
    ):
        """Test that update_description returns False for None ADF."""
        client = JiraClient(jira_settings)
        try:
            result = await client.update_description("PROJ-123", None)

            assert result is False
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_update_description_connection_error_returns_false(
        self, httpx_mock: HTTPXMock, jira_settings: JiraSettings, sample_adf: dict
    ):
        """Test that update_description returns False on connection error."""
        httpx_mock.add_exception(
            httpx.ConnectError("Connection refused"),
            url="https://test.atlassian.net/rest/api/3/issue/PROJ-123",
            method="PUT",
        )

        client = JiraClient(jira_settings)
        try:
            result = await client.update_description("PROJ-123", sample_adf)

            assert result is False
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_update_description_timeout_returns_false(
        self, httpx_mock: HTTPXMock, jira_settings: JiraSettings, sample_adf: dict
    ):
        """Test that update_description returns False on timeout."""
        httpx_mock.add_exception(
            httpx.TimeoutException("Request timed out"),
            url="https://test.atlassian.net/rest/api/3/issue/PROJ-123",
            method="PUT",
        )

        client = JiraClient(jira_settings)
        try:
            result = await client.update_description("PROJ-123", sample_adf)

            assert result is False
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_update_description_sends_correct_payload(
        self, httpx_mock: HTTPXMock, jira_settings: JiraSettings, sample_adf: dict
    ):
        """Test that update_description sends the ADF in the correct JSON structure."""
        httpx_mock.add_response(
            url="https://test.atlassian.net/rest/api/3/issue/PROJ-123",
            method="PUT",
            status_code=204,
        )

        client = JiraClient(jira_settings)
        try:
            await client.update_description("PROJ-123", sample_adf)

            requests = httpx_mock.get_requests()
            assert len(requests) == 1

            import json

            payload = json.loads(requests[0].content)
            assert "fields" in payload
            assert "description" in payload["fields"]
            assert payload["fields"]["description"] == sample_adf
        finally:
            await client.close()
