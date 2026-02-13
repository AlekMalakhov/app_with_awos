"""Slack escalation service for sending low-confidence AC DMs to stakeholders.

This service orchestrates the full escalation flow: resolving a Slack user
by email, opening a DM channel, composing a Block Kit message with
confidence gaps, and sending the message.
"""

from __future__ import annotations

import logging

from src.slack.client import SlackClient
from src.slack.config import SlackSettings
from src.slack.models import EscalationResult

logger = logging.getLogger(__name__)


class SlackEscalationService:
    """Service for escalating low-confidence ACs to a stakeholder via Slack DM.

    Uses constructor injection for SlackClient and SlackSettings, consistent
    with the existing service patterns in this package.
    """

    def __init__(self, slack_client: SlackClient, settings: SlackSettings) -> None:
        """Initialize the escalation service.

        Args:
            slack_client: Async Slack API client for user lookup and messaging.
            settings: Slack configuration including escalation contact email.
        """
        self._client = slack_client
        self._settings = settings

    async def escalate(
        self,
        ticket_key: str,
        ticket_summary: str,
        ticket_url: str,
        confidence_gaps: list[str],
    ) -> EscalationResult:
        """Send an escalation DM to the configured stakeholder.

        Resolves the escalation contact by email, opens a DM channel,
        composes a Block Kit message listing confidence gaps, and sends it.
        Every error path returns an ``EscalationResult`` with ``sent=False``
        rather than raising an exception.

        Args:
            ticket_key: The Jira ticket key (e.g., "PROJ-123").
            ticket_summary: The ticket summary / title.
            ticket_url: Full URL to the Jira ticket.
            confidence_gaps: List of questions or gaps the AI identified.

        Returns:
            EscalationResult indicating whether the DM was sent and any error.
        """
        try:
            logger.info(
                "Starting escalation for ticket %s with %d confidence gaps",
                ticket_key,
                len(confidence_gaps),
            )

            # Step 1: Read escalation contact email
            email = self._settings.escalation_contact_email

            # Step 2: Guard – no email configured
            if email is None:
                logger.warning(
                    "No escalation contact email configured; skipping escalation "
                    "for ticket %s",
                    ticket_key,
                )
                return EscalationResult(
                    sent=False,
                    error="No escalation contact configured",
                )

            # Step 3: Resolve Slack user ID from email
            slack_user_id = await self._client.lookup_user_by_email(email)
            if slack_user_id is None:
                logger.warning(
                    "Could not find Slack user for email %s (ticket %s)",
                    email,
                    ticket_key,
                )
                return EscalationResult(
                    sent=False,
                    error=f"User not found for email: {email}",
                )

            # Step 4: Open a DM channel
            channel_id = await self._client.open_conversation(slack_user_id)
            if channel_id is None:
                logger.error(
                    "Failed to open DM channel with user %s for ticket %s",
                    slack_user_id,
                    ticket_key,
                )
                return EscalationResult(
                    sent=False,
                    slack_user_id=slack_user_id,
                    error="Failed to open DM channel",
                )

            # Step 5: Compose the Block Kit message
            blocks, fallback_text = self._compose_blocks(
                ticket_key, ticket_summary, ticket_url, confidence_gaps
            )

            # Step 6: Send the message
            success = await self._client.send_blocks_message(
                channel_id, blocks, fallback_text
            )

            if success:
                logger.info(
                    "Escalation DM sent successfully to user %s for ticket %s",
                    slack_user_id,
                    ticket_key,
                )
                return EscalationResult(sent=True, slack_user_id=slack_user_id)

            logger.error(
                "Failed to send escalation DM to user %s for ticket %s",
                slack_user_id,
                ticket_key,
            )
            return EscalationResult(
                sent=False,
                slack_user_id=slack_user_id,
                error="Failed to send DM",
            )

        except Exception:
            logger.exception(
                "Unexpected error during escalation for ticket %s", ticket_key
            )
            return EscalationResult(
                sent=False,
                error=f"Unexpected error during escalation for {ticket_key}",
            )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compose_blocks(
        ticket_key: str,
        ticket_summary: str,
        ticket_url: str,
        confidence_gaps: list[str],
    ) -> tuple[list[dict], str]:
        """Compose Block Kit blocks and fallback text for the escalation DM.

        Args:
            ticket_key: The Jira ticket key.
            ticket_summary: The ticket summary / title.
            ticket_url: Full URL to the Jira ticket.
            confidence_gaps: List of questions or gaps.

        Returns:
            A tuple of ``(blocks, fallback_text)``.
        """
        blocks: list[dict] = [
            # Header
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{ticket_key}: {ticket_summary}",
                },
            },
            # Jira link
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"<{ticket_url}|View in Jira>",
                },
            },
            # Divider
            {"type": "divider"},
            # Introduction
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "Hi! I've generated some draft acceptance criteria for "
                        "this ticket, but I have a few questions before they're "
                        "finalized:"
                    ),
                },
            },
            # Confidence gaps as bullet points
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "\n".join(f"\u2022 {gap}" for gap in confidence_gaps),
                },
            },
            # Footer
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": (
                            "These draft ACs have been added to the ticket "
                            "for reference."
                        ),
                    }
                ],
            },
        ]

        fallback_text = (
            f"Clarification needed for {ticket_key}: {ticket_summary}"
        )

        return blocks, fallback_text
