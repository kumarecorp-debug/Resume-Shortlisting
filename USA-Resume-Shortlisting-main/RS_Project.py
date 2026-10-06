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
import threading
import uuid
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
    import ai_extractor
except ImportError:
    from . import ai_extractor

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
logger = logging.getLogger(__name__)

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

# Exponential Backoff Helper for Gmail API (FIX 3)
def gmail_call_with_backoff(func, max_retries=5):
    delays = [5, 15, 30, 60, 90]
    for attempt, delay in enumerate(delays):
        try:
            return func()
        except Exception as e:
            err_str = str(e).lower()
            if any(term in err_str for term in ["ratelimitexceeded", "403", "429", "quotaexceeded"]):
                logger.warning(
                    f"[gmail] rate limited, waiting {delay}s "
                    f"(attempt {attempt+1}/{max_retries})"
                )
                time.sleep(delay)
            else:
                raise e
    raise RuntimeError("gmail rate limit exceeded after retries")

gmail_call_with_retry = gmail_call_with_backoff

# Cached Gmail Messages Listing
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
                    logger.info(f"Successfully authenticated {email_key} via {env_k}")
                    return build('gmail', 'v1', credentials=creds)
            except Exception as e:
                logger.warning(f"Failed to load token from environment variable {env_k}: {e}")
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
            logger.warning(f"Existing token file for {email_key} invalid: {e}")
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
            logger.error(f"Authentication failed for {email_key}: {e}")
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
    """Filters for PDF and DOCX resume attachments only."""
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
    """Return True if email has at least one PDF or DOCX attachment."""
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
    """Extract text safely from PDF and DOCX file bytes with exception catching."""
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
                logger.warning(f"[docx] parse failed {filename}: {e}")
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
                    logger.warning(f"[pdf] parse failed {filename}: {ex2}")
                    return ""

        elif lower.endswith(".txt"):
            text_chunks.append(file_bytes.decode('utf-8', errors='ignore'))
    except Exception as e:
        logger.warning(f"Could not parse text from {filename}: {e}")
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

BAD_NAMES = {
    'curriculum vitae', 'resume', 'cv', 'new', 'final',
    'updated', 'latest', 'years automation testing',
    'candidate', 'unknown', 'n/a', 'na'
}

def is_valid_name(name):
    if not name: return False
    n = str(name).lower().strip()
    if n in BAD_NAMES: return False
    if len(n) < 3: return False
    if n.replace(' ', '').isdigit(): return False
    return True

def normalize_name(name):
    if not name: return ''
    n = str(name).lower().strip()
    n = re.sub(r'\s+', ' ', n)
    n = re.sub(r'\b(mr|mrs|ms|dr|prof)\.?\s+', '', n)
    return n

