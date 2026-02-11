# Functional Specification: Barley AI Consultation

- **Roadmap Item:** Barley AI Consultation (Phase 2) — Connect to Barley's API to query for additional context and define rules for context enrichment.
- **Status:** Completed
- **Author:** AI-assisted

---

## 1. Overview and Rationale (The "Why")

Today, the Jira AC Assistant generates acceptance criteria based solely on the Jira ticket description. When descriptions are vague or lack business context, the generated ACs may be shallow or miss important domain-specific requirements. This forces developers to seek clarification from Product Owners, creating delays.

**Barley AI Consultation** adds an intelligence layer to the AC generation pipeline. By querying Barley's API for project context and business domain knowledge on every ticket, the system can produce richer, more informed acceptance criteria — even when the ticket description itself is sparse.

**Desired outcome:** Higher quality ACs that reflect broader business context, reducing the need for human clarification requests. This directly supports the success metric of reducing developer-to-PO clarification requests by 50%+.

---

## 2. Functional Requirements (The "What")

### 2.1. Topic Extraction from Ticket Description

Before querying Barley, the system must analyze the Jira ticket description and extract key topics and entities relevant to the ticket's intent.

- The AI analyzes the ticket description and identifies the core topics, entities, and domain concepts.
- These extracted topics are combined into a single query payload for Barley.

**Acceptance Criteria:**
- [x] Given a Jira ticket with a description, the system extracts key topics/entities from the description before querying Barley.
- [x] The extracted topics are combined into a single consolidated query (not multiple separate queries).

### 2.2. Barley API Integration

The system must connect to Barley's API and query it for project context and business domain knowledge using the extracted topics.

- The system sends a single combined query (derived from extracted topics) to Barley's API for every ticket that enters the AC generation pipeline.
- Barley returns relevant project context and domain knowledge related to the queried topics.

**Acceptance Criteria:**
- [x] Given any Jira ticket entering the AC generation pipeline, the system always queries Barley's API — regardless of description quality or length.
- [x] The query sent to Barley contains the AI-extracted key topics from the ticket description.
- [x] The system receives and processes the response from Barley's API.

### 2.3. Context Enrichment for AC Generation

The Barley response is fed into the AC generation process to produce higher-quality acceptance criteria.

- The context returned by Barley is combined with the original ticket description to provide a richer input for AC generation.
- If Barley returns no relevant context (empty or irrelevant response), the system proceeds with AC generation using only the ticket description (best-effort ACs). No error or warning is surfaced to the user in this case.

**Acceptance Criteria:**
- [x] Given Barley returns relevant context, the system uses both the ticket description and the Barley context as input for AC generation.
- [x] Given Barley returns no relevant context, the system generates ACs using only the ticket description without any error or interruption.
- [x] ACs generated with Barley enrichment reflect the additional domain context (i.e., they are measurably richer than ACs generated from the description alone).

### 2.4. Barley Context Storage

The Barley enrichment context must be stored on the Jira ticket for transparency, accessible to users on request.

- After Barley is consulted, the system posts the Barley context as a comment on the Jira ticket.
- This allows any team member to review what additional context was used to inform the ACs.

**Acceptance Criteria:**
- [x] Given Barley returns relevant context, the system posts that context as a comment on the corresponding Jira ticket.
- [x] The comment clearly identifies itself as Barley-sourced context (e.g., prefixed with a label like "Barley AI Context").
- [x] Given Barley returns no relevant context, no comment is posted to the Jira ticket.

### 2.5. Barley API Unavailability Handling

The system must not block the AC generation pipeline if Barley is unavailable.

- If the Barley API call fails (timeout, server error, network issue), the system skips Barley enrichment entirely and proceeds to generate ACs from the ticket description alone.
- No retry is attempted. The pipeline continues without delay.

**Acceptance Criteria:**
- [x] Given the Barley API is unavailable (timeout, 5xx error, network failure), the system skips Barley enrichment and generates ACs from the ticket description alone.
- [x] No retry is attempted on Barley API failure.
- [x] The AC generation pipeline is not blocked or delayed by Barley unavailability.

---

## 3. Scope and Boundaries

### In-Scope

- Barley API connection and authentication.
- AI-driven topic extraction from Jira ticket descriptions.
- Single combined query to Barley per ticket.
- Using Barley context to enrich the AC generation input.
- Posting Barley context as a Jira comment for transparency.
- Graceful handling of Barley unavailability (skip and proceed).
- Integration into the existing AC generation pipeline (runs for every ticket).

### Out-of-Scope

- **Slack Integration Foundation** — Slack API connection and PO/DM escalation via DM (separate roadmap item).
- **AC Approval Workflow** — AC review, approve/request changes flow, and writing approved ACs to Jira (Phase 3 roadmap item).
- **Operational Refinements** — Notification & status tracking, error handling & retry logic (Phase 3 roadmap item).
- Multiple Barley queries per ticket (the system uses a single consolidated query).
- Barley context editing or modification by users.
- Custom configuration of when to consult Barley (it always consults Barley).
- Feedback loop from AC approval outcomes back to Barley queries.
