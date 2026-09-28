-- Migration: 004_copied_history.sql
-- Description: Create copied_history table for tracking copied candidate details with RLS policies

CREATE TABLE IF NOT EXISTS copied_history (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_email        TEXT,
    mailbox_account   TEXT NOT NULL,
    candidate_email   TEXT NOT NULL,
    candidate_name    TEXT,
    candidate_phone   TEXT,
    job_description   TEXT,
    copied_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    notes             TEXT
);

CREATE INDEX IF NOT EXISTS idx_copied_history_copied_at
    ON copied_history (copied_at DESC);

CREATE INDEX IF NOT EXISTS idx_copied_history_mailbox
    ON copied_history (mailbox_account);

CREATE INDEX IF NOT EXISTS idx_copied_history_email
    ON copied_history (candidate_email);

ALTER TABLE copied_history ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "allow_all_copied_history" ON copied_history;
CREATE POLICY "allow_all_copied_history"
    ON copied_history
    FOR ALL
    USING (true)
    WITH CHECK (true);
