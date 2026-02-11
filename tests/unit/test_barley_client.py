"""Unit tests for BarleyClient query and connection management."""

import json

import httpx
import pytest
from pytest_httpx import HTTPXMock

from src.barley.client import BarleyClient
from src.barley.config import BarleySettings


@pytest.fixture
def barley_settings() -> BarleySettings:
    """Create BarleySettings with test values.

    Provides a minimal valid configuration for unit tests
    without reading from environment variables.
    """
    return BarleySettings(
        enabled=True,
        api_url="https://barley.test.example.com",
        api_token="test-barley-token-12345",
        timeout=30,
    )


COMPLETIONS_URL = "https://barley.test.example.com/v1/chat/completions"


def _make_chat_response(content: str) -> dict:
    """Build a valid OpenAI-compatible chat completions response."""
    return {
        "id": "chatcmpl-test-123",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    }


class TestBarleyClientQuery:
    """Test suite for BarleyClient.query() method."""

    @pytest.mark.asyncio
    async def test_successful_query_returns_content(
        self, httpx_mock: HTTPXMock, barley_settings: BarleySettings
    ):
        """Test that query returns the content string on a valid response."""
        httpx_mock.add_response(
            url=COMPLETIONS_URL,
            method="POST",
            status_code=200,
            json=_make_chat_response("Here are the acceptance criteria."),
        )

        client = BarleyClient(barley_settings)
        try:
            result = await client.query("Generate ACs for this ticket.")

            assert result == "Here are the acceptance criteria."
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_empty_choices_returns_none(
        self, httpx_mock: HTTPXMock, barley_settings: BarleySettings
    ):
        """Test that query returns None when response has empty choices array."""
        httpx_mock.add_response(
            url=COMPLETIONS_URL,
            method="POST",
            status_code=200,
            json={
                "id": "chatcmpl-test-456",
                "object": "chat.completion",
                "choices": [],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 0,
                    "total_tokens": 10,
                },
            },
        )

        client = BarleyClient(barley_settings)
        try:
            result = await client.query("Generate ACs for this ticket.")

            assert result is None
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_empty_content_returns_none(
        self, httpx_mock: HTTPXMock, barley_settings: BarleySettings
    ):
        """Test that query returns None when message content is None."""
        httpx_mock.add_response(
            url=COMPLETIONS_URL,
            method="POST",
            status_code=200,
            json={
                "id": "chatcmpl-test-789",
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": None},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 0,
                    "total_tokens": 10,
                },
            },
        )

        client = BarleyClient(barley_settings)
        try:
            result = await client.query("Generate ACs for this ticket.")

            assert result is None
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_missing_message_key_returns_none(
        self, httpx_mock: HTTPXMock, barley_settings: BarleySettings
    ):
        """Test that query returns None when choice lacks a message key."""
        httpx_mock.add_response(
            url=COMPLETIONS_URL,
            method="POST",
            status_code=200,
            json={
                "id": "chatcmpl-test-abc",
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 0,
                    "total_tokens": 10,
                },
            },
        )

        client = BarleyClient(barley_settings)
        try:
            result = await client.query("Generate ACs for this ticket.")

            assert result is None
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_timeout_returns_none(
        self, httpx_mock: HTTPXMock, barley_settings: BarleySettings
    ):
        """Test that query returns None on timeout without raising."""
        httpx_mock.add_exception(
            httpx.TimeoutException("Request timed out"),
            url=COMPLETIONS_URL,
            method="POST",
        )

        client = BarleyClient(barley_settings)
        try:
            result = await client.query("Generate ACs for this ticket.")

            assert result is None
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_401_unauthorized_returns_none(
        self, httpx_mock: HTTPXMock, barley_settings: BarleySettings
    ):
        """Test that query returns None on 401 Unauthorized."""
        httpx_mock.add_response(
            url=COMPLETIONS_URL,
            method="POST",
            status_code=401,
            json={"error": "Unauthorized"},
        )

        client = BarleyClient(barley_settings)
        try:
            result = await client.query("Generate ACs for this ticket.")

            assert result is None
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_403_forbidden_returns_none(
        self, httpx_mock: HTTPXMock, barley_settings: BarleySettings
    ):
        """Test that query returns None on 403 Forbidden."""
        httpx_mock.add_response(
            url=COMPLETIONS_URL,
            method="POST",
            status_code=403,
            json={"error": "Forbidden"},
        )

        client = BarleyClient(barley_settings)
        try:
            result = await client.query("Generate ACs for this ticket.")

            assert result is None
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_500_server_error_returns_none(
        self, httpx_mock: HTTPXMock, barley_settings: BarleySettings
    ):
        """Test that query returns None on 500 Internal Server Error."""
        httpx_mock.add_response(
            url=COMPLETIONS_URL,
            method="POST",
            status_code=500,
            json={"error": "Internal Server Error"},
        )

        client = BarleyClient(barley_settings)
        try:
            result = await client.query("Generate ACs for this ticket.")

            assert result is None
        finally:
            await client.close()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status_code", [500, 502, 503, 504])
    async def test_various_5xx_errors_return_none(
        self,
        httpx_mock: HTTPXMock,
        barley_settings: BarleySettings,
        status_code: int,
    ):
        """Test that various 5xx server errors all return None."""
        httpx_mock.add_response(
            url=COMPLETIONS_URL,
            method="POST",
            status_code=status_code,
            json={"error": f"Server Error {status_code}"},
        )

        client = BarleyClient(barley_settings)
        try:
            result = await client.query("Generate ACs for this ticket.")

            assert result is None
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_network_connection_error_returns_none(
        self, httpx_mock: HTTPXMock, barley_settings: BarleySettings
    ):
        """Test that query returns None on network connection failure."""
        httpx_mock.add_exception(
            httpx.ConnectError("Connection refused"),
            url=COMPLETIONS_URL,
            method="POST",
        )

        client = BarleyClient(barley_settings)
        try:
            result = await client.query("Generate ACs for this ticket.")

            assert result is None
        finally:
            await client.close()


