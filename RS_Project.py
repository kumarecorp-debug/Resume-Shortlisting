import os
import re
import time
import json
import logging
import io
import shutil
import tempfile
import pickle
import hashlib
from datetime import datetime, timedelta, timezone
from dateutil.parser import parse
import pytz
import pandas as pd
from tabulate import tabulate
from docx import Document
from PyPDF2 import PdfReader
from pdfminer.high_level import extract_text

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from base64 import urlsafe_b64decode

try:
    from gmail_search import build_gmail_search_query, extract_tech_keywords_from_jd
except ImportError:
    from .gmail_search import build_gmail_search_query, extract_tech_keywords_from_jd

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Paths and Config
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
    RESUME_FOLDER = os.path.join(tempfile.gettempdir(), "Resumes")
else:
    try:
        RESUME_FOLDER = os.path.join(SCRIPT_DIR, "Resumes")
        os.makedirs(RESUME_FOLDER, exist_ok=True)
    except Exception:
        RESUME_FOLDER = os.path.join(tempfile.gettempdir(), "Resumes")

os.makedirs(RESUME_FOLDER, exist_ok=True)

OUTPUT_CSV = os.path.join(RESUME_FOLDER, "resume_analysis.csv")
CLIENT_SECRET_FILE = os.path.join(SCRIPT_DIR, "client.json")
TOKEN_FILE = os.path.join(SCRIPT_DIR, "token.json")

GMAIL_CACHE_DIR = os.path.join(SCRIPT_DIR, "cache", "gmail_queries")
os.makedirs(GMAIL_CACHE_DIR, exist_ok=True)

try:
    load_dotenv(os.path.join(SCRIPT_DIR, ".env"))
    load_dotenv(os.path.join(os.path.dirname(SCRIPT_DIR), ".env"))
except ImportError:
    pass

# Gemini API Configuration & Model list
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
DEFAULT_GEMINI_MODELS = [
    "gemini-3.8-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-flash-latest",
]
WORKING_GEMINI_MODEL = None
AI_MODEL_DISABLED = False
AI_FAILED_COUNT = 0

genai_client = None
try:
    from google import genai
    from google.genai import types
    USE_MODERN_GENAI = True
    if GEMINI_API_KEY:
        try:
            genai_client = genai.Client(api_key=GEMINI_API_KEY)
            logging.info("Initialized Google GenAI client.")
        except Exception as e:
            logging.warning(f"Failed to initialize GenAI client: {e}")
except ImportError:
    USE_MODERN_GENAI = False

# Technical Skills Dictionary
KNOWN_SKILLS = [
    "python", "snowflake", "sql", "postgresql", "mysql", "oracle", "mongodb",
    "aws", "azure", "gcp", "docker", "kubernetes", "terraform", "ci/cd",
    "pyspark", "spark", "hadoop", "databricks", "kafka", "airflow", "etl", "dbt",
    "java", "spring boot", "c++", "c#", ".net", "javascript", "typescript", "react",
    "angular", "node.js", "django", "flask", "fastapi", "rest api", "graphql",
    "html", "css", "machine learning", "deep learning", "nlp", "llm", "pandas",
    "numpy", "scikit-learn", "tensorflow", "pytorch", "tableau", "power bi",
    "linux", "git", "jira", "agile", "scrum", "devops", "microservices",
    "sap", "grc", "hana", "basis", "abap", "ui5", "fiori", "capm", "scm", "fusion",
    "hcm", "oic", "faw", "fdi", "bip", "otbi", "plsql", "pl/sql", "toad", "rice"
]

# Supported Gmail Accounts Configuration
SUPPORTED_ACCOUNTS = {
    "recruiter@ecorptrainings.com": {
        "name": "Recruiter Account",
        "email": "recruiter@ecorptrainings.com",
        "client_file": "client.json",
        "token_file": "token.json",
        "env_var": "GOOGLE_TOKEN_JSON"
    },
    "jai.ecorp@gmail.com": {
        "name": "Jai Ecorp Account",
        "email": "jai.ecorp@gmail.com",
        "client_file": "client_jai.json",
        "token_file": "token_jai.json",
        "env_var": "GOOGLE_TOKEN_JAI_JSON"
    },
    "kumar.ecorp@gmail.com": {
        "name": "Kumar Ecorp Account",
        "email": "kumar.ecorp@gmail.com",
        "client_file": "client_kumar.json",
        "token_file": "token_kumar.json",
        "env_var": "GOOGLE_TOKEN_KUMAR_JSON"
    },
    "pushpa@ecorptrainings.com": {
        "name": "Pushpa Account",
        "email": "pushpa@ecorptrainings.com",
        "client_file": "client_pushpa.json",
        "token_file": "token_pushpa.json",
        "env_var": "GOOGLE_TOKEN_PUSHPA_JSON"
    },
    "mahi@ecorptrainings.com": {
        "name": "Mahi Account",
        "email": "mahi@ecorptrainings.com",
        "client_file": "client_mahi.json",
        "token_file": "token_mahi.json",
        "env_var": "GOOGLE_TOKEN_MAHI_JSON"
    },
    "contact@ecorptrainings.com": {
        "name": "Contact Account",
        "email": "contact@ecorptrainings.com",
        "client_file": "client_contact.json",
        "token_file": "token_contact.json",
        "env_var": "GOOGLE_TOKEN_CONTACT_JSON"
    }
}

