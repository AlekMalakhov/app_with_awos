"""Slack API client for sending messages."""

import logging

import httpx
from tenacity import (
    RetryError,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from src.slack.config import SlackSettings
from src.slack.exceptions import SlackAPIError, SlackConnectionError
from src.slack.models import SlackMessageResponse

logger = logging.getLogger(__name__)

SLACK_API_BASE_URL = "https://slack.com/api"


class _RetryableHTTPError(Exception):
    """Internal exception to trigger retry on 5xx and 429 status codes."""

    pass


def _is_retryable_error(exception: BaseException) -> bool:
    """Determine if an exception should trigger a retry.

    Args:
        exception: The exception that was raised.

    Returns:
        True if the exception should trigger a retry, False otherwise.
    """
    # Retry on our custom retryable HTTP error (5xx and 429)
    if isinstance(exception, _RetryableHTTPError):
        return True
    # Retry on connection errors
    if isinstance(exception, httpx.RequestError):
        return True
    # Retry on timeout
    if isinstance(exception, httpx.TimeoutException):
        return True
    # Don't retry on other exceptions
    return False


class SlackClient:
    """Async client for Slack API operations.

    Uses Bot OAuth token for authentication.
    Provides message sending functionality with retry logic.
    """

    def __init__(self, settings: SlackSettings) -> None:
        """Initialize the Slack client with configuration settings.

        Args:
            settings: SlackSettings instance containing connection configuration.
        """
        self._settings = settings
        self._client = httpx.AsyncClient(
            base_url=SLACK_API_BASE_URL,
            headers=self._build_headers(),
        )

    def _build_headers(self) -> dict[str, str]:
        """Build HTTP headers with Bearer token authentication.

        Returns:
            Dictionary containing Authorization and Content-Type headers.
        """
        return {
            "Authorization": f"Bearer {self._settings.bot_token}",
            "Content-Type": "application/json",
        }

    async def send_message(self, channel_id: str, text: str) -> bool:
        """Send a message to a Slack channel or DM.

        Uses exponential backoff retry for transient errors (5xx, 429, network issues).

        Args:
            channel_id: The Slack channel ID (e.g., "C1234567890" for channels,
                "D1234567890" for DMs).
            text: The message text to send.

        Returns:
            True if the message was sent successfully.

        Raises:
            SlackAPIError: If the Slack API returns an error (ok: false).
            SlackConnectionError: If Slack is unreachable after retries exhausted.
        """

        @retry(
            stop=stop_after_attempt(self._settings.max_retries),
            wait=wait_exponential(multiplier=1, min=1, max=16),
            retry=retry_if_exception(_is_retryable_error),
            reraise=True,
        )
        async def _send_with_retry() -> SlackMessageResponse:
            response = await self._client.post(
                "/chat.postMessage",
                json={"channel": channel_id, "text": text},
            )

            # Check for HTTP-level errors that should trigger retry
            if response.status_code >= 500 or response.status_code == 429:
                raise _RetryableHTTPError(
                    f"Retryable HTTP error: {response.status_code}"
                )

            # Parse the response
            data = response.json()
            return SlackMessageResponse(**data)

        try:
            result = await _send_with_retry()

            # Check for Slack API-level errors
            if not result.ok:
                error_code = result.error or "unknown_error"
                logger.error(
                    "Slack API error when sending message to %s: %s",
                    channel_id,
                    error_code,
                )
                raise SlackAPIError(error_code)

            logger.info(
                "Successfully sent message to channel %s (ts: %s)",
                result.channel,
                result.ts,
            )
            return True

        except RetryError as e:
            # Retries exhausted - convert to SlackConnectionError
            last_exception = e.last_attempt.exception()
            if last_exception:
                raise SlackConnectionError(
                    f"Failed to connect to Slack after {self._settings.max_retries} "
                    f"retries: {last_exception}"
                ) from e
            raise SlackConnectionError(
                f"Failed to connect to Slack after {self._settings.max_retries} retries"
            ) from e
        except _RetryableHTTPError as e:
            # With reraise=True, the last exception is re-raised directly
            raise SlackConnectionError(
                f"Failed to connect to Slack after {self._settings.max_retries} "
                f"retries: {e}"
            ) from e
        except httpx.TimeoutException as e:
            raise SlackConnectionError(f"Request to Slack timed out: {e}") from e
        except httpx.RequestError as e:
            raise SlackConnectionError(f"Failed to connect to Slack: {e}") from e

    async def close(self) -> None:
        """Close the underlying HTTP client connection."""
        await self._client.aclose()
