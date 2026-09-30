# AI Resume Shortlisting & Candidate Extraction Engine

An intelligent automated recruitment dashboard that integrates with Gmail to search mailboxes, download candidate resumes (.pdf, .docx), extract contact details, and evaluate candidate qualifications with AI against job descriptions.

## 🚀 Key Features

- **Smart Gmail Search**: Boolean search (`AND`, `OR`), multi-word queries with natural search semantics, and automatic keyword extraction from full Job Descriptions.
- **Multi-Account Switching**: Seamlessly switch between configured Gmail mailboxes (`recruiter@ecorptrainings.com`, `jai.ecorp@gmail.com`, `kumar.ecorp@gmail.com`, `pushpa@ecorptrainings.com`, `mahi@ecorptrainings.com`, `contact@ecorptrainings.com`).
- **AI-Powered Extraction**: Extracts candidate name, email, phone number, total experience, and technical skill set using Gemini AI.
- **Match Scoring & Ranking**: Computes a 0–100 match score, identifies matched JD skills, provides a one-line justification, and ranks candidates in descending order.
- **Excel Batch Candidate Extraction**:
  - Automatically downloads Excel (`.xlsx`, `.xls`) attachments in addition to PDF and DOCX files.
  - `excel_parser.py`: Automatically normalizes column names (`Name`, `Email`, `Phone`, `Skills`, `Experience`), merges multi-sheet workbooks, caps rows at 500 per file, and caches results in-memory for 10 minutes.
  - Gemini AI Fallback: Uses Gemini structured JSON extraction if column headers are unrecognizable or non-standard.
  - Results Table Integration: Candidate rows from Excel appear seamlessly alongside PDF/DOCX candidates, complete with `📊 Excel` source badge and hover tooltip showing file name, sheet, and row number.
  - Form Checkbox: Option to toggle `📊 Include Excel attachments (.xlsx / .xls)` (ON by default).
- **Candidate Status Tracking (Feature 3)**:
  - Persistent status per candidate (`🟢 New`, `🔵 Used`, `🟡 Not Used`).
  - Copy = Auto-Mark Used: Copying candidate info (individual or bulk) automatically updates status to `used` with optimistic UI update and a 5-second Undo Toast.
  - Interactive Status Badge: Clickable badge popup menu (`New`, `Used`, `Not Used`) for manual status overrides.
  - Toolbar Filters: Status filter (`All`, `New`, `Used`, `Not Used`) and default-checked `☑ Hide candidates marked as Used`.
- **Pagination via "Load More" (25 per page)**:
  - Replaces batch limit dropdown with smooth 25-per-page pagination.
  - Below table indicator: `Showing 25 of N matches [Load Next 25 →]`.
  - Caches full search result list server-side (in-memory & Supabase `search_cache`) with 1-hour TTL.
  - Continuous ranking (#26, #27...) on subsequent page loads.
- **Search History Log (Feature 1)**:
  - Stores all past searches persistently in Supabase (`search_history` table).
  - Dedicated `/history` page with Calendar Date Range Picker (`From`, `To`, `Last 30 Days`) and one-click **Re-run Search 🔄**.
- **Smart Search Popups & History Suggestions**:
  - **Feature A ("You searched this before")**: Displays a debounced (500ms) smart panel under the search box when searching a JD searched over 24 hours ago. Gives options to search again or view last results.
  - **Feature B ("New candidates since last search")**: Checks for new matching emails received since the last search date (within 30 days) and presents a modal to choose between searching new resumes only or searching everything.
  - **Feature C (Autocomplete Suggestions)**: Displays top 10 recent unique searches on search box focus with relative timestamps, last result count, and new candidate count badges.
- **Minimum Experience Filter (years)**:
  - Input field right below the JD/keyword textarea (`Min Experience (years)`).
  - Server-side experience parsing (handles formats like `"7 years"`, `"12.5 yrs"`, `"5 years 6 months"`, `"Over 10 years"`).
  - Filters out candidates with parsed experience below the threshold, while keeping candidates with unknown/unparseable experience tagged with a warning badge (`⚠️ ? yrs`).
  - Below table feedback showing exact count hidden (e.g. `Showing 25 of 100 matches · 12 hidden by experience`).
  - Interactive Experience column header sorting (`Exp ▲/▼`).
  - Persists `min_exp` across searches in `localStorage`.
  - Debug route available at `/debug-parse-exp?text=5+years+6+months`.
- **Copied History Panel**:
  - Slide-in side panel from right (`📋 Copied History` button in top nav) showing all candidate copies grouped by date (`Today`, `Yesterday`, `This Week`, `Older`).
  - Search box to filter copies by candidate name or email, date range buttons, mailbox filter, and CSV export (`📥 Export CSV`).
  - Counter badge on top nav button showing weekly copy count.
- **Skip Already-Copied Prompt on Re-Search**:
  - Automatically checks if candidates were copied for the same `(mailbox, job_description)`.
  - Prompts modal: `🆕 Skip already-copied` or `🔁 Show everything (including copies)`.
  - Remembers user session choice per search query with `⚙️ Change preference` link.
- **Debug & Health Monitoring**:
  - `/debug-status` route to verify Supabase table connectivity (`candidate_status`, `search_history`, `search_cache`).
  - `/debug-copied` route to verify `copied_history` table connection and recent records.

---

## 🗄️ Database Migrations (Supabase SQL)

Before using persistent status tracking, search history, or copied history, run the SQL migrations in your **Supabase SQL Editor**:

1. `migrations/001_search_history.sql`: Creates `search_history` table & indexes.
2. `migrations/002_seen_candidates.sql`: Creates `seen_candidates` table for cumulative batch search.
3. `migrations/003_candidate_status.sql`: Creates `candidate_status` table for tracking candidate statuses.
4. `migrations/004_copied_history.sql`: Creates `copied_history` table for tracking copied candidates.