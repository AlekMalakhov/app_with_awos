"""Unit tests for intent classifier."""

from unittest.mock import MagicMock, patch

import pytest

from src.ai.config import AISettings
from src.ai.exceptions import AIInvalidResponseError
from src.slack.handlers.intent_classifier import (
    Intent,
    IntentClassifier,
    IntentResult,
)


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
    intent: str,
    modification_request: str | None = None,
) -> MagicMock:
    """Create a mock Anthropic API response with tool_use block.

    Args:
        intent: The classified intent (approve, reject, modify)
        modification_request: Optional modification request text

    Returns:
        Mock response object matching Anthropic API structure
    """
    tool_input = {"intent": intent}
    if modification_request is not None:
        tool_input["modification_request"] = modification_request

    tool_use_block = MagicMock()
    tool_use_block.type = "tool_use"
    tool_use_block.name = "classify_response"
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
    text_block.text = "I cannot classify this."

    response = MagicMock()
    response.content = [text_block]

    return response


class TestIntentEnum:
    """Test suite for Intent enum."""

    def test_intent_values(self):
        """Test that Intent enum has expected values."""
        assert Intent.APPROVE.value == "approve"
        assert Intent.REJECT.value == "reject"
        assert Intent.MODIFY.value == "modify"

    def test_intent_from_string(self):
        """Test creating Intent from string value."""
        assert Intent("approve") == Intent.APPROVE
        assert Intent("reject") == Intent.REJECT
        assert Intent("modify") == Intent.MODIFY


class TestIntentResult:
    """Test suite for IntentResult model."""

    def test_intent_result_approve(self):
        """Test IntentResult with APPROVE intent."""
        result = IntentResult(intent=Intent.APPROVE)
        assert result.intent == Intent.APPROVE
        assert result.modification_request is None

    def test_intent_result_reject(self):
        """Test IntentResult with REJECT intent."""
        result = IntentResult(intent=Intent.REJECT)
        assert result.intent == Intent.REJECT
        assert result.modification_request is None

    def test_intent_result_modify_with_request(self):
        """Test IntentResult with MODIFY intent and modification request."""
        result = IntentResult(
            intent=Intent.MODIFY,
            modification_request="Add error handling for edge cases",
        )
        assert result.intent == Intent.MODIFY
        assert result.modification_request == "Add error handling for edge cases"


class TestIntentClassifierIsEnabled:
    """Test suite for IntentClassifier.is_enabled property."""

    def test_is_enabled_returns_true_when_api_key_configured(
        self, ai_settings_enabled: AISettings
    ):
        """Test that is_enabled returns True when API key is set."""
        with patch("src.slack.handlers.intent_classifier.Anthropic"):
            classifier = IntentClassifier(ai_settings_enabled)

            assert classifier.is_enabled is True

    def test_is_enabled_returns_false_when_api_key_not_configured(
        self, ai_settings_disabled: AISettings
    ):
        """Test that is_enabled returns False when API key is empty."""
        classifier = IntentClassifier(ai_settings_disabled)

        assert classifier.is_enabled is False


