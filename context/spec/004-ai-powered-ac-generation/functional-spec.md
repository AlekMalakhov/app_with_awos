# Functional Specification: AI-Powered AC Generation

- **Roadmap Item:** AI-Powered AC Generation — Parse ticket descriptions and generate structured, actionable acceptance criteria using AI.
- **Status:** Completed
- **Author:** Product Analyst

---

## 1. Overview and Rationale (The "Why")

### Problem Statement
Currently, the Jira AC Assistant has all the infrastructure in place — it reads tickets, triggers on creation, and writes ACs back to Jira — but uses hardcoded test ACs. Without real AI-powered generation, Product Owners still spend 15+ minutes per ticket writing detailed acceptance criteria, and developers receive inconsistent or missing ACs that lead to clarification delays.

### Desired Outcome
When a ticket is processed, the system uses Claude AI to analyze the ticket's summary and description, then generates 3-7 structured, actionable acceptance criteria tailored to the specific ticket content. Developers immediately see meaningful, context-aware ACs instead of placeholders.

### Success Criteria
- At least 80% of auto-generated ACs are approved without major revisions.
- Generated ACs are specific to the ticket content (not generic boilerplate).
- System gracefully handles tickets with insufficient descriptions by skipping generation.

---

## 2. Functional Requirements (The "What")

### 2.1. Generate ACs Using Claude AI

- **As a** developer, **I want** acceptance criteria to be generated based on the actual ticket content, **so that** I understand what "done" looks like without chasing the PO for clarification.

  - **Acceptance Criteria:**
    - [x] When a ticket is processed, the system sends the ticket summary and description to Claude Sonnet 4.
    - [x] The AI generates 3-7 acceptance criteria based on the ticket content.
    - [x] The AI uses a flexible format (Given-When-Then, checkbox statements, or mixed) based on what best fits the requirement.
    - [x] Generated ACs are specific to the ticket (not generic boilerplate like "Code is tested").

### 2.2. Handle Insufficient Descriptions

- **As a** system operator, **I want** the system to skip AC generation when descriptions are too vague, **so that** we don't write meaningless ACs to tickets.

  - **Acceptance Criteria:**
    - [x] The AI assesses whether the ticket has sufficient information to generate meaningful ACs.
    - [x] If the AI determines the description is insufficient, no ACs are written to Jira.
    - [x] When generation is skipped, the system logs the ticket key and reason ("insufficient description").
    - [x] The `ac-generated` label is NOT added when generation is skipped.

### 2.3. Structured AI Response

- **As a** system operator, **I want** the AI to return responses in a predictable format, **so that** the system can reliably parse and process the generated ACs.

  - **Acceptance Criteria:**
    - [x] The AI response is parsed into a list of individual AC strings.
    - [x] If the AI response cannot be parsed (malformed), the system logs an error and skips writing.
    - [x] Empty AI responses are treated as "insufficient description" (no ACs written).

### 2.4. AI Configuration

- **As a** system operator, **I want** AI settings to be configurable via environment variables, **so that** I can adjust the model and behavior without code changes.

  - **Acceptance Criteria:**
    - [x] `ANTHROPIC_API_KEY` environment variable is required for AI functionality.
    - [x] `AI_MODEL` environment variable allows specifying the Claude model (default: `claude-sonnet-4-20250514`).
    - [x] If `ANTHROPIC_API_KEY` is not set, the system logs a warning and skips AI generation (uses existing fallback behavior).

---

## 3. Scope and Boundaries

### In-Scope

- Integration with Anthropic Claude API for AC generation.
- Sending ticket summary and description to the AI.
- AI self-assessment of description sufficiency.
- Parsing AI response into individual ACs.
- Configurable AI model via environment variable.
- Logging when generation is skipped due to insufficient description.
- Generating 3-7 ACs per ticket using flexible format.

### Out-of-Scope

- **Write ACs Back to Jira** — Already implemented (Spec 003).
- **Automatic Trigger on Ticket Creation** — Already implemented (Spec 002).
- **Manual Re-Trigger Capability** — Separate roadmap item (Phase 1).
- **Barley AI Consultation** — Separate roadmap item (Phase 2).
- **Slack Integration Foundation** — Separate roadmap item (Phase 2).
- **AC Approval Workflow** — Separate roadmap item (Phase 3).
- **Notification & Status Tracking** — Separate roadmap item (Phase 3).
- **Error Handling & Retry Logic (comprehensive)** — Separate roadmap item (Phase 3).
- Fine-tuning or training the AI on accepted/rejected ACs.
- Custom prompt editing via UI.
- Cost tracking or usage limits for AI calls.

---

## 4. Testing

- **Test Ticket:** [IGAL-1926](https://provectus-dev.atlassian.net/browse/IGAL-1926)
