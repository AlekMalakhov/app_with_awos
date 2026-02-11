"""Unit tests for AI acceptance criteria generator."""

from unittest.mock import MagicMock, patch

import pytest

from src.ai.config import AISettings
from src.ai.exceptions import AIInvalidResponseError
from src.ai.generator import ACGenerator


@pytest.fixture
def ai_settings_enabled() -> AISettings:
    """Create AISettings with API key configured (enabled)."""
    return AISettings(
        anthropic_api_key="sk-ant-test-key-12345",
        ai_model="claude-sonnet-4-20250514",
        ai_max_tokens=1024,
        ai_temperature=0.3,
    )


@pytest.fixture
def ai_settings_disabled() -> AISettings:
    """Create AISettings without API key (disabled)."""
    return AISettings(
        anthropic_api_key="",
        ai_model="claude-sonnet-4-20250514",
        ai_max_tokens=1024,
        ai_temperature=0.3,
    )


def create_mock_tool_use_response(
    sufficient_information: bool,
    acceptance_criteria: list[str],
    skip_reason: str | None = None,
) -> MagicMock:
    """Create a mock Anthropic API response with tool_use block.

    Args:
        sufficient_information: Whether the ticket has sufficient info
        acceptance_criteria: List of AC strings
        skip_reason: Optional reason for skipping

    Returns:
        Mock response object matching Anthropic API structure
    """
    tool_input = {
        "sufficient_information": sufficient_information,
        "acceptance_criteria": acceptance_criteria,
    }
    if skip_reason is not None:
        tool_input["skip_reason"] = skip_reason

    tool_use_block = MagicMock()
    tool_use_block.type = "tool_use"
    tool_use_block.name = "submit_acceptance_criteria"
    tool_use_block.input = tool_input

    response = MagicMock()
    response.content = [tool_use_block]

    return response


def create_mock_text_response() -> MagicMock:
    """Create a mock Anthropic API response with only text block (no tool_use).

    Returns:
        Mock response object with text block only
    """
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = "I cannot generate ACs."

    response = MagicMock()
    response.content = [text_block]

    return response


class TestACGeneratorIsEnabled:
    """Test suite for ACGenerator.is_enabled property."""

    def test_is_enabled_returns_true_when_api_key_configured(
        self, ai_settings_enabled: AISettings
    ):
        """Test that is_enabled returns True when API key is set."""
        with patch("src.ai.generator.Anthropic"):
            generator = ACGenerator(ai_settings_enabled)

            assert generator.is_enabled is True

    def test_is_enabled_returns_false_when_api_key_not_configured(
        self, ai_settings_disabled: AISettings
    ):
        """Test that is_enabled returns False when API key is empty."""
        generator = ACGenerator(ai_settings_disabled)

        assert generator.is_enabled is False


