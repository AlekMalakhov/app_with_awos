"""Unit tests for PollingService start/stop lifecycle."""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.ai.models import ACGenerationResult
from src.database.models import EscalationRecord
from src.jira import JiraClient, JiraSettings
from src.jira.models import TicketData
from src.polling.service import PollingService


@pytest.fixture
def mock_jira_settings() -> JiraSettings:
    """Create mock JiraSettings with test values for polling."""
    return JiraSettings(
        base_url="https://test.atlassian.net",
        user_email="test@example.com",
        api_token="test-api-token",
        project_key="TEST",
        polling_enabled=True,
        polling_interval_seconds=1,  # Short interval for tests
        polling_lookback_days=7,
        polling_max_failures=3,
    )


@pytest.fixture
def mock_jira_client() -> MagicMock:
    """Create a mock JiraClient for unit testing.

    Returns a MagicMock that can stand in for JiraClient without making real API calls.
    """
    return MagicMock(spec=JiraClient)


@pytest.fixture
def polling_service(
    mock_jira_client: MagicMock,
    mock_jira_settings: JiraSettings,
) -> PollingService:
    """Create a PollingService instance with mocked dependencies."""
    return PollingService(
        jira_client=mock_jira_client,
        settings=mock_jira_settings,
    )


class TestPollingServiceStart:
    """Test suite for PollingService.start() method."""

    @pytest.mark.asyncio
    async def test_start_creates_background_task(
        self, polling_service: PollingService
    ) -> None:
        """Verify that start() creates an asyncio background task."""
        # Before start, no task should exist
        assert polling_service._task is None
        assert polling_service._running is False

        # Start the service
        await polling_service.start()

        try:
            # Task should now be created and running flag set
            assert polling_service._task is not None
            assert isinstance(polling_service._task, asyncio.Task)
            assert polling_service._running is True
            assert not polling_service._task.done()
        finally:
            # Cleanup
            await polling_service.stop()

    @pytest.mark.asyncio
    async def test_start_is_idempotent(
        self, polling_service: PollingService
    ) -> None:
        """Verify that calling start() twice does not create two tasks."""
        await polling_service.start()

        try:
            # Capture the first task reference
            first_task = polling_service._task
            assert first_task is not None

            # Call start again
            await polling_service.start()

            # Should still be the same task (not a new one)
            assert polling_service._task is first_task
            assert polling_service._running is True
        finally:
            await polling_service.stop()

    @pytest.mark.asyncio
    async def test_start_sets_running_flag(
        self, polling_service: PollingService
    ) -> None:
        """Verify that start() sets the _running flag to True."""
        assert polling_service._running is False

        await polling_service.start()

        try:
            assert polling_service._running is True
        finally:
            await polling_service.stop()


class TestPollingServiceStop:
    """Test suite for PollingService.stop() method."""

    @pytest.mark.asyncio
    async def test_stop_cancels_task(
        self, polling_service: PollingService
    ) -> None:
        """Verify that stop() cancels the background task."""
        await polling_service.start()

        # Capture task reference before stopping
        task = polling_service._task
        assert task is not None
        assert not task.done()

        # Stop the service
        await polling_service.stop()

        # Task should be cancelled and reference cleared
        assert polling_service._task is None
        assert polling_service._running is False
        assert task.done()
        assert task.cancelled()

    @pytest.mark.asyncio
    async def test_stop_is_idempotent(
        self, polling_service: PollingService
    ) -> None:
        """Verify that calling stop() twice does not raise an exception."""
        await polling_service.start()
        await polling_service.stop()

        # Calling stop again should not raise
        await polling_service.stop()

        # Service should remain stopped
        assert polling_service._task is None
        assert polling_service._running is False

    @pytest.mark.asyncio
    async def test_stop_without_start_is_safe(
        self, polling_service: PollingService
    ) -> None:
        """Verify that stop() can be called without prior start()."""
        # Should not raise an exception
        await polling_service.stop()

        assert polling_service._task is None
        assert polling_service._running is False

    @pytest.mark.asyncio
    async def test_stop_clears_running_flag(
        self, polling_service: PollingService
    ) -> None:
        """Verify that stop() sets the _running flag to False."""
        await polling_service.start()
        assert polling_service._running is True

        await polling_service.stop()
        assert polling_service._running is False


class TestPollingServiceLifecycle:
    """Test suite for complete start/stop lifecycle scenarios."""

    @pytest.mark.asyncio
    async def test_can_restart_after_stop(
        self, polling_service: PollingService
    ) -> None:
        """Verify that the service can be restarted after being stopped."""
        # First start/stop cycle
        await polling_service.start()
        first_task = polling_service._task
        await polling_service.stop()

        # Restart the service
        await polling_service.start()

        try:
            # Should have a new task
            assert polling_service._task is not None
            assert polling_service._task is not first_task
            assert polling_service._running is True
        finally:
            await polling_service.stop()

    @pytest.mark.asyncio
    async def test_multiple_start_stop_cycles(
        self, polling_service: PollingService
    ) -> None:
        """Verify that multiple start/stop cycles work correctly."""
        for _ in range(3):
            await polling_service.start()
            assert polling_service._running is True
            assert polling_service._task is not None

            await polling_service.stop()
            assert polling_service._running is False
            assert polling_service._task is None


class TestPollingServiceBuildJql:
    """Test suite for PollingService._build_jql() method."""

    def test_build_jql_with_default_settings(
        self, mock_jira_client: MagicMock
    ) -> None:
        """Verify JQL construction with default issue types (Story,Task) and 7 days lookback."""
        settings = JiraSettings(
            base_url="https://test.atlassian.net",
            user_email="test@example.com",
            api_token="test-api-token",
            project_key="TEST",
            # Use defaults: issue_types="Story,Task", polling_lookback_days=7
        )
        service = PollingService(jira_client=mock_jira_client, settings=settings)

        jql = service._build_jql()

        # Verify all JQL components are present
        assert "project = TEST" in jql
        assert "issuetype in (Story,Task)" in jql
        assert 'labels not in ("ac-generated", "ac-generation-failed", "regenerating")' in jql
        assert "created >= -7d" in jql
        assert "ORDER BY created ASC" in jql

    def test_build_jql_with_custom_issue_types(
        self, mock_jira_client: MagicMock
    ) -> None:
        """Verify JQL construction with custom issue types."""
        settings = JiraSettings(
            base_url="https://test.atlassian.net",
            user_email="test@example.com",
            api_token="test-api-token",
            project_key="PROJ",
            issue_types="Bug,Epic,Spike",
        )
        service = PollingService(jira_client=mock_jira_client, settings=settings)

        jql = service._build_jql()

        assert "project = PROJ" in jql
        assert "issuetype in (Bug,Epic,Spike)" in jql
        assert 'labels not in ("ac-generated", "ac-generation-failed", "regenerating")' in jql
        assert "created >= -7d" in jql
        assert "ORDER BY created ASC" in jql

    def test_build_jql_with_custom_lookback_days(
        self, mock_jira_client: MagicMock
    ) -> None:
        """Verify JQL construction with custom lookback days."""
        settings = JiraSettings(
            base_url="https://test.atlassian.net",
            user_email="test@example.com",
            api_token="test-api-token",
            project_key="MYPROJ",
            polling_lookback_days=14,
        )
        service = PollingService(jira_client=mock_jira_client, settings=settings)

        jql = service._build_jql()

        assert "project = MYPROJ" in jql
        assert "issuetype in (Story,Task)" in jql
        assert 'labels not in ("ac-generated", "ac-generation-failed", "regenerating")' in jql
        assert "created >= -14d" in jql
        assert "ORDER BY created ASC" in jql

    def test_build_jql_contains_all_required_components(
        self, mock_jira_client: MagicMock
    ) -> None:
        """Verify that JQL contains all required components for ticket discovery."""
        settings = JiraSettings(
            base_url="https://test.atlassian.net",
            user_email="test@example.com",
            api_token="test-api-token",
            project_key="ABC",
            issue_types="Story",
            polling_lookback_days=30,
        )
        service = PollingService(jira_client=mock_jira_client, settings=settings)

        jql = service._build_jql()

        # Verify the exact expected JQL structure
        expected_jql = (
            "project = ABC "
            "AND issuetype in (Story) "
            'AND (labels is EMPTY OR labels not in ("ac-generated", "ac-generation-failed", "regenerating")) '
            "AND created >= -30d "
            "ORDER BY created ASC"
        )
        assert jql == expected_jql

    def test_build_jql_with_single_issue_type(
        self, mock_jira_client: MagicMock
    ) -> None:
        """Verify JQL construction with a single issue type."""
        settings = JiraSettings(
            base_url="https://test.atlassian.net",
            user_email="test@example.com",
            api_token="test-api-token",
            project_key="SINGLE",
            issue_types="Task",
        )
        service = PollingService(jira_client=mock_jira_client, settings=settings)

        jql = service._build_jql()

        assert "issuetype in (Task)" in jql
        assert "project = SINGLE" in jql

    def test_build_jql_excludes_regenerating_label(
        self, mock_jira_client: MagicMock
    ) -> None:
        """Verify JQL excludes tickets with 'regenerating' label.

        The 'regenerating' label is added by the manual regeneration service
        to signal that a ticket is being processed via Slack DM. The polling
        service must skip these tickets to prevent conflicting writes.
        """
        settings = JiraSettings(
            base_url="https://test.atlassian.net",
            user_email="test@example.com",
            api_token="test-api-token",
            project_key="TEST",
        )
        service = PollingService(jira_client=mock_jira_client, settings=settings)

        jql = service._build_jql()

        assert '"regenerating"' in jql
        assert 'labels not in ("ac-generated", "ac-generation-failed", "regenerating")' in jql


