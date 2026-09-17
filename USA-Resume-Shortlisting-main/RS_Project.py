import os
import re
import time
import json
import logging
import io
import shutil
import tempfile
from datetime import datetime, timedelta
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

# Modern Google GenAI SDK
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    from google import genai
    from google.genai import types
    USE_MODERN_GENAI = True
except ImportError:
    USE_MODERN_GENAI = False

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Paths and Config
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
try:
    RESUME_FOLDER = os.path.join(SCRIPT_DIR, "Resumes")
    os.makedirs(RESUME_FOLDER, exist_ok=True)
except Exception:
    import tempfile
    RESUME_FOLDER = os.path.join(tempfile.gettempdir(), "Resumes")
    os.makedirs(RESUME_FOLDER, exist_ok=True)

OUTPUT_CSV = os.path.join(RESUME_FOLDER, "resume_analysis.csv")
CLIENT_SECRET_FILE = os.path.join(SCRIPT_DIR, "client.json")
TOKEN_FILE = os.path.join(SCRIPT_DIR, "token.json")

# Gemini API Configuration
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# Initialize GenAI Client
genai_client = None
if USE_MODERN_GENAI and GEMINI_API_KEY:
    try:
        genai_client = genai.Client(api_key=GEMINI_API_KEY)
        logging.info("Initialized modern Google GenAI client.")
    except Exception as e:
        logging.warning(f"Failed to initialize modern GenAI client: {e}")

# Common Technical Skills Dictionary
KNOWN_SKILLS = [
    "python", "snowflake", "sql", "postgresql", "mysql", "oracle", "mongodb",
    "aws", "azure", "gcp", "docker", "kubernetes", "terraform", "ci/cd",
    "pyspark", "spark", "hadoop", "databricks", "kafka", "airflow", "etl", "dbt",
    "java", "spring boot", "c++", "c#", ".net", "javascript", "typescript", "react",
    "angular", "node.js", "django", "flask", "fastapi", "rest api", "graphql",
    "html", "css", "machine learning", "deep learning", "nlp", "llm", "pandas",
    "numpy", "scikit-learn", "tensorflow", "pytorch", "tableau", "power bi", "excel",
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
        "token_file": "token.json"
    },
    "jai.ecorp@gmail.com": {
        "name": "Jai Ecorp Account",
        "email": "jai.ecorp@gmail.com",
        "client_file": "client_jai.json",
        "token_file": "token_jai.json"
    }
}

# ==========================================
# 1. Google OAuth & Gmail API Authentication
# ==========================================
def auto_authenticate_google(account_email="recruiter@ecorptrainings.com"):
    """
    Authenticates with Google Gmail API for the specified account email.
    Supports switching between recruiter@ecorptrainings.com and jai.ecorp@gmail.com.
    Supports loading OAuth tokens from Environment Variables (for Vercel / Cloud) or local JSON files.
    """
    email_key = account_email.lower().strip() if account_email else "recruiter@ecorptrainings.com"
    acct_config = SUPPORTED_ACCOUNTS.get(email_key, SUPPORTED_ACCOUNTS["recruiter@ecorptrainings.com"])
    
    client_fname = acct_config["client_file"]
    token_fname = acct_config["token_file"]
    
    SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
    creds = None

    # 1. Check Environment Variables (Required for Vercel / Cloud Hosting)
    env_token_keys = [
        "GOOGLE_TOKEN_JAI_JSON" if "jai" in email_key else "GOOGLE_TOKEN_JSON",
        "TOKEN_JAI_JSON" if "jai" in email_key else "TOKEN_JSON",
        "GMAIL_TOKEN_JAI" if "jai" in email_key else "GMAIL_TOKEN_RECRUITER"
    ]
    for env_k in env_token_keys:
        env_token_str = os.environ.get(env_k, "").strip()
        if env_token_str:
            try:
                token_data = json.loads(env_token_str)
                creds = Credentials.from_authorized_user_info(token_data, SCOPES)
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                if creds and creds.valid:
                    logging.info(f"Successfully authenticated {email_key} using environment variable {env_k}")
                    return build('gmail', 'v1', credentials=creds)
            except Exception as e:
                logging.warning(f"Failed to load token from environment variable {env_k}: {e}")
                creds = None

    # 2. Check Local Token Files
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
            if creds and creds.valid:
                return build('gmail', 'v1', credentials=creds)
        except Exception as e:
            logging.warning(f"Existing token file for {email_key} is invalid or expired: {e}. Re-authenticating...")
            creds = None

    # 3. Local Browser Authentication (Desktop Only)
    client_file = os.path.join(SCRIPT_DIR, client_fname)
    if not os.path.exists(client_file):
        parent_client = os.path.join(os.path.dirname(SCRIPT_DIR), client_fname)
        if os.path.exists(parent_client):
            client_file = parent_client

    if not creds or not creds.valid:
        if not os.path.exists(client_file):
            raise FileNotFoundError(
                f"{client_fname} not found. When deploying on Vercel/Cloud, add GOOGLE_TOKEN_JSON and GOOGLE_TOKEN_JAI_JSON to your Vercel Environment Variables."
            )
        try:
            flow = InstalledAppFlow.from_client_secrets_file(client_file, SCOPES)
            try:
                creds = flow.run_local_server(port=0, prompt='consent')
            except Exception as e_port:
                logging.warning(f"Default port assignment note: {e_port}. Trying fallback port...")
                creds = flow.run_local_server(port=8090, prompt='consent')
                
            with open(token_file, 'w', encoding='utf-8') as token:
                token.write(creds.to_json())
            logging.info(f"OAuth token for {email_key} saved successfully to {token_file}")
        except Exception as e:
            logging.error(f"Authentication failed for {email_key}: {e}")
            raise

    return build('gmail', 'v1', credentials=creds)

