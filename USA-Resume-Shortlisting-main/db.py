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
    c_status = status.lower().strip() if status in ["new", "used", "not_used"] else "used"
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
    c_status = status.lower().strip() if status in ["new", "used", "not_used"] else "used"
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

# ============================================================
# FEATURE 1: SEARCH HISTORY (LAST 30 DAYS & CALENDAR PICKER)
# ============================================================
def save_search_history(user_email: str, mailbox_account: str, job_description: str, batch_size: int, results_count: int, candidates_seen: list = None) -> str:
    """
    Inserts a row into search_history table and returns the generated UUID.
    """
    client = get_supabase()
    if not client:
        return None
        
    u_email = user_email.strip().lower() if user_email else "user@ecorptrainings.com"
    m_account = mailbox_account.strip().lower() if mailbox_account else "recruiter@ecorptrainings.com"
    j_desc = job_description.strip() if job_description else ""
    c_list = candidates_seen if isinstance(candidates_seen, list) else []
    
    payload = {
        "user_email": u_email,
        "mailbox_account": m_account,
        "job_description": j_desc,
        "batch_size": int(batch_size or 25),
        "results_count": int(results_count or 0),
        "searched_at": datetime.now(timezone.utc).isoformat(),
        "candidates_seen": c_list
    }
    
    try:
        res = client.table("search_history").insert(payload).execute()
        if res.data and len(res.data) > 0:
            rec_id = res.data[0].get("id")
            logging.info(f"Saved search_history record: {rec_id} ({results_count} results)")
            return rec_id
        return None
    except Exception as e:
        logging.error(f"Error saving search_history: {e}")
        return None

