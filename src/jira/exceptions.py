class JiraError(Exception):
    """Base exception for all Jira operations"""


class JiraAuthenticationError(JiraError):
    """Raised when credentials are invalid or missing (401/403)"""


class JiraConnectionError(JiraError):
    """Raised when Jira is unreachable after retries exhausted"""


class JiraTicketNotFoundError(JiraError):
    """Raised when the requested ticket does not exist (404)"""


class JiraIssueTypeNotSupportedError(JiraError):
    """Raised when ticket's issue type is not in configured list"""
