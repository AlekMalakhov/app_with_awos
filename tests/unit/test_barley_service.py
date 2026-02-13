"""Unit tests for BarleyEnrichmentService."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.barley.config import BarleySettings
from src.barley.models import EnrichmentResult
from src.barley.service import BarleyEnrichmentService


@pytest.fixture
def mock_barley_settings() -> MagicMock:
    """Create a mock BarleySettings with Barley enabled by default."""
    settings = MagicMock(spec=BarleySettings)
    settings.enabled = True
    settings.project_name = "IGAL"
    return settings


@pytest.fixture
def mock_barley_client() -> MagicMock:
    """Create a mock BarleyClient for unit testing."""
    mock = MagicMock()
    mock.query = AsyncMock(return_value="Relevant project context from Barley")
    return mock


@pytest.fixture
def mock_ac_generator() -> MagicMock:
    """Create a mock ACGenerator for topic extraction."""
    mock = MagicMock()
    mock.extract_topics = AsyncMock(
        return_value="authentication, OAuth2, user login flow"
    )
    return mock


@pytest.fixture
def enrichment_service(
    mock_barley_client: MagicMock,
    mock_ac_generator: MagicMock,
    mock_barley_settings: MagicMock,
) -> BarleyEnrichmentService:
    """Create a BarleyEnrichmentService with mocked dependencies."""
    return BarleyEnrichmentService(
        barley_client=mock_barley_client,
        ac_generator=mock_ac_generator,
        settings=mock_barley_settings,
    )


class TestBarleyEnrichmentServiceEnrich:
    """Test suite for BarleyEnrichmentService.enrich() method."""

    @pytest.mark.asyncio
    async def test_enrich_success_returns_topics_and_context(
        self,
        enrichment_service: BarleyEnrichmentService,
        mock_ac_generator: MagicMock,
        mock_barley_client: MagicMock,
    ) -> None:
        """Verify enrich() returns EnrichmentResult with topics and context on success."""
        result = await enrichment_service.enrich(
            summary="Add OAuth2 login",
            description="As a user, I want to log in with OAuth2.",
        )

        assert isinstance(result, EnrichmentResult)
        assert result.topics_extracted == "authentication, OAuth2, user login flow"
        assert result.barley_context == "Relevant project context from Barley"

        mock_ac_generator.extract_topics.assert_called_once_with(
            "Add OAuth2 login",
            "As a user, I want to log in with OAuth2.",
        )
        mock_barley_client.query.assert_called_once()

    @pytest.mark.asyncio
    async def test_enrich_barley_failure_returns_topics_with_none_context(
        self,
        enrichment_service: BarleyEnrichmentService,
        mock_ac_generator: MagicMock,
        mock_barley_client: MagicMock,
    ) -> None:
        """Verify enrich() returns topics but None context when Barley query returns None."""
        mock_barley_client.query = AsyncMock(return_value=None)

        result = await enrichment_service.enrich(
            summary="Add OAuth2 login",
            description="As a user, I want to log in with OAuth2.",
        )

        assert isinstance(result, EnrichmentResult)
        assert result.topics_extracted == "authentication, OAuth2, user login flow"
        assert result.barley_context is None

        mock_ac_generator.extract_topics.assert_called_once()
        mock_barley_client.query.assert_called_once()

    @pytest.mark.asyncio
    async def test_enrich_disabled_returns_empty_result(
        self,
        mock_barley_client: MagicMock,
        mock_ac_generator: MagicMock,
        mock_barley_settings: MagicMock,
    ) -> None:
        """Verify enrich() returns empty EnrichmentResult when Barley is disabled."""
        mock_barley_settings.enabled = False

        service = BarleyEnrichmentService(
            barley_client=mock_barley_client,
            ac_generator=mock_ac_generator,
            settings=mock_barley_settings,
        )

        result = await service.enrich(
            summary="Add OAuth2 login",
            description="As a user, I want to log in with OAuth2.",
        )

        assert isinstance(result, EnrichmentResult)
        assert result.barley_context is None
        assert result.topics_extracted == ""

        # Neither dependency should have been called
        mock_ac_generator.extract_topics.assert_not_called()
        mock_barley_client.query.assert_not_called()

    @pytest.mark.asyncio
    async def test_enrich_extract_topics_fallback_still_queries_barley(
        self,
        enrichment_service: BarleyEnrichmentService,
        mock_ac_generator: MagicMock,
        mock_barley_client: MagicMock,
    ) -> None:
        """Verify fallback topic text (raw description) is still sent to Barley."""
        raw_description = "As a user, I want to log in with OAuth2."
        mock_ac_generator.extract_topics = AsyncMock(return_value=raw_description)

        result = await enrichment_service.enrich(
            summary="Add OAuth2 login",
            description=raw_description,
        )

        assert isinstance(result, EnrichmentResult)
        assert result.topics_extracted == raw_description
        assert result.barley_context == "Relevant project context from Barley"

        # Barley should have been called with a prompt containing the summary
        mock_barley_client.query.assert_called_once()
        call_args = mock_barley_client.query.call_args[0][0]
        assert "Add OAuth2 login" in call_args
