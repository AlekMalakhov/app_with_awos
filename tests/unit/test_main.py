"""Unit tests for FastAPI application startup behavior with Jira credential validation."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.jira.exceptions import JiraAuthenticationError, JiraConnectionError


class TestAppStartupSuccess:
    """Test suite for successful application startup."""

    @patch("src.main.AISettings")
    @patch("src.main.JiraClient")
    @patch("src.main.JiraSettings")
    def test_startup_with_valid_credentials_starts_app_successfully(
        self,
        mock_settings_class: MagicMock,
        mock_client_class: MagicMock,
        mock_ai_settings_class: MagicMock,
    ):
        """Test that app starts successfully when Jira credentials are valid.

        Given valid Jira credentials
        When the FastAPI app starts
        Then JiraClient.validate_connection() is called
        And the app starts without error
        And the health check endpoint returns 200
        """
        # Arrange: Mock JiraSettings with polling disabled
        mock_settings = MagicMock()
        mock_settings.polling_enabled = False
        mock_settings_class.return_value = mock_settings

        # Arrange: Mock JiraClient with successful validation
        mock_client = AsyncMock()
        mock_client.validate_connection = AsyncMock(return_value=True)
        mock_client.close = AsyncMock()
        mock_client_class.return_value = mock_client

        # Arrange: Mock AISettings (disabled)
        mock_ai_settings = MagicMock()
        mock_ai_settings.is_enabled = False
        mock_ai_settings_class.return_value = mock_ai_settings

        # Act & Assert: Import app after mocking to apply patches
        from src.main import app

        with TestClient(app) as client:
            response = client.get("/health")

            # Assert: Health check returns 200
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"
            assert "slack_socket_mode" in data
            assert "database" in data
            assert "uptime_seconds" in data

            # Assert: JiraClient was properly initialized and validated
            mock_settings_class.assert_called_once()
            mock_client_class.assert_called_once_with(mock_settings)
            mock_client.validate_connection.assert_called_once()

    @patch("src.main.AISettings")
    @patch("src.main.JiraClient")
    @patch("src.main.JiraSettings")
    def test_startup_logs_success_message(
        self,
        mock_settings_class: MagicMock,
        mock_client_class: MagicMock,
        mock_ai_settings_class: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ):
        """Test that successful startup logs the validation success message.

        Given valid Jira credentials
        When the FastAPI app starts
        Then 'Jira connection validated successfully' is logged
        """
        # Arrange: Mock JiraSettings with polling disabled
        mock_settings = MagicMock()
        mock_settings.polling_enabled = False
        mock_settings_class.return_value = mock_settings

        # Arrange: Mock JiraClient with successful validation
        mock_client = AsyncMock()
        mock_client.validate_connection = AsyncMock(return_value=True)
        mock_client.close = AsyncMock()
        mock_client_class.return_value = mock_client

        # Arrange: Mock AISettings (disabled)
        mock_ai_settings = MagicMock()
        mock_ai_settings.is_enabled = False
        mock_ai_settings_class.return_value = mock_ai_settings

        # Act: Import app after mocking and start via TestClient
        from src.main import app

        with caplog.at_level("INFO"):
            with TestClient(app):
                pass

        # Assert: Success message was logged
        assert "Jira connection validated successfully" in caplog.text

    @patch("src.main.AISettings")
    @patch("src.main.JiraClient")
    @patch("src.main.JiraSettings")
    def test_startup_stores_client_in_app_state(
        self,
        mock_settings_class: MagicMock,
        mock_client_class: MagicMock,
        mock_ai_settings_class: MagicMock,
    ):
        """Test that JiraClient is stored in app.state after successful startup.

        Given valid Jira credentials
        When the FastAPI app starts successfully
        Then the JiraClient instance is stored in app.state.jira_client
        """
        # Arrange: Mock JiraSettings with polling disabled
        mock_settings = MagicMock()
        mock_settings.polling_enabled = False
        mock_settings_class.return_value = mock_settings

        # Arrange: Mock JiraClient with successful validation
        mock_client = AsyncMock()
        mock_client.validate_connection = AsyncMock(return_value=True)
        mock_client.close = AsyncMock()
        mock_client_class.return_value = mock_client

        # Arrange: Mock AISettings (disabled)
        mock_ai_settings = MagicMock()
        mock_ai_settings.is_enabled = False
        mock_ai_settings_class.return_value = mock_ai_settings

        # Act: Import app after mocking
        from src.main import app

        with TestClient(app):
            # Assert: JiraClient is stored in app state
            assert hasattr(app.state, "jira_client")
            assert app.state.jira_client is mock_client

    @patch("src.main.AISettings")
    @patch("src.main.JiraClient")
    @patch("src.main.JiraSettings")
    def test_shutdown_closes_jira_client(
        self,
        mock_settings_class: MagicMock,
        mock_client_class: MagicMock,
        mock_ai_settings_class: MagicMock,
    ):
        """Test that JiraClient is closed on application shutdown.

        Given the app is running with a valid JiraClient
        When the FastAPI app shuts down
        Then JiraClient.close() is called
        """
        # Arrange: Mock JiraSettings with polling disabled
        mock_settings = MagicMock()
        mock_settings.polling_enabled = False
        mock_settings_class.return_value = mock_settings

        # Arrange: Mock JiraClient with successful validation
        mock_client = AsyncMock()
        mock_client.validate_connection = AsyncMock(return_value=True)
        mock_client.close = AsyncMock()
        mock_client_class.return_value = mock_client

        # Arrange: Mock AISettings (disabled)
        mock_ai_settings = MagicMock()
        mock_ai_settings.is_enabled = False
        mock_ai_settings_class.return_value = mock_ai_settings

        # Act: Import app after mocking, then enter and exit TestClient
        from src.main import app

        with TestClient(app):
            pass  # App starts and then shuts down

        # Assert: close() was called on shutdown
        mock_client.close.assert_called_once()


class TestAppStartupAuthenticationFailure:
    """Test suite for application startup with authentication failure."""

    @patch("src.main.sys.exit")
    @patch("src.main.JiraClient")
    @patch("src.main.JiraSettings")
    def test_startup_with_invalid_credentials_calls_sys_exit(
        self,
        mock_settings_class: MagicMock,
        mock_client_class: MagicMock,
        mock_exit: MagicMock,
    ):
        """Test that app calls sys.exit(1) when Jira authentication fails.

        Given invalid Jira credentials
        When the FastAPI app starts
        Then JiraClient.validate_connection() raises JiraAuthenticationError
        And sys.exit(1) is called
        """
        # Arrange: Mock JiraSettings
        mock_settings = MagicMock()
        mock_settings_class.return_value = mock_settings

        # Arrange: Mock JiraClient to raise JiraAuthenticationError
        mock_client = AsyncMock()
        mock_client.validate_connection = AsyncMock(
            side_effect=JiraAuthenticationError("Authentication failed with status 401")
        )
        mock_client.close = AsyncMock()
        mock_client_class.return_value = mock_client

        # Act: Import app after mocking
        from src.main import app

        try:
            with TestClient(app):
                pass
        except Exception:
            pass  # TestClient may raise due to sys.exit mock

        # Assert: sys.exit was called with exit code 1
        mock_exit.assert_called_once_with(1)

    @patch("src.main.sys.exit")
    @patch("src.main.JiraClient")
    @patch("src.main.JiraSettings")
    def test_startup_authentication_failure_logs_error(
        self,
        mock_settings_class: MagicMock,
        mock_client_class: MagicMock,
        mock_exit: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ):
        """Test that authentication failure logs an error message.

        Given invalid Jira credentials
        When the FastAPI app starts
        Then an error message about authentication failure is logged
        """
        # Arrange: Mock JiraSettings
        mock_settings = MagicMock()
        mock_settings_class.return_value = mock_settings

        # Arrange: Mock JiraClient to raise JiraAuthenticationError
        mock_client = AsyncMock()
        mock_client.validate_connection = AsyncMock(
            side_effect=JiraAuthenticationError("Authentication failed with status 401")
        )
        mock_client.close = AsyncMock()
        mock_client_class.return_value = mock_client

        # Act: Import app after mocking
        from src.main import app

        with caplog.at_level("ERROR"):
            try:
                with TestClient(app):
                    pass
            except Exception:
                pass

        # Assert: Authentication failure was logged
        assert "Jira authentication failed" in caplog.text


class TestAppStartupConnectionFailure:
    """Test suite for application startup with connection failure."""

    @patch("src.main.sys.exit")
    @patch("src.main.JiraClient")
    @patch("src.main.JiraSettings")
    def test_startup_with_unreachable_jira_calls_sys_exit(
        self,
        mock_settings_class: MagicMock,
        mock_client_class: MagicMock,
        mock_exit: MagicMock,
    ):
        """Test that app calls sys.exit(1) when Jira is unreachable.

        Given Jira server is unreachable
        When the FastAPI app starts
        Then JiraClient.validate_connection() raises JiraConnectionError
        And sys.exit(1) is called
        """
        # Arrange: Mock JiraSettings
        mock_settings = MagicMock()
        mock_settings_class.return_value = mock_settings

        # Arrange: Mock JiraClient to raise JiraConnectionError
        mock_client = AsyncMock()
        mock_client.validate_connection = AsyncMock(
            side_effect=JiraConnectionError("Failed to connect to Jira")
        )
        mock_client.close = AsyncMock()
        mock_client_class.return_value = mock_client

        # Act: Import app after mocking
        from src.main import app

        try:
            with TestClient(app):
                pass
        except Exception:
            pass  # TestClient may raise due to sys.exit mock

        # Assert: sys.exit was called with exit code 1
        mock_exit.assert_called_once_with(1)

    @patch("src.main.sys.exit")
    @patch("src.main.JiraClient")
    @patch("src.main.JiraSettings")
    def test_startup_connection_failure_logs_error(
        self,
        mock_settings_class: MagicMock,
        mock_client_class: MagicMock,
        mock_exit: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ):
        """Test that connection failure logs an error message.

        Given Jira server is unreachable
        When the FastAPI app starts
        Then an error message about Jira being unreachable is logged
        """
        # Arrange: Mock JiraSettings
        mock_settings = MagicMock()
        mock_settings_class.return_value = mock_settings

        # Arrange: Mock JiraClient to raise JiraConnectionError
        mock_client = AsyncMock()
        mock_client.validate_connection = AsyncMock(
            side_effect=JiraConnectionError("Connection refused")
        )
        mock_client.close = AsyncMock()
        mock_client_class.return_value = mock_client

        # Act: Import app after mocking
        from src.main import app

        with caplog.at_level("ERROR"):
            try:
                with TestClient(app):
                    pass
            except Exception:
                pass

        # Assert: Connection failure was logged
        assert "Jira unreachable" in caplog.text

    @patch("src.main.sys.exit")
    @patch("src.main.JiraClient")
    @patch("src.main.JiraSettings")
    def test_startup_timeout_calls_sys_exit(
        self,
        mock_settings_class: MagicMock,
        mock_client_class: MagicMock,
        mock_exit: MagicMock,
    ):
        """Test that app calls sys.exit(1) when Jira connection times out.

        Given Jira connection times out
        When the FastAPI app starts
        Then JiraClient.validate_connection() raises JiraConnectionError
        And sys.exit(1) is called
        """
        # Arrange: Mock JiraSettings
        mock_settings = MagicMock()
        mock_settings_class.return_value = mock_settings

        # Arrange: Mock JiraClient to raise JiraConnectionError (timeout)
        mock_client = AsyncMock()
        mock_client.validate_connection = AsyncMock(
            side_effect=JiraConnectionError("Request to Jira timed out")
        )
        mock_client.close = AsyncMock()
        mock_client_class.return_value = mock_client

        # Act: Import app after mocking
        from src.main import app

        try:
            with TestClient(app):
                pass
        except Exception:
            pass  # TestClient may raise due to sys.exit mock

        # Assert: sys.exit was called with exit code 1
        mock_exit.assert_called_once_with(1)


class TestPollingServiceIntegration:
    """Test suite for polling service integration with application startup."""

    @patch("src.main.ACGenerator")
    @patch("src.main.AISettings")
    @patch("src.main.PollingService")
    @patch("src.main.JiraClient")
    @patch("src.main.JiraSettings")
    def test_polling_service_started_when_enabled(
        self,
        mock_settings_class: MagicMock,
        mock_client_class: MagicMock,
        mock_polling_class: MagicMock,
        mock_ai_settings_class: MagicMock,
        mock_ac_generator_class: MagicMock,
    ):
        """Test that polling service is started when polling_enabled is True.

        Given polling_enabled is True and project_key is set
        When the FastAPI app starts
        Then PollingService is instantiated
        And PollingService.start() is called
        And the service is stored in app.state
        """
        # Arrange: Mock JiraSettings with polling enabled
        mock_settings = MagicMock()
        mock_settings.polling_enabled = True
        mock_settings.project_key = "TEST"
        mock_settings.polling_interval_seconds = 60
        mock_settings_class.return_value = mock_settings

        # Arrange: Mock JiraClient with successful validation
        mock_client = AsyncMock()
        mock_client.validate_connection = AsyncMock(return_value=True)
        mock_client.close = AsyncMock()
        mock_client_class.return_value = mock_client

        # Arrange: Mock AISettings with AI enabled
        mock_ai_settings = MagicMock()
        mock_ai_settings.is_enabled = True
        mock_ai_settings.ai_model = "claude-sonnet-4-20250514"
        mock_ai_settings_class.return_value = mock_ai_settings

        # Arrange: Mock ACGenerator
        mock_ac_generator = MagicMock()
        mock_ac_generator_class.return_value = mock_ac_generator

        # Arrange: Mock PollingService
        mock_polling_service = AsyncMock()
        mock_polling_service.start = AsyncMock()
        mock_polling_service.stop = AsyncMock()
        mock_polling_class.return_value = mock_polling_service

        # Act: Import app after mocking
        from src.main import app

        with TestClient(app):
            # Assert: PollingService was instantiated with ac_generator and started
            mock_polling_class.assert_called_once_with(
                mock_client, mock_settings, mock_ac_generator
            )
            mock_polling_service.start.assert_called_once()

            # Assert: PollingService is stored in app.state
            assert hasattr(app.state, "polling_service")
            assert app.state.polling_service is mock_polling_service

    @patch("src.main.ACGenerator")
    @patch("src.main.AISettings")
    @patch("src.main.PollingService")
    @patch("src.main.JiraClient")
    @patch("src.main.JiraSettings")
    def test_polling_service_stopped_on_shutdown(
        self,
        mock_settings_class: MagicMock,
        mock_client_class: MagicMock,
        mock_polling_class: MagicMock,
        mock_ai_settings_class: MagicMock,
        mock_ac_generator_class: MagicMock,
    ):
        """Test that polling service is stopped on application shutdown.

        Given polling service is running
        When the FastAPI app shuts down
        Then PollingService.stop() is called
        """
        # Arrange: Mock JiraSettings with polling enabled
        mock_settings = MagicMock()
        mock_settings.polling_enabled = True
        mock_settings.project_key = "TEST"
        mock_settings.polling_interval_seconds = 60
        mock_settings_class.return_value = mock_settings

        # Arrange: Mock JiraClient with successful validation
        mock_client = AsyncMock()
        mock_client.validate_connection = AsyncMock(return_value=True)
        mock_client.close = AsyncMock()
        mock_client_class.return_value = mock_client

        # Arrange: Mock AISettings with AI enabled
        mock_ai_settings = MagicMock()
        mock_ai_settings.is_enabled = True
        mock_ai_settings.ai_model = "claude-sonnet-4-20250514"
        mock_ai_settings_class.return_value = mock_ai_settings

        # Arrange: Mock ACGenerator
        mock_ac_generator = MagicMock()
        mock_ac_generator_class.return_value = mock_ac_generator

        # Arrange: Mock PollingService
        mock_polling_service = AsyncMock()
        mock_polling_service.start = AsyncMock()
        mock_polling_service.stop = AsyncMock()
        mock_polling_class.return_value = mock_polling_service

        # Act: Import app after mocking, then start and stop
        from src.main import app

        with TestClient(app):
            pass  # App starts and then shuts down

        # Assert: stop() was called on shutdown
        mock_polling_service.stop.assert_called_once()

    @patch("src.main.ACGenerator")
    @patch("src.main.AISettings")
    @patch("src.main.PollingService")
    @patch("src.main.JiraClient")
    @patch("src.main.JiraSettings")
    def test_polling_service_not_started_when_disabled(
        self,
        mock_settings_class: MagicMock,
        mock_client_class: MagicMock,
        mock_polling_class: MagicMock,
        mock_ai_settings_class: MagicMock,
        mock_ac_generator_class: MagicMock,
    ):
        """Test that polling service is NOT started when polling_enabled is False.

        Given polling_enabled is False
        When the FastAPI app starts
        Then PollingService is NOT instantiated
        And app.state.polling_service is None
        """
        # Arrange: Mock JiraSettings with polling disabled
        mock_settings = MagicMock()
        mock_settings.polling_enabled = False
        mock_settings_class.return_value = mock_settings

        # Arrange: Mock JiraClient with successful validation
        mock_client = AsyncMock()
        mock_client.validate_connection = AsyncMock(return_value=True)
        mock_client.close = AsyncMock()
        mock_client_class.return_value = mock_client

        # Arrange: Mock AISettings (AI disabled)
        mock_ai_settings = MagicMock()
        mock_ai_settings.is_enabled = False
        mock_ai_settings_class.return_value = mock_ai_settings

        # Act: Import app after mocking
        from src.main import app

        with TestClient(app):
            # Assert: PollingService was NOT instantiated
            mock_polling_class.assert_not_called()

            # Assert: app.state.polling_service is None
            assert hasattr(app.state, "polling_service")
            assert app.state.polling_service is None

    @patch("src.main.AISettings")
    @patch("src.main.sys.exit")
    @patch("src.main.JiraClient")
    @patch("src.main.JiraSettings")
    def test_app_exits_when_polling_enabled_but_project_key_empty(
        self,
        mock_settings_class: MagicMock,
        mock_client_class: MagicMock,
        mock_exit: MagicMock,
        mock_ai_settings_class: MagicMock,
    ):
        """Test that app exits with error when polling_enabled=True but project_key is empty.

        Given polling_enabled is True
        And project_key is empty
        When the FastAPI app starts
        Then sys.exit(1) is called
        """
        # Arrange: Mock JiraSettings with polling enabled but no project_key
        mock_settings = MagicMock()
        mock_settings.polling_enabled = True
        mock_settings.project_key = ""  # Empty project key
        mock_settings_class.return_value = mock_settings

        # Arrange: Mock JiraClient with successful validation
        mock_client = AsyncMock()
        mock_client.validate_connection = AsyncMock(return_value=True)
        mock_client.close = AsyncMock()
        mock_client_class.return_value = mock_client

        # Arrange: Mock AISettings (disabled to avoid ACGenerator creation)
        mock_ai_settings = MagicMock()
        mock_ai_settings.is_enabled = False
        mock_ai_settings_class.return_value = mock_ai_settings

        # Act: Import app after mocking
        from src.main import app

        try:
            with TestClient(app):
                pass
        except Exception:
            pass  # TestClient may raise due to sys.exit mock

        # Assert: sys.exit was called with exit code 1
        mock_exit.assert_called_once_with(1)

    @patch("src.main.AISettings")
    @patch("src.main.sys.exit")
    @patch("src.main.JiraClient")
    @patch("src.main.JiraSettings")
    def test_app_logs_error_when_project_key_missing(
        self,
        mock_settings_class: MagicMock,
        mock_client_class: MagicMock,
        mock_exit: MagicMock,
        mock_ai_settings_class: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ):
        """Test that an error is logged when polling is enabled but project_key is missing.

        Given polling_enabled is True
        And project_key is empty
        When the FastAPI app starts
        Then an error about missing JIRA_PROJECT_KEY is logged
        """
        # Arrange: Mock JiraSettings with polling enabled but no project_key
        mock_settings = MagicMock()
        mock_settings.polling_enabled = True
        mock_settings.project_key = ""  # Empty project key
        mock_settings_class.return_value = mock_settings

        # Arrange: Mock JiraClient with successful validation
        mock_client = AsyncMock()
        mock_client.validate_connection = AsyncMock(return_value=True)
        mock_client.close = AsyncMock()
        mock_client_class.return_value = mock_client

        # Arrange: Mock AISettings (disabled to avoid ACGenerator creation)
        mock_ai_settings = MagicMock()
        mock_ai_settings.is_enabled = False
        mock_ai_settings_class.return_value = mock_ai_settings

        # Act: Import app after mocking
        from src.main import app

        with caplog.at_level("ERROR"):
            try:
                with TestClient(app):
                    pass
            except Exception:
                pass

        # Assert: Error about missing project key was logged
        assert "JIRA_PROJECT_KEY required when polling is enabled" in caplog.text