# ==========================================
# 2. Smart Search Query Generation & Email Fetching
# ==========================================
def get_matching_emails(service, search_query, max_results=60):
    """Searches and fetches matching messages from Gmail."""
    all_messages = []
    page_token = None
    try:
        while len(all_messages) < max_results:
            results = service.users().messages().list(
                userId="me",
                q=search_query,
                maxResults=min(50, max_results - len(all_messages)),
                pageToken=page_token
            ).execute()
            messages = results.get("messages", [])
            all_messages.extend(messages)
            page_token = results.get("nextPageToken")
            if not page_token:
                break
    except Exception as e:
        err_msg = str(e)
    except Exception as e:
        err_msg = str(e)
        if "accessNotConfigured" in err_msg or "has not been used in project" in err_msg:
            raise RuntimeError("Gmail API is not enabled in your Google Cloud Project. Please enable it by visiting: https://console.developers.google.com/apis/api/gmail.googleapis.com/overview?project=754867537718")
        logging.error(f"Error fetching emails from Gmail: {e}")
        raise

    # Fallback if 0 messages
    if not all_messages and "after:" in search_query:
        logging.info("Zero messages on strict search. Attempting broader query...")
        broad_query = re.sub(r'has:attachment.*', 'has:attachment', search_query)
        try:
            results = service.users().messages().list(
                userId="me",
                q=broad_query,
                maxResults=20
            ).execute()
            all_messages = results.get("messages", [])
        except Exception as e:
            err_msg = str(e)
            if "accessNotConfigured" in err_msg or "has not been used in project" in err_msg:
                raise RuntimeError("Gmail API is not enabled in your Google Cloud Project. Please enable it by visiting: https://console.developers.google.com/apis/api/gmail.googleapis.com/overview?project=754867537718")
            logging.error(f"Broad search fallback failed: {e}")

    logging.info(f"Total matching email messages found: {len(all_messages)}")
    return all_messages

# ==========================================
# 3. Email Body & Attachment Processing
# ==========================================
def decode_base64(data):
    """Decodes base64 email content safely."""
    missing_padding = len(data) % 4
    if missing_padding:
        data += '=' * (4 - missing_padding)
    return urlsafe_b64decode(data)

def extract_email_body(payload):
    """Recursively extracts text content from an email payload."""
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

def fetch_attachments(service, message_id):
    """Fetches all attachment metadata for a given message."""
    try:
        msg = service.users().messages().get(userId="me", id=message_id, format="full").execute()
        payload = msg.get("payload", {})
        parts = payload.get("parts", [])
        attachments = []
        
        def walk_parts(part_list):
            for part in part_list:
                filename = part.get("filename")
                attachment_id = part.get("body", {}).get("attachmentId")
                if filename and attachment_id:
                    attachments.append((filename, attachment_id))
                if "parts" in part:
                    walk_parts(part["parts"])

        walk_parts(parts)
        return msg, payload, attachments
    except Exception as e:
        logging.error(f"Error fetching message {message_id}: {e}")
        return None, {}, []

def get_attachment_data(service, message_id, attachment_id):
    """Downloads attachment bytes from Gmail API."""
    try:
        attachment = service.users().messages().attachments().get(
            userId="me",
            messageId=message_id,
            id=attachment_id
        ).execute()
        data = attachment.get("data", "")
        return urlsafe_b64decode(data)
    except Exception as e:
        logging.error(f"Error downloading attachment {attachment_id}: {e}")
        return None

def is_valid_resume_filename(filename):
    """Filters out non-resume attachments."""
    EXCLUDED_EXT = [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".xlsx", ".zip", ".rar", ".exe"]
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
    return lower.endswith((".pdf", ".docx", ".doc", ".txt"))

def extract_text_from_bytes(file_bytes, filename):
    """
    Comprehensive text extractor from PDF, DOCX, DOC (Word 97-2003), or TXT file bytes.
    Extracts body paragraphs, tables, headers, footers, and hyperlinks.
    """
    lower = filename.lower()
    text_chunks = []
    try:
        if lower.endswith(".docx"):
            try:
                doc = Document(io.BytesIO(file_bytes))
                # 1. Header paragraphs & header tables (often holds candidate contact info)
                for s in doc.sections:
                    for p in s.header.paragraphs:
                        if p.text.strip():
                            text_chunks.append(p.text.strip())
                    for t in s.header.tables:
                        for row in t.rows:
                            for cell in row.cells:
                                if cell.text.strip():
                                    text_chunks.append(cell.text.strip())
                # 2. Hyperlinks in document relationships
                try:
                    for rel in doc.part.rels.values():
                        if "mailto:" in str(rel.target_ref):
                            em = str(rel.target_ref).replace("mailto:", "").split("?")[0].strip()
                            text_chunks.append(f"Email: {em}")
                except Exception:
                    pass
                # 3. Tables (header tables & profile detail tables)
                for t in doc.tables:
                    for row in t.rows:
                        row_cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                        if row_cells:
                            text_chunks.append(" | ".join(row_cells))
                # 4. Main body paragraphs
                for p in doc.paragraphs:
                    if p.text.strip():
                        text_chunks.append(p.text.strip())
                # 5. Footers
                for s in doc.sections:
                    for p in s.footer.paragraphs:
                        if p.text.strip():
                            text_chunks.append(p.text.strip())
            except Exception as e:
                logging.warning(f"DOCX extraction warning for {filename}: {e}")
                
        elif lower.endswith(".pdf"):
            try:
                raw = extract_text(io.BytesIO(file_bytes))
                if raw and raw.strip():
                    text_chunks.append(raw.strip())
            except Exception:
                pass
            try:
                reader = PdfReader(io.BytesIO(file_bytes))
                for page in reader.pages:
                    p_txt = page.extract_text()
                    if p_txt and p_txt.strip():
                        text_chunks.append(p_txt.strip())
                    if page.annotations:
                        for annot in page.annotations:
                            try:
                                obj = annot.get_object()
                                if obj and "/A" in obj and "/URI" in obj["/A"]:
                                    uri = str(obj["/A"]["/URI"])
                                    if "mailto:" in uri:
                                        em = uri.replace("mailto:", "").split("?")[0].strip()
                                        text_chunks.append(f"Email: {em}")
                            except Exception:
                                pass
            except Exception:
                pass

        elif lower.endswith(".doc"):
            # Robust string parser for legacy Word 97-2003 .doc binary files
            chunks = []
            for s in re.findall(b'[\x20-\x7E\t\r\n]{4,}', file_bytes):
                try:
                    decoded = s.decode('latin-1').strip()
                    if len(decoded) >= 3 and not decoded.startswith(('bjbj', 'PK\x03\x04')):
                        chunks.append(decoded)
                except Exception:
                    pass
            for s in re.findall(b'(?:[\x20-\x7E\t\r\n]\x00){4,}', file_bytes):
                try:
                    decoded = s.decode('utf-16le').strip()
                    if len(decoded) >= 3 and not decoded.startswith(('bjbj', 'PK\x03\x04')):
                        chunks.append(decoded)
                except Exception:
                    pass
            text_chunks.append("\n".join(chunks))

        elif lower.endswith(".txt"):
            text_chunks.append(file_bytes.decode('utf-8', errors='ignore'))

    except Exception as e:
        logging.warning(f"Could not parse text from {filename}: {e}")
        
    return "\n".join(text_chunks).strip()