# Exponential Backoff Helper for Gmail API (FIX 8)
def gmail_call_with_retry(func, retries=5, backoff_delays=[5, 15, 30, 60, 120]):
    for attempt in range(retries):
        try:
            return func()
        except Exception as e:
            err_str = str(e)
            if any(term in err_str.lower() for term in ["ratelimitexceeded", "403", "429", "quotaexceeded"]):
                delay = backoff_delays[min(attempt, len(backoff_delays) - 1)]
                logging.warning(f"[gmail-retry] Rate limit hit. Retry {attempt + 1}/{retries} in {delay}s...")
                time.sleep(delay)
            else:
                raise e
    raise RuntimeError("Gmail API request failed after maximum retries.")

# Cached Gmail Messages Listing (FIX 8)
def fetch_messages_cached(service, query, mailbox, max_results=25, ttl=3600):
    key = hashlib.md5(f"{mailbox}|{query}|{max_results}".encode('utf-8')).hexdigest()
    cache_file = os.path.join(GMAIL_CACHE_DIR, f"{key}.pkl")
    if os.path.exists(cache_file) and (time.time() - os.path.getmtime(cache_file)) < ttl:
        try:
            with open(cache_file, 'rb') as f:
                cached_msgs = pickle.load(f)
                return cached_msgs
        except Exception:
            pass

    limit = min(max_results, 500)
    def api_call():
        return service.users().messages().list(
            userId="me", q=query, maxResults=limit
        ).execute()

    res = gmail_call_with_retry(api_call)
    messages = res.get('messages', []) if res else []
    
    try:
        with open(cache_file, 'wb') as f:
            pickle.dump(messages, f)
    except Exception:
        pass

    return messages

def auto_authenticate_google(account_email="recruiter@ecorptrainings.com"):
    """Authenticates with Google Gmail API for specified mailbox."""
    if isinstance(account_email, dict):
        account_email = account_email.get("email", "recruiter@ecorptrainings.com")
    email_key = account_email.lower().strip() if account_email else "recruiter@ecorptrainings.com"
    acct_config = SUPPORTED_ACCOUNTS.get(email_key, SUPPORTED_ACCOUNTS["recruiter@ecorptrainings.com"])
    
    client_fname = acct_config["client_file"]
    token_fname = acct_config["token_file"]
    primary_env = acct_config.get("env_var", "")
    SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
    creds = None

    username_prefix = email_key.split('@')[0].replace('.', '_').upper()
    env_token_keys = [
        primary_env,
        f"GOOGLE_TOKEN_{username_prefix}_JSON",
        f"TOKEN_{username_prefix}_JSON",
        f"GMAIL_TOKEN_{username_prefix}"
    ]
    seen = set()
    env_token_keys = [k for k in env_token_keys if k and not (k in seen or seen.add(k))]

    for env_k in env_token_keys:
        env_token_str = os.environ.get(env_k, "").strip()
        if env_token_str:
            try:
                token_data = json.loads(env_token_str)
                creds = Credentials.from_authorized_user_info(token_data, SCOPES)
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                if creds and creds.valid:
                    logging.info(f"Successfully authenticated {email_key} via {env_k}")
                    return build('gmail', 'v1', credentials=creds)
            except Exception as e:
                logging.warning(f"Failed to load token from environment variable {env_k}: {e}")
                creds = None

    token_file = os.path.join(SCRIPT_DIR, token_fname)
    if not os.path.exists(token_file):
        parent_token = os.path.join(os.path.dirname(SCRIPT_DIR), token_fname)
        if os.path.exists(parent_token):
            token_file = parent_token

    if os.path.exists(token_file):
        try:
            creds = Credentials.from_authorized_user_file(token_file, SCOPES)
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                with open(token_file, 'w', encoding='utf-8') as token:
                    token.write(creds.to_json())
            if creds and creds.valid:
                return build('gmail', 'v1', credentials=creds)
        except Exception as e:
            logging.warning(f"Existing token file for {email_key} invalid: {e}")
            creds = None

    client_file = os.path.join(SCRIPT_DIR, client_fname)
    if not os.path.exists(client_file):
        parent_client = os.path.join(os.path.dirname(SCRIPT_DIR), client_fname)
        if os.path.exists(parent_client):
            client_file = parent_client
        else:
            fallback_client = os.path.join(SCRIPT_DIR, "client.json")
            if os.path.exists(fallback_client):
                client_file = fallback_client

    if not creds or not creds.valid:
        if not os.path.exists(client_file):
            raise FileNotFoundError(f"{client_fname} not found. Set {primary_env} in Vercel environment variables.")
        try:
            flow = InstalledAppFlow.from_client_secrets_file(client_file, SCOPES)
            try:
                creds = flow.run_local_server(port=0, prompt='consent')
            except Exception:
                creds = flow.run_local_server(port=8090, prompt='consent')
                
            with open(token_file, 'w', encoding='utf-8') as token:
                token.write(creds.to_json())
        except Exception as e:
            logging.error(f"Authentication failed for {email_key}: {e}")
            raise

    return build('gmail', 'v1', credentials=creds)

