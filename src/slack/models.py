"""Pydantic models for Slack API data structures."""

from __future__ import annotations

from pydantic import BaseModel


class SlackMessageResponse(BaseModel):
    """Response model for Slack chat.postMessage API.

    Attributes:
        ok: Whether the API call was successful.
        error: Error code if the call failed (None if successful).
        channel: The channel ID where the message was posted (if successful).
        ts: The timestamp of the posted message (if successful).
    """

    ok: bool
    error: str | None = None
    channel: str | None = None
    ts: str | None = None


class SlackEvent(BaseModel):
    """Model for a Slack event object within an event_callback payload.

    Attributes:
        type: The type of event (e.g., "message").
        user: The user ID who triggered the event (optional for bot messages).
        channel: The channel ID where the event occurred.
        text: The text content of the message (optional).
        ts: The timestamp of the event.
        subtype: The subtype of the event (e.g., "bot_message", "message_changed").
        bot_id: The bot ID if this message was sent by a bot.
    """

    type: str
    user: str | None = None
    channel: str
    text: str | None = None
    ts: str
    subtype: str | None = None
    bot_id: str | None = None


class SlackEventPayload(BaseModel):
    """Model for the full Slack Events API webhook payload.

    This model handles both url_verification and event_callback request types.

    Attributes:
        type: The payload type ("url_verification" or "event_callback").
        challenge: The challenge string for URL verification
            (only present for url_verification).
        event: The event object (only present for event_callback).
        event_id: Unique identifier for this event
            (only present for event_callback).
        token: Deprecated verification token (present in all payloads).
    """

    type: str
    challenge: str | None = None
    event: SlackEvent | None = None
    event_id: str | None = None
    token: str | None = None
