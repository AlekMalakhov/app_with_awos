"""Pydantic models for Jira data structures."""

from __future__ import annotations

from pydantic import BaseModel


class TicketData(BaseModel):
    """Data model for Jira ticket information.

    Attributes:
        key: The Jira ticket key (e.g., "PROJ-123").
        summary: The ticket title/summary.
        description: Plain text description (empty string if null).
        description_adf: Raw Atlassian Document Format (for merging).
        issue_type: The issue type (e.g., "Story", "Task").
        parent_key: Key of the direct parent issue, or None.
    """

    key: str
    summary: str
    description: str
    description_adf: dict | None = None
    issue_type: str
    parent_key: str | None = None


class ParentContext(BaseModel):
    """Context extracted from a parent issue for AC enrichment.

    Represents one level in the issue hierarchy (e.g. a Story that is
    the parent of a Sub-task, or an Epic that is the parent of a Story).

    Attributes:
        key: The issue key (e.g., "PROJ-10").
        summary: The issue title/summary.
        description: The issue description as plain text.
        issue_type: The issue type (e.g., "Epic", "Story").
    """

    key: str
    summary: str
    description: str
    issue_type: str


def format_parent_chain(chain: list[ParentContext]) -> str:
    """Format a parent hierarchy into a context string.

    Produces a human-readable block that can be appended to the ticket
    description before sending it to the AC generator.  Nearest parent
    comes first, most distant ancestor last.

    Args:
        chain: Ordered list of parent contexts (nearest → farthest).

    Returns:
        Formatted string, or empty string if the chain is empty.
    """
    if not chain:
        return ""
    sections: list[str] = []
    for parent in chain:
        section = (
            f"Parent {parent.issue_type} ({parent.key}): "
            f"{parent.summary}"
        )
        if parent.description:
            section += f"\nDescription:\n{parent.description}"
        sections.append(section)
    return "\n\n".join(sections)
