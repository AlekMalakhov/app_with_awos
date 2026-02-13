"""Slack module - provides Slack API integration components."""

from src.slack.client import SlackClient
from src.slack.config import SlackSettings
from src.slack.events import slack_router
from src.slack.exceptions import SlackAPIError, SlackConnectionError, SlackError
from src.slack.handlers import DMHandler, Intent, IntentClassifier, IntentResult
from src.slack.models import (
    EscalationResult,
    SlackEvent,
    SlackEventPayload,
    SlackMessageResponse,
)
from src.slack.services import ACRegenerationService

__all__ = [
    "ACRegenerationService",
    "DMHandler",
    "EscalationResult",
    "Intent",
    "IntentClassifier",
    "IntentResult",
    "SlackClient",
    "SlackSettings",
    "SlackError",
    "SlackAPIError",
    "SlackConnectionError",
    "SlackMessageResponse",
    "SlackEvent",
    "SlackEventPayload",
    "slack_router",
]
