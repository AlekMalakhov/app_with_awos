# Technical Specification: Barley AI Consultation

- **Functional Specification:** `context/spec/001-barley-ai-consultation/functional-spec.md`
- **Status:** Completed
- **Author(s):** AI-assisted

---

## 1. High-Level Technical Approach

Integrate Barley's domain-knowledge API into the existing AC generation pipeline as an enrichment step. The system will:

1. Use **Claude** (existing Anthropic API) to extract key topics from the Jira ticket description.
2. Send those topics to **Barley's OpenAI-compatible chat completions endpoint** to retrieve project context and domain knowledge.
3. Pass the Barley context alongside the ticket description into the existing **ACGenerator** for richer AC generation.
4. Post the Barley context as a **Jira comment** for transparency.

A new `BarleyEnrichmentService` orchestrates steps 1-2 and is called by both `PollingService` (automatic flow) and `ACRegenerationService` (manual Slack flow). On any Barley failure, enrichment is skipped and the pipeline proceeds with the ticket description alone.

**Systems affected:** `src/ai/`, `src/jira/`, `src/polling/`, `src/slack/`, new `src/barley/` module.

---

## 2. Proposed Solution & Implementation Plan (The "How")

### 2.1. New Module: `src/barley/`

Following the established pattern of `src/jira/` and `src/slack/`:

| File | Responsibility |
|---|---|
| `src/barley/__init__.py` | Package init |
| `src/barley/config.py` | `BarleySettings(BaseSettings)` — loads `BARLEY_*` env vars |
| `src/barley/client.py` | `BarleyClient` — async HTTP client for Barley chat completions |
| `src/barley/exceptions.py` | `BarleyError`, `BarleyConnectionError`, `BarleyAuthenticationError` |

**`BarleySettings` env vars** (already present in `.env`):

| Variable | Purpose |
|---|---|
| `BARLEY_ENABLED` | Feature toggle (boolean) |
| `BARLEY_API_URL` | Base URL (`https://fastapi.barley.provectus.pro`) |
| `BARLEY_API_TOKEN` | Bearer token for authentication |
| `BARLEY_TIMEOUT` | Request timeout in seconds |

**`BarleyClient` API contract:**

- **Endpoint:** `POST {BARLEY_API_URL}/v1/chat/completions`
- **Auth:** `Authorization: Bearer {BARLEY_API_TOKEN}`
- **Request body:**
  ```json
  {
    "model": "anth",
    "messages": [{"role": "user", "content": "<prompt with extracted topics>"}],
    "temperature": 0.7,
    "max_tokens": 3000
  }
  ```
- **Response:** OpenAI chat completions format — context extracted from `choices[0].message.content`
- **Error handling:** No retries. On any failure (timeout, 4xx, 5xx, network error), raise `BarleyError`. The caller catches and skips enrichment.
- **Method:** `async def query(self, prompt: str) -> str | None` — returns context string or `None` on failure.

### 2.2. Topic Extraction: New Method on `ACGenerator`

Add a new method to `src/ai/generator.py`:

- **Method:** `async def extract_topics(self, summary: str, description: str) -> str`
- **Purpose:** Uses Claude (tool_use pattern, consistent with existing `generate()`) to extract key topics, entities, and domain concepts from the ticket.
- **Returns:** A consolidated string of extracted topics suitable for sending to Barley.
- **On failure:** Returns the raw description as fallback (so Barley still gets something useful).

### 2.3. Enrichment Orchestration: `BarleyEnrichmentService`

New file: `src/barley/service.py`

| Method | Signature | Description |
|---|---|---|
| `enrich` | `async def enrich(self, summary: str, description: str) -> EnrichmentResult` | Full enrichment flow: extract topics → query Barley → return result |

**`EnrichmentResult`** (Pydantic model in `src/barley/models.py`):

| Field | Type | Description |
|---|---|---|
| `barley_context` | `str \| None` | Context returned by Barley, or `None` if unavailable |
| `topics_extracted` | `str` | The extracted topics string sent to Barley |