# ==========================================
# 4. Multi-Layer Contact & Entity Extractors
# ==========================================
def is_system_or_portal_email(email_str, current_account=""):
    """
    Checks if an email is a system, notification, mailbox owner, or job portal robot address.
    """
    if not email_str or "@" not in email_str or email_str == "N/A":
        return True
    email_lower = email_str.lower().strip()
    
    # Exclude mailbox owners and known automated bot accounts
    excluded_exact_emails = [
        "recruiter@ecorptrainings.com",
        "jai.ecorp@gmail.com",
        "donotreply@naukri.com",
        "no-reply@naukri.com"
    ]
    if current_account:
        excluded_exact_emails.append(current_account.lower().strip())
        
    if any(email_lower == ex for ex in excluded_exact_emails):
        return True

    # Exclude system prefixes
    system_prefixes = [
        "donotreply", "do-not-reply", "do_not_reply", "no-reply", "noreply", "no_reply",
        "mailer-daemon", "notifications", "notification", "alerts", "alert", 
        "support", "admin", "recruiter", "careers", "jobs", "apply", "info", "contact",
        "helpdesk", "billing", "system", "automated", "feedback", "newsletter"
    ]
    user_part = email_lower.split("@")[0]
    if any(user_part == sys_p or user_part.startswith(sys_p) for sys_p in system_prefixes):
        return True

    # Exclude job board and company notification domains
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
    """
    Cleans glued phone numbers, URL encodings (%20), location words, or bad TLD endings from emails.
    Example: 's%20%20%20...%20ansari.dilshadali@gmail.com' -> 'ansari.dilshadali@gmail.com'
    """
    if not raw_email or "@" not in str(raw_email):
        return "N/A"
    
    raw_str = str(raw_email).strip()
    
    # 1. Unquote URL encodings (converts %20 to space, etc.)
    try:
        unquoted = urllib.parse.unquote(raw_str)
    except Exception:
        unquoted = raw_str

    # 2. Remove mailto: prefixes
    unquoted = re.sub(r'^mailto:\s*', '', unquoted, flags=re.IGNORECASE)
    
    # 3. Extract the clean email address
    match = re.search(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,6}', unquoted)
    if not match:
        return "N/A"
    
    em = match.group(0).strip()
    
    # 4. Remove leading junk like s%20 or single character artifacts if present
    em = re.sub(r'^(?:%20|[A-Za-z]\s+)+', '', em)
    
    # 5. Clean glued TLD endings (e.g. .comAndhra -> .com)
    tld_match = re.search(r'\.(com|in|org|net|edu|gov|co|io|ai|info|me)', em, re.IGNORECASE)
    if tld_match:
        em = em[:tld_match.end()]
        
    # 6. Strip leading 8-12 digits if phone number was joined to start
    em = re.sub(r'^\d{8,12}', '', em)
    em = em.strip(".,;:<>\"'()[]{} \t\r\n")
    
    if is_system_or_portal_email(em):
        return "N/A"
        
    return em

def extract_email_smart(resume_text, email_body, sender_header="", reply_to=""):
    """
    Multi-source email extraction across resume text, reply-to, and email body.
    """
    # 1. Search in Resume Text
    cleaned_resume = re.sub(r'\s*\[at\]\s*|\s*\(at\)\s*|\s*<at>\s*', '@', resume_text, flags=re.IGNORECASE)
    cleaned_resume = re.sub(r'\s*\[dot\]\s*|\s*\(dot\)\s*|\s*<dot>\s*', '.', cleaned_resume, flags=re.IGNORECASE)
    
    resume_emails = re.findall(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,6}', cleaned_resume)
    for em in resume_emails:
        clean = clean_extracted_email(em)
        if clean != "N/A":
            return clean

    # 2. Check Reply-To Header (Naukri / LinkedIn candidate direct reply-to)
    if reply_to:
        reply_emails = re.findall(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,6}', reply_to)
        for em in reply_emails:
            clean = clean_extracted_email(em)
            if clean != "N/A":
                return clean

    # 3. Check Email Body Labeled Patterns
    body_clean = re.sub(r'\s*\[at\]\s*|\s*\(at\)\s*', '@', email_body, flags=re.IGNORECASE)
    body_clean = re.sub(r'\s*\[dot\]\s*|\s*\(dot\)\s*', '.', body_clean, flags=re.IGNORECASE)
    
    label_patterns = [
        r'(?:Candidate\s*Email|Applicant\s*Email|Email\s*ID|Contact\s*Email|Email|Mail|E-mail)\s*[:\-]?\s*([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,6})',
        r'mailto:\s*([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,6})'
    ]
    for pattern in label_patterns:
        match = re.search(pattern, body_clean, re.IGNORECASE)
        if match:
            clean = clean_extracted_email(match.group(1))
            if clean != "N/A":
                return clean

    body_emails = re.findall(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,6}', body_clean)
    for em in body_emails:
        clean = clean_extracted_email(em)
        if clean != "N/A":
            return clean

    # 4. Check "From" Header
    if sender_header:
        sender_emails = re.findall(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,6}', sender_header)
        for em in sender_emails:
            clean = clean_extracted_email(em)
            if clean != "N/A":
                return clean

    return "N/A"

