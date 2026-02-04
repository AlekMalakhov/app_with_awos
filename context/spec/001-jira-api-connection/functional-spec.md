# Functional Specification: Jira API Connection

- **Roadmap Item:** Establish secure connection to read ticket descriptions from Stories and Tasks
- **Status:** Completed
- **Author:** Poe (Product Analyst)

---

## 1. Overview and Rationale (The "Why")

### Purpose
This specification defines the foundational Jira integration capability that enables the Jira AC Assistant to securely connect to Jira Cloud and read ticket information. Without this capability, no subsequent features (AC generation, writing back to Jira, triggers) can function.

### Problem Being Solved
Development teams need automated access to Jira ticket content to generate acceptance criteria. Currently, there is no programmatic connection between the AC Assistant and Jira, making it impossible to read ticket descriptions for processing.

### Desired Outcome
A secure, reliable connection to Jira Cloud that can:
- Authenticate using API token credentials
- Read ticket summaries and descriptions from configurable issue types
- Handle connection failures gracefully with retry logic
- Validate credentials on application startup

### Success Criteria
- The system successfully connects to Jira Cloud using provided credentials
- Ticket data (summary + description) can be retrieved for any configured issue type
- Invalid credentials are detected at startup, preventing the application from running in a broken state
- Transient API failures are handled with automatic retry

---

## 2. Functional Requirements (The "What")

### FR-1: Jira Authentication
The system must authenticate with Jira Cloud using API token authentication.

**Acceptance Criteria:**
- [x] The system accepts Jira credentials via environment variables: `JIRA_BASE_URL`, `JIRA_USER_EMAIL`, `JIRA_API_TOKEN`
- [x] When valid credentials are provided, the system successfully authenticates with Jira Cloud
- [x] When invalid credentials are provided, authentication fails with a clear error message

### FR-2: Startup Credential Validation
The system must validate Jira credentials on startup and fail fast if they are invalid.

**Acceptance Criteria:**
- [x] On application startup, the system attempts to authenticate with Jira using configured credentials
- [x] If credentials are valid, the system starts normally and logs "Jira connection validated successfully"
- [x] If credentials are invalid or missing, the system logs a clear error message and exits with a non-zero exit code
- [x] If Jira is unreachable at startup (network issue), the system logs the error and exits with a non-zero exit code

### FR-3: Read Ticket Data
The system must be able to read the summary and description fields from Jira tickets.

**Acceptance Criteria:**
- [x] Given a valid Jira ticket key (e.g., "PROJ-123"), the system retrieves the ticket's summary field
- [x] Given a valid Jira ticket key, the system retrieves the ticket's description field
- [x] If the ticket does not exist, the system returns a clear "ticket not found" error
- [x] If the description field is empty or null, the system returns an empty string (not an error)

### FR-4: Configurable Issue Types
The system must only process tickets of configured issue types.

**Acceptance Criteria:**
- [x] The system accepts a comma-separated list of issue types via environment variable: `JIRA_ISSUE_TYPES` (e.g., "Story,Task")
- [x] If `JIRA_ISSUE_TYPES` is not set, the system defaults to "Story,Task"
- [x] When reading a ticket, the system checks if the ticket's issue type is in the configured list
- [x] If the ticket's issue type is not in the configured list, the system returns an "issue type not supported" response (not an error)

### FR-5: Retry Logic for API Failures
The system must implement exponential backoff retry for transient Jira API failures.

**Acceptance Criteria:**
- [x] When a Jira API call fails due to a transient error (5xx, timeout, connection reset), the system retries the request
- [x] The system retries a maximum of 3 times with delays of 1 second, 4 seconds, and 16 seconds (exponential backoff)
- [x] After 3 failed retries, the system logs the failure and returns an error to the caller
- [x] Non-retryable errors (4xx except 429) are not retried and fail immediately
- [x] Rate limit errors (429) are retried using the same backoff strategy

---

## 3. Scope and Boundaries

### In-Scope
- Jira Cloud API authentication using API token (email + token)
- Reading ticket summary and description fields
- Configurable issue type filtering via environment variable
- Startup credential validation with fail-fast behavior
- Exponential backoff retry for transient failures (3 retries: 1s, 4s, 16s)
- Support for single Jira project (as per V1 product scope)

### Out-of-Scope
- **Write ACs Back to Jira** — Separate roadmap item
- **AI-Powered AC Generation** — Separate roadmap item
- **Automatic Trigger on Ticket Creation** — Separate roadmap item
- **Manual Re-Trigger Capability** — Separate roadmap item
- **Barley API Integration** — Phase 2 roadmap item
- **Slack Integration** — Phase 2/3 roadmap item
- OAuth 2.0 authentication (API token only for V1)
- Reading fields beyond summary and description (labels, components, custom fields)
- Multi-project support
- Jira Server/Data Center (Cloud only)
