# Technical Specification: Manual Re-Trigger Capability

- **Functional Specification:** `context/spec/005-manual-re-trigger-capability/functional-spec.md`
- **Status:** Completed
- **Author(s):** AI Assistant

---

## 1. High-Level Technical Approach

This feature enables users to manually request AC regeneration via Slack DM. The implementation requires:

1. **New Slack Module (`src/slack/`)** — Slack Events API integration to receive and process DM messages from users requesting AC regeneration.

2. **New Database Module (`src/database/`)** — SQLite persistence for conversation state, enabling multi-turn approval workflows.

3. **AC Regeneration Service** — Orchestrates the flow: fetching the ticket from Jira, generating new ACs using the existing `ACGenerator`, presenting comparisons via Slack DM, and writing approved ACs back to Jira.

4. **Extended Jira Utilities** — New utilities to extract existing ACs from descriptions and replace (not append) the AC section when writing back.

The Slack bot will use Claude API for natural language understanding to interpret user intent (approve/reject/modify) from conversational responses.

---

## 2. Proposed Solution & Implementation Plan (The "How")

### Architecture Changes

**New Modules:**
- `src/slack/` — Slack bot integration (Events API webhook handlers, DM message processing, Slack client)
- `src/database/` — SQLite persistence for conversation state

**New FastAPI Route:**
- `POST /slack/events` — Slack Events API webhook endpoint

### Data Model / Database Changes

**New SQLite Database:**

A new `conversations` table to track Slack DM conversation state:

| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT (PK) | UUID identifier |
| `slack_user_id` | TEXT | Slack user who initiated |
| `slack_channel_id` | TEXT | DM channel ID |
| `jira_ticket_key` | TEXT (nullable) | Ticket being processed |
| `status` | TEXT | Conversation state (enum) |
| `existing_acs` | TEXT (nullable) | JSON array of existing AC strings |
| `proposed_acs` | TEXT (nullable) | JSON array of newly generated AC strings |
| `message_history` | TEXT | JSON array of message records for context |
| `created_at` | TIMESTAMP | Creation timestamp |
| `updated_at` | TIMESTAMP | Last update timestamp |

**Configuration:**
- `DATABASE_PATH` environment variable for SQLite file location

**Conversation Status Enum:**
- `AWAITING_TICKET` — Initial state, waiting for ticket key
- `FETCHING_TICKET` — Fetching ticket from Jira
- `GENERATING_ACS` — AI is generating new ACs
- `COMPARING` — Showing comparison to user
- `AWAITING_APPROVAL` — Waiting for approve/reject/modify
- `PROCESSING_MODIFICATION` — Processing user's modification request
- `WRITING_TO_JIRA` — Writing approved ACs to Jira
- `COMPLETED` — Successfully written
- `CANCELLED` — User cancelled
- `ERROR` — Error state

### API Contracts

**Slack Events API Webhook:**

`POST /slack/events`
- Handles Slack URL verification challenge
- Receives `message` events for DM channels
- Returns 200 OK immediately; processes asynchronously

No additional REST API endpoints — regeneration is triggered exclusively via Slack DM.

### Component Breakdown

**New Slack Module (`src/slack/`):**

| File | Purpose |
|------|---------|
| `config.py` | `SlackSettings` — `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET` |
| `client.py` | `SlackClient` — `send_message()`, HTTP calls to Slack API |
| `events.py` | FastAPI router for `/slack/events` |
| `handlers/dm_handler.py` | DM message processing, state machine routing |
| `handlers/intent_classifier.py` | Claude-based intent classification (approve/reject/modify) |
| `services/regeneration_service.py` | Orchestration service for full workflow |
| `models.py` | Slack-specific Pydantic models |

**New Database Module (`src/database/`):**

| File | Purpose |
|------|---------|
| `config.py` | `DatabaseSettings` — `DATABASE_PATH` |
| `connection.py` | SQLite connection management |
| `models.py` | `ConversationState`, `ConversationStatus` Pydantic models |
| `repository.py` | `ConversationRepository` — CRUD operations |
| `migrations/001_initial.sql` | Initial schema creation |

**Extended Jira Module (`src/jira/`):**

| File | Purpose |
|------|---------|
| `ac_extractor.py` (new) | `extract_acs_from_description()`, `replace_acs_in_adf()` |

### Logic / Algorithm

**Conversation State Machine:**

```
AWAITING_TICKET → (user provides ticket key) → FETCHING_TICKET
FETCHING_TICKET → (Jira fetched) → GENERATING_ACS
GENERATING_ACS → (ACs generated) → COMPARING
COMPARING → (user approves) → WRITING_TO_JIRA → COMPLETED
COMPARING → (user rejects) → CANCELLED
COMPARING → (user modifies) → PROCESSING_MODIFICATION → AWAITING_APPROVAL
AWAITING_APPROVAL → (user approves) → WRITING_TO_JIRA → COMPLETED
```

**Intent Classification (via Claude API):**

User responses are classified using Claude with a prompt like:
```
Classify the user's response to an AC approval request.
Categories: APPROVE, REJECT, MODIFY

User message: "{message}"

If APPROVE: User accepts the proposed ACs.
If REJECT: User wants to cancel/keep original.
If MODIFY: User wants changes. Extract what they want changed.
```

This enables natural language responses like "looks good", "nope", "can you add error handling" to be correctly interpreted.

**Ticket Key Extraction:**

Use regex pattern `([A-Z]+-\d+)` to extract Jira ticket keys from user messages.

---

## 3. Impact and Risk Analysis

### System Dependencies

- **Jira Integration** — Reuses existing `JiraClient` for ticket fetching and AC writing
- **AC Generation** — Reuses existing `ACGenerator` for producing new ACs
- **Polling Service** — Must coordinate to avoid race conditions

### Potential Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Race condition with automatic trigger | Conflicting writes to same ticket | Check for `ac-generated` label before processing; add `regenerating` label during manual regeneration |
| Stale conversation state | SQLite accumulates abandoned conversations | Background cleanup task for conversations older than 7 days |
| Slack API rate limits | Requests rejected under high load | Apply tenacity retry pattern with exponential backoff |
| Large AC diffs exceed message limit | Truncated or failed Slack messages | Truncate comparison if ACs exceed 3000 chars; split into multiple messages if needed |

---

## 4. Testing Strategy

**Unit Tests:**
- `test_dm_handler.py` — State machine transitions, ticket key extraction
- `test_intent_classifier.py` — Intent classification with mocked Claude responses
- `test_regeneration_service.py` — Orchestration logic with mocked Jira/AI clients
- `test_ac_extractor.py` — AC extraction and replacement utilities
- `test_conversation_repository.py` — SQLite CRUD operations

**Integration Tests:**
- Test Slack Events API endpoint with simulated payloads
- Test full regeneration flow with mocked external APIs
- Test conversation state persistence across multiple messages

**Bot Testing with Slack MCP:**
- Use the Slack MCP server to test bot interactions in a real Slack workspace
- Verify DM conversation flow end-to-end
- Test natural language intent detection with varied user responses
- Validate error message formatting and Jira link generation
