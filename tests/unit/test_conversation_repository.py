"""Unit tests for conversation repository."""

from __future__ import annotations

import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.database import (
    ConversationRepository,
    ConversationState,
    ConversationStatus,
    DatabaseSettings,
    MessageRecord,
    get_database_connection,
)


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
def sample_conversation():
    """Create a sample conversation for testing."""
    return ConversationState(
        id=str(uuid.uuid4()),
        slack_user_id="U12345678",
        slack_channel_id="D87654321",
        jira_ticket_key=None,
        status=ConversationStatus.AWAITING_TICKET,
        existing_acs=None,
        proposed_acs=None,
        message_history=[],
    )


class TestDatabaseConnection:
    """Test suite for database connection management."""

    def test_get_database_connection_creates_directory(self, temp_db_path):
        """Test that get_database_connection creates parent directories."""
        settings = DatabaseSettings(database_path=temp_db_path)
        conn = get_database_connection(settings)

        assert Path(temp_db_path).parent.exists()
        conn.close()

    def test_get_database_connection_initializes_schema(self, db_settings):
        """Test that get_database_connection initializes the schema."""
        conn = get_database_connection(db_settings)

        # Check that conversations table exists
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='conversations'"
        )
        result = cursor.fetchone()

        assert result is not None
        assert result[0] == "conversations"
        conn.close()


class TestConversationRepositoryCreate:
    """Test suite for ConversationRepository.create method."""

    def test_create_and_retrieve_conversation(self, repository, sample_conversation):
        """Test that a conversation can be created and retrieved."""
        created = repository.create(sample_conversation)

        assert created.id == sample_conversation.id
        assert created.slack_user_id == sample_conversation.slack_user_id
        assert created.slack_channel_id == sample_conversation.slack_channel_id
        assert created.status == ConversationStatus.AWAITING_TICKET

    def test_create_sets_timestamps(self, repository, sample_conversation):
        """Test that create sets created_at and updated_at timestamps."""
        created = repository.create(sample_conversation)

        assert created.created_at is not None
        assert created.updated_at is not None

    def test_create_with_jira_ticket_key(self, repository):
        """Test creating a conversation with a Jira ticket key."""
        conversation = ConversationState(
            id=str(uuid.uuid4()),
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            jira_ticket_key="PROJ-123",
            status=ConversationStatus.FETCHING_TICKET,
        )

        created = repository.create(conversation)

        assert created.jira_ticket_key == "PROJ-123"
        assert created.status == ConversationStatus.FETCHING_TICKET

    def test_create_with_acs(self, repository):
        """Test creating a conversation with existing and proposed ACs."""
        conversation = ConversationState(
            id=str(uuid.uuid4()),
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            jira_ticket_key="PROJ-123",
            status=ConversationStatus.COMPARING,
            existing_acs=["AC1: Given X, When Y, Then Z"],
            proposed_acs=["AC1: Given A, When B, Then C", "AC2: Given D, When E, Then F"],
        )

        created = repository.create(conversation)

        assert created.existing_acs == ["AC1: Given X, When Y, Then Z"]
        assert created.proposed_acs == ["AC1: Given A, When B, Then C", "AC2: Given D, When E, Then F"]

    def test_create_with_message_history(self, repository):
        """Test creating a conversation with message history."""
        messages = [
            MessageRecord(role="user", content="Generate ACs for PROJ-123"),
            MessageRecord(role="assistant", content="Fetching ticket PROJ-123..."),
        ]
        conversation = ConversationState(
            id=str(uuid.uuid4()),
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            message_history=messages,
        )

        created = repository.create(conversation)

        assert len(created.message_history) == 2
        assert created.message_history[0].role == "user"
        assert created.message_history[0].content == "Generate ACs for PROJ-123"
        assert created.message_history[1].role == "assistant"


