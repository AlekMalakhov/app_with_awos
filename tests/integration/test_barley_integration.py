"""Integration tests for Barley AI Consultation graceful degradation.

These tests verify that the polling pipeline degrades gracefully when
Barley enrichment is disabled or unavailable. They do NOT require real
Barley, Jira, or Anthropic credentials -- external dependencies are
mocked while the Barley layer uses real settings and (for Test 2) a
real BarleyClient pointed at an unreachable host.

Run these tests with:
    pytest tests/integration/test_barley_integration.py -v
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.ai.models import ACGenerationResult
from src.barley.client import BarleyClient
from src.barley.config import BarleySettings
from src.barley.service import BarleyEnrichmentService
from src.jira import JiraSettings, TicketData
from src.jira.ac_formatter import append_acs_to_description
from src.polling.service import PollingService


pytestmark = [pytest.mark.integration]


# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

SAMPLE_TICKET = TicketData(
    key="TEST-101",
    summary="Add user authentication via OAuth2",
    description=(
        "As a user I want to log in with OAuth2 so that I can access "
        "the application securely. The feature should support Google "
        "and GitHub as identity providers."
    ),
    description_adf={
        "version": 1,
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "As a user I want to log in with OAuth2 so that "
                            "I can access the application securely."
                        ),
                    }
                ],
            }
        ],
    },
    issue_type="Story",
)

GENERATED_ACS = [
    "Given a user on the login page, when they click 'Sign in with Google', "
    "then they are redirected to Google's OAuth2 consent screen.",
    "Given a user completes OAuth2 authentication with GitHub, when they are "
    "redirected back, then a valid session is created.",
    "Given an OAuth2 token has expired, when the user makes a request, "
    "then the system attempts a silent token refresh before prompting re-login.",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_jira_settings() -> JiraSettings:
    """Create minimal JiraSettings without reading environment variables."""
    return JiraSettings(
        base_url="https://fake-jira.atlassian.net",
        user_email="test@example.com",
        api_token="fake-token",
        project_key="TEST",
        polling_enabled=True,
        polling_interval_seconds=60,
    )


def _build_mock_jira_client() -> AsyncMock:
    """Create a fully-mocked async JiraClient.

    Mocks the subset of JiraClient methods invoked by PollingService._process_ticket:
    - search_tickets: returns a single sample ticket
    - get_ticket: returns the same ticket (with description_adf)
    - update_description: succeeds
    - add_label: succeeds
    - add_comment: succeeds
    """
    mock = AsyncMock()
    mock.search_tickets = AsyncMock(return_value=[SAMPLE_TICKET])
    mock.get_ticket = AsyncMock(return_value=SAMPLE_TICKET)
    mock.update_description = AsyncMock(return_value=True)
    mock.add_label = AsyncMock(return_value=True)
    mock.add_comment = AsyncMock(return_value=True)
    mock.close = AsyncMock()
    return mock


def _build_mock_ac_generator() -> MagicMock:
    """Create a mock ACGenerator that returns pre-canned ACs.

    Both ``generate`` and ``extract_topics`` are async, so they use AsyncMock.
    ``is_enabled`` is a synchronous property that returns True.
    """
    mock = MagicMock()
    mock.is_enabled = True
    mock.generate = AsyncMock(return_value=ACGenerationResult(
        acceptance_criteria=GENERATED_ACS,
        confidence_score=0.85,
        confidence_gaps=[],
        sufficient_information=True,
    ))
    mock.extract_topics = AsyncMock(
        return_value="OAuth2, authentication, Google, GitHub identity providers"
    )
    return mock


# ---------------------------------------------------------------------------
# Test 1 -- Barley disabled (BARLEY_ENABLED=false)
# ---------------------------------------------------------------------------


class TestBarleyDisabledPipeline:
    """Verify the polling pipeline works correctly when Barley is disabled."""

    @pytest.mark.asyncio
    async def test_pipeline_completes_without_barley_calls(self) -> None:
        """When BARLEY_ENABLED=false the pipeline should:

        - Generate ACs normally from the ticket description alone
        - Make NO calls to Barley API (neither extract_topics nor query)
        - Post NO Barley context comment to Jira
        - Complete the full pipeline without errors
        """
        # -- Arrange ----------------------------------------------------------
        jira_settings = _build_jira_settings()
        mock_jira = _build_mock_jira_client()
        mock_generator = _build_mock_ac_generator()

        barley_settings = BarleySettings(
            enabled=False,
            api_url="https://should-not-be-called.example.com",
            api_token="unused-token",
        )

        # Use a real BarleyEnrichmentService with a mock BarleyClient to
        # verify that neither the client nor the topic extractor is invoked.
        mock_barley_client = MagicMock()
        mock_barley_client.query = AsyncMock()

        enrichment_service = BarleyEnrichmentService(
            barley_client=mock_barley_client,
            ac_generator=mock_generator,
            settings=barley_settings,
        )

        service = PollingService(
            jira_client=mock_jira,
            settings=jira_settings,
            ac_generator=mock_generator,
            enrichment_service=enrichment_service,
        )

        # -- Act --------------------------------------------------------------
        result = await service._process_ticket(SAMPLE_TICKET)

        # -- Assert -----------------------------------------------------------
        # Pipeline completed successfully
        assert result is True, "Pipeline should complete successfully"

        # ACs were generated from the original description (no enrichment)
        mock_generator.generate.assert_called_once()
        call_kwargs = mock_generator.generate.call_args
        description_used = call_kwargs.kwargs.get(
            "description", call_kwargs.args[1] if len(call_kwargs.args) > 1 else None
        )
        # The description passed to generate should be the ORIGINAL one
        # (no "Additional Context from Barley" appended)
        assert "Additional Context from Barley" not in (description_used or ""), (
            "Description should NOT contain Barley context when Barley is disabled"
        )

        # Barley API was never contacted
        mock_barley_client.query.assert_not_called()

        # Topic extraction was never invoked via the enrichment path
        # (the generator's extract_topics should not be called by enrichment)
        mock_generator.extract_topics.assert_not_called()

        # No Barley context comment was posted to Jira
        mock_jira.add_comment.assert_not_called()

        # The ticket was labelled as processed
        mock_jira.add_label.assert_called_once_with("TEST-101", "ac-generated")


# ---------------------------------------------------------------------------
# Test 2 -- Barley API unreachable (invalid URL)
# ---------------------------------------------------------------------------


class TestBarleyUnreachablePipeline:
    """Verify the polling pipeline degrades gracefully when Barley is unreachable."""

    @pytest.mark.asyncio
    async def test_pipeline_completes_when_barley_unreachable(self) -> None:
        """When Barley API points to an unreachable host the pipeline should:

        - Skip Barley enrichment gracefully (no exception propagated)
        - Generate ACs from the ticket description alone
        - NOT block or delay the pipeline beyond the short connect timeout
        - Complete without raising exceptions
        """
        # -- Arrange ----------------------------------------------------------
        jira_settings = _build_jira_settings()
        mock_jira = _build_mock_jira_client()
        mock_generator = _build_mock_ac_generator()

        barley_settings = BarleySettings(
            enabled=True,
            api_url="http://localhost:1",  # unreachable port
            api_token="unused-token",
            timeout=2,  # short timeout so test runs fast
        )

        # Use a REAL BarleyClient so the actual httpx connection attempt
        # hits localhost:1 and fails with a connection error.
        real_barley_client = BarleyClient(barley_settings)

        enrichment_service = BarleyEnrichmentService(
            barley_client=real_barley_client,
            ac_generator=mock_generator,
            settings=barley_settings,
        )

        service = PollingService(
            jira_client=mock_jira,
            settings=jira_settings,
            ac_generator=mock_generator,
            enrichment_service=enrichment_service,
        )

        # -- Act --------------------------------------------------------------
        try:
            result = await service._process_ticket(SAMPLE_TICKET)
        finally:
            await real_barley_client.close()

        # -- Assert -----------------------------------------------------------
        # Pipeline completed successfully despite Barley failure
        assert result is True, (
            "Pipeline should complete successfully even when Barley is unreachable"
        )

        # ACs were still generated from the original description
        mock_generator.generate.assert_called_once()
        call_kwargs = mock_generator.generate.call_args
        description_used = call_kwargs.kwargs.get(
            "description", call_kwargs.args[1] if len(call_kwargs.args) > 1 else None
        )
        # Barley context should NOT appear because the call failed
        assert "Additional Context from Barley" not in (description_used or ""), (
            "Description should NOT contain Barley context when Barley is unreachable"
        )

        # No Barley context comment posted (enrichment failed gracefully)
        mock_jira.add_comment.assert_not_called()

        # Ticket was updated with ACs and labelled
        mock_jira.update_description.assert_called_once()
        mock_jira.add_label.assert_called_once_with("TEST-101", "ac-generated")
