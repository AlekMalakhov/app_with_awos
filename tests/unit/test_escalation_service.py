"""Unit tests for SlackEscalationService.

Tests the escalation workflow including:
- Resolving Slack user by email
- Opening a DM channel
- Composing and sending Block Kit messages with confidence gaps
- Handling error conditions at every step
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.slack.config import SlackSettings
from src.slack.models import EscalationResult
from src.slack.services.escalation_service import SlackEscalationService


@pytest.fixture
def slack_settings() -> SlackSettings:
    """Create SlackSettings with dummy tokens and a configured escalation email."""
    return SlackSettings(
        bot_token="xoxb-test-token",
        app_token="xapp-test-token",
        escalation_contact_email="po@example.com",
        confidence_threshold=0.7,
    )


@pytest.fixture
def slack_settings_no_email() -> SlackSettings:
    """Create SlackSettings with no escalation email configured."""
    return SlackSettings(
        bot_token="xoxb-test-token",
        app_token="xapp-test-token",
        escalation_contact_email=None,
    )


@pytest.fixture
def mock_slack_client() -> MagicMock:
    """Create a mock SlackClient with all async methods stubbed."""
    mock = MagicMock()
    mock.lookup_user_by_email = AsyncMock(return_value="U12345")
    mock.open_conversation = AsyncMock(return_value="D67890")
    mock.send_blocks_message = AsyncMock(return_value="1234567890.123456")
    mock.set_thread_title = AsyncMock(return_value=True)
    return mock


@pytest.fixture
def service(
    mock_slack_client: MagicMock,
    slack_settings: SlackSettings,
) -> SlackEscalationService:
    """Create a SlackEscalationService with mocked dependencies."""
    return SlackEscalationService(
        slack_client=mock_slack_client,
        settings=slack_settings,
    )


# -- Shared test data -------------------------------------------------------

TICKET_KEY = "PROJ-123"
TICKET_SUMMARY = "Implement user dashboard"
TICKET_URL = "https://jira.example.com/browse/PROJ-123"
CONFIDENCE_GAPS = [
    "What is the expected response time?",
    "Should we support pagination?",
]


class TestSlackEscalationServiceSuccess:
    """Test suite for the full success path of escalation."""

    @pytest.mark.asyncio
    async def test_full_success_path(
        self,
        service: SlackEscalationService,
        mock_slack_client: MagicMock,
    ) -> None:
        """Verify the full success path returns EscalationResult(sent=True)."""
        result = await service.escalate(
            TICKET_KEY, TICKET_SUMMARY, TICKET_URL, CONFIDENCE_GAPS
        )

        assert isinstance(result, EscalationResult)
        assert result.sent is True
        assert result.slack_user_id == "U12345"
        assert result.error is None

        # Verify the call chain
        mock_slack_client.lookup_user_by_email.assert_called_once_with(
            "po@example.com"
        )
        mock_slack_client.open_conversation.assert_called_once_with("U12345")
        mock_slack_client.send_blocks_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_block_kit_structure(
        self,
        service: SlackEscalationService,
        mock_slack_client: MagicMock,
    ) -> None:
        """Verify the Block Kit message contains expected structural elements."""
        await service.escalate(
            TICKET_KEY, TICKET_SUMMARY, TICKET_URL, CONFIDENCE_GAPS
        )

        # Capture the blocks argument
        call_args = mock_slack_client.send_blocks_message.call_args
        channel_arg = call_args[0][0]
        blocks = call_args[0][1]
        fallback_text = call_args[0][2]

        assert channel_arg == "D67890"

        # Verify there are exactly 6 blocks
        assert len(blocks) == 6

        # Block 0: Header with ticket key and summary
        header = blocks[0]
        assert header["type"] == "header"
        assert TICKET_KEY in header["text"]["text"]
        assert TICKET_SUMMARY in header["text"]["text"]

        # Block 1: Section with Jira link
        jira_section = blocks[1]
        assert jira_section["type"] == "section"
        assert TICKET_URL in jira_section["text"]["text"]
        assert "View in Jira" in jira_section["text"]["text"]

        # Block 2: Divider
        assert blocks[2]["type"] == "divider"

        # Block 3: Introduction text
        intro = blocks[3]
        assert intro["type"] == "section"
        assert "questions" in intro["text"]["text"].lower() or "draft" in intro["text"]["text"].lower()

        # Block 4: Confidence gaps as bullet points
        gaps_block = blocks[4]
        assert gaps_block["type"] == "section"
        gaps_text = gaps_block["text"]["text"]
        for gap in CONFIDENCE_GAPS:
            assert gap in gaps_text

        # Block 5: Context footer
        footer = blocks[5]
        assert footer["type"] == "context"
        footer_text = footer["elements"][0]["text"]
        assert "draft" in footer_text.lower() or "ticket" in footer_text.lower()

        # Verify fallback text mentions the ticket
        assert TICKET_KEY in fallback_text


class TestSlackEscalationServiceNoEmail:
    """Test suite for when no escalation email is configured."""

    @pytest.mark.asyncio
    async def test_no_escalation_email_configured(
        self,
        mock_slack_client: MagicMock,
        slack_settings_no_email: SlackSettings,
    ) -> None:
        """Verify returns sent=False with error when no escalation email is configured."""
        service = SlackEscalationService(
            slack_client=mock_slack_client,
            settings=slack_settings_no_email,
        )

        result = await service.escalate(
            TICKET_KEY, TICKET_SUMMARY, TICKET_URL, CONFIDENCE_GAPS
        )

        assert result.sent is False
        assert result.error == "No escalation contact configured"
        # Should not have called any Slack API methods
        mock_slack_client.lookup_user_by_email.assert_not_called()
        mock_slack_client.open_conversation.assert_not_called()
        mock_slack_client.send_blocks_message.assert_not_called()


class TestSlackEscalationServiceUserNotFound:
    """Test suite for when the Slack user lookup fails."""

    @pytest.mark.asyncio
    async def test_user_not_found(
        self,
        service: SlackEscalationService,
        mock_slack_client: MagicMock,
    ) -> None:
        """Verify returns sent=False with error when user is not found by email."""
        mock_slack_client.lookup_user_by_email = AsyncMock(return_value=None)

        result = await service.escalate(
            TICKET_KEY, TICKET_SUMMARY, TICKET_URL, CONFIDENCE_GAPS
        )

        assert result.sent is False
        assert result.error is not None
        assert "po@example.com" in result.error
        # Should not attempt to open conversation or send message
        mock_slack_client.open_conversation.assert_not_called()
        mock_slack_client.send_blocks_message.assert_not_called()


class TestSlackEscalationServiceDMChannelFails:
    """Test suite for when opening the DM channel fails."""

    @pytest.mark.asyncio
    async def test_dm_channel_open_fails(
        self,
        service: SlackEscalationService,
        mock_slack_client: MagicMock,
    ) -> None:
        """Verify returns sent=False when open_conversation returns None."""
        mock_slack_client.lookup_user_by_email = AsyncMock(return_value="U12345")
        mock_slack_client.open_conversation = AsyncMock(return_value=None)

        result = await service.escalate(
            TICKET_KEY, TICKET_SUMMARY, TICKET_URL, CONFIDENCE_GAPS
        )

        assert result.sent is False
        assert result.slack_user_id == "U12345"
        assert result.error is not None
        assert "DM" in result.error or "channel" in result.error.lower()
        # Should not attempt to send message
        mock_slack_client.send_blocks_message.assert_not_called()


class TestSlackEscalationServiceDMSendFails:
    """Test suite for when sending the DM fails."""

    @pytest.mark.asyncio
    async def test_dm_send_fails(
        self,
        service: SlackEscalationService,
        mock_slack_client: MagicMock,
    ) -> None:
        """Verify returns sent=False when send_blocks_message returns None."""
        mock_slack_client.lookup_user_by_email = AsyncMock(return_value="U12345")
        mock_slack_client.open_conversation = AsyncMock(return_value="D67890")
        mock_slack_client.send_blocks_message = AsyncMock(return_value=None)

        result = await service.escalate(
            TICKET_KEY, TICKET_SUMMARY, TICKET_URL, CONFIDENCE_GAPS
        )

        assert result.sent is False
        assert result.slack_user_id == "U12345"
        assert result.error is not None
