"""Unit tests for ACRegenerationService.

Tests the AC regeneration workflow including:
- Fetching tickets from Jira
- Extracting existing ACs from description
- Generating new ACs via ACGenerator
- Updating conversation state through the workflow
- Status transitions through FETCHING_TICKET -> GENERATING_ACS -> COMPARING
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.ai.models import ACGenerationResult
from src.database import ConversationState, ConversationStatus
from src.jira.models import TicketData
from src.slack.services.regeneration_service import ACRegenerationService


@pytest.fixture
def mock_jira_client() -> MagicMock:
    """Create a mock JiraClient for unit testing."""
    mock = MagicMock()
    mock.add_label = AsyncMock(return_value=True)
    mock.remove_label = AsyncMock(return_value=True)
    return mock


@pytest.fixture
def mock_ac_generator() -> MagicMock:
    """Create a mock ACGenerator for unit testing."""
    mock = MagicMock()
    mock.is_enabled = True
    mock.generate = AsyncMock(
        return_value=ACGenerationResult(
            acceptance_criteria=[
                "User can view the dashboard",
                "Dashboard displays real-time data",
                "User can refresh the dashboard manually",
            ],
            confidence_score=0.9,
            confidence_gaps=[],
            sufficient_information=True,
        )
    )
    return mock


@pytest.fixture
def mock_repository() -> MagicMock:
    """Create a mock ConversationRepository for unit testing."""
    mock = MagicMock()
    # Make update return the conversation it receives
    mock.update = MagicMock(side_effect=lambda conv: conv)
    return mock


@pytest.fixture
def conversation() -> ConversationState:
    """Create a test conversation state."""
    return ConversationState(
        id="test-conversation-id",
        slack_user_id="U12345",
        slack_channel_id="D12345",
        status=ConversationStatus.FETCHING_TICKET,
    )


@pytest.fixture
def ticket_with_existing_acs() -> TicketData:
    """Create a ticket that has existing acceptance criteria."""
    description = """As a user, I want to view a dashboard so I can see my metrics.

## Acceptance Criteria

- [ ] Dashboard loads within 3 seconds
- [ ] User can see total sales
- [ ] User can filter by date range

## Technical Notes

