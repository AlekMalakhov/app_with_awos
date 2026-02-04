# Technical Specification: Jira API Connection

- **Functional Specification:** `context/spec/001-jira-api-connection/functional-spec.md`
- **Status:** Completed
- **Author(s):** Technical Architect

---

## 1. High-Level Technical Approach

This specification implements the foundational Jira integration layer for the AC Assistant. The solution uses:

- **httpx** as the async HTTP client (native async support for FastAPI)
- **tenacity** for exponential backoff retry logic
- **Pydantic Settings** for type-safe configuration management
- **FastAPI lifespan** context for startup credential validation

The implementation creates a dedicated `src/jira/` module containing configuration, client, exceptions, and data models. On startup, the application validates Jira credentials and fails fast if they are invalid, preventing the system from running in a broken state.

---

## 2. Proposed Solution & Implementation Plan (The "How")

### 2.1 Project Structure

```
src/
├── main.py                     # FastAPI app with lifespan startup validation
└── jira/
    ├── __init__.py             # Module exports
    ├── config.py               # JiraSettings (pydantic-settings)
    ├── client.py               # JiraClient (httpx + tenacity retry)
    ├── exceptions.py           # Custom exception hierarchy
    └── models.py               # TicketData Pydantic model

tests/
├── conftest.py                 # Shared fixtures
├── unit/
│   ├── test_jira_client.py     # Client methods with mocked HTTP
│   ├── test_jira_config.py     # Configuration validation
│   └── test_jira_exceptions.py # Exception handling
└── integration/
    └── test_jira_integration.py  # Real Jira connection (skipped in CI)
```

### 2.2 Configuration (src/jira/config.py)

```python
from pydantic_settings import BaseSettings

class JiraSettings(BaseSettings):
    base_url: str                        # JIRA_BASE_URL (e.g., https://company.atlassian.net)
    user_email: str                      # JIRA_USER_EMAIL
    api_token: str                       # JIRA_API_TOKEN
    issue_types: str = "Story,Task"      # JIRA_ISSUE_TYPES (comma-separated)
    max_retries: int = 3                 # JIRA_MAX_RETRIES

    class Config:
        env_prefix = "JIRA_"

    @property
    def issue_types_list(self) -> list[str]:
        return [t.strip() for t in self.issue_types.split(",")]
```

**Environment Variables:**
| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `JIRA_BASE_URL` | Yes | - | Jira Cloud instance URL |
| `JIRA_USER_EMAIL` | Yes | - | API user email |
| `JIRA_API_TOKEN` | Yes | - | API token (from Atlassian account) |
| `JIRA_ISSUE_TYPES` | No | `Story,Task` | Comma-separated issue types to process |
| `JIRA_MAX_RETRIES` | No | `3` | Maximum retry attempts |

### 2.3 Exception Hierarchy (src/jira/exceptions.py)

```python
class JiraError(Exception):
    """Base exception for all Jira operations"""

class JiraAuthenticationError(JiraError):
    """Raised when credentials are invalid or missing (401/403)"""

class JiraConnectionError(JiraError):
    """Raised when Jira is unreachable after retries exhausted"""

class JiraTicketNotFoundError(JiraError):
    """Raised when the requested ticket does not exist (404)"""

class JiraIssueTypeNotSupportedError(JiraError):
    """Raised when ticket's issue type is not in configured list"""
```

### 2.4 Data Models (src/jira/models.py)

```python
from pydantic import BaseModel

class TicketData(BaseModel):
    key: str                    # e.g., "PROJ-123"
    summary: str                # Ticket title
    description: str            # Ticket description (empty string if null)
    issue_type: str             # e.g., "Story", "Task"
```

### 2.5 Jira Client (src/jira/client.py)

**Key Responsibilities:**
1. Authenticate with Jira using Basic Auth (email + API token)
2. Provide `validate_connection()` method for startup check
3. Provide `get_ticket(issue_key)` method to read ticket data
4. Implement exponential backoff retry for transient failures

