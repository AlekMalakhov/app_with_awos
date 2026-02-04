# Task List: Write ACs Back to Jira (003)

## Completed Work

The following has already been implemented:
- AC formatter module (`src/jira/ac_formatter.py`) with all functions
- `update_description()` method in `JiraClient`
- `description_adf` field in `TicketData` model
- Unit tests (47 passing tests)

**Remaining work** focuses on integration and end-to-end verification.

---

## Vertical Slices

- [x] **Slice 1: Integrate AC write-back into PollingService (with hardcoded test ACs)**
  - [x] Sub-task: Update `_process_ticket()` in `src/polling/service.py` to import AC formatter functions and call the write-back flow after the AC generation placeholder. Use hardcoded test ACs for now (e.g., `["Test AC 1", "Test AC 2"]`). **[Agent: python-expert]**
  - [x] Sub-task: Ensure the integration handles the case where `validate_acs()` returns False (empty AC list). **[Agent: python-expert]**
  - [x] Sub-task: Run all existing unit tests to ensure no regressions: `uv run pytest tests/unit/ -v`. **[Agent: python-expert]**

- [x] **Slice 2: Manual integration test with real Jira ticket**
  - [x] Sub-task: Create a test ticket in Jira (or use an existing one) without the `ac-generated` label. **[Agent: qa-expert]**
  - [x] Sub-task: Run the application with polling enabled and observe logs to verify it discovers the ticket. **[Agent: qa-expert]**
  - [x] Sub-task: Verify the ticket description in Jira now contains the "## Acceptance Criteria" section with test ACs and attribution. **[Agent: qa-expert]**
  - [x] Sub-task: Verify the ticket has the `ac-generated` label added. **[Agent: qa-expert]**

- [x] **Slice 3: Verify append behavior (regeneration scenario)**
  - [x] Sub-task: Remove the `ac-generated` label from the test ticket (so it gets picked up again). **[Agent: qa-expert]**
  - [x] Sub-task: Run the polling cycle again. **[Agent: qa-expert]**
  - [x] Sub-task: Verify that new ACs are APPENDED below the existing ones (not replacing). **[Agent: qa-expert]**
  - [x] Sub-task: Verify each AC set has its own attribution timestamp. **[Agent: qa-expert]**

- [x] **Slice 4: Create automated integration test**
  - [x] Sub-task: Create `tests/integration/test_jira_write_integration.py` with test cases for write operations. Mark tests with `@pytest.mark.integration`. **[Agent: python-expert]**
  - [x] Sub-task: Add test `test_write_acs_to_real_ticket` - formats ACs, writes to test ticket, verifies via GET. **[Agent: python-expert]**
  - [x] Sub-task: Add test `test_append_acs_to_existing` - writes ACs twice, verifies both sets present. **[Agent: python-expert]**
  - [x] Sub-task: Run integration tests with real Jira credentials: `uv run pytest tests/integration/test_jira_write_integration.py -v`. **[Agent: qa-expert]**

---

## Prerequisites

| Requirement | Status |
|-------------|--------|
| `JIRA_API_TOKEN` | Configured |
| `JIRA_USER_EMAIL` | Configured |
| `JIRA_BASE_URL` | Configured |
| `JIRA_PROJECT_KEY` | Configured (IGAL) |
| `JIRA_POLLING_ENABLED` | Configured (true) |