class TestConversationRepositoryGetById:
    """Test suite for ConversationRepository.get_by_id method."""

    def test_get_by_id_returns_conversation(self, repository, sample_conversation):
        """Test that get_by_id returns the correct conversation."""
        created = repository.create(sample_conversation)

        retrieved = repository.get_by_id(created.id)

        assert retrieved is not None
        assert retrieved.id == created.id
        assert retrieved.slack_user_id == created.slack_user_id

    def test_get_by_id_returns_none_for_nonexistent(self, repository):
        """Test that get_by_id returns None for nonexistent ID."""
        retrieved = repository.get_by_id("nonexistent-id")

        assert retrieved is None

    def test_get_by_id_deserializes_json_fields(self, repository):
        """Test that get_by_id properly deserializes JSON fields."""
        conversation = ConversationState(
            id=str(uuid.uuid4()),
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            existing_acs=["AC1", "AC2"],
            proposed_acs=["AC3"],
            message_history=[MessageRecord(role="user", content="Hello")],
        )
        created = repository.create(conversation)

        retrieved = repository.get_by_id(created.id)

        assert retrieved.existing_acs == ["AC1", "AC2"]
        assert retrieved.proposed_acs == ["AC3"]
        assert len(retrieved.message_history) == 1
        assert retrieved.message_history[0].content == "Hello"


class TestConversationRepositoryGetActive:
    """Test suite for ConversationRepository.get_active method."""

    def test_get_active_finds_awaiting_ticket(self, repository):
        """Test that get_active finds a conversation in AWAITING_TICKET status."""
        conversation = ConversationState(
            id=str(uuid.uuid4()),
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            status=ConversationStatus.AWAITING_TICKET,
        )
        repository.create(conversation)

        active = repository.get_active("U12345678", "D87654321")

        assert active is not None
        assert active.id == conversation.id

    def test_get_active_finds_generating_acs(self, repository):
        """Test that get_active finds a conversation in GENERATING_ACS status."""
        conversation = ConversationState(
            id=str(uuid.uuid4()),
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            status=ConversationStatus.GENERATING_ACS,
        )
        repository.create(conversation)

        active = repository.get_active("U12345678", "D87654321")

        assert active is not None
        assert active.status == ConversationStatus.GENERATING_ACS

    def test_get_active_ignores_completed(self, repository):
        """Test that get_active ignores COMPLETED conversations."""
        conversation = ConversationState(
            id=str(uuid.uuid4()),
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            status=ConversationStatus.COMPLETED,
        )
        repository.create(conversation)

        active = repository.get_active("U12345678", "D87654321")

        assert active is None

    def test_get_active_ignores_cancelled(self, repository):
        """Test that get_active ignores CANCELLED conversations."""
        conversation = ConversationState(
            id=str(uuid.uuid4()),
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            status=ConversationStatus.CANCELLED,
        )
        repository.create(conversation)

        active = repository.get_active("U12345678", "D87654321")

        assert active is None

    def test_get_active_ignores_error(self, repository):
        """Test that get_active ignores ERROR conversations."""
        conversation = ConversationState(
            id=str(uuid.uuid4()),
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            status=ConversationStatus.ERROR,
        )
        repository.create(conversation)

        active = repository.get_active("U12345678", "D87654321")

        assert active is None

    def test_get_active_returns_most_recent(self, repository):
        """Test that get_active returns the most recent active conversation."""
        old_conversation = ConversationState(
            id=str(uuid.uuid4()),
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            status=ConversationStatus.AWAITING_TICKET,
        )
        repository.create(old_conversation)

        new_conversation = ConversationState(
            id=str(uuid.uuid4()),
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            status=ConversationStatus.GENERATING_ACS,
        )
        repository.create(new_conversation)

        active = repository.get_active("U12345678", "D87654321")

        # Should return the newest one (GENERATING_ACS)
        assert active is not None
        assert active.status == ConversationStatus.GENERATING_ACS

    def test_get_active_filters_by_user(self, repository):
        """Test that get_active filters by slack_user_id."""
        conversation = ConversationState(
            id=str(uuid.uuid4()),
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            status=ConversationStatus.AWAITING_TICKET,
        )
        repository.create(conversation)

        # Different user
        active = repository.get_active("U99999999", "D87654321")

        assert active is None

    def test_get_active_filters_by_channel(self, repository):
        """Test that get_active filters by slack_channel_id."""
        conversation = ConversationState(
            id=str(uuid.uuid4()),
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            status=ConversationStatus.AWAITING_TICKET,
        )
        repository.create(conversation)

        # Different channel
        active = repository.get_active("U12345678", "D99999999")

        assert active is None


