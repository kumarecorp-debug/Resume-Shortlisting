# AI Resume Shortlisting & Candidate Extraction Engine

An intelligent automated recruitment dashboard that integrates with Gmail to search mailboxes, download candidate resumes (.pdf, .docx), extract contact details, and evaluate candidate qualifications with AI against job descriptions.

## 🚀 Key Features

- **Smart Gmail Search**: `has:attachment` Boolean search (`AND`, `OR`), multi-word queries, disk query caching, and exponential backoff.
- **Multi-Account Switching**: Seamlessly switch between configured Gmail mailboxes (`recruiter@ecorptrainings.com`, `jai.ecorp@gmail.com`, `kumar.ecorp@gmail.com`, `pushpa@ecorptrainings.com`, `mahi@ecorptrainings.com`, `contact@ecorptrainings.com`).
- **AI-Powered Extraction (Groq Primary)**: Uses high-throughput, ultra-fast Groq models (`llama-3.1-8b-instant`, `qwen/qwen3.8-27b`) with 5x batching (`extract_batch`), thread-safe rate limiting (25 RPM), and fallback to Gemini.
- **5x Batching & Production Performance**: Groups up to 5 resumes in a single Groq API call, reducing search duration from 110s down to ~25-35s for 22 resumes.
- **Vercel Timeout Guard & Real-Time Progress Streaming**: Includes `/api/search/start`, `/api/search/progress/<search_id>`, `/api/search/result/<search_id>` polling endpoints with a 50s server-side safety timeout to prevent Vercel 60s HTTP gateway timeouts.
- **Fast Mode**: Toggleable `⚡ Fast mode` checkbox to cap AI extractions at 30 candidates for maximum search speed.
- **Match Scoring & Ranking**: Computes a 0–100 match score, identifies matched JD skills, provides a one-line justification, and ranks candidates in descending order.
- **Candidate Status Tracking (Feature 3)**:
  - Persistent status per candidate (`🟢 New`, `🔵 Used`, `🟡 Skipped`).
  - Action buttons: "Mark Used", "Mark Skipped", and "📋 Copy & Mark Used".
  - Quick status filter (`Not Used`, `New Only`, `Used Only`, `Skipped Only`).
  - Bulk actions bar for marking multiple selected candidates simultaneously.
- **Repurposed Time Window Search History Filter**:
  - Time Window pills (`Today`, `Yesterday`, `7d`, `14d`, `30d`, `Custom 📅`) query the `search_history` database directly.
  - Super fast DB lookup with zero Gmail API calls and zero Gemini LLM extraction costs.
  - Stores full candidate JSON schemas (`name`, `email`, `phone`, `skills`, `experience`, `gender`, `matched_skills`, `match_score`, `match_reason`) in `search_history.candidates_seen`.
  - Toggle seamlessly between **⚡ Live Gmail Search** and **📅 From Search History**.
- **Search History Log & API**:
  - GET `/api/search/from-history` endpoint for querying candidate records filtered by time window, show mode (`Copied`, `Not Copied`), experience, and gender.
  - Dedicated `/history` page with Calendar Date Range Picker (`From`, `To`, `Last 7 Days`, `Last 30 Days`).
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

---

## 🛠️ Setup & Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/kumarecorp-debug/Resume-Shortlisting.git
   cd Resume-Shortlisting
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure Environment Variables**:
   Copy `.env.example` to `.env` and set your API keys:
   ```env
   GEMINI_API_KEY=your_gemini_api_key_here
   SUPABASE_URL=https://fvbctgxwjrctcssckggp.supabase.co
   SUPABASE_ANON_KEY=your_supabase_anon_key_here
   ```

4. **Run the Application**:
   ```bash
   python app.py
   ```
   Open `http://127.0.0.1:5000` in your web browser.
