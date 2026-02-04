"""Exception hierarchy for AI operations."""


class AIError(Exception):
    """Base exception for AI operations."""


class AIConfigurationError(AIError):
    """Raised when AI is not properly configured."""


class AIRateLimitError(AIError):
    """Raised when API rate limit is exceeded."""


class AIInvalidResponseError(AIError):
    """Raised when AI response cannot be parsed."""
