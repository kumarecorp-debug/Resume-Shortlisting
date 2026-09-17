# AI Resume Shortlisting & Candidate Extraction Engine

An intelligent automated recruitment dashboard that integrates with Gmail to search mailboxes, download candidate resumes (.pdf, .docx), extract contact details, and evaluate candidate qualifications with AI against job descriptions.

## 🚀 Key Features
- **Smart Gmail Search**: Boolean search (`AND`, `OR`), multi-word queries with natural search semantics, and automatic keyword extraction from full Job Descriptions.
- **Multi-Account Switching**: Seamlessly switch between configured Gmail mailboxes.
- **AI-Powered Extraction**: Extracts candidate name, email, phone number, total experience, and technical skill set using Gemini AI.
- **Match Scoring & Ranking**: Computes a 0–100 match score, identifies matched JD skills, provides a one-line justification, and ranks candidates in descending order.
- **Interactive UI & Filtering**: Includes a real-time match score slider filter, quick keyword chips, and CSV export functionality.

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
   Copy `.env.example` to `.env` and configure your API keys:
   ```env
   GEMINI_API_KEY=your_gemini_api_key_here
   ```

4. **Setup Google OAuth Credentials**:
   Place your Google OAuth `client.json` (and `client_jai.json` if using multiple accounts) in the root directory.

5. **Run the Application**:
   ```bash
   python app.py
   ```
   Open `http://127.0.0.1:5000` in your web browser.
