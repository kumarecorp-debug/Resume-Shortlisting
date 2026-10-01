-- Migration 005: Store full candidate objects in search_history.candidates_seen
-- Description: Updates candidate tracking from email strings ["a@x.com"] to full JSON objects [{"email": "a@x.com", "name": "...", "phone": "...", "skills": "...", "experience": "..."}]

COMMENT ON COLUMN public.search_history.candidates_seen IS 'Stores JSON array of full candidate objects: [{email, name, gender, phone, skills, experience, matched_skills, match_score, match_reason}]';
