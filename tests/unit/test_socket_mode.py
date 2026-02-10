"""Unit tests for Slack Socket Mode service with AI Agent support.

Tests cover:
- assistant_thread_started event handling
- assistant_thread_context_changed event handling
- Message event handling in assistant threads
- Traditional DM message handling
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.slack.config import SlackSettings
from src.slack.socket_mode import (
    DEFAULT_SUGGESTED_PROMPTS,
    DEFAULT_WELCOME_MESSAGE,
    SlackSocketModeService,
)


@pytest.fixture
def slack_settings() -> SlackSettings:
    """Create SlackSettings with test values."""
    return SlackSettings(
        bot_token="xoxb-test-token-12345",
        app_token="xapp-test-app-token-67890",
        signing_secret="test-signing-secret",
        max_retries=1,
    )


@pytest.fixture
def mock_async_app() -> MagicMock:
    """Create a mock AsyncApp."""
    mock_app = MagicMock()
    mock_app.event = MagicMock(return_value=lambda f: f)
    return mock_app


@pytest.fixture
def mock_socket_handler() -> MagicMock:
    """Create a mock AsyncSocketModeHandler."""
    mock_handler = MagicMock()
    mock_handler.start_async = AsyncMock()
    mock_handler.close_async = AsyncMock()
    return mock_handler


class TestSlackSocketModeServiceInit:
    """Test suite for SlackSocketModeService initialization."""

    def test_service_initializes_with_settings(
        self, slack_settings: SlackSettings
    ) -> None:
        """Test that service initializes correctly with settings."""
        with patch(
            "src.slack.socket_mode.AsyncApp"
        ) as mock_app_class, patch(
            "src.slack.socket_mode.AsyncSocketModeHandler"
        ) as mock_handler_class:
            mock_app_class.return_value = MagicMock()
            mock_handler_class.return_value = MagicMock()

            service = SlackSocketModeService(slack_settings)

            assert service._settings == slack_settings
            assert service._running is False
            mock_app_class.assert_called_once_with(token=slack_settings.bot_token)
            mock_handler_class.assert_called_once()

    def test_service_registers_event_handlers(
        self, slack_settings: SlackSettings
    ) -> None:
        """Test that service registers all required event handlers."""
        with patch(
            "src.slack.socket_mode.AsyncApp"
        ) as mock_app_class, patch(
            "src.slack.socket_mode.AsyncSocketModeHandler"
        ):
            mock_app = MagicMock()
            mock_app_class.return_value = mock_app

            # Track which events are registered
            registered_events: list[str] = []

            def track_event(event_type: str):
                def decorator(func):
                    registered_events.append(event_type)
                    return func
                return decorator

            mock_app.event = track_event

            SlackSocketModeService(slack_settings)

            # Verify all three event types are registered
            assert "assistant_thread_started" in registered_events
            assert "assistant_thread_context_changed" in registered_events
            assert "message" in registered_events


class TestAssistantThreadStartedHandler:
    """Test suite for assistant_thread_started event handling."""

    @pytest.mark.asyncio
    async def test_handler_sends_welcome_message(
        self, slack_settings: SlackSettings
    ) -> None:
        """Test that handler sends welcome message on thread start."""
        with patch(
            "src.slack.socket_mode.AsyncApp"
        ) as mock_app_class, patch(
            "src.slack.socket_mode.AsyncSocketModeHandler"
        ):
            mock_app = MagicMock()
            mock_app_class.return_value = mock_app

            # Capture the registered handler
            handlers: dict[str, Any] = {}

            def capture_handler(event_type: str):
                def decorator(func):
                    handlers[event_type] = func
                    return func
                return decorator

            mock_app.event = capture_handler

            SlackSocketModeService(slack_settings)

            # Get the registered handler
            handler = handlers.get("assistant_thread_started")
            assert handler is not None

            # Create mocks for handler arguments
            event = {"type": "assistant_thread_started"}
            say = AsyncMock()
            set_status = MagicMock()
            set_suggested_prompts = MagicMock()

            # Call the handler
            await handler(event, say, set_status, set_suggested_prompts)

            # Verify welcome message was sent
            say.assert_called_once_with(text=DEFAULT_WELCOME_MESSAGE)

    @pytest.mark.asyncio
    async def test_handler_sets_status(
        self, slack_settings: SlackSettings
    ) -> None:
        """Test that handler sets status indicator."""
        with patch(
            "src.slack.socket_mode.AsyncApp"
        ) as mock_app_class, patch(
            "src.slack.socket_mode.AsyncSocketModeHandler"
        ):
            mock_app = MagicMock()
            mock_app_class.return_value = mock_app

            handlers: dict[str, Any] = {}

            def capture_handler(event_type: str):
                def decorator(func):
                    handlers[event_type] = func
                    return func
                return decorator

            mock_app.event = capture_handler

            SlackSocketModeService(slack_settings)

            handler = handlers.get("assistant_thread_started")
            event = {"type": "assistant_thread_started"}
            say = AsyncMock()
            set_status = MagicMock()
            set_suggested_prompts = MagicMock()

            await handler(event, say, set_status, set_suggested_prompts)

            set_status.assert_called_once_with("is ready to help...")

    @pytest.mark.asyncio
    async def test_handler_sets_suggested_prompts(
        self, slack_settings: SlackSettings
    ) -> None:
        """Test that handler sets suggested prompts."""
        with patch(
            "src.slack.socket_mode.AsyncApp"
        ) as mock_app_class, patch(
            "src.slack.socket_mode.AsyncSocketModeHandler"
        ):
            mock_app = MagicMock()
            mock_app_class.return_value = mock_app

            handlers: dict[str, Any] = {}

            def capture_handler(event_type: str):
                def decorator(func):
                    handlers[event_type] = func
                    return func
                return decorator

            mock_app.event = capture_handler

            SlackSocketModeService(slack_settings)

            handler = handlers.get("assistant_thread_started")
            event = {"type": "assistant_thread_started"}
            say = AsyncMock()
            set_status = MagicMock()
            set_suggested_prompts = MagicMock()

            await handler(event, say, set_status, set_suggested_prompts)

            set_suggested_prompts.assert_called_once_with(DEFAULT_SUGGESTED_PROMPTS)

    @pytest.mark.asyncio
    async def test_handler_handles_errors_gracefully(
        self, slack_settings: SlackSettings
    ) -> None:
        """Test that handler handles errors without raising."""
        with patch(
            "src.slack.socket_mode.AsyncApp"
        ) as mock_app_class, patch(
            "src.slack.socket_mode.AsyncSocketModeHandler"
        ):
            mock_app = MagicMock()
            mock_app_class.return_value = mock_app

            handlers: dict[str, Any] = {}

            def capture_handler(event_type: str):
                def decorator(func):
                    handlers[event_type] = func
                    return func
                return decorator

            mock_app.event = capture_handler

            SlackSocketModeService(slack_settings)

            handler = handlers.get("assistant_thread_started")
            event = {"type": "assistant_thread_started"}
            say = AsyncMock(side_effect=Exception("API Error"))
            set_status = MagicMock()
            set_suggested_prompts = MagicMock()

            # Should not raise
            await handler(event, say, set_status, set_suggested_prompts)


class TestAssistantThreadContextChangedHandler:
    """Test suite for assistant_thread_context_changed event handling."""

    @pytest.mark.asyncio
    async def test_handler_logs_context_change(
        self, slack_settings: SlackSettings
    ) -> None:
        """Test that handler processes context change event."""
        with patch(
            "src.slack.socket_mode.AsyncApp"
        ) as mock_app_class, patch(
            "src.slack.socket_mode.AsyncSocketModeHandler"
        ):
            mock_app = MagicMock()
            mock_app_class.return_value = mock_app

            handlers: dict[str, Any] = {}

            def capture_handler(event_type: str):
                def decorator(func):
                    handlers[event_type] = func
                    return func
                return decorator

            mock_app.event = capture_handler

            SlackSocketModeService(slack_settings)

            handler = handlers.get("assistant_thread_context_changed")
            assert handler is not None

            event = {
                "type": "assistant_thread_context_changed",
                "assistant_thread": {
                    "context": {
                        "channel_id": "C123456",
                    }
                },
            }
            say = AsyncMock()

            # Should not raise
            await handler(event, say)


class TestMessageHandler:
    """Test suite for message event handling."""

    @pytest.mark.asyncio
    async def test_handler_ignores_bot_messages(
        self, slack_settings: SlackSettings
    ) -> None:
        """Test that handler ignores messages from bots."""
        with patch(
            "src.slack.socket_mode.AsyncApp"
        ) as mock_app_class, patch(
            "src.slack.socket_mode.AsyncSocketModeHandler"
        ):
            mock_app = MagicMock()
            mock_app_class.return_value = mock_app

            handlers: dict[str, Any] = {}

            def capture_handler(event_type: str):
                def decorator(func):
                    handlers[event_type] = func
                    return func
                return decorator

            mock_app.event = capture_handler

            SlackSocketModeService(slack_settings)

            handler = handlers.get("message")
            event = {
                "type": "message",
                "bot_id": "B12345",
                "channel": "D12345",
                "text": "Bot message",
            }
            say = AsyncMock()

            await handler(event, say)

            # say should not be called for bot messages
            say.assert_not_called()

    @pytest.mark.asyncio
    async def test_handler_ignores_subtype_messages(
        self, slack_settings: SlackSettings
    ) -> None:
        """Test that handler ignores messages with subtypes."""
        with patch(
            "src.slack.socket_mode.AsyncApp"
        ) as mock_app_class, patch(
            "src.slack.socket_mode.AsyncSocketModeHandler"
        ):
            mock_app = MagicMock()
            mock_app_class.return_value = mock_app

            handlers: dict[str, Any] = {}

            def capture_handler(event_type: str):
                def decorator(func):
                    handlers[event_type] = func
                    return func
                return decorator

            mock_app.event = capture_handler

            SlackSocketModeService(slack_settings)

            handler = handlers.get("message")
            event = {
                "type": "message",
                "subtype": "message_changed",
                "user": "U12345",
                "channel": "D12345",
                "text": "Edited message",
            }
            say = AsyncMock()

            await handler(event, say)

            say.assert_not_called()

    @pytest.mark.asyncio
    async def test_handler_ignores_messages_without_user(
        self, slack_settings: SlackSettings
    ) -> None:
        """Test that handler ignores messages without user ID."""
        with patch(
            "src.slack.socket_mode.AsyncApp"
        ) as mock_app_class, patch(
            "src.slack.socket_mode.AsyncSocketModeHandler"
        ):
            mock_app = MagicMock()
            mock_app_class.return_value = mock_app

            handlers: dict[str, Any] = {}

            def capture_handler(event_type: str):
                def decorator(func):
                    handlers[event_type] = func
                    return func
                return decorator

            mock_app.event = capture_handler

            SlackSocketModeService(slack_settings)

            handler = handlers.get("message")
            event = {
                "type": "message",
                "channel": "D12345",
                "text": "Message without user",
            }
            say = AsyncMock()

            await handler(event, say)

            say.assert_not_called()

    @pytest.mark.asyncio
    async def test_handler_sets_status_when_available(
        self, slack_settings: SlackSettings
    ) -> None:
        """Test that handler sets 'thinking' status when set_status is provided."""
        with patch(
            "src.slack.socket_mode.AsyncApp"
        ) as mock_app_class, patch(
            "src.slack.socket_mode.AsyncSocketModeHandler"
        ):
            mock_app = MagicMock()
            mock_app_class.return_value = mock_app

            handlers: dict[str, Any] = {}

            def capture_handler(event_type: str):
                def decorator(func):
                    handlers[event_type] = func
                    return func
                return decorator

            mock_app.event = capture_handler

            service = SlackSocketModeService(slack_settings)

            # Mock _process_message to return a response
            with patch.object(
                service, "_process_message", new_callable=AsyncMock
            ) as mock_process:
                mock_process.return_value = "Test response"

                handler = handlers.get("message")
                event = {
                    "type": "message",
                    "user": "U12345",
                    "channel": "D12345",
                    "text": "Hello",
                    "channel_type": "im",
                }
                say = AsyncMock()
                set_status = MagicMock()

                await handler(event, say, set_status)

                set_status.assert_called_once_with("is thinking...")

    @pytest.mark.asyncio
    async def test_handler_processes_user_message(
        self, slack_settings: SlackSettings
    ) -> None:
        """Test that handler processes valid user messages."""
        with patch(
            "src.slack.socket_mode.AsyncApp"
        ) as mock_app_class, patch(
            "src.slack.socket_mode.AsyncSocketModeHandler"
        ):
            mock_app = MagicMock()
            mock_app_class.return_value = mock_app

            handlers: dict[str, Any] = {}

            def capture_handler(event_type: str):
                def decorator(func):
                    handlers[event_type] = func
                    return func
                return decorator

            mock_app.event = capture_handler

            service = SlackSocketModeService(slack_settings)

            # Mock _process_message to return a response
            with patch.object(
                service, "_process_message", new_callable=AsyncMock
            ) as mock_process:
                mock_process.return_value = "Test response"

                handler = handlers.get("message")
                event = {
                    "type": "message",
                    "user": "U12345",
                    "channel": "D12345",
                    "text": "PROJ-123",
                }
                say = AsyncMock()

                await handler(event, say)

                mock_process.assert_called_once_with(
                    "U12345", "D12345", "PROJ-123", event_ts=None
                )
                say.assert_called_once_with(text="Test response")

    @pytest.mark.asyncio
    async def test_handler_does_not_respond_when_no_response(
        self, slack_settings: SlackSettings
    ) -> None:
        """Test that handler does not call say when process returns None."""
        with patch(
            "src.slack.socket_mode.AsyncApp"
        ) as mock_app_class, patch(
            "src.slack.socket_mode.AsyncSocketModeHandler"
        ):
            mock_app = MagicMock()
            mock_app_class.return_value = mock_app

            handlers: dict[str, Any] = {}

            def capture_handler(event_type: str):
                def decorator(func):
                    handlers[event_type] = func
                    return func
                return decorator

            mock_app.event = capture_handler

            service = SlackSocketModeService(slack_settings)

            with patch.object(
                service, "_process_message", new_callable=AsyncMock
            ) as mock_process:
                mock_process.return_value = None

                handler = handlers.get("message")
                event = {
                    "type": "message",
                    "user": "U12345",
                    "channel": "D12345",
                    "text": "Hello",
                }
                say = AsyncMock()

                await handler(event, say)

                say.assert_not_called()


class TestServiceLifecycle:
    """Test suite for service start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_sets_running_flag(
        self, slack_settings: SlackSettings
    ) -> None:
        """Test that start sets the running flag."""
        with patch(
            "src.slack.socket_mode.AsyncApp"
        ) as mock_app_class, patch(
            "src.slack.socket_mode.AsyncSocketModeHandler"
        ) as mock_handler_class:
            mock_app = MagicMock()
            mock_app_class.return_value = mock_app

            mock_handler = MagicMock()
            mock_handler.start_async = AsyncMock()
            mock_handler_class.return_value = mock_handler

            service = SlackSocketModeService(slack_settings)

            assert service.is_running is False

            await service.start()

            assert service.is_running is True

    @pytest.mark.asyncio
    async def test_start_raises_if_already_running(
        self, slack_settings: SlackSettings
    ) -> None:
        """Test that start raises RuntimeError if already running."""
        with patch(
            "src.slack.socket_mode.AsyncApp"
        ) as mock_app_class, patch(
            "src.slack.socket_mode.AsyncSocketModeHandler"
        ) as mock_handler_class:
            mock_app = MagicMock()
            mock_app_class.return_value = mock_app

            mock_handler = MagicMock()
            mock_handler.start_async = AsyncMock()
            mock_handler_class.return_value = mock_handler

            service = SlackSocketModeService(slack_settings)

            await service.start()

            with pytest.raises(RuntimeError, match="already running"):
                await service.start()

    @pytest.mark.asyncio
    async def test_stop_clears_running_flag(
        self, slack_settings: SlackSettings
    ) -> None:
        """Test that stop clears the running flag."""
        with patch(
            "src.slack.socket_mode.AsyncApp"
        ) as mock_app_class, patch(
            "src.slack.socket_mode.AsyncSocketModeHandler"
        ) as mock_handler_class:
            mock_app = MagicMock()
            mock_app_class.return_value = mock_app

            mock_handler = MagicMock()
            mock_handler.start_async = AsyncMock()
            mock_handler.close_async = AsyncMock()
            mock_handler_class.return_value = mock_handler

            service = SlackSocketModeService(slack_settings)

            await service.start()
            assert service.is_running is True

            await service.stop()
            assert service.is_running is False

    @pytest.mark.asyncio
    async def test_stop_when_not_running_is_noop(
        self, slack_settings: SlackSettings
    ) -> None:
        """Test that stop does nothing if service is not running."""
        with patch(
            "src.slack.socket_mode.AsyncApp"
        ) as mock_app_class, patch(
            "src.slack.socket_mode.AsyncSocketModeHandler"
        ) as mock_handler_class:
            mock_app = MagicMock()
            mock_app_class.return_value = mock_app

            mock_handler = MagicMock()
            mock_handler.close_async = AsyncMock()
            mock_handler_class.return_value = mock_handler

            service = SlackSocketModeService(slack_settings)

            # Should not raise
            await service.stop()

            # close_async should not be called
            mock_handler.close_async.assert_not_called()


class TestDefaultConstants:
    """Test suite for default constants."""

    def test_default_welcome_message_is_not_empty(self) -> None:
        """Test that default welcome message is not empty."""
        assert DEFAULT_WELCOME_MESSAGE
        assert len(DEFAULT_WELCOME_MESSAGE) > 0

    def test_default_welcome_message_mentions_jira(self) -> None:
        """Test that default welcome message mentions Jira."""
        assert "Jira" in DEFAULT_WELCOME_MESSAGE

    def test_default_suggested_prompts_is_list(self) -> None:
        """Test that default suggested prompts is a list."""
        assert isinstance(DEFAULT_SUGGESTED_PROMPTS, list)
        assert len(DEFAULT_SUGGESTED_PROMPTS) > 0

    def test_default_suggested_prompts_have_required_keys(self) -> None:
        """Test that each suggested prompt has title and message."""
        for prompt in DEFAULT_SUGGESTED_PROMPTS:
            assert "title" in prompt
            assert "message" in prompt
            assert prompt["title"]
            assert prompt["message"]
