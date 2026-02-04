"""Pydantic models for Jira data structures."""

from pydantic import BaseModel


class TicketData(BaseModel):
    """Data model for Jira ticket information.

    Attributes:
        key: The Jira ticket key (e.g., "PROJ-123").
        summary: The ticket title/summary.
        description: The ticket description as plain text (empty string if null in Jira).
        description_adf: The raw description in Atlassian Document Format (for merging).
        issue_type: The issue type (e.g., "Story", "Task").
    """

    key: str
    summary: str
    description: str
    description_adf: dict | None = None
    issue_type: str
