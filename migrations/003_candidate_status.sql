-- Migration 003: Candidate Status Tracking
CREATE TABLE IF NOT EXISTS candidate_status (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mailbox_account VARCHAR(255) NOT NULL,
    candidate_email VARCHAR(255) NOT NULL,
    candidate_name VARCHAR(255),
    status VARCHAR(50) DEFAULT 'new' CHECK (status IN ('new', 'used', 'skipped')),
    marked_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    notes TEXT,
    CONSTRAINT unique_mailbox_candidate UNIQUE (mailbox_account, candidate_email)
);

CREATE INDEX IF NOT EXISTS idx_candidate_status_mailbox_email 
ON candidate_status (mailbox_account, candidate_email);
