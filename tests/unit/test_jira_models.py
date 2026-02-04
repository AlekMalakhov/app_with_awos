"""Unit tests for Jira data models."""

import pytest
from pydantic import ValidationError

from src.jira.models import TicketData


class TestTicketDataInstantiation:
    """Test suite for TicketData model instantiation."""

    def test_successful_instantiation_with_all_valid_fields(self):
        """Test that TicketData can be created with all valid fields."""
        ticket = TicketData(
            key="PROJ-123",
            summary="Implement new feature",
            description="This is a detailed description of the feature.",
            issue_type="Story",
        )

        assert ticket.key == "PROJ-123"
        assert ticket.summary == "Implement new feature"
        assert ticket.description == "This is a detailed description of the feature."
        assert ticket.issue_type == "Story"

    def test_instantiation_with_empty_description(self):
        """Test that TicketData can be created with empty string description."""
        ticket = TicketData(
            key="PROJ-456",
            summary="Fix bug",
            description="",
            issue_type="Task",
        )

        assert ticket.key == "PROJ-456"
        assert ticket.summary == "Fix bug"
        assert ticket.description == ""
        assert ticket.issue_type == "Task"

    def test_instantiation_with_different_issue_types(self):
        """Test that TicketData accepts different issue type values."""
        story = TicketData(
            key="PROJ-001",
            summary="Story ticket",
            description="A story",
            issue_type="Story",
        )
        task = TicketData(
            key="PROJ-002",
            summary="Task ticket",
            description="A task",
            issue_type="Task",
        )

        assert story.issue_type == "Story"
        assert task.issue_type == "Task"


class TestTicketDataFieldAccess:
    """Test suite for TicketData field access."""

    def test_key_field_is_accessible(self):
        """Test that key field is accessible and returns correct value."""
        ticket = TicketData(
            key="TEST-789",
            summary="Test summary",
            description="Test description",
            issue_type="Story",
        )

        assert ticket.key == "TEST-789"

    def test_summary_field_is_accessible(self):
        """Test that summary field is accessible and returns correct value."""
        ticket = TicketData(
            key="TEST-789",
            summary="Test summary",
            description="Test description",
            issue_type="Story",
        )

        assert ticket.summary == "Test summary"

    def test_description_field_is_accessible(self):
        """Test that description field is accessible and returns correct value."""
        ticket = TicketData(
            key="TEST-789",
            summary="Test summary",
            description="Test description",
            issue_type="Story",
        )

        assert ticket.description == "Test description"

    def test_issue_type_field_is_accessible(self):
        """Test that issue_type field is accessible and returns correct value."""
        ticket = TicketData(
            key="TEST-789",
            summary="Test summary",
            description="Test description",
            issue_type="Story",
        )

        assert ticket.issue_type == "Story"


class TestTicketDataValidation:
    """Test suite for TicketData validation errors."""

    def test_missing_key_raises_validation_error(self):
        """Test that missing key field raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            TicketData(
                summary="Test summary",
                description="Test description",
                issue_type="Story",
            )

        errors = exc_info.value.errors()
        assert any(error["loc"] == ("key",) for error in errors)

    def test_missing_summary_raises_validation_error(self):
        """Test that missing summary field raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            TicketData(
                key="PROJ-123",
                description="Test description",
                issue_type="Story",
            )

        errors = exc_info.value.errors()
        assert any(error["loc"] == ("summary",) for error in errors)

    def test_missing_description_raises_validation_error(self):
        """Test that missing description field raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            TicketData(
                key="PROJ-123",
                summary="Test summary",
                issue_type="Story",
            )

        errors = exc_info.value.errors()
        assert any(error["loc"] == ("description",) for error in errors)

    def test_missing_issue_type_raises_validation_error(self):
        """Test that missing issue_type field raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            TicketData(
                key="PROJ-123",
                summary="Test summary",
                description="Test description",
            )

        errors = exc_info.value.errors()
        assert any(error["loc"] == ("issue_type",) for error in errors)

    def test_missing_all_fields_raises_validation_error(self):
        """Test that missing all fields raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            TicketData()

        errors = exc_info.value.errors()
        assert len(errors) == 4


class TestTicketDataSerialization:
    """Test suite for TicketData serialization."""

    def test_model_dump_returns_dictionary(self):
        """Test that model_dump returns a dictionary with all fields."""
        ticket = TicketData(
            key="PROJ-123",
            summary="Test summary",
            description="Test description",
            issue_type="Story",
        )

        result = ticket.model_dump()

        assert isinstance(result, dict)
        assert result["key"] == "PROJ-123"
        assert result["summary"] == "Test summary"
        assert result["description"] == "Test description"
        assert result["issue_type"] == "Story"

    def test_model_dump_with_empty_description(self):
        """Test that model_dump correctly serializes empty description."""
        ticket = TicketData(
            key="PROJ-456",
            summary="Another summary",
            description="",
            issue_type="Task",
        )

        result = ticket.model_dump()

        assert result["description"] == ""

    def test_model_dump_contains_all_expected_keys(self):
        """Test that model_dump contains exactly the expected keys."""
        ticket = TicketData(
            key="PROJ-789",
            summary="Summary",
            description="Description",
            issue_type="Story",
        )

        result = ticket.model_dump()

        expected_keys = {"key", "summary", "description", "description_adf", "issue_type"}
        assert set(result.keys()) == expected_keys


class TestTicketDataDescriptionAdf:
    """Test suite for TicketData description_adf field."""

    def test_description_adf_defaults_to_none(self):
        """Test that description_adf defaults to None when not provided."""
        ticket = TicketData(
            key="PROJ-123",
            summary="Test summary",
            description="Test description",
            issue_type="Story",
        )

        assert ticket.description_adf is None

    def test_description_adf_can_be_set(self):
        """Test that description_adf can be set to a dictionary."""
        adf = {
            "type": "doc",
            "version": 1,
            "content": [{"type": "paragraph", "content": []}],
        }
        ticket = TicketData(
            key="PROJ-123",
            summary="Test summary",
            description="Test description",
            description_adf=adf,
            issue_type="Story",
        )

        assert ticket.description_adf == adf

    def test_description_adf_included_in_model_dump(self):
        """Test that description_adf is included in model_dump output."""
        adf = {"type": "doc", "version": 1, "content": []}
        ticket = TicketData(
            key="PROJ-123",
            summary="Test summary",
            description="Test description",
            description_adf=adf,
            issue_type="Story",
        )

        result = ticket.model_dump()

        assert "description_adf" in result
        assert result["description_adf"] == adf
