# Product Roadmap: Jira AC Assistant

_This roadmap outlines our strategic direction based on customer needs and business goals. It focuses on the "what" and "why," not the technical "how."_

---

### Phase 1

_The foundational integration layer — connecting to Jira and generating basic ACs._

- [ ] **Jira Integration Foundation**
  - [x] **Jira API Connection:** Establish secure connection to read ticket descriptions from Stories and Tasks.
  - [x] **Write ACs Back to Jira:** Enable writing generated acceptance criteria to the ticket's AC field.

- [ ] **Core AC Generation**
  - [x] **AI-Powered AC Generation:** Parse ticket descriptions and generate structured, actionable acceptance criteria using AI.
  - [x] **Automatic Trigger on Ticket Creation:** Automatically invoke AC generation when a new Story/Task is created.
  - [x] **Manual Re-Trigger Capability:** Allow users to manually request AC regeneration on demand.

---

### Phase 2

_Intelligence layer — enriching context when descriptions lack detail._

- [x] **Barley AI Consultation**
  - [x] **Barley API Integration:** Connect to Barley's API to query for additional context when ticket descriptions are insufficient.
  - [x] **Context Enrichment Logic:** Define rules for when to escalate to Barley (e.g., missing user stories, unclear scope).

- [ ] **Slack Integration Foundation**
  - [ ] **Slack API Connection:** Establish secure connection to send direct messages via Slack.
  - [ ] **PO/DM Escalation via DM:** When Barley cannot provide enough information, send a Slack DM to the Product Owner or Delivery Manager requesting clarification.

---

### Phase 3

_Approval workflow — closing the loop with human stakeholders._

- [ ] **AC Approval Workflow**
  - [ ] **AC Review in Slack:** Present generated ACs to PO/DM in Slack for review.
  - [ ] **Approve/Request Changes Flow:** Allow stakeholders to approve ACs or request modifications via Slack interactions.
  - [ ] **Write Approved ACs to Jira:** Automatically update Jira ticket with approved acceptance criteria.

- [ ] **Operational Refinements**
  - [ ] **Notification & Status Tracking:** Provide visibility into AC generation status (pending, awaiting approval, approved).
  - [ ] **Error Handling & Retry Logic:** Gracefully handle API failures and provide retry mechanisms.