def dedupe_by_name(candidates):
    seen = {}
    result = []
    for c in candidates:
        name_val = c.get('Name') or c.get('name') or ''
        key = normalize_name(name_val)
        if not key:
            result.append(c)
            continue
        score_c = float(str(c.get('Match Score', c.get('match_score', 0))).replace('%', '') or 0)
        if key in seen:
            existing = seen[key]
            score_ex = float(str(existing.get('Match Score', existing.get('match_score', 0))).replace('%', '') or 0)
            if score_c > score_ex:
                if existing in result:
                    result.remove(existing)
                result.append(c)
                seen[key] = c
            else:
                logger.info(f'[search-DEDUP] removed dup: {name_val}')
        else:
            seen[key] = c
            result.append(c)
    return result

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
    """Extracts candidate details using Groq (primary) via ai_extractor with SHA256 caching and Gemini fallback."""
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

    combined_text = resume_text if len(resume_text) > 50 else (resume_text + "\n" + email_body)
    if not combined_text.strip():
        return candidate_data

    # Groq Primary Extraction via ai_extractor module
    try:
        ai_fields = ai_extractor.extract_fields_cached(combined_text)
        if ai_fields and isinstance(ai_fields, dict):
            if ai_fields.get("name"):
                c_name = clean_candidate_name(str(ai_fields["name"]).strip())
                if c_name != "Candidate":
                    candidate_data["Name"] = c_name
            if ai_fields.get("email") and "@" in str(ai_fields["email"]):
                c_email = clean_extracted_email(str(ai_fields["email"]).strip())
                if c_email != "N/A":
                    candidate_data["Email"] = c_email
            if ai_fields.get("phone") and str(ai_fields["phone"]).strip():
                c_phone = clean_phone(str(ai_fields["phone"]).strip())
                if c_phone:
                    candidate_data["Phone"] = c_phone
            if ai_fields.get("skills") and str(ai_fields["skills"]).strip():
                candidate_data["Skill Set"] = str(ai_fields["skills"]).strip()
            if ai_fields.get("experience") and str(ai_fields["experience"]).strip():
                exp_val = str(ai_fields["experience"]).strip()
                exp_parsed = extract_experience_from_text(exp_val)
                candidate_data["Experience"] = exp_parsed if exp_parsed != "2.0 years" else f"{exp_val} years"
            if ai_fields.get("gender") and str(ai_fields["gender"]).lower() != "unknown":
                candidate_data["Gender"] = str(ai_fields["gender"]).strip().capitalize()
    except Exception as ex:
        logger.warning(f"[ai] Extraction note: {ex}")

    return candidate_data