class TestBarleyClientRequestPayload:
    """Test suite for verifying the correct request payload is sent."""

    @pytest.mark.asyncio
    async def test_query_sends_correct_model(
        self, httpx_mock: HTTPXMock, barley_settings: BarleySettings
    ):
        """Test that query sends the correct model name in the payload."""
        httpx_mock.add_response(
            url=COMPLETIONS_URL,
            method="POST",
            status_code=200,
            json=_make_chat_response("Response text"),
        )

        client = BarleyClient(barley_settings)
        try:
            await client.query("Test prompt")

            requests = httpx_mock.get_requests()
            assert len(requests) == 1

            payload = json.loads(requests[0].content)
            assert payload["model"] == "anth"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_query_sends_correct_messages(
        self, httpx_mock: HTTPXMock, barley_settings: BarleySettings
    ):
        """Test that query sends the prompt as a user message."""
        httpx_mock.add_response(
            url=COMPLETIONS_URL,
            method="POST",
            status_code=200,
            json=_make_chat_response("Response text"),
        )

        client = BarleyClient(barley_settings)
        try:
            await client.query("Generate ACs for user login feature.")

            requests = httpx_mock.get_requests()
            assert len(requests) == 1

            payload = json.loads(requests[0].content)
            assert payload["messages"] == [
                {"role": "user", "content": "Generate ACs for user login feature."}
            ]
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_query_sends_correct_temperature_and_max_tokens(
        self, httpx_mock: HTTPXMock, barley_settings: BarleySettings
    ):
        """Test that query sends the expected temperature and max_tokens values."""
        httpx_mock.add_response(
            url=COMPLETIONS_URL,
            method="POST",
            status_code=200,
            json=_make_chat_response("Response text"),
        )

        client = BarleyClient(barley_settings)
        try:
            await client.query("Test prompt")

            requests = httpx_mock.get_requests()
            assert len(requests) == 1

            payload = json.loads(requests[0].content)
            assert payload["temperature"] == 0.7
            assert payload["max_tokens"] == 3000
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_query_sends_correct_headers(
        self, httpx_mock: HTTPXMock, barley_settings: BarleySettings
    ):
        """Test that query includes correct Authorization and Content-Type headers."""
        httpx_mock.add_response(
            url=COMPLETIONS_URL,
            method="POST",
            status_code=200,
            json=_make_chat_response("Response text"),
        )

        client = BarleyClient(barley_settings)
        try:
            await client.query("Test prompt")

            requests = httpx_mock.get_requests()
            assert len(requests) == 1

            auth_header = requests[0].headers["Authorization"]
            assert auth_header == "Bearer test-barley-token-12345"
            assert requests[0].headers["Content-Type"] == "application/json"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_query_posts_to_correct_endpoint(
        self, httpx_mock: HTTPXMock, barley_settings: BarleySettings
    ):
        """Test that query sends the request to /v1/chat/completions."""
        httpx_mock.add_response(
            url=COMPLETIONS_URL,
            method="POST",
            status_code=200,
            json=_make_chat_response("Response text"),
        )

        client = BarleyClient(barley_settings)
        try:
            await client.query("Test prompt")

            requests = httpx_mock.get_requests()
            assert len(requests) == 1
            assert requests[0].method == "POST"
            assert requests[0].url.path == "/v1/chat/completions"
        finally:
            await client.close()


class TestBarleyClientClose:
    """Test suite for BarleyClient.close() method."""

    @pytest.mark.asyncio
    async def test_close_closes_httpx_client(
        self, barley_settings: BarleySettings
    ):
        """Test that close() properly closes the underlying httpx client."""
        client = BarleyClient(barley_settings)

        # Verify client is open (not closed)
        assert not client._client.is_closed

        await client.close()

        # Verify client is now closed
        assert client._client.is_closed

    @pytest.mark.asyncio
    async def test_close_can_be_called_multiple_times(
        self, barley_settings: BarleySettings
    ):
        """Test that calling close() multiple times does not raise."""
        client = BarleyClient(barley_settings)

        await client.close()
        # Second close should not raise
        await client.close()

        assert client._client.is_closed
