"""Unit tests for AI acceptance criteria generator."""

from unittest.mock import MagicMock, patch

import pytest

from src.ai.config import AISettings
from src.ai.exceptions import AIInvalidResponseError
from src.ai.generator import ACGenerator
from src.ai.models import ACGenerationResult


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
    confidence_score: float | None = None,
    confidence_gaps: list[str] | None = None,
) -> MagicMock:
    """Create a mock Anthropic API response with tool_use block.

    Args:
        sufficient_information: Whether the ticket has sufficient info
        acceptance_criteria: List of AC strings
        skip_reason: Optional reason for skipping
        confidence_score: Optional confidence score (omitted from
            tool_input when None, to test default handling)
        confidence_gaps: Optional confidence gaps (omitted from
            tool_input when None, to test default handling)

    Returns:
        Mock response object matching Anthropic API structure
    """
    tool_input = {
        "sufficient_information": sufficient_information,
        "acceptance_criteria": acceptance_criteria,
    }
    if skip_reason is not None:
        tool_input["skip_reason"] = skip_reason
    if confidence_score is not None:
        tool_input["confidence_score"] = confidence_score
    if confidence_gaps is not None:
        tool_input["confidence_gaps"] = confidence_gaps

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
        """Test generate() returns ACGenerationResult when API returns valid response."""
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
            confidence_score=0.9,
            confidence_gaps=[],
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

            assert isinstance(result, ACGenerationResult)
            assert result.acceptance_criteria == expected_acs
            assert len(result.acceptance_criteria) == 3
            assert result.sufficient_information is True
            assert result.confidence_score == 0.9
            assert result.confidence_gaps == []

    @pytest.mark.asyncio
    async def test_generate_returns_empty_acs_when_insufficient_information(
        self, ai_settings_enabled: AISettings
    ):
        """Test generate() returns result with empty ACs when insufficient info."""
        mock_response = create_mock_tool_use_response(
            sufficient_information=False,
            acceptance_criteria=[],
            skip_reason="The ticket description is too vague to generate specific ACs.",
            confidence_score=0.2,
            confidence_gaps=["vague description"],
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

            assert isinstance(result, ACGenerationResult)
            assert result.acceptance_criteria == []
            assert result.sufficient_information is False

    @pytest.mark.asyncio
    async def test_generate_returns_empty_acs_when_acceptance_criteria_empty(
        self, ai_settings_enabled: AISettings
    ):
        """Test that generate() returns result with empty ACs when AI returns empty list."""
        mock_response = create_mock_tool_use_response(
            sufficient_information=True,
            acceptance_criteria=[],
            confidence_score=0.5,
            confidence_gaps=[],
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

            assert isinstance(result, ACGenerationResult)
            assert result.acceptance_criteria == []
            assert result.sufficient_information is True

    @pytest.mark.asyncio
    async def test_generate_returns_empty_result_when_disabled(
        self, ai_settings_disabled: AISettings
    ):
        """Test that generate() returns empty ACGenerationResult when disabled."""
        generator = ACGenerator(ai_settings_disabled)

        result = await generator.generate(
            summary="Any summary",
            description="Any description",
        )

        assert isinstance(result, ACGenerationResult)
        assert result.acceptance_criteria == []
        assert result.sufficient_information is False
        assert result.confidence_score == 0.0
        assert result.confidence_gaps == ["Generator is disabled"]

    @pytest.mark.asyncio
    async def test_generate_returns_empty_result_on_api_exception(
        self, ai_settings_enabled: AISettings
    ):
        """Test that generate() returns empty ACGenerationResult on API exception."""
        with patch("src.ai.generator.Anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create.side_effect = Exception("API connection failed")
            mock_anthropic.return_value = mock_client

            generator = ACGenerator(ai_settings_enabled)
            result = await generator.generate(
                summary="Some feature",
                description="Some description",
            )

            assert isinstance(result, ACGenerationResult)
            assert result.acceptance_criteria == []
            assert result.sufficient_information is False
            assert result.confidence_score == 0.0
            assert result.confidence_gaps == ["Generation failed due to an error"]

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
            confidence_score=0.7,
            confidence_gaps=["no description provided"],
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

            assert isinstance(result, ACGenerationResult)
            assert result.acceptance_criteria == expected_acs

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
            confidence_score=0.95,
            confidence_gaps=[],
        )

        with patch("src.ai.generator.Anthropic"):
            generator = ACGenerator(ai_settings_enabled)

            result = generator._parse_response(mock_response)

            assert isinstance(result, ACGenerationResult)
            assert result.acceptance_criteria == expected_acs
            assert result.sufficient_information is True
            assert result.confidence_score == 0.95
            assert result.confidence_gaps == []

    def test_parse_response_returns_empty_acs_when_insufficient_info(
        self, ai_settings_enabled: AISettings
    ):
        """Test _parse_response() returns result with empty ACs when insufficient info."""
        mock_response = create_mock_tool_use_response(
            sufficient_information=False,
            acceptance_criteria=[],
            skip_reason="Not enough detail",
            confidence_score=0.3,
            confidence_gaps=["missing details"],
        )

        with patch("src.ai.generator.Anthropic"):
            generator = ACGenerator(ai_settings_enabled)

            result = generator._parse_response(mock_response)

            assert isinstance(result, ACGenerationResult)
            assert result.acceptance_criteria == []
            assert result.sufficient_information is False
            assert result.confidence_score == 0.3
            assert result.confidence_gaps == ["missing details"]

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

            # Should return empty ACs because sufficient_information defaults to False
            assert isinstance(result, ACGenerationResult)
            assert result.acceptance_criteria == []
            assert result.sufficient_information is False


class TestACGeneratorConfidenceScoreAndGaps:
    """Test suite for confidence_score and confidence_gaps parsing in _parse_response()."""

    def test_parse_response_with_valid_confidence_score_and_empty_gaps(
        self, ai_settings_enabled: AISettings
    ):
        """Test _parse_response() correctly parses high confidence with no gaps."""
        mock_response = create_mock_tool_use_response(
            sufficient_information=True,
            acceptance_criteria=["AC 1", "AC 2"],
            confidence_score=0.85,
            confidence_gaps=[],
        )

        with patch("src.ai.generator.Anthropic"):
            generator = ACGenerator(ai_settings_enabled)

            result = generator._parse_response(mock_response)

            assert result.confidence_score == 0.85
            assert result.confidence_gaps == []
            assert result.acceptance_criteria == ["AC 1", "AC 2"]
            assert result.sufficient_information is True

    def test_parse_response_with_low_confidence_and_gaps(
        self, ai_settings_enabled: AISettings
    ):
        """Test _parse_response() correctly parses low confidence with specific gaps."""
        expected_gaps = [
            "unclear user role",
            "missing error handling behavior",
        ]
        mock_response = create_mock_tool_use_response(
            sufficient_information=True,
            acceptance_criteria=["AC 1"],
            confidence_score=0.4,
            confidence_gaps=expected_gaps,
        )

        with patch("src.ai.generator.Anthropic"):
            generator = ACGenerator(ai_settings_enabled)

            result = generator._parse_response(mock_response)

            assert result.confidence_score == 0.4
            assert result.confidence_gaps == expected_gaps
            assert len(result.confidence_gaps) == 2

    def test_parse_response_defaults_confidence_score_when_missing(
        self, ai_settings_enabled: AISettings
    ):
        """Test _parse_response() defaults confidence_score to 1.0 when absent."""
        tool_use_block = MagicMock()
        tool_use_block.type = "tool_use"
        tool_use_block.name = "submit_acceptance_criteria"
        tool_use_block.input = {
            "sufficient_information": True,
            "acceptance_criteria": ["AC 1", "AC 2"],
            "confidence_gaps": [],
            # confidence_score intentionally omitted
        }

        response = MagicMock()
        response.content = [tool_use_block]

        with patch("src.ai.generator.Anthropic"):
            generator = ACGenerator(ai_settings_enabled)

            result = generator._parse_response(response)

            assert result.confidence_score == 1.0
            assert result.confidence_gaps == []
            assert result.acceptance_criteria == ["AC 1", "AC 2"]

    def test_parse_response_defaults_confidence_gaps_when_missing(
        self, ai_settings_enabled: AISettings
    ):
        """Test _parse_response() defaults confidence_gaps to [] when absent."""
        tool_use_block = MagicMock()
        tool_use_block.type = "tool_use"
        tool_use_block.name = "submit_acceptance_criteria"
        tool_use_block.input = {
            "sufficient_information": True,
            "acceptance_criteria": ["AC 1"],
            "confidence_score": 0.75,
            # confidence_gaps intentionally omitted
        }

        response = MagicMock()
        response.content = [tool_use_block]

        with patch("src.ai.generator.Anthropic"):
            generator = ACGenerator(ai_settings_enabled)

            result = generator._parse_response(response)

            assert result.confidence_score == 0.75
            assert result.confidence_gaps == []

    def test_parse_response_defaults_both_confidence_fields_when_missing(
        self, ai_settings_enabled: AISettings
    ):
        """Test _parse_response() applies defaults when both confidence fields absent."""
        tool_use_block = MagicMock()
        tool_use_block.type = "tool_use"
        tool_use_block.name = "submit_acceptance_criteria"
        tool_use_block.input = {
            "sufficient_information": True,
            "acceptance_criteria": ["AC 1", "AC 2", "AC 3"],
            # Both confidence_score and confidence_gaps intentionally omitted
        }

        response = MagicMock()
        response.content = [tool_use_block]

        with patch("src.ai.generator.Anthropic"):
            generator = ACGenerator(ai_settings_enabled)

            result = generator._parse_response(response)

            assert result.confidence_score == 1.0
            assert result.confidence_gaps == []
            assert result.acceptance_criteria == ["AC 1", "AC 2", "AC 3"]
            assert result.sufficient_information is True

    def test_parse_response_with_confidence_score_at_lower_boundary(
        self, ai_settings_enabled: AISettings
    ):
        """Test _parse_response() handles confidence_score of 0.0."""
        mock_response = create_mock_tool_use_response(
            sufficient_information=True,
            acceptance_criteria=["AC 1"],
            confidence_score=0.0,
            confidence_gaps=["no information available"],
        )

        with patch("src.ai.generator.Anthropic"):
            generator = ACGenerator(ai_settings_enabled)

            result = generator._parse_response(mock_response)

            assert result.confidence_score == 0.0
            assert result.confidence_gaps == ["no information available"]

    def test_parse_response_with_confidence_score_at_upper_boundary(
        self, ai_settings_enabled: AISettings
    ):
        """Test _parse_response() handles confidence_score of 1.0."""
        mock_response = create_mock_tool_use_response(
            sufficient_information=True,
            acceptance_criteria=["AC 1", "AC 2"],
            confidence_score=1.0,
            confidence_gaps=[],
        )

        with patch("src.ai.generator.Anthropic"):
            generator = ACGenerator(ai_settings_enabled)

            result = generator._parse_response(mock_response)

            assert result.confidence_score == 1.0
            assert result.confidence_gaps == []


class TestACGeneratorIntegration:
    """Integration-style tests for ACGenerator (still mocked, but testing full flow)."""

    @pytest.mark.asyncio
    async def test_full_flow_with_valid_ticket(self, ai_settings_enabled: AISettings):
        """Test complete flow from generate() to parsed ACGenerationResult."""
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
            confidence_score=0.95,
            confidence_gaps=[],
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

            assert isinstance(result, ACGenerationResult)
            assert result.acceptance_criteria == expected_acs
            assert len(result.acceptance_criteria) == 4
            assert result.sufficient_information is True
            assert result.confidence_score == 0.95
            assert result.confidence_gaps == []

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
            confidence_score=0.1,
            confidence_gaps=["extremely vague description"],
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

            assert isinstance(result, ACGenerationResult)
            assert result.acceptance_criteria == []
            assert result.sufficient_information is False
            assert result.confidence_score == 0.1
            assert result.confidence_gaps == ["extremely vague description"]


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
