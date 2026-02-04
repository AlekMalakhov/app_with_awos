"""FastAPI application entry point with Jira credential validation on startup."""

import logging
import sys
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI

from src.jira.client import JiraClient
from src.jira.config import JiraSettings
from src.jira.exceptions import JiraAuthenticationError, JiraConnectionError
from src.polling import PollingService

logger = logging.getLogger(__name__)


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

    # Start polling service if enabled
    polling_service = None
    if settings.polling_enabled:
        if not settings.project_key:
            logger.error("JIRA_PROJECT_KEY required when polling is enabled")
            sys.exit(1)

        polling_service = PollingService(jira_client, settings)
        await polling_service.start()
        logger.info(f"Polling service started (interval: {settings.polling_interval_seconds}s)")

    # Store client and polling service in app state for access in routes if needed
    app.state.jira_client = jira_client
    app.state.polling_service = polling_service

    yield  # Application runs

    # Shutdown: cleanup
    if polling_service:
        await polling_service.stop()
        logger.info("Polling service stopped")
    await jira_client.close()


app = FastAPI(
    title="Jira AC Assistant",
    lifespan=lifespan,
)


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint.

    Returns:
        Dictionary with status indicating the application is healthy.
    """
    return {"status": "healthy"}
