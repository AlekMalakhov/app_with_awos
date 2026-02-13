-- Add slack_thread_ts column for threading DM responses
ALTER TABLE conversations ADD COLUMN slack_thread_ts TEXT;