class TestConversationRepositoryUpdate:
    """Test suite for ConversationRepository.update method."""

    def test_update_modifies_status(self, repository, sample_conversation):
        """Test that update modifies the status field."""
        created = repository.create(sample_conversation)

        created.status = ConversationStatus.GENERATING_ACS
        updated = repository.update(created)

        assert updated.status == ConversationStatus.GENERATING_ACS

        # Verify persistence
        retrieved = repository.get_by_id(created.id)
        assert retrieved.status == ConversationStatus.GENERATING_ACS

    def test_update_modifies_jira_ticket_key(self, repository, sample_conversation):
        """Test that update modifies the jira_ticket_key field."""
        created = repository.create(sample_conversation)

        created.jira_ticket_key = "PROJ-456"
        updated = repository.update(created)

        assert updated.jira_ticket_key == "PROJ-456"

    def test_update_modifies_acs(self, repository, sample_conversation):
        """Test that update modifies existing_acs and proposed_acs fields."""
        created = repository.create(sample_conversation)

        created.existing_acs = ["Old AC"]
        created.proposed_acs = ["New AC 1", "New AC 2"]
        updated = repository.update(created)

        assert updated.existing_acs == ["Old AC"]
        assert updated.proposed_acs == ["New AC 1", "New AC 2"]

    def test_update_appends_message_history(self, repository, sample_conversation):
        """Test that update can append to message history."""
        created = repository.create(sample_conversation)

        created.message_history.append(
            MessageRecord(role="user", content="Test message")
        )
        updated = repository.update(created)

        assert len(updated.message_history) == 1
        assert updated.message_history[0].content == "Test message"

    def test_update_changes_updated_at(self, repository, sample_conversation):
        """Test that update changes the updated_at timestamp."""
        created = repository.create(sample_conversation)
        original_updated_at = created.updated_at

        created.status = ConversationStatus.GENERATING_ACS
        updated = repository.update(created)

        assert updated.updated_at != original_updated_at


class TestConversationRepositoryDelete:
    """Test suite for ConversationRepository.delete method."""

    def test_delete_removes_conversation(self, repository, sample_conversation):
        """Test that delete removes the conversation."""
        created = repository.create(sample_conversation)

        result = repository.delete(created.id)

        assert result is True
        assert repository.get_by_id(created.id) is None

    def test_delete_returns_false_for_nonexistent(self, repository):
        """Test that delete returns False for nonexistent ID."""
        result = repository.delete("nonexistent-id")

        assert result is False


