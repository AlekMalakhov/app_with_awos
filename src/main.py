"""FastAPI application entry point with Jira credential validation on startup."""

import asyncio
import logging
import os
import sys
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

# Configure logging to show all module logs
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
# Set debug level for slack_bolt if DEBUG env var is set
if os.environ.get("DEBUG"):
    logging.getLogger("slack_bolt").setLevel(logging.DEBUG)
    logging.getLogger("src.slack").setLevel(logging.DEBUG)

from src.ai import ACGenerator, AISettings
from src.barley.client import BarleyClient
from src.barley.config import BarleySettings
from src.barley.service import BarleyEnrichmentService
from src.database import ConversationRepository
from src.database.repository import EscalationRepository
from src.jira.client import JiraClient
from src.jira.config import JiraSettings
from src.jira.exceptions import JiraAuthenticationError, JiraConnectionError
from src.polling import PollingService
from src.slack.client import SlackClient
from src.slack.config import SlackSettings
from src.slack.events import slack_router
from src.slack.services import SlackEscalationService
from src.slack.socket_mode import SlackSocketModeService

logger = logging.getLogger(__name__)

CLEANUP_INTERVAL_SECONDS = 24 * 60 * 60  # 24 hours


async def _resolve_bot_user_id(bot_token: str) -> str | None:
    """Resolve the bot's own Slack user ID via auth.test.

    Args:
        bot_token: The Slack bot OAuth token.

    Returns:
        The bot's user ID string, or None if resolution fails.
    """
    import httpx

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://slack.com/api/auth.test",
                headers={"Authorization": f"Bearer {bot_token}"},
            )
            data = resp.json()
            if data.get("ok"):
                user_id = data["user_id"]
                logger.info("Resolved bot user ID: %s", user_id)
                return user_id
            logger.warning("auth.test failed: %s", data.get("error"))
    except Exception:
        logger.warning("Failed to resolve bot user ID", exc_info=True)
    return None


