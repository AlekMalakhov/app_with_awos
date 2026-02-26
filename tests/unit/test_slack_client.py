"""Unit tests for SlackClient message sending functionality."""

from unittest.mock import patch

import httpx
import pytest
from pytest_httpx import HTTPXMock

from src.slack.client import SlackClient
from src.slack.config import SlackSettings
from src.slack.exceptions import SlackAPIError, SlackConnectionError


@pytest.fixture
def slack_settings() -> SlackSettings:
    """Create SlackSettings with test values.

    Note: max_retries=1 disables retry logic for simpler testing of basic functionality.
    """
    return SlackSettings(
        bot_token="xoxb-test-token-12345",
        app_token="xapp-test-token",
        signing_secret="test-signing-secret",
        max_retries=1,
    )


@pytest.fixture
def slack_settings_with_retries() -> SlackSettings:
    """Create SlackSettings with retry logic enabled (max_retries=3)."""
    return SlackSettings(
        bot_token="xoxb-test-token-12345",
        app_token="xapp-test-token",
        signing_secret="test-signing-secret",
        max_retries=3,
    )


class TestSlackClientSendMessage:
    """Test suite for SlackClient.send_message() method."""

    @pytest.mark.asyncio
    async def test_successful_message_send_returns_true(
        self, httpx_mock: HTTPXMock, slack_settings: SlackSettings
    ):
        """Test that send_message returns True on successful API response."""
        httpx_mock.add_response(
            url="https://slack.com/api/chat.postMessage",
            method="POST",
            status_code=200,
            json={
                "ok": True,
                "channel": "C1234567890",
                "ts": "1234567890.123456",
            },
        )

        client = SlackClient(slack_settings)
        try:
            result = await client.send_message("C1234567890", "Hello, world!")
            assert result is True
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_send_message_includes_correct_headers(
        self, httpx_mock: HTTPXMock, slack_settings: SlackSettings
    ):
        """Test that send_message includes correct Authorization header."""
        httpx_mock.add_response(
            url="https://slack.com/api/chat.postMessage",
            method="POST",
            status_code=200,
            json={"ok": True, "channel": "C1234567890", "ts": "1234567890.123456"},
        )

        client = SlackClient(slack_settings)
        try:
            await client.send_message("C1234567890", "Test message")

            requests = httpx_mock.get_requests()
            assert len(requests) == 1
            auth_header = requests[0].headers["Authorization"]
            assert auth_header == "Bearer xoxb-test-token-12345"
            assert requests[0].headers["Content-Type"] == "application/json"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_send_message_includes_correct_payload(
        self, httpx_mock: HTTPXMock, slack_settings: SlackSettings
    ):
        """Test that send_message sends correct JSON payload with channel and text."""
        httpx_mock.add_response(
            url="https://slack.com/api/chat.postMessage",
            method="POST",
            status_code=200,
            json={"ok": True, "channel": "D9876543210", "ts": "1234567890.123456"},
        )

        client = SlackClient(slack_settings)
        try:
            await client.send_message("D9876543210", "Hello from DM!")

            requests = httpx_mock.get_requests()
            assert len(requests) == 1

            import json

            payload = json.loads(requests[0].content)
            assert payload["channel"] == "D9876543210"
            assert payload["text"] == "Hello from DM!"
        finally:
            await client.close()


