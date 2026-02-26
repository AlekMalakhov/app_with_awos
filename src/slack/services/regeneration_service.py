"""AC Regeneration service for orchestrating Jira ticket AC regeneration workflow.

This service coordinates fetching tickets from Jira, extracting existing ACs,
and generating new ACs via the AI generator, updating conversation state
throughout the process.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from src.database import ConversationRepository, ConversationState, ConversationStatus
from src.jira import (
    EmptyDescriptionError,
    JiraClient,
    extract_acs_from_adf,
    replace_acs_in_adf,
)

if TYPE_CHECKING:
    from src.ai import ACGenerator
    from src.barley.service import BarleyEnrichmentService

# Type alias for an async callback that receives a status message string.
ProgressCallback = Callable[[str], Awaitable[None]]

logger = logging.getLogger(__name__)


class ACRegenerationService:
    """Service for orchestrating the AC regeneration workflow.

    Coordinates between JiraClient, ACGenerator, and ConversationRepository
    to fetch ticket data, extract existing ACs, generate new ACs, and
    manage conversation state transitions.
    """

    def __init__(
        self,
        jira_client: JiraClient,
        ac_generator: ACGenerator,
        conversation_repository: ConversationRepository,
        enrichment_service: BarleyEnrichmentService | None = None,
    ) -> None:
        """Initialize the AC regeneration service.

        Args:
            jira_client: Client for fetching ticket data from Jira.
            ac_generator: AI-powered acceptance criteria generator.
            conversation_repository: Repository for persisting conversation state.
            enrichment_service: Optional BarleyEnrichmentService for enriching
                ticket descriptions with project context before AC generation.
        """
        self._jira_client = jira_client
        self._ac_generator = ac_generator
        self._repository = conversation_repository
        self._enrichment_service = enrichment_service

    async def start_regeneration(
        self,
        conversation: ConversationState,
        ticket_key: str,
        on_progress: ProgressCallback | None = None,
    ) -> ConversationState:
        """Start the AC regeneration workflow for a given ticket.

        Orchestrates the following steps:
        1. Fetch ticket from Jira via JiraClient.get_ticket()
        2. Extract existing ACs from ticket description
        3. Update conversation state to GENERATING_ACS
        4. Generate new ACs via ACGenerator.generate()
        5. Store existing_acs and proposed_acs on conversation
        6. Store description_adf for later use in approval flow
        7. Update conversation state to COMPARING

        Args:
            conversation: The current conversation state.
            ticket_key: The Jira ticket key (e.g., "PROJ-123").
            on_progress: Optional async callback invoked with status messages
                at key points during processing (e.g., after fetching the ticket,
                before generating ACs).

        Returns:
            Updated ConversationState with existing_acs, proposed_acs,
            description_adf, and status set to COMPARING.
        """
        logger.info("Starting AC regeneration for ticket %s", ticket_key)

        # Step 0: Add "regenerating" label to signal manual processing
        await self._jira_client.add_label(ticket_key, "regenerating")
        logger.debug("Added 'regenerating' label to ticket %s", ticket_key)

        try:
            # Step 1: Fetch ticket from Jira
            ticket = await self._jira_client.get_ticket(ticket_key)
            logger.debug("Fetched ticket %s: %s", ticket_key, ticket.summary)

            # Step 1.5: Check for empty description
            if not ticket.description:
                logger.warning("Ticket %s has no description", ticket_key)
                raise EmptyDescriptionError(ticket_key)

            # Step 2: Extract existing ACs from ADF structure (handles both
            # tool-generated taskList and manually-written bulletList formats)
            existing_acs = extract_acs_from_adf(ticket.description_adf)
            logger.debug(
                "Extracted %d existing ACs from ticket %s",
                len(existing_acs),
                ticket_key,
            )

            # Step 3: Update conversation state to GENERATING_ACS
            conversation.status = ConversationStatus.GENERATING_ACS
            conversation.jira_ticket_key = ticket_key
            conversation.existing_acs = existing_acs
            conversation.description_adf = ticket.description_adf
            conversation = self._repository.update(conversation)
            logger.debug("Updated conversation state to GENERATING_ACS")

            # Notify caller that we're about to generate ACs
            if on_progress is not None:
                await on_progress("Generating new acceptance criteria...")

            # Enrich description with parent hierarchy context
            enriched_description = ticket.description
            if ticket.parent_key:
                try:
                    from src.jira.models import format_parent_chain

                    chain = await self._jira_client.get_parent_chain(
                        ticket.parent_key,
                    )
                    if chain:
                        enriched_description += (
                            "\n\n" + format_parent_chain(chain)
                        )
                        keys = [p.key for p in chain]
                        logger.info(
                            "Parent context applied for %s: %s",
                            ticket_key,
                            " -> ".join(keys),
                        )
                except Exception:
                    logger.exception(
                        "Parent context fetch failed for %s, "
                        "proceeding without",
                        ticket_key,
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
                            "Barley enrichment applied for %s", ticket_key
                        )
                        logger.debug(
                            "Barley context for %s: %s",
                            ticket_key,
                            enrichment_result.barley_context,
                        )
                        await self._jira_client.add_comment(
                            ticket_key, enrichment_result.barley_context
                        )
                    else:
                        logger.debug(
                            "Barley enrichment returned no context for %s",
                            ticket_key,
                        )
                except Exception:
                    logger.exception(
                        "Barley enrichment failed for %s, proceeding without context",
                        ticket_key,
                    )

            # Step 4: Generate new ACs via ACGenerator
            result = await self._ac_generator.generate(
                summary=ticket.summary,
                description=enriched_description,
            )
            proposed_acs = result.acceptance_criteria
            logger.info(
                "Generated %d proposed ACs for ticket %s",
                len(proposed_acs),
                ticket_key,
            )

            # Step 5 & 6: Store proposed_acs on conversation
            conversation.proposed_acs = proposed_acs

            # Step 7: Update conversation state to COMPARING
            conversation.status = ConversationStatus.COMPARING
            conversation = self._repository.update(conversation)
            logger.debug("Updated conversation state to COMPARING")

            return conversation
        except Exception:
            # Remove "regenerating" label on any failure
            await self._jira_client.remove_label(ticket_key, "regenerating")
            logger.debug(
                "Removed 'regenerating' label from ticket %s due to error",
                ticket_key,
            )
            raise

    async def approve_acs(self, conversation: ConversationState) -> ConversationState:
        """Write approved ACs to Jira and update conversation state.

        Orchestrates the following steps:
        1. Update conversation status to WRITING_TO_JIRA
        2. Use replace_acs_in_adf() to create updated ADF with new ACs
        3. Call JiraClient.update_description() to write to Jira
        4. Update conversation status to COMPLETED

        Args:
            conversation: The conversation state with proposed_acs to approve.

        Returns:
            Updated ConversationState with status set to COMPLETED.
        """
        logger.info(
            "Approving ACs for ticket %s in conversation %s",
            conversation.jira_ticket_key,
            conversation.id,
        )

        # Step 1: Update conversation status to WRITING_TO_JIRA
        conversation.status = ConversationStatus.WRITING_TO_JIRA
        conversation = self._repository.update(conversation)
        logger.debug("Updated conversation state to WRITING_TO_JIRA")

        # Step 2: Use replace_acs_in_adf() to create updated ADF with new ACs
        updated_adf = replace_acs_in_adf(
            existing_adf=conversation.description_adf,
            new_acs=conversation.proposed_acs or [],
        )
        logger.debug("Created updated ADF with new ACs")

        # Step 3: Call JiraClient.update_description() to write to Jira
        await self._jira_client.update_description(
            issue_key=conversation.jira_ticket_key,
            description_adf=updated_adf,
        )
        logger.info("Updated Jira ticket %s with new ACs", conversation.jira_ticket_key)

        # Step 3.5: Remove "regenerating" label after successful write
        await self._jira_client.remove_label(
            conversation.jira_ticket_key, "regenerating",
        )
        logger.debug(
            "Removed 'regenerating' label from ticket %s",
            conversation.jira_ticket_key,
        )

        # Step 4: Update conversation status to COMPLETED
        conversation.status = ConversationStatus.COMPLETED
        conversation = self._repository.update(conversation)
        logger.debug("Updated conversation state to COMPLETED")

        return conversation

    async def reject_acs(self, conversation: ConversationState) -> ConversationState:
        """Reject proposed ACs, cancel conversation, and clean up labels.

        Orchestrates the following steps:
        1. Remove the "regenerating" label from the Jira ticket
        2. Update conversation status to CANCELLED

        Args:
            conversation: The conversation state to reject/cancel.

        Returns:
            Updated ConversationState with status set to CANCELLED.
        """
        logger.info(
            "Rejecting ACs for ticket %s in conversation %s",
            conversation.jira_ticket_key,
            conversation.id,
        )

        # Remove "regenerating" label since we're done with this ticket
        if conversation.jira_ticket_key:
            await self._jira_client.remove_label(
                conversation.jira_ticket_key, "regenerating",
            )
            logger.debug(
                "Removed 'regenerating' label from ticket %s",
                conversation.jira_ticket_key,
            )

        # Update conversation status to CANCELLED
        conversation.status = ConversationStatus.CANCELLED
        conversation = self._repository.update(conversation)
        logger.debug("Updated conversation state to CANCELLED")

        return conversation

    async def regenerate_with_feedback(
        self,
        conversation: ConversationState,
        feedback: str,
    ) -> ConversationState:
        """Regenerate ACs incorporating user feedback.

        Orchestrates the following steps:
        1. Update conversation status to PROCESSING_MODIFICATION
        2. Build enhanced prompt with original ticket, previous ACs, and feedback
        3. Call ACGenerator.generate() with enhanced context
        4. Update conversation's proposed_acs with new ACs
        5. Update status to COMPARING
        6. Return updated conversation

        Args:
            conversation: The current conversation state with existing proposed_acs.
            feedback: The user's modification request/feedback.

        Returns:
            Updated ConversationState with new proposed_acs and status COMPARING.
        """
        logger.info(
            "Regenerating ACs with feedback for conversation %s",
            conversation.id,
        )

        # Step 1: Update conversation status to PROCESSING_MODIFICATION
        conversation.status = ConversationStatus.PROCESSING_MODIFICATION
        conversation = self._repository.update(conversation)
        logger.debug("Updated conversation state to PROCESSING_MODIFICATION")

        # Step 2: Build enhanced prompt with original ticket, previous ACs, and feedback
        # Fetch the ticket again to get the original summary and description
        ticket = await self._jira_client.get_ticket(conversation.jira_ticket_key)

        # Fetch parent hierarchy context
        parent_section = ""
        if ticket.parent_key:
            try:
                from src.jira.models import format_parent_chain

                chain = await self._jira_client.get_parent_chain(
                    ticket.parent_key,
                )
                if chain:
                    parent_section = "\n" + format_parent_chain(chain) + "\n"
            except Exception:
                logger.exception(
                    "Parent context fetch failed for %s, "
                    "proceeding without",
                    conversation.jira_ticket_key,
                )

        # Format previously proposed ACs as bullet list
        previous_acs_list = conversation.proposed_acs or []
        previous_acs_formatted = "\n".join(f"- {ac}" for ac in previous_acs_list)

        # Build the "no previous ACs" message separately to keep lines short
        no_previous_acs_msg = "(No previous acceptance criteria)"
        previous_acs_section = previous_acs_formatted or no_previous_acs_msg

        enhanced_description = f"""Original ticket: {ticket.summary}

Description:
{ticket.description or "(No description provided)"}
{parent_section}
Previously proposed acceptance criteria:
{previous_acs_section}

User feedback: {feedback}

Please generate updated acceptance criteria that address the user's feedback."""

        # Step 3: Call ACGenerator.generate() with enhanced context
        result = await self._ac_generator.generate(
            summary=ticket.summary,
            description=enhanced_description,
        )
        proposed_acs = result.acceptance_criteria
        logger.info(
            "Generated %d new proposed ACs for conversation %s",
            len(proposed_acs),
            conversation.id,
        )

        # Step 4: Update conversation's proposed_acs with new ACs
        conversation.proposed_acs = proposed_acs

        # Step 5: Update status to COMPARING
        conversation.status = ConversationStatus.COMPARING
        conversation = self._repository.update(conversation)
        logger.debug("Updated conversation state to COMPARING")

        return conversation