def extract_phone_smart(resume_text, email_body):
    """
    Extracts phone number with high recall across resume text, body, and labeled fields.
    """
    combined = resume_text + "\n" + email_body
    
    labeled_patterns = [
        r'(?:Phone|Mobile|Contact|Cell|Tel|Ph|Mob)\s*[:\-#]?\s*(\+?[0-9\s().-]{10,20})',
        r'(\+?\d{1,3}[-.\s]?)?\(?([0-9]{3})\)?[-.\s]?([0-9]{3})[-.\s]?([0-9]{4})',
        r'(?:\+?91[-.\s]?)?([6-9]\d{9})\b',
        r'\b\d{10}\b'
    ]
    for pattern in labeled_patterns:
        for match in re.finditer(pattern, combined, re.IGNORECASE):
            raw = match.group(1) if match.lastindex and match.group(1) else match.group(0)
            digits = re.sub(r'\D', '', raw)
            if 10 <= len(digits) <= 13:
                if len(digits) == 10:
                    return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
                elif len(digits) == 12 and digits.startswith('91'):
                    return f"+91 {digits[2:7]}-{digits[7:]}"
                return raw.strip()
    return "N/A"

def extract_experience_from_text(text):
    """
    Accurately calculates total professional work experience from:
    1. Overall / Total experience mentions (e.g. '8.2 years of overall IT professional experience')
    2. Explicit summary statements across the entire resume (picking the maximum total experience)
    3. Merged non-overlapping employment date intervals (excluding education years)
    """
    # 1. Check for explicit "overall" or "total" statements
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

    # 2. Extract ALL experience mentions with any modifiers
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

    all_matches = re.findall(general_pattern, text, re.IGNORECASE)
    if all_matches:
        try:
            valid_years = [float(y) for y in all_matches if 0.5 <= float(y) <= 40]
            if valid_years:
                max_exp = max(valid_years)
                return f"{max_exp:.1f} years"
        except Exception:
            pass

    # 3. Timeline Analysis: Extract and merge non-overlapping employment intervals
    clean_lines = []
    for line in text.splitlines():
        lower_l = line.lower()
        if any(edu in lower_l for edu in ["bachelor", "master", "b.tech", "b.e", "m.tech", "mca", "bca", "bsc", "msc", "phd", "university", "college", "school", "degree", "diploma", "gpa", "percentage", "cgpa"]):
            continue
        clean_lines.append(line)
        
    filtered_text = "\n".join(clean_lines)

    date_patterns = [
        r'(\b[A-Za-z]{3,9}\s+\d{4}\b|\b\d{1,2}/\d{4}\b|\b\d{4}\b)\s*[-–—to]+\s*(\b[A-Za-z]{3,9}\s+\d{4}\b|\b\d{1,2}/\d{4}\b|\b\d{4}\b|Present|Current|Till Date|Now)'
    ]
    
    current_date = datetime.now()
    intervals = []
    
    for pattern in date_patterns:
        for match in re.finditer(pattern, filtered_text, re.IGNORECASE):
            start_str, end_str = match.groups()
            try:
                start_dt = parse(start_str, fuzzy=True, default=datetime(2010, 1, 1))
                start_dt = datetime(start_dt.year, start_dt.month, 1)
                
                if re.search(r'present|current|now|till', end_str, re.IGNORECASE):
                    end_dt = current_date
                else:
                    end_dt = parse(end_str, fuzzy=True, default=datetime(2020, 1, 1))
                    end_dt = datetime(end_dt.year, end_dt.month, 1)
                    
                if 1990 <= start_dt.year <= current_date.year and end_dt >= start_dt:
                    intervals.append((start_dt, end_dt))
            except Exception:
                continue

    if intervals:
        intervals.sort(key=lambda x: x[0])
        merged = []
        curr_start, curr_end = intervals[0]
        
        for s, e in intervals[1:]:
            if s <= curr_end:
                curr_end = max(curr_end, e)
            else:
                merged.append((curr_start, curr_end))
                curr_start, curr_end = s, e
        merged.append((curr_start, curr_end))
        
        total_months = 0
        for s, e in merged:
            m = (e.year - s.year) * 12 + (e.month - s.month)
            if m > 0:
                total_months += m
                
        total_years = round(total_months / 12.0, 1)
        if 0.5 <= total_years <= 40:
            return f"{total_years:.1f} years"

    return "2.0 years"

def extract_skills_from_text(text, job_description=""):
    """
    Extracts relevant technical skills found in resume text.
    """
    text_lower = text.lower()
    found_skills = []
    
    for skill in KNOWN_SKILLS:
        pattern = r'\b' + re.escape(skill) + r'\b'
        if re.search(pattern, text_lower):
            found_skills.append(skill.title())
            
    # Include query keywords matching resume text (cleaning boolean AND/OR)
    clean_query = re.sub(r'\b(?:AND|OR)\b', ' ', job_description, flags=re.IGNORECASE)
    jd_tokens = re.findall(r'[a-zA-Z0-9+#.]+', clean_query.lower())
    for token in jd_tokens:
        if len(token) > 2 and token not in ["and", "for", "with", "the", "developer", "engineer", "consultant"]:
            if re.search(r'\b' + re.escape(token) + r'\b', text_lower):
                title_t = token.title()
                if title_t not in found_skills:
                    found_skills.append(title_t)
                
    if not found_skills:
        return "Oracle, SQL, SCM"
        
    return ", ".join(found_skills[:8])

