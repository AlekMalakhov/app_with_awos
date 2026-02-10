# Functional Specification: Manual Re-Trigger Capability

- **Roadmap Item:** Manual Re-Trigger Capability — Allow users to manually request AC regeneration on demand.
- **Status:** Completed
- **Author:** AI Assistant

---

## 1. Overview and Rationale (The "Why")

### Problem Statement
Currently, acceptance criteria are only generated automatically when a Jira ticket is first created. If the ticket description is updated after creation, or if the initial ACs are insufficient, there is no way for users to request fresh acceptance criteria without creating a new ticket.

### User Pain Points
- **Jordan the PO** often refines ticket descriptions after initial creation based on stakeholder feedback, but cannot get updated ACs.
- **Alex the Developer** may find existing ACs unclear or incomplete and has no mechanism to request regeneration.
- Descriptions frequently evolve during backlog grooming sessions, making initial ACs outdated.

### Desired Outcome
Any user with Jira access can request AC regeneration via a natural language message to the Slack bot. The system presents a comparison of existing vs. newly generated ACs, allowing the user to approve, reject, or request modifications before changes are written to Jira.

### Success Criteria
- Users can successfully trigger AC regeneration via Slack DM.
- The diff/comparison flow allows informed decision-making before overwriting ACs.
- At least 80% of manually regenerated ACs are approved without requiring multiple revision cycles.

---

## 2. Functional Requirements (The "What")

### 2.1 Trigger Regeneration via Slack DM

- **As a** user with Jira access, **I want to** send a natural language message to the AC Assistant bot in Slack requesting AC regeneration, **so that** I can get updated acceptance criteria when the ticket description changes.

  - **Acceptance Criteria:**
    - [x] Given I have a DM conversation with the AC Assistant bot, when I send a message asking to regenerate ACs for a ticket (e.g., "regenerate ACs for PROJ-123", "refresh the acceptance criteria on PROJ-456", "please update ACs for ticket PROJ-789"), then the bot acknowledges the request and begins processing.
    - [x] Given my message includes a valid Jira ticket key, when the bot processes the request, then it reads the current ticket description from Jira.
    - [x] Given my message does not include a recognizable ticket key, when the bot processes the request, then it asks me to provide the ticket key.

### 2.2 Generate and Present Comparison

- **As a** user who triggered regeneration, **I want to** see both the existing ACs and the newly generated ACs side-by-side, **so that** I can make an informed decision about which to keep.

  - **Acceptance Criteria:**
    - [x] Given regeneration is triggered for a ticket with existing ACs, when generation completes, then the bot sends a Slack DM showing: (1) the current/existing ACs, (2) the newly generated ACs, clearly labeled.
    - [x] Given regeneration is triggered for a ticket with no existing ACs, when generation completes, then the bot sends a Slack DM showing only the newly generated ACs with a note that no previous ACs existed.
    - [x] Given the comparison is displayed, when the user views it, then clear instructions are provided on how to approve, reject, or request changes.

### 2.3 Approval Flow via Natural Language

- **As a** user reviewing the comparison, **I want to** respond in natural language to approve, reject, or request modifications, **so that** I don't need to remember specific commands.

  - **Acceptance Criteria:**
    - [x] Given the comparison has been presented, when I reply with an affirmative response (e.g., "looks good", "approve", "yes", "go ahead", "use the new ones"), then the bot interprets this as approval.
    - [x] Given I approve the new ACs, when the bot processes approval, then the new ACs replace the existing ACs on the Jira ticket.
    - [x] Given I approve and ACs are written successfully, when the update completes, then the bot confirms with a message like "Done! ACs updated on PROJ-123." including a clickable link to the Jira ticket.
    - [x] Given the comparison has been presented, when I reply with a negative response (e.g., "no", "reject", "keep the original", "nope"), then the bot interprets this as rejection and does not update the Jira ticket.
    - [x] Given I reject the new ACs, when the bot processes rejection, then the bot confirms the original ACs remain unchanged.
    - [x] Given the comparison has been presented, when I reply indicating I want changes (e.g., "can you add X", "the second criterion is wrong", "needs to include Y"), then the bot asks clarifying questions about the desired changes.
    - [x] Given I provide feedback for modifications, when the bot processes my feedback, then it regenerates ACs incorporating my feedback and presents a new comparison.
    - [x] Given the approval request is pending, when no timeout is configured, then the request remains pending indefinitely until I respond.

### 2.4 Error Handling

- **As a** user, **I want to** receive clear, specific error messages with guidance, **so that** I can understand what went wrong and how to resolve it.

  - **Acceptance Criteria:**
    - [x] Given I request regeneration for a ticket key that does not exist, when the bot checks Jira, then I receive: "I couldn't find ticket [KEY] in Jira. Please check the ticket key and try again."
    - [x] Given I request regeneration for a ticket with an empty description, when the bot reads the ticket, then I receive: "Ticket [KEY] doesn't have a description. Please add a description in Jira and try again."
    - [x] Given the Jira API is unavailable, when the bot attempts to read or write, then I receive: "I'm having trouble connecting to Jira right now. Please try again in a few minutes."
    - [x] Given I don't have permission to view the requested ticket, when the bot attempts to read it, then I receive: "I don't have access to ticket [KEY]. Please check that the ticket exists and that the bot has the necessary permissions."

---

## 3. Scope and Boundaries

### In-Scope

- Triggering AC regeneration via natural language message to the Slack bot in a DM.
- Presenting a comparison of existing vs. newly generated ACs in Slack DM.
- Natural language understanding for approval, rejection, and modification requests.
- Clarifying questions flow when user requests modifications.
- Writing approved ACs back to Jira with confirmation message and link.
- Specific error messages with retry guidance for common failure scenarios.
- Support for any user with Jira access (no role restrictions).

### Out-of-Scope

- **Jira comment triggering** — Regeneration is only supported via Slack DM, not via Jira comments.
- **Interactive Slack buttons** — Approval uses natural language replies only, not button UI.
- **Approval timeout** — No automatic action on timeout; requests remain pending indefinitely.
- **Barley AI Consultation** — Covered in a separate specification (Phase 2 roadmap item).
- **Slack Integration Foundation** — Covered in a separate specification (Phase 2 roadmap item).
- **AC Approval Workflow** — The broader PO/DM approval workflow is covered in Phase 3; this spec covers only the individual user's manual trigger flow.
- **Notification & Status Tracking** — Covered in Phase 3 Operational Refinements.
- **Error Handling & Retry Logic** — Broader retry mechanisms covered in Phase 3; this spec covers user-facing error messages only.
