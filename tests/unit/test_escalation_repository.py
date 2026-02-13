"""Unit tests for EscalationRepository."""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest

from src.database.config import DatabaseSettings
from src.database.models import EscalationRecord
from src.database.repository import EscalationRepository


@pytest.fixture
def temp_db_path():
    """Create a temporary database file path for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_escalations.db"
        yield str(db_path)


@pytest.fixture
def db_settings(temp_db_path):
    """Create DatabaseSettings with temporary database path."""
    return DatabaseSettings(database_path=temp_db_path)


@pytest.fixture
def repository(db_settings):
    """Create an EscalationRepository with a temporary database."""
    repo = EscalationRepository(settings=db_settings)
    yield repo
    repo.close()


def _make_escalation(
    *,
    ticket_key: str = "PROJ-123",
    confidence_score: float = 0.55,
    confidence_gaps: list[str] | None = None,
    slack_user_id: str | None = "U12345",
    status: str = "SENT",
    error_message: str | None = None,
) -> EscalationRecord:
    """Helper to build an EscalationRecord with sensible defaults."""
    return EscalationRecord(
        id=str(uuid.uuid4()),
        jira_ticket_key=ticket_key,
        confidence_score=confidence_score,
        confidence_gaps=confidence_gaps or ["What is the expected response time?"],
        slack_user_id=slack_user_id,
        status=status,
        error_message=error_message,
    )


class TestEscalationRepositoryCreateAndRetrieve:
    """Test suite for creating and retrieving escalation records."""

    def test_create_and_retrieve_by_ticket_key(self, repository):
        """Test that an EscalationRecord can be created and retrieved with all fields intact."""
        gaps = [
            "What is the expected response time?",
            "Should we support pagination?",
        ]
        record = _make_escalation(
            ticket_key="PROJ-100",
            confidence_score=0.42,
            confidence_gaps=gaps,
            slack_user_id="U99999",
            status="SENT",
        )

        repository.create(record)
        results = repository.get_by_ticket_key("PROJ-100")

        assert len(results) == 1
        retrieved = results[0]
        assert retrieved.id == record.id
        assert retrieved.jira_ticket_key == "PROJ-100"
        assert retrieved.confidence_score == pytest.approx(0.42)
        assert retrieved.confidence_gaps == gaps
        assert retrieved.slack_user_id == "U99999"
        assert retrieved.status == "SENT"
        assert retrieved.error_message is None
        assert retrieved.created_at == record.created_at


class TestEscalationRepositoryMultipleRecords:
    """Test suite for retrieving multiple escalation records for the same ticket."""

    def test_multiple_records_for_same_ticket(self, repository):
        """Test that get_by_ticket_key returns all records for a given ticket key."""
        record_a = _make_escalation(
            ticket_key="PROJ-200",
            confidence_score=0.5,
            confidence_gaps=["Gap A"],
            status="SENT",
        )
        record_b = _make_escalation(
            ticket_key="PROJ-200",
            confidence_score=0.3,
            confidence_gaps=["Gap B", "Gap C"],
            status="FAILED",
            error_message="User not found",
        )

        repository.create(record_a)
        repository.create(record_b)
        results = repository.get_by_ticket_key("PROJ-200")

        assert len(results) == 2
        ids = {r.id for r in results}
        assert record_a.id in ids
        assert record_b.id in ids


class TestEscalationRepositoryNoRecords:
    """Test suite for querying escalation records that do not exist."""

    def test_no_records_found(self, repository):
        """Test that get_by_ticket_key returns an empty list for a non-existent key."""
        results = repository.get_by_ticket_key("NONEXISTENT-999")

        assert results == []


class TestEscalationRepositoryFailedStatus:
    """Test suite for escalation records with FAILED status and error messages."""

    def test_failed_status_with_error_message(self, repository):
        """Test that a FAILED record with an error_message round-trips correctly."""
        record = _make_escalation(
            ticket_key="PROJ-300",
            confidence_score=0.6,
            confidence_gaps=["Unclear requirements"],
            slack_user_id=None,
            status="FAILED",
            error_message="User not found for email: nobody@example.com",
        )

        repository.create(record)
        results = repository.get_by_ticket_key("PROJ-300")

        assert len(results) == 1
        retrieved = results[0]
        assert retrieved.status == "FAILED"
        assert retrieved.error_message == "User not found for email: nobody@example.com"
        assert retrieved.slack_user_id is None
        assert retrieved.confidence_gaps == ["Unclear requirements"]