class TestConversationStatusTransitions:
    """Test suite for conversation status transitions."""

    def test_awaiting_ticket_to_fetching_ticket(self, repository, sample_conversation):
        """Test transition from AWAITING_TICKET to FETCHING_TICKET."""
        created = repository.create(sample_conversation)
        assert created.status == ConversationStatus.AWAITING_TICKET

        created.status = ConversationStatus.FETCHING_TICKET
        created.jira_ticket_key = "PROJ-123"
        updated = repository.update(created)

        assert updated.status == ConversationStatus.FETCHING_TICKET

    def test_fetching_ticket_to_generating_acs(self, repository):
        """Test transition from FETCHING_TICKET to GENERATING_ACS."""
        conversation = ConversationState(
            id=str(uuid.uuid4()),
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            jira_ticket_key="PROJ-123",
            status=ConversationStatus.FETCHING_TICKET,
        )
        created = repository.create(conversation)

        created.status = ConversationStatus.GENERATING_ACS
        updated = repository.update(created)

        assert updated.status == ConversationStatus.GENERATING_ACS

    def test_generating_acs_to_comparing(self, repository):
        """Test transition from GENERATING_ACS to COMPARING."""
        conversation = ConversationState(
            id=str(uuid.uuid4()),
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            jira_ticket_key="PROJ-123",
            status=ConversationStatus.GENERATING_ACS,
        )
        created = repository.create(conversation)

        created.status = ConversationStatus.COMPARING
        created.proposed_acs = ["New AC 1", "New AC 2"]
        updated = repository.update(created)

        assert updated.status == ConversationStatus.COMPARING

    def test_comparing_to_awaiting_approval(self, repository):
        """Test transition from COMPARING to AWAITING_APPROVAL."""
        conversation = ConversationState(
            id=str(uuid.uuid4()),
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            jira_ticket_key="PROJ-123",
            status=ConversationStatus.COMPARING,
            proposed_acs=["AC 1", "AC 2"],
        )
        created = repository.create(conversation)

        created.status = ConversationStatus.AWAITING_APPROVAL
        updated = repository.update(created)

        assert updated.status == ConversationStatus.AWAITING_APPROVAL

    def test_awaiting_approval_to_processing_modification(self, repository):
        """Test transition from AWAITING_APPROVAL to PROCESSING_MODIFICATION."""
        conversation = ConversationState(
            id=str(uuid.uuid4()),
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            jira_ticket_key="PROJ-123",
            status=ConversationStatus.AWAITING_APPROVAL,
        )
        created = repository.create(conversation)

        created.status = ConversationStatus.PROCESSING_MODIFICATION
        updated = repository.update(created)

        assert updated.status == ConversationStatus.PROCESSING_MODIFICATION

    def test_awaiting_approval_to_writing_to_jira(self, repository):
        """Test transition from AWAITING_APPROVAL to WRITING_TO_JIRA."""
        conversation = ConversationState(
            id=str(uuid.uuid4()),
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            jira_ticket_key="PROJ-123",
            status=ConversationStatus.AWAITING_APPROVAL,
        )
        created = repository.create(conversation)

        created.status = ConversationStatus.WRITING_TO_JIRA
        updated = repository.update(created)

        assert updated.status == ConversationStatus.WRITING_TO_JIRA

    def test_writing_to_jira_to_completed(self, repository):
        """Test transition from WRITING_TO_JIRA to COMPLETED."""
        conversation = ConversationState(
            id=str(uuid.uuid4()),
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            jira_ticket_key="PROJ-123",
            status=ConversationStatus.WRITING_TO_JIRA,
        )
        created = repository.create(conversation)

        created.status = ConversationStatus.COMPLETED
        updated = repository.update(created)

        assert updated.status == ConversationStatus.COMPLETED

    def test_any_state_to_cancelled(self, repository):
        """Test transition from any state to CANCELLED."""
        conversation = ConversationState(
            id=str(uuid.uuid4()),
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            jira_ticket_key="PROJ-123",
            status=ConversationStatus.AWAITING_APPROVAL,
        )
        created = repository.create(conversation)

        created.status = ConversationStatus.CANCELLED
        updated = repository.update(created)

        assert updated.status == ConversationStatus.CANCELLED

    def test_any_state_to_error(self, repository):
        """Test transition from any state to ERROR."""
        conversation = ConversationState(
            id=str(uuid.uuid4()),
            slack_user_id="U12345678",
            slack_channel_id="D87654321",
            jira_ticket_key="PROJ-123",
            status=ConversationStatus.GENERATING_ACS,
        )
        created = repository.create(conversation)

        created.status = ConversationStatus.ERROR
        updated = repository.update(created)

        assert updated.status == ConversationStatus.ERROR


class TestConversationStatusEnum:
    """Test suite for ConversationStatus enum."""

    def test_all_statuses_defined(self):
        """Test that all expected statuses are defined."""
        expected_statuses = [
            "AWAITING_TICKET",
            "FETCHING_TICKET",
            "GENERATING_ACS",
            "COMPARING",
            "AWAITING_APPROVAL",
            "PROCESSING_MODIFICATION",
            "WRITING_TO_JIRA",
            "COMPLETED",
            "CANCELLED",
            "ERROR",
        ]

        actual_statuses = [status.value for status in ConversationStatus]

        assert sorted(actual_statuses) == sorted(expected_statuses)

    def test_status_is_string_enum(self):
        """Test that ConversationStatus values are strings."""
        for status in ConversationStatus:
            assert isinstance(status.value, str)


