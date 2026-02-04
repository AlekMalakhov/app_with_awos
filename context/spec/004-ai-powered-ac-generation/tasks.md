# Task List: AI-Powered AC Generation (004)

## Vertical Slices

- [x] **Slice 1: Create AI module foundation with settings and disabled-mode handling**
  - [x] Sub-task: Add `anthropic` package to `pyproject.toml` dependencies. **[Agent: python-expert]**
  - [x] Sub-task: Create `src/ai/__init__.py`, `src/ai/config.py`, and `src/ai/exceptions.py` with `AISettings` class and exception hierarchy. **[Agent: python-expert]**
  - [x] Sub-task: Write unit tests for `AISettings` (test `is_enabled` property with/without API key). **[Agent: python-expert]**
  - [x] Sub-task: Run `uv run pytest tests/unit/test_ai_config.py -v` to verify tests pass. **[Agent: python-expert]**

- [x] **Slice 2: Implement ACGenerator with Claude API integration**
  - [x] Sub-task: Create `src/ai/generator.py` with `ACGenerator` class that calls Anthropic API using tool_use for structured output. **[Agent: python-expert]**
  - [x] Sub-task: Implement the prompt template and tool schema for generating 3-7 ACs. **[Agent: python-expert]**
  - [x] Sub-task: Handle `sufficient_information=false` response by returning empty list. **[Agent: python-expert]**
  - [x] Sub-task: Write unit tests with mocked Anthropic responses for success, insufficient info, and malformed response cases. **[Agent: python-expert]**
  - [x] Sub-task: Run `uv run pytest tests/unit/test_ai_generator.py -v` to verify tests pass. **[Agent: python-expert]**

- [x] **Slice 3: Integrate ACGenerator into PollingService**
  - [x] Sub-task: Update `PollingService.__init__()` to accept optional `ACGenerator` parameter. **[Agent: python-expert]**
  - [x] Sub-task: Replace hardcoded ACs in `_process_ticket()` with `ACGenerator.generate()` call. **[Agent: python-expert]**
  - [x] Sub-task: Handle case when AI returns empty list (insufficient info) - skip without adding label, log warning. **[Agent: python-expert]**
  - [x] Sub-task: Handle case when `ACGenerator` is None or disabled - log warning, return False. **[Agent: python-expert]**
  - [x] Sub-task: Update `src/main.py` to create `AISettings` and `ACGenerator`, pass to `PollingService`. **[Agent: python-expert]**
  - [x] Sub-task: Write/update unit tests for PollingService with mocked ACGenerator. **[Agent: python-expert]**
  - [x] Sub-task: Run all unit tests `uv run pytest tests/unit/ -v` to verify no regressions. **[Agent: python-expert]**

- [x] **Slice 4: Manual integration test with real Jira ticket**
  - [x] Sub-task: Ensure `ANTHROPIC_API_KEY` is set in `.env` file. **[Agent: qa-expert]**
  - [x] Sub-task: Verify test ticket IGAL-1926 exists and has a meaningful description. **[Agent: qa-expert]**
  - [x] Sub-task: Remove `ac-generated` label from IGAL-1926 if present. **[Agent: qa-expert]**
  - [x] Sub-task: Run the application and trigger processing of IGAL-1926. **[Agent: qa-expert]**
  - [x] Sub-task: Verify AI-generated ACs appear in IGAL-1926 description (not hardcoded test ACs). **[Agent: qa-expert]**
  - [x] Sub-task: Verify the ACs are specific to the ticket content. **[Agent: qa-expert]**

- [x] **Slice 5: Test insufficient description handling**
  - [x] Sub-task: Create or find a Jira ticket with minimal/vague description (e.g., just "Fix bug"). **[Agent: qa-expert]**
  - [x] Sub-task: Remove `ac-generated` label from the test ticket. **[Agent: qa-expert]**
  - [x] Sub-task: Run the application and observe logs. **[Agent: qa-expert]**
  - [x] Sub-task: Verify the system skips AC generation and logs "insufficient information". **[Agent: qa-expert]**
  - [x] Sub-task: Verify the `ac-generated` label is NOT added to the ticket. **[Agent: qa-expert]**

- [x] **Slice 6: Create automated integration tests**
  - [x] Sub-task: Create `tests/integration/test_ai_generation.py` with `@pytest.mark.integration`. **[Agent: python-expert]**
  - [x] Sub-task: Add test `test_generate_acs_real_api` - calls Claude API with sample ticket data, verifies ACs returned. **[Agent: python-expert]**
  - [x] Sub-task: Run integration tests: `uv run pytest tests/integration/test_ai_generation.py -v`. **[Agent: qa-expert]**

---

## Prerequisites

| Requirement | Status |
|-------------|--------|
| `ANTHROPIC_API_KEY` | Configured |
| Test ticket IGAL-1926 | Available |
