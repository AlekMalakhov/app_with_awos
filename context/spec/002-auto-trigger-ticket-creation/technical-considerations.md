# Technical Specification: Automatic Trigger on Ticket Creation

- **Functional Specification:** `context/spec/002-auto-trigger-ticket-creation/functional-spec.md`
- **Status:** Completed
- **Author(s):** Technical Architect

---

## 1. High-Level Technical Approach

This specification implements a background polling service that automatically discovers new Jira tickets and invokes AC generation. The solution uses:

- **asyncio background task** integrated with FastAPI lifespan for polling
- **Extended JiraSettings** with polling-specific configuration (project key, interval, enabled flag)
- **New JiraClient methods** for JQL search and label management
- **In-memory failure tracking** to manage retry limits per ticket
- **Existing retry patterns** from JiraClient (tenacity, exponential backoff)

The implementation creates a new `src/polling/` module containing the polling service, while extending the existing Jira module with search and label capabilities.

---

## 2. Proposed Solution & Implementation Plan (The "How")

### 2.1 Configuration Changes

**File:** `src/jira/config.py`

Extend `JiraSettings` with polling configuration:

```python
class JiraSettings(BaseSettings):
    # Existing fields...
    base_url: str
    user_email: str
    api_token: str
    issue_types: str = "Story,Task"
    max_retries: int = 3

    # New polling fields
    project_key: str = ""                    # JIRA_PROJECT_KEY (required if polling enabled)
    polling_enabled: bool = False            # JIRA_POLLING_ENABLED (default: disabled)
    polling_interval_seconds: int = 300      # JIRA_POLLING_INTERVAL_SECONDS (5 min)
    polling_lookback_days: int = 7           # JIRA_POLLING_LOOKBACK_DAYS
    polling_max_failures: int = 3            # JIRA_POLLING_MAX_FAILURES
```

**Environment Variables:**
| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `JIRA_PROJECT_KEY` | str | (required) | Jira project key (e.g., "IGAL") |
| `JIRA_POLLING_ENABLED` | bool | false | Enable/disable polling service |
| `JIRA_POLLING_INTERVAL_SECONDS` | int | 300 | Polling interval (5 minutes) |
| `JIRA_POLLING_LOOKBACK_DAYS` | int | 7 | How far back to look for tickets |
| `JIRA_POLLING_MAX_FAILURES` | int | 3 | Failures before adding `ac-generation-failed` label |

### 2.2 JiraClient Extensions

**File:** `src/jira/client.py`

Add two new methods:

```python
async def search_tickets(self, jql: str, max_results: int = 50) -> list[TicketData]:
    """Search for tickets using JQL query.

    Uses the Agile board API endpoint (since JQL search returned 0 results in testing).
    Alternatively, uses /rest/api/3/search/jql endpoint.

    Returns:
        List of TicketData objects matching the query.
    """

async def add_label(self, issue_key: str, label: str) -> bool:
    """Add a label to a Jira ticket.

    Args:
        issue_key: The ticket key (e.g., "IGAL-123")
        label: The label to add (e.g., "ac-generated")

    Returns:
        True if successful, False if label addition failed.
    """
```

**API Endpoints Used:**
| Operation | Method | Endpoint |
|-----------|--------|----------|
| Search tickets | GET | `/rest/api/3/search/jql?jql={jql}&maxResults={n}` |
| Add label | PUT | `/rest/api/3/issue/{key}` with `{"update": {"labels": [{"add": "{label}"}]}}` |

### 2.3 Polling Service Module

**New Files:**
```
src/
└── polling/
    ├── __init__.py
    ├── service.py      # PollingService class
    └── models.py       # TicketProcessingResult model (optional)
```

**File:** `src/polling/service.py`

```python
class PollingService:
    """Background service that polls Jira for unprocessed tickets."""

    def __init__(
        self,
        jira_client: JiraClient,
        settings: JiraSettings,
        ac_generator: ACGeneratorProtocol | None = None,  # Placeholder for future
    ):
        self._client = jira_client
        self._settings = settings
        self._ac_generator = ac_generator
        self._failure_counts: dict[str, int] = {}  # In-memory failure tracking
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the polling loop as a background task."""

    async def stop(self) -> None:
        """Gracefully stop the polling loop."""

    async def _poll_cycle(self) -> None:
        """Execute a single polling cycle."""

    def _build_jql(self) -> str:
        """Build the JQL query for ticket discovery."""
        # project = {PROJECT} AND issuetype in ({TYPES})
        # AND labels not in ("ac-generated", "ac-generation-failed")
        # AND created >= -{lookback}d
        # ORDER BY created ASC

    async def _process_ticket(self, ticket: TicketData) -> bool:
        """Process a single ticket through the AC generation pipeline."""

    def _has_existing_acs(self, description: str) -> bool:
        """Check if description already contains an '## Acceptance Criteria' section."""

    def _record_failure(self, ticket_key: str) -> int:
        """Record a failure and return the new failure count."""

    def _clear_failure(self, ticket_key: str) -> None:
        """Clear failure count for a successfully processed ticket."""
```