class TestSlackClientAPIErrors:
    """Test suite for SlackClient handling of Slack API errors (ok: false)."""

    @pytest.mark.asyncio
    async def test_channel_not_found_raises_slack_api_error(
        self, httpx_mock: HTTPXMock, slack_settings: SlackSettings
    ):
        """Test that send_message raises SlackAPIError when channel_not_found."""
        httpx_mock.add_response(
            url="https://slack.com/api/chat.postMessage",
            method="POST",
            status_code=200,
            json={"ok": False, "error": "channel_not_found"},
        )

        client = SlackClient(slack_settings)
        try:
            with pytest.raises(SlackAPIError) as exc_info:
                await client.send_message("C0000000000", "Test message")

            assert exc_info.value.error_code == "channel_not_found"
            assert "channel_not_found" in str(exc_info.value)
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_invalid_auth_raises_slack_api_error(
        self, httpx_mock: HTTPXMock, slack_settings: SlackSettings
    ):
        """Test that send_message raises SlackAPIError on invalid_auth error."""
        httpx_mock.add_response(
            url="https://slack.com/api/chat.postMessage",
            method="POST",
            status_code=200,
            json={"ok": False, "error": "invalid_auth"},
        )

        client = SlackClient(slack_settings)
        try:
            with pytest.raises(SlackAPIError) as exc_info:
                await client.send_message("C1234567890", "Test message")

            assert exc_info.value.error_code == "invalid_auth"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_not_in_channel_raises_slack_api_error(
        self, httpx_mock: HTTPXMock, slack_settings: SlackSettings
    ):
        """Test that send_message raises SlackAPIError on not_in_channel error."""
        httpx_mock.add_response(
            url="https://slack.com/api/chat.postMessage",
            method="POST",
            status_code=200,
            json={"ok": False, "error": "not_in_channel"},
        )

        client = SlackClient(slack_settings)
        try:
            with pytest.raises(SlackAPIError) as exc_info:
                await client.send_message("C1234567890", "Test message")

            assert exc_info.value.error_code == "not_in_channel"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_unknown_error_raises_slack_api_error(
        self, httpx_mock: HTTPXMock, slack_settings: SlackSettings
    ):
        """Test that send_message raises SlackAPIError for unknown errors."""
        httpx_mock.add_response(
            url="https://slack.com/api/chat.postMessage",
            method="POST",
            status_code=200,
            json={"ok": False, "error": "some_unknown_error"},
        )

        client = SlackClient(slack_settings)
        try:
            with pytest.raises(SlackAPIError) as exc_info:
                await client.send_message("C1234567890", "Test message")

            assert exc_info.value.error_code == "some_unknown_error"
        finally:
            await client.close()


