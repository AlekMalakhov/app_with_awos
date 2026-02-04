"""Pydantic models for Jira data structures."""

from pydantic import BaseModel


class TicketData(BaseModel):
    """Data model for Jira ticket information.

    Attributes:
        key: The Jira ticket key (e.g., "PROJ-123").
        summary: The ticket title/summary.
        description: The ticket description (empty string if null in Jira).
        issue_type: The issue type (e.g., "Story", "Task").
    """

    key: str
    summary: str
    description: str
    issue_type: str