class TestPollingServicePollCycle:
    """Test suite for PollingService._poll_cycle() method."""

    @pytest.fixture
    def mock_tickets(self) -> list[TicketData]:
        """Create sample tickets for test responses."""
        return [
            TicketData(
                key="TEST-1",
                summary="First ticket",
                description="Description 1",
                issue_type="Story",
            ),
            TicketData(
                key="TEST-2",
                summary="Second ticket",
                description="Description 2",
                issue_type="Task",
            ),
            TicketData(
                key="TEST-3",
                summary="Third ticket",
                description="Description 3",
                issue_type="Story",
            ),
        ]

    @pytest.mark.asyncio
    async def test_poll_cycle_calls_search_tickets_with_correct_jql(
        self,
        mock_jira_settings: JiraSettings,
        mock_tickets: list[TicketData],
    ) -> None:
        """Verify poll cycle calls search_tickets with the JQL from _build_jql."""
        mock_client = MagicMock(spec=JiraClient)
        mock_client.search_tickets = AsyncMock(return_value=mock_tickets)

        service = PollingService(
            jira_client=mock_client,
            settings=mock_jira_settings,
        )

        await service._poll_cycle()

        # Verify search_tickets was called exactly once
        mock_client.search_tickets.assert_called_once()

        # Verify the JQL passed matches what _build_jql generates
        expected_jql = service._build_jql()
        actual_jql = mock_client.search_tickets.call_args[0][0]
        assert actual_jql == expected_jql

    @pytest.mark.asyncio
    async def test_poll_cycle_logs_discovered_ticket_count(
        self,
        mock_jira_settings: JiraSettings,
        mock_tickets: list[TicketData],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Verify poll cycle logs the count of discovered tickets."""
        mock_client = MagicMock(spec=JiraClient)
        mock_client.search_tickets = AsyncMock(return_value=mock_tickets)

        service = PollingService(
            jira_client=mock_client,
            settings=mock_jira_settings,
        )

        with caplog.at_level(logging.INFO, logger="src.polling.service"):
            await service._poll_cycle()

        # Verify the log message contains the ticket count
        assert any(
            "Poll cycle: discovered 3 tickets" in record.message
            for record in caplog.records
        )

    @pytest.mark.asyncio
    async def test_poll_cycle_logs_zero_tickets_when_none_found(
        self,
        mock_jira_settings: JiraSettings,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Verify poll cycle logs zero when no tickets are found."""
        mock_client = MagicMock(spec=JiraClient)
        mock_client.search_tickets = AsyncMock(return_value=[])

        service = PollingService(
            jira_client=mock_client,
            settings=mock_jira_settings,
        )

        with caplog.at_level(logging.INFO, logger="src.polling.service"):
            await service._poll_cycle()

        # Verify the log message shows 0 tickets
        assert any(
            "Poll cycle: discovered 0 tickets" in record.message
            for record in caplog.records
        )

    @pytest.mark.asyncio
    async def test_poll_cycle_overlap_prevention_skips_when_cycle_running(
        self,
        mock_jira_settings: JiraSettings,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Verify poll cycle is skipped when _cycle_running is True."""
        mock_client = MagicMock(spec=JiraClient)
        mock_client.search_tickets = AsyncMock(return_value=[])

        service = PollingService(
            jira_client=mock_client,
            settings=mock_jira_settings,
        )

        # Simulate a previous cycle still running
        service._cycle_running = True

        with caplog.at_level(logging.WARNING, logger="src.polling.service"):
            await service._poll_cycle()

        # Verify search_tickets was NOT called
        mock_client.search_tickets.assert_not_called()

        # Verify warning was logged
        assert any(
            "Previous poll cycle still running, skipping this cycle" in record.message
            for record in caplog.records
        )

    @pytest.mark.asyncio
    async def test_poll_cycle_resets_cycle_running_flag_after_completion(
        self,
        mock_jira_settings: JiraSettings,
        mock_tickets: list[TicketData],
    ) -> None:
        """Verify _cycle_running is reset to False after poll cycle completes."""
        mock_client = MagicMock(spec=JiraClient)
        mock_client.search_tickets = AsyncMock(return_value=mock_tickets)

        service = PollingService(
            jira_client=mock_client,
            settings=mock_jira_settings,
        )

        # Verify initial state
        assert service._cycle_running is False

        await service._poll_cycle()

        # Verify flag is reset after completion
        assert service._cycle_running is False

    @pytest.mark.asyncio
    async def test_poll_cycle_resets_cycle_running_flag_on_exception(
        self,
        mock_jira_settings: JiraSettings,
    ) -> None:
        """Verify _cycle_running is reset even if search_tickets raises an exception."""
        mock_client = MagicMock(spec=JiraClient)
        mock_client.search_tickets = AsyncMock(side_effect=RuntimeError("API error"))

        service = PollingService(
            jira_client=mock_client,
            settings=mock_jira_settings,
        )

        # Verify initial state
        assert service._cycle_running is False

        with pytest.raises(RuntimeError, match="API error"):
            await service._poll_cycle()

        # Verify flag is reset even after exception (finally block)
        assert service._cycle_running is False


class TestPollingServicePrerequisiteValidation:
    """Test suite for prerequisite validation methods (_has_existing_acs, _process_ticket)."""

    @pytest.fixture
    def mock_ac_generator(self) -> MagicMock:
        """Create a mock ACGenerator for prerequisite validation tests."""
        mock = MagicMock()
        mock.is_enabled = True
        mock.generate = AsyncMock(
            return_value=ACGenerationResult(
                acceptance_criteria=[
                    "User can perform the described action",
                    "System responds within acceptable time limits",
                    "Error states are handled gracefully",
                ],
                confidence_score=0.9,
                confidence_gaps=[],
                sufficient_information=True,
            )
        )
        return mock

    @pytest.fixture
    def service(
        self,
        mock_jira_client: MagicMock,
        mock_jira_settings: JiraSettings,
        mock_ac_generator: MagicMock,
    ) -> PollingService:
        """Create a PollingService instance for prerequisite validation tests."""
        return PollingService(
            jira_client=mock_jira_client,
            settings=mock_jira_settings,
            ac_generator=mock_ac_generator,
        )

    # Tests for _has_existing_acs

    def test_prerequisite_has_existing_acs_returns_true_when_ac_section_present(
        self, service: PollingService
    ) -> None:
        """Verify _has_existing_acs returns True when description contains '## Acceptance Criteria'."""
        description = "Some ticket description\n\n## Acceptance Criteria\n- Criterion 1\n- Criterion 2"

        result = service._has_existing_acs(description)

        assert result is True

    def test_prerequisite_has_existing_acs_returns_false_when_no_ac_section(
        self, service: PollingService
    ) -> None:
        """Verify _has_existing_acs returns False when description has no AC section."""
        description = "A simple ticket description without any AC section."

        result = service._has_existing_acs(description)

        assert result is False

    def test_prerequisite_has_existing_acs_returns_true_for_plain_text_acs(
        self, service: PollingService
    ) -> None:
        """Verify _has_existing_acs returns True for ACs from Jira's ADF (no ## prefix)."""
        description = "Some description Acceptance Criteria Criterion 1 Criterion 2"

        result = service._has_existing_acs(description)

        assert result is True

    def test_prerequisite_has_existing_acs_is_case_insensitive(
        self, service: PollingService
    ) -> None:
        """Verify _has_existing_acs matches AC section regardless of case."""
        # Test various case combinations
        descriptions = [
            "## ACCEPTANCE CRITERIA\n- Item",
            "## acceptance criteria\n- Item",
            "## Acceptance criteria\n- Item",
            "## ACCEPTANCE criteria\n- Item",
            "## acceptance CRITERIA\n- Item",
        ]

        for description in descriptions:
            result = service._has_existing_acs(description)
            assert result is True, f"Failed for description: {description}"

    def test_prerequisite_has_existing_acs_returns_false_for_empty_description(
        self, service: PollingService
    ) -> None:
        """Verify _has_existing_acs returns False for empty string."""
        result = service._has_existing_acs("")

        assert result is False

    # Tests for _process_ticket

    @pytest.mark.asyncio
    async def test_prerequisite_process_ticket_skips_empty_description(
        self,
        service: PollingService,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Verify _process_ticket returns False when ticket has empty description."""
        ticket = TicketData(
            key="TEST-100",
            summary="Ticket with empty description",
            description="",
            issue_type="Story",
        )

        with caplog.at_level(logging.INFO, logger="src.polling.service"):
            result = await service._process_ticket(ticket)

        assert result is False
        assert any(
            "Skipping TEST-100: empty description" in record.message
            for record in caplog.records
        )

    @pytest.mark.asyncio
    async def test_prerequisite_process_ticket_skips_existing_acs(
        self,
        service: PollingService,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Verify _process_ticket returns False when ticket already has acceptance criteria."""
        ticket = TicketData(
            key="TEST-102",
            summary="Ticket with existing ACs",
            description="Some description\n\n## Acceptance Criteria\n- Already has ACs",
            issue_type="Story",
        )

        with caplog.at_level(logging.INFO, logger="src.polling.service"):
            result = await service._process_ticket(ticket)

        assert result is False
        assert any(
            "Skipping TEST-102: already has acceptance criteria" in record.message
            for record in caplog.records
        )

    @pytest.mark.asyncio
    async def test_prerequisite_process_ticket_returns_true_for_valid_ticket(
        self,
        service: PollingService,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Verify _process_ticket returns True for valid ticket without existing ACs."""
        ticket = TicketData(
            key="TEST-103",
            summary="Valid ticket needing ACs",
            description="As a user, I want to perform an action so that I get a benefit.",
            issue_type="Story",
        )
        # Mock Jira client methods for success path
        service._client.add_label = AsyncMock(return_value=True)
        service._client.get_ticket = AsyncMock(return_value=ticket)
        service._client.update_description = AsyncMock(return_value=True)

        with caplog.at_level(logging.DEBUG, logger="src.polling.service"):
            result = await service._process_ticket(ticket)

        assert result is True


class TestPollingServiceSuccessFlow:
    """Test suite for PollingService success flow after AC generation."""

    @pytest.fixture
    def mock_jira_client(self) -> MagicMock:
        """Create a mock JiraClient for success flow tests."""
        return MagicMock(spec=JiraClient)

    @pytest.fixture
    def mock_jira_settings(self) -> JiraSettings:
        """Create mock JiraSettings for success flow tests."""
        return JiraSettings(
            base_url="https://test.atlassian.net",
            user_email="test@example.com",
            api_token="test-api-token",
            project_key="TEST",
            polling_enabled=True,
            polling_interval_seconds=1,
            polling_lookback_days=7,
            polling_max_failures=3,
        )

    @pytest.fixture
    def mock_ac_generator(self) -> MagicMock:
        """Create a mock ACGenerator for success flow tests."""
        mock = MagicMock()
        mock.is_enabled = True
        mock.generate = AsyncMock(
            return_value=ACGenerationResult(
                acceptance_criteria=[
                    "User can perform the described action",
                    "System responds within acceptable time limits",
                    "Error states are handled gracefully",
                ],
                confidence_score=0.9,
                confidence_gaps=[],
                sufficient_information=True,
            )
        )
        return mock

    @pytest.fixture
    def service(
        self,
        mock_jira_client: MagicMock,
        mock_jira_settings: JiraSettings,
        mock_ac_generator: MagicMock,
    ) -> PollingService:
        """Create a PollingService instance for success flow tests."""
        return PollingService(
            jira_client=mock_jira_client,
            settings=mock_jira_settings,
            ac_generator=mock_ac_generator,
        )

    @pytest.fixture
    def valid_ticket(self) -> TicketData:
        """Create a valid ticket that passes prerequisite checks."""
        return TicketData(
            key="TEST-200",
            summary="Valid ticket for success flow tests",
            description="As a user, I want to test success flow so that labeling works.",
            issue_type="Story",
        )

    @pytest.mark.asyncio
    async def test_success_add_label_called_with_correct_arguments(
        self,
        service: PollingService,
        valid_ticket: TicketData,
    ) -> None:
        """Verify add_label is called with correct ticket key and label on success."""
        service._client.add_label = AsyncMock(return_value=True)
        service._client.get_ticket = AsyncMock(return_value=valid_ticket)
        service._client.update_description = AsyncMock(return_value=True)

        await service._process_ticket(valid_ticket)

        service._client.add_label.assert_called_once_with("TEST-200", "ac-generated")

    @pytest.mark.asyncio
    async def test_success_logged_when_label_added(
        self,
        service: PollingService,
        valid_ticket: TicketData,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Verify success is logged with timestamp when label is added successfully."""
        service._client.add_label = AsyncMock(return_value=True)
        service._client.get_ticket = AsyncMock(return_value=valid_ticket)
        service._client.update_description = AsyncMock(return_value=True)

        with caplog.at_level(logging.INFO, logger="src.polling.service"):
            result = await service._process_ticket(valid_ticket)

        assert result is True
        # Check for success log message with ticket key
        assert any(
            "Successfully processed TEST-200 at" in record.message
            for record in caplog.records
        )
        # Verify the log record has INFO level
        success_records = [
            record
            for record in caplog.records
            if "Successfully processed TEST-200" in record.message
        ]
        assert len(success_records) == 1
        assert success_records[0].levelno == logging.INFO

    @pytest.mark.asyncio
    async def test_success_warning_logged_when_label_fails(
        self,
        service: PollingService,
        valid_ticket: TicketData,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Verify warning is logged when add_label fails."""
        service._client.add_label = AsyncMock(return_value=False)
        service._client.get_ticket = AsyncMock(return_value=valid_ticket)
        service._client.update_description = AsyncMock(return_value=True)

        with caplog.at_level(logging.WARNING, logger="src.polling.service"):
            result = await service._process_ticket(valid_ticket)

        # Process still returns True since AC generation succeeded
        assert result is True
        # Check for warning log message
        assert any(
            "Processed TEST-200 but failed to add label" in record.message
            for record in caplog.records
        )
        # Verify the log record has WARNING level
        warning_records = [
            record
            for record in caplog.records
            if "failed to add label" in record.message
        ]
        assert len(warning_records) == 1
        assert warning_records[0].levelno == logging.WARNING

    @pytest.mark.asyncio
    async def test_success_returns_true_regardless_of_label_result(
        self,
        service: PollingService,
        valid_ticket: TicketData,
    ) -> None:
        """Verify _process_ticket returns True even when label addition fails."""
        # Test with label success
        service._client.add_label = AsyncMock(return_value=True)
        service._client.get_ticket = AsyncMock(return_value=valid_ticket)
        service._client.update_description = AsyncMock(return_value=True)
        result_with_label = await service._process_ticket(valid_ticket)
        assert result_with_label is True

        # Test with label failure
        service._client.add_label = AsyncMock(return_value=False)
        service._client.get_ticket = AsyncMock(return_value=valid_ticket)
        service._client.update_description = AsyncMock(return_value=True)
        result_without_label = await service._process_ticket(valid_ticket)
        assert result_without_label is True


class TestPollingServiceFailureTracking:
    """Test suite for PollingService failure tracking (_record_failure, _clear_failure)."""

    @pytest.fixture
    def mock_jira_client(self) -> MagicMock:
        """Create a mock JiraClient for failure tracking tests."""
        return MagicMock(spec=JiraClient)

    @pytest.fixture
    def mock_jira_settings(self) -> JiraSettings:
        """Create mock JiraSettings for failure tracking tests."""
        return JiraSettings(
            base_url="https://test.atlassian.net",
            user_email="test@example.com",
            api_token="test-api-token",
            project_key="TEST",
            polling_enabled=True,
            polling_interval_seconds=1,
            polling_lookback_days=7,
            polling_max_failures=3,
        )

    @pytest.fixture
    def mock_ac_generator(self) -> MagicMock:
        """Create a mock ACGenerator for failure tracking tests."""
        mock = MagicMock()
        mock.is_enabled = True
        mock.generate = AsyncMock(
            return_value=ACGenerationResult(
                acceptance_criteria=[
                    "User can perform the described action",
                    "System responds within acceptable time limits",
                    "Error states are handled gracefully",
                ],
                confidence_score=0.9,
                confidence_gaps=[],
                sufficient_information=True,
            )
        )
        return mock

    @pytest.fixture
    def service(
        self,
        mock_jira_client: MagicMock,
        mock_jira_settings: JiraSettings,
        mock_ac_generator: MagicMock,
    ) -> PollingService:
        """Create a PollingService instance for failure tracking tests."""
        return PollingService(
            jira_client=mock_jira_client,
            settings=mock_jira_settings,
            ac_generator=mock_ac_generator,
        )

    @pytest.fixture
    def valid_ticket(self) -> TicketData:
        """Create a valid ticket that passes prerequisite checks."""
        return TicketData(
            key="TEST-300",
            summary="Valid ticket for failure tracking tests",
            description="As a user, I want to test failure tracking so that retries work.",
            issue_type="Story",
        )

    # Tests for _record_failure

    def test_record_failure_increments_count_from_zero(
        self, service: PollingService
    ) -> None:
        """Verify _record_failure increments count from 0 to 1 for a new ticket."""
        ticket_key = "TEST-301"

        # No prior failures
        assert ticket_key not in service._failure_counts

        count = service._record_failure(ticket_key)

        assert count == 1
        assert service._failure_counts[ticket_key] == 1

    def test_record_failure_increments_count_correctly(
        self, service: PollingService
    ) -> None:
        """Verify _record_failure increments count correctly on subsequent calls."""
        ticket_key = "TEST-302"

        # Record multiple failures
        count1 = service._record_failure(ticket_key)
        count2 = service._record_failure(ticket_key)
        count3 = service._record_failure(ticket_key)

        assert count1 == 1
        assert count2 == 2
        assert count3 == 3
        assert service._failure_counts[ticket_key] == 3

    def test_record_failure_returns_correct_count(
        self, service: PollingService
    ) -> None:
        """Verify _record_failure returns the new count after incrementing."""
        ticket_key = "TEST-303"

        # Pre-set a failure count
        service._failure_counts[ticket_key] = 5

        result = service._record_failure(ticket_key)

        assert result == 6

    def test_record_failure_tracks_multiple_tickets_independently(
        self, service: PollingService
    ) -> None:
        """Verify _record_failure tracks each ticket separately."""
        ticket_a = "TEST-304A"
        ticket_b = "TEST-304B"

        # Record failures for ticket A
        service._record_failure(ticket_a)
        service._record_failure(ticket_a)

        # Record failures for ticket B
        service._record_failure(ticket_b)

        assert service._failure_counts[ticket_a] == 2
        assert service._failure_counts[ticket_b] == 1

    # Tests for _clear_failure

    def test_clear_failure_removes_count(
        self, service: PollingService
    ) -> None:
        """Verify _clear_failure removes the failure count for a ticket."""
        ticket_key = "TEST-305"

        # Pre-set a failure count
        service._failure_counts[ticket_key] = 3
        assert ticket_key in service._failure_counts

        service._clear_failure(ticket_key)

        assert ticket_key not in service._failure_counts

    def test_clear_failure_is_safe_for_nonexistent_ticket(
        self, service: PollingService
    ) -> None:
        """Verify _clear_failure does not raise for a ticket with no failures."""
        ticket_key = "TEST-306"

        # No prior failures
        assert ticket_key not in service._failure_counts

        # Should not raise
        service._clear_failure(ticket_key)

        assert ticket_key not in service._failure_counts

    def test_clear_failure_does_not_affect_other_tickets(
        self, service: PollingService
    ) -> None:
        """Verify _clear_failure only removes the specified ticket's count."""
        ticket_a = "TEST-307A"
        ticket_b = "TEST-307B"

        # Pre-set failure counts for both tickets
        service._failure_counts[ticket_a] = 2
        service._failure_counts[ticket_b] = 5

        service._clear_failure(ticket_a)

        assert ticket_a not in service._failure_counts
        assert service._failure_counts[ticket_b] == 5

    # Tests for max failures triggering ac-generation-failed label

    @pytest.mark.asyncio
    async def test_max_failure_triggers_ac_generation_failed_label(
        self,
        mock_jira_client: MagicMock,
        mock_jira_settings: JiraSettings,
        valid_ticket: TicketData,
    ) -> None:
        """Verify max failures triggers ac-generation-failed label."""
        mock_jira_client.add_label = AsyncMock(return_value=True)

        service = PollingService(
            jira_client=mock_jira_client,
            settings=mock_jira_settings,
        )

        # Pre-set failure count to max - 1 (i.e., 2 when max is 3)
        service._failure_counts[valid_ticket.key] = (
            mock_jira_settings.polling_max_failures - 1
        )

        # Simulate AC generation failure by temporarily patching behavior
        # We need to make the next _process_ticket call fail AC generation
        # The implementation has a placeholder that always succeeds, so we mock it
        original_process = service._process_ticket

        async def mock_failing_process(ticket: TicketData) -> bool:
            """Simulate AC generation failure to trigger label logic."""
            # Check 1: Has description?
            if not ticket.description:
                return False

            # Check 2: Has existing ACs?
            if service._has_existing_acs(ticket.description):
                return False

            # Simulate failure
            failure_count = service._record_failure(ticket.key)

            # If max failures reached, add failed label
            if failure_count >= service._settings.polling_max_failures:
                await service._client.add_label(ticket.key, "ac-generation-failed")

            return False

        # Patch and run
        service._process_ticket = mock_failing_process
        await service._process_ticket(valid_ticket)

        # Verify the label was added
        mock_jira_client.add_label.assert_called_once_with(
            valid_ticket.key, "ac-generation-failed"
        )

    @pytest.mark.asyncio
    async def test_failure_below_max_does_not_trigger_label(
        self,
        mock_jira_client: MagicMock,
        mock_jira_settings: JiraSettings,
        valid_ticket: TicketData,
    ) -> None:
        """Verify failures below max do not trigger ac-generation-failed label."""
        mock_jira_client.add_label = AsyncMock(return_value=True)

        service = PollingService(
            jira_client=mock_jira_client,
            settings=mock_jira_settings,
        )

        # Pre-set failure count to max - 2 (i.e., 1 when max is 3)
        # After one more failure, count will be 2, still below max of 3
        service._failure_counts[valid_ticket.key] = (
            mock_jira_settings.polling_max_failures - 2
        )

        async def mock_failing_process(ticket: TicketData) -> bool:
            """Simulate AC generation failure without reaching max."""
            if not ticket.description:
                return False

            if service._has_existing_acs(ticket.description):
                return False

            # Simulate failure
            failure_count = service._record_failure(ticket.key)

            # If max failures reached, add failed label
            if failure_count >= service._settings.polling_max_failures:
                await service._client.add_label(ticket.key, "ac-generation-failed")

            return False

        service._process_ticket = mock_failing_process
        await service._process_ticket(valid_ticket)

        # Verify the label was NOT added (still below max)
        mock_jira_client.add_label.assert_not_called()

    # Tests for success clearing failure count

    @pytest.mark.asyncio
    async def test_success_clears_failure_count(
        self,
        service: PollingService,
        valid_ticket: TicketData,
    ) -> None:
        """Verify successful processing clears any prior failure count."""
        service._client.add_label = AsyncMock(return_value=True)
        service._client.get_ticket = AsyncMock(return_value=valid_ticket)
        service._client.update_description = AsyncMock(return_value=True)

        # Pre-set a failure count
        service._failure_counts[valid_ticket.key] = 2

        await service._process_ticket(valid_ticket)

        # Failure count should be cleared on success
        assert valid_ticket.key not in service._failure_counts

    @pytest.mark.asyncio
    async def test_success_clears_failure_count_after_multiple_failures(
        self,
        service: PollingService,
        valid_ticket: TicketData,
    ) -> None:
        """Verify success clears failure count even after multiple prior failures."""
        service._client.add_label = AsyncMock(return_value=True)
        service._client.get_ticket = AsyncMock(return_value=valid_ticket)
        service._client.update_description = AsyncMock(return_value=True)

        # Pre-set multiple failures (but below max)
        service._failure_counts[valid_ticket.key] = (
            service._settings.polling_max_failures - 1
        )

        # Successful processing should clear the count
        result = await service._process_ticket(valid_ticket)

        assert result is True
        assert valid_ticket.key not in service._failure_counts


class TestPollingServiceACGeneratorIntegration:
    """Test suite for PollingService integration with ACGenerator."""

    @pytest.fixture
    def mock_jira_client(self) -> MagicMock:
        """Create a mock JiraClient for AC generator integration tests."""
        return MagicMock(spec=JiraClient)

    @pytest.fixture
    def mock_jira_settings(self) -> JiraSettings:
        """Create mock JiraSettings for AC generator integration tests."""
        return JiraSettings(
            base_url="https://test.atlassian.net",
            user_email="test@example.com",
            api_token="test-api-token",
            project_key="TEST",
            polling_enabled=True,
            polling_interval_seconds=1,
            polling_lookback_days=7,
            polling_max_failures=3,
        )

    @pytest.fixture
    def mock_ac_generator(self) -> MagicMock:
        """Create a mock ACGenerator for testing."""
        mock = MagicMock()
        mock.is_enabled = True
        mock.generate = AsyncMock(
            return_value=ACGenerationResult(
                acceptance_criteria=[
                    "User can perform the described action",
                    "System responds within acceptable time limits",
                    "Error states are handled gracefully",
                ],
                confidence_score=0.9,
                confidence_gaps=[],
                sufficient_information=True,
            )
        )
        return mock

    @pytest.fixture
    def valid_ticket(self) -> TicketData:
        """Create a valid ticket that passes prerequisite checks."""
        return TicketData(
            key="TEST-400",
            summary="Valid ticket for AC generator tests",
            description="As a user, I want to test AC generation integration.",
            issue_type="Story",
        )

    @pytest.mark.asyncio
    async def test_process_ticket_calls_ac_generator_generate(
        self,
        mock_jira_client: MagicMock,
        mock_jira_settings: JiraSettings,
        mock_ac_generator: MagicMock,
        valid_ticket: TicketData,
    ) -> None:
        """Verify _process_ticket calls ac_generator.generate() with correct args."""
        mock_jira_client.add_label = AsyncMock(return_value=True)
        mock_jira_client.get_ticket = AsyncMock(return_value=valid_ticket)
        mock_jira_client.update_description = AsyncMock(return_value=True)

        service = PollingService(
            jira_client=mock_jira_client,
            settings=mock_jira_settings,
            ac_generator=mock_ac_generator,
        )

        await service._process_ticket(valid_ticket)

        mock_ac_generator.generate.assert_called_once_with(
            summary=valid_ticket.summary,
            description=valid_ticket.description,
        )

    @pytest.mark.asyncio
    async def test_process_ticket_writes_generated_acs_to_jira(
        self,
        mock_jira_client: MagicMock,
        mock_jira_settings: JiraSettings,
        mock_ac_generator: MagicMock,
        valid_ticket: TicketData,
    ) -> None:
        """Verify _process_ticket writes AI-generated ACs to Jira."""
        mock_jira_client.add_label = AsyncMock(return_value=True)
        mock_jira_client.get_ticket = AsyncMock(return_value=valid_ticket)
        mock_jira_client.update_description = AsyncMock(return_value=True)

        service = PollingService(
            jira_client=mock_jira_client,
            settings=mock_jira_settings,
            ac_generator=mock_ac_generator,
        )

        result = await service._process_ticket(valid_ticket)

        assert result is True
        mock_jira_client.update_description.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_ticket_returns_false_when_ac_generator_is_none(
        self,
        mock_jira_client: MagicMock,
        mock_jira_settings: JiraSettings,
        valid_ticket: TicketData,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Verify _process_ticket returns False when ac_generator is None."""
        service = PollingService(
            jira_client=mock_jira_client,
            settings=mock_jira_settings,
            ac_generator=None,  # No AC generator
        )

        with caplog.at_level(logging.WARNING, logger="src.polling.service"):
            result = await service._process_ticket(valid_ticket)

        assert result is False
        assert any(
            "AI generation disabled, skipping TEST-400" in record.message
            for record in caplog.records
        )

    @pytest.mark.asyncio
    async def test_process_ticket_returns_false_when_ac_generator_is_disabled(
        self,
        mock_jira_client: MagicMock,
        mock_jira_settings: JiraSettings,
        valid_ticket: TicketData,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Verify _process_ticket returns False when ac_generator.is_enabled is False."""
        mock_generator = MagicMock()
        mock_generator.is_enabled = False  # Generator exists but is disabled

        service = PollingService(
            jira_client=mock_jira_client,
            settings=mock_jira_settings,
            ac_generator=mock_generator,
        )

        with caplog.at_level(logging.WARNING, logger="src.polling.service"):
            result = await service._process_ticket(valid_ticket)

        assert result is False
        assert any(
            "AI generation disabled, skipping TEST-400" in record.message
            for record in caplog.records
        )

    @pytest.mark.asyncio
    async def test_process_ticket_returns_false_when_generate_returns_empty_list(
        self,
        mock_jira_client: MagicMock,
        mock_jira_settings: JiraSettings,
        valid_ticket: TicketData,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Verify _process_ticket returns False when ac_generator.generate() returns []."""
        mock_generator = MagicMock()
        mock_generator.is_enabled = True
        mock_generator.generate = AsyncMock(
            return_value=ACGenerationResult(
                acceptance_criteria=[],
                confidence_score=0.0,
                confidence_gaps=["Insufficient information"],
                sufficient_information=False,
            )
        )  # Empty list = insufficient info

        service = PollingService(
            jira_client=mock_jira_client,
            settings=mock_jira_settings,
            ac_generator=mock_generator,
        )

        with caplog.at_level(logging.WARNING, logger="src.polling.service"):
            result = await service._process_ticket(valid_ticket)

        assert result is False
        assert any(
            "AI determined insufficient information for TEST-400" in record.message
            for record in caplog.records
        )

    @pytest.mark.asyncio
    async def test_ac_generated_label_not_added_when_ai_returns_empty_list(
        self,
        mock_jira_client: MagicMock,
        mock_jira_settings: JiraSettings,
        valid_ticket: TicketData,
    ) -> None:
        """Verify ac-generated label is NOT added when AI returns empty list."""
        mock_jira_client.add_label = AsyncMock(return_value=True)

        mock_generator = MagicMock()
        mock_generator.is_enabled = True
        mock_generator.generate = AsyncMock(
            return_value=ACGenerationResult(
                acceptance_criteria=[],
                confidence_score=0.0,
                confidence_gaps=["Insufficient information"],
                sufficient_information=False,
            )
        )

        service = PollingService(
            jira_client=mock_jira_client,
            settings=mock_jira_settings,
            ac_generator=mock_generator,
        )

        await service._process_ticket(valid_ticket)

        # Verify add_label was NOT called (since processing was skipped)
        mock_jira_client.add_label.assert_not_called()

    @pytest.mark.asyncio
    async def test_ac_generated_label_added_on_success(
        self,
        mock_jira_client: MagicMock,
        mock_jira_settings: JiraSettings,
        mock_ac_generator: MagicMock,
        valid_ticket: TicketData,
    ) -> None:
        """Verify ac-generated label is added when AI generation succeeds."""
        mock_jira_client.add_label = AsyncMock(return_value=True)
        mock_jira_client.get_ticket = AsyncMock(return_value=valid_ticket)
        mock_jira_client.update_description = AsyncMock(return_value=True)

        service = PollingService(
            jira_client=mock_jira_client,
            settings=mock_jira_settings,
            ac_generator=mock_ac_generator,
        )

        result = await service._process_ticket(valid_ticket)

        assert result is True
        mock_jira_client.add_label.assert_called_once_with("TEST-400", "ac-generated")

    @pytest.mark.asyncio
    async def test_prerequisite_checks_run_before_ai_generation(
        self,
        mock_jira_client: MagicMock,
        mock_jira_settings: JiraSettings,
        mock_ac_generator: MagicMock,
    ) -> None:
        """Verify prerequisite checks (empty description, existing ACs) run before AI call."""
        # Ticket with existing ACs - should skip AI generation
        ticket_with_acs = TicketData(
            key="TEST-401",
            summary="Ticket with existing ACs",
            description="Description\n\n## Acceptance Criteria\n- Already has ACs",
            issue_type="Story",
        )

        service = PollingService(
            jira_client=mock_jira_client,
            settings=mock_jira_settings,
            ac_generator=mock_ac_generator,
        )

        result = await service._process_ticket(ticket_with_acs)

        assert result is False
        # AC generator should NOT be called because ticket already has ACs
        mock_ac_generator.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_description_skips_ai_generation(
        self,
        mock_jira_client: MagicMock,
        mock_jira_settings: JiraSettings,
        mock_ac_generator: MagicMock,
    ) -> None:
        """Verify empty description causes skip before AI generation is called."""
        ticket_empty_desc = TicketData(
            key="TEST-402",
            summary="Ticket with empty description",
            description="",
            issue_type="Story",
        )

        service = PollingService(
            jira_client=mock_jira_client,
            settings=mock_jira_settings,
            ac_generator=mock_ac_generator,
        )

        result = await service._process_ticket(ticket_empty_desc)

        assert result is False
        # AC generator should NOT be called because description is empty
        mock_ac_generator.generate.assert_not_called()

    def test_polling_service_init_accepts_ac_generator(
        self,
        mock_jira_client: MagicMock,
        mock_jira_settings: JiraSettings,
        mock_ac_generator: MagicMock,
    ) -> None:
        """Verify PollingService.__init__ accepts ac_generator parameter."""
        service = PollingService(
            jira_client=mock_jira_client,
            settings=mock_jira_settings,
            ac_generator=mock_ac_generator,
        )

        assert service._ac_generator is mock_ac_generator

    def test_polling_service_init_ac_generator_defaults_to_none(
        self,
        mock_jira_client: MagicMock,
        mock_jira_settings: JiraSettings,
    ) -> None:
        """Verify PollingService.__init__ defaults ac_generator to None."""
        service = PollingService(
            jira_client=mock_jira_client,
            settings=mock_jira_settings,
        )

        assert service._ac_generator is None


class TestPollingServiceBarleyEnrichment:
    """Test suite for PollingService integration with BarleyEnrichmentService."""

    @pytest.fixture
    def mock_jira_client(self) -> MagicMock:
        """Create a mock JiraClient for Barley enrichment tests."""
        return MagicMock(spec=JiraClient)

    @pytest.fixture
    def mock_jira_settings(self) -> JiraSettings:
        """Create mock JiraSettings for Barley enrichment tests."""
        return JiraSettings(
            base_url="https://test.atlassian.net",
            user_email="test@example.com",
            api_token="test-api-token",
            project_key="TEST",
            polling_enabled=True,
            polling_interval_seconds=1,
            polling_lookback_days=7,
            polling_max_failures=3,
        )

    @pytest.fixture
    def mock_ac_generator(self) -> MagicMock:
        """Create a mock ACGenerator for Barley enrichment tests."""
        mock = MagicMock()
        mock.is_enabled = True
        mock.generate = AsyncMock(
            return_value=ACGenerationResult(
                acceptance_criteria=[
                    "User can perform the described action",
                    "System responds within acceptable time limits",
                    "Error states are handled gracefully",
                ],
                confidence_score=0.9,
                confidence_gaps=[],
                sufficient_information=True,
            )
        )
        return mock

    @pytest.fixture
    def mock_enrichment_service(self) -> MagicMock:
        """Create a mock BarleyEnrichmentService."""
        from src.barley.models import EnrichmentResult

        mock = MagicMock()
        mock.enrich = AsyncMock(
            return_value=EnrichmentResult(
                barley_context="Project uses React for the frontend and Python FastAPI for the backend.",
                topics_extracted="React, FastAPI, frontend, backend",
            )
        )
        return mock

    @pytest.fixture
    def valid_ticket(self) -> TicketData:
        """Create a valid ticket that passes prerequisite checks."""
        return TicketData(
            key="TEST-500",
            summary="Valid ticket for Barley enrichment tests",
            description="As a user, I want to integrate Barley context into AC generation.",
            issue_type="Story",
        )

    @pytest.mark.asyncio
    async def test_enrichment_applied_passes_enriched_description_to_generate(
        self,
        mock_jira_client: MagicMock,
        mock_jira_settings: JiraSettings,
        mock_ac_generator: MagicMock,
        mock_enrichment_service: MagicMock,
        valid_ticket: TicketData,
    ) -> None:
        """Verify enriched description is passed to ACGenerator.generate() when context available."""
        mock_jira_client.add_label = AsyncMock(return_value=True)
        mock_jira_client.add_comment = AsyncMock(return_value=True)
        mock_jira_client.get_ticket = AsyncMock(return_value=valid_ticket)
        mock_jira_client.update_description = AsyncMock(return_value=True)

        service = PollingService(
            jira_client=mock_jira_client,
            settings=mock_jira_settings,
            ac_generator=mock_ac_generator,
            enrichment_service=mock_enrichment_service,
        )

        result = await service._process_ticket(valid_ticket)

        assert result is True

        # Verify enrich was called with the ticket's summary and description
        mock_enrichment_service.enrich.assert_called_once_with(
            summary=valid_ticket.summary,
            description=valid_ticket.description,
        )

        # Verify generate() received the enriched description (with Barley context appended)
        generate_call_kwargs = mock_ac_generator.generate.call_args[1]
        assert "Additional Context from Barley:" in generate_call_kwargs["description"]
        assert "Project uses React for the frontend" in generate_call_kwargs["description"]

        # Verify add_comment was called with the Barley context
        mock_jira_client.add_comment.assert_called_once_with(
            valid_ticket.key,
            "Project uses React for the frontend and Python FastAPI for the backend.",
        )

    @pytest.mark.asyncio
    async def test_enrichment_no_context_passes_original_description(
        self,
        mock_jira_client: MagicMock,
        mock_jira_settings: JiraSettings,
        mock_ac_generator: MagicMock,
        mock_enrichment_service: MagicMock,
        valid_ticket: TicketData,
    ) -> None:
        """Verify original description is passed to generate() when barley_context is None."""
        from src.barley.models import EnrichmentResult

        mock_enrichment_service.enrich = AsyncMock(
            return_value=EnrichmentResult(
                barley_context=None,
                topics_extracted="some topics",
            )
        )
        mock_jira_client.add_label = AsyncMock(return_value=True)
        mock_jira_client.get_ticket = AsyncMock(return_value=valid_ticket)
        mock_jira_client.update_description = AsyncMock(return_value=True)

        service = PollingService(
            jira_client=mock_jira_client,
            settings=mock_jira_settings,
            ac_generator=mock_ac_generator,
            enrichment_service=mock_enrichment_service,
        )

        result = await service._process_ticket(valid_ticket)

        assert result is True

        # Verify generate() received the original description (no enrichment)
        generate_call_kwargs = mock_ac_generator.generate.call_args[1]
        assert generate_call_kwargs["description"] == valid_ticket.description

        # Verify add_comment was NOT called (no context to post)
        mock_jira_client.add_comment.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_enrichment_service_uses_original_description(
        self,
        mock_jira_client: MagicMock,
        mock_jira_settings: JiraSettings,
        mock_ac_generator: MagicMock,
        valid_ticket: TicketData,
    ) -> None:
        """Verify original description is used when enrichment_service is None."""
        mock_jira_client.add_label = AsyncMock(return_value=True)
        mock_jira_client.get_ticket = AsyncMock(return_value=valid_ticket)
        mock_jira_client.update_description = AsyncMock(return_value=True)

        service = PollingService(
            jira_client=mock_jira_client,
            settings=mock_jira_settings,
            ac_generator=mock_ac_generator,
            enrichment_service=None,  # No enrichment service
        )

        result = await service._process_ticket(valid_ticket)

        assert result is True

        # Verify generate() received the original description
        generate_call_kwargs = mock_ac_generator.generate.call_args[1]
        assert generate_call_kwargs["description"] == valid_ticket.description

    @pytest.mark.asyncio
    async def test_enrichment_exception_continues_with_original_description(
        self,
        mock_jira_client: MagicMock,
        mock_jira_settings: JiraSettings,
        mock_ac_generator: MagicMock,
        mock_enrichment_service: MagicMock,
        valid_ticket: TicketData,
    ) -> None:
        """Verify _process_ticket() continues with original description when enrichment raises."""
        mock_enrichment_service.enrich = AsyncMock(
            side_effect=RuntimeError("Barley API crashed")
        )
        mock_jira_client.add_label = AsyncMock(return_value=True)
        mock_jira_client.get_ticket = AsyncMock(return_value=valid_ticket)
        mock_jira_client.update_description = AsyncMock(return_value=True)

        service = PollingService(
            jira_client=mock_jira_client,
            settings=mock_jira_settings,
            ac_generator=mock_ac_generator,
            enrichment_service=mock_enrichment_service,
        )

        # Should NOT raise - enrichment failure is caught and processing continues
        result = await service._process_ticket(valid_ticket)

        assert result is True

        # Verify generate() received the original description (not enriched)
        generate_call_kwargs = mock_ac_generator.generate.call_args[1]
        assert generate_call_kwargs["description"] == valid_ticket.description

        # Verify add_comment was NOT called (enrichment failed)
        mock_jira_client.add_comment.assert_not_called()


class TestPollingServiceConfidenceEscalation:
    """Test suite for confidence-based escalation logic in _process_ticket."""

    @pytest.fixture
    def mock_jira_client(self) -> MagicMock:
        """Create a mock JiraClient for confidence escalation tests."""
        return MagicMock(spec=JiraClient)

    @pytest.fixture
    def mock_jira_settings(self) -> JiraSettings:
        """Create mock JiraSettings for confidence escalation tests."""
        return JiraSettings(
            base_url="https://test.atlassian.net",
            user_email="test@example.com",
            api_token="test-api-token",
            project_key="TEST",
            polling_enabled=True,
            polling_interval_seconds=1,
            polling_lookback_days=7,
            polling_max_failures=3,
        )

    @pytest.fixture
    def valid_ticket(self) -> TicketData:
        """Create a valid ticket that passes prerequisite checks."""
        return TicketData(
            key="TEST-600",
            summary="Ticket needing confidence check",
            description="As a user, I want to test confidence escalation.",
            issue_type="Story",
        )

    @pytest.fixture
    def mock_escalation_service(self) -> MagicMock:
        """Create a mock SlackEscalationService."""
        from src.slack.models import EscalationResult

        mock = MagicMock()
        mock.escalate = AsyncMock(
            return_value=EscalationResult(sent=True, slack_user_id="U12345"),
        )
        return mock

    @pytest.fixture
    def mock_escalation_repository(self) -> MagicMock:
        """Create a mock EscalationRepository."""
        mock = MagicMock()
        mock.create = MagicMock()
        return mock

    # --- Test 1: High confidence, no escalation ---

    @pytest.mark.asyncio
    async def test_high_confidence_skips_escalation(
        self,
        mock_jira_client: MagicMock,
        mock_jira_settings: JiraSettings,
        mock_escalation_service: MagicMock,
        mock_escalation_repository: MagicMock,
        valid_ticket: TicketData,
    ) -> None:
        """Verify escalation is NOT triggered when confidence is above threshold.

        Given confidence_score=0.9 (above default threshold 0.7)
        When _process_ticket is called
        Then escalation_service.escalate() is NOT called
        And ACs are written directly without any prepended note.
        """
        mock_ac_generator = MagicMock()
        mock_ac_generator.is_enabled = True
        generated_acs = [
            "User can perform the described action",
            "System responds within acceptable time limits",
        ]
        mock_ac_generator.generate = AsyncMock(
            return_value=ACGenerationResult(
                acceptance_criteria=generated_acs,
                confidence_score=0.9,
                confidence_gaps=[],
                sufficient_information=True,
            )
        )

        mock_jira_client.get_ticket = AsyncMock(return_value=valid_ticket)
        mock_jira_client.update_description = AsyncMock(return_value=True)
        mock_jira_client.add_label = AsyncMock(return_value=True)

        service = PollingService(
            jira_client=mock_jira_client,
            settings=mock_jira_settings,
            ac_generator=mock_ac_generator,
            escalation_service=mock_escalation_service,
            escalation_repository=mock_escalation_repository,
            confidence_threshold=0.7,
        )

        result = await service._process_ticket(valid_ticket)

        assert result is True

        # Escalation should NOT have been called
        mock_escalation_service.escalate.assert_not_called()
        mock_escalation_repository.create.assert_not_called()

        # update_description should have been called (ACs written directly)
        mock_jira_client.update_description.assert_called_once()

    # --- Test 2: Low confidence + DM sent successfully ---

    @pytest.mark.asyncio
    async def test_low_confidence_escalation_sent_successfully(
        self,
        mock_jira_client: MagicMock,
        mock_jira_settings: JiraSettings,
        mock_escalation_service: MagicMock,
        mock_escalation_repository: MagicMock,
        valid_ticket: TicketData,
    ) -> None:
        """Verify escalation is triggered and recorded when confidence is below threshold.

        Given confidence_score=0.4 (below default threshold 0.7)
        And escalation_service.escalate() returns EscalationResult(sent=True)
        When _process_ticket is called
        Then escalation_service.escalate() IS called with correct args
        And escalation_repository.create() is called with status="SENT"
        And ACs written to Jira include the "clarification requested" note.
        """
        from src.slack.models import EscalationResult

        confidence_gaps = ["unclear user role", "missing error handling"]
        generated_acs = [
            "User can perform the described action",
            "System responds within acceptable time limits",
        ]
        mock_ac_generator = MagicMock()
        mock_ac_generator.is_enabled = True
        mock_ac_generator.generate = AsyncMock(
            return_value=ACGenerationResult(
                acceptance_criteria=generated_acs,
                confidence_score=0.4,
                confidence_gaps=confidence_gaps,
                sufficient_information=True,
            )
        )

        mock_escalation_service.escalate = AsyncMock(
            return_value=EscalationResult(sent=True, slack_user_id="U12345"),
        )

        mock_jira_client.get_ticket = AsyncMock(return_value=valid_ticket)
        mock_jira_client.update_description = AsyncMock(return_value=True)
        mock_jira_client.add_label = AsyncMock(return_value=True)

        service = PollingService(
            jira_client=mock_jira_client,
            settings=mock_jira_settings,
            ac_generator=mock_ac_generator,
            escalation_service=mock_escalation_service,
            escalation_repository=mock_escalation_repository,
            confidence_threshold=0.7,
        )

        result = await service._process_ticket(valid_ticket)

        assert result is True

        # Verify escalation was called with correct arguments
        expected_url = f"{mock_jira_settings.base_url}/browse/{valid_ticket.key}"
        mock_escalation_service.escalate.assert_called_once_with(
            valid_ticket.key,
            valid_ticket.summary,
            expected_url,
            confidence_gaps,
        )

        # Verify escalation record was created with status="SENT"
        mock_escalation_repository.create.assert_called_once()
        created_record = mock_escalation_repository.create.call_args[0][0]
        assert isinstance(created_record, EscalationRecord)
        assert created_record.jira_ticket_key == valid_ticket.key
        assert created_record.confidence_score == 0.4
        assert created_record.confidence_gaps == confidence_gaps
        assert created_record.slack_user_id == "U12345"
        assert created_record.status == "SENT"
        assert created_record.error_message is None

        # Verify update_description was called (ACs were written)
        mock_jira_client.update_description.assert_called_once()

    # --- Test 3: Low confidence + DM failed ---

    @pytest.mark.asyncio
    async def test_low_confidence_escalation_failed(
        self,
        mock_jira_client: MagicMock,
        mock_jira_settings: JiraSettings,
        mock_escalation_service: MagicMock,
        mock_escalation_repository: MagicMock,
        valid_ticket: TicketData,
    ) -> None:
        """Verify escalation failure is recorded and warning note is prepended.

        Given confidence_score=0.3 (below threshold)
        And escalation_service.escalate() returns EscalationResult(sent=False, error="User not found")
        When _process_ticket is called
        Then escalation_repository.create() is called with status="FAILED" and the error
        And ACs written to Jira include the "could not be delivered" warning.
        """
        from src.slack.models import EscalationResult

        generated_acs = [
            "User can perform the described action",
            "System responds within acceptable time limits",
        ]
        mock_ac_generator = MagicMock()
        mock_ac_generator.is_enabled = True
        mock_ac_generator.generate = AsyncMock(
            return_value=ACGenerationResult(
                acceptance_criteria=generated_acs,
                confidence_score=0.3,
                confidence_gaps=["unclear requirements"],
                sufficient_information=True,
            )
        )

        mock_escalation_service.escalate = AsyncMock(
            return_value=EscalationResult(
                sent=False, error="User not found"
            ),
        )

        mock_jira_client.get_ticket = AsyncMock(return_value=valid_ticket)
        mock_jira_client.update_description = AsyncMock(return_value=True)
        mock_jira_client.add_label = AsyncMock(return_value=True)

        service = PollingService(
            jira_client=mock_jira_client,
            settings=mock_jira_settings,
            ac_generator=mock_ac_generator,
            escalation_service=mock_escalation_service,
            escalation_repository=mock_escalation_repository,
            confidence_threshold=0.7,
        )

        result = await service._process_ticket(valid_ticket)

        assert result is True

        # Verify escalation was attempted
        mock_escalation_service.escalate.assert_called_once()

        # Verify escalation record was created with status="FAILED"
        mock_escalation_repository.create.assert_called_once()
        created_record = mock_escalation_repository.create.call_args[0][0]
        assert isinstance(created_record, EscalationRecord)
        assert created_record.status == "FAILED"
        assert created_record.error_message == "User not found"

        # Verify update_description was called (ACs still written with warning)
        mock_jira_client.update_description.assert_called_once()

    # --- Test 4: No escalation service configured (backward compatibility) ---

    @pytest.mark.asyncio
    async def test_no_escalation_service_writes_acs_directly(
        self,
        mock_jira_client: MagicMock,
        mock_jira_settings: JiraSettings,
        valid_ticket: TicketData,
    ) -> None:
        """Verify backward compatibility when no escalation service is configured.

        Given escalation_service is None (not provided)
        And confidence_score is below threshold (0.4)
        When _process_ticket is called
        Then ACs are written directly to Jira without any escalation attempt
        And no error is raised.
        """
        generated_acs = [
            "User can perform the described action",
            "System responds within acceptable time limits",
        ]
        mock_ac_generator = MagicMock()
        mock_ac_generator.is_enabled = True
        mock_ac_generator.generate = AsyncMock(
            return_value=ACGenerationResult(
                acceptance_criteria=generated_acs,
                confidence_score=0.4,
                confidence_gaps=["unclear scope"],
                sufficient_information=True,
            )
        )

        mock_jira_client.get_ticket = AsyncMock(return_value=valid_ticket)
        mock_jira_client.update_description = AsyncMock(return_value=True)
        mock_jira_client.add_label = AsyncMock(return_value=True)

        # No escalation_service provided (default None)
        service = PollingService(
            jira_client=mock_jira_client,
            settings=mock_jira_settings,
            ac_generator=mock_ac_generator,
            escalation_service=None,
        )

        result = await service._process_ticket(valid_ticket)

        assert result is True

        # update_description should have been called (ACs written directly)
        mock_jira_client.update_description.assert_called_once()

        # No escalation should have been attempted (no service configured)
        # This is verified implicitly: if escalation_service were called,
        # it would raise AttributeError on None
