# Functional Specification: Automatic Trigger on Ticket Creation

- **Roadmap Item:** Automatically invoke AC generation when a new Story/Task is created
- **Status:** Completed
- **Author:** Poe (Product Analyst)

---

## 1. Overview and Rationale (The "Why")

### Purpose
This specification defines the automatic triggering mechanism that invokes AC generation for new Stories and Tasks in Jira. Using a polling approach, the system periodically checks for unprocessed tickets and generates acceptance criteria without manual intervention.

### Problem Being Solved
Product Owners currently have to remember to trigger AC generation for each new ticket. This creates friction, leads to inconsistent coverage, and tickets may sit without ACs until someone notices. Automatic triggering ensures AC generation happens consistently for every eligible ticket.

### Desired Outcome
A background process that:
- Polls Jira every 5 minutes for new, unprocessed tickets
- Checks prerequisites (has description, no existing ACs)
- Invokes AC generation for eligible tickets
- Marks processed tickets with a label to avoid duplicate processing

### Success Criteria
- All new Stories/Tasks with descriptions get ACs generated within 5 minutes of creation
- No duplicate generation (label prevents reprocessing)
- System recovers gracefully from downtime (7-day lookback window)
- All events are logged for debugging and monitoring

---

## 2. Functional Requirements (The "What")

### FR-1: Background Polling Service
The system must run a background task that periodically polls Jira for unprocessed tickets.

**Acceptance Criteria:**
- [x] The system runs a background task that executes every 5 minutes
- [x] The polling interval is configurable via environment variable `JIRA_POLLING_INTERVAL_SECONDS` (default: 300)
- [x] The task runs independently of HTTP request handling
- [x] If a poll cycle is still running when the next is scheduled, the new cycle is skipped (no overlap)

### FR-2: Ticket Discovery via JQL
The system must query Jira for tickets that need AC generation.

**Acceptance Criteria:**
- [x] The system queries Jira using JQL: `project = {PROJECT} AND issuetype in ({ISSUE_TYPES}) AND labels not in ("ac-generated", "ac-generation-failed") AND created >= -7d`
- [x] The project key is read from environment variable `JIRA_PROJECT_KEY`
- [x] Issue types are read from existing `JIRA_ISSUE_TYPES` configuration
- [x] The lookback window (7 days) catches tickets missed during downtime
- [x] Results are ordered by created date ascending (oldest first)

### FR-3: Prerequisite Validation
The system must validate that each discovered ticket meets prerequisites before processing.

**Acceptance Criteria:**
- [x] For each ticket found, the system fetches full ticket details
- [x] If the ticket's description field is empty or null, the ticket is skipped and logged
- [x] If the ticket's AC field already contains content, the ticket is skipped and logged
- [x] Only tickets passing all checks proceed to AC generation

### FR-4: AC Generation Invocation
The system must invoke the AC generation process for eligible tickets.

**Acceptance Criteria:**
- [x] When all prerequisites pass, the system invokes the AC generation service with the ticket key
- [x] Tickets are processed sequentially to avoid overwhelming external APIs
- [x] Successful generation completion is logged with ticket key and timestamp
- [x] [PLACEHOLDER: AC generation service integration - depends on "AI-Powered AC Generation" spec]

### FR-5: Processed Ticket Marking
The system must mark successfully processed tickets to prevent duplicate processing.

**Acceptance Criteria:**
- [x] After successful AC generation, the system adds the label `ac-generated` to the ticket
- [x] The label is added via Jira API (PUT /rest/api/3/issue/{key})
- [x] If label addition fails, the failure is logged but does not block subsequent tickets
- [x] Tickets with the `ac-generated` label are excluded from future discovery queries

### FR-6: Failure Handling and Retry
The system must handle failures gracefully with automatic retry.

**Acceptance Criteria:**
- [x] If AC generation fails for a ticket, the ticket is NOT marked with `ac-generated` (will be retried next poll)
- [x] Transient errors (5xx, timeout) result in the ticket being retried in the next poll cycle
- [x] After 3 consecutive failures for the same ticket, a label `ac-generation-failed` is added
- [x] Tickets with `ac-generation-failed` are excluded from automatic retries (requires manual intervention)
- [x] All failures are logged with full error details

### FR-7: Event Logging
The system must log all polling and processing events.

**Acceptance Criteria:**
- [x] Each poll cycle is logged: start time, tickets found, tickets processed, tickets skipped
- [x] Each ticket processing is logged: ticket key, validation result, generation result
- [x] Logs include structured data for easy parsing (Python logging format, JSON configurable)
- [x] Log level is configurable via `LOG_LEVEL` environment variable

---

## 3. Scope and Boundaries

### In-Scope
- Background polling service running every 5 minutes
- JQL-based ticket discovery with 7-day lookback
- Prerequisite checks: description presence, AC field empty
- Adding `ac-generated` label to mark processed tickets
- Adding `ac-generation-failed` label after repeated failures
- Invoking AC generation service (placeholder until that spec is complete)
- Comprehensive event logging

### Out-of-Scope
- **Write ACs Back to Jira** — Separate roadmap item
- **AI-Powered AC Generation** — Separate roadmap item (this spec only invokes it)
- **Manual Re-Trigger Capability** — Separate roadmap item
- **Barley API Integration** — Phase 2 roadmap item
- **Slack Integration** — Phase 2/3 roadmap item
- **AC Approval Workflow** — Phase 3 roadmap item
- Webhook-based triggering (using polling instead)
- Real-time processing (5-minute polling latency is acceptable)
- Multi-project support (V1 targets single project via `JIRA_PROJECT_KEY`)
