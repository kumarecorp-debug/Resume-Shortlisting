import os
import logging
import hashlib
from datetime import datetime, timedelta, timezone
try:
    from supabase import create_client, Client
    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False
    Client = None

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://fvbctgxwjrctcssckggp.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_ANON_KEY") or os.environ.get("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImZ2YmN0Z3h3anJjdGNzc2NrZ2dwIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTAxNDc1MDUsImV4cCI6MjEwNTcyMzUwNX0.Nz0G-FmUDvzKOVTmIhu8EFpYjH5EDjZO-JuSwylRCVU")

_supabase_client = None

def get_supabase() -> Client:
    global _supabase_client
    if _supabase_client is not None:
        return _supabase_client
    if not SUPABASE_AVAILABLE:
        logging.warning("Supabase SDK is not installed.")
        return None
    try:
        _supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
        return _supabase_client
    except Exception as e:
        logging.error(f"Failed to initialize Supabase client in db.py: {e}")
        return None

# ============================================================
# FEATURE 3: CANDIDATE STATUS TRACKING
# ============================================================
def get_candidate_statuses(mailbox_account: str, candidate_emails: list) -> dict:
    """
    Returns a dict mapping candidate_email -> status ('new', 'used', 'skipped')
    """
    if not candidate_emails or not mailbox_account:
        return {}
    client = get_supabase()
    if not client:
        return {}
    
    clean_emails = [e.strip().lower() for e in candidate_emails if e and str(e).strip().lower() != 'n/a']
    if not clean_emails:
        return {}
        
    try:
        res = client.table("candidate_status") \
            .select("candidate_email, status") \
            .eq("mailbox_account", mailbox_account.lower().strip()) \
            .in_("candidate_email", clean_emails) \
            .execute()
        
        status_map = {}
        if res.data:
            for row in res.data:
                em = row.get("candidate_email", "").lower().strip()
                st = row.get("status", "new")
                if em:
                    status_map[em] = st
        return status_map
    except Exception as e:
        logging.warning(f"Error fetching candidate statuses from Supabase: {e}")
        return {}

def update_candidate_status(mailbox_account: str, candidate_email: str, candidate_name: str = "", status: str = "used", notes: str = None) -> bool:
    """
    Upserts candidate status into 'candidate_status' table.
    """
    client = get_supabase()
    if not client:
        return False
        
    if not mailbox_account or not candidate_email:
        return False
        
    m_account = mailbox_account.lower().strip()
    c_email = candidate_email.lower().strip()
    c_status = status.lower().strip() if status in ["new", "used", "skipped"] else "used"
    c_name = candidate_name.strip() if candidate_name else ""
    
    payload = {
        "mailbox_account": m_account,
        "candidate_email": c_email,
        "candidate_name": c_name,
        "status": c_status,
        "marked_at": datetime.now(timezone.utc).isoformat(),
        "notes": notes
    }
    
    try:
        client.table("candidate_status").upsert(payload, on_conflict="mailbox_account,candidate_email").execute()
        logging.info(f"Successfully updated candidate status for {c_email} -> {c_status}")
        return True
    except Exception as e:
        logging.error(f"Error updating candidate status for {c_email}: {e}")
        return False

def bulk_update_candidate_status(mailbox_account: str, candidates: list, status: str) -> int:
    """
    Bulk upserts candidate statuses for a list of candidates [{email, name}, ...]
    """
    client = get_supabase()
    if not client or not candidates or not mailbox_account:
        return 0
        
    m_account = mailbox_account.lower().strip()
    c_status = status.lower().strip() if status in ["new", "used", "skipped"] else "used"
    now_iso = datetime.now(timezone.utc).isoformat()
    
    payloads = []
    for cand in candidates:
        if isinstance(cand, dict):
            em = cand.get("email") or cand.get("candidate_email", "")
            nm = cand.get("name") or cand.get("candidate_name", "")
        else:
            em = str(cand)
            nm = ""
            
        em = em.lower().strip()
        if em and em != 'n/a':
            payloads.append({
                "mailbox_account": m_account,
                "candidate_email": em,
                "candidate_name": nm,
                "status": c_status,
                "marked_at": now_iso
            })
            
    if not payloads:
        return 0
        
    try:
        client.table("candidate_status").upsert(payloads, on_conflict="mailbox_account,candidate_email").execute()
        logging.info(f"Bulk updated {len(payloads)} candidates to status '{c_status}'")
        return len(payloads)
    except Exception as e:
        logging.error(f"Error bulk updating candidate status: {e}")
        return 0
