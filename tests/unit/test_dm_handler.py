"""Unit tests for DMHandler message processing functionality."""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.database import (
    ConversationRepository,
    ConversationState,
    ConversationStatus,
    DatabaseSettings,
)
from src.slack.handlers.dm_handler import (
    EVENT_DEDUP_TTL_SECONDS,
    MAX_MESSAGE_LENGTH,
    TICKET_KEY_PATTERN,
    DMHandler,
    DMResponse,
    format_comparison,
)
from src.slack.handlers.intent_classifier import Intent, IntentResult


@pytest.fixture
def temp_db_path():
    """Create a temporary database file path for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_conversations.db"
        yield str(db_path)


@pytest.fixture
def db_settings(temp_db_path):
    """Create DatabaseSettings with temporary database path."""
    return DatabaseSettings(database_path=temp_db_path)


@pytest.fixture
def repository(db_settings):
    """Create a ConversationRepository with a temporary database."""
    repo = ConversationRepository(settings=db_settings)
    yield repo
    repo.close()


@pytest.fixture
def mock_slack_client():
    """Create a mock SlackClient for testing."""
    client = MagicMock()
    client.send_message = AsyncMock(return_value=True)
    return client


@pytest.fixture
def dm_handler(mock_slack_client, repository):
    """Create a DMHandler with mock dependencies."""
    return DMHandler(slack_client=mock_slack_client, repository=repository)


class TestTicketKeyExtraction:
    """Test suite for Jira ticket key extraction from messages."""

    def test_extract_single_ticket_key(self):
        """Test extracting a single ticket key from a simple message."""
        match = TICKET_KEY_PATTERN.search("PROJ-123")
        assert match is not None
        assert match.group(1) == "PROJ-123"

    def test_extract_ticket_key_from_sentence(self):
        """Test extracting a ticket key from a longer message."""
        match = TICKET_KEY_PATTERN.search("regenerate ACs for PROJ-123 please")
        assert match is not None
        assert match.group(1) == "PROJ-123"

    def test_extract_first_ticket_key_from_multiple(self):
        """Test that the first ticket key is extracted when multiple are present."""
        match = TICKET_KEY_PATTERN.search("check PROJ-123 and also ABC-456")
        assert match is not None
        assert match.group(1) == "PROJ-123"

    def test_extract_ticket_key_with_single_digit(self):
        """Test extracting a ticket key with a single-digit number."""
        match = TICKET_KEY_PATTERN.search("ABC-1")
        assert match is not None
        assert match.group(1) == "ABC-1"

    def test_extract_ticket_key_with_large_number(self):
        """Test extracting a ticket key with a large number."""
        match = TICKET_KEY_PATTERN.search("BIGPROJECT-99999")
        assert match is not None
        assert match.group(1) == "BIGPROJECT-99999"

    def test_no_ticket_key_in_plain_text(self):
        """Test that no match is found in plain text without ticket key."""
        match = TICKET_KEY_PATTERN.search("hello world")
        assert match is None

    def test_no_ticket_key_lowercase_project(self):
        """Test that lowercase project codes are not matched."""
        match = TICKET_KEY_PATTERN.search("proj-123")
        assert match is None

    def test_no_ticket_key_missing_number(self):
        """Test that project codes without numbers are not matched."""
        match = TICKET_KEY_PATTERN.search("PROJ-")
        assert match is None

    def test_empty_string_no_match(self):
        """Test that empty string returns no match."""
        match = TICKET_KEY_PATTERN.search("")
        assert match is None


class TestDMHandlerTicketExtraction:
    """Test suite for DMHandler._extract_ticket_key method."""

    @pytest.mark.asyncio
    async def test_handle_message_with_ticket_key_returns_acknowledgment(
        self, dm_handler
    ):
        """Test that a message with a ticket key returns an acknowledgment."""
        response = await dm_handler.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="PROJ-123",
        )

        assert response.text == "Processing PROJ-123..."

    @pytest.mark.asyncio
    async def test_handle_message_extracts_ticket_from_longer_message(
        self, dm_handler
    ):
        """Test that ticket key is extracted from a longer message."""
        response = await dm_handler.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="regenerate ACs for PROJ-123 please",
        )

        assert response.text == "Processing PROJ-123..."

    @pytest.mark.asyncio
    async def test_handle_message_uses_first_ticket_key(self, dm_handler):
        """Test that the first ticket key is used when multiple are present."""
        response = await dm_handler.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="compare PROJ-123 with ABC-456",
        )

        assert response.text == "Processing PROJ-123..."


class TestDMHandlerNoTicketKey:
    """Test suite for DMHandler behavior when no ticket key is found."""

    @pytest.mark.asyncio
    async def test_no_ticket_key_no_active_conversation_returns_prompt(
        self, dm_handler
    ):
        """Test prompt returned when no ticket key and no active conversation."""
        response = await dm_handler.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="hello",
        )

        assert response.text == "Please provide a Jira ticket key (e.g., PROJ-123)"

    @pytest.mark.asyncio
    async def test_no_ticket_key_awaiting_ticket_returns_prompt(
        self, dm_handler, repository
    ):
        """Test prompt returned when active conversation is in AWAITING_TICKET."""
        # Create an active conversation in AWAITING_TICKET state
        conversation = ConversationState(
            id=str(uuid.uuid4()),
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            status=ConversationStatus.AWAITING_TICKET,
        )
        repository.create(conversation)

        response = await dm_handler.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="what's the status?",
        )

        assert response.text == "Please provide a Jira ticket key (e.g., PROJ-123)"

    @pytest.mark.asyncio
    async def test_no_ticket_key_active_comparing_returns_none(
        self, dm_handler, repository
    ):
        """Test None is returned when active conversation is not AWAITING_TICKET."""
        # Create an active conversation in COMPARING state
        conversation = ConversationState(
            id=str(uuid.uuid4()),
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            jira_ticket_key="PROJ-999",
            status=ConversationStatus.COMPARING,
        )
        repository.create(conversation)

        response = await dm_handler.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="looks good",
        )

        assert response is None

    @pytest.mark.asyncio
    async def test_no_ticket_key_empty_text_returns_prompt(self, dm_handler):
        """Test that a prompt is returned when message text is empty."""
        response = await dm_handler.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="",
        )

        assert response.text == "Please provide a Jira ticket key (e.g., PROJ-123)"


class TestDMHandlerConversationCreation:
    """Test suite for DMHandler conversation state creation."""

    @pytest.mark.asyncio
    async def test_creates_conversation_with_fetching_ticket_status(
        self, dm_handler, repository
    ):
        """Test that a new conversation is created with FETCHING_TICKET status."""
        await dm_handler.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="PROJ-123",
        )

        # Verify conversation was created
        conversation = repository.get_active("U12345678", "D87654321")
        assert conversation is not None
        assert conversation.status == ConversationStatus.FETCHING_TICKET

    @pytest.mark.asyncio
    async def test_creates_conversation_with_correct_jira_ticket_key(
        self, dm_handler, repository
    ):
        """Test that the jira_ticket_key is set correctly on the conversation."""
        await dm_handler.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="Please process ABC-456",
        )

        conversation = repository.get_active("U12345678", "D87654321")
        assert conversation is not None
        assert conversation.jira_ticket_key == "ABC-456"

    @pytest.mark.asyncio
    async def test_creates_conversation_with_correct_user_and_channel(
        self, dm_handler, repository
    ):
        """Test that user_id and channel_id are set correctly on the conversation."""
        await dm_handler.handle_message(
            user_id="U11111111",
            channel_id="D22222222",
            text="TEST-789",
        )

        conversation = repository.get_active("U11111111", "D22222222")
        assert conversation is not None
        assert conversation.slack_user_id == "U11111111"
        assert conversation.slack_channel_id == "D22222222"

    @pytest.mark.asyncio
    async def test_creates_conversation_with_uuid_id(self, dm_handler, repository):
        """Test that the conversation is created with a valid UUID."""
        await dm_handler.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="PROJ-123",
        )

        conversation = repository.get_active("U12345678", "D87654321")
        assert conversation is not None

        # Verify the ID is a valid UUID
        try:
            uuid.UUID(conversation.id)
        except ValueError:
            pytest.fail("Conversation ID is not a valid UUID")

    @pytest.mark.asyncio
    async def test_multiple_messages_create_separate_conversations(
        self, dm_handler, repository
    ):
        """Test that multiple messages with ticket keys create separate convos."""
        await dm_handler.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="PROJ-111",
        )

        first_conversation = repository.get_active("U12345678", "D87654321")
        first_id = first_conversation.id

        # Send another message with a different ticket key
        await dm_handler.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="PROJ-222",
        )

        # Get the most recent active conversation
        second_conversation = repository.get_active("U12345678", "D87654321")

        # The second conversation should be different (newer)
        assert second_conversation is not None
        assert second_conversation.id != first_id
        assert second_conversation.jira_ticket_key == "PROJ-222"


class TestDMHandlerEdgeCases:
    """Test suite for DMHandler edge cases and boundary conditions."""

    @pytest.mark.asyncio
    async def test_ticket_key_at_start_of_message(self, dm_handler):
        """Test ticket key extraction when key is at the start of message."""
        response = await dm_handler.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="PROJ-123 needs ACs generated",
        )

        assert response.text == "Processing PROJ-123..."

    @pytest.mark.asyncio
    async def test_ticket_key_at_end_of_message(self, dm_handler):
        """Test ticket key extraction when key is at the end of message."""
        response = await dm_handler.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="generate ACs for PROJ-123",
        )

        assert response.text == "Processing PROJ-123..."

    @pytest.mark.asyncio
    async def test_ticket_key_surrounded_by_punctuation(self, dm_handler):
        """Test ticket key extraction when surrounded by punctuation."""
        response = await dm_handler.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="check (PROJ-123) now!",
        )

        assert response.text == "Processing PROJ-123..."

    @pytest.mark.asyncio
    async def test_whitespace_only_message_returns_prompt(self, dm_handler):
        """Test that whitespace-only message returns prompt."""
        response = await dm_handler.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="   ",
        )

        assert response.text == "Please provide a Jira ticket key (e.g., PROJ-123)"

    @pytest.mark.asyncio
    async def test_different_users_have_separate_conversations(
        self, dm_handler, repository
    ):
        """Test that different users have separate conversation states."""
        # User 1 creates a conversation
        await dm_handler.handle_message(
            user_id="U11111111",
            channel_id="D11111111",
            text="PROJ-111",
        )

        # User 2 has no active conversation
        response = await dm_handler.handle_message(
            user_id="U22222222",
            channel_id="D22222222",
            text="hello",
        )

        # User 2 should be prompted (no active conversation for them)
        assert response.text == "Please provide a Jira ticket key (e.g., PROJ-123)"

        # Verify User 1 still has their conversation
        user1_conv = repository.get_active("U11111111", "D11111111")
        assert user1_conv is not None
        assert user1_conv.jira_ticket_key == "PROJ-111"


class TestFormatComparison:
    """Test suite for format_comparison function."""

    def test_format_comparison_with_existing_acs(self):
        """Test formatting when both existing and proposed ACs are present."""
        conversation = ConversationState(
            id=str(uuid.uuid4()),
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            jira_ticket_key="PROJ-123",
            status=ConversationStatus.COMPARING,
            existing_acs=["First existing criterion", "Second existing criterion"],
            proposed_acs=["First new criterion", "Second new criterion"],
        )

        result = format_comparison(conversation)

        assert "*Ticket:* PROJ-123" in result
        assert "*Existing Acceptance Criteria:*" in result
        assert "\u2022 First existing criterion" in result
        assert "\u2022 Second existing criterion" in result
        assert "*Proposed New Acceptance Criteria:*" in result
        assert "\u2022 First new criterion" in result
        assert "\u2022 Second new criterion" in result
        assert 'Reply with "approve"' in result

    def test_format_comparison_with_no_existing_acs(self):
        """Test formatting when no existing ACs are present."""
        conversation = ConversationState(
            id=str(uuid.uuid4()),
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            jira_ticket_key="PROJ-456",
            status=ConversationStatus.COMPARING,
            existing_acs=[],
            proposed_acs=["First new criterion", "Second new criterion"],
        )

        result = format_comparison(conversation)

        assert "*Ticket:* PROJ-456" in result
        assert "*Existing Acceptance Criteria:*" in result
        assert "(No existing acceptance criteria)" in result
        assert "*Proposed New Acceptance Criteria:*" in result
        assert "\u2022 First new criterion" in result

    def test_format_comparison_with_none_existing_acs(self):
        """Test formatting when existing_acs is None."""
        conversation = ConversationState(
            id=str(uuid.uuid4()),
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            jira_ticket_key="PROJ-789",
            status=ConversationStatus.COMPARING,
            existing_acs=None,
            proposed_acs=["New criterion"],
        )

        result = format_comparison(conversation)

        assert "(No existing acceptance criteria)" in result

    def test_format_comparison_truncation_for_long_messages(self):
        """Test that long messages are truncated at MAX_MESSAGE_LENGTH."""
        # Create a conversation with many long ACs to exceed the limit
        long_acs = [f"This is a very long acceptance criterion number {i} " * 20 for i in range(50)]

        conversation = ConversationState(
            id=str(uuid.uuid4()),
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            jira_ticket_key="PROJ-999",
            status=ConversationStatus.COMPARING,
            existing_acs=long_acs,
            proposed_acs=long_acs,
        )

        result = format_comparison(conversation)

        assert len(result) <= MAX_MESSAGE_LENGTH
        assert result.endswith("... (truncated)")

    def test_format_comparison_no_truncation_for_short_messages(self):
        """Test that short messages are not truncated."""
        conversation = ConversationState(
            id=str(uuid.uuid4()),
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            jira_ticket_key="PROJ-123",
            status=ConversationStatus.COMPARING,
            existing_acs=["Short AC"],
            proposed_acs=["Another short AC"],
        )

        result = format_comparison(conversation)

        assert "... (truncated)" not in result

    def test_format_comparison_with_empty_proposed_acs(self):
        """Test formatting when proposed_acs is empty."""
        conversation = ConversationState(
            id=str(uuid.uuid4()),
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            jira_ticket_key="PROJ-123",
            status=ConversationStatus.COMPARING,
            existing_acs=["Existing AC"],
            proposed_acs=[],
        )

        result = format_comparison(conversation)

        assert "(No proposed acceptance criteria)" in result

    def test_format_comparison_with_no_ticket_key(self):
        """Test formatting when jira_ticket_key is None."""
        conversation = ConversationState(
            id=str(uuid.uuid4()),
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            status=ConversationStatus.COMPARING,
            jira_ticket_key=None,
            existing_acs=["AC"],
            proposed_acs=["New AC"],
        )

        result = format_comparison(conversation)

        assert "*Ticket:* Unknown" in result


class TestDMHandlerFullFlow:
    """Test suite for DMHandler full regeneration flow."""

    @pytest.fixture
    def mock_regeneration_service(self):
        """Create a mock ACRegenerationService."""
        service = MagicMock()
        service.start_regeneration = AsyncMock()
        return service

    @pytest.fixture
    def dm_handler_with_service(self, mock_slack_client, repository, mock_regeneration_service):
        """Create a DMHandler with a mock regeneration service."""
        return DMHandler(
            slack_client=mock_slack_client,
            repository=repository,
            regeneration_service=mock_regeneration_service,
        )

    @pytest.mark.asyncio
    async def test_full_flow_returns_comparison_message(
        self, dm_handler_with_service, mock_regeneration_service
    ):
        """Test that the full flow returns a formatted comparison message."""
        # Configure the mock service to return a conversation with ACs
        updated_conversation = ConversationState(
            id="test-conv-id",
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            jira_ticket_key="PROJ-123",
            status=ConversationStatus.COMPARING,
            existing_acs=["Existing AC 1", "Existing AC 2"],
            proposed_acs=["New AC 1", "New AC 2", "New AC 3"],
        )
        mock_regeneration_service.start_regeneration.return_value = updated_conversation

        response = await dm_handler_with_service.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="regenerate ACs for PROJ-123",
        )

        # Verify the response contains the comparison message
        assert "*Ticket:* PROJ-123" in response.text
        assert "*Existing Acceptance Criteria:*" in response.text
        assert "\u2022 Existing AC 1" in response.text
        assert "*Proposed New Acceptance Criteria:*" in response.text
        assert "\u2022 New AC 1" in response.text
        assert 'Reply with "approve"' in response.text

    @pytest.mark.asyncio
    async def test_full_flow_calls_regeneration_service(
        self, dm_handler_with_service, mock_regeneration_service, repository
    ):
        """Test that the handler calls the regeneration service with correct args."""
        # Configure the mock service
        mock_regeneration_service.start_regeneration.return_value = ConversationState(
            id="test-id",
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            jira_ticket_key="TEST-999",
            status=ConversationStatus.COMPARING,
            existing_acs=[],
            proposed_acs=["New AC"],
        )

        await dm_handler_with_service.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="TEST-999",
        )

        # Verify the service was called
        mock_regeneration_service.start_regeneration.assert_called_once()
        call_args = mock_regeneration_service.start_regeneration.call_args

        # Check the ticket_key argument
        assert call_args.kwargs["ticket_key"] == "TEST-999"

        # Check the conversation argument has the right ticket key
        conversation_arg = call_args.kwargs["conversation"]
        assert conversation_arg.jira_ticket_key == "TEST-999"
        assert conversation_arg.slack_user_id == "U12345678"
        assert conversation_arg.slack_channel_id == "D87654321"

    @pytest.mark.asyncio
    async def test_handler_without_service_returns_simple_acknowledgment(
        self, dm_handler
    ):
        """Test that handler without service returns simple 'Processing...' message."""
        response = await dm_handler.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="PROJ-123",
        )

        assert response.text == "Processing PROJ-123..."

    @pytest.mark.asyncio
    async def test_full_flow_with_no_existing_acs(
        self, dm_handler_with_service, mock_regeneration_service
    ):
        """Test full flow when ticket has no existing ACs."""
        mock_regeneration_service.start_regeneration.return_value = ConversationState(
            id="test-id",
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            jira_ticket_key="NEW-123",
            status=ConversationStatus.COMPARING,
            existing_acs=[],
            proposed_acs=["Brand new AC 1", "Brand new AC 2"],
        )

        response = await dm_handler_with_service.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="NEW-123",
        )

        assert "(No existing acceptance criteria)" in response.text
        assert "\u2022 Brand new AC 1" in response.text


class TestDMHandlerIntermediateMessages:
    """Test suite verifying no intermediate status messages are sent during regeneration.

    Intermediate status messages (e.g. "Fetching ticket...", "Generating new ACs...")
    should NOT be sent as separate DM messages. In Slack AI Agent mode, each bot
    message creates a new conversation entry in the History tab, causing clutter.
    The Socket Mode "is thinking..." status indicator provides sufficient feedback.
    """

    @pytest.fixture
    def mock_regeneration_service(self):
        """Create a mock ACRegenerationService."""
        service = MagicMock()
        service.start_regeneration = AsyncMock()
        return service

    @pytest.fixture
    def dm_handler_with_service(self, mock_slack_client, repository, mock_regeneration_service):
        """Create a DMHandler with a mock regeneration service."""
        return DMHandler(
            slack_client=mock_slack_client,
            repository=repository,
            regeneration_service=mock_regeneration_service,
        )

    @pytest.mark.asyncio
    async def test_no_intermediate_messages_sent_during_regeneration(
        self, dm_handler_with_service, mock_regeneration_service, mock_slack_client
    ):
        """Test that no intermediate status messages are sent during regeneration."""
        mock_regeneration_service.start_regeneration.return_value = ConversationState(
            id="test-id",
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            jira_ticket_key="PROJ-123",
            status=ConversationStatus.COMPARING,
            existing_acs=[],
            proposed_acs=["New AC"],
        )

        await dm_handler_with_service.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="PROJ-123",
        )

        # No intermediate send_message calls should have been made
        mock_slack_client.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_on_progress_callback_not_passed_to_regeneration_service(
        self, dm_handler_with_service, mock_regeneration_service, mock_slack_client
    ):
        """Test that on_progress callback is NOT passed to start_regeneration."""
        mock_regeneration_service.start_regeneration.return_value = ConversationState(
            id="test-id",
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            jira_ticket_key="PROJ-123",
            status=ConversationStatus.COMPARING,
            existing_acs=[],
            proposed_acs=["New AC"],
        )

        await dm_handler_with_service.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="PROJ-123",
        )

        # Verify on_progress was NOT passed (or not in kwargs)
        call_args = mock_regeneration_service.start_regeneration.call_args
        on_progress = call_args.kwargs.get("on_progress")
        assert on_progress is None

    @pytest.mark.asyncio
    async def test_no_intermediate_messages_sent_without_regeneration_service(
        self, dm_handler, mock_slack_client
    ):
        """Test that no messages are sent when no service is configured."""
        await dm_handler.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="PROJ-123",
        )

        # No send_message calls should have been made
        mock_slack_client.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_intermediate_messages_sent_when_error_occurs(
        self, dm_handler_with_service, mock_regeneration_service, mock_slack_client
    ):
        """Test that no intermediate messages are sent even if regeneration fails."""
        from src.jira import JiraTicketNotFoundError

        mock_regeneration_service.start_regeneration.side_effect = JiraTicketNotFoundError(
            "Not found"
        )

        await dm_handler_with_service.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="PROJ-123",
        )

        # No intermediate "Fetching ticket..." message should have been sent
        mock_slack_client.send_message.assert_not_called()


class TestDMHandlerComparingStateApproval:
    """Test suite for DMHandler COMPARING state handling with approval flow."""

    @pytest.fixture
    def mock_intent_classifier(self):
        """Create a mock IntentClassifier for testing."""
        classifier = MagicMock()
        classifier.classify_intent = AsyncMock(
            return_value=IntentResult(intent=Intent.APPROVE)
        )
        return classifier

    @pytest.fixture
    def mock_jira_settings(self):
        """Create a mock JiraSettings for testing."""
        settings = MagicMock()
        settings.base_url = "https://company.atlassian.net"
        return settings

    @pytest.fixture
    def mock_regeneration_service(self):
        """Create a mock ACRegenerationService."""
        service = MagicMock()
        service.start_regeneration = AsyncMock()
        service.approve_acs = AsyncMock()
        service.reject_acs = AsyncMock()
        return service

    @pytest.fixture
    def dm_handler_with_approval_deps(
        self,
        mock_slack_client,
        repository,
        mock_regeneration_service,
        mock_intent_classifier,
        mock_jira_settings,
    ):
        """Create a DMHandler with all dependencies for approval flow."""
        return DMHandler(
            slack_client=mock_slack_client,
            repository=repository,
            regeneration_service=mock_regeneration_service,
            intent_classifier=mock_intent_classifier,
            jira_settings=mock_jira_settings,
        )

    @pytest.mark.asyncio
    async def test_comparing_state_with_approve_intent_returns_confirmation(
        self,
        dm_handler_with_approval_deps,
        mock_regeneration_service,
        mock_intent_classifier,
        repository,
    ):
        """Test that APPROVE intent in COMPARING state returns confirmation message."""
        # Create an active conversation in COMPARING state
        conversation = ConversationState(
            id=str(uuid.uuid4()),
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            jira_ticket_key="PROJ-123",
            status=ConversationStatus.COMPARING,
            existing_acs=["Old AC"],
            proposed_acs=["New AC"],
        )
        repository.create(conversation)

        response = await dm_handler_with_approval_deps.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="looks good, approve",
        )

        assert response is not None
        assert "Done! ACs updated on PROJ-123" in response.text

    @pytest.mark.asyncio
    async def test_comparing_state_with_approve_intent_includes_jira_link(
        self,
        dm_handler_with_approval_deps,
        mock_regeneration_service,
        mock_intent_classifier,
        repository,
    ):
        """Test that confirmation message includes Jira link."""
        # Create an active conversation in COMPARING state
        conversation = ConversationState(
            id=str(uuid.uuid4()),
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            jira_ticket_key="PROJ-456",
            status=ConversationStatus.COMPARING,
            existing_acs=["Old AC"],
            proposed_acs=["New AC"],
        )
        repository.create(conversation)

        response = await dm_handler_with_approval_deps.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="approve",
        )

        assert response is not None
        assert "https://company.atlassian.net/browse/PROJ-456" in response.text

    @pytest.mark.asyncio
    async def test_comparing_state_with_approve_intent_calls_approve_acs(
        self,
        dm_handler_with_approval_deps,
        mock_regeneration_service,
        mock_intent_classifier,
        repository,
    ):
        """Test that approve_acs is called when user approves."""
        # Create an active conversation in COMPARING state
        conversation = ConversationState(
            id=str(uuid.uuid4()),
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            jira_ticket_key="PROJ-789",
            status=ConversationStatus.COMPARING,
            existing_acs=["Old AC"],
            proposed_acs=["New AC"],
        )
        repository.create(conversation)

        await dm_handler_with_approval_deps.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="yes, approve it",
        )

        mock_regeneration_service.approve_acs.assert_called_once()
        call_args = mock_regeneration_service.approve_acs.call_args
        # The conversation should be passed to approve_acs
        assert call_args[0][0].jira_ticket_key == "PROJ-789"

    @pytest.mark.asyncio
    async def test_comparing_state_with_approve_intent_classifies_message(
        self,
        dm_handler_with_approval_deps,
        mock_regeneration_service,
        mock_intent_classifier,
        repository,
    ):
        """Test that intent classifier is called with user message."""
        # Create an active conversation in COMPARING state
        conversation = ConversationState(
            id=str(uuid.uuid4()),
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            jira_ticket_key="PROJ-999",
            status=ConversationStatus.COMPARING,
            existing_acs=["Old AC"],
            proposed_acs=["New AC"],
        )
        repository.create(conversation)

        await dm_handler_with_approval_deps.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="lgtm ship it",
        )

        mock_intent_classifier.classify_intent.assert_called_once_with("lgtm ship it")

    @pytest.mark.asyncio
    async def test_comparing_state_with_reject_intent_returns_cancellation_message(
        self,
        dm_handler_with_approval_deps,
        mock_regeneration_service,
        mock_intent_classifier,
        repository,
    ):
        """Test that REJECT intent returns cancellation confirmation message."""
        # Configure classifier to return REJECT
        mock_intent_classifier.classify_intent = AsyncMock(
            return_value=IntentResult(intent=Intent.REJECT)
        )

        # Create an active conversation in COMPARING state
        conversation = ConversationState(
            id=str(uuid.uuid4()),
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            jira_ticket_key="PROJ-123",
            status=ConversationStatus.COMPARING,
            existing_acs=["Old AC"],
            proposed_acs=["New AC"],
        )
        repository.create(conversation)

        response = await dm_handler_with_approval_deps.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="no, reject this",
        )

        # Should return the exact cancellation message per functional spec
        assert response.text == "Cancelled. Original ACs remain unchanged."
        mock_regeneration_service.approve_acs.assert_not_called()

    @pytest.mark.asyncio
    async def test_comparing_state_with_reject_intent_calls_reject_acs(
        self,
        dm_handler_with_approval_deps,
        mock_regeneration_service,
        mock_intent_classifier,
        repository,
    ):
        """Test that REJECT intent delegates to reject_acs on the regeneration service."""
        # Configure classifier to return REJECT
        mock_intent_classifier.classify_intent = AsyncMock(
            return_value=IntentResult(intent=Intent.REJECT)
        )

        # Create an active conversation in COMPARING state
        conversation_id = str(uuid.uuid4())
        conversation = ConversationState(
            id=conversation_id,
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            jira_ticket_key="PROJ-123",
            status=ConversationStatus.COMPARING,
            existing_acs=["Old AC"],
            proposed_acs=["New AC"],
        )
        repository.create(conversation)

        await dm_handler_with_approval_deps.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="cancel",
        )

        # Verify reject_acs was called on the regeneration service
        mock_regeneration_service.reject_acs.assert_called_once()
        call_args = mock_regeneration_service.reject_acs.call_args
        assert call_args[0][0].jira_ticket_key == "PROJ-123"

    @pytest.mark.asyncio
    async def test_comparing_state_with_reject_intent_message_text_matches_spec(
        self,
        dm_handler_with_approval_deps,
        mock_regeneration_service,
        mock_intent_classifier,
        repository,
    ):
        """Test that rejection message text matches functional specification exactly."""
        # Configure classifier to return REJECT
        mock_intent_classifier.classify_intent = AsyncMock(
            return_value=IntentResult(intent=Intent.REJECT)
        )

        # Create an active conversation in COMPARING state
        conversation = ConversationState(
            id=str(uuid.uuid4()),
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            jira_ticket_key="TEST-789",
            status=ConversationStatus.COMPARING,
            existing_acs=["Existing AC"],
            proposed_acs=["Proposed AC"],
        )
        repository.create(conversation)

        response = await dm_handler_with_approval_deps.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="reject",
        )

        # Per functional spec: "Cancelled. Original ACs remain unchanged."
        assert response.text == "Cancelled. Original ACs remain unchanged."

    @pytest.mark.asyncio
    async def test_comparing_state_with_modify_intent_triggers_regeneration(
        self,
        dm_handler_with_approval_deps,
        mock_regeneration_service,
        mock_intent_classifier,
        repository,
    ):
        """Test that MODIFY intent triggers regeneration with feedback."""
        # Configure classifier to return MODIFY
        mock_intent_classifier.classify_intent = AsyncMock(
            return_value=IntentResult(
                intent=Intent.MODIFY,
                modification_request="Add more details about error handling",
            )
        )

        # Configure service to return updated conversation
        mock_regeneration_service.regenerate_with_feedback = AsyncMock(
            return_value=ConversationState(
                id="test-id",
                slack_user_id="U12345678",
                slack_channel_id="D87654321",
                jira_ticket_key="PROJ-123",
                status=ConversationStatus.COMPARING,
                existing_acs=["Old AC"],
                proposed_acs=["Updated AC with error handling"],
            )
        )

        # Create an active conversation in COMPARING state
        conversation = ConversationState(
            id=str(uuid.uuid4()),
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            jira_ticket_key="PROJ-123",
            status=ConversationStatus.COMPARING,
            existing_acs=["Old AC"],
            proposed_acs=["New AC"],
        )
        repository.create(conversation)

        response = await dm_handler_with_approval_deps.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="add more about error handling",
        )

        # MODIFY triggers regeneration and returns new comparison
        assert response is not None
        assert "*Ticket:* PROJ-123" in response.text
        mock_regeneration_service.approve_acs.assert_not_called()
        mock_regeneration_service.regenerate_with_feedback.assert_called_once()

    @pytest.mark.asyncio
    async def test_comparing_state_without_intent_classifier_returns_none(
        self,
        mock_slack_client,
        repository,
        mock_regeneration_service,
    ):
        """Test that COMPARING state without intent classifier returns None."""
        # Create handler without intent_classifier
        handler = DMHandler(
            slack_client=mock_slack_client,
            repository=repository,
            regeneration_service=mock_regeneration_service,
            intent_classifier=None,
        )

        # Create an active conversation in COMPARING state
        conversation = ConversationState(
            id=str(uuid.uuid4()),
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            jira_ticket_key="PROJ-123",
            status=ConversationStatus.COMPARING,
            existing_acs=["Old AC"],
            proposed_acs=["New AC"],
        )
        repository.create(conversation)

        response = await handler.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="approve",
        )

        assert response is None

    @pytest.mark.asyncio
    async def test_jira_url_format_is_correct(
        self,
        dm_handler_with_approval_deps,
        mock_regeneration_service,
        mock_intent_classifier,
        repository,
    ):
        """Test that Jira URL follows the format: {base_url}/browse/{ticket_key}."""
        # Create an active conversation in COMPARING state
        conversation = ConversationState(
            id=str(uuid.uuid4()),
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            jira_ticket_key="TEST-42",
            status=ConversationStatus.COMPARING,
            existing_acs=["Old AC"],
            proposed_acs=["New AC"],
        )
        repository.create(conversation)

        response = await dm_handler_with_approval_deps.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="approve",
        )

        # Verify exact URL format
        assert "https://company.atlassian.net/browse/TEST-42" in response.text


class TestDMHandlerModifyIntent:
    """Test suite for DMHandler MODIFY intent handling."""

    @pytest.fixture
    def mock_intent_classifier(self):
        """Create a mock IntentClassifier that returns MODIFY intent."""
        classifier = MagicMock()
        classifier.classify_intent = AsyncMock(
            return_value=IntentResult(
                intent=Intent.MODIFY,
                modification_request="Add error handling criteria",
            )
        )
        return classifier

    @pytest.fixture
    def mock_jira_settings(self):
        """Create a mock JiraSettings for testing."""
        settings = MagicMock()
        settings.base_url = "https://company.atlassian.net"
        return settings

    @pytest.fixture
    def mock_regeneration_service(self):
        """Create a mock ACRegenerationService."""
        service = MagicMock()
        service.start_regeneration = AsyncMock()
        service.approve_acs = AsyncMock()
        service.regenerate_with_feedback = AsyncMock()
        return service

    @pytest.fixture
    def dm_handler_with_modify_deps(
        self,
        mock_slack_client,
        repository,
        mock_regeneration_service,
        mock_intent_classifier,
        mock_jira_settings,
    ):
        """Create a DMHandler with all dependencies for modification flow."""
        return DMHandler(
            slack_client=mock_slack_client,
            repository=repository,
            regeneration_service=mock_regeneration_service,
            intent_classifier=mock_intent_classifier,
            jira_settings=mock_jira_settings,
        )

    @pytest.mark.asyncio
    async def test_modify_intent_calls_regenerate_with_feedback(
        self,
        dm_handler_with_modify_deps,
        mock_regeneration_service,
        mock_intent_classifier,
        repository,
    ):
        """Test that MODIFY intent calls regenerate_with_feedback."""
        # Configure service to return updated conversation
        updated_conversation = ConversationState(
            id="test-id",
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            jira_ticket_key="PROJ-123",
            status=ConversationStatus.COMPARING,
            existing_acs=["Existing AC"],
            proposed_acs=["Updated AC 1", "Updated AC 2"],
        )
        mock_regeneration_service.regenerate_with_feedback.return_value = updated_conversation

        # Create an active conversation in COMPARING state
        conversation = ConversationState(
            id=str(uuid.uuid4()),
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            jira_ticket_key="PROJ-123",
            status=ConversationStatus.COMPARING,
            existing_acs=["Old AC"],
            proposed_acs=["Proposed AC"],
        )
        repository.create(conversation)

        await dm_handler_with_modify_deps.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="add error handling criteria",
        )

        mock_regeneration_service.regenerate_with_feedback.assert_called_once()

    @pytest.mark.asyncio
    async def test_modify_intent_returns_new_comparison(
        self,
        dm_handler_with_modify_deps,
        mock_regeneration_service,
        mock_intent_classifier,
        repository,
    ):
        """Test that MODIFY intent returns a new comparison message."""
        # Configure service to return updated conversation with new ACs
        updated_conversation = ConversationState(
            id="test-id",
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            jira_ticket_key="PROJ-123",
            status=ConversationStatus.COMPARING,
            existing_acs=["Existing AC"],
            proposed_acs=["New AC with error handling", "Another new AC"],
        )
        mock_regeneration_service.regenerate_with_feedback.return_value = updated_conversation

        # Create an active conversation in COMPARING state
        conversation = ConversationState(
            id=str(uuid.uuid4()),
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            jira_ticket_key="PROJ-123",
            status=ConversationStatus.COMPARING,
            existing_acs=["Existing AC"],
            proposed_acs=["Old Proposed AC"],
        )
        repository.create(conversation)

        response = await dm_handler_with_modify_deps.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="add more detail about error handling",
        )

        # Verify response is a formatted comparison message with new ACs
        assert response is not None
        assert "*Ticket:* PROJ-123" in response.text
        assert "*Proposed New Acceptance Criteria:*" in response.text
        assert "New AC with error handling" in response.text
        assert "Another new AC" in response.text
        assert 'Reply with "approve"' in response.text

    @pytest.mark.asyncio
    async def test_modify_intent_passes_modification_request_to_service(
        self,
        dm_handler_with_modify_deps,
        mock_regeneration_service,
        mock_intent_classifier,
        repository,
    ):
        """Test that modification_request is passed to regenerate_with_feedback."""
        # Configure service return value
        mock_regeneration_service.regenerate_with_feedback.return_value = ConversationState(
            id="test-id",
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            jira_ticket_key="PROJ-123",
            status=ConversationStatus.COMPARING,
            existing_acs=[],
            proposed_acs=["New AC"],
        )

        # Create an active conversation in COMPARING state
        conversation = ConversationState(
            id=str(uuid.uuid4()),
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            jira_ticket_key="PROJ-123",
            status=ConversationStatus.COMPARING,
            existing_acs=["Old AC"],
            proposed_acs=["Proposed AC"],
        )
        repository.create(conversation)

        await dm_handler_with_modify_deps.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="add error handling criteria",
        )

        # Verify the modification_request was passed
        call_args = mock_regeneration_service.regenerate_with_feedback.call_args
        assert call_args.kwargs["feedback"] == "Add error handling criteria"

    @pytest.mark.asyncio
    async def test_modify_intent_uses_original_text_if_no_modification_request(
        self,
        dm_handler_with_modify_deps,
        mock_regeneration_service,
        mock_intent_classifier,
        repository,
    ):
        """Test that original text is used if modification_request is None."""
        # Configure classifier to return MODIFY without modification_request
        mock_intent_classifier.classify_intent = AsyncMock(
            return_value=IntentResult(
                intent=Intent.MODIFY,
                modification_request=None,
            )
        )

        # Configure service return value
        mock_regeneration_service.regenerate_with_feedback.return_value = ConversationState(
            id="test-id",
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            jira_ticket_key="PROJ-123",
            status=ConversationStatus.COMPARING,
            existing_acs=[],
            proposed_acs=["New AC"],
        )

        # Create an active conversation in COMPARING state
        conversation = ConversationState(
            id=str(uuid.uuid4()),
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            jira_ticket_key="PROJ-123",
            status=ConversationStatus.COMPARING,
            existing_acs=["Old AC"],
            proposed_acs=["Proposed AC"],
        )
        repository.create(conversation)

        original_text = "make the ACs more specific"
        await dm_handler_with_modify_deps.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text=original_text,
        )

        # Verify the original text was used as feedback
        call_args = mock_regeneration_service.regenerate_with_feedback.call_args
        assert call_args.kwargs["feedback"] == original_text

    @pytest.mark.asyncio
    async def test_modify_intent_does_not_call_approve_acs(
        self,
        dm_handler_with_modify_deps,
        mock_regeneration_service,
        mock_intent_classifier,
        repository,
    ):
        """Test that MODIFY intent does not call approve_acs."""
        # Configure service return value
        mock_regeneration_service.regenerate_with_feedback.return_value = ConversationState(
            id="test-id",
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            jira_ticket_key="PROJ-123",
            status=ConversationStatus.COMPARING,
            existing_acs=[],
            proposed_acs=["New AC"],
        )

        # Create an active conversation in COMPARING state
        conversation = ConversationState(
            id=str(uuid.uuid4()),
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            jira_ticket_key="PROJ-123",
            status=ConversationStatus.COMPARING,
            existing_acs=["Old AC"],
            proposed_acs=["Proposed AC"],
        )
        repository.create(conversation)

        await dm_handler_with_modify_deps.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="change the criteria",
        )

        mock_regeneration_service.approve_acs.assert_not_called()

    @pytest.mark.asyncio
    async def test_modify_intent_passes_conversation_to_service(
        self,
        dm_handler_with_modify_deps,
        mock_regeneration_service,
        mock_intent_classifier,
        repository,
    ):
        """Test that the conversation is passed to regenerate_with_feedback."""
        # Configure service return value
        mock_regeneration_service.regenerate_with_feedback.return_value = ConversationState(
            id="test-id",
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            jira_ticket_key="PROJ-456",
            status=ConversationStatus.COMPARING,
            existing_acs=[],
            proposed_acs=["New AC"],
        )

        # Create an active conversation in COMPARING state
        conversation = ConversationState(
            id=str(uuid.uuid4()),
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            jira_ticket_key="PROJ-456",
            status=ConversationStatus.COMPARING,
            existing_acs=["Old AC"],
            proposed_acs=["Proposed AC"],
        )
        repository.create(conversation)

        await dm_handler_with_modify_deps.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="modify these",
        )

        # Verify the conversation was passed
        call_args = mock_regeneration_service.regenerate_with_feedback.call_args
        conversation_arg = call_args.kwargs["conversation"]
        assert conversation_arg.jira_ticket_key == "PROJ-456"

    @pytest.mark.asyncio
    async def test_modify_intent_classifies_message(
        self,
        dm_handler_with_modify_deps,
        mock_regeneration_service,
        mock_intent_classifier,
        repository,
    ):
        """Test that intent classifier is called with user message."""
        # Configure service return value
        mock_regeneration_service.regenerate_with_feedback.return_value = ConversationState(
            id="test-id",
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            jira_ticket_key="PROJ-123",
            status=ConversationStatus.COMPARING,
            existing_acs=[],
            proposed_acs=["New AC"],
        )

        # Create an active conversation in COMPARING state
        conversation = ConversationState(
            id=str(uuid.uuid4()),
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            jira_ticket_key="PROJ-123",
            status=ConversationStatus.COMPARING,
            existing_acs=["Old AC"],
            proposed_acs=["Proposed AC"],
        )
        repository.create(conversation)

        await dm_handler_with_modify_deps.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="add security requirements",
        )

        mock_intent_classifier.classify_intent.assert_called_once_with("add security requirements")


class TestDMHandlerErrorHandling:
    """Test suite for DMHandler error handling with user-friendly messages."""

    @pytest.fixture
    def mock_regeneration_service(self):
        """Create a mock ACRegenerationService for testing."""
        service = MagicMock()
        service.start_regeneration = AsyncMock()
        return service

    @pytest.fixture
    def dm_handler_with_service(self, mock_slack_client, repository, mock_regeneration_service):
        """Create a DMHandler with a mock regeneration service."""
        return DMHandler(
            slack_client=mock_slack_client,
            repository=repository,
            regeneration_service=mock_regeneration_service,
        )

    @pytest.mark.asyncio
    async def test_ticket_not_found_returns_correct_message(
        self, dm_handler_with_service, mock_regeneration_service
    ):
        """Test that 404 error returns the correct user-friendly message."""
        from src.jira import JiraTicketNotFoundError

        mock_regeneration_service.start_regeneration.side_effect = JiraTicketNotFoundError(
            "Ticket PROJ-123 not found"
        )

        response = await dm_handler_with_service.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="PROJ-123",
        )

        assert response.text == (
            "I couldn't find ticket PROJ-123 in Jira. "
            "Please check the ticket key and try again."
        )

    @pytest.mark.asyncio
    async def test_empty_description_returns_correct_message(
        self, dm_handler_with_service, mock_regeneration_service
    ):
        """Test that empty description error returns the correct user-friendly message."""
        from src.jira import EmptyDescriptionError

        mock_regeneration_service.start_regeneration.side_effect = EmptyDescriptionError(
            "PROJ-456"
        )

        response = await dm_handler_with_service.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="PROJ-456",
        )

        assert response.text == (
            "Ticket PROJ-456 doesn't have a description. "
            "Please add a description in Jira and try again."
        )

    @pytest.mark.asyncio
    async def test_jira_connection_error_returns_correct_message(
        self, dm_handler_with_service, mock_regeneration_service
    ):
        """Test that Jira connection error returns the correct user-friendly message."""
        from src.jira import JiraConnectionError

        mock_regeneration_service.start_regeneration.side_effect = JiraConnectionError(
            "Failed to connect to Jira"
        )

        response = await dm_handler_with_service.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="PROJ-789",
        )

        assert response.text == (
            "I'm having trouble connecting to Jira right now. "
            "Please try again in a few minutes."
        )

    @pytest.mark.asyncio
    async def test_permission_denied_returns_correct_message(
        self, dm_handler_with_service, mock_regeneration_service
    ):
        """Test that 403 permission error returns the correct user-friendly message."""
        from src.jira import JiraAuthenticationError

        mock_regeneration_service.start_regeneration.side_effect = JiraAuthenticationError(
            "Authentication failed with status 403"
        )

        response = await dm_handler_with_service.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="PROJ-999",
        )

        assert response.text == (
            "I don't have access to ticket PROJ-999. "
            "Please check that the ticket exists and that the bot "
            "has the necessary permissions."
        )

    @pytest.mark.asyncio
    async def test_ticket_not_found_sets_conversation_to_error_status(
        self, dm_handler_with_service, mock_regeneration_service, repository
    ):
        """Test that ticket not found error sets conversation status to ERROR."""
        from src.jira import JiraTicketNotFoundError

        mock_regeneration_service.start_regeneration.side_effect = JiraTicketNotFoundError(
            "Ticket TEST-111 not found"
        )

        await dm_handler_with_service.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="TEST-111",
        )

        # Query directly to get conversation in ERROR status
        cursor = repository._conn.execute(
            "SELECT id FROM conversations WHERE slack_user_id = ? AND slack_channel_id = ? ORDER BY created_at DESC LIMIT 1",
            ("U12345678", "D87654321"),
        )
        row = cursor.fetchone()
        assert row is not None
        conversation = repository.get_by_id(row[0])
        assert conversation is not None
        assert conversation.status == ConversationStatus.ERROR

    @pytest.mark.asyncio
    async def test_empty_description_sets_conversation_to_error_status(
        self, dm_handler_with_service, mock_regeneration_service, repository
    ):
        """Test that empty description error sets conversation status to ERROR."""
        from src.jira import EmptyDescriptionError

        mock_regeneration_service.start_regeneration.side_effect = EmptyDescriptionError(
            "TEST-222"
        )

        await dm_handler_with_service.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="TEST-222",
        )

        # Query directly to get conversation in ERROR status
        cursor = repository._conn.execute(
            "SELECT id FROM conversations WHERE slack_user_id = ? AND slack_channel_id = ? ORDER BY created_at DESC LIMIT 1",
            ("U12345678", "D87654321"),
        )
        row = cursor.fetchone()
        assert row is not None
        conversation = repository.get_by_id(row[0])
        assert conversation is not None
        assert conversation.status == ConversationStatus.ERROR

    @pytest.mark.asyncio
    async def test_jira_connection_error_sets_conversation_to_error_status(
        self, dm_handler_with_service, mock_regeneration_service, repository
    ):
        """Test that Jira connection error sets conversation status to ERROR."""
        from src.jira import JiraConnectionError

        mock_regeneration_service.start_regeneration.side_effect = JiraConnectionError(
            "Failed to connect"
        )

        await dm_handler_with_service.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="TEST-333",
        )

        # Query directly to get conversation in ERROR status
        cursor = repository._conn.execute(
            "SELECT id FROM conversations WHERE slack_user_id = ? AND slack_channel_id = ? ORDER BY created_at DESC LIMIT 1",
            ("U12345678", "D87654321"),
        )
        row = cursor.fetchone()
        assert row is not None
        conversation = repository.get_by_id(row[0])
        assert conversation is not None
        assert conversation.status == ConversationStatus.ERROR

    @pytest.mark.asyncio
    async def test_permission_denied_sets_conversation_to_error_status(
        self, dm_handler_with_service, mock_regeneration_service, repository
    ):
        """Test that permission denied error sets conversation status to ERROR."""
        from src.jira import JiraAuthenticationError

        mock_regeneration_service.start_regeneration.side_effect = JiraAuthenticationError(
            "Authentication failed"
        )

        await dm_handler_with_service.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="TEST-444",
        )

        # Query directly to get conversation in ERROR status
        cursor = repository._conn.execute(
            "SELECT id FROM conversations WHERE slack_user_id = ? AND slack_channel_id = ? ORDER BY created_at DESC LIMIT 1",
            ("U12345678", "D87654321"),
        )
        row = cursor.fetchone()
        assert row is not None
        conversation = repository.get_by_id(row[0])
        assert conversation is not None
        assert conversation.status == ConversationStatus.ERROR

    @pytest.mark.asyncio
    async def test_error_message_is_stored_on_conversation(
        self, dm_handler_with_service, mock_regeneration_service, repository
    ):
        """Test that error message is stored on the conversation."""
        from src.jira import JiraTicketNotFoundError

        mock_regeneration_service.start_regeneration.side_effect = JiraTicketNotFoundError(
            "Ticket TEST-555 not found"
        )

        await dm_handler_with_service.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="TEST-555",
        )

        # Query directly to get conversation in ERROR status
        cursor = repository._conn.execute(
            "SELECT id FROM conversations WHERE slack_user_id = ? AND slack_channel_id = ? ORDER BY created_at DESC LIMIT 1",
            ("U12345678", "D87654321"),
        )
        row = cursor.fetchone()
        assert row is not None
        conversation = repository.get_by_id(row[0])
        assert conversation is not None
        assert conversation.error_message == (
            "I couldn't find ticket TEST-555 in Jira. "
            "Please check the ticket key and try again."
        )

    @pytest.mark.asyncio
    async def test_empty_description_error_message_is_stored(
        self, dm_handler_with_service, mock_regeneration_service, repository
    ):
        """Test that empty description error message is stored on the conversation."""
        from src.jira import EmptyDescriptionError

        mock_regeneration_service.start_regeneration.side_effect = EmptyDescriptionError(
            "TEST-666"
        )

        await dm_handler_with_service.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="TEST-666",
        )

        # Query directly to get conversation in ERROR status
        cursor = repository._conn.execute(
            "SELECT id FROM conversations WHERE slack_user_id = ? AND slack_channel_id = ? ORDER BY created_at DESC LIMIT 1",
            ("U12345678", "D87654321"),
        )
        row = cursor.fetchone()
        assert row is not None
        conversation = repository.get_by_id(row[0])
        assert conversation is not None
        assert conversation.error_message == (
            "Ticket TEST-666 doesn't have a description. "
            "Please add a description in Jira and try again."
        )


class TestDMHandlerEventDeduplication:
    """Test suite for DMHandler event deduplication mechanism."""

    @pytest.mark.asyncio
    async def test_same_event_processed_only_once(self, dm_handler):
        """Test that the same event (same ts+channel) is processed only once."""
        # First call should be processed normally
        response1 = await dm_handler.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="PROJ-123",
            event_ts="1234567890.123456",
        )
        assert response1.text == "Processing PROJ-123..."

        # Second call with same ts+channel should be skipped (duplicate)
        response2 = await dm_handler.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="PROJ-123",
            event_ts="1234567890.123456",
        )
        assert response2 is None

    @pytest.mark.asyncio
    async def test_different_ts_same_channel_both_processed(self, dm_handler):
        """Test that events with different ts values on the same channel are both processed."""
        response1 = await dm_handler.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="PROJ-111",
            event_ts="1234567890.000001",
        )
        assert response1.text == "Processing PROJ-111..."

        response2 = await dm_handler.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="PROJ-222",
            event_ts="1234567890.000002",
        )
        assert response2.text == "Processing PROJ-222..."

    @pytest.mark.asyncio
    async def test_same_ts_different_channel_both_processed(self, dm_handler):
        """Test that events with same ts but different channels are both processed."""
        response1 = await dm_handler.handle_message(
            user_id="U12345678",
            channel_id="D11111111",
            text="PROJ-111",
            event_ts="1234567890.123456",
        )
        assert response1.text == "Processing PROJ-111..."

        response2 = await dm_handler.handle_message(
            user_id="U12345678",
            channel_id="D22222222",
            text="PROJ-222",
            event_ts="1234567890.123456",
        )
        assert response2.text == "Processing PROJ-222..."

    @pytest.mark.asyncio
    async def test_expired_cache_entry_allows_reprocessing(self, dm_handler):
        """Test that expired cache entries allow reprocessing after TTL."""
        import time as _time
        from unittest.mock import patch

        # First call - should be processed
        response1 = await dm_handler.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="PROJ-123",
            event_ts="1234567890.123456",
        )
        assert response1.text == "Processing PROJ-123..."

        # Simulate time passing beyond the TTL by manipulating the cache entry
        # We patch time.monotonic to return a value far in the future
        original_monotonic = _time.monotonic
        future_time = original_monotonic() + EVENT_DEDUP_TTL_SECONDS + 1

        with patch("src.slack.handlers.dm_handler.time.monotonic", return_value=future_time):
            # After TTL expiry, the same event should be processable again
            response2 = await dm_handler.handle_message(
                user_id="U12345678",
                channel_id="D87654321",
                text="PROJ-123",
                event_ts="1234567890.123456",
            )
            assert response2.text == "Processing PROJ-123..."

    @pytest.mark.asyncio
    async def test_no_event_ts_skips_deduplication(self, dm_handler):
        """Test that events without event_ts bypass deduplication entirely."""
        # Both calls should be processed since event_ts is None (default)
        response1 = await dm_handler.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="PROJ-123",
        )
        assert response1.text == "Processing PROJ-123..."

        response2 = await dm_handler.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="PROJ-456",
        )
        assert response2.text == "Processing PROJ-456..."

    @pytest.mark.asyncio
    async def test_duplicate_event_does_not_create_conversation(
        self, dm_handler, repository
    ):
        """Test that a duplicate event does not create a new conversation."""
        # First call creates a conversation
        await dm_handler.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="PROJ-123",
            event_ts="1234567890.123456",
        )
        first_conversation = repository.get_active("U12345678", "D87654321")
        assert first_conversation is not None
        first_id = first_conversation.id

        # Duplicate call should be skipped entirely
        await dm_handler.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="PROJ-123",
            event_ts="1234567890.123456",
        )

        # Should still have the same active conversation (no new one created)
        current_conversation = repository.get_active("U12345678", "D87654321")
        assert current_conversation is not None
        assert current_conversation.id == first_id

    @pytest.mark.asyncio
    async def test_cleanup_removes_expired_entries(self, dm_handler):
        """Test that _cleanup_expired_events removes old entries from cache."""
        import time as _time
        from unittest.mock import patch

        # Record an event at a specific time
        base_time = _time.monotonic()
        with patch(
            "src.slack.handlers.dm_handler.time.monotonic", return_value=base_time
        ):
            await dm_handler.handle_message(
                user_id="U12345678",
                channel_id="D87654321",
                text="PROJ-123",
                event_ts="1111111111.111111",
            )
        assert len(dm_handler._seen_events) == 1

        # Advance time past TTL and trigger cleanup via a new event
        future_time = base_time + EVENT_DEDUP_TTL_SECONDS + 1
        with patch(
            "src.slack.handlers.dm_handler.time.monotonic", return_value=future_time
        ):
            await dm_handler.handle_message(
                user_id="U12345678",
                channel_id="D87654321",
                text="PROJ-456",
                event_ts="2222222222.222222",
            )

        # Old entry should be cleaned up, only the new one remains
        assert "1111111111.111111:D87654321" not in dm_handler._seen_events
        assert "2222222222.222222:D87654321" in dm_handler._seen_events

    @pytest.mark.asyncio
    async def test_dedup_key_format_is_ts_colon_channel(self, dm_handler):
        """Test that the deduplication key follows the 'ts:channel' format."""
        await dm_handler.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="PROJ-123",
            event_ts="1234567890.123456",
        )

        expected_key = "1234567890.123456:D87654321"
        assert expected_key in dm_handler._seen_events


class TestDMHandlerUnsupportedIssueType:
    """Test suite for BUG-1: unsupported issue type error handling."""

    @pytest.fixture
    def mock_regeneration_service(self):
        """Create a mock ACRegenerationService for testing."""
        service = MagicMock()
        service.start_regeneration = AsyncMock()
        return service

    @pytest.fixture
    def dm_handler_with_service(self, mock_slack_client, repository, mock_regeneration_service):
        """Create a DMHandler with a mock regeneration service."""
        return DMHandler(
            slack_client=mock_slack_client,
            repository=repository,
            regeneration_service=mock_regeneration_service,
        )

    @pytest.mark.asyncio
    async def test_unsupported_issue_type_returns_user_friendly_message(
        self, dm_handler_with_service, mock_regeneration_service
    ):
        """Test that unsupported issue type error returns a user-friendly message."""
        from src.jira import JiraIssueTypeNotSupportedError

        mock_regeneration_service.start_regeneration.side_effect = (
            JiraIssueTypeNotSupportedError(
                "Issue type 'Bug' is not supported. Supported types: ['Story', 'Task']"
            )
        )

        response = await dm_handler_with_service.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="IGAL-123",
        )

        assert response is not None
        assert "IGAL-123" in response.text
        assert "unsupported issue type" in response.text
        assert "Bug" in response.text
        assert "Story" in response.text
        assert "Task" in response.text

    @pytest.mark.asyncio
    async def test_unsupported_issue_type_sets_conversation_to_error(
        self, dm_handler_with_service, mock_regeneration_service, repository
    ):
        """Test that unsupported issue type sets conversation status to ERROR."""
        from src.jira import JiraIssueTypeNotSupportedError

        mock_regeneration_service.start_regeneration.side_effect = (
            JiraIssueTypeNotSupportedError(
                "Issue type 'Bug' is not supported. Supported types: ['Story', 'Task']"
            )
        )

        await dm_handler_with_service.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="IGAL-456",
        )

        # Query directly to get conversation in ERROR status
        cursor = repository._conn.execute(
            "SELECT id FROM conversations WHERE slack_user_id = ? AND slack_channel_id = ? ORDER BY created_at DESC LIMIT 1",
            ("U12345678", "D87654321"),
        )
        row = cursor.fetchone()
        assert row is not None
        conversation = repository.get_by_id(row[0])
        assert conversation is not None
        assert conversation.status == ConversationStatus.ERROR

    @pytest.mark.asyncio
    async def test_unsupported_issue_type_does_not_silently_fail(
        self, dm_handler_with_service, mock_regeneration_service
    ):
        """Test that unsupported issue type does NOT return None (silent failure)."""
        from src.jira import JiraIssueTypeNotSupportedError

        mock_regeneration_service.start_regeneration.side_effect = (
            JiraIssueTypeNotSupportedError(
                "Issue type 'Epic' is not supported. Supported types: ['Story', 'Task']"
            )
        )

        response = await dm_handler_with_service.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="PROJ-789",
        )

        # The key assertion: response must NOT be None
        assert response is not None


class TestDMHandlerStaleConversation:
    """Test suite for BUG-2: stale conversations in processing states."""

    @pytest.mark.asyncio
    async def test_stale_fetching_ticket_conversation_gets_reset(
        self, dm_handler, repository
    ):
        """Test that a stale FETCHING_TICKET conversation is reset on new message."""
        # Create an active conversation stuck in FETCHING_TICKET state
        conversation = ConversationState(
            id=str(uuid.uuid4()),
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            jira_ticket_key="PROJ-999",
            status=ConversationStatus.FETCHING_TICKET,
        )
        repository.create(conversation)

        # User sends a new message (without a ticket key)
        response = await dm_handler.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="hello, are you there?",
        )

        # Should get a helpful response, not None
        assert response is not None
        assert "previous request got stuck" in response.text
        assert "PROJ-123" in response.text  # contains the prompt format

    @pytest.mark.asyncio
    async def test_stale_generating_acs_conversation_gets_reset(
        self, dm_handler, repository
    ):
        """Test that a stale GENERATING_ACS conversation is reset on new message."""
        conversation = ConversationState(
            id=str(uuid.uuid4()),
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            jira_ticket_key="PROJ-888",
            status=ConversationStatus.GENERATING_ACS,
        )
        repository.create(conversation)

        response = await dm_handler.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="what's happening?",
        )

        assert response is not None
        assert "previous request got stuck" in response.text

    @pytest.mark.asyncio
    async def test_stale_writing_to_jira_conversation_gets_reset(
        self, dm_handler, repository
    ):
        """Test that a stale WRITING_TO_JIRA conversation is reset on new message."""
        conversation = ConversationState(
            id=str(uuid.uuid4()),
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            jira_ticket_key="PROJ-777",
            status=ConversationStatus.WRITING_TO_JIRA,
        )
        repository.create(conversation)

        response = await dm_handler.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="still waiting...",
        )

        assert response is not None
        assert "previous request got stuck" in response.text

    @pytest.mark.asyncio
    async def test_stale_conversation_is_marked_as_error(
        self, dm_handler, repository
    ):
        """Test that a stale conversation is marked as ERROR status."""
        conversation_id = str(uuid.uuid4())
        conversation = ConversationState(
            id=conversation_id,
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            jira_ticket_key="PROJ-999",
            status=ConversationStatus.FETCHING_TICKET,
        )
        repository.create(conversation)

        await dm_handler.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="hello",
        )

        # Verify the conversation was marked as ERROR
        updated = repository.get_by_id(conversation_id)
        assert updated is not None
        assert updated.status == ConversationStatus.ERROR
        assert updated.error_message is not None

    @pytest.mark.asyncio
    async def test_stale_conversation_reset_allows_new_request(
        self, dm_handler, repository
    ):
        """Test that after resetting a stale conversation, user can start a new request."""
        conversation = ConversationState(
            id=str(uuid.uuid4()),
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            jira_ticket_key="PROJ-999",
            status=ConversationStatus.FETCHING_TICKET,
        )
        repository.create(conversation)

        # First message: resets the stale conversation
        response1 = await dm_handler.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="hello",
        )
        assert "previous request got stuck" in response1.text

        # Second message: user can now submit a new ticket
        response2 = await dm_handler.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="PROJ-456",
        )
        assert response2.text == "Processing PROJ-456..."

    @pytest.mark.asyncio
    async def test_comparing_state_is_not_treated_as_stale(
        self, dm_handler, repository
    ):
        """Test that COMPARING state is NOT treated as stale (it expects user input)."""
        conversation = ConversationState(
            id=str(uuid.uuid4()),
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            jira_ticket_key="PROJ-123",
            status=ConversationStatus.COMPARING,
            existing_acs=["AC1"],
            proposed_acs=["AC2"],
        )
        repository.create(conversation)

        # Without intent classifier, this returns None (existing behavior)
        response = await dm_handler.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="looks good",
        )

        # Should NOT contain the stale message
        assert response is None  # existing behavior without classifier


class TestDMHandlerJiraUrlDoubleSlash:
    """Test suite for BUG-3: double slash in Jira URL."""

    @pytest.fixture
    def mock_intent_classifier(self):
        """Create a mock IntentClassifier for testing."""
        classifier = MagicMock()
        classifier.classify_intent = AsyncMock(
            return_value=IntentResult(intent=Intent.APPROVE)
        )
        return classifier

    @pytest.fixture
    def mock_regeneration_service(self):
        """Create a mock ACRegenerationService."""
        service = MagicMock()
        service.start_regeneration = AsyncMock()
        service.approve_acs = AsyncMock()
        return service

    @pytest.fixture
    def mock_jira_settings_trailing_slash(self):
        """Create a mock JiraSettings with trailing slash in base_url."""
        settings = MagicMock()
        settings.base_url = "https://provectus-dev.atlassian.net/"
        return settings

    @pytest.fixture
    def dm_handler_with_trailing_slash(
        self,
        mock_slack_client,
        repository,
        mock_regeneration_service,
        mock_intent_classifier,
        mock_jira_settings_trailing_slash,
    ):
        """Create a DMHandler with trailing slash in Jira base URL."""
        return DMHandler(
            slack_client=mock_slack_client,
            repository=repository,
            regeneration_service=mock_regeneration_service,
            intent_classifier=mock_intent_classifier,
            jira_settings=mock_jira_settings_trailing_slash,
        )

    @pytest.mark.asyncio
    async def test_jira_url_no_double_slash_with_trailing_slash_base_url(
        self,
        dm_handler_with_trailing_slash,
        mock_regeneration_service,
        mock_intent_classifier,
        repository,
    ):
        """Test that Jira URL has no double slash when base_url has trailing slash."""
        # Create an active conversation in COMPARING state
        conversation = ConversationState(
            id=str(uuid.uuid4()),
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            jira_ticket_key="IGAL-1951",
            status=ConversationStatus.COMPARING,
            existing_acs=["Old AC"],
            proposed_acs=["New AC"],
        )
        repository.create(conversation)

        response = await dm_handler_with_trailing_slash.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="approve",
        )

        assert response is not None
        # The key assertion: no double slash before "browse"
        assert "//browse" not in response.text
        assert "https://provectus-dev.atlassian.net/browse/IGAL-1951" in response.text

    @pytest.mark.asyncio
    async def test_jira_url_correct_without_trailing_slash(
        self,
        mock_slack_client,
        repository,
        mock_intent_classifier,
    ):
        """Test that Jira URL is correct when base_url has no trailing slash."""
        mock_jira_settings = MagicMock()
        mock_jira_settings.base_url = "https://company.atlassian.net"

        mock_regen_service = MagicMock()
        mock_regen_service.approve_acs = AsyncMock()

        handler = DMHandler(
            slack_client=mock_slack_client,
            repository=repository,
            regeneration_service=mock_regen_service,
            intent_classifier=mock_intent_classifier,
            jira_settings=mock_jira_settings,
        )

        conversation = ConversationState(
            id=str(uuid.uuid4()),
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            jira_ticket_key="PROJ-100",
            status=ConversationStatus.COMPARING,
            existing_acs=["AC"],
            proposed_acs=["New AC"],
        )
        repository.create(conversation)

        response = await handler.handle_message(
            user_id="U12345678",
            channel_id="D87654321",
            text="approve",
        )

        assert response is not None
        assert "https://company.atlassian.net/browse/PROJ-100" in response.text

    def test_build_jira_url_strips_trailing_slash(self, mock_slack_client, repository):
        """Test _build_jira_url directly strips trailing slash."""
        mock_jira_settings = MagicMock()
        mock_jira_settings.base_url = "https://example.atlassian.net/"

        handler = DMHandler(
            slack_client=mock_slack_client,
            repository=repository,
            jira_settings=mock_jira_settings,
        )

        url = handler._build_jira_url("TEST-42")
        assert url == "https://example.atlassian.net/browse/TEST-42"
        assert "//" not in url.replace("https://", "")

    def test_build_jira_url_strips_multiple_trailing_slashes(
        self, mock_slack_client, repository
    ):
        """Test _build_jira_url strips multiple trailing slashes."""
        mock_jira_settings = MagicMock()
        mock_jira_settings.base_url = "https://example.atlassian.net///"

        handler = DMHandler(
            slack_client=mock_slack_client,
            repository=repository,
            jira_settings=mock_jira_settings,
        )

        url = handler._build_jira_url("TEST-99")
        assert url == "https://example.atlassian.net/browse/TEST-99"