class TestSlackClientRetryBehavior:
    """Test suite for SlackClient retry logic with exponential backoff."""

    @pytest.mark.asyncio
    @patch("asyncio.sleep", return_value=None)
    async def test_429_rate_limit_retries_then_succeeds(
        self,
        mock_sleep,
        httpx_mock: HTTPXMock,
        slack_settings_with_retries: SlackSettings,
    ):
        """Test that 429 rate limit error triggers retry and eventually succeeds.

        First request returns 429 (rate limited), second request succeeds with 200.
        """
        # First response: 429 Rate Limited
        httpx_mock.add_response(
            url="https://slack.com/api/chat.postMessage",
            method="POST",
            status_code=429,
            json={"ok": False, "error": "rate_limited"},
        )
        # Second response: 200 Success
        httpx_mock.add_response(
            url="https://slack.com/api/chat.postMessage",
            method="POST",
            status_code=200,
            json={"ok": True, "channel": "C1234567890", "ts": "1234567890.123456"},
        )

        client = SlackClient(slack_settings_with_retries)
        try:
            result = await client.send_message("C1234567890", "Test message")

            # Verify the call eventually succeeded
            assert result is True

            # Verify exactly 2 requests were made (initial 429 + successful retry)
            requests = httpx_mock.get_requests()
            assert len(requests) == 2
        finally:
            await client.close()

    @pytest.mark.asyncio
    @patch("asyncio.sleep", return_value=None)
    async def test_5xx_error_retries_then_fails(
        self,
        mock_sleep,
        httpx_mock: HTTPXMock,
        slack_settings_with_retries: SlackSettings,
    ):
        """Test that 5xx errors trigger retries and fail after max_retries.

        With max_retries=3, tenacity will make 3 total attempts.
        All 3 return 500, so SlackConnectionError should be raised.
        """
        # Mock 3 consecutive 500 responses
        httpx_mock.add_response(
            url="https://slack.com/api/chat.postMessage",
            method="POST",
            status_code=500,
            json={"error": "Internal Server Error"},
        )
        httpx_mock.add_response(
            url="https://slack.com/api/chat.postMessage",
            method="POST",
            status_code=500,
            json={"error": "Internal Server Error"},
        )
        httpx_mock.add_response(
            url="https://slack.com/api/chat.postMessage",
            method="POST",
            status_code=500,
            json={"error": "Internal Server Error"},
        )

        client = SlackClient(slack_settings_with_retries)
        try:
            with pytest.raises(SlackConnectionError) as exc_info:
                await client.send_message("C1234567890", "Test message")

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
    async def test_5xx_error_retries_then_succeeds(
        self,
        mock_sleep,
        httpx_mock: HTTPXMock,
        slack_settings_with_retries: SlackSettings,
    ):
        """Test that 5xx error triggers retry and succeeds on subsequent 200.

        First request returns 500 (server error), second request succeeds with 200.
        """
        # First response: 500 Server Error
        httpx_mock.add_response(
            url="https://slack.com/api/chat.postMessage",
            method="POST",
            status_code=500,
            json={"error": "Internal Server Error"},
        )
        # Second response: 200 Success
        httpx_mock.add_response(
            url="https://slack.com/api/chat.postMessage",
            method="POST",
            status_code=200,
            json={"ok": True, "channel": "C1234567890", "ts": "1234567890.123456"},
        )

        client = SlackClient(slack_settings_with_retries)
        try:
            result = await client.send_message("C1234567890", "Test message")

            # Verify the call eventually succeeded
            assert result is True

            # Verify exactly 2 requests were made (initial 500 + successful retry)
            requests = httpx_mock.get_requests()
            assert len(requests) == 2
        finally:
            await client.close()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status_code", [500, 502, 503, 504])
    @patch("asyncio.sleep", return_value=None)
    async def test_various_5xx_errors_trigger_retry(
        self,
        mock_sleep,
        httpx_mock: HTTPXMock,
        slack_settings_with_retries: SlackSettings,
        status_code: int,
    ):
        """Test that various 5xx server errors all trigger retry behavior.

        Tests 500, 502, 503, and 504 status codes.
        """
        # First response: 5xx error
        httpx_mock.add_response(
            url="https://slack.com/api/chat.postMessage",
            method="POST",
            status_code=status_code,
            json={"error": f"Server Error {status_code}"},
        )
        # Second response: success
        httpx_mock.add_response(
            url="https://slack.com/api/chat.postMessage",
            method="POST",
            status_code=200,
            json={"ok": True, "channel": "C1234567890", "ts": "1234567890.123456"},
        )

        client = SlackClient(slack_settings_with_retries)
        try:
            result = await client.send_message("C1234567890", "Test message")

            # Verify eventual success after retry
            assert result is True

            # Verify exactly 2 requests were made
            requests = httpx_mock.get_requests()
            assert len(requests) == 2
        finally:
            await client.close()


