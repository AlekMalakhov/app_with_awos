"""Custom exceptions for Barley API operations."""


class BarleyError(Exception):
    """Base exception for all Barley-related errors."""


class BarleyConnectionError(BarleyError):
    """Raised when Barley API is unreachable or request times out."""


class BarleyAuthenticationError(BarleyError):
    """Raised when authentication fails (401/403)."""
