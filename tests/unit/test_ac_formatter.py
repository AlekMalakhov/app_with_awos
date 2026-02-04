"""Unit tests for AC formatter module."""

from unittest.mock import patch

import pytest

from src.jira.ac_formatter import (
    append_acs_to_description,
    build_attribution_node,
    format_acs_to_adf,
    validate_acs,
)


class TestValidateAcs:
    """Test suite for validate_acs function."""

    def test_validate_acs_with_valid_list_returns_true(self):
        """Test that a valid AC list returns True."""
        acs = ["AC 1", "AC 2", "AC 3"]
        assert validate_acs(acs) is True

    def test_validate_acs_with_single_item_returns_true(self):
        """Test that a single valid AC returns True."""
        acs = ["Single AC"]
        assert validate_acs(acs) is True

    def test_validate_acs_with_empty_list_returns_false(self):
        """Test that an empty list returns False."""
        assert validate_acs([]) is False

    def test_validate_acs_with_none_items_returns_false(self):
        """Test that a list with only None items returns False."""
        assert validate_acs([None, None]) is False

    def test_validate_acs_with_empty_strings_returns_false(self):
        """Test that a list with only empty strings returns False."""
        assert validate_acs(["", "   ", ""]) is False

    def test_validate_acs_with_mixed_valid_and_invalid_returns_true(self):
        """Test that a list with some valid items returns True."""
        acs = ["Valid AC", "", None, "Another valid"]
        assert validate_acs(acs) is True

    def test_validate_acs_logs_warning_for_empty_list(self, caplog):
        """Test that empty list logs a warning."""
        validate_acs([], "PROJ-123")
        assert "Empty acceptance criteria list" in caplog.text
        assert "PROJ-123" in caplog.text

    def test_validate_acs_logs_warning_for_filtered_empty(self, caplog):
        """Test that warning is logged when all items are invalid."""
        validate_acs(["", "   "], "PROJ-456")
        assert "No valid acceptance criteria" in caplog.text


class TestBuildAttributionNode:
    """Test suite for build_attribution_node function."""

    def test_build_attribution_node_returns_paragraph(self):
        """Test that attribution node is a paragraph type."""
        node = build_attribution_node()
        assert node["type"] == "paragraph"

    def test_build_attribution_node_has_content(self):
        """Test that attribution node has content."""
        node = build_attribution_node()
        assert "content" in node
        assert len(node["content"]) > 0

    def test_build_attribution_node_has_italic_mark(self):
        """Test that attribution text is italicized."""
        node = build_attribution_node()
        text_node = node["content"][0]
        assert text_node["type"] == "text"
        assert any(mark["type"] == "em" for mark in text_node.get("marks", []))

    def test_build_attribution_node_contains_assistant_name(self):
        """Test that attribution mentions Jira AC Assistant."""
        node = build_attribution_node()
        text = node["content"][0]["text"]
        assert "Jira AC Assistant" in text

    def test_build_attribution_node_contains_timestamp(self):
        """Test that attribution contains a human-readable timestamp."""
        with patch("src.jira.ac_formatter.datetime") as mock_dt:
            from datetime import datetime, timezone

            mock_now = datetime(2024, 1, 15, 14, 30, 0, tzinfo=timezone.utc)
            mock_dt.now.return_value = mock_now
            mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)

            node = build_attribution_node()
            text = node["content"][0]["text"]
            # Should contain human-friendly date format
            assert "January" in text or "2024" in text


class TestFormatAcsToAdf:
    """Test suite for format_acs_to_adf function."""

    def test_format_acs_to_adf_single_ac(self):
        """Test formatting a single AC produces valid ADF."""
        result = format_acs_to_adf(["User can login"])

        assert result is not None
        assert result["type"] == "doc"
        assert result["version"] == 1
        assert len(result["content"]) == 3  # heading + taskList + attribution

    def test_format_acs_to_adf_multiple_acs(self):
        """Test formatting multiple ACs produces correct task list."""
        acs = ["AC 1", "AC 2", "AC 3"]
        result = format_acs_to_adf(acs)

        assert result is not None
        task_list = result["content"][1]
        assert task_list["type"] == "taskList"
        assert len(task_list["content"]) == 3

    def test_format_acs_to_adf_empty_list_returns_none(self):
        """Test that empty list returns None."""
        assert format_acs_to_adf([]) is None

    def test_format_acs_to_adf_only_invalid_items_returns_none(self):
        """Test that list with only invalid items returns None."""
        assert format_acs_to_adf(["", None, "   "]) is None

    def test_format_acs_to_adf_has_heading(self):
        """Test that ADF has Acceptance Criteria heading."""
        result = format_acs_to_adf(["Test AC"])

        heading = result["content"][0]
        assert heading["type"] == "heading"
        assert heading["attrs"]["level"] == 2
        assert heading["content"][0]["text"] == "Acceptance Criteria"

    def test_format_acs_to_adf_task_items_have_todo_state(self):
        """Test that task items have TODO state (unchecked)."""
        result = format_acs_to_adf(["Test AC"])

        task_list = result["content"][1]
        task_item = task_list["content"][0]
        assert task_item["type"] == "taskItem"
        assert task_item["attrs"]["state"] == "TODO"

    def test_format_acs_to_adf_task_items_have_local_ids(self):
        """Test that task items have unique localId attributes."""
        result = format_acs_to_adf(["AC 1", "AC 2"])

        task_list = result["content"][1]
        local_ids = [item["attrs"]["localId"] for item in task_list["content"]]
        assert len(set(local_ids)) == 2  # All unique

    def test_format_acs_to_adf_preserves_ac_text(self):
        """Test that AC text is preserved in task items."""
        result = format_acs_to_adf(["User can upload file"])

        task_list = result["content"][1]
        task_item = task_list["content"][0]
        text_content = task_item["content"][0]["text"]
        assert text_content == "User can upload file"

    def test_format_acs_to_adf_filters_invalid_items(self):
        """Test that invalid items are filtered out."""
        acs = ["Valid AC", "", None, "   ", "Another valid"]
        result = format_acs_to_adf(acs)

        task_list = result["content"][1]
        assert len(task_list["content"]) == 2

    def test_format_acs_to_adf_strips_whitespace(self):
        """Test that AC text is stripped of leading/trailing whitespace."""
        result = format_acs_to_adf(["  Padded AC  "])

        task_list = result["content"][1]
        task_item = task_list["content"][0]
        text_content = task_item["content"][0]["text"]
        assert text_content == "Padded AC"


