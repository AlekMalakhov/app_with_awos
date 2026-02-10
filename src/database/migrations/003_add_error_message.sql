-- Add error_message column to store user-friendly error messages
-- This is used when conversation enters ERROR status

ALTER TABLE conversations ADD COLUMN error_message TEXT;