class TestSlackClientConnectionErrors:
    """Test suite for SlackClient handling of connection and network errors."""

    @pytest.mark.asyncio
    async def test_connection_error_raises_slack_connection_error(
        self, httpx_mock: HTTPXMock, slack_settings: SlackSettings
    ):
        """Test that send_message raises SlackConnectionError on network failure."""
        httpx_mock.add_exception(
            httpx.ConnectError("Connection refused"),
            url="https://slack.com/api/chat.postMessage",
            method="POST",
        )

        client = SlackClient(slack_settings)
        try:
            with pytest.raises(SlackConnectionError) as exc_info:
                await client.send_message("C1234567890", "Test message")

            assert "Failed to connect" in str(exc_info.value)
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_timeout_raises_slack_connection_error(
        self, httpx_mock: HTTPXMock, slack_settings: SlackSettings
    ):
        """Test that send_message raises SlackConnectionError on timeout."""
        httpx_mock.add_exception(
            httpx.TimeoutException("Request timed out"),
            url="https://slack.com/api/chat.postMessage",
            method="POST",
        )

        client = SlackClient(slack_settings)
        try:
            with pytest.raises(SlackConnectionError) as exc_info:
                await client.send_message("C1234567890", "Test message")

            assert "timed out" in str(exc_info.value)
        finally:
            await client.close()

    @pytest.mark.asyncio
    @patch("asyncio.sleep", return_value=None)
    async def test_connection_error_retries_then_fails(
        self,
        mock_sleep,
        httpx_mock: HTTPXMock,
        slack_settings_with_retries: SlackSettings,
    ):
        """Test that connection errors trigger retries and fail after max_retries."""
        # Mock 3 consecutive connection errors
        httpx_mock.add_exception(
            httpx.ConnectError("Connection refused"),
            url="https://slack.com/api/chat.postMessage",
            method="POST",
        )
        httpx_mock.add_exception(
            httpx.ConnectError("Connection refused"),
            url="https://slack.com/api/chat.postMessage",
            method="POST",
        )
        httpx_mock.add_exception(
            httpx.ConnectError("Connection refused"),
            url="https://slack.com/api/chat.postMessage",
            method="POST",
        )

        client = SlackClient(slack_settings_with_retries)
        try:
            with pytest.raises(SlackConnectionError) as exc_info:
                await client.send_message("C1234567890", "Test message")

            assert "Failed to connect" in str(exc_info.value)

            # Verify exactly 3 requests were made
            requests = httpx_mock.get_requests()
            assert len(requests) == 3
        finally:
            await client.close()

    @pytest.mark.asyncio
    @patch("asyncio.sleep", return_value=None)
    async def test_connection_error_retries_then_succeeds(
        self,
        mock_sleep,
        httpx_mock: HTTPXMock,
        slack_settings_with_retries: SlackSettings,
    ):
        """Test that connection error triggers retry and succeeds on next attempt."""
        # First attempt: connection error
        httpx_mock.add_exception(
            httpx.ConnectError("Connection refused"),
            url="https://slack.com/api/chat.postMessage",
            method="POST",
        )
        # Second attempt: success
        httpx_mock.add_response(
            url="https://slack.com/api/chat.postMessage",
            method="POST",
            status_code=200,
            json={"ok": True, "channel": "C1234567890", "ts": "1234567890.123456"},
        )

        client = SlackClient(slack_settings_with_retries)
        try:
            result = await client.send_message("C1234567890", "Test message")

            # Verify eventual success after retry
            assert result is True

            # Verify exactly 2 requests were made
            requests = httpx_mock.get_requests()
            assert len(requests) == 2
        finally:
            await client.close()


class TestSlackClientDMMessages:
    """Test suite for SlackClient sending DM messages."""

    @pytest.mark.asyncio
    async def test_send_dm_message_to_user(
        self, httpx_mock: HTTPXMock, slack_settings: SlackSettings
    ):
        """Test that send_message works with DM channel IDs (starting with D)."""
        httpx_mock.add_response(
            url="https://slack.com/api/chat.postMessage",
            method="POST",
            status_code=200,
            json={
                "ok": True,
                "channel": "D0987654321",
                "ts": "1234567890.654321",
            },
        )

        client = SlackClient(slack_settings)
        try:
            result = await client.send_message(
                "D0987654321", "Hello! This is a direct message."
            )
            assert result is True

            requests = httpx_mock.get_requests()
            assert len(requests) == 1

            import json

            payload = json.loads(requests[0].content)
            assert payload["channel"] == "D0987654321"
            assert payload["text"] == "Hello! This is a direct message."
        finally:
            await client.close()