class TestAppendAcsToDescription:
    """Test suite for append_acs_to_description function."""

    def test_append_to_none_description(self):
        """Test appending ACs to None description."""
        result = append_acs_to_description(None, ["AC 1"])

        assert result is not None
        assert result["type"] == "doc"
        assert len(result["content"]) == 3

    def test_append_to_empty_dict_description(self):
        """Test appending ACs to empty dict description."""
        result = append_acs_to_description({}, ["AC 1"])

        assert result is not None
        assert result["type"] == "doc"

    def test_append_to_existing_description(self):
        """Test appending ACs to existing description content."""
        existing = {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "Original description"}],
                }
            ],
        }

        result = append_acs_to_description(existing, ["New AC"])

        assert result is not None
        # Should have: original paragraph + heading + taskList + attribution
        assert len(result["content"]) == 4
        assert result["content"][0]["type"] == "paragraph"
        assert result["content"][1]["type"] == "heading"

    def test_append_preserves_existing_content(self):
        """Test that existing content is preserved."""
        existing = {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "Keep this text"}],
                }
            ],
        }

        result = append_acs_to_description(existing, ["New AC"])

        first_para = result["content"][0]
        assert first_para["content"][0]["text"] == "Keep this text"

    def test_append_with_empty_acs_returns_existing(self):
        """Test that empty ACs returns existing description unchanged."""
        existing = {
            "type": "doc",
            "version": 1,
            "content": [{"type": "paragraph", "content": []}],
        }

        result = append_acs_to_description(existing, [])

        assert result == existing

    def test_append_with_invalid_acs_returns_existing(self):
        """Test that invalid ACs returns existing description."""
        existing = {
            "type": "doc",
            "version": 1,
            "content": [{"type": "paragraph", "content": []}],
        }

        result = append_acs_to_description(existing, ["", None])

        assert result == existing

    def test_append_multiple_times(self):
        """Test appending ACs multiple times (simulating regeneration)."""
        # First append
        first_result = append_acs_to_description(None, ["First AC"])

        # Second append
        second_result = append_acs_to_description(first_result, ["Second AC"])

        # Should have: 2x (heading + taskList + attribution) = 6 nodes
        assert len(second_result["content"]) == 6

    def test_append_to_description_with_existing_acs(self):
        """Test appending new ACs when description already has AC section."""
        existing = {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "heading",
                    "attrs": {"level": 2},
                    "content": [{"type": "text", "text": "Acceptance Criteria"}],
                },
                {
                    "type": "taskList",
                    "attrs": {"localId": "existing-id"},
                    "content": [
                        {
                            "type": "taskItem",
                            "attrs": {"localId": "item-1", "state": "TODO"},
                            "content": [{"type": "text", "text": "Existing AC"}],
                        }
                    ],
                },
            ],
        }

        result = append_acs_to_description(existing, ["New AC"])

        # Should have: existing heading + existing taskList + new heading + new taskList + attribution
        assert len(result["content"]) == 5


class TestAdfStructureValidity:
    """Test suite for verifying ADF structure validity."""

    def test_adf_document_has_required_fields(self):
        """Test that ADF document has type, version, and content."""
        result = format_acs_to_adf(["Test"])

        assert "type" in result
        assert "version" in result
        assert "content" in result
        assert result["type"] == "doc"
        assert result["version"] == 1
        assert isinstance(result["content"], list)

    def test_task_list_has_local_id(self):
        """Test that taskList has localId attribute."""
        result = format_acs_to_adf(["Test"])

        task_list = result["content"][1]
        assert "attrs" in task_list
        assert "localId" in task_list["attrs"]

    def test_task_item_has_required_attrs(self):
        """Test that taskItem has localId and state attributes."""
        result = format_acs_to_adf(["Test"])

        task_list = result["content"][1]
        task_item = task_list["content"][0]
        assert task_item["attrs"]["localId"] is not None
        assert task_item["attrs"]["state"] == "TODO"
