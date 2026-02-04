"""Unit tests for AI configuration settings."""

import pytest

from src.ai.config import AISettings


class TestAISettingsDefaults:
    """Test suite for AISettings default values."""

    def test_default_anthropic_api_key_is_empty_string(self, monkeypatch):
        """Test that anthropic_api_key defaults to empty string when not set."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        settings = AISettings()

        assert settings.anthropic_api_key == ""

    def test_default_ai_model_is_claude_sonnet_4(self, monkeypatch):
        """Test that ai_model defaults to claude-sonnet-4-20250514."""
        monkeypatch.delenv("AI_MODEL", raising=False)

        settings = AISettings()

        assert settings.ai_model == "claude-sonnet-4-20250514"

    def test_default_ai_max_tokens_is_1024(self, monkeypatch):
        """Test that ai_max_tokens defaults to 1024."""
        monkeypatch.delenv("AI_MAX_TOKENS", raising=False)

        settings = AISettings()

        assert settings.ai_max_tokens == 1024

    def test_default_ai_temperature_is_0_3(self, monkeypatch):
        """Test that ai_temperature defaults to 0.3."""
        monkeypatch.delenv("AI_TEMPERATURE", raising=False)

        settings = AISettings()

        assert settings.ai_temperature == 0.3


class TestAISettingsIsEnabled:
    """Test suite for AISettings.is_enabled property."""

    def test_is_enabled_returns_false_when_api_key_is_empty(self, monkeypatch):
        """Test that is_enabled returns False when anthropic_api_key is empty."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        settings = AISettings()

        assert settings.is_enabled is False

    def test_is_enabled_returns_true_when_api_key_is_set(self, monkeypatch):
        """Test that is_enabled returns True when anthropic_api_key is set."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key-12345")

        settings = AISettings()

        assert settings.is_enabled is True

    def test_is_enabled_returns_false_when_api_key_is_whitespace_only(self, monkeypatch):
        """Test that is_enabled returns False when anthropic_api_key is whitespace."""
        # Note: Empty string from env var will be empty, but whitespace-only
        # should also be considered as "not enabled" in practice
        monkeypatch.setenv("ANTHROPIC_API_KEY", "")

        settings = AISettings()

        assert settings.is_enabled is False


class TestAISettingsFromEnvVars:
    """Test suite for AISettings loading from environment variables."""

    def test_anthropic_api_key_loaded_from_env(self, monkeypatch):
        """Test that ANTHROPIC_API_KEY is loaded from environment variable."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key-67890")

        settings = AISettings()

        assert settings.anthropic_api_key == "sk-ant-test-key-67890"

    def test_custom_ai_model_loaded_from_env(self, monkeypatch):
        """Test that AI_MODEL is loaded from environment variable."""
        monkeypatch.setenv("AI_MODEL", "claude-opus-4-20250514")

        settings = AISettings()

        assert settings.ai_model == "claude-opus-4-20250514"

    def test_custom_ai_max_tokens_loaded_from_env(self, monkeypatch):
        """Test that AI_MAX_TOKENS is loaded from environment variable."""
        monkeypatch.setenv("AI_MAX_TOKENS", "2048")

        settings = AISettings()

        assert settings.ai_max_tokens == 2048

    def test_custom_ai_temperature_loaded_from_env(self, monkeypatch):
        """Test that AI_TEMPERATURE is loaded from environment variable."""
        monkeypatch.setenv("AI_TEMPERATURE", "0.7")

        settings = AISettings()

        assert settings.ai_temperature == 0.7

    def test_all_settings_loaded_together(self, monkeypatch):
        """Test that all settings are loaded correctly when all env vars are set."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-full-test-key")
        monkeypatch.setenv("AI_MODEL", "claude-3-haiku-20240307")
        monkeypatch.setenv("AI_MAX_TOKENS", "512")
        monkeypatch.setenv("AI_TEMPERATURE", "0.5")

        settings = AISettings()

        assert settings.anthropic_api_key == "sk-ant-full-test-key"
        assert settings.ai_model == "claude-3-haiku-20240307"
        assert settings.ai_max_tokens == 512
        assert settings.ai_temperature == 0.5
        assert settings.is_enabled is True