**API Endpoints Used:**
| Operation | Method | Endpoint | Purpose |
|-----------|--------|----------|---------|
| Validate credentials | GET | `/rest/api/3/myself` | Lightweight auth check |
| Get ticket | GET | `/rest/api/3/issue/{key}?fields=summary,description,issuetype` | Read ticket data |

**Retry Logic (tenacity):**
- **Retryable errors:** 5xx, 429 (rate limit), timeout, connection errors
- **Non-retryable errors:** 4xx (except 429) — fail immediately
- **Max retries:** Configurable (default 3)
- **Backoff delays:** 1s, 4s, 16s (exponential: `4^attempt` seconds)

```python
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

retry_config = retry(
    stop=stop_after_attempt(settings.max_retries),
    wait=wait_exponential(multiplier=1, min=1, max=16),
    retry=retry_if_exception(is_retryable_error)
)
```

### 2.6 Startup Validation (src/main.py)

Use FastAPI's lifespan context manager to validate credentials on startup:

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
import sys

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: validate Jira connection
    try:
        await jira_client.validate_connection()
        logger.info("Jira connection validated successfully")
    except JiraAuthenticationError as e:
        logger.error(f"Jira authentication failed: {e}")
        sys.exit(1)
    except JiraConnectionError as e:
        logger.error(f"Jira unreachable: {e}")
        sys.exit(1)

    yield  # Application runs

    # Shutdown: cleanup if needed
    await jira_client.close()

app = FastAPI(lifespan=lifespan)
```

---

## 3. Impact and Risk Analysis

### 3.1 System Dependencies

| Dependency | Impact |
|------------|--------|
| **Jira Cloud API** | Core dependency; if unavailable, ticket reading fails |
| **Network connectivity** | Required for all operations |
| **Environment variables** | Must be set before startup |

### 3.2 Potential Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| **Jira API rate limiting (429)** | Medium | Medium | Exponential backoff with configurable retries handles rate limits gracefully |
| **Credentials exposed in logs** | Low | High | Never log API token; mask sensitive values in error messages |
| **Jira Cloud outage at startup** | Low | High | Fail-fast prevents broken state; document restart procedure |
| **Invalid credentials deployed** | Medium | High | Startup validation catches immediately; clear error message guides resolution |
| **Large ticket descriptions** | Low | Low | No explicit limit needed; httpx handles large responses |

---

## 4. Testing Strategy

### 4.1 Unit Tests (tests/unit/)

All unit tests mock HTTP responses using `pytest-httpx`:

| Test File | Coverage |
|-----------|----------|
| `test_jira_config.py` | Config validation, defaults, issue_types parsing |
| `test_jira_client.py` | Auth header generation, API calls, retry logic, error handling |
| `test_jira_exceptions.py` | Exception hierarchy, error messages |

**Key Test Cases:**
- Valid credentials → successful connection
- Invalid credentials → `JiraAuthenticationError` raised
- Ticket exists → returns `TicketData` with summary and description
- Ticket not found → `JiraTicketNotFoundError` raised
- Empty description → returns empty string (not error)
- Unsupported issue type → `JiraIssueTypeNotSupportedError` raised
- 5xx error → retries 3 times then fails
- 429 rate limit → retries with backoff
- 4xx error (not 429) → fails immediately without retry

### 4.2 Integration Tests (tests/integration/)

Real Jira connection tests, skipped in CI (require valid credentials):

```python
@pytest.mark.integration
@pytest.mark.skipif(not os.getenv("JIRA_API_TOKEN"), reason="No Jira credentials")
async def test_real_jira_connection():
    # Test against actual Jira instance
```

**Test Cases:**
- Validate connection with real credentials
- Read an existing ticket
- Handle non-existent ticket

### 4.3 Dependencies

```
pytest>=7.4.0
pytest-asyncio>=0.21.0
pytest-httpx>=0.27.0
pytest-cov>=4.1.0
```
