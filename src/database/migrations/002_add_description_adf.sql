-- Add description_adf column to store original ticket description in ADF format
-- This is needed for the approval flow to merge new ACs into the original description

ALTER TABLE conversations ADD COLUMN description_adf TEXT;