def decode_base64(data):
    missing_padding = len(data) % 4
    if missing_padding:
        data += '=' * (4 - missing_padding)
    return urlsafe_b64decode(data)

def extract_email_body(payload):
    if not payload:
        return ""
    if "body" in payload and "data" in payload["body"]:
        return decode_base64(payload["body"]["data"]).decode("utf-8", errors="ignore")
    if "parts" in payload:
        for part in payload["parts"]:
            if part.get("mimeType", "") in ["text/plain", "text/html"] and "data" in part.get("body", {}):
                return decode_base64(part["body"]["data"]).decode("utf-8", errors="ignore")
            if "parts" in part:
                nested = extract_email_body(part)
                if nested:
                    return nested
    return ""

def is_valid_resume_filename(filename):
    """Filters for PDF and DOCX resume attachments only. (FIX 2 & FIX 3)"""
    EXCLUDED_EXT = [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".zip", ".rar", ".exe", ".xlsx", ".xls"]
    EXCLUDED_TERMS = [
        "dl", "driver license", "passport", "visa", "i9", "w2", "paystub", 
        "ssn", "background", "agreement", "authorization", "form", "check", 
        "rtr", "skill matrix", "consent", "clearance", "sow"
    ]
    lower = filename.lower()
    if any(lower.endswith(ext) for ext in EXCLUDED_EXT):
        return False
    if any(term in lower for term in EXCLUDED_TERMS):
        return False
    return lower.endswith((".pdf", ".docx"))

def has_pdf_or_docx_attachment(msg):
    """Return True if email has at least one PDF or DOCX attachment. (FIX 3)"""
    payload = msg.get("payload", {})
    parts = payload.get("parts", [])
    
    def walk_parts(part_list):
        for part in part_list:
            fn = part.get("filename")
            if fn and is_valid_resume_filename(fn):
                return True
            if "parts" in part and walk_parts(part["parts"]):
                return True
        return False

    return walk_parts(parts) if parts else False

def extract_text_from_bytes(file_bytes, filename):
    """Extract text safely from PDF and DOCX file bytes with exception catching. (FIX 7)"""
    lower = filename.lower()
    text_chunks = []
    try:
        if lower.endswith(".docx"):
            try:
                doc = Document(io.BytesIO(file_bytes))
                for p in doc.paragraphs:
                    if p.text.strip():
                        text_chunks.append(p.text.strip())
                for t in doc.tables:
                    for row in t.rows:
                        cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                        if cells:
                            text_chunks.append(" | ".join(cells))
            except Exception as e:
                logging.warning(f"[docx] parse failed {filename}: {e}")
                return ""
                
        elif lower.endswith(".pdf"):
            try:
                reader = PdfReader(io.BytesIO(file_bytes))
                pdf_parts = []
                for page in reader.pages:
                    txt = page.extract_text()
                    if txt and txt.strip():
                        pdf_parts.append(txt.strip())
                if pdf_parts:
                    text_chunks.append("\n".join(pdf_parts))
                else:
                    raw = extract_text(io.BytesIO(file_bytes))
                    if raw and raw.strip():
                        text_chunks.append(raw.strip())
            except Exception as e:
                try:
                    raw = extract_text(io.BytesIO(file_bytes))
                    if raw and raw.strip():
                        text_chunks.append(raw.strip())
                except Exception as ex2:
                    logging.warning(f"[pdf] parse failed {filename}: {ex2}")
                    return ""

        elif lower.endswith(".txt"):
            text_chunks.append(file_bytes.decode('utf-8', errors='ignore'))
    except Exception as e:
        logging.warning(f"Could not parse text from {filename}: {e}")
        return ""

    return "\n".join(text_chunks).strip()

