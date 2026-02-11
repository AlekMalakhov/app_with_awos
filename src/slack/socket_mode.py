"""Slack Socket Mode handler for real-time event processing.

This module provides Socket Mode support for receiving Slack events via WebSocket
instead of HTTP webhooks. This is required when the Slack App is configured for
Socket Mode.

Supports both traditional DM messages and Slack AI Agent (Assistant) events:
- assistant_thread_started: When user starts a conversation with the assistant
- assistant_thread_context_changed: When context changes (user switches channels)
- message: Standard messages in DMs and assistant threads
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_bolt.async_app import AsyncApp

from src.ai import ACGenerator, AISettings
from src.barley.client import BarleyClient
from src.barley.config import BarleySettings
from src.barley.service import BarleyEnrichmentService
from src.database import ConversationRepository
from src.jira import JiraClient, JiraSettings
from src.slack.client import SlackClient
from src.slack.config import SlackSettings
from src.slack.handlers.dm_handler import DMHandler
from src.slack.handlers.intent_classifier import IntentClassifier
from src.slack.services.regeneration_service import ACRegenerationService

if TYPE_CHECKING:
    from slack_bolt.async_app import AsyncSay

logger = logging.getLogger(__name__)

# Default welcome message for assistant threads
DEFAULT_WELCOME_MESSAGE = (
    "Hello! I can help you regenerate acceptance criteria for Jira tickets. "
    "Just provide a ticket key like PROJ-123."
)

# Default suggested prompts for assistant threads
DEFAULT_SUGGESTED_PROMPTS = [
    {
        "title": "Regenerate ACs",
        "message": "Regenerate acceptance criteria for PROJ-123",
    },
    {
        "title": "Help",
        "message": "What can you help me with?",
    },
]


class SlackSocketModeService:
    """Service for managing Slack Socket Mode connection.

    Handles the WebSocket connection to Slack for receiving real-time events.
    Routes incoming DM messages to the existing DMHandler for processing.

    Attributes:
        _settings: SlackSettings for configuration.
        _app: The slack_bolt AsyncApp instance.
        _handler: The AsyncSocketModeHandler for managing the WebSocket.
        _running: Flag indicating if the service is currently running.
    """

    def __init__(self, settings: SlackSettings) -> None:
        """Initialize the Socket Mode service.

        Args:
            settings: SlackSettings containing bot_token and app_token.
        """
        self._settings = settings
        self._running = False

        # Create the Bolt app with bot token
        self._app = AsyncApp(token=settings.bot_token)

        # Create the Socket Mode handler with app token
        self._handler = AsyncSocketModeHandler(self._app, settings.app_token)

        # Register event handlers
        self._register_handlers()

        logger.info("SlackSocketModeService initialized")

    def _register_handlers(self) -> None:
        """Register event handlers for the Bolt app.

        Registers handlers for:
        - assistant_thread_started: When user opens conversation with AI Agent
        - assistant_thread_context_changed: When context changes in assistant thread
        - message: Standard messages in DMs and assistant threads
        """
        self._register_assistant_thread_started_handler()
        self._register_assistant_thread_context_changed_handler()
        self._register_message_handler()

    def _register_assistant_thread_started_handler(self) -> None:
        """Register handler for assistant_thread_started event.

        This event fires when a user starts a conversation with the Slack AI Agent.
        We acknowledge it, set an initial status, suggest prompts, and send
        a welcome message.
        """

        @self._app.event("assistant_thread_started")
        async def handle_assistant_thread_started(
            event: dict[str, Any],
            say: AsyncSay,
            set_status: Callable[[str], None],
            set_suggested_prompts: Callable[[list[dict[str, str]]], None],
        ) -> None:
            """Handle assistant thread started event.

            Sets initial status, suggested prompts, and sends welcome message.

            Args:
                event: The Slack event payload.
                say: Function to send a response message.
                set_status: Function to set the assistant status indicator.
                set_suggested_prompts: Function to set suggested prompts for the user.
            """
            logger.info(
                "Assistant thread started: event=%s",
                {k: v for k, v in event.items() if k != "assistant_thread"},
            )

            try:
                # Set status to indicate the assistant is ready
                set_status("is ready to help...")

                # Set suggested prompts to guide the user
                set_suggested_prompts(DEFAULT_SUGGESTED_PROMPTS)

                # Send welcome message
                await say(text=DEFAULT_WELCOME_MESSAGE)

                logger.debug("Assistant thread started handler completed successfully")

            except Exception as e:
                logger.error(
                    "Error handling assistant_thread_started: %s",
                    e,
                    exc_info=True,
                )

    def _register_assistant_thread_context_changed_handler(self) -> None:
        """Register handler for assistant_thread_context_changed event.

        This event fires when the context changes in an assistant thread,
        such as when the user switches to a different channel.
        """

        @self._app.event("assistant_thread_context_changed")
        async def handle_assistant_thread_context_changed(
            event: dict[str, Any],
            say: AsyncSay,
        ) -> None:
            """Handle assistant thread context changed event.

            Logs the context change. Can be extended to take action based on
            the new context (e.g., channel the user is viewing).

            Args:
                event: The Slack event payload containing context information.
                say: Function to send a response message.
            """
            # Extract context information if available
            assistant_thread = event.get("assistant_thread", {})
            context = assistant_thread.get("context", {})

            logger.info(
                "Assistant thread context changed: channel_id=%s, context=%s",
                context.get("channel_id"),
                context,
            )

            # Currently we just log the context change.
            # Future enhancement: Could provide context-aware suggestions
            # based on the channel the user is viewing.

    def _register_message_handler(self) -> None:
        """Register handler for message events.

        Handles both traditional DM messages and messages in assistant threads.
        """

        @self._app.event("message")
        async def handle_message_event(
            event: dict[str, Any],
            say: AsyncSay,
            set_status: Callable[[str], None] | None = None,
        ) -> None:
            """Handle incoming message events.

            Filters out bot messages and routes DM/assistant thread messages
            to DMHandler.

            Args:
                event: The Slack event payload containing user, channel, text, etc.
                say: Function to send a response message.
                set_status: Optional function to set assistant status (available
                    in assistant threads).
            """
            # Ignore bot messages to prevent loops
            if event.get("bot_id") or event.get("subtype"):
                logger.debug(
                    "Ignoring bot/subtype message: bot_id=%s, subtype=%s",
                    event.get("bot_id"),
                    event.get("subtype"),
                )
                return

            user_id = event.get("user")
            channel_id = event.get("channel")
            text = event.get("text", "")
            event_ts = event.get("ts")
            channel_type = event.get("channel_type")

            if not user_id or not channel_id:
                logger.warning(
                    "Message event missing user or channel: %s",
                    event,
                )
                return

            # Check if this is an assistant thread message
            is_assistant_thread = channel_type == "im" and event.get(
                "assistant_thread"
            )

            logger.info(
                "Received message via Socket Mode: user=%s, channel=%s, "
                "text=%s, channel_type=%s, is_assistant_thread=%s",
                user_id,
                channel_id,
                text[:50] if text else None,
                channel_type,
                is_assistant_thread,
            )

            # Set status if in assistant thread and set_status is available
            if set_status is not None:
                try:
                    set_status("is thinking...")
                except Exception as e:
                    logger.debug("Could not set status: %s", e)

            # Process the message using DMHandler
            response = await self._process_message(
                user_id, channel_id, text, event_ts=event_ts
            )

            if response:
                await say(text=response)

    async def _process_message(
        self,
        user_id: str,
        channel_id: str,
        text: str,
        event_ts: str | None = None,
    ) -> str | None:
        """Process a DM message using the DMHandler.

        Creates all necessary dependencies, processes the message, and returns
        the response. Resources are cleaned up after processing.

        Args:
            user_id: The Slack user ID who sent the message.
            channel_id: The Slack channel/DM ID.
            text: The message text content.
            event_ts: Optional Slack event timestamp for deduplication.

        Returns:
            Response message to send back, or None if no response needed.
        """
        repository = ConversationRepository()
        slack_client = SlackClient(self._settings)
        jira_client: JiraClient | None = None
        barley_client: BarleyClient | None = None

        try:
            # Create Jira and AI dependencies for regeneration service
            jira_settings = JiraSettings()
            ai_settings = AISettings()

            jira_client = JiraClient(jira_settings)
            ac_generator = ACGenerator(ai_settings)

            # Create Barley enrichment service if enabled
            enrichment_service = None
            try:
                barley_settings = BarleySettings()
                if barley_settings.enabled:
                    barley_client = BarleyClient(settings=barley_settings)
                    enrichment_service = BarleyEnrichmentService(
                        barley_client=barley_client,
                        ac_generator=ac_generator,
                        settings=barley_settings,
                    )
            except Exception:
                logger.debug("Barley enrichment not available for Socket Mode processing")

            regeneration_service = ACRegenerationService(
                jira_client=jira_client,
                ac_generator=ac_generator,
                conversation_repository=repository,
                enrichment_service=enrichment_service,
            )

            intent_classifier = IntentClassifier(ai_settings)

            handler = DMHandler(
                slack_client=slack_client,
                repository=repository,
                regeneration_service=regeneration_service,
                intent_classifier=intent_classifier,
                jira_settings=jira_settings,
            )

            return await handler.handle_message(
                user_id, channel_id, text, event_ts=event_ts
            )

        except Exception as e:
            logger.error(
                "Error processing message from user %s: %s",
                user_id,
                e,
                exc_info=True,
            )
            return None
        finally:
            await slack_client.close()
            if barley_client is not None:
                await barley_client.close()
            if jira_client is not None:
                await jira_client.close()
            repository.close()

    async def start(self) -> None:
        """Start the Socket Mode connection.

        Establishes the WebSocket connection to Slack and begins listening
        for events. This method runs the connection in a background task
        and returns immediately.

        Raises:
            RuntimeError: If the service is already running.
        """
        if self._running:
            raise RuntimeError("Socket Mode service is already running")

        logger.info("Starting Slack Socket Mode connection...")

        # Start the handler in a background task
        self._running = True
        asyncio.create_task(self._run_handler())

        logger.info("Slack Socket Mode connection started")

    async def _run_handler(self) -> None:
        """Run the Socket Mode handler.

        This is executed as a background task and will reconnect automatically
        on disconnection.
        """
        try:
            await self._handler.start_async()
        except Exception as e:
            logger.error("Socket Mode handler error: %s", e, exc_info=True)
            self._running = False

    async def stop(self) -> None:
        """Stop the Socket Mode connection gracefully.

        Closes the WebSocket connection and cleans up resources.
        """
        if not self._running:
            logger.debug("Socket Mode service is not running")
            return

        logger.info("Stopping Slack Socket Mode connection...")

        try:
            await self._handler.close_async()
        except Exception as e:
            logger.warning("Error closing Socket Mode handler: %s", e)

        self._running = False
        logger.info("Slack Socket Mode connection stopped")

    @property
    def is_running(self) -> bool:
        """Check if the Socket Mode service is currently running.

        Returns:
            True if the service is running, False otherwise.
        """
        return self._running
