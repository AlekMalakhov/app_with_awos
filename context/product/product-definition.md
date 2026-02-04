# Product Definition: Jira AC Assistant

- **Version:** 1.0
- **Status:** Proposed

---

## 1. The Big Picture (The "Why")

### 1.1. Project Vision & Purpose

To eliminate the manual effort and inconsistency in writing acceptance criteria by automatically generating high-quality, standardized ACs for Jira tickets — intelligently gathering missing details from AI assistants and human stakeholders when needed.

### 1.2. Target Audience

Development teams, Product Owners, and Delivery Managers who work with Jira to manage software delivery and need clear, actionable acceptance criteria to reduce ambiguity and speed up implementation.

### 1.3. User Personas

- **Persona 1: "Alex the Developer"**
  - **Role:** Software engineer on an agile team.
  - **Goal:** Wants clear, unambiguous acceptance criteria so they know exactly what "done" looks like before starting work.
  - **Frustration:** Often receives vague stories and has to chase POs for clarification, delaying work.

- **Persona 2: "Jordan the Product Owner"**
  - **Role:** Product Owner managing a backlog of 50+ tickets.
  - **Goal:** Wants to quickly create well-defined stories without spending 15+ minutes writing detailed ACs for each one.
  - **Frustration:** Writing consistent, high-quality ACs is time-consuming and repetitive.

- **Persona 3: "Sam the Delivery Manager"**
  - **Role:** Delivery Manager overseeing multiple teams.
  - **Goal:** Wants tickets to flow smoothly from creation to completion without bottlenecks.
  - **Frustration:** Poorly defined tickets cause delays and scope creep.

### 1.4. Success Metrics

- Reduce the number of clarification requests from developers back to POs by 50% or more.
- Achieve a consistent AC format across all generated tickets.
- At least 80% of auto-generated ACs are approved without major revisions.

---

## 2. The Product Experience (The "What")

### 2.1. Core Features

- **Automatic AC Generation from Jira Description** — Parse the story/task description and generate structured, actionable acceptance criteria using AI.
- **Barley AI Consultation** — When the description lacks sufficient detail, query the Barley API to gather additional context and enrich the ACs.
- **Slack DM Escalation** — If Barley cannot provide enough information, automatically send a Slack DM to the Product Owner or Delivery Manager requesting clarification and approval of the generated ACs.
- **Dual Trigger Modes** — Support both automatic triggering on ticket creation and manual re-triggering on demand.
- **AC Approval Workflow** — Allow stakeholders to review and approve generated ACs via Slack before they are finalized.

### 2.2. User Journey

1. A Product Owner creates a new Story or Task in Jira with a description.
2. The Jira AC Assistant is automatically triggered (or manually invoked).
3. The assistant analyzes the description and generates draft acceptance criteria.
4. If the description lacks detail, the assistant queries the Barley API for additional context.
5. If Barley cannot provide sufficient information, the assistant sends a Slack DM to the PO or DM asking for clarification.
6. The PO/DM reviews the generated ACs in Slack and approves or requests changes.
7. Once approved, the ACs are written back to the Jira ticket.
8. The development team can begin work with clear, agreed-upon acceptance criteria.

---

## 3. Project Boundaries

### 3.1. What's In-Scope for this Version

- Integration with Jira to read ticket descriptions and write acceptance criteria.
- AI-powered AC generation from ticket content.
- Integration with Barley API for context enrichment.
- Slack integration for DM-based escalation to PO/DM.
- Approval workflow via Slack.
- Support for both automatic and manual triggering.
- Single Jira project support.

### 3.2. What's Out-of-Scope (Non-Goals)

- Custom UI components within Jira (no Jira Forge/Connect apps for editing).
- Machine learning from feedback (no training on accepted/rejected ACs).
- Multi-project support (V1 targets a single Jira project).
- Automated test case generation from ACs.
- Mobile app or standalone web UI.
