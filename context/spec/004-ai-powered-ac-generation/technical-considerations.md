# Technical Specification: AI-Powered AC Generation

- **Functional Specification:** `context/spec/004-ai-powered-ac-generation/functional-spec.md`
- **Status:** Completed
- **Author(s):** Technical Architect

---

## 1. High-Level Technical Approach

This feature replaces the hardcoded test ACs in `PollingService._process_ticket()` with real AI-generated acceptance criteria using Anthropic's Claude API.

The implementation will:

1. **Create a new `src/ai/` module** following the existing `src/jira/` pattern
2. **Use the official Anthropic Python SDK** for Claude API communication
3. **Use structured output (tool_use)** to ensure reliable JSON parsing of generated ACs
4. **Integrate into `PollingService`** at the existing placeholder location
5. **Gracefully degrade** when `ANTHROPIC_API_KEY` is not configured

---

## 2. Proposed Solution & Implementation Plan (The "How")

### 2.1 New Module: AI Generator

**Directory:** `src/ai/`

**Files:**

| File | Purpose |
|------|---------|
| `__init__.py` | Module exports (`AISettings`, `ACGenerator`) |
| `config.py` | Pydantic Settings for AI configuration |
| `generator.py` | `ACGenerator` class - orchestrates prompt, API call, and parsing |
| `exceptions.py` | AI-specific exceptions |

### 2.2 AI Configuration (Settings)

**File:** `src/ai/config.py`

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class AISettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="")

    anthropic_api_key: str = ""  # Empty string = AI disabled
    ai_model: str = "claude-sonnet-4-20250514"
    ai_max_tokens: int = 1024
    ai_temperature: float = 0.3  # Lower = more deterministic

    @property
    def is_enabled(self) -> bool:
        return bool(self.anthropic_api_key)
```

**Environment Variables:**
- `ANTHROPIC_API_KEY` (required for AI) - Anthropic API key
- `AI_MODEL` (optional, default: `claude-sonnet-4-20250514`) - Claude model to use

### 2.3 AC Generator

**File:** `src/ai/generator.py`

**Class:** `ACGenerator`

```python
class ACGenerator:
    def __init__(self, settings: AISettings) -> None:
        self._settings = settings
        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    async def generate(
        self,
        summary: str,
        description: str
    ) -> list[str]:
        """
        Generate acceptance criteria for a Jira ticket.

        Args:
            summary: Ticket summary/title
            description: Ticket description text

        Returns:
            List of AC strings, or empty list if description insufficient
        """
```

**Structured Output Schema (Tool Use):**

```python
AC_TOOL = {
    "name": "submit_acceptance_criteria",
    "description": "Submit the generated acceptance criteria",
    "input_schema": {
        "type": "object",
        "properties": {
            "sufficient_information": {
                "type": "boolean",
                "description": "True if the ticket has enough information to generate meaningful ACs"
            },
            "acceptance_criteria": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of 3-7 acceptance criteria"
            },
            "skip_reason": {
                "type": "string",
                "description": "Reason for skipping if insufficient information"
            }
        },
        "required": ["sufficient_information", "acceptance_criteria"]
    }
}
```

**Prompt Design:**

```
You are an expert Product Owner writing acceptance criteria for software development tickets.

Analyze the following Jira ticket and generate 3-7 clear, testable acceptance criteria.

TICKET SUMMARY: {summary}

TICKET DESCRIPTION:
{description}

GUIDELINES:
- Use the format that best fits each criterion (Given-When-Then for behavior, checkbox for state)
- Be specific to THIS ticket - avoid generic criteria like "Code is tested"
- Each criterion should be independently verifiable
- If the description lacks sufficient detail to write meaningful ACs, set sufficient_information to false

Use the submit_acceptance_criteria tool to provide your response.
```

### 2.4 Exception Hierarchy

**File:** `src/ai/exceptions.py`

```python
class AIError(Exception):
    """Base exception for AI operations."""