class TestMessageRecord:
    """Test suite for MessageRecord model."""

    def test_message_record_creation(self):
        """Test creating a MessageRecord."""
        message = MessageRecord(role="user", content="Hello")

        assert message.role == "user"
        assert message.content == "Hello"
        assert message.timestamp is not None

    def test_message_record_with_timestamp(self):
        """Test creating a MessageRecord with explicit timestamp."""
        message = MessageRecord(
            role="assistant",
            content="Hi there",
            timestamp="2024-01-15T10:30:00",
        )

        assert message.timestamp == "2024-01-15T10:30:00"

    def test_message_record_serialization(self):
        """Test that MessageRecord can be serialized to dict."""
        message = MessageRecord(role="user", content="Test")

        data = message.model_dump()

        assert data["role"] == "user"
        assert data["content"] == "Test"
        assert "timestamp" in data


def _create_conversation_with_age(
    repository: ConversationRepository,
    status: ConversationStatus,
    age_days: int,
) -> ConversationState:
    """Helper: create a conversation and manually set its updated_at to simulate age.

    Args:
        repository: The repository to use.
        status: The desired conversation status.
        age_days: How many days old the updated_at should be.

    Returns:
        The created ConversationState (with updated_at already backdated in DB).
    """
    conversation = ConversationState(
        id=str(uuid.uuid4()),
        slack_user_id="U12345678",
        slack_channel_id="D87654321",
        status=status,
    )
    created = repository.create(conversation)

    # Manually backdate updated_at in the database
    old_timestamp = (datetime.now(UTC) - timedelta(days=age_days)).isoformat()
    repository._conn.execute(
        "UPDATE conversations SET updated_at = ? WHERE id = ?",
        (old_timestamp, created.id),
    )
    repository._conn.commit()

    return created


class TestDeleteStale:
    """Test suite for ConversationRepository.delete_stale method."""

    def test_delete_stale_removes_old_completed(self, repository):
        """Test that old COMPLETED conversations are deleted."""
        _create_conversation_with_age(
            repository, ConversationStatus.COMPLETED, age_days=10
        )

        count = repository.delete_stale(older_than_days=7)

        assert count == 1

    def test_delete_stale_removes_old_cancelled(self, repository):
        """Test that old CANCELLED conversations are deleted."""
        _create_conversation_with_age(
            repository, ConversationStatus.CANCELLED, age_days=10
        )

        count = repository.delete_stale(older_than_days=7)

        assert count == 1

    def test_delete_stale_removes_old_error(self, repository):
        """Test that old ERROR conversations are deleted."""
        _create_conversation_with_age(
            repository, ConversationStatus.ERROR, age_days=10
        )

        count = repository.delete_stale(older_than_days=7)

        assert count == 1

    def test_delete_stale_preserves_young_terminal(self, repository):
        """Test that recent terminal conversations are NOT deleted."""
        conv = _create_conversation_with_age(
            repository, ConversationStatus.COMPLETED, age_days=3
        )

        count = repository.delete_stale(older_than_days=7)

        assert count == 0
        assert repository.get_by_id(conv.id) is not None

    def test_delete_stale_ignores_non_terminal_statuses(self, repository):
        """Test that non-terminal conversations are NOT deleted by delete_stale."""
        non_terminal = [
            ConversationStatus.AWAITING_TICKET,
            ConversationStatus.FETCHING_TICKET,
            ConversationStatus.GENERATING_ACS,
            ConversationStatus.COMPARING,
            ConversationStatus.AWAITING_APPROVAL,
            ConversationStatus.PROCESSING_MODIFICATION,
            ConversationStatus.WRITING_TO_JIRA,
        ]
        for status in non_terminal:
            _create_conversation_with_age(repository, status, age_days=30)

        count = repository.delete_stale(older_than_days=7)

        assert count == 0

    def test_delete_stale_returns_correct_count(self, repository):
        """Test that delete_stale returns the exact count of deleted rows."""
        _create_conversation_with_age(
            repository, ConversationStatus.COMPLETED, age_days=10
        )
        _create_conversation_with_age(
            repository, ConversationStatus.CANCELLED, age_days=15
        )
        _create_conversation_with_age(
            repository, ConversationStatus.ERROR, age_days=20
        )
        # This one is too young — should not be deleted
        _create_conversation_with_age(
            repository, ConversationStatus.COMPLETED, age_days=2
        )

        count = repository.delete_stale(older_than_days=7)

        assert count == 3

    def test_delete_stale_custom_threshold(self, repository):
        """Test delete_stale with a custom older_than_days threshold."""
        _create_conversation_with_age(
            repository, ConversationStatus.COMPLETED, age_days=4
        )

        # With default 7 days, it should NOT be deleted
        count_default = repository.delete_stale(older_than_days=7)
        assert count_default == 0

        # With 3-day threshold, it SHOULD be deleted
        count_custom = repository.delete_stale(older_than_days=3)
        assert count_custom == 1

    def test_delete_stale_conversation_actually_removed(self, repository):
        """Test that deleted conversations are no longer retrievable."""
        conv = _create_conversation_with_age(
            repository, ConversationStatus.COMPLETED, age_days=10
        )

        repository.delete_stale(older_than_days=7)

        assert repository.get_by_id(conv.id) is None


