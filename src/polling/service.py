"""Background polling service for Jira ticket processing."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from src.database.models import ConversationState, ConversationStatus, EscalationRecord
from src.jira import JiraClient, JiraSettings, TicketData
from src.jira.ac_formatter import append_acs_to_description, validate_acs

if TYPE_CHECKING:
    from src.ai import ACGenerator
    from src.ai.models import ACGenerationResult
    from src.barley.service import BarleyEnrichmentService
    from src.database.repository import ConversationRepository, EscalationRepository
    from src.slack.services.escalation_service import SlackEscalationService

logger = logging.getLogger(__name__)


class PollingService:
    """Background service that polls Jira for unprocessed tickets.

    This service runs as an asyncio background task, periodically checking
    for new tickets that need acceptance criteria generation.
    """

    def __init__(
        self,
        jira_client: JiraClient,
        settings: JiraSettings,
        ac_generator: ACGenerator | None = None,
        enrichment_service: BarleyEnrichmentService | None = None,
        escalation_service: SlackEscalationService | None = None,
        escalation_repository: EscalationRepository | None = None,
        conversation_repository: ConversationRepository | None = None,
        confidence_threshold: float = 0.7,
    ) -> None:
        """Initialize the polling service.

        Args:
            jira_client: JiraClient instance for API operations.
            settings: JiraSettings containing polling configuration.
            ac_generator: Optional ACGenerator for AI-powered AC generation.
            enrichment_service: Optional BarleyEnrichmentService for enriching
                ticket descriptions with project context before AC generation.
            escalation_service: Optional SlackEscalationService for escalating
                low-confidence ACs to a stakeholder via Slack DM.
            escalation_repository: Optional EscalationRepository for persisting
                escalation records to the database.
            conversation_repository: Optional ConversationRepository for creating
                conversation state when escalation is sent (enables thread replies).
            confidence_threshold: Minimum confidence score (0.0-1.0) required to
                write ACs directly. Below this threshold, escalation is triggered.
        """
        self._client = jira_client
        self._settings = settings
        self._ac_generator = ac_generator
        self._enrichment_service = enrichment_service
        self._escalation_service = escalation_service
        self._escalation_repository = escalation_repository
        self._conversation_repository = conversation_repository
        self._confidence_threshold = confidence_threshold
        self._failure_counts: dict[str, int] = {}  # In-memory failure tracking
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._cycle_running: bool = False

    async def start(self) -> None:
        """Start the polling loop as a background task.

        This method is idempotent - calling it multiple times will not
        start additional polling loops.
        """
        if self._running:
            logger.warning("Polling service is already running")
            return

        logger.info("Starting polling service")
        self._running = True
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        """Gracefully stop the polling loop.

        Cancels the background task and waits for it to complete.
        """
        if not self._running:
            logger.warning("Polling service is not running")
            return

        logger.info("Stopping polling service")
        self._running = False

        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass  # Expected when task is cancelled
            self._task = None

        logger.info("Polling service stopped")

    async def _run_loop(self) -> None:
        """Main polling loop - runs until stopped.

        Executes poll cycles at intervals defined by settings.polling_interval_seconds.
        """
        logger.info(
            "Polling loop started with interval of %d seconds",
            self._settings.polling_interval_seconds,
        )

        while self._running:
            await self._poll_cycle()
            await asyncio.sleep(self._settings.polling_interval_seconds)

    async def _poll_cycle(self) -> None:
        """Execute a single polling cycle.

        Discovers tickets matching the JQL query and logs the count.
        Skips if a previous cycle is still running to prevent overlap.
        """
        if self._cycle_running:
            logger.warning("Previous poll cycle still running, skipping this cycle")
            return

        self._cycle_running = True
        try:
            jql = self._build_jql()
            logger.debug("Executing JQL: %s", jql)

            tickets = await self._client.search_tickets(jql)
            logger.info("Poll cycle: discovered %d tickets", len(tickets))

            # Process each discovered ticket
            for ticket in tickets:
                await self._process_ticket(ticket)
        finally:
            self._cycle_running = False

    def _build_jql(self) -> str:
        """Build the JQL query for ticket discovery.

        Returns:
            JQL query string that finds:
            - Tickets in the configured project
            - With configured issue types (Story, Task, etc.)
            - Without "ac-generated", "ac-generation-failed", or "regenerating" labels
            - Created within the lookback window
            - Ordered by created date ascending (oldest first)
        """
        return (
            f"project = {self._settings.project_key} "
            f"AND issuetype in ({self._settings.issue_types}) "
            f'AND (labels is EMPTY OR labels not in ("ac-generated", "ac-generation-failed", "regenerating")) '
            f"AND created >= -{self._settings.polling_lookback_days}d "
            f"ORDER BY created ASC"
        )

    def _has_existing_acs(self, description: str) -> bool:
        """Check if description already contains an Acceptance Criteria section.

        Checks for both markdown-formatted ACs (## Acceptance Criteria) and
        plain-text ACs extracted from Jira's ADF format (Acceptance Criteria
        without the ## prefix).

        Args:
            description: The ticket description text

        Returns:
            True if the description contains an AC section, False otherwise.
        """
        if not description:
            return False
        return "acceptance criteria" in description.lower()

    def _record_failure(self, ticket_key: str) -> int:
        """Record a failure and return the new failure count.

        Args:
            ticket_key: The ticket key (e.g., "IGAL-123")

        Returns:
            The new failure count for this ticket.
        """
        self._failure_counts[ticket_key] = self._failure_counts.get(ticket_key, 0) + 1
        return self._failure_counts[ticket_key]

    def _clear_failure(self, ticket_key: str) -> None:
        """Clear failure count for a successfully processed ticket.

        Args:
            ticket_key: The ticket key (e.g., "IGAL-123")
        """
        self._failure_counts.pop(ticket_key, None)

    async def _process_ticket(self, ticket: TicketData) -> bool:
        """Process a single ticket through the AC generation pipeline.

        Args:
            ticket: The ticket to process

        Returns:
            True if processing succeeded, False if skipped or failed.
        """
        # Check 1: Has description?
        if not ticket.description:
            logger.info("Skipping %s: empty description", ticket.key)
            return False

        # Check 2: Has existing ACs?
        if self._has_existing_acs(ticket.description):
            logger.info("Skipping %s: already has acceptance criteria", ticket.key)
            return False

        # Enrich description with parent hierarchy context
        enriched_description = ticket.description
        if ticket.parent_key:
            try:
                from src.jira.models import format_parent_chain

                chain = await self._client.get_parent_chain(
                    ticket.parent_key,
                )
                if chain:
                    enriched_description += (
                        "\n\n" + format_parent_chain(chain)
                    )
                    keys = [p.key for p in chain]
                    logger.info(
                        "Parent context applied for %s: %s",
                        ticket.key,
                        " -> ".join(keys),
                    )
            except Exception:
                logger.exception(
                    "Parent context fetch failed for %s, "
                    "proceeding without",
                    ticket.key,
                )

        # Enrich description with Barley project context (if available)
        if self._enrichment_service is not None:
            try:
                enrichment_result = await self._enrichment_service.enrich(
                    summary=ticket.summary,
                    description=ticket.description,
                )
                if enrichment_result.barley_context is not None:
                    enriched_description = (
                        f"{ticket.description}\n\n"
                        f"Additional Context from Barley:\n"
                        f"{enrichment_result.barley_context}"
                    )
                    logger.info(
                        "Barley enrichment applied for %s", ticket.key
                    )
                    logger.debug(
                        "Barley context for %s: %s",
                        ticket.key,
                        enrichment_result.barley_context,
                    )
                    await self._client.add_comment(
                        ticket.key, enrichment_result.barley_context
                    )
                else:
                    logger.debug(
                        "Barley enrichment returned no context for %s",
                        ticket.key,
                    )
            except Exception:
                logger.exception(
                    "Barley enrichment failed for %s, proceeding without context",
                    ticket.key,
                )

        # 1. Generate ACs using AI
        if self._ac_generator is None or not self._ac_generator.is_enabled:
            logger.warning("AI generation disabled, skipping %s", ticket.key)
            return False

        result = await self._ac_generator.generate(
            summary=ticket.summary,
            description=enriched_description,
        )
        generated_acs = result.acceptance_criteria

        if not generated_acs:
            logger.warning(
                "AI determined insufficient information for %s, skipping",
                ticket.key,
            )
            return False

        # 2. Validate ACs
        if not validate_acs(generated_acs, ticket.key):
            logger.warning("No valid ACs to write for %s", ticket.key)
            return False

        # 3. Confidence check: escalate if below threshold
        is_low_confidence = (
            result.confidence_score < self._confidence_threshold
            and self._escalation_service is not None
        )

        if is_low_confidence:
            generated_acs = await self._handle_low_confidence(
                ticket_key=ticket.key,
                summary=ticket.summary,
                result=result,
                generated_acs=generated_acs,
            )

        # 4. Get current ticket with description_adf
        try:
            current_ticket = await self._client.get_ticket(ticket.key)
        except Exception as e:
            logger.error("Failed to fetch ticket %s for AC write: %s", ticket.key, e)
            return False

        # 5. Format and append ACs to existing description
        updated_description = append_acs_to_description(
            existing_adf=current_ticket.description_adf,
            new_acs=generated_acs,
        )

        # 6. Write back to Jira
        if updated_description:
            ac_generation_success = await self._client.update_description(
                ticket.key, updated_description
            )
            if ac_generation_success:
                logger.info("Successfully wrote ACs to %s", ticket.key)
            else:
                logger.error("Failed to write ACs to %s after retries", ticket.key)
        else:
            logger.warning("No ACs to write for %s (empty result)", ticket.key)
            ac_generation_success = False

        if not ac_generation_success:
            # Record failure
            failure_count = self._record_failure(ticket.key)
            logger.warning(
                "AC generation failed for %s (attempt %d)", ticket.key, failure_count
            )

            # If max failures reached, add failed label
            if failure_count >= self._settings.polling_max_failures:
                await self._client.add_label(ticket.key, "ac-generation-failed")
                logger.error(
                    "Max failures reached for %s, added ac-generation-failed label",
                    ticket.key,
                )

            return False

        # Clear any previous failure count on success
        self._clear_failure(ticket.key)

        # Add label to mark ticket as processed
        label_added = await self._client.add_label(ticket.key, "ac-generated")
        if label_added:
            logger.info("Successfully processed %s at %s", ticket.key, datetime.now().isoformat())
        else:
            logger.warning("Processed %s but failed to add label", ticket.key)

        return True

    async def _handle_low_confidence(
        self,
        ticket_key: str,
        summary: str,
        result: ACGenerationResult,
        generated_acs: list[str],
    ) -> list[str]:
        """Handle low-confidence AC generation by escalating via Slack.

        Sends an escalation DM to the configured stakeholder, records the
        escalation in the database, and prepends an appropriate note to the
        generated ACs before they are written to Jira.

        Args:
            ticket_key: The Jira ticket key (e.g., "PROJ-123").
            summary: The ticket summary / title.
            result: The full ACGenerationResult from the AI generator.
            generated_acs: The list of generated AC strings.

        Returns:
            A new list of AC strings with a note/warning prepended at index 0.
        """
        # Build the Jira ticket URL
        ticket_url = f"{self._settings.base_url}/browse/{ticket_key}"

        logger.info(
            "Low confidence (%.2f < %.2f) for %s, escalating via Slack",
            result.confidence_score,
            self._confidence_threshold,
            ticket_key,
        )

        # Send escalation DM
        escalation_result = await self._escalation_service.escalate(
            ticket_key, summary, ticket_url, result.confidence_gaps
        )

        # Record escalation in the database
        if self._escalation_repository:
            record = EscalationRecord(
                id=str(uuid.uuid4()),
                jira_ticket_key=ticket_key,
                confidence_score=result.confidence_score,
                confidence_gaps=result.confidence_gaps,
                slack_user_id=escalation_result.slack_user_id,
                status="SENT" if escalation_result.sent else "FAILED",
                error_message=escalation_result.error,
            )
            self._escalation_repository.create(record)

        # Create conversation state so the user can reply in the thread
        if (
            escalation_result.sent
            and escalation_result.slack_user_id
            and escalation_result.channel_id
            and escalation_result.message_ts
            and self._conversation_repository
        ):
            conversation = ConversationState(
                id=str(uuid.uuid4()),
                slack_user_id=escalation_result.slack_user_id,
                slack_channel_id=escalation_result.channel_id,
                jira_ticket_key=ticket_key,
                status=ConversationStatus.COMPARING,
                proposed_acs=generated_acs,
                slack_thread_ts=escalation_result.message_ts,
            )
            self._conversation_repository.create(conversation)
            logger.info(
                "Created conversation %s for escalation thread %s (ticket %s)",
                conversation.id,
                escalation_result.message_ts,
                ticket_key,
            )

        # Prepend note/warning to the ACs
        if escalation_result.sent:
            note = (
                "Note: Clarification has been requested from the Product "
                "Owner. Please review the following draft acceptance criteria."
            )
            logger.info(
                "Escalation sent for %s, writing draft ACs with note",
                ticket_key,
            )
        else:
            note = (
                "Note: The system attempted to contact the Product Owner for "
                "clarification on the items below, but the message could not "
                "be delivered. Please review these ACs manually."
            )
            logger.warning(
                "Escalation failed for %s (%s), writing draft ACs with warning",
                ticket_key,
                escalation_result.error,
            )

        return [note, *generated_acs]
