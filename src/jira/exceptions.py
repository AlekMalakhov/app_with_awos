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


class EmptyDescriptionError(JiraError):
    """Raised when a Jira ticket has no description"""

    def __init__(self, ticket_key: str) -> None:
        """Initialize the error with the ticket key.

        Args:
            ticket_key: The Jira ticket key that has no description.
        """
        self.ticket_key = ticket_key
        super().__init__(f"Ticket {ticket_key} has no description")