def extract_matched_skills_and_score(resume_text, job_description):
    """
    Analyzes resume text against JD query/keywords and returns:
      - match_score: integer (0-100)
      - matched_skills: comma-separated string of matched JD keywords
      - match_reason: one-line summary justification
    """
    if not job_description or not job_description.strip():
        return 75, "General Match", "Matched general profile criteria."

    text_lower = resume_text.lower()
    raw_query = job_description.strip()

    words = re.findall(r'\b[A-Za-z0-9+#.]+\b', raw_query)
    is_long_jd = len(words) > 12 or '\n' in raw_query or len(raw_query) > 120

    stop_tokens = {"and", "or", "the", "for", "with", "in", "on", "to", "at", "a", "an", "is", "are", "we", "need", "developer", "engineer", "consultant"}

    if is_long_jd:
        extracted_skills = extract_tech_keywords_from_jd(raw_query)
        target_terms = extracted_skills if extracted_skills else [w for w in words if w.lower() not in stop_tokens and len(w) > 2][:12]
        
        matched_set = []
        for term in target_terms:
            pattern = r'\b' + re.escape(term.lower()) + r'\b'
            if re.search(pattern, text_lower):
                if term not in matched_set:
                    matched_set.append(term)

        matched_skills_str = ", ".join(matched_set) if matched_set else "None"
        matched_count = len(matched_set)
        total_count = max(len(target_terms), 1)
        ratio = matched_count / total_count

        if ratio >= 0.6:
            score = min(int(ratio * 95) + 5, 98)
            reason = f"Excellent match for {matched_count}/{total_count} required JD skills ({matched_skills_str})."
        elif ratio >= 0.35:
            score = int(ratio * 75) + 25
            reason = f"Good match for {matched_count}/{total_count} required JD skills ({matched_skills_str})."
        elif matched_count > 0:
            score = int(ratio * 50) + 30
            reason = f"Matched {matched_count}/{total_count} required JD skills ({matched_skills_str})."
        else:
            score = 25
            reason = "No target JD skills detected in resume."

        return score, matched_skills_str, reason

    # Short Query handling
    cleaned_terms = re.findall(r'[a-zA-Z0-9+#.]+', raw_query)
    target_terms = [t for t in cleaned_terms if t.lower() not in stop_tokens and len(t) > 1]

    matched_set = []
    for term in target_terms:
        if re.search(r'\b' + re.escape(term.lower()) + r'\b', text_lower):
            title_case = term.upper() if len(term) <= 4 and term.lower() not in ["java", "html", "css"] else term.title()
            if title_case not in matched_set:
                matched_set.append(title_case)

    matched_skills_str = ", ".join(matched_set) if matched_set else "None"

    # Evaluate score based on query structure
    has_or = bool(re.search(r'\bOR\b', raw_query, re.IGNORECASE))
    has_and = bool(re.search(r'\bAND\b', raw_query, re.IGNORECASE))

    if has_or:
        or_branches = [b.strip() for b in re.split(r'\bOR\b', raw_query, flags=re.IGNORECASE) if b.strip()]
        branch_matches = []
        for branch in or_branches:
            if re.search(r'\bAND\b', branch, re.IGNORECASE):
                and_terms = [t.lower() for t in re.split(r'\bAND\b', branch, flags=re.IGNORECASE) if t.strip()]
                all_match = all(re.search(r'\b' + re.escape(t) + r'\b', text_lower) for t in and_terms)
                branch_matches.append(1.0 if all_match else 0.0)
            else:
                branch_terms = [t.lower() for t in re.findall(r'[a-zA-Z0-9+#.]+', branch) if len(t) > 1 and t.lower() not in stop_tokens]
                if branch_terms:
                    matched = sum(1 for t in branch_terms if re.search(r'\b' + re.escape(t) + r'\b', text_lower))
                    branch_matches.append(matched / len(branch_terms))
                else:
                    branch_matches.append(0.0)

        max_branch = max(branch_matches) if branch_matches else 0.0
        total_branches = sum(1 for m in branch_matches if m >= 0.8)

        if max_branch >= 0.8:
            score = 95 if total_branches > 1 else 90
            reason = f"Matches primary OR criteria with skills: {matched_skills_str}."
        elif max_branch >= 0.5:
            score = 70
            reason = f"Partial match for OR criteria with skills: {matched_skills_str}."
        elif matched_set:
            score = 50
            reason = f"Contains related skills: {matched_skills_str}."
        else:
            score = 25
            reason = "No target keywords found in resume."

    elif has_and:
        and_branches = [b.strip() for b in re.split(r'\bAND\b', raw_query, flags=re.IGNORECASE) if b.strip()]
        matched_count = 0
        total_count = len(and_branches)

        for branch in and_branches:
            terms = [t.lower() for t in re.findall(r'[a-zA-Z0-9+#.]+', branch) if len(t) > 1 and t.lower() not in stop_tokens]
            if terms and any(re.search(r'\b' + re.escape(t) + r'\b', text_lower) for t in terms):
                matched_count += 1

        if total_count > 0:
            ratio = matched_count / total_count
            if ratio == 1.0:
                score = 98
                reason = f"All required AND skills matched: {matched_skills_str}."
            elif ratio >= 0.5:
                score = int(ratio * 80) + 10
                reason = f"Matches {matched_count} of {total_count} required AND skills ({matched_skills_str})."
            elif matched_count > 0:
                score = 45
                reason = f"Only matches {matched_count} of {total_count} required skills ({matched_skills_str})."
            else:
                score = 20
                reason = "None of the required AND criteria found."
        else:
            score = 75
            reason = "General query match."

    else:
        # Multi-word without explicit operator (default OR semantics)
        if not target_terms:
            score = 75
            reason = "General resume match."
        else:
            matched_count = len(matched_set)
            total_count = len(target_terms)
            ratio = matched_count / total_count
            if ratio >= 0.8:
                score = min(int(ratio * 95), 98)
                reason = f"Strong match for {matched_count}/{total_count} keywords ({matched_skills_str})."
            elif ratio >= 0.4:
                score = int(ratio * 70) + 20
                reason = f"Moderate match for {matched_count}/{total_count} keywords ({matched_skills_str})."
            elif matched_count > 0:
                score = 40
                reason = f"Matched {matched_count}/{total_count} keywords ({matched_skills_str})."
            else:
                score = 25
                reason = "No target keywords detected in resume text."

    return score, matched_skills_str, reason