def get_search_history(user_email: str = None, mailbox_account: str = None, from_date: str = None, to_date: str = None, days: int = 30) -> list:
    """
    Queries search_history filtered by date range or default (last N days).
    from_date / to_date are strings formatted 'YYYY-MM-DD'.
    """
    client = get_supabase()
    if not client:
        return []
        
    try:
        query = client.table("search_history").select("id, user_email, mailbox_account, job_description, batch_size, results_count, searched_at")
        
        if mailbox_account:
            query = query.eq("mailbox_account", mailbox_account.strip().lower())
            
        has_date_filter = False
        if from_date:
            try:
                # Convert 'YYYY-MM-DD 00:00:00' in local time to UTC ISO string for DB filter
                dt_from_local = datetime.strptime(from_date, "%Y-%m-%d")
                dt_from_utc = dt_from_local.astimezone(timezone.utc)
                query = query.gte("searched_at", dt_from_utc.isoformat())
                has_date_filter = True
            except ValueError:
                pass
                
        if to_date:
            try:
                # Convert 'YYYY-MM-DD 23:59:59' in local time to UTC ISO string for DB filter
                dt_to_local = datetime.strptime(to_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
                dt_to_utc = dt_to_local.astimezone(timezone.utc)
                query = query.lte("searched_at", dt_to_utc.isoformat())
                has_date_filter = True
            except ValueError:
                pass
                
        if not has_date_filter:
            try:
                cutoff = datetime.now(timezone.utc) - timedelta(days=days)
                query = query.gte("searched_at", cutoff.isoformat())
            except Exception:
                pass
                
        res = query.order("searched_at", desc=True).limit(200).execute()
        return res.data or []
    except Exception as e:
        logging.error(f"Error querying search_history: {e}")
        return []

def get_search_history_item(search_id: str) -> dict:
    """
    Fetches a single search_history record by ID including candidates_seen.
    """
    client = get_supabase()
    if not client or not search_id:
        return None
        
    try:
        res = client.table("search_history").select("*").eq("id", search_id).execute()
        if res.data and len(res.data) > 0:
            return res.data[0]
        return None
    except Exception as e:
        logging.error(f"Error fetching search_history item {search_id}: {e}")
        return None

def get_latest_search_history(mailbox_account: str, job_description: str) -> dict:
    """
    Finds the most recent search in search_history with matching mailbox_account
    and job_description (case-insensitive, trimmed).
    Returns dict or None.
    """
    client = get_supabase()
    if not client or not mailbox_account or not job_description:
        return None
        
    m_account = mailbox_account.strip().lower()
    j_desc = job_description.strip().lower()
    
    try:
        res = client.table("search_history") \
            .select("id, user_email, mailbox_account, job_description, batch_size, results_count, candidates_seen, searched_at") \
            .eq("mailbox_account", m_account) \
            .order("searched_at", desc=True) \
            .limit(100) \
            .execute()
            
        records = res.data or []
        for rec in records:
            rec_jd = (rec.get("job_description") or "").strip().lower()
            if rec_jd == j_desc:
                return rec
        return None
    except Exception as e:
        logging.error(f"Error in get_latest_search_history: {e}")
        return None

def get_recent_unique_searches(mailbox_account: str = None, limit: int = 10) -> list:
    """
    Returns the top N most recent unique JDs from search_history for a mailbox.
    """
    client = get_supabase()
    if not client:
        return []
        
    try:
        query = client.table("search_history") \
            .select("id, user_email, mailbox_account, job_description, batch_size, results_count, candidates_seen, searched_at")
            
        if mailbox_account:
            query = query.eq("mailbox_account", mailbox_account.strip().lower())
            
        res = query.order("searched_at", desc=True).limit(100).execute()
        records = res.data or []
        
        seen_jds = set()
        unique_list = []
        for rec in records:
            jd = (rec.get("job_description") or "").strip()
            if not jd:
                continue
            jd_key = jd.lower()
            if jd_key not in seen_jds:
                seen_jds.add(jd_key)
                unique_list.append(rec)
                if len(unique_list) >= limit:
                    break
                    
        return unique_list
    except Exception as e:
        logging.error(f"Error in get_recent_unique_searches: {e}")
        return []

# ============================================================
# SEARCH CACHE FOR PAGINATION (1 HOUR TTL)
# ============================================================
_IN_MEMORY_SEARCH_CACHE = {}

def cache_search_results(search_id: str, results: list) -> str:
    """
    Caches search results list in memory and Supabase search_cache table.
    """
    import uuid
    if not search_id:
        search_id = str(uuid.uuid4())
        
    now_dt = datetime.now(timezone.utc)
    _IN_MEMORY_SEARCH_CACHE[search_id] = {
        "results": results,
        "created_at": now_dt
    }
    
    # Try persisting to Supabase search_cache table if present
    client = get_supabase()
    if client:
        try:
            payload = {
                "id": search_id,
                "results": results,
                "created_at": now_dt.isoformat()
            }
            client.table("search_cache").upsert(payload).execute()
            # Cleanup rows older than 1 hour
            cutoff = (now_dt - timedelta(hours=1)).isoformat()
            client.table("search_cache").delete().lt("created_at", cutoff).execute()
        except Exception as e:
            logging.debug(f"Note on Supabase search_cache upsert: {e}")
            
    return search_id

def get_cached_results(search_id: str, offset: int = 0, limit: int = 25) -> dict:
    """
    Retrieves slice of search results from cache (in-memory or Supabase).
    Returns dict: {'results': [...], 'total': N, 'expired': bool}
    """
    if not search_id:
        return {'results': [], 'total': 0, 'expired': True}
        
    now_dt = datetime.now(timezone.utc)
    
    # 1. Check in-memory cache
    if search_id in _IN_MEMORY_SEARCH_CACHE:
        item = _IN_MEMORY_SEARCH_CACHE[search_id]
        if now_dt - item["created_at"] < timedelta(hours=1):
            full_list = item["results"]
            sliced = full_list[offset:offset + limit]
            return {'results': sliced, 'total': len(full_list), 'expired': False}
        else:
            del _IN_MEMORY_SEARCH_CACHE[search_id]
            
    # 2. Check Supabase search_cache table
    client = get_supabase()
    if client:
        try:
            res = client.table("search_cache").select("results, created_at").eq("id", search_id).execute()
            if res.data and len(res.data) > 0:
                rec = res.data[0]
                c_at_str = rec.get("created_at")
                c_at = datetime.fromisoformat(c_at_str.replace("Z", "+00:00")) if c_at_str else now_dt
                if now_dt - c_at < timedelta(hours=1):
                    full_list = rec.get("results", [])
                    _IN_MEMORY_SEARCH_CACHE[search_id] = {"results": full_list, "created_at": c_at}
                    sliced = full_list[offset:offset + limit]
                    return {'results': sliced, 'total': len(full_list), 'expired': False}
        except Exception as e:
            logging.debug(f"Note on Supabase search_cache query: {e}")
            
    return {'results': [], 'total': 0, 'expired': True}

def get_table_debug_status() -> dict:
    """
    Returns table existence status and row counts for troubleshooting.
    """
    client = get_supabase()
    tables = ["candidate_status", "search_history", "search_cache"]
    result = {
        "supabase_configured": bool(client),
        "supabase_url": SUPABASE_URL,
        "tables": {}
    }
    
    if not client:
        for t in tables:
            result["tables"][t] = {"exists": False, "row_count": 0, "error": "Supabase client uninitialized"}
        return result
        
    for t in tables:
        try:
            res = client.table(t).select("id", count="exact").limit(1).execute()
            row_count = res.count if hasattr(res, 'count') and res.count is not None else len(res.data or [])
            result["tables"][t] = {
                "exists": True,
                "row_count": row_count,
                "error": None
            }
        except Exception as e:
            result["tables"][t] = {
                "exists": False,
                "row_count": 0,
                "error": str(e)
            }
            
    return result
