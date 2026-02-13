"""DM Handler for processing incoming Slack direct messages.

This module handles incoming DM messages, extracts Jira ticket keys,
and manages conversation state transitions.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.database import ConversationRepository, ConversationState, ConversationStatus
from src.jira import (
    EmptyDescriptionError,
    JiraAuthenticationError,
    JiraConnectionError,
    JiraIssueTypeNotSupportedError,
    JiraTicketNotFoundError,
)
from src.slack.handlers.intent_classifier import Intent

if TYPE_CHECKING:
    from src.jira import JiraSettings
    from src.slack.client import SlackClient
    from src.slack.handlers.intent_classifier import IntentClassifier
    from src.slack.services.regeneration_service import ACRegenerationService


@dataclass
class DMResponse:
    """Response from the DM handler containing text and optional thread_ts.

    Attributes:
        text: The response message text.
        thread_ts: Optional Slack thread timestamp. When set, the response
            should be posted as a reply in that thread.
    """

    text: str
    thread_ts: str | None = None

logger = logging.getLogger(__name__)

# Maximum message length before truncation (Slack limit is ~4000)
MAX_MESSAGE_LENGTH = 3000
TRUNCATION_SUFFIX = "... (truncated)"

# Pattern to extract Jira ticket keys (e.g., PROJ-123, ABC-1)
TICKET_KEY_PATTERN = re.compile(r"([A-Z]+-\d+)")

# TTL for event deduplication cache entries (in seconds)
EVENT_DEDUP_TTL_SECONDS = 60


def format_comparison(conversation: ConversationState) -> str:
    """Format existing vs. new ACs for Slack display.

    Formats the comparison message showing both the existing acceptance criteria
    and the newly proposed acceptance criteria. Uses Slack markdown formatting
    with *bold* for headers and bullet points for criteria lists.

    Args:
        conversation: The conversation state containing ticket key, existing_acs,
            and proposed_acs.

    Returns:
        Formatted comparison message string. If the message exceeds MAX_MESSAGE_LENGTH,
        it will be truncated with a suffix indicator.
    """
    ticket_key = conversation.jira_ticket_key or "Unknown"
    existing_acs = conversation.existing_acs or []
    proposed_acs = conversation.proposed_acs or []

    # Build the message parts
    lines: list[str] = []

    # Ticket header
    lines.append(f"*Ticket:* {ticket_key}")
    lines.append("")

    # Existing ACs section
    lines.append("*Existing Acceptance Criteria:*")
    if existing_acs:
        for ac in existing_acs:
            lines.append(f"\u2022 {ac}")
    else:
        lines.append("(No existing acceptance criteria)")
    lines.append("")

    # Proposed ACs section
    lines.append("*Proposed New Acceptance Criteria:*")
    if proposed_acs:
        for ac in proposed_acs:
            lines.append(f"\u2022 {ac}")
    else:
        lines.append("(No proposed acceptance criteria)")
    lines.append("")

    # Instructions
    lines.append(
        'Reply with "approve" to update the ticket, "reject" to cancel, '
        "or describe what changes you'd like."
    )

    message = "\n".join(lines)

    # Truncate if necessary
    if len(message) > MAX_MESSAGE_LENGTH:
        truncate_at = MAX_MESSAGE_LENGTH - len(TRUNCATION_SUFFIX)
        message = message[:truncate_at] + TRUNCATION_SUFFIX

    return message


class DMHandler:
    """Handler for processing incoming Slack DM messages.

    Extracts Jira ticket keys from messages and manages conversation state.
    When a ticket key is found, creates a new conversation in FETCHING_TICKET state,
    triggers AC regeneration, and returns a comparison message.
    When no ticket key is found, prompts the user to provide one.
    When in COMPARING state and user approves, writes ACs to Jira.

    Attributes:
        _slack_client: SlackClient instance for sending responses.
        _repository: ConversationRepository for persisting conversation state.
        _regeneration_service: Optional ACRegenerationService for AC regeneration.
        _intent_classifier: Optional IntentClassifier for classifying user responses.
        _jira_settings: Optional JiraSettings for constructing Jira URLs.
    """

    def __init__(
        self,
        slack_client: SlackClient,
        repository: ConversationRepository,
        regeneration_service: ACRegenerationService | None = None,
        intent_classifier: IntentClassifier | None = None,
        jira_settings: JiraSettings | None = None,
    ) -> None:
        """Initialize the DM handler with dependencies.

        Args:
            slack_client: SlackClient instance for sending messages.
            repository: ConversationRepository for conversation state persistence.
            regeneration_service: Optional ACRegenerationService for AC regeneration.
                If provided, enables the full flow from ticket key to comparison.
            intent_classifier: Optional IntentClassifier for classifying user responses.
                If provided, enables intent classification for approval flow.
            jira_settings: Optional JiraSettings for constructing Jira ticket URLs.
        """
        self._slack_client = slack_client
        self._repository = repository
        self._regeneration_service = regeneration_service
        self._intent_classifier = intent_classifier
        self._jira_settings = jira_settings
        # In-memory cache for event deduplication: maps "ts:channel" -> seen_at timestamp
        self._seen_events: dict[str, float] = {}

    async def handle_message(
        self,
        user_id: str,
        channel_id: str,
        text: str,
        event_ts: str | None = None,
    ) -> DMResponse | None:
        """Process an incoming DM message and return response if needed.

        Extracts Jira ticket keys from the message text. If a ticket key is found,
        creates a new conversation with FETCHING_TICKET status. If no ticket key
        is found and there's no active conversation (or the active conversation
        is in AWAITING_TICKET state), returns a prompt message.

        When event_ts is provided, the handler will check for duplicate events
        using the ts+channel as a composite key. Events seen within the TTL
        window (60 seconds) are skipped to prevent duplicate processing from
        both HTTP webhook and Socket Mode channels.

        Args:
            user_id: The Slack user ID who sent the message.
            channel_id: The Slack channel/DM ID where the message was received.
            text: The message text content.
            event_ts: Optional Slack event timestamp for deduplication.

        Returns:
            DMResponse with text and optional thread_ts, or None if no response
            needed.
        """
        # Deduplicate events when event_ts is provided
        if event_ts is not None and self._is_duplicate_event(event_ts, channel_id):
            logger.info(
                "Skipping duplicate event: ts=%s, channel=%s",
                event_ts,
                channel_id,
            )
            return None

        logger.debug(
            "Processing DM message: user=%s, channel=%s, text=%s",
            user_id,
            channel_id,
            text[:50] if text else None,
        )

        # Try to extract a ticket key from the message
        ticket_key = self._extract_ticket_key(text)

        if ticket_key:
            # Create new conversation with FETCHING_TICKET status
            # Store event_ts as thread_ts so all replies go to this thread
            conversation = self._create_conversation(
                user_id=user_id,
                channel_id=channel_id,
                ticket_key=ticket_key,
                thread_ts=event_ts,
            )
            logger.info(
                "Created conversation %s for ticket %s (thread_ts=%s)",
                conversation.id,
                ticket_key,
                event_ts,
            )

            # If regeneration service is available, run full flow
            if self._regeneration_service is not None:
                try:
                    conversation = await self._regeneration_service.start_regeneration(
                        conversation=conversation,
                        ticket_key=ticket_key,
                    )
                    return DMResponse(
                        text=format_comparison(conversation),
                        thread_ts=conversation.slack_thread_ts,
                    )
                except JiraTicketNotFoundError:
                    error_msg = (
                        f"I couldn't find ticket {ticket_key} in Jira. "
                        "Please check the ticket key and try again."
                    )
                    self._set_conversation_error(conversation, error_msg)
                    return DMResponse(
                        text=error_msg,
                        thread_ts=conversation.slack_thread_ts,
                    )
                except EmptyDescriptionError:
                    error_msg = (
                        f"Ticket {ticket_key} doesn't have a description. "
                        "Please add a description in Jira and try again."
                    )
                    self._set_conversation_error(conversation, error_msg)
                    return DMResponse(
                        text=error_msg,
                        thread_ts=conversation.slack_thread_ts,
                    )
                except JiraIssueTypeNotSupportedError as exc:
                    error_msg = (
                        f"Ticket {ticket_key} has an unsupported issue type "
                        "for AC generation. "
                        f"{exc}"
                    )
                    self._set_conversation_error(conversation, error_msg)
                    return DMResponse(
                        text=error_msg,
                        thread_ts=conversation.slack_thread_ts,
                    )
                except JiraAuthenticationError:
                    error_msg = (
                        f"I don't have access to ticket {ticket_key}. "
                        "Please check that the ticket exists and that the bot "
                        "has the necessary permissions."
                    )
                    self._set_conversation_error(conversation, error_msg)
                    return DMResponse(
                        text=error_msg,
                        thread_ts=conversation.slack_thread_ts,
                    )
                except JiraConnectionError:
                    error_msg = (
                        "I'm having trouble connecting to Jira right now. "
                        "Please try again in a few minutes."
                    )
                    self._set_conversation_error(conversation, error_msg)
                    return DMResponse(
                        text=error_msg,
                        thread_ts=conversation.slack_thread_ts,
                    )

            # Fall back to simple acknowledgment if no service
            return DMResponse(
                text=f"Processing {ticket_key}...",
                thread_ts=conversation.slack_thread_ts,
            )

        # No ticket key found - check for active conversation
        active_conversation = self._repository.get_active(user_id, channel_id)

        if active_conversation is None:
            # No active conversation - prompt for ticket key (no thread)
            logger.debug("No active conversation found, prompting for ticket key")
            return DMResponse(text="Please provide a Jira ticket key (e.g., PROJ-123)")

        if active_conversation.status == ConversationStatus.AWAITING_TICKET:
            # Active conversation is waiting for a ticket key
            logger.debug(
                "Active conversation %s is in AWAITING_TICKET state",
                active_conversation.id,
            )
            return DMResponse(text="Please provide a Jira ticket key (e.g., PROJ-123)")

        if active_conversation.status == ConversationStatus.COMPARING:
            # User is responding to AC comparison - classify intent
            return await self._handle_comparing_response(active_conversation, text)

        # Check for stale processing states - these indicate a previous request
        # failed silently and left the conversation stuck
        stale_processing_states = {
            ConversationStatus.FETCHING_TICKET,
            ConversationStatus.GENERATING_ACS,
            ConversationStatus.WRITING_TO_JIRA,
        }
        if active_conversation.status in stale_processing_states:
            logger.warning(
                "Detected stale conversation %s in %s state, marking as ERROR",
                active_conversation.id,
                active_conversation.status.value,
            )
            self._set_conversation_error(
                active_conversation,
                f"Previous request for {active_conversation.jira_ticket_key} "
                "got stuck. Please try again.",
            )
            return DMResponse(
                text=(
                    "It looks like your previous request got stuck. "
                    "I've cleared it so you can start fresh. "
                    "Please provide a Jira ticket key (e.g., PROJ-123)"
                ),
            )

        # Active conversation is in another state (e.g., PROCESSING_MODIFICATION)
        logger.debug(
            "Active conversation %s is in %s state, no response needed",
            active_conversation.id,
            active_conversation.status.value,
        )
        return None

    async def _handle_comparing_response(
        self,
        conversation: ConversationState,
        text: str,
    ) -> DMResponse | None:
        """Handle user response when conversation is in COMPARING state.

        Classifies the user's intent and takes appropriate action:
        - APPROVE: Write ACs to Jira and return confirmation
        - REJECT: Cancel the conversation and keep original ACs
        - MODIFY: Regenerate ACs with user feedback and return new comparison

        Args:
            conversation: The active conversation in COMPARING state.
            text: The user's message text.

        Returns:
            DMResponse with text and thread_ts, or None if no response needed.
        """
        if self._intent_classifier is None or self._regeneration_service is None:
            logger.warning(
                "Cannot handle COMPARING response without intent_classifier "
                "and regeneration_service"
            )
            return None

        thread_ts = conversation.slack_thread_ts

        # Classify user intent
        intent_result = await self._intent_classifier.classify_intent(text)
        logger.info(
            "Classified intent for conversation %s: %s",
            conversation.id,
            intent_result.intent.value,
        )

        if intent_result.intent == Intent.APPROVE:
            # Write ACs to Jira
            await self._regeneration_service.approve_acs(conversation)

            # Build confirmation message with Jira link
            ticket_key = conversation.jira_ticket_key or "Unknown"
            ticket_url = self._build_jira_url(ticket_key)

            return DMResponse(
                text=f"Done! ACs updated on {ticket_key}. {ticket_url}",
                thread_ts=thread_ts,
            )

        if intent_result.intent == Intent.REJECT:
            # Cancel the conversation - original ACs remain unchanged
            await self._regeneration_service.reject_acs(conversation)
            logger.info(
                "Conversation %s cancelled by user rejection",
                conversation.id,
            )
            return DMResponse(
                text="Cancelled. Original ACs remain unchanged.",
                thread_ts=thread_ts,
            )

        if intent_result.intent == Intent.MODIFY:
            # Regenerate ACs with user feedback
            modification_request = intent_result.modification_request or text
            logger.info(
                "Processing modification request for conversation %s: %s",
                conversation.id,
                modification_request[:100] if modification_request else None,
            )

            # Regenerate ACs with the modification feedback
            updated_conversation = (
                await self._regeneration_service.regenerate_with_feedback(
                    conversation=conversation,
                    feedback=modification_request,
                )
            )

            # Return new comparison message
            return DMResponse(
                text=format_comparison(updated_conversation),
                thread_ts=thread_ts,
            )

        # Unknown intent - should not happen
        logger.warning(
            "Unknown intent %s for conversation %s",
            intent_result.intent.value,
            conversation.id,
        )
        return None

    def _is_duplicate_event(self, event_ts: str, channel_id: str) -> bool:
        """Check if an event has already been processed within the TTL window.

        Builds a composite dedup key from event_ts and channel_id, checks
        whether the key exists in the seen-events cache, and if not, records
        it. Also runs periodic cleanup of expired entries.

        Args:
            event_ts: The Slack message timestamp.
            channel_id: The Slack channel/DM ID.

        Returns:
            True if the event is a duplicate and should be skipped.
        """
        self._cleanup_expired_events()

        dedup_key = f"{event_ts}:{channel_id}"

        if dedup_key in self._seen_events:
            return True

        self._seen_events[dedup_key] = time.monotonic()
        return False

    def _cleanup_expired_events(self) -> None:
        """Remove expired entries from the seen-events cache.

        Entries older than EVENT_DEDUP_TTL_SECONDS are removed to keep
        the cache from growing unboundedly.
        """
        cutoff = time.monotonic() - EVENT_DEDUP_TTL_SECONDS
        expired_keys = [
            key for key, seen_at in self._seen_events.items() if seen_at < cutoff
        ]
        for key in expired_keys:
            del self._seen_events[key]

    def _build_jira_url(self, ticket_key: str) -> str:
        """Build the Jira ticket URL.

        Args:
            ticket_key: The Jira ticket key (e.g., "PROJ-123").

        Returns:
            Full URL to the Jira ticket, or empty string if settings not available.
        """
        if self._jira_settings is None:
            return ""
        base_url = self._jira_settings.base_url.rstrip("/")
        return f"{base_url}/browse/{ticket_key}"

    def _extract_ticket_key(self, text: str) -> str | None:
        """Extract the first Jira ticket key from message text.

        Uses regex pattern to find ticket keys in the format PROJECT-NUMBER
        (e.g., PROJ-123, ABC-1).

        Args:
            text: The message text to search.

        Returns:
            The first ticket key found, or None if no ticket key is present.
        """
        if not text:
            return None

        match = TICKET_KEY_PATTERN.search(text)
        if match:
            ticket_key = match.group(1)
            logger.debug("Extracted ticket key: %s", ticket_key)
            return ticket_key

        return None

    def _create_conversation(
        self,
        user_id: str,
        channel_id: str,
        ticket_key: str,
        thread_ts: str | None = None,
    ) -> ConversationState:
        """Create a new conversation record with FETCHING_TICKET status.

        Args:
            user_id: The Slack user ID who initiated the conversation.
            channel_id: The Slack channel/DM ID for the conversation.
            ticket_key: The Jira ticket key to process.
            thread_ts: Optional Slack message timestamp to use as thread parent.

        Returns:
            The created ConversationState.
        """
        conversation = ConversationState(
            id=str(uuid.uuid4()),
            slack_user_id=user_id,
            slack_channel_id=channel_id,
            jira_ticket_key=ticket_key,
            status=ConversationStatus.FETCHING_TICKET,
            slack_thread_ts=thread_ts,
        )

        return self._repository.create(conversation)

    def _set_conversation_error(
        self,
        conversation: ConversationState,
        error_message: str,
    ) -> None:
        """Update conversation status to ERROR and store the error message.

        Args:
            conversation: The conversation to update.
            error_message: The user-friendly error message to store.
        """
        conversation.status = ConversationStatus.ERROR
        conversation.error_message = error_message
        self._repository.update(conversation)
        logger.error(
            "Conversation %s set to ERROR: %s",
            conversation.id,
            error_message,
        )