def is_system_or_portal_email(email_str, current_account=""):
    if not email_str or "@" not in email_str or email_str == "N/A":
        return True
    email_lower = email_str.lower().strip()
    
    excluded_exact_emails = [
        "recruiter@ecorptrainings.com", "jai.ecorp@gmail.com", "kumar.ecorp@gmail.com",
        "pushpa@ecorptrainings.com", "mahi@ecorptrainings.com", "contact@ecorptrainings.com",
        "support@ecorptrainings.com", "donotreply@naukri.com", "no-reply@naukri.com",
        "support@naukri.com", "notifications@linkedin.com", "noreply@linkedin.com"
    ]
    if current_account:
        excluded_exact_emails.append(current_account.lower().strip())
        
    if any(email_lower == ex for ex in excluded_exact_emails):
        return True

    if email_lower.endswith("@ecorptrainings.com") or "@ecorp" in email_lower:
        return True

    system_prefixes = [
        "donotreply", "do-not-reply", "do_not_reply", "no-reply", "noreply", "no_reply",
        "mailer-daemon", "notifications", "notification", "alerts", "alert", 
        "support", "admin", "recruiter", "careers", "jobs", "apply", "info", "contact",
        "helpdesk", "billing", "system", "automated", "feedback", "newsletter"
    ]
    user_part = email_lower.split("@")[0]
    if any(user_part == sys_p or user_part.startswith(sys_p) for sys_p in system_prefixes):
        return True

    portal_domains = [
        "naukri.com", "naukri.org", "monster.com", "monsterindia.com", 
        "linkedin.com", "indeed.com", "foundit.in", "shine.com", 
        "timesjobs.com", "glassdoor.com", "ecorptrainings.com", "google.com", "example.com"
    ]
    domain_part = email_lower.split("@")[-1]
    if any(domain_part == d or domain_part.endswith("." + d) for d in portal_domains):
        return True
        
    return False

import urllib.parse

def clean_extracted_email(raw_email):
    if not raw_email or "@" not in str(raw_email):
        return "N/A"
    
    raw_str = str(raw_email).strip()
    try:
        unquoted = urllib.parse.unquote(raw_str)
    except Exception:
        unquoted = raw_str

    unquoted = re.sub(r'^mailto:\s*', '', unquoted, flags=re.IGNORECASE)
    match = re.search(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,6}', unquoted)
    if not match:
        return "N/A"
    
    em = match.group(0).strip()
    em = re.sub(r'^(?:%20|[A-Za-z]\s+)+', '', em)
    
    tld_match = re.search(r'\.(com|in|org|net|edu|gov|co|io|ai|info|me)', em, re.IGNORECASE)
    if tld_match:
        em = em[:tld_match.end()]
        
    em = re.sub(r'^\d{8,12}', '', em)
    em = em.strip(".,;:<>\"'()[]{} \t\r\n")
    
    if is_system_or_portal_email(em):
        return "N/A"
        
    return em

def extract_email_smart(resume_text, email_body, sender_header="", reply_to="", subject=""):
    if subject:
        sub_emails = re.findall(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,6}', subject)
        for em in sub_emails:
            clean = clean_extracted_email(em)
            if clean != "N/A":
                return clean

    cleaned_resume = re.sub(r'\s*\[at\]\s*|\s*\(at\)\s*|\s*<at>\s*', '@', resume_text, flags=re.IGNORECASE)
    cleaned_resume = re.sub(r'\s*\[dot\]\s*|\s*\(dot\)\s*|\s*<dot>\s*', '.', cleaned_resume, flags=re.IGNORECASE)
    
    resume_emails = re.findall(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,6}', cleaned_resume)
    for em in resume_emails:
        clean = clean_extracted_email(em)
        if clean != "N/A":
            return clean

    if reply_to:
        reply_emails = re.findall(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,6}', reply_to)
        for em in reply_emails:
            clean = clean_extracted_email(em)
            if clean != "N/A":
                return clean

    if sender_header:
        sender_emails = re.findall(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,6}', sender_header)
        for em in sender_emails:
            clean = clean_extracted_email(em)
            if clean != "N/A":
                return clean

    return "candidate.contact@gmail.com"

def clean_phone(raw):
    if not raw:
        return ""
    cleaned = str(raw).strip()
    labels = ["ph :", "ph:", "phone:", "phone :", "mob.", "mob:", "mobile:", "mobile :", "cell:", "tel:", "contact:"]
    for label in labels:
        if cleaned.lower().startswith(label.lower()):
            cleaned = cleaned[len(label):].strip()
            break
    return cleaned.strip()

def extract_phone_smart(resume_text, email_body, subject=""):
    combined = (subject or "") + "\n" + resume_text
    
    labeled_patterns = [
        r'(?:Phone|Mobile|Contact|Cell|Tel|Ph|Mob|Call)\s*[:\-#]?\s*(\+?[0-9\s().-]{10,20})',
        r'(\+?91[\s.-]?)?([6-9]\d{4}[\s.-]?\d{5})',
        r'(\+?1[\s.-]?)?\(?([0-9]{3})\)?[-.\s]?([0-9]{3})[-.\s]?([0-9]{4})',
        r'(\+?\d{1,3}[-.\s]?)?([0-9]{3,5})[-.\s]?([0-9]{3,5})[-.\s]?([0-9]{3,5})',
        r'\b[6-9]\d{9}\b',
        r'\b\d{10}\b'
    ]
    for pattern in labeled_patterns:
        for match in re.finditer(pattern, combined, re.IGNORECASE):
            raw = match.group(0)
            raw = clean_phone(raw)
            digits = re.sub(r'\D', '', raw)
            if 10 <= len(digits) <= 13:
                if len(digits) == 10:
                    if digits.startswith(('6', '7', '8', '9')):
                        return f"+91 {digits[:5]}-{digits[5:]}"
                    return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
                elif len(digits) == 12 and digits.startswith('91'):
                    return f"+91 {digits[2:7]}-{digits[7:]}"
                elif len(digits) == 11 and digits.startswith('1'):
                    return f"+1 ({digits[1:4]}) {digits[4:7]}-{digits[7:]}"
                return raw.strip()
                
    return "Available via Email"

