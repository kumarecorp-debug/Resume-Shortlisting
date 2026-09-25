-- Migration 002: Seen Candidates Tracking
CREATE TABLE IF NOT EXISTS seen_candidates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mailbox_account VARCHAR(255) NOT NULL,
    job_description_hash VARCHAR(64) NOT NULL,
    candidate_email VARCHAR(255) NOT NULL,
    candidate_name VARCHAR(255),
    first_seen_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_seen_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT unique_mailbox_jd_candidate UNIQUE (mailbox_account, job_description_hash, candidate_email)
);

CREATE INDEX IF NOT EXISTS idx_seen_candidates_lookup 
ON seen_candidates (mailbox_account, job_description_hash);
