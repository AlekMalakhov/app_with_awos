-- Add escalations table to record escalation attempts
-- Tracks both successful and failed Slack escalations for debugging and Phase 3 integration

CREATE TABLE IF NOT EXISTS escalations (
    id TEXT PRIMARY KEY,
    jira_ticket_key TEXT NOT NULL,
    confidence_score REAL NOT NULL,
    confidence_gaps TEXT NOT NULL,
    slack_user_id TEXT,
    status TEXT NOT NULL,
    error_message TEXT,
    created_at TEXT NOT NULL
);
