-- Migration 001: Search History
CREATE TABLE IF NOT EXISTS search_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_email VARCHAR(255) NOT NULL,
    mailbox_account VARCHAR(255) NOT NULL,
    job_description TEXT NOT NULL,
    batch_size INT DEFAULT 25,
    results_count INT DEFAULT 0,
    searched_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    candidates_seen JSONB DEFAULT '[]'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_search_history_searched_at 
ON search_history (searched_at DESC);

CREATE INDEX IF NOT EXISTS idx_search_history_mailbox 
ON search_history (mailbox_account);