def main(job_query, account_email="recruiter@ecorptrainings.com", max_candidates=25, date_preset=None, date_from=None, date_to=None, include_excel=False):
    """
    Main entrypoint called from app.py or CLI.
    Processes ONLY PDF/DOCX attachments.
    Honors max_candidates limit strictly.
    Uses Groq for ultra-fast candidate entity extraction with gentle sequential delays.
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
class SearchProgress:
    def __init__(self, target, search_id=""):
        self.target = max(target, 1)
        self.emails_scanned = 0
        self.resumes_found = 0
        self.current = 0
        self.lock = threading.Lock()
        self.status = "downloading"  # downloading | extracting | done | error
        self.search_id = search_id
        self.t_start = time.time()

    def set_stats(self, emails_scanned=None, resumes_found=None, status=None):
        with self.lock:
            if emails_scanned is not None:
                self.emails_scanned = emails_scanned
            if resumes_found is not None:
                self.resumes_found = resumes_found
            if status is not None:
                self.status = status

    def increment(self, step=1):
        with self.lock:
            self.current = min(self.current + step, self.target)
            pct = int((self.current / self.target) * 100)
            logger.info(f"[search-PROGRESS] {self.current}/{self.target} ({pct}%)")

    def done(self):
        with self.lock:
            self.current = self.target
            self.status = "done"

_searches = {}
_attachment_cache = {}
_search_cache = {}

MAX_EMAILS_TO_SCAN = 500
MAX_ATTACHMENTS_TO_DOWNLOAD = 200

if os.environ.get("VERCEL"):
    MAX_ATTACHMENTS_TO_DOWNLOAD = 50

_search_lock = threading.Lock()
_downloaded_messages = set()
ATTACHMENT_DOWNLOAD_DELAY = 0.1  # 100ms delay between download requests (10/sec safe rate)

def download_attachment_cached(service, message_id, attachment_id):
    cache_key = f"{message_id}:{attachment_id}"
    if cache_key in _attachment_cache:
        logger.info(f"[attachment] cache hit for message {message_id}")
        return _attachment_cache[cache_key]

    time.sleep(ATTACHMENT_DOWNLOAD_DELAY)
    logger.info(f"[gmail-API] attachment.get message_id={message_id} attachment_id={attachment_id} time={time.time()}")

    def _call():
        return service.users().messages().attachments().get(
            userId="me", messageId=message_id, id=attachment_id
        ).execute()

    att_res = gmail_call_with_backoff(_call)

    if att_res and att_res.get('data'):
        file_bytes = urlsafe_b64decode(att_res.get('data'))
        _attachment_cache[cache_key] = file_bytes
        return file_bytes
    return None

def search_gmail_until_target(mailbox=None, jd=None, target_attachments=50, batch_size=50, max_emails=500, service=None, query=None, email_key=None, search_id=None):
    """
    Fetch Gmail emails in batches until target_attachments resume files are downloaded.
    Deduplicates attachments by content hash and logs search progress.
    """
    if email_key is None:
        email_key = mailbox if mailbox else "recruiter@ecorptrainings.com"
    if service is None:
        service = auto_authenticate_google(email_key)
    if query is None:
        if jd:
            GMAIL_ATTACHMENT_FILTER = "(filename:pdf OR filename:docx OR filename:xlsx OR filename:xls)"
            query = f"has:attachment {GMAIL_ATTACHMENT_FILTER} {jd}"
        else:
            query = "has:attachment"

    # Search caching disabled (FIX 3) to prevent serving stale results
    target_attachments = min(int(target_attachments or 50), MAX_ATTACHMENTS_TO_DOWNLOAD if 'MAX_ATTACHMENTS_TO_DOWNLOAD' in globals() else 200)
    downloaded_files = []
    seen_hashes = set()
    page_token = None
    emails_scanned = 0
    iteration = 0
    max_iterations = max(1, max_emails // batch_size)

    progress = _searches.get(search_id) if search_id and '_searches' in globals() else None

    while len(downloaded_files) < target_attachments and iteration < max_iterations:
        iteration += 1
        logger.info(
            f"[search-LOOP] iteration {iteration}: "
            f"scanned={emails_scanned} attached={len(downloaded_files)} "
            f"target={target_attachments}"
        )

        try:
            kwargs = {'userId': 'me', 'q': query, 'maxResults': batch_size}
            if page_token:
                kwargs['pageToken'] = page_token
            res = gmail_call_with_retry(lambda: service.users().messages().list(**kwargs).execute())
        except Exception as e:
            logger.warning(f"[search-LOOP] Gmail error: {e}, retrying in 3s")
            time.sleep(3)
            continue

        messages = res.get('messages', [])
        if not messages:
            logger.info("[search-LOOP] no more emails")
            break

        for msg_meta in messages:
            msg_id = msg_meta['id']
            if msg_id in _downloaded_messages:
                logger.info(f"[search-DOWNLOAD] message {msg_id} already processed, skipping")
                continue
            _downloaded_messages.add(msg_id)

            emails_scanned += 1
            if progress:
                progress.set_stats(emails_scanned=emails_scanned, resumes_found=len(downloaded_files), status="downloading")

            if len(downloaded_files) >= target_attachments:
                break

            try:
                time.sleep(ATTACHMENT_DOWNLOAD_DELAY)
                logger.info(f"[gmail-API] message.get message_id={msg_id} time={time.time()}")
                full_msg = gmail_call_with_backoff(lambda: service.users().messages().get(
                    userId='me', id=msg_id, format='full'
                ).execute())
                if not full_msg or not has_pdf_or_docx_attachment(full_msg):
                    continue

                payload = full_msg.get("payload", {})
                parts = payload.get("parts", [])
                headers = payload.get("headers", [])
                subject = next((h["value"] for h in headers if h["name"].lower() == "subject"), "")
                sender_header = next((h["value"] for h in headers if h["name"].lower() == "from"), "")
                reply_to_header = next((h["value"] for h in headers if h["name"].lower() == "reply-to"), "")
                internal_date_ms = full_msg.get("internalDate")

                attachments = []
                def walk_parts(part_list):
                    for part in part_list:
                        fn = part.get("filename")
                        att_id = part.get("body", {}).get("attachmentId")
                        if fn and att_id:
                            attachments.append((fn, att_id))
                        if "parts" in part:
                            walk_parts(part["parts"])
                walk_parts(parts)

                valid_files = [(f, a_id) for f, a_id in attachments if is_valid_resume_filename(f)]
                for filename, attachment_id in valid_files:
                    if len(downloaded_files) >= target_attachments:
                        break
                    file_bytes = download_attachment_cached(service, msg_meta['id'], attachment_id)
                    if not file_bytes:
                        continue

                    # Dedupe by content hash
                    content_hash = hashlib.md5(file_bytes[:4096]).hexdigest()
                    if content_hash in seen_hashes:
                        logger.info(f"[search] duplicate attachment skipped for {filename}")
                        continue
                    seen_hashes.add(content_hash)

                    downloaded_files.append({
                        'filename': filename,
                        'file_bytes': file_bytes,
                        'message_id': msg_meta['id'],
                        'payload': payload,
                        'headers': headers,
                        'subject': subject,
                        'sender_header': sender_header,
                        'reply_to_header': reply_to_header,
                        'internal_date_ms': internal_date_ms
                    })
                    if progress:
                        progress.set_stats(resumes_found=len(downloaded_files))
                    logger.info(f"[search-DOWNLOAD] {len(downloaded_files)}/{target_attachments} attachments")

            except Exception as e_item:
                logger.warning(f"[search-LOOP] download failed: {e_item}")

            time.sleep(0.05)

        if len(downloaded_files) >= target_attachments:
            logger.info(f"[search-LOOP] TARGET REACHED: {len(downloaded_files)} files")
            break

        page_token = res.get('nextPageToken')
        if not page_token:
            logger.info("[search-LOOP] no more pages")
            break

    logger.info(f"[search-LOOP-DONE] scanned={emails_scanned} attachments={len(downloaded_files)}")
    return downloaded_files

def search_until_relevant(mailbox="recruiter@ecorptrainings.com", jd="", target_relevant=25,
                           score_threshold=40, batch_size=50,
                           max_emails=1000, progress_callback=None):
    """
    Loop Gmail search until target_relevant candidates meeting score_threshold are collected.
    """
    if isinstance(mailbox, dict):
        email_key = mailbox.get("email", "recruiter@ecorptrainings.com")
    else:
        email_key = str(mailbox).lower().strip() if mailbox else "recruiter@ecorptrainings.com"

    try:
        target_relevant = int(target_relevant or 25)
    except Exception:
        target_relevant = 25

    try:
        score_threshold = float(score_threshold or 40)
    except Exception:
        score_threshold = 40.0

    service = auto_authenticate_google(email_key)
    query = build_gmail_search_query(jd)

    relevant = []
    seen_emails = set()
    seen_hashes = set()
    page_token = None
    emails_scanned = 0
    iteration = 0
    max_iterations = max(1, max_emails // batch_size)

    while len(relevant) < target_relevant and iteration < max_iterations:
        iteration += 1
        logger.info(f'[search-LOOP] iter {iteration}: emails={emails_scanned} relevant={len(relevant)}/{target_relevant}')

        try:
            kwargs = {'userId': 'me', 'q': query, 'maxResults': batch_size}
            if page_token:
                kwargs['pageToken'] = page_token
            res = gmail_call_with_retry(lambda: service.users().messages().list(**kwargs).execute())
        except Exception as e:
            if 'rateLimitExceeded' in str(e):
                logger.warning('[gmail] rate limited, waiting 10s')
                time.sleep(10)
                continue
            logger.warning(f'[search-LOOP] list error: {e}')
            break

        messages = res.get('messages', [])
        if not messages:
            logger.info('[search-LOOP] no more emails')
            break

        for msg_meta in messages:
            if len(relevant) >= target_relevant:
                break

            msg_id = msg_meta['id']
            if msg_id in seen_emails:
                continue
            seen_emails.add(msg_id)
            emails_scanned += 1

            try:
                time.sleep(ATTACHMENT_DOWNLOAD_DELAY)
                full_msg = gmail_call_with_backoff(lambda: service.users().messages().get(
                    userId='me', id=msg_id, format='full'
                ).execute())
                if not full_msg or not has_pdf_or_docx_attachment(full_msg):
                    continue

                payload = full_msg.get("payload", {})
                parts = payload.get("parts", [])
                headers = payload.get("headers", [])
                subject = next((h["value"] for h in headers if h["name"].lower() == "subject"), "")
                sender_header = next((h["value"] for h in headers if h["name"].lower() == "from"), "")
                reply_to_header = next((h["value"] for h in headers if h["name"].lower() == "reply-to"), "")

                attachments = []
                def walk_parts(part_list):
                    for part in part_list:
                        fn = part.get("filename")
                        att_id = part.get("body", {}).get("attachmentId")
                        if fn and att_id:
                            attachments.append((fn, att_id))
                        if "parts" in part:
                            walk_parts(part["parts"])
                walk_parts(parts)

                valid_files = [(f, a_id) for f, a_id in attachments if is_valid_resume_filename(f)]
                for filename, attachment_id in valid_files:
                    if len(relevant) >= target_relevant:
                        break

                    file_bytes = download_attachment_cached(service, msg_id, attachment_id)
                    if not file_bytes:
                        continue

                    h = hashlib.md5(file_bytes[:4096]).hexdigest()
                    if h in seen_hashes:
                        continue
                    seen_hashes.add(h)

                    txt = extract_text_from_bytes(file_bytes, filename)
                    if not txt:
                        continue

                    ai_results = ai_extractor.extract_batch([txt], jd)
                    ai_data = ai_results[0] if ai_results and isinstance(ai_results[0], dict) else {}

                    email_body = extract_email_body(payload)
                    extracted_email = extract_email_smart(txt, email_body, sender_header, reply_to_header, subject)
                    extracted_phone = extract_phone_smart(txt, email_body, subject)
                    deterministic_name = extract_candidate_name_smart(txt, email_body, sender_header, filename, extracted_email, subject)
                    deterministic_exp = extract_experience_from_text(txt)
                    deterministic_skills = extract_skills_from_text(txt, jd)
                    det_score, det_matched_skills, det_reason = extract_matched_skills_and_score(txt, jd)

                    cand_name = ai_data.get("name") or deterministic_name
                    if not is_valid_name(cand_name):
                        cand_name = extracted_email.split('@')[0] if '@' in extracted_email else 'Unknown'

                    cand_email = clean_extracted_email(ai_data.get("email")) if ai_data.get("email") else extracted_email
                    if cand_email == "N/A":
                        cand_email = extracted_email if extracted_email != "N/A" else "candidate.contact@gmail.com"

                    cand_phone = clean_phone(ai_data.get("phone")) if ai_data.get("phone") else extracted_phone
                    if not cand_phone:
                        cand_phone = extracted_phone if extracted_phone != "N/A" else "Available via Email"

                    cand_skills = ai_data.get("skills") or deterministic_skills
                    if isinstance(cand_skills, list):
                        cand_skills = ", ".join(str(s) for s in cand_skills)

                    cand_exp = ai_data.get("experience") or deterministic_exp
                    raw_score = ai_data.get("match_score") if ai_data.get("match_score") is not None else det_score
                    try:
                        cand_score = float(str(raw_score).replace('%', '') or det_score)
                    except Exception:
                        cand_score = float(det_score)

                    cand_matched_skills = ai_data.get("matched_skills") or det_matched_skills
                    cand_reason = ai_data.get("match_reason") or det_reason
                    cand_gender = ai_data.get("gender") or "Unknown"

                    candidate = {
                        "name": cand_name,
                        "Name": cand_name,
                        "email": cand_email,
                        "Email": cand_email,
                        "phone": cand_phone,
                        "Phone": cand_phone,
                        "skills": str(cand_skills),
                        "Skill Set": str(cand_skills),
                        "experience": str(cand_exp),
                        "Experience": str(cand_exp),
                        "matched_skills": str(cand_matched_skills),
                        "Matched Skills": str(cand_matched_skills),
                        "match_score": int(cand_score),
                        "Match Score": int(cand_score),
                        "match_reason": str(cand_reason),
                        "Match Reason": str(cand_reason),
                        "gender": str(cand_gender).capitalize(),
                        "Gender": str(cand_gender).capitalize(),
                        "source": 'pdf' if filename.lower().endswith('.pdf') else 'docx',
                        "Source": 'pdf' if filename.lower().endswith('.pdf') else 'docx',
                        "source_file": filename,
                        "ReceivedAt": datetime.now(timezone.utc).isoformat()
                    }

                    if cand_score >= score_threshold:
                        relevant.append(candidate)
                        logger.info(f'[search-LOOP] ✓ kept #{len(relevant)}: {cand_name} ({cand_score})')

                    if progress_callback:
                        try:
                            progress_callback(len(relevant), target_relevant)
                        except Exception:
                            pass
            except Exception as e_msg:
                logger.warning(f'[search-LOOP] message item error: {e_msg}')

        page_token = res.get('nextPageToken')
        if not page_token:
            logger.info('[search-LOOP] no more pages')
            break

    relevant = dedupe_by_name(relevant)
    meta = {
        'target': target_relevant,
        'found': len(relevant),
        'shortage': max(0, target_relevant - len(relevant)),
        'emails_scanned': emails_scanned,
        'jd': jd,
        'mailbox': email_key
    }
    logger.info(f'[search-DONE] {meta}')
    return relevant, meta

def main(job_query, account_email="recruiter@ecorptrainings.com", max_candidates=25, date_preset=None, date_from=None, date_to=None, include_excel=False, search_id=None, fast_mode=False):
    """
    Main entrypoint called from app.py or CLI.
    Fetches Gmail emails until max_candidates target attachments are downloaded.
    Extracts candidates via Groq with progress tracking.
    """
    if not _search_lock.acquire(blocking=False):
        logger.warning("[search] already running, skipping duplicate search request")
        return pd.DataFrame()

    try:
        return _do_main(job_query, account_email=account_email, max_candidates=max_candidates, date_preset=date_preset, date_from=date_from, date_to=date_to, include_excel=include_excel, search_id=search_id, fast_mode=fast_mode)
    finally:
        _search_lock.release()

def _do_main(job_query, account_email="recruiter@ecorptrainings.com", max_candidates=25, date_preset=None, date_from=None, date_to=None, include_excel=False, search_id=None, fast_mode=False):
    if not job_query or not job_query.strip():
        print("Job Query / Job Description cannot be empty.")
        return

    try:
        target_candidates = int(max_candidates or 25)
    except (ValueError, TypeError):
        target_candidates = 25

    os.makedirs(RESUME_FOLDER, exist_ok=True)
    if isinstance(account_email, dict):
        account_email = account_email.get("email", "recruiter@ecorptrainings.com")
    email_key = account_email.lower().strip() if account_email else "recruiter@ecorptrainings.com"
    
    # FIX 3: Remove old result files to avoid serving stale cached results
    if os.path.exists(OUTPUT_CSV):
        try:
            os.remove(OUTPUT_CSV)
        except Exception:
            pass
    summary_file_path = os.path.join(RESUME_FOLDER, "scan_summary.json")
    if os.path.exists(summary_file_path):
        try:
            os.remove(summary_file_path)
        except Exception:
            pass

    if not search_id:
        search_id = str(uuid.uuid4())
    logger.info(f"[search-NEW] search_id={search_id} jd={job_query}")
    logger.info(f"[search-ENTRY] mailbox={email_key} jd={job_query} target={target_candidates} timestamp={time.time()}")
    if email_key == 'recruiter@ecorptrainings.com' and job_query.lower() == 'java':
        logger.info(f"[search-VERIFY] this is a fresh search for java")

    t_start = time.time()
    service = auto_authenticate_google(email_key)
    
    logger.info(f"[search-STEP] building Gmail query")
    search_query = build_gmail_search_query(job_query, date_preset=date_preset, date_from=date_from, date_to=date_to)
    logger.info(f"[search-STEP] query={search_query}")

    progress = SearchProgress(target=target_candidates, search_id=search_id)
    _searches[search_id] = progress

    logger.info(f"[search-STEP] calling search_gmail_until_target")
    downloaded_attachments = search_gmail_until_target(
        service=service,
        query=search_query,
        email_key=email_key,
        target_attachments=target_candidates,
        batch_size=50,
        max_emails=min(target_candidates * 5, MAX_EMAILS_TO_SCAN),
        search_id=search_id
    )

    total_downloaded = len(downloaded_attachments)
    logger.info(f"[search-STEP] downloaded {total_downloaded} files")
    logger.info(f"[search] collected {total_downloaded} attachments for target {target_candidates}")

    default_cols = ["Rank", "Source", "source", "source_file", "Name", "Gender", "Email", "Phone", "Experience", "Skill Set", "Matched Skills", "Match Score", "Match Reason", "ReceivedAt"]

    if not downloaded_attachments:
        logger.info("[search-DONE] 0 resume attachments found.")
        pd.DataFrame(columns=default_cols).to_csv(OUTPUT_CSV, index=False)
        with open(summary_file_path, "w") as f_sum:
            json.dump({'pdf': 0, 'docx': 0, 'total_scanned': 0, 'matched': 0}, f_sum)
        progress.done()
        return

    items_to_extract = downloaded_attachments
    if fast_mode and total_downloaded > 30:
        items_to_extract = downloaded_attachments[:30]
        logger.info(f"[search-FASTMODE] Fast mode active: extracting 30 of {total_downloaded} downloaded attachments")

    logger.info(f"[search-START] search_id={search_id} target={target_candidates} jd={job_query}")

    progress.set_stats(status="extracting")
    all_candidates = []
    seen_identifiers = set()
    scan_summary = {'pdf': 0, 'docx': 0}

    BATCH_SIZE = getattr(ai_extractor, 'BATCH_SIZE', 5)
    total_batches = (len(items_to_extract) + BATCH_SIZE - 1) // BATCH_SIZE

    for batch_idx in range(total_batches):
        batch_items = items_to_extract[batch_idx * BATCH_SIZE : (batch_idx + 1) * BATCH_SIZE]
        batch_texts = []

        for item in batch_items:
            fn_low = item['filename'].lower()
            src_type = 'pdf' if fn_low.endswith('.pdf') else 'docx'
            scan_summary[src_type] = scan_summary.get(src_type, 0) + 1
            txt = extract_text_from_bytes(item['file_bytes'], item['filename'])
            batch_texts.append(txt)

        # Batch AI Extraction via Groq
        batch_ai_results = ai_extractor.extract_batch(batch_texts, job_query)
        logger.info(f"[search-EXTRACT] batch {batch_idx + 1}/{total_batches} ({len(batch_ai_results)} candidates)")

        for idx, item in enumerate(batch_items):
            resume_text = batch_texts[idx]
            if not resume_text:
                progress.increment()
                continue

            filename = item['filename']
            email_body = extract_email_body(item['payload'])
            sender_header = item['sender_header']
            reply_to_header = item['reply_to_header']
            subject = item['subject']
            internal_date_ms = item['internal_date_ms']
            received_iso = None

            if internal_date_ms:
                try:
                    ts_sec = float(internal_date_ms) / 1000.0
                    received_iso = datetime.fromtimestamp(ts_sec, tz=timezone.utc).isoformat()
                except Exception:
                    pass

            fn_low = filename.lower()
            src_type = 'pdf' if fn_low.endswith('.pdf') else 'docx'

            # Deterministic extraction
            extracted_email = extract_email_smart(resume_text, email_body, sender_header, reply_to_header, subject)
            extracted_phone = extract_phone_smart(resume_text, email_body, subject)
            deterministic_name = extract_candidate_name_smart(resume_text, email_body, sender_header, filename, extracted_email, subject)
            deterministic_exp = extract_experience_from_text(resume_text)
            deterministic_skills = extract_skills_from_text(resume_text, job_query)
            det_score, det_matched_skills, det_reason = extract_matched_skills_and_score(resume_text, job_query)

            ai_data = batch_ai_results[idx] if idx < len(batch_ai_results) and isinstance(batch_ai_results[idx], dict) else {}

            cand_name = ai_data.get("name") or deterministic_name
            if not is_valid_name(cand_name):
                fallback_user = extracted_email.split('@')[0] if '@' in extracted_email else 'Unknown'
                cand_name = fallback_user or 'Unknown'

            cand_email = clean_extracted_email(ai_data.get("email")) if ai_data.get("email") else extracted_email
            if cand_email == "N/A":
                cand_email = extracted_email if extracted_email != "N/A" else "candidate.contact@gmail.com"

            cand_phone = clean_phone(ai_data.get("phone")) if ai_data.get("phone") else extracted_phone
            if not cand_phone:
                cand_phone = extracted_phone if extracted_phone != "N/A" else "Available via Email"

            cand_skills = ai_data.get("skills") or deterministic_skills
            if isinstance(cand_skills, list):
                cand_skills = ", ".join(str(s) for s in cand_skills)

            cand_exp = ai_data.get("experience") or deterministic_exp
            raw_score = ai_data.get("match_score") if ai_data.get("match_score") is not None else det_score
            try:
                cand_score = float(str(raw_score).replace('%', '') or det_score)
            except Exception:
                cand_score = float(det_score)

            cand_matched_skills = ai_data.get("matched_skills") or det_matched_skills
            cand_reason = ai_data.get("match_reason") or det_reason
            cand_gender = ai_data.get("gender") or "Unknown"

            candidate_data = {
                "Name": cand_name,
                "Email": cand_email,
                "Phone": cand_phone,
                "Skill Set": str(cand_skills),
                "Experience": str(cand_exp),
                "Matched Skills": str(cand_matched_skills),
                "Match Score": int(cand_score),
                "Match Reason": str(cand_reason),
                "Gender": str(cand_gender).capitalize(),
                "Source": src_type,
                "source": src_type,
                "source_file": filename,
                "ReceivedAt": received_iso or datetime.now(timezone.utc).isoformat(),
                "received_at": received_iso or datetime.now(timezone.utc).isoformat()
            }

            cand_email_low = cand_email.lower().strip()
            if is_system_or_portal_email(cand_email_low, email_key):
                pers_match = re.findall(r'[A-Za-z0-9._%+-]+@(?!ecorptrainings|ecorp|naukri|linkedin|indeed)[A-Za-z0-9.-]+\.[A-Za-z]{2,6}', resume_text, re.IGNORECASE)
                if pers_match:
                    candidate_data["Email"] = pers_match[0]
                else:
                    progress.increment()
                    continue

            dedup_key = candidate_data["Email"].lower()
            if dedup_key not in seen_identifiers:
                seen_identifiers.add(dedup_key)
                all_candidates.append(candidate_data)

            progress.increment()

    # PART 4 — Filter candidates by score BEFORE counting toward target
    MIN_MATCH_SCORE = int(os.environ.get("MIN_MATCH_SCORE", 40))
    relevant = []
    for candidate in all_candidates:
        score = float(str(candidate.get("Match Score", 0)).replace('%', ''))
        if score >= MIN_MATCH_SCORE:
            relevant.append(candidate)
        else:
            logger.info(f'[search-SCORE] skipped {candidate.get("Name")} (score={score})')

    hidden_count = len(all_candidates) - len(relevant)
    logger.info(f'[search-SCORE] {len(relevant)} relevant, {hidden_count} below score {MIN_MATCH_SCORE}')

    # PART 5 — Name deduplication
    candidates = dedupe_by_name(relevant)
    removed_dups = len(relevant) - len(candidates)
    logger.info(f'[search-DEDUP] {removed_dups} duplicates removed')

    progress.done()
    elapsed = round(time.time() - t_start, 1)
    logger.info(f'[search-DONE] target={target_candidates} found={len(candidates)} emails={progress.emails_scanned} duration={elapsed}s')

    summary_data = {
        'pdf': scan_summary.get('pdf', 0),
        'docx': scan_summary.get('docx', 0),
        'total_scanned': len(candidates),
        'matched': len([c for c in candidates if c.get('Match Score', 0) >= 50]),
        'hidden_below_score': hidden_count
    }
    with open(summary_file_path, "w") as f_sum:
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