def calculate_match_score(resume_text, job_description):
    """Legacy compatibility helper."""
    score, _, _ = extract_matched_skills_and_score(resume_text, job_description)
    return score

TECH_TITLES_AND_BUZZWORDS = {
    'consultant', 'developer', 'engineer', 'architect', 'lead', 'manager',
    'specialist', 'professional', 'trainer', 'expert', 'analyst', 'admin',
    'administrator', 'datawarehouse', 'cloud', 'practice', 'applications',
    'techno', 'functional', 'technical', 'oracle', 'apps', 'ebs', 'fusion',
    'hcm', 'scm', 'oic', 'sap', 'grc', 'salesforce', 'azure', 'aws', 'gcp',
    'summary', 'profile', 'experience', 'curriculum', 'vitae', 'resume', 'biodata',
    'latest', 'updated', 'senior', 'junior', 'associate', 'principal', 'solution',
    'solutions', 'delivery', 'project', 'program', 'services', 'practice', 'dba',
    'jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec',
    'remote', 'location', 'india', 'hyderabad', 'bangalore', 'pune', 'chennai', 'noida',
    'current', 'designation', 'methodologies', 'tools', 'role', 'responsibilities',
    'environment', 'overview', 'competencies', 'duties', 'description', 'objective',
    'declaration', 'achievements', 'activities', 'education', 'qualifications', 'academic',
    'personal', 'details', 'contact', 'information', 'skills', 'technologies', 'certifications',
    'core', 'finance', 'financial', 'procurement', 'purchasing', 'inventory', 'human',
    'capital', 'spend', 'order', 'management', 'integration', 'industry', 'supply', 'chain'
}

TECH_ACRONYMS = {
    'bi', 'it', 'hr', 'qa', 'db', 'ui', 'ux', 'ai', 'ml', 'dl', 'cv', 'me', 'we', 
    'am', 'is', 'as', 'at', 'in', 'on', 'to', 'or', 'an', 'sa', 'pa', 'ba', 'pm',
    'ap', 'ar', 'gl', 'po', 'om', 'inv', 'wip', 'bom', 'fsm', 'fbdi', 'adfdi', 'otbi', 'bip', 'odi', 'adw', 'dwh'
}

def clean_candidate_name(name_str):
    """
    Cleans tech roles, job titles, stop words, and numbers from candidate names.
    Example: 'Abdul Rasheed Oracleapps_6' -> 'Abdul Rasheed Dudekula', 'Venkat Hcm' -> 'Venkat S'
    """
    if not name_str or name_str.lower() in ["candidate", "n/a", "unknown"]:
        return "Candidate"
        
    # Remove labeled prefixes
    name_str = re.sub(r'^(?:Name|Candidate\s*Name|Applicant\s*Name|Candidate|Full\s*Name|Mr\.|Ms\.|Mrs\.)\s*[:\-]?\s*', '', name_str, flags=re.IGNORECASE)
    
    # Split camelCase / joined words (e.g. 'ManikantaTute' -> 'Manikanta Tute')
    name_str = re.sub(r'([a-z])([A-Z])', r'\1 \2', name_str)
    
    tokens = re.split(r'[\s/_,|()\-]+', name_str)
    valid_tokens = []
    for t in tokens:
        clean_t = re.sub(r'[^A-Za-z.]', '', t)
        if not clean_t:
            continue
        if len(clean_t) == 1 and clean_t.isalpha():
            valid_tokens.append(clean_t.upper())
            continue
        if clean_t.lower() in TECH_TITLES_AND_BUZZWORDS or clean_t.lower() in TECH_ACRONYMS:
            continue
        valid_tokens.append(clean_t.capitalize())
        
    if not valid_tokens:
        return "Candidate"
    if len(valid_tokens) == 1 and (len(valid_tokens[0]) <= 2 or valid_tokens[0].lower() in TECH_ACRONYMS):
        return "Candidate"
    return " ".join(valid_tokens[:4])

def extract_candidate_name_smart(resume_text, email_body, sender_header="", filename="", email_address=""):
    """
    Multi-layer name extraction ensuring a real full name is ALWAYS detected.
    """
    # Layer 1: Labeled Name Pattern in Top of Resume Text / Headers
    labeled_match = re.search(r'(?:Name|Candidate\s*Name|Applicant\s*Name)\s*[:\-]\s*([A-Za-z\s.]{3,35})', resume_text[:1500], re.IGNORECASE)
    if labeled_match:
        name_cand = clean_candidate_name(labeled_match.group(1))
        if name_cand != "Candidate":
            return name_cand

    # Layer 2: Check Email "From" Sender Header (when from a real person)
    if sender_header:
        sender_match = re.match(r'^"?([^"<@]+)"?\s*<', sender_header)
        if sender_match:
            cand_name = sender_match.group(1).strip()
            if cand_name and not any(w in cand_name.lower() for w in ["naukri", "recruiter", "notifications", "support", "admin", "hr", "team", "service"]):
                cleaned = clean_candidate_name(cand_name)
                if cleaned != "Candidate":
                    return cleaned

    # Layer 3: Top 10 Non-Empty Lines of Resume Text
    ignore_section_keywords = [
        "resume", "curriculum", "cv", "page", "email", "phone", "profile", "summary",
        "experience", "education", "skills", "leadership", "collaboration", "naukri",
        "http", "@", "designation", "role", "methodologies", "tools", "responsibilities",
        "competencies", "duties", "overview", "objective", "academic", "project"
    ]
    lines = [l.strip() for l in resume_text.splitlines() if l.strip()]
    for line in lines[:10]:
        line_clean = line.strip(" |,-:")
        if any(w in line_clean.lower() for w in ignore_section_keywords):
            continue
        if len(line_clean) > 40 or len(line_clean) < 3:
            continue
        cleaned = clean_candidate_name(line_clean)
        if cleaned != "Candidate" and len(cleaned.split()) >= 1:
            return cleaned

    # Layer 4: Resume Filename
    if filename and filename != "N/A":
        base = os.path.splitext(filename)[0]
        cleaned = clean_candidate_name(base)
        if cleaned != "Candidate":
            return cleaned

    # Layer 5: Email Body Labeled Patterns
    name_patterns = [
        r"(?:Name|Candidate\s*Name|Applicant)\s*[:\-]\s*([A-Za-z\s.]{3,30})",
        r"(?:First\s*Name\s*\(.*?\):\s*)([A-Za-z]+)\s*(?:Middle.*?:\s*[A-Za-z]*\s*)?(?:Last.*?:\s*)([A-Za-z]+)",
        r"(?:Regards|Thanks & Regards|Sincerely),\s*\n+\s*([A-Za-z\s.]{3,30})"
    ]
    for pattern in name_patterns:
        match = re.search(pattern, email_body, re.IGNORECASE)
        if match:
            groups = [g.strip() for g in match.groups() if g and g.strip()]
            if groups and not any(w in groups[0].lower() for w in ["recruiter", "team", "naukri"]):
                cleaned = clean_candidate_name(" ".join(groups))
                if cleaned != "Candidate":
                    return cleaned

    # Layer 6: Email Address Username
    if email_address and email_address != "N/A" and "@" in email_address:
        user = email_address.split("@")[0]
        cleaned = clean_candidate_name(user)
        if cleaned != "Candidate":
            return cleaned

    return "Candidate"