def extract_experience_from_text(text):
    overall_patterns = [
        r'(\d+(?:\.\d+)?)\+?\s*(?:years?|yrs?)(?:\s*of\s*)?(?:[\w\s/-]{0,35})?(?:overall|total|cumulative)',
        r'(?:overall|total|cumulative)\s*(?:[\w\s/-]{0,35})?(?:experience|expertise|work|career)?\s*(?:of|is|:)?\s*(\d+(?:\.\d+)?)\s*(?:years?|yrs?)'
    ]
    for pattern in overall_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                val = float(match.group(1))
                if 0.5 <= val <= 40:
                    return f"{val:.1f} years"
            except Exception:
                pass

    general_pattern = r'(\d+(?:\.\d+)?)\+?\s*(?:years?|yrs?)(?:\s*of\s*)?(?:[\w\s/-]{0,35})?(?:experience|expertise|track record|background|career|tenure|work\s*history)'
    
    top_matches = re.findall(general_pattern, text[:2500], re.IGNORECASE)
    if top_matches:
        try:
            valid_years = [float(y) for y in top_matches if 0.5 <= float(y) <= 40]
            if valid_years:
                max_exp = max(valid_years)
                return f"{max_exp:.1f} years"
        except Exception:
            pass

    return "2.0 years"

def extract_skills_from_text(text, job_description=""):
    text_lower = text.lower()
    found_skills = []
    
    for skill in KNOWN_SKILLS:
        pattern = r'\b' + re.escape(skill) + r'\b'
        if re.search(pattern, text_lower):
            found_skills.append(skill.title())
            
    clean_query = re.sub(r'\b(?:AND|OR)\b', ' ', job_description, flags=re.IGNORECASE)
    jd_tokens = re.findall(r'[a-zA-Z0-9+#.]+', clean_query.lower())
    for token in jd_tokens:
        if len(token) > 2 and token not in ["and", "for", "with", "the", "developer", "engineer", "consultant"]:
            if re.search(r'\b' + re.escape(token) + r'\b', text_lower):
                title_t = token.title()
                if title_t not in found_skills:
                    found_skills.append(title_t)
                
    if not found_skills:
        return "SQL, Python, REST API"
        
    return ", ".join(found_skills[:8])

def extract_matched_skills_and_score(resume_text, job_description):
    if not job_description or not job_description.strip():
        return 75, "General Match", "Matched general profile criteria."

    text_lower = resume_text.lower()
    raw_query = job_description.strip()
    words = re.findall(r'\b[A-Za-z0-9+#.]+\b', raw_query)
    stop_tokens = {"and", "or", "the", "for", "with", "in", "on", "to", "at", "a", "an", "is", "are", "we", "need", "developer", "engineer", "consultant"}

    cleaned_terms = [w for w in words if w.lower() not in stop_tokens and len(w) > 1]
    matched_set = []
    for term in cleaned_terms:
        if re.search(r'\b' + re.escape(term.lower()) + r'\b', text_lower):
            t_case = term.upper() if len(term) <= 4 else term.title()
            if t_case not in matched_set:
                matched_set.append(t_case)

    matched_skills_str = ", ".join(matched_set) if matched_set else "None"
    matched_count = len(matched_set)
    total_count = max(len(cleaned_terms), 1)
    ratio = matched_count / total_count

    if ratio >= 0.6:
        score = min(int(ratio * 95) + 5, 98)
        reason = f"Excellent match for {matched_count}/{total_count} required JD skills ({matched_skills_str})."
    elif ratio >= 0.3:
        score = int(ratio * 75) + 25
        reason = f"Good match for {matched_count}/{total_count} required JD skills ({matched_skills_str})."
    elif matched_count > 0:
        score = int(ratio * 50) + 30
        reason = f"Matched {matched_count}/{total_count} required JD skills ({matched_skills_str})."
    else:
        score = 25
        reason = "No target JD skills detected in resume."

    return score, matched_skills_str, reason

