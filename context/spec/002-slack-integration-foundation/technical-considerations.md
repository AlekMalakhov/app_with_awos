# Technical Specification: Slack Integration Foundation

- **Functional Specification:** `context/spec/002-slack-integration-foundation/functional-spec.md`
- **Status:** Completed
- **Author(s):** AI-assisted

---

## 1. High-Level Technical Approach

Extend the existing AC generation pipeline with a confidence-based escalation step. The system will:

1. **Enhance `ACGenerator`** to return a numeric confidence score (0.0–1.0) and a list of specific gaps/questions alongside the generated ACs.
2. **Add a `users.lookupByEmail` method** to the existing `SlackClient` to resolve an email address to a Slack user ID.
3. **Create a new `SlackEscalationService`** that composes and sends a Block Kit-formatted DM to the configured stakeholder with ticket context and clarifying questions.
4. **Modify `PollingService._process_ticket()`** to check the confidence score after AC generation. Below threshold: send escalation DM, then write draft ACs with a "clarification requested" note. Above threshold: write ACs directly (existing behavior).
5. **Add an `escalations` database table** to record escalation history for debugging and future Phase 3 integration.

**Systems affected:** `src/ai/`, `src/slack/`, `src/polling/`, `src/database/`.

---

## 2. Proposed Solution & Implementation Plan (The "How")

### 2.1. ACGenerator Changes (`src/ai/generator.py`)

**Tool schema update** — Add two new fields to the existing `AC_TOOL` input schema:

| Field | Type | Description |
|---|---|---|
| `confidence_score` | `number` (0.0–1.0) | AI's confidence in the completeness and accuracy of the generated ACs |
| `confidence_gaps` | `array` of `string` | Specific areas where the AI lacked information (e.g., "unclear user role", "missing error handling behavior"). Empty when confidence is high. |

**New return type** — Replace the current `list[str]` return from `generate()` with a Pydantic model:

| File | Model | Fields |
|---|---|---|
| `src/ai/models.py` (new) | `ACGenerationResult` | `acceptance_criteria: list[str]`, `confidence_score: float`, `confidence_gaps: list[str]`, `sufficient_information: bool` |

**Method change** — `ACGenerator.generate()` signature changes from `-> list[str]` to `-> ACGenerationResult`. The `_parse_response()` method is updated to extract the new fields from the tool_use response.

**Caller updates** — All callers of `generate()` (`PollingService._process_ticket()`, `ACRegenerationService.start_regeneration()`) must be updated to unpack the new return type.

### 2.2. SlackClient Extension (`src/slack/client.py`)

Add new methods to the existing `SlackClient`:

| Method | Signature | Description |
|---|---|---|
| `lookup_user_by_email` | `async def lookup_user_by_email(self, email: str) -> str \| None` | Calls Slack `users.lookupByEmail` API. Returns the Slack user ID or `None` if not found. |
| `send_blocks_message` | `async def send_blocks_message(self, channel: str, blocks: list[dict], text: str) -> bool` | Sends a Block Kit message. `text` serves as fallback for notifications. |

**`lookup_user_by_email` details:**

- **Endpoint:** `GET https://slack.com/api/users.lookupByEmail?email={email}`
- **Auth:** Existing bot token (already configured in `SlackSettings`)
- **Required Slack scopes:** `users:read.email`, `users:read` (in addition to existing scopes)
- **Error handling:** Returns `None` on user-not-found (`user_not_found` error code) or API failure. Logs the error.

**`send_blocks_message` details:**

- **Endpoint:** `POST https://slack.com/api/chat.postMessage` with `blocks` parameter (existing endpoint, new payload shape)

### 2.3. SlackEscalationService (`src/slack/services/escalation_service.py` — new file)

Orchestrates the escalation flow. Constructor accepts `SlackClient` and `SlackSettings` (constructor injection, consistent with existing services).

| Method | Signature | Description |
|---|---|---|
| `escalate` | `async def escalate(self, ticket_key: str, ticket_summary: str, ticket_url: str, confidence_gaps: list[str]) -> EscalationResult` | Full escalation flow: lookup user → compose DM → send |

**`EscalationResult`** (Pydantic model in `src/slack/models.py`):

| Field | Type | Description |
|---|---|---|
| `sent` | `bool` | Whether the DM was successfully sent |
| `slack_user_id` | `str \| None` | Resolved Slack user ID (if found) |
| `error` | `str \| None` | Error description if sending failed |

**Flow inside `escalate()`:**

1. Read `escalation_contact_email` from settings
2. Call `SlackClient.lookup_user_by_email(email)` → `slack_user_id` or `None`
3. If `None`: return `EscalationResult(sent=False, error="User not found")`
4. Open a DM channel with the user via `conversations.open`
5. Compose Block Kit message (see 2.3.1)
6. Call `SlackClient.send_blocks_message(channel, blocks, fallback_text)`
7. Return `EscalationResult(sent=True, slack_user_id=...)`

**2.3.1 Block Kit DM Structure:**

The DM uses Block Kit with the following sections:

- **Header block:** Ticket key + summary (e.g., "PROJ-123: User login flow")
- **Section block:** Link to Jira ticket
- **Divider**
- **Section block:** Introduction text (natural tone, e.g., "Hi! I've generated some draft acceptance criteria for this ticket, but I have a few questions...")
- **Section blocks:** Each gap/question as a separate bullet point
- **Context block:** Footer note (e.g., "These draft ACs have been added to the ticket for reference.")

### 2.4. SlackSettings Extension (`src/slack/config.py`)

Add new fields to the existing `SlackSettings` class:

| Field | Env Variable | Type | Default | Description |
|---|---|---|---|---|
| `escalation_contact_email` | `SLACK_ESCALATION_CONTACT_EMAIL` | `str \| None` | `amalakhov@provectus.com` | Email of the PO/DM to receive escalation DMs |
| `confidence_threshold` | `SLACK_CONFIDENCE_THRESHOLD` | `float` | `0.7` | ACs below this score trigger escalation |

Note: The `SLACK_` prefix is applied automatically by the existing `env_prefix="SLACK_"` in `SlackSettings`.

### 2.5. Database Changes

**New migration file:** `src/database/migrations/004_add_escalations.sql`

**New table: `escalations`**

| Column | Type | Description |
|---|---|---|
| `id` | `TEXT PRIMARY KEY` | UUID |
| `jira_ticket_key` | `TEXT NOT NULL` | Ticket key (e.g., `PROJ-123`) |
| `confidence_score` | `REAL NOT NULL` | AI confidence score at time of escalation |
| `confidence_gaps` | `TEXT NOT NULL` | JSON array of gap strings |
| `slack_user_id` | `TEXT` | Resolved Slack user ID (null if lookup failed) |
| `status` | `TEXT NOT NULL` | `SENT`, `FAILED` |
| `error_message` | `TEXT` | Error details if status is `FAILED` |
| `created_at` | `TEXT NOT NULL` | ISO 8601 timestamp |

**New model:** `EscalationRecord` in `src/database/models.py` — Pydantic model mapping to this table.

**New repository:** `EscalationRepository` in `src/database/repository.py` (or a new file) — follows the same pattern as `ConversationRepository`. Methods: `create()`, `get_by_ticket_key()`.

### 2.6. Pipeline Integration (`src/polling/service.py`)

**Modified flow in `_process_ticket()`** — after AC generation, before Jira write-back:

1. Call `ACGenerator.generate()` → `ACGenerationResult`
2. Check `confidence_score` against `SlackSettings.confidence_threshold`
3. **If score >= threshold:** Write ACs to Jira (existing behavior, no changes)
4. **If score < threshold:**
   - Call `SlackEscalationService.escalate(ticket_key, summary, ticket_url, confidence_gaps)`
   - Record escalation in `escalations` table via `EscalationRepository.create()`
   - **If escalation sent:** Write draft ACs to Jira with prepended note: *"Note: Clarification has been requested from the Product Owner. Please review the following draft acceptance criteria."*
   - **If escalation failed:** Write draft ACs to Jira with prepended warning: *"Note: The system attempted to contact the Product Owner for clarification on the items below, but the message could not be delivered. Please review these ACs manually."*

### 2.7. Startup & Wiring (`src/main.py`)

In the `lifespan()` function:

- `SlackSettings` is already instantiated. The new fields (`escalation_contact_email`, `confidence_threshold`) are loaded automatically.
- Instantiate `SlackEscalationService(slack_client, slack_settings)`.
- Pass `SlackEscalationService` to `PollingService` constructor.
- Instantiate `EscalationRepository` and pass to `PollingService` or `SlackEscalationService`.

---

## 3. Impact and Risk Analysis

### System Dependencies

| Dependency | Impact |
|---|---|
| Slack API | New `users.lookupByEmail` and `conversations.open` calls. Requires additional OAuth scopes (`users:read.email`, `users:read`). |
| Anthropic Claude API | Modified tool schema — confidence score adds minimal token overhead to each generation call. |
| SQLite | New `escalations` table. Migration runs automatically on startup. |

### Potential Risks & Mitigations

| Risk | Mitigation |
|---|---|
| **Confidence score reliability** — the AI may not produce consistent or well-calibrated scores | Use prompt engineering to anchor the scale (e.g., "0.9+ = all requirements clear, 0.5 = major gaps"). Tune the default threshold (0.7) based on observed behavior. The threshold is configurable via env var. |
| **Slack user not found by email** — the configured email may not match any Slack user (different domain, guest account, etc.) | Graceful fallback: write draft ACs with warning note. Error logged and recorded in `escalations` table. |
| **Slack bot token missing required scopes** — `users:read.email` may not be granted | Document required scopes. Log a clear error on startup if user lookup fails due to missing scopes. |
| **Breaking change to `generate()` return type** — all callers must be updated | The change is fully internal. Update `PollingService` and `ACRegenerationService` in the same PR. |
| **Escalation spam** — if many tickets fall below the threshold, the PO gets flooded with DMs | Acceptable for V1 (single project). Monitor in Phase 3 and consider batching/digest if needed. |

---

## 4. Testing Strategy

### Unit Tests

| Component | Test Focus |
|---|---|
| `ACGenerator.generate()` (updated) | Mock Anthropic SDK. Verify the new `confidence_score` and `confidence_gaps` fields are parsed correctly from tool_use response. Test edge cases: missing fields, out-of-range scores. |
| `SlackClient.lookup_user_by_email()` | Mock `httpx` responses. Test: user found, user not found (`user_not_found` error), API error, invalid email. |
| `SlackClient.send_blocks_message()` | Mock `httpx`. Verify Block Kit payload structure. |
| `SlackEscalationService.escalate()` | Mock `SlackClient`. Test: full success path, user-not-found path, DM send failure path. Verify `EscalationResult` values for each case. |
| `EscalationRepository` | Ephemeral SQLite (temp directory). Test `create()` and `get_by_ticket_key()`. |
| `PollingService._process_ticket()` (updated) | Mock `ACGenerator`, `SlackEscalationService`, `EscalationRepository`. Test: high-confidence path (no escalation), low-confidence + successful DM, low-confidence + failed DM. Verify correct note/warning text appended to ACs. |

### Integration Tests

- End-to-end test with real Slack API (guarded by `requires_slack_credentials` fixture). Test `lookup_user_by_email` and `send_blocks_message` against a test workspace.