async def _run_periodic_cleanup(repository: ConversationRepository) -> None:
    """Run periodic cleanup of stale and abandoned conversations.

    Executes every 24 hours, deleting conversations that are no longer
    needed. Logs results and handles exceptions gracefully so that
    cleanup failures never crash the application.

    Args:
        repository: ConversationRepository used to perform deletions.
    """
    while True:
        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
        try:
            stale_count = repository.delete_stale()
            abandoned_count = repository.delete_abandoned()
            logger.info(
                "Cleaned up %d stale and %d abandoned conversations",
                stale_count,
                abandoned_count,
            )
        except Exception:
            logger.exception("Error during conversation cleanup")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Lifespan context manager for FastAPI application.

    On startup:
        - Loads Jira settings from environment variables
        - Creates JiraClient and validates connection
        - Exits with code 1 if authentication or connection fails
        - Starts PollingService if polling_enabled is True

    On shutdown:
        - Stops PollingService if it was started
        - Closes the JiraClient connection
    """
    # Startup: load settings and validate Jira connection
    settings = JiraSettings()
    jira_client = JiraClient(settings)

    try:
        await jira_client.validate_connection()
        logger.info("Jira connection validated successfully")
    except JiraAuthenticationError as e:
        logger.error(f"Jira authentication failed: {e}")
        sys.exit(1)
    except JiraConnectionError as e:
        logger.error(f"Jira unreachable: {e}")
        sys.exit(1)

    # Create AI generator if API key is configured
    ai_settings = AISettings()
    ac_generator = ACGenerator(ai_settings) if ai_settings.is_enabled else None

    if ac_generator:
        logger.info("AI generation enabled with model: %s", ai_settings.ai_model)
    else:
        logger.warning("AI generation disabled (ANTHROPIC_API_KEY not set)")

    # Create Barley enrichment service if enabled
    barley_client = None
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
            logger.info("Barley enrichment enabled")
        else:
            logger.info("Barley enrichment disabled")
    except Exception:
        logger.info("Barley enrichment disabled")

    # Initialize Slack escalation service if configured
    slack_settings = None
    slack_client = None
    slack_escalation_service = None
    escalation_repository = None
    try:
        slack_settings = SlackSettings()
        if slack_settings.escalation_contact_email:
            slack_client = SlackClient(slack_settings)
            slack_escalation_service = SlackEscalationService(
                slack_client, slack_settings
            )
            escalation_repository = EscalationRepository()
            logger.info("Slack escalation service initialized")
    except Exception as e:
        logger.warning("Slack escalation service not available: %s", e)

    # Start polling service if enabled
    polling_service = None
    if settings.polling_enabled:
        if not settings.project_key:
            logger.error("JIRA_PROJECT_KEY required when polling is enabled")
            sys.exit(1)

        polling_service = PollingService(
            jira_client,
            settings,
            ac_generator,
            enrichment_service,
            escalation_service=slack_escalation_service,
            escalation_repository=escalation_repository,
            confidence_threshold=slack_settings.confidence_threshold
            if slack_settings
            else 0.7,
        )
        await polling_service.start()
        interval = settings.polling_interval_seconds
        logger.info(f"Polling service started (interval: {interval}s)")

    # Start Slack Socket Mode if enabled
    socket_mode_service = None
    try:
        if slack_settings is None:
            slack_settings = SlackSettings()
        if slack_settings.socket_mode_enabled:
            # Resolve bot's own user ID to filter self-messages
            bot_user_id = await _resolve_bot_user_id(slack_settings.bot_token)
            socket_mode_service = SlackSocketModeService(
                slack_settings, bot_user_id=bot_user_id
            )
            await socket_mode_service.start()
            logger.info("Slack Socket Mode service started")
    except Exception as e:
        logger.warning("Failed to start Slack Socket Mode: %s", e)
        # Don't exit - Socket Mode is optional, HTTP endpoint still works

    # Start background conversation cleanup task
    conversation_repo = ConversationRepository()
    cleanup_task = asyncio.create_task(_run_periodic_cleanup(conversation_repo))
    logger.info("Conversation cleanup task started (interval: 24h)")

    # Store client and services in app state for access in routes if needed
    app.state.jira_client = jira_client
    app.state.polling_service = polling_service
    app.state.socket_mode_service = socket_mode_service
    app.state.startup_time = time.monotonic()

    yield  # Application runs

    # Shutdown: cleanup
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
    conversation_repo.close()
    logger.info("Conversation cleanup task stopped")

    if socket_mode_service:
        await socket_mode_service.stop()
        logger.info("Slack Socket Mode service stopped")
    if polling_service:
        await polling_service.stop()
        logger.info("Polling service stopped")
    if escalation_repository:
        escalation_repository.close()
        logger.info("Escalation repository closed")
    if slack_client:
        await slack_client.close()
        logger.info("Slack client closed")
    if barley_client:
        await barley_client.close()
        logger.info("Barley client closed")
    await jira_client.close()


app = FastAPI(
    title="Jira AC Assistant",
    lifespan=lifespan,
)

# Register routers
app.include_router(slack_router, prefix="/slack")


@app.get("/health")
async def health_check() -> dict[str, str | float]:
    """Health check endpoint with component status reporting.

    Checks the status of Socket Mode, database connectivity, and
    reports application uptime. Returns an overall status of "healthy"
    when all components are operational, or "degraded" when any
    component reports an error or disconnected state.

    Returns:
        Dictionary with overall status, component statuses, and uptime.
    """
    # Check Socket Mode status
    socket_mode_service = getattr(app.state, "socket_mode_service", None)
    if socket_mode_service is None:
        slack_socket_mode = "disabled"
    elif socket_mode_service.is_running:
        slack_socket_mode = "connected"
    else:
        slack_socket_mode = "disconnected"

    # Check database connectivity
    try:
        repo = ConversationRepository()
        try:
            repo.get_by_id("health-check-ping")
            database = "ok"
        finally:
            repo.close()
    except Exception:
        database = "error"

    # Calculate uptime
    startup_time = getattr(app.state, "startup_time", None)
    if startup_time is not None:
        uptime_seconds = round(time.monotonic() - startup_time, 2)
    else:
        uptime_seconds = 0.0

    # Determine overall status
    is_degraded = (
        slack_socket_mode == "disconnected" or database == "error"
    )
    status = "degraded" if is_degraded else "healthy"

    return {
        "status": status,
        "slack_socket_mode": slack_socket_mode,
        "database": database,
        "uptime_seconds": uptime_seconds,
    }