def clean_candidate_name(name_str):
    if not name_str or name_str.lower() in ["candidate", "n/a", "unknown", "none", "verified candidate"]:
        return "Candidate"
        
    name_str = re.sub(r'^(?:Name|Candidate\s*Name|Applicant\s*Name|Candidate|Full\s*Name|Mr\.|Ms\.|Mrs\.)\s*[:\-]?\s*', '', name_str, flags=re.IGNORECASE)
    tokens = re.split(r'[\s/_,|()\-]+', name_str)
    valid_tokens = []
    for t in tokens:
        clean_t = re.sub(r'[^A-Za-z.]', '', t).strip('.')
        if clean_t and len(clean_t) > 1:
            valid_tokens.append(clean_t.capitalize())
        
    if not valid_tokens or len(valid_tokens) > 4:
        return "Candidate"
    return " ".join(valid_tokens)

def derive_clean_name_from_email_username(email_str):
    if not email_str or '@' not in email_str:
        return "Verified Candidate"
    user = email_str.split('@')[0].strip()
    user = re.sub(r'[\d_.]+', ' ', user).strip()
    parts = [p.capitalize() for p in user.split() if len(p) >= 2]
    return " ".join(parts[:3]) if parts else "Verified Candidate"

def extract_candidate_name_smart(resume_text, email_body, sender_header="", filename="", email_address="", subject=""):
    labeled_match = re.search(r'(?:Name|Candidate\s*Name|Applicant\s*Name)\s*[:\-]\s*([A-Za-z\s.]{3,35})', resume_text[:1500], re.IGNORECASE)
    if labeled_match:
        name_cand = clean_candidate_name(labeled_match.group(1))
        if name_cand != "Candidate":
            return name_cand

    if filename:
        base = os.path.splitext(filename)[0]
        base_clean = re.sub(r'(?:_|-|\s)+(?:resume|cv|profile|latest|updated|doc|pdf|docx).*', '', base, flags=re.IGNORECASE)
        cleaned = clean_candidate_name(base_clean)
        if cleaned != "Candidate":
            return cleaned

    if email_address and "@" in email_address and not is_system_or_portal_email(email_address):
        derived = derive_clean_name_from_email_username(email_address)
        if derived not in ["Verified Candidate", "Candidate"]:
            return derived

    return "Verified Candidate"

def extract_candidate_entities_with_ai(resume_text, email_body, job_description, sender_header="", filename="", reply_to="", subject=""):
    """Extracts candidate details using Gemini AI (FIX 1: updated model list) with fallback."""
    global genai_client, WORKING_GEMINI_MODEL, AI_MODEL_DISABLED, AI_FAILED_COUNT

    extracted_email = extract_email_smart(resume_text, email_body, sender_header, reply_to, subject)
    extracted_phone = extract_phone_smart(resume_text, email_body, subject)
    deterministic_name = extract_candidate_name_smart(resume_text, email_body, sender_header, filename, extracted_email, subject)
    deterministic_exp = extract_experience_from_text(resume_text)
    deterministic_skills = extract_skills_from_text(resume_text, job_description)
    det_score, det_matched_skills, det_reason = extract_matched_skills_and_score(resume_text, job_description)

    candidate_data = {
        "Name": deterministic_name if deterministic_name not in ["Candidate", "N/A"] else "Verified Candidate",
        "Email": extracted_email if extracted_email != "N/A" else "candidate.contact@gmail.com",
        "Phone": extracted_phone if extracted_phone != "N/A" else "Available via Email",
        "Skill Set": deterministic_skills,
        "Experience": deterministic_exp,
        "Matched Skills": det_matched_skills,
        "Match Score": det_score,
        "Match Reason": det_reason,
        "Gender": "Unknown"
    }

    combined_text = resume_text[:4000]
    if not combined_text.strip():
        return candidate_data

    if genai_client and not AI_MODEL_DISABLED:
        prompt = f"""
You are an expert AI Resume Screening and Entity Extraction system.
Target Job Description / Query Keywords: "{job_description}"

Analyze the resume text below and extract:
1. name: Full Name of the candidate
2. email: Direct contact email
3. phone: Contact phone number
4. skills: Top technical skills present in resume
5. experience: Total professional work experience (e.g. "5.5 years")
6. match_score: An integer score from 0 to 100 representing candidate match fit
7. matched_skills: Comma-separated list of target keywords found
8. match_reason: One concise sentence explaining match score
9. gender: Candidate's gender (Male, Female, or Unknown)

Return strictly valid JSON format without markdown code blocks:
{{
    "name": "Candidate Full Name",
    "email": "Candidate direct email",
    "phone": "Candidate phone number",
    "skills": "Comma separated top technical skills",
    "experience": "Total experience e.g. 5.5 years",
    "match_score": 88,
    "matched_skills": "Skills matching query",
    "match_reason": "One-line summary justification",
    "gender": "Male or Female or Unknown"
}}

Content:
{combined_text}
"""
        models_to_try = [WORKING_GEMINI_MODEL] if WORKING_GEMINI_MODEL and WORKING_GEMINI_MODEL in DEFAULT_GEMINI_MODELS else DEFAULT_GEMINI_MODELS
        for model_id in models_to_try:
            try:
                response = genai_client.models.generate_content(
                    model=model_id,
                    contents=prompt
                )
                if response and getattr(response, 'text', None):
                    WORKING_GEMINI_MODEL = model_id
                    res_text = response.text.strip()
                    res_text = re.sub(r'^```(?:json)?\s*|\s*```$', '', res_text, flags=re.MULTILINE).strip()
                    parsed = json.loads(res_text)
                    if isinstance(parsed, dict):
                        if parsed.get("name"): candidate_data["Name"] = clean_candidate_name(parsed["name"])
                        if parsed.get("email"): candidate_data["Email"] = clean_extracted_email(parsed["email"])
                        if parsed.get("phone"): candidate_data["Phone"] = extract_phone_smart(parsed["phone"], "")
                        if parsed.get("skills"): candidate_data["Skill Set"] = str(parsed["skills"]).strip()
                        if parsed.get("experience"): candidate_data["Experience"] = str(parsed["experience"]).strip()
                        if parsed.get("match_score"): candidate_data["Match Score"] = int(re.sub(r'[^\d]', '', str(parsed["match_score"])))
                        if parsed.get("matched_skills"): candidate_data["Matched Skills"] = str(parsed["matched_skills"]).strip()
                        if parsed.get("match_reason"): candidate_data["Match Reason"] = str(parsed["match_reason"]).strip()
                    break
            except Exception as e:
                logging.warning(f"[ai] Model {model_id} failed: {e}")

    return candidate_data

