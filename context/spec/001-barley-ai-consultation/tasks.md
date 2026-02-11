# Task List: Barley AI Consultation

- **Specification:** `context/spec/001-barley-ai-consultation/`
- **Status:** Pending

---

- [x] **Slice 1: Barley client module with API connectivity**
  _Smallest testable piece: the system can connect to Barley's API and handle failures. App remains runnable — module is loaded but not yet wired into the AC pipeline._
  - [x] Create `src/barley/__init__.py`, `config.py` (`BarleySettings`), `exceptions.py` (`BarleyError`, `BarleyConnectionError`, `BarleyAuthenticationError`). **[Agent: python-expert]**
  - [x] Create `src/barley/client.py` with `BarleyClient` — async `httpx.AsyncClient` wrapping `POST /v1/chat/completions`, Bearer auth, configurable timeout, no retries. `query(prompt) -> str | None` returns response content or `None` on any failure. **[Agent: barley-api-integrator]**
  - [x] Write unit tests for `BarleyClient`: successful query, empty response, timeout, 401, 5xx, network error. Use `pytest-httpx` mocking. **[Agent: python-expert]**
  - [x] Verify: run `pytest tests/unit/test_barley_client.py` — all tests pass. Start app with `BARLEY_ENABLED=true` — no startup errors. **[Agent: qa-expert]**

- [x] **Slice 2: Topic extraction via Claude**
  _The system can extract key topics from a Jira ticket description using Claude. Testable independently._
  - [x] Add `extract_topics(summary, description) -> str` method to `ACGenerator` in `src/ai/generator.py`. Uses Claude tool_use pattern (consistent with existing `generate()`). Returns consolidated topics string. Falls back to raw description on failure. **[Agent: python-expert]**
  - [x] Write unit tests for `extract_topics()`: successful extraction, Anthropic API failure (falls back to description), empty description. Mock Anthropic SDK. **[Agent: python-expert]**
  - [x] Verify: run `pytest tests/unit/test_ac_generator.py` — all tests pass (new + existing). **[Agent: qa-expert]**

- [x] **Slice 3: Enrichment service wired into automatic polling flow**
  _First end-to-end value: tickets entering the polling pipeline get Barley-enriched ACs and a Jira comment with the context. The full automatic flow works._
  - [x] Create `src/barley/models.py` with `EnrichmentResult` Pydantic model (`barley_context: str | None`, `topics_extracted: str`). **[Agent: python-expert]**
  - [x] Create `src/barley/service.py` with `BarleyEnrichmentService.enrich(summary, description) -> EnrichmentResult`. Orchestrates: extract_topics → query Barley → return result. Short-circuits when `BARLEY_ENABLED=false`. **[Agent: python-expert]**
  - [x] Add `add_comment(issue_key, body) -> bool` method to `JiraClient` in `src/jira/client.py`. Posts ADF comment to `POST /rest/api/3/issue/{key}/comment` with "Barley AI Context" prefix. **[Agent: python-expert]**
  - [x] Integrate into `PollingService._process_ticket()`: call `BarleyEnrichmentService.enrich()` before `ACGenerator.generate()`, append Barley context to description, post Jira comment. **[Agent: python-expert]**
  - [x] Update `src/main.py` lifespan: instantiate `BarleySettings`, `BarleyClient`, `BarleyEnrichmentService`. Pass to `PollingService`. Call `BarleyClient.close()` on shutdown. **[Agent: python-expert]**
  - [x] Write unit tests: `BarleyEnrichmentService` (success, Barley failure, disabled), `JiraClient.add_comment()` (success, failure), updated `PollingService` (enrichment called, context passed to generate, comment posted). **[Agent: python-expert]**
  - [x] Verify: run full test suite `pytest` — all tests pass (new + existing). Start app, confirm no startup errors. **[Agent: qa-expert]**

- [x] **Slice 4: Barley enrichment in Slack-triggered regeneration**
  _The manual re-trigger via Slack DM also benefits from Barley enrichment. Both flows are now enriched._
  - [x] Integrate `BarleyEnrichmentService` into `ACRegenerationService.start_regeneration()` in `src/slack/services/regeneration_service.py`. Same pattern: enrich before generate, append context, post Jira comment. **[Agent: python-expert]**
  - [x] Write unit tests for updated `ACRegenerationService`: enrichment called, context appended, Jira comment posted, Barley failure handled gracefully. **[Agent: python-expert]**
  - [x] Verify: run full test suite `pytest` — all tests pass. **[Agent: qa-expert]**

- [x] **Slice 5: Verify graceful degradation**
  _Validates that the entire system works correctly when Barley is disabled or unavailable — no regressions to existing behavior._
  - [x] Write integration test: with `BARLEY_ENABLED=false`, run the polling pipeline against a real Jira ticket — ACs are generated normally, no Barley calls made, no Jira comment posted. **[Agent: python-expert]**
  - [x] Write integration test: with Barley API pointed to an invalid URL, run the polling pipeline — ACs are generated from description alone, pipeline is not blocked or delayed. **[Agent: python-expert]**
  - [x] Verify: run `pytest tests/integration/` with appropriate credentials — all integration tests pass. **[Agent: qa-expert]**
