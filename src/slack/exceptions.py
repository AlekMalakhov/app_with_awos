"""Custom exceptions for Slack API operations."""


class SlackError(Exception):
    """Base exception for all Slack operations."""


class SlackAPIError(SlackError):
    """Raised when Slack API returns an error response (ok: false)."""

    def __init__(self, error_code: str, message: str | None = None) -> None:
        """Initialize the exception with error code and optional message.

        Args:
            error_code: The Slack API error code (e.g., "channel_not_found").
            message: Optional additional message.
        """
        self.error_code = error_code
        super().__init__(message or f"Slack API error: {error_code}")


class SlackConnectionError(SlackError):
    """Raised when Slack is unreachable after retries exhausted."""