class AIConfigurationError(AIError):
    """Raised when AI is not properly configured."""

class AIRateLimitError(AIError):
    """Raised when API rate limit is exceeded."""

class AIInvalidResponseError(AIError):
    """Raised when AI response cannot be parsed."""
```

### 2.5 Integration Point

**File:** `src/polling/service.py`

**Current code (lines 186-191):**
```python
# 1. Generate ACs (hardcoded for now - will be replaced by AI generation later)
generated_acs = [
    "User can perform the described action",
    "System responds within acceptable time limits",
    "Error states are handled gracefully",
]
```

**New code:**
```python
# 1. Generate ACs using AI
if self._ac_generator and self._ac_generator.is_enabled:
    generated_acs = await self._ac_generator.generate(
        summary=ticket.summary,
        description=ticket.description,
    )
    if not generated_acs:
        logger.warning(
            "AI determined insufficient information for %s, skipping",
            ticket.key,
        )
        return False
else:
    logger.warning("AI generation disabled, skipping %s", ticket.key)
    return False
```

**PollingService constructor changes:**
```python
def __init__(
    self,
    jira_client: JiraClient,
    polling_settings: PollingSettings,
    ac_generator: ACGenerator | None = None,  # New parameter
) -> None:
    self._jira_client = jira_client
    self._polling_settings = polling_settings
    self._ac_generator = ac_generator
```

### 2.6 Architecture Document Update

**File:** `context/product/architecture.md`

Update Section 4 (External Services & APIs):
```markdown
- **Anthropic Claude API:** AI-powered acceptance criteria generation (Claude Sonnet 4)
```

Remove AWS Bedrock reference.

---

## 3. Impact and Risk Analysis

### 3.1 System Dependencies

| Dependency | Impact |
|------------|--------|
| `PollingService` | New optional `ACGenerator` parameter; returns `False` if AI unavailable |
| `anthropic` package | New pip dependency (add to pyproject.toml) |
| Environment | Requires `ANTHROPIC_API_KEY` for AI functionality |

### 3.2 Potential Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| **API key not configured** | High (new env var) | Medium | Graceful skip with warning log |
| **Rate limiting (429)** | Medium | Medium | Anthropic SDK has built-in retry; log and skip on exhaustion |
| **Malformed AI response** | Low | Medium | Tool use ensures structured output; fallback to skip |
| **High API costs** | Low | Medium | Use Sonnet (cost-effective); limit to 1024 tokens |
| **AI generates poor ACs** | Medium | Low | Temperature=0.3 for consistency; users can regenerate |

---

## 4. Testing Strategy

### 4.1 Unit Tests

**File:** `tests/unit/test_ai_generator.py`

| Test Case | Description |
|-----------|-------------|
| `test_generate_acs_success` | Mock API returns valid tool_use response → list of ACs |
| `test_generate_acs_insufficient_info` | Mock returns `sufficient_information=false` → empty list |
| `test_generate_acs_empty_response` | Mock returns empty criteria → empty list |
| `test_generator_disabled_when_no_key` | `AISettings` with empty key → `is_enabled=False` |
| `test_parse_tool_use_response` | Validate JSON extraction from tool_use block |

**File:** `tests/unit/test_polling_service.py` (extend existing)

| Test Case | Description |
|-----------|-------------|
| `test_process_ticket_with_ai_generator` | ACGenerator returns ACs → writes to Jira |
| `test_process_ticket_ai_insufficient` | ACGenerator returns empty → skips without label |
| `test_process_ticket_no_ai_configured` | No generator → logs warning, returns False |

### 4.2 Integration Tests

**File:** `tests/integration/test_ai_generation.py`

| Test Case | Description |
|-----------|-------------|
| `test_generate_acs_real_api` | Real Claude API call with test ticket → valid ACs returned |
| `test_end_to_end_ticket_processing` | Process IGAL-1926 → ACs appear in Jira |