class TestDeleteAbandoned:
    """Test suite for ConversationRepository.delete_abandoned method."""

    def test_delete_abandoned_removes_old_awaiting_ticket(self, repository):
        """Test that old AWAITING_TICKET conversations are deleted."""
        _create_conversation_with_age(
            repository, ConversationStatus.AWAITING_TICKET, age_days=10
        )

        count = repository.delete_abandoned(older_than_days=7)

        assert count == 1

    def test_delete_abandoned_removes_old_fetching_ticket(self, repository):
        """Test that old FETCHING_TICKET conversations are deleted."""
        _create_conversation_with_age(
            repository, ConversationStatus.FETCHING_TICKET, age_days=10
        )

        count = repository.delete_abandoned(older_than_days=7)

        assert count == 1

    def test_delete_abandoned_removes_old_generating_acs(self, repository):
        """Test that old GENERATING_ACS conversations are deleted."""
        _create_conversation_with_age(
            repository, ConversationStatus.GENERATING_ACS, age_days=10
        )

        count = repository.delete_abandoned(older_than_days=7)

        assert count == 1

    def test_delete_abandoned_removes_old_comparing(self, repository):
        """Test that old COMPARING conversations are deleted."""
        _create_conversation_with_age(
            repository, ConversationStatus.COMPARING, age_days=10
        )

        count = repository.delete_abandoned(older_than_days=7)

        assert count == 1

    def test_delete_abandoned_removes_old_awaiting_approval(self, repository):
        """Test that old AWAITING_APPROVAL conversations are deleted."""
        _create_conversation_with_age(
            repository, ConversationStatus.AWAITING_APPROVAL, age_days=10
        )

        count = repository.delete_abandoned(older_than_days=7)

        assert count == 1

    def test_delete_abandoned_removes_old_processing_modification(self, repository):
        """Test that old PROCESSING_MODIFICATION conversations are deleted."""
        _create_conversation_with_age(
            repository, ConversationStatus.PROCESSING_MODIFICATION, age_days=10
        )

        count = repository.delete_abandoned(older_than_days=7)

        assert count == 1

    def test_delete_abandoned_removes_old_writing_to_jira(self, repository):
        """Test that old WRITING_TO_JIRA conversations are deleted."""
        _create_conversation_with_age(
            repository, ConversationStatus.WRITING_TO_JIRA, age_days=10
        )

        count = repository.delete_abandoned(older_than_days=7)

        assert count == 1

    def test_delete_abandoned_preserves_young_non_terminal(self, repository):
        """Test that recent non-terminal conversations are NOT deleted."""
        conv = _create_conversation_with_age(
            repository, ConversationStatus.AWAITING_APPROVAL, age_days=3
        )

        count = repository.delete_abandoned(older_than_days=7)

        assert count == 0
        assert repository.get_by_id(conv.id) is not None

    def test_delete_abandoned_ignores_terminal_statuses(self, repository):
        """Test that terminal conversations are NOT deleted by delete_abandoned."""
        terminal = [
            ConversationStatus.COMPLETED,
            ConversationStatus.CANCELLED,
            ConversationStatus.ERROR,
        ]
        for status in terminal:
            _create_conversation_with_age(repository, status, age_days=30)

        count = repository.delete_abandoned(older_than_days=7)

        assert count == 0

    def test_delete_abandoned_returns_correct_count(self, repository):
        """Test that delete_abandoned returns the exact count of deleted rows."""
        _create_conversation_with_age(
            repository, ConversationStatus.AWAITING_TICKET, age_days=10
        )
        _create_conversation_with_age(
            repository, ConversationStatus.GENERATING_ACS, age_days=15
        )
        # Young one — should not be deleted
        _create_conversation_with_age(
            repository, ConversationStatus.COMPARING, age_days=2
        )
        # Terminal one — should not be deleted by delete_abandoned
        _create_conversation_with_age(
            repository, ConversationStatus.COMPLETED, age_days=30
        )

        count = repository.delete_abandoned(older_than_days=7)

        assert count == 2

    def test_delete_abandoned_custom_threshold(self, repository):
        """Test delete_abandoned with a custom older_than_days threshold."""
        _create_conversation_with_age(
            repository, ConversationStatus.FETCHING_TICKET, age_days=4
        )

        # With default 7 days, it should NOT be deleted
        count_default = repository.delete_abandoned(older_than_days=7)
        assert count_default == 0

        # With 3-day threshold, it SHOULD be deleted
        count_custom = repository.delete_abandoned(older_than_days=3)
        assert count_custom == 1

    def test_delete_abandoned_conversation_actually_removed(self, repository):
        """Test that deleted abandoned conversations are no longer retrievable."""
        conv = _create_conversation_with_age(
            repository, ConversationStatus.AWAITING_APPROVAL, age_days=10
        )

        repository.delete_abandoned(older_than_days=7)

        assert repository.get_by_id(conv.id) is None


