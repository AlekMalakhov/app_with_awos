"""Integration tests for the /health endpoint."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.database import ConversationRepository


@pytest.fixture
def app_with_healthy_state() -> FastAPI:
    """Create a FastAPI app with all components healthy.

    Socket Mode is running and database is accessible.
    """
    from src.main import app, health_check

    mock_socket = MagicMock()
    mock_socket.is_running = True

    app.state.socket_mode_service = mock_socket
    app.state.startup_time = time.monotonic() - 60.0  # 60 seconds ago

    return app


@pytest.fixture
def app_with_disconnected_socket() -> FastAPI:
    """Create a FastAPI app with Socket Mode disconnected."""
    from src.main import app

    mock_socket = MagicMock()
    mock_socket.is_running = False

    app.state.socket_mode_service = mock_socket
    app.state.startup_time = time.monotonic() - 30.0

    return app


@pytest.fixture
def app_with_disabled_socket() -> FastAPI:
    """Create a FastAPI app with Socket Mode disabled (not configured)."""
    from src.main import app

    app.state.socket_mode_service = None
    app.state.startup_time = time.monotonic() - 10.0

    return app


class TestHealthEndpointHealthy:
    """Tests for healthy state where all components are operational."""

    def test_returns_200(self, app_with_healthy_state: FastAPI) -> None:
        """Health endpoint always returns HTTP 200."""
        client = TestClient(app_with_healthy_state, raise_server_exceptions=False)
        response = client.get("/health")

        assert response.status_code == 200

    def test_status_is_healthy(self, app_with_healthy_state: FastAPI) -> None:
        """Overall status is healthy when all components are ok."""
        client = TestClient(app_with_healthy_state, raise_server_exceptions=False)
        response = client.get("/health")
        data = response.json()

        assert data["status"] == "healthy"

    def test_socket_mode_connected(self, app_with_healthy_state: FastAPI) -> None:
        """Socket Mode reports connected when is_running is True."""
        client = TestClient(app_with_healthy_state, raise_server_exceptions=False)
        response = client.get("/health")
        data = response.json()

        assert data["slack_socket_mode"] == "connected"

    def test_database_ok(self, app_with_healthy_state: FastAPI) -> None:
        """Database reports ok when connection succeeds."""
        client = TestClient(app_with_healthy_state, raise_server_exceptions=False)
        response = client.get("/health")
        data = response.json()

        assert data["database"] == "ok"

    def test_uptime_is_positive(self, app_with_healthy_state: FastAPI) -> None:
        """Uptime is a positive number reflecting seconds since startup."""
        client = TestClient(app_with_healthy_state, raise_server_exceptions=False)
        response = client.get("/health")
        data = response.json()

        assert data["uptime_seconds"] > 0

    def test_response_contains_all_fields(
        self, app_with_healthy_state: FastAPI
    ) -> None:
        """Response contains all expected fields."""
        client = TestClient(app_with_healthy_state, raise_server_exceptions=False)
        response = client.get("/health")
        data = response.json()

        assert "status" in data
        assert "slack_socket_mode" in data
        assert "database" in data
        assert "uptime_seconds" in data


class TestHealthEndpointDegradedSocketMode:
    """Tests for degraded state caused by Socket Mode being disconnected."""

    def test_status_is_degraded(
        self, app_with_disconnected_socket: FastAPI
    ) -> None:
        """Overall status is degraded when Socket Mode is disconnected."""
        client = TestClient(
            app_with_disconnected_socket, raise_server_exceptions=False
        )
        response = client.get("/health")
        data = response.json()

        assert data["status"] == "degraded"

    def test_socket_mode_disconnected(
        self, app_with_disconnected_socket: FastAPI
    ) -> None:
        """Socket Mode reports disconnected when is_running is False."""
        client = TestClient(
            app_with_disconnected_socket, raise_server_exceptions=False
        )
        response = client.get("/health")
        data = response.json()

        assert data["slack_socket_mode"] == "disconnected"

    def test_still_returns_200(
        self, app_with_disconnected_socket: FastAPI
    ) -> None:
        """Health endpoint returns 200 even in degraded state."""
        client = TestClient(
            app_with_disconnected_socket, raise_server_exceptions=False
        )
        response = client.get("/health")

        assert response.status_code == 200


class TestHealthEndpointSocketModeDisabled:
    """Tests for state where Socket Mode is not configured."""

    def test_status_is_healthy(
        self, app_with_disabled_socket: FastAPI
    ) -> None:
        """Overall status is healthy when Socket Mode is disabled (not an error)."""
        client = TestClient(
            app_with_disabled_socket, raise_server_exceptions=False
        )
        response = client.get("/health")
        data = response.json()

        assert data["status"] == "healthy"

    def test_socket_mode_disabled(
        self, app_with_disabled_socket: FastAPI
    ) -> None:
        """Socket Mode reports disabled when service is None."""
        client = TestClient(
            app_with_disabled_socket, raise_server_exceptions=False
        )
        response = client.get("/health")
        data = response.json()

        assert data["slack_socket_mode"] == "disabled"


class TestHealthEndpointDatabaseError:
    """Tests for degraded state caused by database connectivity issues."""

    def test_status_is_degraded_on_db_error(
        self, app_with_healthy_state: FastAPI
    ) -> None:
        """Overall status is degraded when database check fails."""
        with patch(
            "src.main.ConversationRepository",
            side_effect=Exception("DB connection failed"),
        ):
            client = TestClient(
                app_with_healthy_state, raise_server_exceptions=False
            )
            response = client.get("/health")
            data = response.json()

        assert data["status"] == "degraded"
        assert data["database"] == "error"

    def test_database_error_with_socket_connected(
        self, app_with_healthy_state: FastAPI
    ) -> None:
        """Socket Mode still reports connected even when DB is down."""
        with patch(
            "src.main.ConversationRepository",
            side_effect=Exception("DB connection failed"),
        ):
            client = TestClient(
                app_with_healthy_state, raise_server_exceptions=False
            )
            response = client.get("/health")
            data = response.json()

        assert data["slack_socket_mode"] == "connected"
        assert data["database"] == "error"

    def test_database_error_on_query(
        self, app_with_healthy_state: FastAPI
    ) -> None:
        """Database reports error when the query itself fails."""
        mock_repo = MagicMock(spec=ConversationRepository)
        mock_repo.get_by_id.side_effect = Exception("Query failed")

        with patch(
            "src.main.ConversationRepository",
            return_value=mock_repo,
        ):
            client = TestClient(
                app_with_healthy_state, raise_server_exceptions=False
            )
            response = client.get("/health")
            data = response.json()

        assert data["status"] == "degraded"
        assert data["database"] == "error"

    def test_still_returns_200_on_db_error(
        self, app_with_healthy_state: FastAPI
    ) -> None:
        """Health endpoint returns 200 even when database is down."""
        with patch(
            "src.main.ConversationRepository",
            side_effect=Exception("DB connection failed"),
        ):
            client = TestClient(
                app_with_healthy_state, raise_server_exceptions=False
            )
            response = client.get("/health")

        assert response.status_code == 200


class TestHealthEndpointUptime:
    """Tests for uptime tracking."""

    def test_uptime_reflects_startup_time(
        self, app_with_healthy_state: FastAPI
    ) -> None:
        """Uptime value is approximately correct based on startup_time.

        The fixture sets startup 60 seconds ago, so uptime should be >= 60.
        """
        client = TestClient(app_with_healthy_state, raise_server_exceptions=False)
        response = client.get("/health")
        data = response.json()

        assert data["uptime_seconds"] >= 59.0

    def test_uptime_zero_when_no_startup_time(
        self, app_with_healthy_state: FastAPI
    ) -> None:
        """Uptime defaults to 0.0 if startup_time is not set."""
        # Remove startup_time to simulate edge case
        if hasattr(app_with_healthy_state.state, "startup_time"):
            del app_with_healthy_state.state.startup_time

        client = TestClient(app_with_healthy_state, raise_server_exceptions=False)
        response = client.get("/health")
        data = response.json()

        assert data["uptime_seconds"] == 0.0
