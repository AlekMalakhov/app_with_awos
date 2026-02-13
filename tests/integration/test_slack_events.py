"""Integration tests for Slack Events API webhook endpoint."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.slack.config import SlackSettings


@pytest.fixture
def slack_settings() -> SlackSettings:
    """Create SlackSettings with test values."""
    return SlackSettings(
        bot_token="xoxb-test-token-12345",
        app_token="xapp-test-token",
        signing_secret="test-signing-secret-abc123",
        max_retries=1,
    )


@pytest.fixture
def test_client(slack_settings: SlackSettings) -> TestClient:
    """Create a test client with mocked Slack settings.

    We need to patch the settings before importing the app to ensure
    the router uses our test settings.
    """
    with patch("src.slack.events._get_slack_settings", return_value=slack_settings):
        # Import here to avoid issues with module-level app state
        from fastapi import FastAPI

        from src.slack.events import slack_router

        # Create a minimal app just for testing the router
        app = FastAPI()
        app.include_router(slack_router, prefix="/slack")

        yield TestClient(app)


def generate_slack_signature(
    signing_secret: str,
    timestamp: str,
    body: str,
) -> str:
    """Generate a valid Slack signature for testing.

    Args:
        signing_secret: The Slack signing secret.
        timestamp: The request timestamp.
        body: The request body as a string.

    Returns:
        The computed signature in Slack's format (v0=...).
    """
    sig_basestring = f"v0:{timestamp}:{body}"
    return "v0=" + hmac.new(
        signing_secret.encode(),
        sig_basestring.encode(),
        hashlib.sha256,
    ).hexdigest()


class TestURLVerification:
    """Test suite for Slack URL verification challenge."""

    def test_url_verification_returns_challenge(
        self, test_client: TestClient
    ):
        """Test that URL verification request returns the challenge value."""
        payload = {
            "type": "url_verification",
            "challenge": "test-challenge-abc123",
            "token": "deprecated-token",
        }

        response = test_client.post(
            "/slack/events",
            json=payload,
        )

        assert response.status_code == 200
        assert response.json() == {"challenge": "test-challenge-abc123"}

    def test_url_verification_without_signature_headers(
        self, test_client: TestClient
    ):
        """Test that URL verification works without signature headers.

        Slack's URL verification doesn't require signature verification
        since it's a one-time setup request.
        """
        payload = {
            "type": "url_verification",
            "challenge": "another-challenge-xyz",
            "token": "deprecated-token",
        }

        response = test_client.post(
            "/slack/events",
            json=payload,
        )

        assert response.status_code == 200
        assert response.json()["challenge"] == "another-challenge-xyz"


class TestSignatureVerification:
    """Test suite for Slack request signature verification."""

    def test_valid_signature_passes(
        self, test_client: TestClient, slack_settings: SlackSettings
    ):
        """Test that a request with a valid signature is accepted."""
        timestamp = str(int(time.time()))
        payload = {
            "type": "event_callback",
            "event": {
                "type": "message",
                "user": "U1234567890",
                "channel": "D1234567890",
                "text": "Hello, bot!",
                "ts": "1234567890.123456",
            },
            "event_id": "Ev1234567890",
            "token": "deprecated-token",
        }
        body = json.dumps(payload)
        signature = generate_slack_signature(
            slack_settings.signing_secret,
            timestamp,
            body,
        )

        response = test_client.post(
            "/slack/events",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Slack-Signature": signature,
                "X-Slack-Request-Timestamp": timestamp,
            },
        )

        assert response.status_code == 200
        assert response.json() == {"ok": True}

    def test_invalid_signature_returns_401(
        self, test_client: TestClient
    ):
        """Test that a request with an invalid signature returns 401."""
        timestamp = str(int(time.time()))
        payload = {
            "type": "event_callback",
            "event": {
                "type": "message",
                "user": "U1234567890",
                "channel": "D1234567890",
                "text": "Hello, bot!",
                "ts": "1234567890.123456",
            },
            "event_id": "Ev1234567890",
            "token": "deprecated-token",
        }
        body = json.dumps(payload)

        response = test_client.post(
            "/slack/events",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Slack-Signature": "v0=invalid_signature_abc123",
                "X-Slack-Request-Timestamp": timestamp,
            },
        )

        assert response.status_code == 401
        assert "Invalid Slack signature" in response.json()["detail"]

    def test_missing_signature_header_returns_401(
        self, test_client: TestClient
    ):
        """Test that a request without signature header returns 401."""
        timestamp = str(int(time.time()))
        payload = {
            "type": "event_callback",
            "event": {
                "type": "message",
                "user": "U1234567890",
                "channel": "D1234567890",
                "text": "Hello, bot!",
                "ts": "1234567890.123456",
            },
            "event_id": "Ev1234567890",
            "token": "deprecated-token",
        }

        response = test_client.post(
            "/slack/events",
            json=payload,
            headers={
                "X-Slack-Request-Timestamp": timestamp,
            },
        )

        assert response.status_code == 401
        assert "Missing Slack signature headers" in response.json()["detail"]

    def test_missing_timestamp_header_returns_401(
        self, test_client: TestClient, slack_settings: SlackSettings
    ):
        """Test that a request without timestamp header returns 401."""
        payload = {
            "type": "event_callback",
            "event": {
                "type": "message",
                "user": "U1234567890",
                "channel": "D1234567890",
                "text": "Hello, bot!",
                "ts": "1234567890.123456",
            },
            "event_id": "Ev1234567890",
            "token": "deprecated-token",
        }
        body = json.dumps(payload)
        # Generate signature with a timestamp but don't send the header
        signature = generate_slack_signature(
            slack_settings.signing_secret,
            str(int(time.time())),
            body,
        )

        response = test_client.post(
            "/slack/events",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Slack-Signature": signature,
            },
        )

        assert response.status_code == 401
        assert "Missing Slack signature headers" in response.json()["detail"]

    def test_old_timestamp_returns_401(
        self, test_client: TestClient, slack_settings: SlackSettings
    ):
        """Test that a request with an old timestamp (replay attack) returns 401."""
        # Timestamp from 10 minutes ago (beyond 5 minute window)
        old_timestamp = str(int(time.time()) - 600)
        payload = {
            "type": "event_callback",
            "event": {
                "type": "message",
                "user": "U1234567890",
                "channel": "D1234567890",
                "text": "Hello, bot!",
                "ts": "1234567890.123456",
            },
            "event_id": "Ev1234567890",
            "token": "deprecated-token",
        }
        body = json.dumps(payload)
        signature = generate_slack_signature(
            slack_settings.signing_secret,
            old_timestamp,
            body,
        )

        response = test_client.post(
            "/slack/events",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Slack-Signature": signature,
                "X-Slack-Request-Timestamp": old_timestamp,
            },
        )

        assert response.status_code == 401
        assert "Invalid Slack signature" in response.json()["detail"]


class TestMessageEventHandling:
    """Test suite for handling message events."""

    def test_message_event_returns_200(
        self, test_client: TestClient, slack_settings: SlackSettings
    ):
        """Test that a valid message event returns 200 OK."""
        timestamp = str(int(time.time()))
        payload = {
            "type": "event_callback",
            "event": {
                "type": "message",
                "user": "U1234567890",
                "channel": "D1234567890",
                "text": "regenerate ACs for PROJ-123",
                "ts": "1234567890.123456",
            },
            "event_id": "Ev1234567890",
            "token": "deprecated-token",
        }
        body = json.dumps(payload)
        signature = generate_slack_signature(
            slack_settings.signing_secret,
            timestamp,
            body,
        )

        response = test_client.post(
            "/slack/events",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Slack-Signature": signature,
                "X-Slack-Request-Timestamp": timestamp,
            },
        )

        assert response.status_code == 200
        assert response.json() == {"ok": True}

    def test_message_event_with_no_text(
        self, test_client: TestClient, slack_settings: SlackSettings
    ):
        """Test that a message event without text is handled gracefully."""
        timestamp = str(int(time.time()))
        payload = {
            "type": "event_callback",
            "event": {
                "type": "message",
                "user": "U1234567890",
                "channel": "D1234567890",
                "ts": "1234567890.123456",
            },
            "event_id": "Ev1234567890",
            "token": "deprecated-token",
        }
        body = json.dumps(payload)
        signature = generate_slack_signature(
            slack_settings.signing_secret,
            timestamp,
            body,
        )

        response = test_client.post(
            "/slack/events",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Slack-Signature": signature,
                "X-Slack-Request-Timestamp": timestamp,
            },
        )

        assert response.status_code == 200
        assert response.json() == {"ok": True}


class TestBotMessageIgnoring:
    """Test suite for ignoring bot messages to prevent loops."""

    def test_message_with_bot_id_is_ignored(
        self, test_client: TestClient, slack_settings: SlackSettings
    ):
        """Test that messages with bot_id are ignored and return 200."""
        timestamp = str(int(time.time()))
        payload = {
            "type": "event_callback",
            "event": {
                "type": "message",
                "bot_id": "B1234567890",
                "channel": "D1234567890",
                "text": "I am a bot message",
                "ts": "1234567890.123456",
            },
            "event_id": "Ev1234567890",
            "token": "deprecated-token",
        }
        body = json.dumps(payload)
        signature = generate_slack_signature(
            slack_settings.signing_secret,
            timestamp,
            body,
        )

        response = test_client.post(
            "/slack/events",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Slack-Signature": signature,
                "X-Slack-Request-Timestamp": timestamp,
            },
        )

        assert response.status_code == 200
        assert response.json() == {"ok": True}

    def test_message_with_subtype_is_ignored(
        self, test_client: TestClient, slack_settings: SlackSettings
    ):
        """Test that messages with subtype (e.g., message_changed) are ignored."""
        timestamp = str(int(time.time()))
        payload = {
            "type": "event_callback",
            "event": {
                "type": "message",
                "subtype": "message_changed",
                "user": "U1234567890",
                "channel": "D1234567890",
                "text": "Edited message",
                "ts": "1234567890.123456",
            },
            "event_id": "Ev1234567890",
            "token": "deprecated-token",
        }
        body = json.dumps(payload)
        signature = generate_slack_signature(
            slack_settings.signing_secret,
            timestamp,
            body,
        )

        response = test_client.post(
            "/slack/events",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Slack-Signature": signature,
                "X-Slack-Request-Timestamp": timestamp,
            },
        )

        assert response.status_code == 200
        assert response.json() == {"ok": True}

    def test_message_with_bot_message_subtype_is_ignored(
        self, test_client: TestClient, slack_settings: SlackSettings
    ):
        """Test that messages with bot_message subtype are ignored."""
        timestamp = str(int(time.time()))
        payload = {
            "type": "event_callback",
            "event": {
                "type": "message",
                "subtype": "bot_message",
                "channel": "D1234567890",
                "text": "Bot message via subtype",
                "ts": "1234567890.123456",
            },
            "event_id": "Ev1234567890",
            "token": "deprecated-token",
        }
        body = json.dumps(payload)
        signature = generate_slack_signature(
            slack_settings.signing_secret,
            timestamp,
            body,
        )

        response = test_client.post(
            "/slack/events",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Slack-Signature": signature,
                "X-Slack-Request-Timestamp": timestamp,
            },
        )

        assert response.status_code == 200
        assert response.json() == {"ok": True}


class TestNonMessageEvents:
    """Test suite for handling non-message event types."""

    def test_non_message_event_returns_200(
        self, test_client: TestClient, slack_settings: SlackSettings
    ):
        """Test that non-message events are handled and return 200."""
        timestamp = str(int(time.time()))
        payload = {
            "type": "event_callback",
            "event": {
                "type": "app_mention",
                "user": "U1234567890",
                "channel": "C1234567890",
                "text": "<@U0LAN0Z89> Hello bot!",
                "ts": "1234567890.123456",
            },
            "event_id": "Ev1234567890",
            "token": "deprecated-token",
        }
        body = json.dumps(payload)
        signature = generate_slack_signature(
            slack_settings.signing_secret,
            timestamp,
            body,
        )

        response = test_client.post(
            "/slack/events",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Slack-Signature": signature,
                "X-Slack-Request-Timestamp": timestamp,
            },
        )

        assert response.status_code == 200
        assert response.json() == {"ok": True}
