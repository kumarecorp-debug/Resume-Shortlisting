# AI Resume Shortlisting & Candidate Extraction Engine

An intelligent automated recruitment dashboard that integrates with Gmail to search mailboxes, download candidate resumes (.pdf, .docx), extract contact details, and evaluate candidate qualifications with AI against job descriptions.

## 🚀 Key Features

- **Smart Gmail Search**: Boolean search (`AND`, `OR`), multi-word queries with natural search semantics, and automatic keyword extraction from full Job Descriptions.
- **Multi-Account Switching**: Seamlessly switch between configured Gmail mailboxes (`recruiter@ecorptrainings.com`, `jai.ecorp@gmail.com`, `kumar.ecorp@gmail.com`, `pushpa@ecorptrainings.com`, `mahi@ecorptrainings.com`, `contact@ecorptrainings.com`).
- **AI-Powered Extraction**: Extracts candidate name, email, phone number, total experience, and technical skill set using Gemini AI.
- **Match Scoring & Ranking**: Computes a 0–100 match score, identifies matched JD skills, provides a one-line justification, and ranks candidates in descending order.
- **Candidate Status Tracking (Feature 3)**:
  - Persistent status per candidate (`🟢 New`, `🔵 Used`, `🟡 Skipped`).
  - Action buttons: "Mark Used", "Mark Skipped", and "📋 Copy & Mark Used".
  - Quick status filter (`Not Used`, `New Only`, `Used Only`, `Skipped Only`).
  - Bulk actions bar for marking multiple selected candidates simultaneously.
- **Search History Log (Feature 1)**:
  - Stores all past searches persistently in Supabase.
  - Dedicated `/history` page with Calendar Date Range Picker (`From`, `To`, `Last 7 Days`, `Last 30 Days`).
  - One-click **Re-run Search 🔄** functionality.
- **Cumulative Batch Search (Feature 2)**:
  - "Skip already-seen candidates" toggle to filter out candidates returned in previous searches.
  - Displays summary banner showing new vs hidden candidates with `[Show seen too]` toggle.
- **Debug & Health Monitoring**:
  - `/debug-status` route to verify Supabase table connectivity and row counts.

---

## 🗄️ Database Migrations (Supabase SQL)

Before using persistent status tracking or search history, run the SQL migrations in your **Supabase SQL Editor**:

1. `migrations/001_search_history.sql`: Creates `search_history` table & indexes.
2. `migrations/002_seen_candidates.sql`: Creates `seen_candidates` table for cumulative batch search.
3. `migrations/003_candidate_status.sql`: Creates `candidate_status` table for tracking candidate statuses.