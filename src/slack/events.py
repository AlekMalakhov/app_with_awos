"""Slack Events API webhook endpoint for receiving events from Slack."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import time
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request, status

from src.ai import ACGenerator, AISettings
from src.database import ConversationRepository
from src.jira import JiraClient, JiraSettings
from src.slack.client import SlackClient
from src.slack.config import SlackSettings
from src.slack.handlers.dm_handler import DMHandler
from src.slack.handlers.intent_classifier import IntentClassifier
from src.slack.models import SlackEventPayload
from src.slack.services.regeneration_service import ACRegenerationService

logger = logging.getLogger(__name__)

slack_router = APIRouter(tags=["slack"])


def verify_slack_signature(
    signing_secret: str,
    timestamp: str,
    body: bytes,
    signature: str,
) -> bool:
    """Verify that a request is from Slack using HMAC-SHA256 signature.

    Args:
        signing_secret: The Slack signing secret for this app.
        timestamp: The X-Slack-Request-Timestamp header value.
        body: The raw request body bytes.
        signature: The X-Slack-Signature header value.

    Returns:
        True if the signature is valid, False otherwise.
    """
    # Check timestamp is not too old (prevent replay attacks)
    # Allow 5 minutes of clock drift
    try:
        if abs(time.time() - int(timestamp)) > 60 * 5:
            logger.warning("Slack request timestamp is too old: %s", timestamp)
            return False
    except ValueError:
        logger.warning("Invalid timestamp format: %s", timestamp)
        return False

    # Create signature base string
    sig_basestring = f"v0:{timestamp}:{body.decode('utf-8')}"

    # Calculate expected signature
    expected_sig = "v0=" + hmac.new(
        signing_secret.encode(),
        sig_basestring.encode(),
        hashlib.sha256,
    ).hexdigest()

    # Compare signatures using constant-time comparison
    return hmac.compare_digest(expected_sig, signature)


def _get_slack_settings() -> SlackSettings:
    """Get Slack settings from environment.

    Returns:
        SlackSettings instance loaded from environment variables.
    """
    return SlackSettings()


async def _process_dm_message(
    user_id: str,
    channel_id: str,
    text: str,
    settings: SlackSettings,
    event_ts: str | None = None,
) -> None:
    """Process a DM message in the background.

    Creates handler dependencies, processes the message, and sends any response.
    This function is designed to be run as a background task to avoid blocking
    the Slack events endpoint.

    Args:
        user_id: The Slack user ID who sent the message.
        channel_id: The Slack channel/DM ID where the message was received.
        text: The message text content.
        settings: SlackSettings for creating the Slack client.
        event_ts: Optional Slack event timestamp for deduplication.
    """
    repository = ConversationRepository()
    slack_client = SlackClient(settings)
    jira_client: JiraClient | None = None

    try:
        # Create Jira and AI dependencies for regeneration service
        jira_settings = JiraSettings()
        ai_settings = AISettings()

        jira_client = JiraClient(jira_settings)
        ac_generator = ACGenerator(ai_settings)

        regeneration_service = ACRegenerationService(
            jira_client=jira_client,
            ac_generator=ac_generator,
            conversation_repository=repository,
        )

        intent_classifier = IntentClassifier(ai_settings)

        handler = DMHandler(
            slack_client=slack_client,
            repository=repository,
            regeneration_service=regeneration_service,
            intent_classifier=intent_classifier,
            jira_settings=jira_settings,
        )
        response = await handler.handle_message(
            user_id, channel_id, text, event_ts=event_ts
        )

        if response:
            try:
                await slack_client.send_message(channel_id, response)
            except Exception as e:
                logger.error(
                    "Failed to send response to channel %s: %s",
                    channel_id,
                    e,
                )
    except Exception as e:
        logger.error(
            "Error processing DM message from user %s: %s",
            user_id,
            e,
        )
    finally:
        await slack_client.close()
        if jira_client is not None:
            await jira_client.close()
        repository.close()


@slack_router.post("/events")
async def slack_events(
    request: Request,
    x_slack_signature: str | None = Header(default=None),
    x_slack_request_timestamp: str | None = Header(default=None),
) -> dict[str, Any]:
    """Handle incoming Slack Events API webhooks.

    This endpoint handles two types of requests:
    1. URL Verification - Slack sends a challenge during app setup
       that must be echoed back.
    2. Event Callbacks - Actual events (like messages) that need processing.

    Args:
        request: The FastAPI request object.
        x_slack_signature: The Slack signature header for request verification.
        x_slack_request_timestamp: The timestamp header for signature verification.

    Returns:
        For url_verification: {"challenge": <challenge_value>}
        For event_callback: {"ok": True}

    Raises:
        HTTPException: 401 if signature verification fails.
    """
    # Read raw body for signature verification
    body = await request.body()

    # Parse the payload
    payload = SlackEventPayload.model_validate_json(body)

    # Handle URL verification (no signature verification needed for this)
    if payload.type == "url_verification":
        logger.info("Handling Slack URL verification challenge")
        return {"challenge": payload.challenge}

    # For all other requests, verify the signature
    if not x_slack_signature or not x_slack_request_timestamp:
        logger.warning("Missing Slack signature headers")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Slack signature headers",
        )

    settings = _get_slack_settings()

    if not verify_slack_signature(
        signing_secret=settings.signing_secret,
        timestamp=x_slack_request_timestamp,
        body=body,
        signature=x_slack_signature,
    ):
        logger.warning("Invalid Slack signature")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Slack signature",
        )

    # Handle event callbacks
    if payload.type == "event_callback" and payload.event:
        event = payload.event

        # Ignore bot messages to prevent potential loops
        if event.bot_id or event.subtype:
            logger.debug(
                "Ignoring bot/subtype message: bot_id=%s, subtype=%s",
                event.bot_id,
                event.subtype,
            )
            return {"ok": True}

        # Handle message events
        if event.type == "message":
            logger.info(
                "Received message event: user=%s, channel=%s, text=%s",
                event.user,
                event.channel,
                event.text[:50] if event.text else None,
            )

            # Process DM messages in background to return quickly
            if event.user and event.channel and event.text:
                asyncio.create_task(
                    _process_dm_message(
                        user_id=event.user,
                        channel_id=event.channel,
                        text=event.text,
                        settings=settings,
                        event_ts=event.ts,
                    )
                )

    # Return 200 OK immediately (Slack requires fast response)
    return {"ok": True}