class TestDeleteStaleAndAbandonedTogether:
    """Test that delete_stale and delete_abandoned work correctly together."""

    def test_mixed_cleanup(self, repository):
        """Test running both cleanup methods on a mixed set of conversations."""
        # Old terminal (should be cleaned by delete_stale)
        old_completed = _create_conversation_with_age(
            repository, ConversationStatus.COMPLETED, age_days=10
        )
        old_error = _create_conversation_with_age(
            repository, ConversationStatus.ERROR, age_days=14
        )

        # Old non-terminal (should be cleaned by delete_abandoned)
        old_awaiting = _create_conversation_with_age(
            repository, ConversationStatus.AWAITING_TICKET, age_days=10
        )
        old_generating = _create_conversation_with_age(
            repository, ConversationStatus.GENERATING_ACS, age_days=12
        )

        # Young conversations (should survive both)
        young_completed = _create_conversation_with_age(
            repository, ConversationStatus.COMPLETED, age_days=2
        )
        young_awaiting = _create_conversation_with_age(
            repository, ConversationStatus.AWAITING_TICKET, age_days=1
        )

        stale_count = repository.delete_stale(older_than_days=7)
        abandoned_count = repository.delete_abandoned(older_than_days=7)

        assert stale_count == 2
        assert abandoned_count == 2

        # Old ones removed
        assert repository.get_by_id(old_completed.id) is None
        assert repository.get_by_id(old_error.id) is None
        assert repository.get_by_id(old_awaiting.id) is None
        assert repository.get_by_id(old_generating.id) is None

        # Young ones preserved
        assert repository.get_by_id(young_completed.id) is not None
        assert repository.get_by_id(young_awaiting.id) is not None
