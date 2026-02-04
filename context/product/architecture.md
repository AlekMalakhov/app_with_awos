# System Architecture Overview: Jira AC Assistant

---

## 1. Application & Technology Stack

- **Backend Framework:** Python + FastAPI
- **AI/LLM Provider:** AWS Bedrock
- **Language Version:** Python 3.11+

---

## 2. Data & Persistence

- **Primary Database:** SQLite (file-based)
- **Data Stored:** Workflow state (ticket IDs, AC generation status, approval status), conversation context with Barley/Slack

---

## 3. Infrastructure & Deployment

- **Deployment Model:** Local Docker container
- **Container Runtime:** Docker
- **Configuration:** Environment variables for API keys and service URLs

---

## 4. External Services & APIs

- **Jira Cloud API:** Read ticket descriptions, write acceptance criteria back to tickets
- **Jira Trigger Mechanism:** Jira Automation rules (calls service endpoint on ticket creation)
- **Barley API:** Context enrichment when ticket descriptions lack detail (Phase 2)
- **Slack API:** DM escalation to PO/DM, approval workflow via Slack interactions (Phase 2-3)
- **AWS Bedrock:** AI-powered acceptance criteria generation

---

## 5. Observability & Monitoring

- **Logging:** Basic structured logging to stdout/file
- **Log Format:** JSON for easy parsing
- **Future Enhancement:** CloudWatch or centralized logging for production deployment
