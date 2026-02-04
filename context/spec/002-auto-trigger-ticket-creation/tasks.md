# Task List: Automatic Trigger on Ticket Creation

**Spec:** `002-auto-trigger-ticket-creation`
**Status:** Implementation Complete
**Designated Test Ticket:** [IGAL-1926](https://provectus-dev.atlassian.net/browse/IGAL-1926)

> **Safety Note:** All E2E and integration tests that modify Jira must use only the designated test ticket `IGAL-1926` to protect the production board.

---

## Slice 1: Polling Configuration
**Goal:** Extend JiraSettings with polling configuration so the system can be configured. App remains runnable with new optional config fields.

- [x] **Sub-task 1.1:** Add polling configuration fields to `JiraSettings` in `src/jira/config.py` (`project_key`, `polling_enabled`, `polling_interval_seconds`, `polling_lookback_days`, `polling_max_failures`) with appropriate defaults. **[Agent: python-expert]**
- [x] **Sub-task 1.2:** Add unit tests for new configuration fields in `tests/unit/test_jira_config.py` (test defaults, test env var loading). **[Agent: python-expert]**
- [x] **Sub-task 1.3:** Run `pytest tests/unit/test_jira_config.py -v` and verify all tests pass. **[Agent: qa-expert]**

---

## Slice 2: JQL Search Capability
**Goal:** Add `search_tickets()` method to JiraClient. App remains runnable; new method is available for use.

- [x] **Sub-task 2.1:** Add `search_tickets(jql: str, max_results: int = 50) -> list[TicketData]` method to `JiraClient` in `src/jira/client.py` with retry logic matching existing patterns. **[Agent: python-expert]**
- [x] **Sub-task 2.2:** Add unit tests for `search_tickets()` in `tests/unit/test_jira_client.py` (success with results, empty results, 5xx retry, 401/403 auth error). **[Agent: python-expert]**
- [x] **Sub-task 2.3:** Run `pytest tests/unit/test_jira_client.py -v -k search` and verify all tests pass. **[Agent: qa-expert]**

---

## Slice 3: Label Management Capability
**Goal:** Add `add_label()` method to JiraClient. App remains runnable; method available for marking tickets.

- [x] **Sub-task 3.1:** Add `add_label(issue_key: str, label: str) -> bool` method to `JiraClient` in `src/jira/client.py` using PUT `/rest/api/3/issue/{key}` with `{"update": {"labels": [{"add": "{label}"}]}}`. **[Agent: python-expert]**
- [x] **Sub-task 3.2:** Add unit tests for `add_label()` in `tests/unit/test_jira_client.py` (success returns True, failure returns False, does not raise). **[Agent: python-expert]**
- [x] **Sub-task 3.3:** Run `pytest tests/unit/test_jira_client.py -v -k label` and verify all tests pass. **[Agent: qa-expert]**

---

## Slice 4: Polling Service Skeleton with Lifecycle
**Goal:** Create PollingService class with start/stop lifecycle. App can start with polling disabled (default).

- [x] **Sub-task 4.1:** Create `src/polling/__init__.py` exporting `PollingService`. **[Agent: python-expert]**
- [x] **Sub-task 4.2:** Create `src/polling/service.py` with `PollingService` class: `__init__`, `start()`, `stop()` methods using asyncio task management. **[Agent: python-expert]**
- [x] **Sub-task 4.3:** Create `tests/unit/test_polling_service.py` with tests for start/stop lifecycle (verify task created on start, cancelled on stop). **[Agent: python-expert]**
- [x] **Sub-task 4.4:** Run `pytest tests/unit/test_polling_service.py -v` and verify all tests pass. **[Agent: qa-expert]**

---

## Slice 5: JQL Query Building
**Goal:** Implement `_build_jql()` to construct discovery query. Polling service can build valid JQL.

- [x] **Sub-task 5.1:** Implement `_build_jql() -> str` method in `PollingService` that constructs JQL: `project = {PROJECT} AND issuetype in ({TYPES}) AND labels not in ("ac-generated", "ac-generation-failed") AND created >= -{lookback}d ORDER BY created ASC`. **[Agent: python-expert]**
- [x] **Sub-task 5.2:** Add unit tests for `_build_jql()` verifying correct JQL construction with various settings. **[Agent: python-expert]**
- [x] **Sub-task 5.3:** Run `pytest tests/unit/test_polling_service.py -v -k jql` and verify tests pass. **[Agent: qa-expert]**

---

## Slice 6: Poll Cycle with Ticket Discovery
**Goal:** Implement `_poll_cycle()` to discover tickets and log them. Service discovers tickets each cycle.

- [x] **Sub-task 6.1:** Implement `_poll_cycle()` method that calls `_build_jql()`, executes `search_tickets()`, and logs discovered ticket count. **[Agent: python-expert]**
- [x] **Sub-task 6.2:** Add overlap prevention: skip cycle if previous cycle still running (use `_running` flag). **[Agent: python-expert]**
- [x] **Sub-task 6.3:** Add unit tests for poll cycle (mock search, verify logging, verify overlap skip). **[Agent: python-expert]**
- [x] **Sub-task 6.4:** Run `pytest tests/unit/test_polling_service.py -v -k poll_cycle` and verify tests pass. **[Agent: qa-expert]**

---

## Slice 7: Prerequisite Validation
**Goal:** Implement ticket validation to skip ineligible tickets. Service filters tickets correctly.

- [x] **Sub-task 7.1:** Implement `_has_existing_acs(description: str) -> bool` that checks for `## Acceptance Criteria` section (case-insensitive). **[Agent: python-expert]**
- [x] **Sub-task 7.2:** Implement `_process_ticket()` with prerequisite checks: skip if description empty, skip if has existing ACs. Log skip reasons. **[Agent: python-expert]**
- [x] **Sub-task 7.3:** Add unit tests for prerequisite validation (empty description skipped, existing ACs skipped, valid ticket proceeds). **[Agent: python-expert]**
- [x] **Sub-task 7.4:** Run `pytest tests/unit/test_polling_service.py -v -k prerequisite` and verify tests pass. **[Agent: qa-expert]**

---

## Slice 8: Successful Processing with Label
**Goal:** On successful processing, add `ac-generated` label. Complete success flow works.

- [x] **Sub-task 8.1:** Implement placeholder AC generation in `_process_ticket()` (log "AC generation placeholder" and return success). **[Agent: python-expert]**
- [x] **Sub-task 8.2:** On success, call `add_label(ticket.key, "ac-generated")`. Log success with timestamp. **[Agent: python-expert]**
- [x] **Sub-task 8.3:** Add unit tests for success flow (mock AC generation success, verify label added, verify logging). **[Agent: python-expert]**
- [x] **Sub-task 8.4:** Run `pytest tests/unit/test_polling_service.py -v -k success` and verify tests pass. **[Agent: qa-expert]**

---

## Slice 9: Failure Tracking and Max Failures
**Goal:** Track failures per ticket and add `ac-generation-failed` label after max failures.

- [x] **Sub-task 9.1:** Implement `_record_failure(ticket_key: str) -> int` and `_clear_failure(ticket_key: str)` for in-memory failure tracking. **[Agent: python-expert]**
- [x] **Sub-task 9.2:** On failure, increment count. If count >= `polling_max_failures`, add `ac-generation-failed` label. **[Agent: python-expert]**
- [x] **Sub-task 9.3:** On success, clear failure count for that ticket. **[Agent: python-expert]**
- [x] **Sub-task 9.4:** Add unit tests for failure tracking (count increments, max failures triggers label, success clears count). **[Agent: python-expert]**
- [x] **Sub-task 9.5:** Run `pytest tests/unit/test_polling_service.py -v -k failure` and verify tests pass. **[Agent: qa-expert]**

---

## Slice 10: FastAPI Lifespan Integration
**Goal:** Integrate PollingService with FastAPI startup/shutdown. App starts polling when enabled.

- [x] **Sub-task 10.1:** Modify `src/main.py` lifespan: if `settings.polling_enabled`, create and start `PollingService`. **[Agent: python-expert]**
- [x] **Sub-task 10.2:** Add validation: exit with error if `polling_enabled=True` but `project_key` is empty. **[Agent: python-expert]**
- [x] **Sub-task 10.3:** On shutdown, call `polling_service.stop()` if service was started. **[Agent: python-expert]**
- [x] **Sub-task 10.4:** Store `polling_service` in `app.state` for access if needed. **[Agent: python-expert]**
- [x] **Sub-task 10.5:** Update `tests/unit/test_main.py` with tests for polling integration (enabled starts service, disabled does not, missing project_key exits). **[Agent: python-expert]**
- [x] **Sub-task 10.6:** Run `pytest tests/unit/test_main.py -v` and verify all tests pass. **[Agent: qa-expert]**

---

## Slice 11: Integration Testing
**Goal:** Verify end-to-end behavior against real Jira using designated test ticket.

**Test Ticket:** [IGAL-1926](https://provectus-dev.atlassian.net/browse/IGAL-1926)

- [x] **Sub-task 11.1:** Create `tests/integration/test_polling_integration.py` with `test_real_jql_search()` that searches real Jira. **[Agent: python-expert]**
- [x] **Sub-task 11.2:** Add `test_real_add_remove_label()` that adds and removes a test label on ticket `IGAL-1926`. **[Agent: python-expert]**
- [x] **Sub-task 11.3:** Add docstring documenting required environment variables and how to run integration tests. **[Agent: python-expert]**
- [x] **Sub-task 11.4:** Run integration tests with real credentials and verify behavior against `IGAL-1926`. **[Agent: qa-expert]**
- [x] **Sub-task 11.5:** Using Atlassian MCP, verify the labels are visible on test ticket `IGAL-1926` after processing. **[Agent: qa-expert]**
