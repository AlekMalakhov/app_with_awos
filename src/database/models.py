"""Pydantic models for conversation state persistence."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, Field


def _utc_now_iso() -> str:
    """Return current UTC time as ISO format string."""
    return datetime.now(UTC).isoformat()


class ConversationStatus(str, Enum):
    """Enum representing the possible states of a conversation.

    States:
        AWAITING_TICKET: Initial state, waiting for ticket key
        FETCHING_TICKET: Fetching ticket from Jira
        GENERATING_ACS: AI is generating new ACs
        COMPARING: Showing comparison to user
        AWAITING_APPROVAL: Waiting for approve/reject/modify
        PROCESSING_MODIFICATION: Processing user's modification request
        WRITING_TO_JIRA: Writing approved ACs to Jira
        COMPLETED: Successfully written
        CANCELLED: User cancelled
        ERROR: Error state
    """

    AWAITING_TICKET = "AWAITING_TICKET"
    FETCHING_TICKET = "FETCHING_TICKET"
    GENERATING_ACS = "GENERATING_ACS"
    COMPARING = "COMPARING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    PROCESSING_MODIFICATION = "PROCESSING_MODIFICATION"
    WRITING_TO_JIRA = "WRITING_TO_JIRA"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    ERROR = "ERROR"


class MessageRecord(BaseModel):
    """Record of a single message in the conversation history.

    Attributes:
        role: The role of the message sender (e.g., "user", "assistant", "system").
        content: The content of the message.
        timestamp: ISO format timestamp of when the message was sent.
    """

    role: str
    content: str
    timestamp: str = Field(default_factory=_utc_now_iso)


class ConversationState(BaseModel):
    """Model representing the state of a conversation.

    Attributes:
        id: UUID identifier for the conversation.
        slack_user_id: Slack user who initiated the conversation.
        slack_channel_id: DM channel ID where the conversation takes place.
        jira_ticket_key: Ticket being processed (nullable).
        status: Current conversation state.
        existing_acs: JSON array of existing AC strings (nullable).
        proposed_acs: JSON array of newly generated AC strings (nullable).
        description_adf: Original ticket description in ADF format for merging (nullable).
        error_message: Error message when conversation is in ERROR status (nullable).
        message_history: JSON array of message records for context.
        created_at: ISO format creation timestamp.
        updated_at: ISO format last update timestamp.
    """

    id: str
    slack_user_id: str
    slack_channel_id: str
    jira_ticket_key: str | None = None
    status: ConversationStatus = ConversationStatus.AWAITING_TICKET
    existing_acs: list[str] | None = None
    proposed_acs: list[str] | None = None
    description_adf: dict | None = None
    error_message: str | None = None
    message_history: list[MessageRecord] = Field(default_factory=list)
    created_at: str = Field(default_factory=_utc_now_iso)
    updated_at: str = Field(default_factory=_utc_now_iso)
