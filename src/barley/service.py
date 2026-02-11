"""Barley enrichment service for augmenting AC generation with project context."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.barley.config import BarleySettings
from src.barley.models import EnrichmentResult

if TYPE_CHECKING:
    from src.ai import ACGenerator
    from src.barley.client import BarleyClient

logger = logging.getLogger(__name__)


class BarleyEnrichmentService:
    """Orchestrates topic extraction and Barley context retrieval.

    Extracts key topics from a Jira ticket using the ACGenerator, then
    queries Barley for relevant project context and domain knowledge.
    When Barley is disabled, short-circuits and returns an empty result.
    """

    def __init__(
        self,
        barley_client: BarleyClient,
        ac_generator: ACGenerator,
        settings: BarleySettings,
    ) -> None:
        """Initialize the enrichment service.

        Args:
            barley_client: BarleyClient instance for querying project context.
            ac_generator: ACGenerator instance for topic extraction.
            settings: BarleySettings containing the enabled toggle.
        """
        self._barley_client = barley_client
        self._ac_generator = ac_generator
        self._settings = settings

    async def enrich(self, summary: str, description: str) -> EnrichmentResult:
        """Enrich a Jira ticket with Barley project context.

        Extracts topics from the ticket summary and description, then queries
        Barley to retrieve relevant domain knowledge. Returns an empty result
        when the Barley feature is disabled.

        Args:
            summary: Ticket summary/title.
            description: Ticket description text.

        Returns:
            EnrichmentResult containing the Barley context and extracted topics.
        """
        if not self._settings.enabled:
            logger.debug("Barley enrichment is disabled, skipping")
            return EnrichmentResult()

        logger.info("Starting Barley enrichment for ticket")

        topics = await self._ac_generator.extract_topics(summary, description)
        logger.debug("Extracted topics: %s", topics)

        prompt = (
            "Given a Jira ticket about the following topics, provide relevant "
            f"project context and domain knowledge: {topics}"
        )

        context = await self._barley_client.query(prompt)

        status = "received" if context else "unavailable"
        logger.info("Barley enrichment completed (context %s)", status)

        return EnrichmentResult(barley_context=context, topics_extracted=topics)