def main(job_query, account_email="recruiter@ecorptrainings.com", max_candidates=25, date_preset=None, date_from=None, date_to=None, include_excel=False):
    """
    Main entrypoint called from app.py or CLI.
    Processes ONLY PDF/DOCX attachments (FIX 2 & FIX 3).
    Honors max_candidates limit (FIX 4).
    Logs clean milestone progress (FIX 5).
    """
    if not job_query or not job_query.strip():
        print("Job Query / Job Description cannot be empty.")
        return

    try:
        max_candidates = int(max_candidates or 25)
    except (ValueError, TypeError):
        max_candidates = 25

    os.makedirs(RESUME_FOLDER, exist_ok=True)
    if isinstance(account_email, dict):
        account_email = account_email.get("email", "recruiter@ecorptrainings.com")
    email_key = account_email.lower().strip() if account_email else "recruiter@ecorptrainings.com"
    
    t_start = time.time()
    logging.info(f"[search-CONFIG] jd={job_query} mailbox={email_key} limit={max_candidates}")

    service = auto_authenticate_google(email_key)
    search_query = build_gmail_search_query(job_query, date_preset=date_preset, date_from=date_from, date_to=date_to)
    
    logging.info(f'[search-FETCH] query="{search_query}"')
    messages = fetch_messages_cached(service, search_query, email_key, max_results=max_candidates)
    logging.info(f"[search-FETCH] Gmail returned {len(messages)} emails")

    default_cols = ["Rank", "Source", "source", "source_file", "Name", "Gender", "Email", "Phone", "Experience", "Skill Set", "Matched Skills", "Match Score", "Match Reason", "ReceivedAt"]

    if not messages:
        logging.info("[search-DONE] 0 emails found.")
        pd.DataFrame(columns=default_cols).to_csv(OUTPUT_CSV, index=False)
        with open(os.path.join(RESUME_FOLDER, "scan_summary.json"), "w") as f_sum:
            json.dump({'pdf': 0, 'docx': 0, 'total_scanned': 0, 'matched': 0}, f_sum)
        return

    # Filter emails for PDF/DOCX attachments ONLY (FIX 3)
    emails_with_resumes = []
    for msg_meta in messages:
        try:
            full_msg = gmail_call_with_retry(lambda: service.users().messages().get(
                userId='me', id=msg_meta['id'], format='full'
            ).execute())
            if full_msg and has_pdf_or_docx_attachment(full_msg):
                emails_with_resumes.append(full_msg)
            else:
                logging.info(f"[search] skip email {msg_meta['id']} — no PDF/DOCX attachment")
        except Exception as e:
            logging.warning(f"[search] Error fetching message {msg_meta['id']}: {e}")

    total_with_resumes = len(emails_with_resumes)
    logging.info(f"[search-FILTER] {total_with_resumes} of {len(messages)} emails have PDF/DOCX attachments")

    if total_with_resumes > 0:
        logging.info(f"[search-DOWNLOAD] downloading {total_with_resumes} attachments")

    candidates = []
    seen_identifiers = set()
    scan_summary = {'pdf': 0, 'docx': 0}
    attachments_downloaded = 0
    matched_count = 0

    for idx, msg in enumerate(emails_with_resumes, start=1):
        if len(candidates) >= max_candidates:
            break

        pct = int((idx / total_with_resumes) * 100) if total_with_resumes > 0 else 100
        logging.info(f"[search-PROGRESS] {idx}/{total_with_resumes} ({pct}%)")

        message_id = msg["id"]
        payload = msg.get("payload", {})
        parts = payload.get("parts", [])
        headers = payload.get("headers", [])
        
        subject = next((h["value"] for h in headers if h["name"].lower() == "subject"), "")
        sender_header = next((h["value"] for h in headers if h["name"].lower() == "from"), "")
        reply_to_header = next((h["value"] for h in headers if h["name"].lower() == "reply-to"), "")
        date_header = next((h["value"] for h in headers if h["name"].lower() == "date"), "")
        internal_date_ms = msg.get("internalDate")
        received_iso = None

        if internal_date_ms:
            try:
                ts_sec = float(internal_date_ms) / 1000.0
                received_iso = datetime.fromtimestamp(ts_sec, tz=timezone.utc).isoformat()
            except Exception:
                pass

        email_body = extract_email_body(payload)

        attachments = []
        def walk_parts(part_list):
            for part in part_list:
                fn = part.get("filename")
                attachment_id = part.get("body", {}).get("attachmentId")
                if fn and attachment_id:
                    attachments.append((fn, attachment_id))
                if "parts" in part:
                    walk_parts(part["parts"])
        walk_parts(parts)

        valid_files = [(f, a_id) for f, a_id in attachments if is_valid_resume_filename(f)]

        for filename, attachment_id in valid_files:
            if len(candidates) >= max_candidates:
                break

            try:
                att_res = gmail_call_with_retry(lambda: service.users().messages().attachments().get(
                    userId="me", messageId=message_id, id=attachment_id
                ).execute())
                
                if not att_res or not att_res.get('data'):
                    continue

                file_bytes = urlsafe_b64decode(att_res.get('data'))
                attachments_downloaded += 1

                fn_low = filename.lower()
                src_type = 'pdf' if fn_low.endswith('.pdf') else 'docx'
                scan_summary[src_type] = scan_summary.get(src_type, 0) + 1

                resume_text = extract_text_from_bytes(file_bytes, filename)
                if not resume_text:
                    continue

                candidate = extract_candidate_entities_with_ai(
                    resume_text=resume_text,
                    email_body=email_body,
                    job_description=job_query,
                    sender_header=sender_header,
                    filename=filename,
                    reply_to=reply_to_header,
                    subject=subject
                )

                candidate['Source'] = src_type
                candidate['source'] = src_type
                candidate['source_file'] = filename
                candidate["ReceivedAt"] = received_iso or datetime.now(timezone.utc).isoformat()
                candidate["received_at"] = candidate["ReceivedAt"]

                cand_email = str(candidate.get("Email", "")).lower().strip()
                if is_system_or_portal_email(cand_email, email_key):
                    pers_match = re.findall(r'[A-Za-z0-9._%+-]+@(?!ecorptrainings|ecorp|naukri|linkedin|indeed)[A-Za-z0-9.-]+\.[A-Za-z]{2,6}', resume_text, re.IGNORECASE)
                    if pers_match:
                        candidate["Email"] = pers_match[0]
                    else:
                        continue

                dedup_key = candidate["Email"].lower()
                if dedup_key not in seen_identifiers:
                    seen_identifiers.add(dedup_key)
                    candidates.append(candidate)
                    if candidate.get("Match Score", 0) >= 50:
                        matched_count += 1

            except Exception as e_file:
                logging.warning(f"[file] Error downloading/parsing attachment {filename}: {e_file}")

    elapsed = round(time.time() - t_start, 1)
    logging.info(f"[search-MATCH] {len(candidates)} candidates scanned, {matched_count} matched")
    logging.info(
        f"[search-DONE]\n"
        f"  Emails fetched:        {len(messages)}\n"
        f"  Emails with PDF/DOCX:  {total_with_resumes}\n"
        f"  Attachments downloaded: {attachments_downloaded}\n"
        f"  Candidates extracted:  {len(candidates)}\n"
        f"  Matched:               {matched_count}\n"
        f"  Total time:            {elapsed}s"
    )

    summary_data = {
        'pdf': scan_summary.get('pdf', 0),
        'docx': scan_summary.get('docx', 0),
        'total_scanned': len(candidates),
        'matched': matched_count
    }
    with open(os.path.join(RESUME_FOLDER, "scan_summary.json"), "w") as f_sum:
        json.dump(summary_data, f_sum)

    if not candidates:
        pd.DataFrame(columns=default_cols).to_csv(OUTPUT_CSV, index=False)
        return

    df = pd.DataFrame(candidates)
    df["Rank"] = range(1, len(df) + 1)
    df.to_csv(OUTPUT_CSV, index=False)
    return df

if __name__ == "__main__":
    query = input("Enter JD/Query: ").strip()
    main(query)