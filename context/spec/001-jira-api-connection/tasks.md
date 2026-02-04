# Tasks: Jira API Connection

## Slice 1: Project Foundation & Configuration
The smallest piece of user-visible value: the application starts and loads Jira configuration from environment variables.

- [x] **Sub-task 1.1:** Create the `src/jira/` module directory structure with `__init__.py`. **[Agent: general-purpose]**
- [x] **Sub-task 1.2:** Implement `src/jira/config.py` with `JiraSettings` Pydantic Settings class that reads `JIRA_BASE_URL`, `JIRA_USER_EMAIL`, `JIRA_API_TOKEN`, `JIRA_ISSUE_TYPES` (default: "Story,Task"), and `JIRA_MAX_RETRIES` (default: 3). Include the `issue_types_list` property. **[Agent: general-purpose]**
- [x] **Sub-task 1.3:** Write unit tests in `tests/unit/test_jira_config.py` to verify config validation, defaults, and `issue_types` parsing. **[Agent: general-purpose]**
- [x] **Sub-task 1.4:** Run the tests to verify configuration loading works correctly. **[Agent: qa-expert]**

---

## Slice 2: Exception Hierarchy
Establish clear error handling before implementing the client.

- [x] **Sub-task 2.1:** Implement `src/jira/exceptions.py` with the exception hierarchy: `JiraError`, `JiraAuthenticationError`, `JiraConnectionError`, `JiraTicketNotFoundError`, `JiraIssueTypeNotSupportedError`. **[Agent: general-purpose]**
- [x] **Sub-task 2.2:** Write unit tests in `tests/unit/test_jira_exceptions.py` to verify exception inheritance and error messages. **[Agent: general-purpose]**
- [x] **Sub-task 2.3:** Run the tests to verify exceptions work correctly. **[Agent: qa-expert]**

---

## Slice 3: Data Models
Define the data structures for ticket information.

- [x] **Sub-task 3.1:** Implement `src/jira/models.py` with the `TicketData` Pydantic model containing `key`, `summary`, `description`, and `issue_type` fields. **[Agent: general-purpose]**
- [x] **Sub-task 3.2:** Update `src/jira/__init__.py` to export `JiraSettings`, exceptions, and `TicketData`. **[Agent: general-purpose]**
- [x] **Sub-task 3.3:** Write a basic unit test to verify `TicketData` model instantiation and validation. **[Agent: general-purpose]**

---

## Slice 4: Jira Client - Connection Validation
The first end-to-end testable piece: validate that we can authenticate with Jira.

- [x] **Sub-task 4.1:** Implement `src/jira/client.py` with `JiraClient` class that:
  - Uses `httpx.AsyncClient` for HTTP calls
  - Generates Basic Auth header from email + API token
  - Implements `validate_connection()` method that calls `GET /rest/api/3/myself`
  - Raises `JiraAuthenticationError` on 401/403
  - Raises `JiraConnectionError` on network/timeout errors
  **[Agent: general-purpose]**
- [x] **Sub-task 4.2:** Write unit tests in `tests/unit/test_jira_client.py` using `pytest-httpx` to mock:
  - Successful authentication (200 response)
  - Invalid credentials (401 → `JiraAuthenticationError`)
  - Forbidden (403 → `JiraAuthenticationError`)
  - Connection error → `JiraConnectionError`
  **[Agent: general-purpose]**
- [x] **Sub-task 4.3:** Run the unit tests to verify connection validation works. **[Agent: qa-expert]**

---

## Slice 5: Jira Client - Retry Logic
Add resilience for transient failures.

- [x] **Sub-task 5.1:** Add tenacity retry decorator to `JiraClient` with:
  - Max retries from config (default 3)
  - Exponential backoff: 1s, 4s, 16s
  - Retry on: 5xx, 429, timeout, connection errors
  - No retry on: 4xx (except 429)
  **[Agent: general-purpose]**
- [x] **Sub-task 5.2:** Write unit tests to verify:
  - 5xx error retries 3 times then fails with `JiraConnectionError`
  - 429 rate limit retries with backoff
  - 4xx error (not 429) fails immediately without retry
  **[Agent: general-purpose]**
- [x] **Sub-task 5.3:** Run the retry logic tests. **[Agent: qa-expert]**

---

## Slice 6: Jira Client - Read Ticket Data
The core feature: reading ticket summary and description.

- [x] **Sub-task 6.1:** Implement `get_ticket(issue_key: str)` method in `JiraClient` that:
  - Calls `GET /rest/api/3/issue/{key}?fields=summary,description,issuetype`
  - Parses response into `TicketData` model
  - Returns empty string for null/missing description
  - Raises `JiraTicketNotFoundError` on 404
  - Checks issue type against configured list, raises `JiraIssueTypeNotSupportedError` if not in list
  **[Agent: general-purpose]**
- [x] **Sub-task 6.2:** Write unit tests for `get_ticket()`:
  - Ticket exists → returns `TicketData` with summary and description
  - Ticket not found (404) → `JiraTicketNotFoundError`
  - Empty/null description → returns empty string
  - Unsupported issue type → `JiraIssueTypeNotSupportedError`
  - Issue type in configured list → success
  **[Agent: general-purpose]**
- [x] **Sub-task 6.3:** Run the ticket reading tests. **[Agent: qa-expert]**

---

## Slice 7: Startup Validation with FastAPI Lifespan
Make the application fail-fast on invalid credentials.

- [x] **Sub-task 7.1:** Update `src/main.py` to add FastAPI lifespan context manager that:
  - Calls `jira_client.validate_connection()` on startup
  - Logs "Jira connection validated successfully" on success
  - Logs clear error and exits with non-zero code on `JiraAuthenticationError`
  - Logs clear error and exits with non-zero code on `JiraConnectionError`
  - Calls `jira_client.close()` on shutdown
  **[Agent: general-purpose]**
- [x] **Sub-task 7.2:** Update `src/jira/__init__.py` to export `JiraClient`. **[Agent: general-purpose]**
- [x] **Sub-task 7.3:** Write tests to verify startup behavior:
  - Valid credentials → app starts, logs success message
  - Invalid credentials → app logs error and exits with non-zero code
  - Jira unreachable → app logs error and exits with non-zero code
  **[Agent: general-purpose]**
- [x] **Sub-task 7.4:** Run the startup validation tests. **[Agent: qa-expert]**

---

## Slice 8: Integration Tests (Optional - requires real Jira credentials)
Real-world validation against an actual Jira instance.

- [x] **Sub-task 8.1:** Create `tests/integration/test_jira_integration.py` with:
  - `@pytest.mark.integration` marker
  - Skip if `JIRA_API_TOKEN` not set
  - Test real connection validation
  - Test reading an existing ticket
  - Test handling non-existent ticket
  **[Agent: general-purpose]**
- [x] **Sub-task 8.2:** Update `tests/conftest.py` with shared fixtures for integration tests. **[Agent: general-purpose]**
- [x] **Sub-task 8.3:** If real Jira credentials are available, run integration tests to verify end-to-end functionality. **[Agent: qa-expert]**

---

## Slice 9: Final Verification
Ensure everything works together.

- [x] **Sub-task 9.1:** Run the full test suite to ensure all tests pass. **[Agent: qa-expert]**
- [x] **Sub-task 9.2:** Start the application with valid mock/real credentials to verify it starts successfully and logs the connection message. **[Agent: qa-expert]**
- [x] **Sub-task 9.3:** Start the application with invalid credentials to verify it fails fast with a clear error message. **[Agent: qa-expert]**