class TestIntentClassifierApprove:
    """Test suite for APPROVE intent classification."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "message",
        [
            "approve",
            "yes",
            "looks good",
            "go ahead",
            "APPROVE",
            "Yes, looks good!",
            "lgtm",
            "ship it",
            "perfect",
        ],
    )
    async def test_classify_approve_intents(
        self, ai_settings_enabled: AISettings, message: str
    ):
        """Test classify_intent returns APPROVE for approval messages."""
        mock_response = create_mock_tool_use_response(intent="approve")

        with patch("src.slack.handlers.intent_classifier.Anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_response
            mock_anthropic.return_value = mock_client

            classifier = IntentClassifier(ai_settings_enabled)
            result = await classifier.classify_intent(message)

            assert result.intent == Intent.APPROVE
            assert result.modification_request is None


class TestIntentClassifierReject:
    """Test suite for REJECT intent classification."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "message",
        [
            "reject",
            "no",
            "cancel",
            "keep original",
            "REJECT",
            "No thanks",
            "nevermind",
            "stop",
            "abort",
        ],
    )
    async def test_classify_reject_intents(
        self, ai_settings_enabled: AISettings, message: str
    ):
        """Test classify_intent returns REJECT for rejection messages."""
        mock_response = create_mock_tool_use_response(intent="reject")

        with patch("src.slack.handlers.intent_classifier.Anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_response
            mock_anthropic.return_value = mock_client

            classifier = IntentClassifier(ai_settings_enabled)
            result = await classifier.classify_intent(message)

            assert result.intent == Intent.REJECT
            assert result.modification_request is None


class TestIntentClassifierModify:
    """Test suite for MODIFY intent classification."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "message,expected_modification",
        [
            ("add error handling", "Add error handling to the acceptance criteria"),
            (
                "change the second one to include validation",
                "Change the second criterion to include validation",
            ),
            (
                "remove the third criterion",
                "Remove the third acceptance criterion",
            ),
            (
                "make them more specific",
                "Make the acceptance criteria more specific",
            ),
        ],
    )
    async def test_classify_modify_intents(
        self,
        ai_settings_enabled: AISettings,
        message: str,
        expected_modification: str,
    ):
        """Test classify_intent returns MODIFY for modification messages."""
        mock_response = create_mock_tool_use_response(
            intent="modify",
            modification_request=expected_modification,
        )

        with patch("src.slack.handlers.intent_classifier.Anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_response
            mock_anthropic.return_value = mock_client

            classifier = IntentClassifier(ai_settings_enabled)
            result = await classifier.classify_intent(message)

            assert result.intent == Intent.MODIFY
            assert result.modification_request == expected_modification

    @pytest.mark.asyncio
    async def test_modify_intent_extracts_modification_request(
        self, ai_settings_enabled: AISettings
    ):
        """Test that modification_request is properly extracted for MODIFY intent."""
        expected_modification = "Add performance requirements and error handling"
        mock_response = create_mock_tool_use_response(
            intent="modify",
            modification_request=expected_modification,
        )

        with patch("src.slack.handlers.intent_classifier.Anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_response
            mock_anthropic.return_value = mock_client

            classifier = IntentClassifier(ai_settings_enabled)
            result = await classifier.classify_intent(
                "Please add performance requirements and error handling"
            )

            assert result.intent == Intent.MODIFY
            assert result.modification_request == expected_modification


class TestIntentClassifierEdgeCases:
    """Test suite for edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_classify_intent_returns_reject_when_disabled(
        self, ai_settings_disabled: AISettings
    ):
        """Test that classify_intent returns REJECT when classifier is disabled."""
        classifier = IntentClassifier(ai_settings_disabled)

        result = await classifier.classify_intent("yes")

        # Should default to REJECT to avoid unintended approvals
        assert result.intent == Intent.REJECT
        assert result.modification_request is None

    @pytest.mark.asyncio
    async def test_classify_intent_raises_error_on_api_exception(
        self, ai_settings_enabled: AISettings
    ):
        """Test that classify_intent raises error when API call fails."""
        with patch("src.slack.handlers.intent_classifier.Anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create.side_effect = Exception("API connection failed")
            mock_anthropic.return_value = mock_client

            classifier = IntentClassifier(ai_settings_enabled)

            with pytest.raises(AIInvalidResponseError) as exc_info:
                await classifier.classify_intent("approve")

            assert "Failed to classify intent" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_classify_intent_raises_error_when_no_tool_use_block(
        self, ai_settings_enabled: AISettings
    ):
        """Test that classify_intent raises error when response has no tool_use."""
        mock_response = create_mock_text_response()

        with patch("src.slack.handlers.intent_classifier.Anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_response
            mock_anthropic.return_value = mock_client

            classifier = IntentClassifier(ai_settings_enabled)

            with pytest.raises(AIInvalidResponseError) as exc_info:
                await classifier.classify_intent("approve")

            assert "tool_use block" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_classify_intent_raises_error_when_invalid_intent_value(
        self, ai_settings_enabled: AISettings
    ):
        """Test that classify_intent raises error for invalid intent value."""
        mock_response = create_mock_tool_use_response(intent="invalid_intent")

        with patch("src.slack.handlers.intent_classifier.Anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_response
            mock_anthropic.return_value = mock_client

            classifier = IntentClassifier(ai_settings_enabled)

            with pytest.raises(AIInvalidResponseError) as exc_info:
                await classifier.classify_intent("some message")

            assert "Invalid intent value" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_classify_intent_raises_error_when_intent_field_missing(
        self, ai_settings_enabled: AISettings
    ):
        """Test that classify_intent raises error when intent field is missing."""
        tool_use_block = MagicMock()
        tool_use_block.type = "tool_use"
        tool_use_block.name = "classify_response"
        tool_use_block.input = {}  # No intent field

        response = MagicMock()
        response.content = [tool_use_block]

        with patch("src.slack.handlers.intent_classifier.Anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = response
            mock_anthropic.return_value = mock_client

            classifier = IntentClassifier(ai_settings_enabled)

            with pytest.raises(AIInvalidResponseError) as exc_info:
                await classifier.classify_intent("some message")

            assert "intent field" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_classify_intent_calls_api_with_correct_parameters(
        self, ai_settings_enabled: AISettings
    ):
        """Test that classify_intent calls Anthropic API with correct parameters."""
        mock_response = create_mock_tool_use_response(intent="approve")

        with patch("src.slack.handlers.intent_classifier.Anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_response
            mock_anthropic.return_value = mock_client

            classifier = IntentClassifier(ai_settings_enabled)
            await classifier.classify_intent("looks good")

            # Verify Anthropic client was initialized with API key
            mock_anthropic.assert_called_once_with(api_key="sk-ant-test-key-12345")

            # Verify API call parameters
            call_args = mock_client.messages.create.call_args
            assert call_args.kwargs["model"] == "claude-sonnet-4-20250514"
            assert call_args.kwargs["max_tokens"] == 1024
            assert "system" in call_args.kwargs
            assert "tools" in call_args.kwargs
            assert call_args.kwargs["tool_choice"] == {
                "type": "tool",
                "name": "classify_response",
            }

            # Verify the message contains the user's input
            messages = call_args.kwargs["messages"]
            assert len(messages) == 1
            assert "looks good" in messages[0]["content"]


class TestIntentClassifierParseResponse:
    """Test suite for IntentClassifier._parse_response() method."""

    def test_parse_response_extracts_approve_intent(
        self, ai_settings_enabled: AISettings
    ):
        """Test _parse_response extracts APPROVE intent correctly."""
        mock_response = create_mock_tool_use_response(intent="approve")

        with patch("src.slack.handlers.intent_classifier.Anthropic"):
            classifier = IntentClassifier(ai_settings_enabled)
            result = classifier._parse_response(mock_response)

            assert result.intent == Intent.APPROVE
            assert result.modification_request is None

    def test_parse_response_extracts_reject_intent(
        self, ai_settings_enabled: AISettings
    ):
        """Test _parse_response extracts REJECT intent correctly."""
        mock_response = create_mock_tool_use_response(intent="reject")

        with patch("src.slack.handlers.intent_classifier.Anthropic"):
            classifier = IntentClassifier(ai_settings_enabled)
            result = classifier._parse_response(mock_response)

            assert result.intent == Intent.REJECT
            assert result.modification_request is None

    def test_parse_response_extracts_modify_intent_with_request(
        self, ai_settings_enabled: AISettings
    ):
        """Test _parse_response extracts MODIFY intent with modification request."""
        mock_response = create_mock_tool_use_response(
            intent="modify",
            modification_request="Add validation criteria",
        )

        with patch("src.slack.handlers.intent_classifier.Anthropic"):
            classifier = IntentClassifier(ai_settings_enabled)
            result = classifier._parse_response(mock_response)

            assert result.intent == Intent.MODIFY
            assert result.modification_request == "Add validation criteria"

    def test_parse_response_handles_modify_without_modification_request(
        self, ai_settings_enabled: AISettings
    ):
        """Test _parse_response handles MODIFY intent without modification request."""
        mock_response = create_mock_tool_use_response(intent="modify")

        with patch("src.slack.handlers.intent_classifier.Anthropic"):
            classifier = IntentClassifier(ai_settings_enabled)
            result = classifier._parse_response(mock_response)

            assert result.intent == Intent.MODIFY
            assert result.modification_request is None

    def test_parse_response_raises_error_for_wrong_tool_name(
        self, ai_settings_enabled: AISettings
    ):
        """Test _parse_response raises error when tool_use has wrong name."""
        tool_use_block = MagicMock()
        tool_use_block.type = "tool_use"
        tool_use_block.name = "wrong_tool_name"
        tool_use_block.input = {"intent": "approve"}

        response = MagicMock()
        response.content = [tool_use_block]

        with patch("src.slack.handlers.intent_classifier.Anthropic"):
            classifier = IntentClassifier(ai_settings_enabled)

            with pytest.raises(AIInvalidResponseError):
                classifier._parse_response(response)

    def test_parse_response_raises_error_for_empty_content(
        self, ai_settings_enabled: AISettings
    ):
        """Test _parse_response raises error when content is empty."""
        response = MagicMock()
        response.content = []

        with patch("src.slack.handlers.intent_classifier.Anthropic"):
            classifier = IntentClassifier(ai_settings_enabled)

            with pytest.raises(AIInvalidResponseError) as exc_info:
                classifier._parse_response(response)

            assert "tool_use block" in str(exc_info.value)