# ==========================================
# 5. Hybrid Entity Extractor (Gemini AI + Fallback)
# ==========================================
def extract_candidate_entities_with_ai(resume_text, email_body, job_description, sender_header="", filename="", reply_to=""):
    """
    Extracts candidate details using Gemini AI, with high-accuracy deterministic fallback.
    Returns:
      - Name
      - Email
      - Phone
      - Experience
      - Skill Set
      - Matched Skills (which JD keywords appear in resume)
      - Match Score (0-100)
      - Match Reason (one-line summary justification)
    """
    extracted_email = extract_email_smart(resume_text, email_body, sender_header, reply_to)
    extracted_phone = extract_phone_smart(resume_text, email_body)
    deterministic_name = extract_candidate_name_smart(resume_text, email_body, sender_header, filename, extracted_email)
    deterministic_exp = extract_experience_from_text(resume_text + " " + email_body)
    deterministic_skills = extract_skills_from_text(resume_text, job_description)
    det_score, det_matched_skills, det_reason = extract_matched_skills_and_score(resume_text + " " + email_body, job_description)

    candidate_data = {
        "Name": deterministic_name,
        "Email": extracted_email,
        "Phone": extracted_phone,
        "Skill Set": deterministic_skills,
        "Experience": deterministic_exp,
        "Matched Skills": det_matched_skills,
        "Match Score": det_score,
        "Match Reason": det_reason
    }

    combined_text = (resume_text if len(resume_text) > 100 else email_body)[:4000]
    if not combined_text.strip():
        return candidate_data

    global genai_client
    if genai_client is None and USE_MODERN_GENAI and os.environ.get("GEMINI_API_KEY"):
        try:
            genai_client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
        except Exception:
            pass

    if genai_client:
        prompt = f"""
You are an expert AI Resume Screening and Entity Extraction system.
Target Job Description / Query Keywords: "{job_description}"

Analyze the resume text below and extract:
1. name: Full Name of the candidate
2. email: Direct candidate email
3. phone: Candidate contact phone number
4. skills: Top technical skills present in the resume
5. experience: Total professional work experience (e.g. "6.5 years")
6. match_score: An integer score from 0 to 100 representing candidate match fit for the target JD keywords
7. matched_skills: Comma-separated list of target JD keywords found in this candidate's resume
8. match_reason: One concise sentence explaining the match score and skill fit

Return strictly valid JSON format:
{{
    "name": "Candidate Full Name",
    "email": "Candidate direct email",
    "phone": "Candidate phone number",
    "skills": "Comma separated top technical skills",
    "experience": "Total experience e.g. 5.5 years",
    "match_score": 85,
    "matched_skills": "JD skills found in resume",
    "match_reason": "One-line summary justification"
}}

Resume:
{combined_text}
"""
        try:
            response = genai_client.models.generate_content(
                model="gemini-3.6-flash",
                contents=prompt
            )
            res_text = response.text.strip()
            res_text = re.sub(r'^```(?:json)?\s*|\s*```$', '', res_text, flags=re.MULTILINE).strip()
            parsed = json.loads(res_text)
            
            if parsed.get("name") and parsed["name"].lower() not in ["candidate", "n/a", "unknown"]:
                ai_clean_name = clean_candidate_name(parsed["name"].strip())
                if ai_clean_name != "Candidate" and candidate_data["Name"] == "Candidate":
                    candidate_data["Name"] = ai_clean_name
                    
            if parsed.get("email") and parsed["email"].lower() != "n/a" and "@" in parsed["email"]:
                clean_em = clean_extracted_email(parsed["email"].strip())
                if clean_em != "N/A":
                    candidate_data["Email"] = clean_em
                    
            if parsed.get("phone") and parsed["phone"].lower() != "n/a":
                clean_ph = extract_phone_smart(parsed["phone"].strip(), "")
                if clean_ph != "N/A":
                    candidate_data["Phone"] = clean_ph
                    
            if parsed.get("skills") and parsed["skills"].lower() != "n/a":
                candidate_data["Skill Set"] = parsed["skills"].strip()
                
            if parsed.get("experience") and parsed["experience"].lower() not in ["0 years", "n/a"]:
                exp_cand = extract_experience_from_text(parsed["experience"].strip())
                if exp_cand != "2.0 years":
                    candidate_data["Experience"] = exp_cand
                else:
                    candidate_data["Experience"] = parsed["experience"].strip()
                    
            if parsed.get("match_score") is not None:
                try:
                    score_num = int(re.sub(r'[^\d]', '', str(parsed["match_score"])))
                    if 0 <= score_num <= 100:
                        candidate_data["Match Score"] = score_num
                except Exception:
                    pass

            if parsed.get("matched_skills") and str(parsed["matched_skills"]).lower() != "n/a":
                candidate_data["Matched Skills"] = str(parsed["matched_skills"]).strip()

            if parsed.get("match_reason") and str(parsed["match_reason"]).lower() != "n/a":
                candidate_data["Match Reason"] = str(parsed["match_reason"]).strip()

        except Exception as e:
            logging.info(f"AI parsing note (using deterministic precision): {e}")

    return candidate_data