class TestACGeneratorGenerate:
    """Test suite for ACGenerator.generate() method."""

    @pytest.mark.asyncio
    async def test_generate_returns_acs_when_sufficient_information(
        self, ai_settings_enabled: AISettings
    ):
        """Test generate() returns ACs when API returns valid response."""
        expected_acs = [
            (
                "Given a user on the login page, when they enter valid "
                "credentials, then they are redirected to dashboard"
            ),
            "The login form validates email format before submission",
            "Password must be at least 8 characters",
        ]

        mock_response = create_mock_tool_use_response(
            sufficient_information=True,
            acceptance_criteria=expected_acs,
        )

        with patch("src.ai.generator.Anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_response
            mock_anthropic.return_value = mock_client

            generator = ACGenerator(ai_settings_enabled)
            result = await generator.generate(
                summary="Implement user login",
                description="Users should be able to log in with email and password.",
            )

            assert result == expected_acs
            assert len(result) == 3

    @pytest.mark.asyncio
    async def test_generate_returns_empty_list_when_insufficient_information(
        self, ai_settings_enabled: AISettings
    ):
        """Test generate() returns empty list when AI determines insufficient info."""
        mock_response = create_mock_tool_use_response(
            sufficient_information=False,
            acceptance_criteria=[],
            skip_reason="The ticket description is too vague to generate specific ACs.",
        )

        with patch("src.ai.generator.Anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_response
            mock_anthropic.return_value = mock_client

            generator = ACGenerator(ai_settings_enabled)
            result = await generator.generate(
                summary="Fix the thing",
                description="It's broken.",
            )

            assert result == []

    @pytest.mark.asyncio
    async def test_generate_returns_empty_list_when_acceptance_criteria_empty(
        self, ai_settings_enabled: AISettings
    ):
        """Test that generate() returns empty list when AI returns empty AC list."""
        mock_response = create_mock_tool_use_response(
            sufficient_information=True,
            acceptance_criteria=[],
        )

        with patch("src.ai.generator.Anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_response
            mock_anthropic.return_value = mock_client

            generator = ACGenerator(ai_settings_enabled)
            result = await generator.generate(
                summary="Some feature",
                description="Some description",
            )

            assert result == []

    @pytest.mark.asyncio
    async def test_generate_returns_empty_list_when_disabled(
        self, ai_settings_disabled: AISettings
    ):
        """Test that generate() returns empty list when ACGenerator is disabled."""
        generator = ACGenerator(ai_settings_disabled)

        result = await generator.generate(
            summary="Any summary",
            description="Any description",
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_generate_returns_empty_list_on_api_exception(
        self, ai_settings_enabled: AISettings
    ):
        """Test that generate() returns empty list when API call raises exception."""
        with patch("src.ai.generator.Anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create.side_effect = Exception("API connection failed")
            mock_anthropic.return_value = mock_client

            generator = ACGenerator(ai_settings_enabled)
            result = await generator.generate(
                summary="Some feature",
                description="Some description",
            )

            assert result == []

    @pytest.mark.asyncio
    async def test_generate_handles_empty_description(
        self, ai_settings_enabled: AISettings
    ):
        """Test that generate() handles empty description gracefully."""
        expected_acs = [
            "Feature X is implemented",
            "Feature X follows design specs",
        ]

        mock_response = create_mock_tool_use_response(
            sufficient_information=True,
            acceptance_criteria=expected_acs,
        )

        with patch("src.ai.generator.Anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_response
            mock_anthropic.return_value = mock_client

            generator = ACGenerator(ai_settings_enabled)
            result = await generator.generate(
                summary="Implement feature X",
                description="",
            )

            # Verify the API was called with the placeholder text
            call_args = mock_client.messages.create.call_args
            messages = call_args.kwargs["messages"]
            assert "(No description provided)" in messages[0]["content"]

            assert result == expected_acs

    @pytest.mark.asyncio
    async def test_generate_calls_api_with_correct_parameters(
        self, ai_settings_enabled: AISettings
    ):
        """Test that generate() calls Anthropic API with correct parameters."""
        mock_response = create_mock_tool_use_response(
            sufficient_information=True,
            acceptance_criteria=["AC 1", "AC 2"],
        )

        with patch("src.ai.generator.Anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_response
            mock_anthropic.return_value = mock_client

            generator = ACGenerator(ai_settings_enabled)
            await generator.generate(
                summary="Test summary",
                description="Test description",
            )

            # Verify Anthropic client was initialized with API key
            mock_anthropic.assert_called_once_with(
                api_key="sk-ant-test-key-12345"
            )

            # Verify API call parameters
            call_args = mock_client.messages.create.call_args
            assert call_args.kwargs["model"] == "claude-sonnet-4-20250514"
            assert call_args.kwargs["max_tokens"] == 1024
            assert "system" in call_args.kwargs
            assert "tools" in call_args.kwargs
            assert call_args.kwargs["tool_choice"] == {
                "type": "tool",
                "name": "submit_acceptance_criteria",
            }


class TestACGeneratorParseResponse:
    """Test suite for ACGenerator._parse_response() method."""

    def test_parse_response_raises_error_when_no_tool_use_block(
        self, ai_settings_enabled: AISettings
    ):
        """Test _parse_response() raises AIInvalidResponseError when no tool_use."""
        mock_response = create_mock_text_response()

        with patch("src.ai.generator.Anthropic"):
            generator = ACGenerator(ai_settings_enabled)

            with pytest.raises(AIInvalidResponseError) as exc_info:
                generator._parse_response(mock_response)

            assert "tool_use block" in str(exc_info.value)

    def test_parse_response_raises_error_when_empty_content(
        self, ai_settings_enabled: AISettings
    ):
        """Test _parse_response() raises AIInvalidResponseError when content empty."""
        response = MagicMock()
        response.content = []

        with patch("src.ai.generator.Anthropic"):
            generator = ACGenerator(ai_settings_enabled)

            with pytest.raises(AIInvalidResponseError) as exc_info:
                generator._parse_response(response)

            assert "tool_use block" in str(exc_info.value)

    def test_parse_response_raises_error_when_wrong_tool_name(
        self, ai_settings_enabled: AISettings
    ):
        """Test that _parse_response() raises error when tool_use has wrong name."""
        tool_use_block = MagicMock()
        tool_use_block.type = "tool_use"
        tool_use_block.name = "wrong_tool_name"
        tool_use_block.input = {"some": "data"}

        response = MagicMock()
        response.content = [tool_use_block]

        with patch("src.ai.generator.Anthropic"):
            generator = ACGenerator(ai_settings_enabled)

            with pytest.raises(AIInvalidResponseError):
                generator._parse_response(response)

    def test_parse_response_extracts_acs_from_valid_tool_use(
        self, ai_settings_enabled: AISettings
    ):
        """Test that _parse_response() correctly extracts ACs from valid response."""
        expected_acs = ["AC 1", "AC 2", "AC 3"]
        mock_response = create_mock_tool_use_response(
            sufficient_information=True,
            acceptance_criteria=expected_acs,
        )

        with patch("src.ai.generator.Anthropic"):
            generator = ACGenerator(ai_settings_enabled)

            result = generator._parse_response(mock_response)

            assert result == expected_acs

    def test_parse_response_returns_empty_list_when_insufficient_info(
        self, ai_settings_enabled: AISettings
    ):
        """Test _parse_response() returns empty when insufficient_information false."""
        mock_response = create_mock_tool_use_response(
            sufficient_information=False,
            acceptance_criteria=[],
            skip_reason="Not enough detail",
        )

        with patch("src.ai.generator.Anthropic"):
            generator = ACGenerator(ai_settings_enabled)

            result = generator._parse_response(mock_response)

            assert result == []

    def test_parse_response_handles_missing_sufficient_information_field(
        self, ai_settings_enabled: AISettings
    ):
        """Test _parse_response() defaults to False when sufficient_info missing."""
        tool_use_block = MagicMock()
        tool_use_block.type = "tool_use"
        tool_use_block.name = "submit_acceptance_criteria"
        tool_use_block.input = {
            "acceptance_criteria": ["AC 1"],
            # sufficient_information is missing
        }

        response = MagicMock()
        response.content = [tool_use_block]

        with patch("src.ai.generator.Anthropic"):
            generator = ACGenerator(ai_settings_enabled)

            result = generator._parse_response(response)

            # Should return empty list because sufficient_information defaults to False
            assert result == []


class TestACGeneratorIntegration:
    """Integration-style tests for ACGenerator (still mocked, but testing full flow)."""

    @pytest.mark.asyncio
    async def test_full_flow_with_valid_ticket(self, ai_settings_enabled: AISettings):
        """Test complete flow from generate() to parsed ACs."""
        expected_acs = [
            (
                "Given a user clicks 'Add to Cart', then the item is added "
                "to their shopping cart"
            ),
            "The cart icon displays the updated item count",
            "Users can add the same item multiple times to increase quantity",
            "Out of stock items show a disabled 'Add to Cart' button",
        ]

        mock_response = create_mock_tool_use_response(
            sufficient_information=True,
            acceptance_criteria=expected_acs,
        )

        with patch("src.ai.generator.Anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_response
            mock_anthropic.return_value = mock_client

            generator = ACGenerator(ai_settings_enabled)
            result = await generator.generate(
                summary="Implement Add to Cart functionality",
                description=(
                    "As a shopper, I want to add items to my cart "
                    "so that I can purchase them later.\n\n"
                    "Requirements:\n"
                    "- Button on product page\n"
                    "- Update cart count\n"
                    "- Support multiple quantities\n"
                    "- Handle out of stock items"
                ),
            )

            assert result == expected_acs
            assert len(result) == 4

    @pytest.mark.asyncio
    async def test_full_flow_with_vague_ticket(self, ai_settings_enabled: AISettings):
        """Test complete flow when ticket is too vague for ACs."""
        mock_response = create_mock_tool_use_response(
            sufficient_information=False,
            acceptance_criteria=[],
            skip_reason=(
                "The description 'make it work' is too vague to generate "
                "specific acceptance criteria."
            ),
        )

        with patch("src.ai.generator.Anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_response
            mock_anthropic.return_value = mock_client

            generator = ACGenerator(ai_settings_enabled)
            result = await generator.generate(
                summary="Fix bug",
                description="Make it work",
            )

            assert result == []


def create_mock_topics_tool_use_response(topics: str) -> MagicMock:
    """Create a mock Anthropic API response with submit_extracted_topics tool_use block.

    Args:
        topics: The extracted topics string

    Returns:
        Mock response object matching Anthropic API structure
    """
    tool_use_block = MagicMock()
    tool_use_block.type = "tool_use"
    tool_use_block.name = "submit_extracted_topics"
    tool_use_block.input = {"topics": topics}

    response = MagicMock()
    response.content = [tool_use_block]

    return response


class TestACGeneratorExtractTopics:
    """Test suite for ACGenerator.extract_topics() method."""

    @pytest.mark.asyncio
    async def test_extract_topics_returns_topics_on_successful_extraction(
        self, ai_settings_enabled: AISettings
    ):
        """Test extract_topics() returns extracted topics from valid tool_use response."""
        expected_topics = (
            "This ticket covers user authentication in the payments domain, "
            "involving the Stripe API integration and OAuth2 token refresh flow."
        )

        mock_response = create_mock_topics_tool_use_response(topics=expected_topics)

        with patch("src.ai.generator.Anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_response
            mock_anthropic.return_value = mock_client

            generator = ACGenerator(ai_settings_enabled)
            result = await generator.extract_topics(
                summary="Fix Stripe OAuth token refresh",
                description="The payment service fails when the OAuth2 token expires.",
            )

            assert result == expected_topics
            mock_client.messages.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_extract_topics_returns_raw_description_on_api_exception(
        self, ai_settings_enabled: AISettings
    ):
        """Test extract_topics() falls back to raw description when API raises."""
        raw_description = "The payment service fails when the OAuth2 token expires."

        with patch("src.ai.generator.Anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create.side_effect = Exception("API connection failed")
            mock_anthropic.return_value = mock_client

            generator = ACGenerator(ai_settings_enabled)
            result = await generator.extract_topics(
                summary="Fix Stripe OAuth token refresh",
                description=raw_description,
            )

            assert result == raw_description

    @pytest.mark.asyncio
    async def test_extract_topics_returns_empty_string_for_empty_description(
        self, ai_settings_enabled: AISettings
    ):
        """Test extract_topics() returns empty string when description is empty."""
        with patch("src.ai.generator.Anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_anthropic.return_value = mock_client

            generator = ACGenerator(ai_settings_enabled)
            result = await generator.extract_topics(
                summary="Some summary",
                description="",
            )

            assert result == ""
            mock_client.messages.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_extract_topics_returns_raw_description_on_invalid_response(
        self, ai_settings_enabled: AISettings
    ):
        """Test extract_topics() falls back to raw description when response has no tool_use block."""
        raw_description = "Users need single sign-on via SAML for enterprise clients."
        mock_response = create_mock_text_response()

        with patch("src.ai.generator.Anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_response
            mock_anthropic.return_value = mock_client

            generator = ACGenerator(ai_settings_enabled)
            result = await generator.extract_topics(
                summary="Implement SAML SSO",
                description=raw_description,
            )

            assert result == raw_description

    @pytest.mark.asyncio
    async def test_extract_topics_returns_raw_description_when_disabled(
        self, ai_settings_disabled: AISettings
    ):
        """Test extract_topics() returns raw description without API call when disabled."""
        raw_description = "Users need single sign-on via SAML for enterprise clients."

        generator = ACGenerator(ai_settings_disabled)
        result = await generator.extract_topics(
            summary="Implement SAML SSO",
            description=raw_description,
        )

        assert result == raw_description
