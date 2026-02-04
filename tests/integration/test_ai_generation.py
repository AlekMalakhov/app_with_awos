"""Integration tests for AI acceptance criteria generator with real Anthropic API.

These tests require real Anthropic credentials to run:
- ANTHROPIC_API_KEY: Anthropic API key for Claude access

Tests are skipped automatically if ANTHROPIC_API_KEY is not set.

Note: These tests make real API calls and will consume API credits.
"""

import os

import pytest

from src.ai.config import AISettings
from src.ai.generator import ACGenerator

# Skip all tests in this module if Anthropic credentials are not available
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("ANTHROPIC_API_KEY"),
        reason="Anthropic credentials not available",
    ),
]


# Sample test data for realistic ticket testing
SAMPLE_SUMMARY = "[TEST] Allow Barley to modify existing Jira tickets"
SAMPLE_DESCRIPTION = """
Purpose:
This test story validates that Barley can successfully update existing Jira tickets.

Scope:
- Update ticket fields (status, assignee, description, priority)
- Track changes in Jira history
- Handle permissions appropriately

Expected Functionality:
- API endpoints for ticket modification
- Proper error handling for invalid requests
- Permission validation before modifications
"""


@pytest.mark.integration
class TestAIGenerationIntegration:
    """Integration tests for ACGenerator using real Anthropic API."""

    @pytest.mark.asyncio
    async def test_generate_acs_real_api(self, requires_anthropic_credentials):
        """Test generating acceptance criteria with real Anthropic API.

        This test validates that:
        - Real AISettings can be loaded from environment
        - Real ACGenerator can be created and used
        - API returns a valid response with acceptance criteria
        - Response contains 3-7 ACs as per specification
        - Each AC is a non-empty string
        """
        # Create settings from environment
        settings = AISettings()
        assert settings.is_enabled, "AISettings should be enabled with valid API key"

        # Create generator
        generator = ACGenerator(settings)
        assert generator.is_enabled, "ACGenerator should be enabled"

        # Generate ACs with realistic ticket data
        result = await generator.generate(
            summary=SAMPLE_SUMMARY,
            description=SAMPLE_DESCRIPTION,
        )

        # Verify response is a non-empty list
        assert isinstance(result, list), "Result should be a list"
        assert len(result) > 0, "Result should not be empty"

        # Verify each item is a string
        for ac in result:
            assert isinstance(ac, str), f"Each AC should be a string, got {type(ac)}"
            assert len(ac) > 0, "Each AC should be non-empty"

        # Verify AC count is within expected range (3-7 as per spec)
        assert 3 <= len(result) <= 7, (
            f"Expected 3-7 acceptance criteria, got {len(result)}"
        )

    @pytest.mark.asyncio
    async def test_generate_acs_insufficient_description(
        self, requires_anthropic_credentials
    ):
        """Test that vague descriptions return empty list.

        This test validates that the AI correctly identifies when there is
        insufficient information to generate meaningful acceptance criteria.
        """
        # Create settings from environment
        settings = AISettings()
        generator = ACGenerator(settings)

        # Call generate with very vague description
        result = await generator.generate(
            summary="Fix bug",
            description="Fix bug",
        )

        # Verify empty list is returned for insufficient information
        assert isinstance(result, list), "Result should be a list"
        assert len(result) == 0, (
            f"Expected empty list for vague description, got {len(result)} ACs"
        )
