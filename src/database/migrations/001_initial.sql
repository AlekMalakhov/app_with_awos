-- Initial schema for conversations table
-- Stores conversation state for Slack DM interactions

CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    slack_user_id TEXT NOT NULL,
    slack_channel_id TEXT NOT NULL,
    jira_ticket_key TEXT,
    status TEXT NOT NULL DEFAULT 'AWAITING_TICKET',
    existing_acs TEXT,
    proposed_acs TEXT,
    message_history TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Index for finding active conversations by user and channel
CREATE INDEX IF NOT EXISTS idx_conversations_user_channel
ON conversations(slack_user_id, slack_channel_id);

-- Index for filtering by status
CREATE INDEX IF NOT EXISTS idx_conversations_status
ON conversations(status);