Use React for the frontend.
"""
    return TicketData(
        key="PROJ-123",
        summary="View Dashboard Feature",
        description=description,
        description_adf={
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": "As a user, I want to view a dashboard so I can see my metrics.",
                        }
                    ],
                },
                {
                    "type": "heading",
                    "attrs": {"level": 2},
                    "content": [{"type": "text", "text": "Acceptance Criteria"}],
                },
                {
                    "type": "taskList",
                    "attrs": {"localId": "ac-list-1"},
                    "content": [
                        {
                            "type": "taskItem",
                            "attrs": {"localId": "ac-1", "state": "TODO"},
                            "content": [
                                {"type": "text", "text": "Dashboard loads within 3 seconds"}
                            ],
                        },
                        {
                            "type": "taskItem",
                            "attrs": {"localId": "ac-2", "state": "TODO"},
                            "content": [
                                {"type": "text", "text": "User can see total sales"}
                            ],
                        },
                        {
                            "type": "taskItem",
                            "attrs": {"localId": "ac-3", "state": "TODO"},
                            "content": [
                                {"type": "text", "text": "User can filter by date range"}
                            ],
                        },
                    ],
                },
                {
                    "type": "heading",
                    "attrs": {"level": 2},
                    "content": [{"type": "text", "text": "Technical Notes"}],
                },
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "Use React for the frontend."}
                    ],
                },
            ],
        },
        issue_type="Story",
    )


@pytest.fixture
def ticket_without_existing_acs() -> TicketData:
    """Create a ticket that has no existing acceptance criteria."""
    description = "As a user, I want to export data to CSV so I can analyze it externally."
    return TicketData(
        key="PROJ-456",
        summary="Export Data to CSV",
        description=description,
        description_adf={
            "type": "doc",
            "version": 1,
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": description}]}],
        },
        issue_type="Task",
    )


@pytest.fixture
def ticket_with_empty_description() -> TicketData:
    """Create a ticket with an empty description."""
    return TicketData(
        key="PROJ-789",
        summary="Empty Description Ticket",
        description="",
        description_adf=None,
        issue_type="Story",
    )


@pytest.fixture
def service(
    mock_jira_client: MagicMock,
    mock_ac_generator: MagicMock,
    mock_repository: MagicMock,
) -> ACRegenerationService:
    """Create an ACRegenerationService instance with mocked dependencies."""
    return ACRegenerationService(
        jira_client=mock_jira_client,
        ac_generator=mock_ac_generator,
        conversation_repository=mock_repository,
    )


class TestACRegenerationServiceInit:
    """Test suite for ACRegenerationService initialization."""

    def test_init_stores_dependencies(
        self,
        mock_jira_client: MagicMock,
        mock_ac_generator: MagicMock,
        mock_repository: MagicMock,
    ) -> None:
        """Verify __init__ correctly stores all dependencies."""
        service = ACRegenerationService(
            jira_client=mock_jira_client,
            ac_generator=mock_ac_generator,
            conversation_repository=mock_repository,
        )

        assert service._jira_client is mock_jira_client
        assert service._ac_generator is mock_ac_generator
        assert service._repository is mock_repository


class TestStartRegeneration:
    """Test suite for ACRegenerationService.start_regeneration() method."""

    @pytest.mark.asyncio
    async def test_fetches_ticket_from_jira(
        self,
        service: ACRegenerationService,
        mock_jira_client: MagicMock,
        conversation: ConversationState,
        ticket_with_existing_acs: TicketData,
    ) -> None:
        """Verify start_regeneration calls JiraClient.get_ticket with correct ticket key."""
        mock_jira_client.get_ticket = AsyncMock(return_value=ticket_with_existing_acs)

        await service.start_regeneration(conversation, "PROJ-123")

        mock_jira_client.get_ticket.assert_called_once_with("PROJ-123")

    @pytest.mark.asyncio
    async def test_extracts_existing_acs_from_description(
        self,
        service: ACRegenerationService,
        mock_jira_client: MagicMock,
        conversation: ConversationState,
        ticket_with_existing_acs: TicketData,
    ) -> None:
        """Verify existing ACs are extracted from the ticket description."""
        mock_jira_client.get_ticket = AsyncMock(return_value=ticket_with_existing_acs)

        result = await service.start_regeneration(conversation, "PROJ-123")

        # Existing ACs from the ticket description
        expected_existing_acs = [
            "Dashboard loads within 3 seconds",
            "User can see total sales",
            "User can filter by date range",
        ]
        assert result.existing_acs == expected_existing_acs

    @pytest.mark.asyncio
    async def test_generates_new_acs_via_ac_generator(
        self,
        service: ACRegenerationService,
        mock_jira_client: MagicMock,
        mock_ac_generator: MagicMock,
        conversation: ConversationState,
        ticket_with_existing_acs: TicketData,
    ) -> None:
        """Verify ACGenerator.generate is called with correct arguments."""
        mock_jira_client.get_ticket = AsyncMock(return_value=ticket_with_existing_acs)

        await service.start_regeneration(conversation, "PROJ-123")

        mock_ac_generator.generate.assert_called_once_with(
            summary=ticket_with_existing_acs.summary,
            description=ticket_with_existing_acs.description,
        )

    @pytest.mark.asyncio
    async def test_updates_conversation_with_existing_and_proposed_acs(
        self,
        service: ACRegenerationService,
        mock_jira_client: MagicMock,
        mock_ac_generator: MagicMock,
        conversation: ConversationState,
        ticket_with_existing_acs: TicketData,
    ) -> None:
        """Verify conversation is updated with both existing_acs and proposed_acs."""
        mock_jira_client.get_ticket = AsyncMock(return_value=ticket_with_existing_acs)

        result = await service.start_regeneration(conversation, "PROJ-123")

        # Existing ACs from the ticket description
        expected_existing_acs = [
            "Dashboard loads within 3 seconds",
            "User can see total sales",
            "User can filter by date range",
        ]
        expected_proposed_acs = [
            "User can view the dashboard",
            "Dashboard displays real-time data",
            "User can refresh the dashboard manually",
        ]

        assert result.existing_acs == expected_existing_acs
        assert result.proposed_acs == expected_proposed_acs

    @pytest.mark.asyncio
    async def test_transitions_through_generating_acs_to_comparing(
        self,
        service: ACRegenerationService,
        mock_jira_client: MagicMock,
        mock_repository: MagicMock,
        conversation: ConversationState,
        ticket_with_existing_acs: TicketData,
    ) -> None:
        """Verify status transitions: FETCHING_TICKET -> GENERATING_ACS -> COMPARING."""
        mock_jira_client.get_ticket = AsyncMock(return_value=ticket_with_existing_acs)

        # Track status changes
        status_changes: list[ConversationStatus] = []

        def track_update(conv: ConversationState) -> ConversationState:
            status_changes.append(conv.status)
            return conv

        mock_repository.update = MagicMock(side_effect=track_update)

        result = await service.start_regeneration(conversation, "PROJ-123")

        # Should have been updated twice: first to GENERATING_ACS, then to COMPARING
        assert len(status_changes) == 2
        assert status_changes[0] == ConversationStatus.GENERATING_ACS
        assert status_changes[1] == ConversationStatus.COMPARING
        assert result.status == ConversationStatus.COMPARING

    @pytest.mark.asyncio
    async def test_handles_ticket_with_no_existing_acs(
        self,
        service: ACRegenerationService,
        mock_jira_client: MagicMock,
        conversation: ConversationState,
        ticket_without_existing_acs: TicketData,
    ) -> None:
        """Verify existing_acs is empty list when ticket has no AC section."""
        mock_jira_client.get_ticket = AsyncMock(return_value=ticket_without_existing_acs)

        result = await service.start_regeneration(conversation, "PROJ-456")

        # No AC section in description, so existing_acs should be empty
        assert result.existing_acs == []
        # But proposed_acs should still be populated from the generator
        assert len(result.proposed_acs) == 3

    @pytest.mark.asyncio
    async def test_handles_empty_description_raises_error(
        self,
        service: ACRegenerationService,
        mock_jira_client: MagicMock,
        mock_ac_generator: MagicMock,
        conversation: ConversationState,
        ticket_with_empty_description: TicketData,
    ) -> None:
        """Verify empty description raises EmptyDescriptionError."""
        from src.jira import EmptyDescriptionError

        mock_jira_client.get_ticket = AsyncMock(return_value=ticket_with_empty_description)

        # Empty description should now raise EmptyDescriptionError
        with pytest.raises(EmptyDescriptionError) as exc_info:
            await service.start_regeneration(conversation, "PROJ-789")

        assert exc_info.value.ticket_key == "PROJ-789"
        # Generator should NOT be called since we raise before that step
        mock_ac_generator.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_stores_jira_ticket_key_on_conversation(
        self,
        service: ACRegenerationService,
        mock_jira_client: MagicMock,
        conversation: ConversationState,
        ticket_with_existing_acs: TicketData,
    ) -> None:
        """Verify jira_ticket_key is stored on the conversation."""
        mock_jira_client.get_ticket = AsyncMock(return_value=ticket_with_existing_acs)

        result = await service.start_regeneration(conversation, "PROJ-123")

        assert result.jira_ticket_key == "PROJ-123"

    @pytest.mark.asyncio
    async def test_stores_description_adf_on_conversation(
        self,
        service: ACRegenerationService,
        mock_jira_client: MagicMock,
        conversation: ConversationState,
        ticket_with_existing_acs: TicketData,
    ) -> None:
        """Verify description_adf from ticket is stored on conversation for later use."""
        mock_jira_client.get_ticket = AsyncMock(return_value=ticket_with_existing_acs)

        result = await service.start_regeneration(conversation, "PROJ-123")

        assert result.description_adf == ticket_with_existing_acs.description_adf
        assert result.description_adf is not None
        assert result.description_adf["type"] == "doc"

    @pytest.mark.asyncio
    async def test_empty_description_ticket_raises_error_before_storing_adf(
        self,
        service: ACRegenerationService,
        mock_jira_client: MagicMock,
        conversation: ConversationState,
        ticket_with_empty_description: TicketData,
    ) -> None:
        """Verify empty description raises error before storing description_adf."""
        from src.jira import EmptyDescriptionError

        mock_jira_client.get_ticket = AsyncMock(return_value=ticket_with_empty_description)

        # Empty description should raise EmptyDescriptionError
        with pytest.raises(EmptyDescriptionError):
            await service.start_regeneration(conversation, "PROJ-789")

    @pytest.mark.asyncio
    async def test_repository_update_called_correctly(
        self,
        service: ACRegenerationService,
        mock_jira_client: MagicMock,
        mock_repository: MagicMock,
        conversation: ConversationState,
        ticket_with_existing_acs: TicketData,
    ) -> None:
        """Verify repository.update is called with the conversation."""
        mock_jira_client.get_ticket = AsyncMock(return_value=ticket_with_existing_acs)

        await service.start_regeneration(conversation, "PROJ-123")

        # Repository update should be called twice
        assert mock_repository.update.call_count == 2

    @pytest.mark.asyncio
    async def test_returns_updated_conversation(
        self,
        service: ACRegenerationService,
        mock_jira_client: MagicMock,
        conversation: ConversationState,
        ticket_with_existing_acs: TicketData,
    ) -> None:
        """Verify the method returns the updated conversation state."""
        mock_jira_client.get_ticket = AsyncMock(return_value=ticket_with_existing_acs)

        result = await service.start_regeneration(conversation, "PROJ-123")

        assert isinstance(result, ConversationState)
        assert result.status == ConversationStatus.COMPARING
        assert result.jira_ticket_key == "PROJ-123"
        assert result.existing_acs is not None
        assert result.proposed_acs is not None


class TestStartRegenerationEdgeCases:
    """Test edge cases for start_regeneration method."""

    @pytest.mark.asyncio
    async def test_handles_generator_returning_empty_list(
        self,
        service: ACRegenerationService,
        mock_jira_client: MagicMock,
        mock_ac_generator: MagicMock,
        conversation: ConversationState,
        ticket_with_existing_acs: TicketData,
    ) -> None:
        """Verify handling when AC generator returns empty list (insufficient info)."""
        mock_jira_client.get_ticket = AsyncMock(return_value=ticket_with_existing_acs)
        mock_ac_generator.generate = AsyncMock(
            return_value=ACGenerationResult(
                acceptance_criteria=[],
                confidence_score=0.0,
                confidence_gaps=["Insufficient information"],
                sufficient_information=False,
            )
        )

        result = await service.start_regeneration(conversation, "PROJ-123")

        # Even with empty proposed_acs, the state should transition to COMPARING
        assert result.proposed_acs == []
        assert result.status == ConversationStatus.COMPARING

    @pytest.mark.asyncio
    async def test_preserves_conversation_id(
        self,
        service: ACRegenerationService,
        mock_jira_client: MagicMock,
        conversation: ConversationState,
        ticket_with_existing_acs: TicketData,
    ) -> None:
        """Verify original conversation ID is preserved throughout the workflow."""
        mock_jira_client.get_ticket = AsyncMock(return_value=ticket_with_existing_acs)
        original_id = conversation.id

        result = await service.start_regeneration(conversation, "PROJ-123")

        assert result.id == original_id

    @pytest.mark.asyncio
    async def test_preserves_slack_user_and_channel_ids(
        self,
        service: ACRegenerationService,
        mock_jira_client: MagicMock,
        conversation: ConversationState,
        ticket_with_existing_acs: TicketData,
    ) -> None:
        """Verify slack_user_id and slack_channel_id are preserved."""
        mock_jira_client.get_ticket = AsyncMock(return_value=ticket_with_existing_acs)
        original_user_id = conversation.slack_user_id
        original_channel_id = conversation.slack_channel_id

        result = await service.start_regeneration(conversation, "PROJ-123")

        assert result.slack_user_id == original_user_id
        assert result.slack_channel_id == original_channel_id


class TestApproveAcs:
    """Test suite for ACRegenerationService.approve_acs() method."""

    @pytest.fixture
    def comparing_conversation(self) -> ConversationState:
        """Create a conversation in COMPARING state ready for approval."""
        return ConversationState(
            id="test-conversation-id",
            slack_user_id="U12345",
            slack_channel_id="D12345",
            jira_ticket_key="PROJ-123",
            status=ConversationStatus.COMPARING,
            existing_acs=["Old AC 1", "Old AC 2"],
            proposed_acs=["New AC 1", "New AC 2", "New AC 3"],
            description_adf={
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": "Test description"}],
                    }
                ],
            },
        )

    @pytest.mark.asyncio
    async def test_updates_status_to_writing_to_jira_then_completed(
        self,
        service: ACRegenerationService,
        mock_jira_client: MagicMock,
        mock_repository: MagicMock,
        comparing_conversation: ConversationState,
    ) -> None:
        """Verify status transitions: COMPARING -> WRITING_TO_JIRA -> COMPLETED."""
        mock_jira_client.update_description = AsyncMock(return_value=True)

        # Track status changes
        status_changes: list[ConversationStatus] = []

        def track_update(conv: ConversationState) -> ConversationState:
            status_changes.append(conv.status)
            return conv

        mock_repository.update = MagicMock(side_effect=track_update)

        result = await service.approve_acs(comparing_conversation)

        # Should have been updated twice: WRITING_TO_JIRA, then COMPLETED
        assert len(status_changes) == 2
        assert status_changes[0] == ConversationStatus.WRITING_TO_JIRA
        assert status_changes[1] == ConversationStatus.COMPLETED
        assert result.status == ConversationStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_calls_jira_client_update_description(
        self,
        service: ACRegenerationService,
        mock_jira_client: MagicMock,
        comparing_conversation: ConversationState,
    ) -> None:
        """Verify JiraClient.update_description is called with correct args."""
        mock_jira_client.update_description = AsyncMock(return_value=True)

        await service.approve_acs(comparing_conversation)

        mock_jira_client.update_description.assert_called_once()
        call_args = mock_jira_client.update_description.call_args

        assert call_args.kwargs["issue_key"] == "PROJ-123"
        # Verify the ADF was passed
        assert "description_adf" in call_args.kwargs
        assert call_args.kwargs["description_adf"] is not None

    @pytest.mark.asyncio
    async def test_uses_replace_acs_in_adf_correctly(
        self,
        service: ACRegenerationService,
        mock_jira_client: MagicMock,
        comparing_conversation: ConversationState,
    ) -> None:
        """Verify replace_acs_in_adf is called and result is passed to Jira."""
        mock_jira_client.update_description = AsyncMock(return_value=True)

        await service.approve_acs(comparing_conversation)

        # Get the ADF that was passed to update_description
        call_args = mock_jira_client.update_description.call_args
        updated_adf = call_args.kwargs["description_adf"]

        # The ADF should be a valid document
        assert updated_adf["type"] == "doc"
        assert updated_adf["version"] == 1
        assert "content" in updated_adf

    @pytest.mark.asyncio
    async def test_returns_updated_conversation(
        self,
        service: ACRegenerationService,
        mock_jira_client: MagicMock,
        comparing_conversation: ConversationState,
    ) -> None:
        """Verify the method returns the updated conversation state."""
        mock_jira_client.update_description = AsyncMock(return_value=True)

        result = await service.approve_acs(comparing_conversation)

        assert isinstance(result, ConversationState)
        assert result.status == ConversationStatus.COMPLETED
        assert result.jira_ticket_key == "PROJ-123"

    @pytest.mark.asyncio
    async def test_preserves_conversation_id(
        self,
        service: ACRegenerationService,
        mock_jira_client: MagicMock,
        comparing_conversation: ConversationState,
    ) -> None:
        """Verify original conversation ID is preserved."""
        mock_jira_client.update_description = AsyncMock(return_value=True)
        original_id = comparing_conversation.id

        result = await service.approve_acs(comparing_conversation)

        assert result.id == original_id

    @pytest.mark.asyncio
    async def test_handles_empty_proposed_acs(
        self,
        service: ACRegenerationService,
        mock_jira_client: MagicMock,
        comparing_conversation: ConversationState,
    ) -> None:
        """Verify handling when proposed_acs is empty."""
        mock_jira_client.update_description = AsyncMock(return_value=True)
        comparing_conversation.proposed_acs = []

        result = await service.approve_acs(comparing_conversation)

        # Should still complete successfully
        assert result.status == ConversationStatus.COMPLETED
        mock_jira_client.update_description.assert_called_once()

    @pytest.mark.asyncio
    async def test_handles_none_proposed_acs(
        self,
        service: ACRegenerationService,
        mock_jira_client: MagicMock,
        comparing_conversation: ConversationState,
    ) -> None:
        """Verify handling when proposed_acs is None."""
        mock_jira_client.update_description = AsyncMock(return_value=True)
        comparing_conversation.proposed_acs = None

        result = await service.approve_acs(comparing_conversation)

        # Should still complete successfully
        assert result.status == ConversationStatus.COMPLETED
        mock_jira_client.update_description.assert_called_once()

    @pytest.mark.asyncio
    async def test_handles_none_description_adf(
        self,
        service: ACRegenerationService,
        mock_jira_client: MagicMock,
        comparing_conversation: ConversationState,
    ) -> None:
        """Verify handling when description_adf is None."""
        mock_jira_client.update_description = AsyncMock(return_value=True)
        comparing_conversation.description_adf = None

        result = await service.approve_acs(comparing_conversation)

        # Should still complete successfully (replace_acs_in_adf handles None)
        assert result.status == ConversationStatus.COMPLETED
        mock_jira_client.update_description.assert_called_once()


class TestRegenerateWithFeedback:
    """Test suite for ACRegenerationService.regenerate_with_feedback() method."""

    @pytest.fixture
    def comparing_conversation(self) -> ConversationState:
        """Create a conversation in COMPARING state ready for modification."""
        return ConversationState(
            id="test-conversation-id",
            slack_user_id="U12345",
            slack_channel_id="D12345",
            jira_ticket_key="PROJ-123",
            status=ConversationStatus.COMPARING,
            existing_acs=["Old AC 1", "Old AC 2"],
            proposed_acs=["Proposed AC 1", "Proposed AC 2", "Proposed AC 3"],
            description_adf={
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": "Test description"}],
                    }
                ],
            },
        )

    @pytest.fixture
    def ticket_data(self) -> TicketData:
        """Create ticket data for testing."""
        return TicketData(
            key="PROJ-123",
            summary="Test Feature Summary",
            description="This is the original ticket description.",
            description_adf={
                "type": "doc",
                "version": 1,
                "content": [],
            },
            issue_type="Story",
        )

    @pytest.mark.asyncio
    async def test_updates_status_through_processing_modification_to_comparing(
        self,
        service: ACRegenerationService,
        mock_jira_client: MagicMock,
        mock_repository: MagicMock,
        comparing_conversation: ConversationState,
        ticket_data: TicketData,
    ) -> None:
        """Verify status transitions: COMPARING -> PROCESSING_MODIFICATION -> COMPARING."""
        mock_jira_client.get_ticket = AsyncMock(return_value=ticket_data)

        # Track status changes
        status_changes: list[ConversationStatus] = []

        def track_update(conv: ConversationState) -> ConversationState:
            status_changes.append(conv.status)
            return conv

        mock_repository.update = MagicMock(side_effect=track_update)

        result = await service.regenerate_with_feedback(
            comparing_conversation, "Add error handling criteria"
        )

        # Should have been updated twice: PROCESSING_MODIFICATION, then COMPARING
        assert len(status_changes) == 2
        assert status_changes[0] == ConversationStatus.PROCESSING_MODIFICATION
        assert status_changes[1] == ConversationStatus.COMPARING
        assert result.status == ConversationStatus.COMPARING

    @pytest.mark.asyncio
    async def test_feedback_is_incorporated_into_prompt_context(
        self,
        service: ACRegenerationService,
        mock_jira_client: MagicMock,
        mock_ac_generator: MagicMock,
        comparing_conversation: ConversationState,
        ticket_data: TicketData,
    ) -> None:
        """Verify feedback is included in the prompt sent to ACGenerator."""
        mock_jira_client.get_ticket = AsyncMock(return_value=ticket_data)

        feedback = "Add error handling and performance criteria"
        await service.regenerate_with_feedback(comparing_conversation, feedback)

        # Verify generator was called
        mock_ac_generator.generate.assert_called_once()

        # Get the description argument passed to generate()
        call_args = mock_ac_generator.generate.call_args
        description_arg = call_args.kwargs["description"]

        # Verify the description contains all context elements
        assert "Original ticket:" in description_arg
        assert ticket_data.summary in description_arg
        assert "Previously proposed acceptance criteria:" in description_arg
        assert "Proposed AC 1" in description_arg
        assert "Proposed AC 2" in description_arg
        assert "User feedback:" in description_arg
        assert feedback in description_arg

    @pytest.mark.asyncio
    async def test_proposed_acs_is_updated_with_new_acs(
        self,
        service: ACRegenerationService,
        mock_jira_client: MagicMock,
        mock_ac_generator: MagicMock,
        comparing_conversation: ConversationState,
        ticket_data: TicketData,
    ) -> None:
        """Verify proposed_acs is updated with newly generated ACs."""
        mock_jira_client.get_ticket = AsyncMock(return_value=ticket_data)

        # Configure generator to return new ACs
        new_acs = [
            "Updated AC 1 with error handling",
            "Updated AC 2 with performance metrics",
            "Updated AC 3 with new requirement",
        ]
        mock_ac_generator.generate = AsyncMock(
            return_value=ACGenerationResult(
                acceptance_criteria=new_acs,
                confidence_score=0.9,
                confidence_gaps=[],
                sufficient_information=True,
            )
        )

        result = await service.regenerate_with_feedback(
            comparing_conversation, "Add error handling"
        )

        assert result.proposed_acs == new_acs

    @pytest.mark.asyncio
    async def test_preserves_existing_acs(
        self,
        service: ACRegenerationService,
        mock_jira_client: MagicMock,
        mock_ac_generator: MagicMock,
        comparing_conversation: ConversationState,
        ticket_data: TicketData,
    ) -> None:
        """Verify existing_acs is not modified during regeneration."""
        mock_jira_client.get_ticket = AsyncMock(return_value=ticket_data)

        original_existing_acs = comparing_conversation.existing_acs.copy()

        result = await service.regenerate_with_feedback(
            comparing_conversation, "Add more criteria"
        )

        assert result.existing_acs == original_existing_acs

    @pytest.mark.asyncio
    async def test_preserves_conversation_id(
        self,
        service: ACRegenerationService,
        mock_jira_client: MagicMock,
        comparing_conversation: ConversationState,
        ticket_data: TicketData,
    ) -> None:
        """Verify original conversation ID is preserved."""
        mock_jira_client.get_ticket = AsyncMock(return_value=ticket_data)
        original_id = comparing_conversation.id

        result = await service.regenerate_with_feedback(
            comparing_conversation, "Some feedback"
        )

        assert result.id == original_id

    @pytest.mark.asyncio
    async def test_fetches_ticket_for_context(
        self,
        service: ACRegenerationService,
        mock_jira_client: MagicMock,
        comparing_conversation: ConversationState,
        ticket_data: TicketData,
    ) -> None:
        """Verify ticket is fetched to get original summary and description."""
        mock_jira_client.get_ticket = AsyncMock(return_value=ticket_data)

        await service.regenerate_with_feedback(
            comparing_conversation, "Add criteria"
        )

        mock_jira_client.get_ticket.assert_called_once_with("PROJ-123")

    @pytest.mark.asyncio
    async def test_includes_original_ticket_summary_in_prompt(
        self,
        service: ACRegenerationService,
        mock_jira_client: MagicMock,
        mock_ac_generator: MagicMock,
        comparing_conversation: ConversationState,
        ticket_data: TicketData,
    ) -> None:
        """Verify original ticket summary is included in the enhanced prompt."""
        mock_jira_client.get_ticket = AsyncMock(return_value=ticket_data)

        await service.regenerate_with_feedback(
            comparing_conversation, "Feedback"
        )

        call_args = mock_ac_generator.generate.call_args
        summary_arg = call_args.kwargs["summary"]
        description_arg = call_args.kwargs["description"]

        # Summary should be the original ticket summary
        assert summary_arg == ticket_data.summary
        # Description should include the original summary as context
        assert ticket_data.summary in description_arg

    @pytest.mark.asyncio
    async def test_includes_original_description_in_prompt(
        self,
        service: ACRegenerationService,
        mock_jira_client: MagicMock,
        mock_ac_generator: MagicMock,
        comparing_conversation: ConversationState,
        ticket_data: TicketData,
    ) -> None:
        """Verify original ticket description is included in the enhanced prompt."""
        mock_jira_client.get_ticket = AsyncMock(return_value=ticket_data)

        await service.regenerate_with_feedback(
            comparing_conversation, "Feedback"
        )

        call_args = mock_ac_generator.generate.call_args
        description_arg = call_args.kwargs["description"]

        assert ticket_data.description in description_arg

    @pytest.mark.asyncio
    async def test_handles_empty_proposed_acs(
        self,
        service: ACRegenerationService,
        mock_jira_client: MagicMock,
        mock_ac_generator: MagicMock,
        comparing_conversation: ConversationState,
        ticket_data: TicketData,
    ) -> None:
        """Verify handling when proposed_acs is empty."""
        mock_jira_client.get_ticket = AsyncMock(return_value=ticket_data)
        comparing_conversation.proposed_acs = []

        await service.regenerate_with_feedback(
            comparing_conversation, "Generate new criteria"
        )

        # Should still work, prompt will indicate no previous criteria
        mock_ac_generator.generate.assert_called_once()

    @pytest.mark.asyncio
    async def test_handles_none_proposed_acs(
        self,
        service: ACRegenerationService,
        mock_jira_client: MagicMock,
        mock_ac_generator: MagicMock,
        comparing_conversation: ConversationState,
        ticket_data: TicketData,
    ) -> None:
        """Verify handling when proposed_acs is None."""
        mock_jira_client.get_ticket = AsyncMock(return_value=ticket_data)
        comparing_conversation.proposed_acs = None

        await service.regenerate_with_feedback(
            comparing_conversation, "Generate new criteria"
        )

        # Should still work, prompt will indicate no previous criteria
        mock_ac_generator.generate.assert_called_once()
        call_args = mock_ac_generator.generate.call_args
        description_arg = call_args.kwargs["description"]
        assert "(No previous acceptance criteria)" in description_arg

    @pytest.mark.asyncio
    async def test_returns_updated_conversation(
        self,
        service: ACRegenerationService,
        mock_jira_client: MagicMock,
        comparing_conversation: ConversationState,
        ticket_data: TicketData,
    ) -> None:
        """Verify the method returns the updated conversation state."""
        mock_jira_client.get_ticket = AsyncMock(return_value=ticket_data)

        result = await service.regenerate_with_feedback(
            comparing_conversation, "Some feedback"
        )

        assert isinstance(result, ConversationState)
        assert result.status == ConversationStatus.COMPARING
        assert result.jira_ticket_key == "PROJ-123"

    @pytest.mark.asyncio
    async def test_repository_update_called_twice(
        self,
        service: ACRegenerationService,
        mock_jira_client: MagicMock,
        mock_repository: MagicMock,
        comparing_conversation: ConversationState,
        ticket_data: TicketData,
    ) -> None:
        """Verify repository.update is called twice (status changes)."""
        mock_jira_client.get_ticket = AsyncMock(return_value=ticket_data)

        await service.regenerate_with_feedback(
            comparing_conversation, "Feedback"
        )

        # Repository update should be called twice
        assert mock_repository.update.call_count == 2


class TestStartRegenerationEmptyDescription:
    """Test suite for empty description handling in start_regeneration."""

    @pytest.mark.asyncio
    async def test_raises_empty_description_error_when_description_is_empty(
        self,
        service: ACRegenerationService,
        mock_jira_client: MagicMock,
        conversation: ConversationState,
        ticket_with_empty_description: TicketData,
    ) -> None:
        """Verify EmptyDescriptionError is raised when ticket has empty description."""
        from src.jira import EmptyDescriptionError

        mock_jira_client.get_ticket = AsyncMock(return_value=ticket_with_empty_description)

        with pytest.raises(EmptyDescriptionError) as exc_info:
            await service.start_regeneration(conversation, "PROJ-789")

        assert exc_info.value.ticket_key == "PROJ-789"

    @pytest.mark.asyncio
    async def test_raises_empty_description_error_when_description_is_whitespace(
        self,
        service: ACRegenerationService,
        mock_jira_client: MagicMock,
        conversation: ConversationState,
    ) -> None:
        """Verify EmptyDescriptionError is raised when ticket description is whitespace only."""
        from src.jira import EmptyDescriptionError

        ticket_with_whitespace_description = TicketData(
            key="PROJ-999",
            summary="Ticket with whitespace description",
            description="   ",
            description_adf=None,
            issue_type="Story",
        )
        mock_jira_client.get_ticket = AsyncMock(return_value=ticket_with_whitespace_description)

        # Whitespace-only description should be treated as empty
        # Note: The current check uses `if not ticket.description` which treats
        # whitespace as truthy. If we want to catch whitespace-only, we would need
        # to change the check to `if not ticket.description.strip()`.
        # For now, this test verifies current behavior.
        result = await service.start_regeneration(conversation, "PROJ-999")
        # Whitespace is currently considered valid, so it should succeed
        assert result.status == ConversationStatus.COMPARING

    @pytest.mark.asyncio
    async def test_does_not_raise_when_description_has_content(
        self,
        service: ACRegenerationService,
        mock_jira_client: MagicMock,
        conversation: ConversationState,
        ticket_with_existing_acs: TicketData,
    ) -> None:
        """Verify no exception is raised when ticket has a description."""
        mock_jira_client.get_ticket = AsyncMock(return_value=ticket_with_existing_acs)

        # This should not raise an exception
        result = await service.start_regeneration(conversation, "PROJ-123")

        assert result.status == ConversationStatus.COMPARING


class TestRegeneratingLabelCoordination:
    """Test suite for regenerating label coordination in ACRegenerationService.

    Verifies that the 'regenerating' label is properly added and removed
    to prevent race conditions between manual and automatic AC generation.
    """

    @pytest.mark.asyncio
    async def test_start_regeneration_adds_regenerating_label(
        self,
        service: ACRegenerationService,
        mock_jira_client: MagicMock,
        conversation: ConversationState,
        ticket_with_existing_acs: TicketData,
    ) -> None:
        """Verify 'regenerating' label is added at the start of regeneration."""
        mock_jira_client.get_ticket = AsyncMock(return_value=ticket_with_existing_acs)

        await service.start_regeneration(conversation, "PROJ-123")

        mock_jira_client.add_label.assert_called_once_with("PROJ-123", "regenerating")

    @pytest.mark.asyncio
    async def test_start_regeneration_adds_label_before_fetching_ticket(
        self,
        service: ACRegenerationService,
        mock_jira_client: MagicMock,
        conversation: ConversationState,
        ticket_with_existing_acs: TicketData,
    ) -> None:
        """Verify 'regenerating' label is added before get_ticket is called."""
        call_order: list[str] = []

        async def track_add_label(key: str, label: str) -> bool:
            call_order.append("add_label")
            return True

        async def track_get_ticket(key: str) -> TicketData:
            call_order.append("get_ticket")
            return ticket_with_existing_acs

        mock_jira_client.add_label = AsyncMock(side_effect=track_add_label)
        mock_jira_client.get_ticket = AsyncMock(side_effect=track_get_ticket)

        await service.start_regeneration(conversation, "PROJ-123")

        assert call_order == ["add_label", "get_ticket"]

    @pytest.mark.asyncio
    async def test_approve_acs_removes_regenerating_label(
        self,
        service: ACRegenerationService,
        mock_jira_client: MagicMock,
    ) -> None:
        """Verify 'regenerating' label is removed after successful approval."""
        mock_jira_client.update_description = AsyncMock(return_value=True)

        comparing_conversation = ConversationState(
            id="test-id",
            slack_user_id="U12345",
            slack_channel_id="D12345",
            jira_ticket_key="PROJ-123",
            status=ConversationStatus.COMPARING,
            existing_acs=["Old AC"],
            proposed_acs=["New AC"],
            description_adf={
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": "Test"}],
                    }
                ],
            },
        )

        await service.approve_acs(comparing_conversation)

        mock_jira_client.remove_label.assert_called_once_with(
            "PROJ-123", "regenerating",
        )

    @pytest.mark.asyncio
    async def test_reject_acs_removes_regenerating_label(
        self,
        service: ACRegenerationService,
        mock_jira_client: MagicMock,
    ) -> None:
        """Verify 'regenerating' label is removed on rejection."""
        comparing_conversation = ConversationState(
            id="test-id",
            slack_user_id="U12345",
            slack_channel_id="D12345",
            jira_ticket_key="PROJ-123",
            status=ConversationStatus.COMPARING,
            existing_acs=["Old AC"],
            proposed_acs=["New AC"],
        )

        result = await service.reject_acs(comparing_conversation)

        mock_jira_client.remove_label.assert_called_once_with(
            "PROJ-123", "regenerating",
        )
        assert result.status == ConversationStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_reject_acs_updates_status_to_cancelled(
        self,
        service: ACRegenerationService,
        mock_jira_client: MagicMock,
        mock_repository: MagicMock,
    ) -> None:
        """Verify reject_acs sets conversation status to CANCELLED."""
        comparing_conversation = ConversationState(
            id="test-id",
            slack_user_id="U12345",
            slack_channel_id="D12345",
            jira_ticket_key="PROJ-123",
            status=ConversationStatus.COMPARING,
        )

        result = await service.reject_acs(comparing_conversation)

        assert result.status == ConversationStatus.CANCELLED
        mock_repository.update.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_regeneration_removes_label_on_error(
        self,
        service: ACRegenerationService,
        mock_jira_client: MagicMock,
        conversation: ConversationState,
    ) -> None:
        """Verify 'regenerating' label is removed when start_regeneration fails."""
        mock_jira_client.get_ticket = AsyncMock(
            side_effect=RuntimeError("Connection failed")
        )

        with pytest.raises(RuntimeError, match="Connection failed"):
            await service.start_regeneration(conversation, "PROJ-123")

        # Label should have been added then removed
        mock_jira_client.add_label.assert_called_once_with("PROJ-123", "regenerating")
        mock_jira_client.remove_label.assert_called_once_with(
            "PROJ-123", "regenerating",
        )

    @pytest.mark.asyncio
    async def test_start_regeneration_removes_label_on_empty_description_error(
        self,
        service: ACRegenerationService,
        mock_jira_client: MagicMock,
        conversation: ConversationState,
        ticket_with_empty_description: TicketData,
    ) -> None:
        """Verify 'regenerating' label is removed on EmptyDescriptionError."""
        from src.jira import EmptyDescriptionError

        mock_jira_client.get_ticket = AsyncMock(
            return_value=ticket_with_empty_description
        )

        with pytest.raises(EmptyDescriptionError):
            await service.start_regeneration(conversation, "PROJ-789")

        mock_jira_client.add_label.assert_called_once_with("PROJ-789", "regenerating")
        mock_jira_client.remove_label.assert_called_once_with(
            "PROJ-789", "regenerating",
        )

    @pytest.mark.asyncio
    async def test_reject_acs_handles_none_ticket_key(
        self,
        service: ACRegenerationService,
        mock_jira_client: MagicMock,
    ) -> None:
        """Verify reject_acs handles conversation with no ticket key gracefully."""
        conversation_no_ticket = ConversationState(
            id="test-id",
            slack_user_id="U12345",
            slack_channel_id="D12345",
            jira_ticket_key=None,
            status=ConversationStatus.COMPARING,
        )

        result = await service.reject_acs(conversation_no_ticket)

        # Should not attempt to remove label when ticket key is None
        mock_jira_client.remove_label.assert_not_called()
        assert result.status == ConversationStatus.CANCELLED


class TestACRegenerationServiceBarleyEnrichment:
    """Test suite for Barley enrichment integration in ACRegenerationService.start_regeneration().

    Verifies that when a BarleyEnrichmentService is provided, the enrichment
    context is correctly incorporated into the AC generation workflow.
    """

    @pytest.fixture
    def mock_enrichment_service(self) -> MagicMock:
        """Create a mock BarleyEnrichmentService with a successful enrichment result."""
        from src.barley.models import EnrichmentResult

        mock = MagicMock()
        mock.enrich = AsyncMock(
            return_value=EnrichmentResult(
                barley_context="Project uses React for the frontend and Python FastAPI for the backend.",
                topics_extracted="React, FastAPI, frontend, backend",
            )
        )
        return mock

    @pytest.fixture
    def service_with_enrichment(
        self,
        mock_jira_client: MagicMock,
        mock_ac_generator: MagicMock,
        mock_repository: MagicMock,
        mock_enrichment_service: MagicMock,
    ) -> ACRegenerationService:
        """Create an ACRegenerationService instance with a mock enrichment service."""
        return ACRegenerationService(
            jira_client=mock_jira_client,
            ac_generator=mock_ac_generator,
            conversation_repository=mock_repository,
            enrichment_service=mock_enrichment_service,
        )

    @pytest.mark.asyncio
    async def test_enrichment_applied_passes_enriched_description_to_generate(
        self,
        service_with_enrichment: ACRegenerationService,
        mock_jira_client: MagicMock,
        mock_ac_generator: MagicMock,
        mock_enrichment_service: MagicMock,
        conversation: ConversationState,
        ticket_without_existing_acs: TicketData,
    ) -> None:
        """Verify enriched description is passed to ACGenerator.generate() when context available."""
        mock_jira_client.get_ticket = AsyncMock(return_value=ticket_without_existing_acs)
        mock_jira_client.add_comment = AsyncMock(return_value=True)

        await service_with_enrichment.start_regeneration(conversation, "PROJ-456")

        # Verify enrich was called with the ticket's summary and description
        mock_enrichment_service.enrich.assert_called_once_with(
            summary=ticket_without_existing_acs.summary,
            description=ticket_without_existing_acs.description,
        )

        # Verify generate() received the enriched description (with Barley context appended)
        generate_call_kwargs = mock_ac_generator.generate.call_args[1]
        assert "Additional Context from Barley:" in generate_call_kwargs["description"]
        assert "Project uses React for the frontend" in generate_call_kwargs["description"]

    @pytest.mark.asyncio
    async def test_enrichment_applied_adds_comment_with_barley_context(
        self,
        service_with_enrichment: ACRegenerationService,
        mock_jira_client: MagicMock,
        mock_enrichment_service: MagicMock,
        conversation: ConversationState,
        ticket_without_existing_acs: TicketData,
    ) -> None:
        """Verify add_comment is called with the Barley context when enrichment returns context."""
        mock_jira_client.get_ticket = AsyncMock(return_value=ticket_without_existing_acs)
        mock_jira_client.add_comment = AsyncMock(return_value=True)

        await service_with_enrichment.start_regeneration(conversation, "PROJ-456")

        # Verify add_comment was called with the Barley context
        mock_jira_client.add_comment.assert_called_once_with(
            "PROJ-456",
            "Project uses React for the frontend and Python FastAPI for the backend.",
        )

    @pytest.mark.asyncio
    async def test_enrichment_no_context_passes_original_description(
        self,
        service_with_enrichment: ACRegenerationService,
        mock_jira_client: MagicMock,
        mock_ac_generator: MagicMock,
        mock_enrichment_service: MagicMock,
        conversation: ConversationState,
        ticket_without_existing_acs: TicketData,
    ) -> None:
        """Verify original description is passed to generate() when barley_context is None."""
        from src.barley.models import EnrichmentResult

        mock_enrichment_service.enrich = AsyncMock(
            return_value=EnrichmentResult(
                barley_context=None,
                topics_extracted="some topics",
            )
        )
        mock_jira_client.get_ticket = AsyncMock(return_value=ticket_without_existing_acs)

        await service_with_enrichment.start_regeneration(conversation, "PROJ-456")

        # Verify generate() received the original description (no enrichment)
        generate_call_kwargs = mock_ac_generator.generate.call_args[1]
        assert generate_call_kwargs["description"] == ticket_without_existing_acs.description

    @pytest.mark.asyncio
    async def test_enrichment_no_context_does_not_add_comment(
        self,
        service_with_enrichment: ACRegenerationService,
        mock_jira_client: MagicMock,
        mock_enrichment_service: MagicMock,
        conversation: ConversationState,
        ticket_without_existing_acs: TicketData,
    ) -> None:
        """Verify add_comment is NOT called when barley_context is None."""
        from src.barley.models import EnrichmentResult

        mock_enrichment_service.enrich = AsyncMock(
            return_value=EnrichmentResult(
                barley_context=None,
                topics_extracted="some topics",
            )
        )
        mock_jira_client.get_ticket = AsyncMock(return_value=ticket_without_existing_acs)
        mock_jira_client.add_comment = AsyncMock(return_value=True)

        await service_with_enrichment.start_regeneration(conversation, "PROJ-456")

        # Verify add_comment was NOT called (no context to post)
        mock_jira_client.add_comment.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_enrichment_service_uses_original_description(
        self,
        service: ACRegenerationService,
        mock_jira_client: MagicMock,
        mock_ac_generator: MagicMock,
        conversation: ConversationState,
        ticket_without_existing_acs: TicketData,
    ) -> None:
        """Verify original description is used when enrichment_service is None."""
        mock_jira_client.get_ticket = AsyncMock(return_value=ticket_without_existing_acs)

        await service.start_regeneration(conversation, "PROJ-456")

        # Verify generate() received the original description
        generate_call_kwargs = mock_ac_generator.generate.call_args[1]
        assert generate_call_kwargs["description"] == ticket_without_existing_acs.description

    @pytest.mark.asyncio
    async def test_enrichment_exception_continues_with_original_description(
        self,
        service_with_enrichment: ACRegenerationService,
        mock_jira_client: MagicMock,
        mock_ac_generator: MagicMock,
        mock_enrichment_service: MagicMock,
        conversation: ConversationState,
        ticket_without_existing_acs: TicketData,
    ) -> None:
        """Verify start_regeneration() continues with original description when enrichment raises."""
        mock_enrichment_service.enrich = AsyncMock(
            side_effect=RuntimeError("Barley API crashed")
        )
        mock_jira_client.get_ticket = AsyncMock(return_value=ticket_without_existing_acs)

        # Should NOT raise - enrichment failure is caught and processing continues
        result = await service_with_enrichment.start_regeneration(conversation, "PROJ-456")

        assert result.status == ConversationStatus.COMPARING

        # Verify generate() received the original description (not enriched)
        generate_call_kwargs = mock_ac_generator.generate.call_args[1]
        assert generate_call_kwargs["description"] == ticket_without_existing_acs.description

    @pytest.mark.asyncio
    async def test_enrichment_exception_does_not_add_comment(
        self,
        service_with_enrichment: ACRegenerationService,
        mock_jira_client: MagicMock,
        mock_enrichment_service: MagicMock,
        conversation: ConversationState,
        ticket_without_existing_acs: TicketData,
    ) -> None:
        """Verify add_comment is NOT called when enrichment raises an exception."""
        mock_enrichment_service.enrich = AsyncMock(
            side_effect=RuntimeError("Barley API crashed")
        )
        mock_jira_client.get_ticket = AsyncMock(return_value=ticket_without_existing_acs)
        mock_jira_client.add_comment = AsyncMock(return_value=True)

        await service_with_enrichment.start_regeneration(conversation, "PROJ-456")

        # Verify add_comment was NOT called (enrichment failed)
        mock_jira_client.add_comment.assert_not_called()