**Polling Cycle Logic:**
```
1. Build JQL query
2. Search for matching tickets
3. For each ticket:
   a. Fetch full details (if needed)
   b. Check prerequisites:
      - Has description? (skip if empty)
      - Has existing ACs section? (skip if yes)
   c. If eligible:
      - Invoke AC generation (placeholder for now)
      - On success: add "ac-generated" label, clear failures
      - On failure: increment failure count
        - If failures >= max: add "ac-generation-failed" label
4. Log cycle summary
5. Sleep for interval
```

### 2.4 FastAPI Integration

**File:** `src/main.py`

Modify the lifespan context manager:

```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Existing startup...
    settings = JiraSettings()
    jira_client = JiraClient(settings)
    await jira_client.validate_connection()

    # NEW: Start polling service if enabled
    polling_service = None
    if settings.polling_enabled:
        if not settings.project_key:
            logger.error("JIRA_PROJECT_KEY required when polling is enabled")
            sys.exit(1)

        polling_service = PollingService(jira_client, settings)
        await polling_service.start()
        logger.info(f"Polling service started (interval: {settings.polling_interval_seconds}s)")

    app.state.jira_client = jira_client
    app.state.polling_service = polling_service

    yield

    # Shutdown
    if polling_service:
        await polling_service.stop()
        logger.info("Polling service stopped")
    await jira_client.close()
```

### 2.5 Module Exports

**File:** `src/polling/__init__.py`
```python
from src.polling.service import PollingService

__all__ = ["PollingService"]
```

**File:** `src/jira/__init__.py` (update)
```python
# Add to existing exports
__all__ = [
    # ... existing
    "JiraClient",  # Already exported
]
```

---

## 3. Impact and Risk Analysis

### System Dependencies

| Dependency | Impact |
|------------|--------|
| JiraClient | Extended with `search_tickets()` and `add_label()` methods |
| JiraSettings | Extended with polling configuration fields |
| FastAPI lifespan | Modified to start/stop polling service |
| Existing tests | May need updates for new JiraSettings fields |

### Potential Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Jira API rate limiting | Medium | High | Use 5-min interval, existing retry/backoff |
| Polling task crashes | Low | Medium | Wrap in try/except, log errors, continue |
| Memory leak (failure dict) | Low | Low | Dict only grows for failing tickets, cleared on success |
| JQL search returns 0 (permission issue) | Medium | High | Test with real credentials, fallback to board API if needed |
| AC generation not yet implemented | Expected | None | Placeholder that logs and returns success |
| Long-running poll blocks next cycle | Low | Medium | Skip overlap if previous cycle still running |

---

## 4. Testing Strategy

### Unit Tests

**File:** `tests/unit/test_polling_service.py`

| Test Case | Description |
|-----------|-------------|
| `test_polling_disabled_does_not_start` | Verify service doesn't start when disabled |
| `test_poll_cycle_discovers_tickets` | Mock JQL search, verify tickets processed |
| `test_skip_ticket_without_description` | Verify empty description tickets are skipped |
| `test_skip_ticket_with_existing_acs` | Verify tickets with AC section are skipped |
| `test_success_adds_label` | Verify `ac-generated` label added on success |
| `test_failure_increments_count` | Verify failure count tracking works |
| `test_max_failures_adds_failed_label` | Verify `ac-generation-failed` after 3 failures |
| `test_graceful_shutdown` | Verify task cancellation and cleanup |

**File:** `tests/unit/test_jira_client_search.py`

| Test Case | Description |
|-----------|-------------|
| `test_search_tickets_returns_list` | Mock JQL response, verify TicketData list |
| `test_search_tickets_empty_results` | Verify empty list returned for 0 matches |
| `test_add_label_success` | Mock PUT response, verify True returned |
| `test_add_label_failure` | Mock error response, verify False returned |

### Integration Tests

**File:** `tests/integration/test_polling_integration.py`

| Test Case | Description |
|-----------|-------------|
| `test_real_jql_search` | Search real Jira with test credentials |
| `test_real_add_label` | Add/remove test label on real ticket |

---

## 5. File Summary

| File | Action | Description |
|------|--------|-------------|
| `src/jira/config.py` | Modify | Add polling configuration fields |
| `src/jira/client.py` | Modify | Add `search_tickets()` and `add_label()` methods |
| `src/polling/__init__.py` | Create | Module exports |
| `src/polling/service.py` | Create | PollingService class |
| `src/main.py` | Modify | Integrate polling with lifespan |
| `tests/unit/test_jira_config.py` | Modify | Add tests for new config fields |
| `tests/unit/test_jira_client.py` | Modify | Add tests for new client methods |
| `tests/unit/test_polling_service.py` | Create | Unit tests for PollingService |
| `tests/integration/test_polling_integration.py` | Create | Integration tests |