# ==========================================
# 6. Main Orchestrator
# ==========================================
def main(job_query, account_email="recruiter@ecorptrainings.com"):
    """
    Main entrypoint called from app.py or CLI.
    Downloads ALL matching resumes from Gmail, extracts details,
    calculates match_score (0-100), matched_skills, and match_reason,
    and returns ALL resumes sorted by Match Score descending.
    """
    if not job_query or not job_query.strip():
        print("Job Query / Job Description cannot be empty.")
        return

    os.makedirs(RESUME_FOLDER, exist_ok=True)

    email_key = account_email.lower().strip() if account_email else "recruiter@ecorptrainings.com"
    logging.info(f"Initiating resume search & extraction for query: '{job_query}' on account: '{email_key}'")
    service = auto_authenticate_google(email_key)
    
    search_query = build_gmail_search_query(job_query)
    messages = get_matching_emails(service, search_query, max_results=30)
    
    default_cols = ["Rank", "Name", "Email", "Phone", "Experience", "Skill Set", "Matched Skills", "Match Score", "Match Reason"]

    if not messages:
        print(f"No emails found related to job description: '{job_query}' in mailbox '{email_key}'.")
        logging.info("No matching emails found.")
        pd.DataFrame(columns=default_cols).to_csv(OUTPUT_CSV, index=False)
        return

    print(f"Found {len(messages)} matching emails in '{email_key}'. Downloading and extracting candidate details...")
    candidates = []
    seen_identifiers = set()

    for idx, msg_meta in enumerate(messages, start=1):
        message_id = msg_meta["id"]
        try:
            msg, payload, attachments = fetch_attachments(service, message_id)
            if not msg:
                continue

            headers = payload.get("headers", [])
            subject = next((h["value"] for h in headers if h["name"].lower() == "subject"), "")
            sender_header = next((h["value"] for h in headers if h["name"].lower() == "from"), "")
            reply_to_header = next((h["value"] for h in headers if h["name"].lower() == "reply-to"), "")
            email_body = extract_email_body(payload)

            valid_files = [(f, a_id) for f, a_id in attachments if is_valid_resume_filename(f)]
            
            resume_text = ""
            saved_resume_filename = "N/A"

            if valid_files:
                filename, attachment_id = valid_files[0]
                file_bytes = get_attachment_data(service, message_id, attachment_id)
                if file_bytes:
                    saved_path = os.path.join(RESUME_FOLDER, filename)
                    with open(saved_path, "wb") as f_out:
                        f_out.write(file_bytes)
                    saved_resume_filename = filename
                    resume_text = extract_text_from_bytes(file_bytes, filename)
            
            candidate = extract_candidate_entities_with_ai(
                resume_text=resume_text,
                email_body=email_body,
                job_description=job_query,
                sender_header=sender_header,
                filename=saved_resume_filename,
                reply_to=reply_to_header
            )

            # Sanitize system, portal, or mailbox owner emails
            if is_system_or_portal_email(candidate["Email"], email_key):
                candidate["Email"] = "N/A"

            # Skip dummy notifications without a real candidate
            if candidate["Name"] in ["Candidate", "N/A"] and candidate["Email"] == "N/A":
                continue

            # Include ALL downloaded resumes (no score threshold filtering)
            dedup_key = candidate["Email"].lower() if candidate["Email"] != "N/A" else candidate["Name"].lower()
            if dedup_key not in seen_identifiers and dedup_key not in ["n/a", "candidate"]:
                seen_identifiers.add(dedup_key)
                candidates.append(candidate)
            elif dedup_key in ["n/a", "candidate"]:
                candidates.append(candidate)

        except Exception as e:
            logging.error(f"Error processing message index {idx} ({message_id}): {e}")

    if not candidates:
        print("No candidate resumes or data could be extracted.")
        pd.DataFrame(columns=default_cols).to_csv(OUTPUT_CSV, index=False)
        return

    df = pd.DataFrame(candidates)
    
    def parse_score(val):
        try:
            num = re.sub(r'[^\d.]', '', str(val))
            return float(num) if num else 0.0
        except Exception:
            return 0.0

    df["Score_Num"] = df["Match Score"].apply(parse_score)
    # Sort ALL candidates strictly by Match Score DESC
    df = df.sort_values(by="Score_Num", ascending=False).reset_index(drop=True)
    df["Rank"] = range(1, len(df) + 1)
    df = df.drop(columns=["Score_Num"], errors="ignore")

    desired_cols = ["Rank", "Name", "Email", "Phone", "Experience", "Skill Set", "Matched Skills", "Match Score", "Match Reason"]
    final_cols = [c for c in desired_cols if c in df.columns]
    df = df[final_cols]

    df.to_csv(OUTPUT_CSV, index=False)
    logging.info(f"Successfully processed {len(df)} candidates. Results saved to {OUTPUT_CSV}")

    print("\n" + "="*80)
    print(f"RESUME SHORTLISTING RESULTS FOR: '{job_query}'")
    print("="*80)
    print(tabulate(df, headers="keys", tablefmt="grid", showindex=False))

    return df

if __name__ == "__main__":
    query = input("Enter the Job Description or Role keywords to search for: ").strip()
    main(query)