**Flow inside `enrich()`:**
1. Call `ACGenerator.extract_topics(summary, description)` → topics string
2. Build prompt with topics and send to `BarleyClient.query(prompt)` → context or `None`
3. Return `EnrichmentResult`

If `BARLEY_ENABLED` is `false`, `enrich()` returns `EnrichmentResult(barley_context=None, topics_extracted="")` immediately.

### 2.4. Pipeline Integration

**`PollingService._process_ticket()`** (`src/polling/service.py`):
- After fetching ticket, before calling `ACGenerator.generate()`:
  1. Call `BarleyEnrichmentService.enrich(summary, description)`
  2. If `barley_context` is not `None`, append it to the description passed to `ACGenerator.generate()`
  3. If `barley_context` is not `None`, call `JiraClient.add_comment()` to post context to the ticket

**`ACRegenerationService.start_regeneration()`** (`src/slack/services/regeneration_service.py`):
- Same pattern: call `BarleyEnrichmentService.enrich()` before AC generation, append context, post Jira comment.

### 2.5. New JiraClient Method

Add to `src/jira/client.py`:

- **Method:** `async def add_comment(self, issue_key: str, body: str) -> bool`
- **Endpoint:** `POST /rest/api/3/issue/{issue_key}/comment`
- **Payload:** Jira ADF comment body with the Barley context, prefixed with "Barley AI Context" label
- **Returns:** `bool` (success/failure, consistent with `update_description` and `add_label` patterns)
- **No retry** — follows the skip-and-proceed philosophy for non-critical operations.

### 2.6. Configuration & Startup

In `src/main.py` lifespan:
- Instantiate `BarleySettings`, `BarleyClient`, and `BarleyEnrichmentService`
- Pass `BarleyEnrichmentService` to `PollingService` and make it available to `ACRegenerationService`
- Call `BarleyClient.close()` on shutdown

---

## 3. Impact and Risk Analysis

### System Dependencies

| Dependency | Impact |
|---|---|
| Anthropic Claude API | New `extract_topics()` call adds one extra LLM round-trip per ticket |
| Barley API | New external dependency; failures must not block pipeline |
| Jira API | New `add_comment` call per ticket (when Barley returns context) |

### Potential Risks & Mitigations

| Risk | Mitigation |
|---|---|
| **Added latency** — two extra API calls (topic extraction + Barley) per ticket | Both are fire-and-enrich; pipeline proceeds regardless. Barley timeout is configurable via `BARLEY_TIMEOUT`. |
| **Barley API unavailability** | Skip and proceed — no retries, no blocking. AC generation works without Barley (existing behavior). |
| **Context too long** — Barley may return verbose context that inflates the ACGenerator prompt beyond token limits | Truncate Barley context to a configurable max length before passing to ACGenerator. |
| **Feature toggle** — need to disable Barley without redeploying | `BARLEY_ENABLED` env var acts as a kill switch. |
| **Jira comment spam** — a comment is posted for every ticket with Barley context | Acceptable per functional spec. Can be toggled off if needed. |

---

## 4. Testing Strategy

### Unit Tests

| Component | Test Focus |
|---|---|
| `BarleyClient` | Mock `httpx` responses (success, empty context, timeout, 4xx, 5xx). Verify `query()` returns context or `None`. |
| `BarleyEnrichmentService` | Mock `ACGenerator.extract_topics()` and `BarleyClient.query()`. Verify orchestration logic, fallback on failure, and `BARLEY_ENABLED=false` short-circuit. |
| `ACGenerator.extract_topics()` | Mock Anthropic SDK. Verify topic extraction prompt and response parsing. |
| `JiraClient.add_comment()` | Mock `httpx`. Verify request format (ADF body, correct endpoint). |
| `PollingService` (updated) | Mock `BarleyEnrichmentService`. Verify enrichment is called and context is passed to `generate()`. |
| `ACRegenerationService` (updated) | Same as above for the manual flow. |

### Integration Tests

- End-to-end test with real Barley API (guarded by `requires_barley_credentials` fixture, similar to existing `requires_jira_credentials` pattern).