class TestSlackClientLookupUserByEmail:
    """Test suite for SlackClient.lookup_user_by_email() method."""

    @pytest.mark.asyncio
    async def test_user_found_returns_user_id(
        self, httpx_mock: HTTPXMock, slack_settings: SlackSettings
    ):
        """Test that lookup_user_by_email returns user ID when user is found."""
        httpx_mock.add_response(
            url="https://slack.com/api/users.lookupByEmail?email=alice%40example.com",
            method="GET",
            status_code=200,
            json={"ok": True, "user": {"id": "U12345"}},
        )

        client = SlackClient(slack_settings)
        try:
            result = await client.lookup_user_by_email("alice@example.com")
            assert result == "U12345"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_user_not_found_returns_none(
        self, httpx_mock: HTTPXMock, slack_settings: SlackSettings
    ):
        """Test that lookup_user_by_email returns None when user is not found."""
        httpx_mock.add_response(
            url="https://slack.com/api/users.lookupByEmail?email=unknown%40example.com",
            method="GET",
            status_code=200,
            json={"ok": False, "error": "user_not_found"},
        )

        client = SlackClient(slack_settings)
        try:
            result = await client.lookup_user_by_email("unknown@example.com")
            assert result is None
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_api_error_returns_none(
        self, httpx_mock: HTTPXMock, slack_settings: SlackSettings
    ):
        """Test that lookup_user_by_email returns None on API auth error."""
        httpx_mock.add_response(
            url="https://slack.com/api/users.lookupByEmail?email=alice%40example.com",
            method="GET",
            status_code=200,
            json={"ok": False, "error": "invalid_auth"},
        )

        client = SlackClient(slack_settings)
        try:
            result = await client.lookup_user_by_email("alice@example.com")
            assert result is None
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_network_error_returns_none(
        self, httpx_mock: HTTPXMock, slack_settings: SlackSettings
    ):
        """Test that lookup_user_by_email returns None on network error."""
        httpx_mock.add_exception(
            httpx.ConnectError("Connection refused"),
            url="https://slack.com/api/users.lookupByEmail?email=alice%40example.com",
            method="GET",
        )

        client = SlackClient(slack_settings)
        try:
            result = await client.lookup_user_by_email("alice@example.com")
            assert result is None
        finally:
            await client.close()


class TestSlackClientSendBlocksMessage:
    """Test suite for SlackClient.send_blocks_message() method."""

    @pytest.mark.asyncio
    async def test_successful_blocks_message_returns_ts(
        self, httpx_mock: HTTPXMock, slack_settings: SlackSettings
    ):
        """Test that send_blocks_message returns ts on success and sends correct payload."""
        httpx_mock.add_response(
            url="https://slack.com/api/chat.postMessage",
            method="POST",
            status_code=200,
            json={"ok": True, "channel": "D123", "ts": "123.456"},
        )

        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": "Hello *world*"}},
        ]

        client = SlackClient(slack_settings)
        try:
            result = await client.send_blocks_message(
                "D123", blocks, "Hello world"
            )
            assert result == "123.456"

            requests = httpx_mock.get_requests()
            assert len(requests) == 1

            import json

            payload = json.loads(requests[0].content)
            assert payload["channel"] == "D123"
            assert payload["blocks"] == blocks
            assert payload["text"] == "Hello world"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_api_error_returns_none(
        self, httpx_mock: HTTPXMock, slack_settings: SlackSettings
    ):
        """Test that send_blocks_message returns None on API error."""
        httpx_mock.add_response(
            url="https://slack.com/api/chat.postMessage",
            method="POST",
            status_code=200,
            json={"ok": False, "error": "channel_not_found"},
        )

        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": "Hello"}},
        ]

        client = SlackClient(slack_settings)
        try:
            result = await client.send_blocks_message(
                "C0000000000", blocks, "Hello"
            )
            assert result is None
        finally:
            await client.close()
