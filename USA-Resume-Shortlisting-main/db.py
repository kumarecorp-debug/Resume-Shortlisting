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

def parse_exp_years_helper(exp_str):
    if not exp_str or exp_str == "N/A":
        return None
    try:
        import re
        m = re.search(r'(\d+(?:\.\d+)?)', str(exp_str))
        if m:
            return float(m.group(1))
    except Exception:
        pass
    return None

def guess_gender(name):
    if not name or str(name).strip().lower() in ['verified candidate', 'candidate', 'n/a', '']:
        return 'Male'
    parts = str(name).strip().split()
    if not parts:
        return 'Male'
    first_name = parts[0].capitalize()
    first_name_lower = first_name.lower()
    female_names = {
        'pooja', 'priya', 'neha', 'anjali', 'swati', 'divya', 'kavita', 'deepa', 'megha', 'shweta',
        'sunita', 'anita', 'kiran', 'rekha', 'rashmi', 'sneha', 'jyoti', 'monika', 'payal', 'richa',
        'sonam', 'smita', 'bhavna', 'sapna', 'archana', 'simran', 'preeti', 'renu', 'seema', 'tanvi',
        'radha', 'sheetal', 'harshita', 'apoorva', 'srishti', 'kriti', 'nisha', 'sakshi', 'shikha',
        'shipra', 'garima', 'pallavi', 'surabhi', 'saloni', 'sonia', 'vandana', 'komal', 'namrata',
        'meena', 'savita', 'sarita', 'lata', 'usha', 'geeta', 'suman', 'mona', 'reena',
        'babita', 'sangita', 'namita', 'lalita'
    }
    male_exceptions = {
        'karan', 'bhavin', 'gulab', 'sudhakar', 'nagarjuna', 'krishna', 'rama', 'aditya', 'surya',
        'shiva', 'pavan', 'vijay', 'ajay', 'sanjay', 'jay', 'rahul', 'amit', 'sumit', 'vince',
        'anil', 'sunil', 'rajesh', 'suresh', 'ramesh', 'dinesh', 'manish', 'mukesh', 'nilesh',
        'gopal', 'mohan', 'sohan', 'rohan', 'varun', 'tarun', 'arun', 'alok', 'ashok', 'fateh', 'navneet',
        'vikrant', 'dorababu', 'ravikumar', 'tamilamuthan'
    }
    if first_name_lower in female_names:
        return 'Female'
    if first_name_lower in male_exceptions:
        return 'Male'
    try:
        import gender_guesser.detector as gender
        detector = gender.Detector()
        gen = detector.get_gender(first_name)
        if gen in ['male', 'mostly_male']: return 'Male'
        if gen in ['female', 'mostly_female']: return 'Female'
    except Exception:
        pass
    if first_name_lower.endswith(('a', 'i')) and len(first_name_lower) > 3:
        return 'Female'
    return 'Male'

def search_candidates_from_history(mailbox_account: str, job_query: str = "", time_window: str = "any", date_from: str = None, date_to: str = None, show_mode: str = "all", min_exp: float = None, gender_filter: str = "all") -> dict:
    """
    Queries search_history and copied_history tables in Supabase for candidate resumes
    previously searched or saved within the specified time window.
    Does NOT invoke Gmail or Gemini API calls.
    """
    client = get_supabase()
    now = datetime.now(timezone.utc)

    # 1. Compute date range
    from_dt, to_dt = None, None
    tw_clean = (time_window or "any").lower().strip()
    if tw_clean == 'today':
        from_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
        to_dt = now
    elif tw_clean == 'yesterday':
        from_dt = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        to_dt = (now - timedelta(days=1)).replace(hour=23, minute=59, second=59, microsecond=999999)
    elif tw_clean == '7d':
        from_dt = now - timedelta(days=7)
        to_dt = now
    elif tw_clean == '14d':
        from_dt = now - timedelta(days=14)
        to_dt = now
    elif tw_clean == '30d':
        from_dt = now - timedelta(days=30)
        to_dt = now
    elif tw_clean == 'custom':
        if date_from:
            try:
                from_dt = datetime.strptime(date_from.strip(), "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except Exception:
                pass
        if date_to:
            try:
                to_dt = datetime.strptime(date_to.strip(), "%Y-%m-%d").replace(hour=23, minute=59, second=59, microsecond=999999, tzinfo=timezone.utc)
            except Exception:
                pass

    m_account = mailbox_account.lower().strip() if mailbox_account else ""
    jq_clean = job_query.strip().lower() if job_query else ""

    searches = []
    if client:
        try:
            q = client.table("search_history").select("candidates_seen, searched_at, job_description, mailbox_account")
            if m_account:
                q = q.eq("mailbox_account", m_account)
            if from_dt:
                q = q.gte("searched_at", from_dt.isoformat())
            if to_dt:
                q = q.lte("searched_at", to_dt.isoformat())

            res = q.order("searched_at", desc=True).limit(200).execute()
            searches = res.data or []
        except Exception as e:
            logging.error(f"Error querying search_history in search_candidates_from_history: {e}")

    # 2. Filter searches by job_query if provided
    filtered_searches = []
    for s in searches:
        s_jd = (s.get("job_description") or "").lower()
        if not jq_clean:
            filtered_searches.append(s)
        elif jq_clean in s_jd or s_jd in jq_clean:
            filtered_searches.append(s)
        else:
            words = [w for w in jq_clean.replace("and", " ").replace("or", " ").split() if len(w) > 2]
            if words and any(w in s_jd for w in words):
                filtered_searches.append(s)

    # Build candidate enrichment lookup map
    lookup = {}
    try:
        import pandas as pd
        for csv_path in [
            os.path.join(os.path.dirname(__file__), "Resumes", "resume_analysis.csv"),
            os.path.join(os.getcwd(), "Resumes", "resume_analysis.csv"),
            os.path.join(os.getcwd(), "resume_analysis.csv")
        ]:
            if os.path.exists(csv_path):
                try:
                    df_csv = pd.read_csv(csv_path)
                    for _, row in df_csv.iterrows():
                        em = str(row.get("Email") or "").strip().lower()
                        if em and em != "n/a":
                            if em not in lookup: lookup[em] = {}
                            ph = str(row.get("Phone") or "").strip()
                            exp = str(row.get("Experience") or "").strip()
                            nm = str(row.get("Name") or "").strip()
                            gen = str(row.get("Gender") or "").strip()
                            sk = str(row.get("Skill Set") or "").strip()
                            if ph and ph not in ["N/A", "nan", ""]: lookup[em]["Phone"] = ph
                            if exp and exp not in ["N/A", "nan", ""]: lookup[em]["Experience"] = exp
                            if nm and nm not in ["N/A", "nan", ""]: lookup[em]["Name"] = nm
                            if gen and gen not in ["N/A", "nan", "Unknown", ""]: lookup[em]["Gender"] = gen
                            if sk and sk not in ["N/A", "nan", ""]: lookup[em]["Skill Set"] = sk
                except Exception:
                    pass
    except Exception:
        pass

    if client:
        try:
            q_ch = client.table("copied_history").select("candidate_email, candidate_name, candidate_phone, job_description")
            if m_account:
                q_ch = q_ch.eq("mailbox_account", m_account)
            ch_res = q_ch.limit(1000).execute()
            for ch in (ch_res.data or []):
                em = (ch.get("candidate_email") or "").strip().lower()
                if em and em != "n/a":
                    if em not in lookup: lookup[em] = {}
                    ph = (ch.get("candidate_phone") or "").strip()
                    nm = (ch.get("candidate_name") or "").strip()
                    if ph and ph != "N/A": lookup[em]["Phone"] = ph
                    if nm and nm != "N/A": lookup[em]["Name"] = nm
        except Exception as e_ch:
            logging.warning(f"Error reading copied_history enrichment: {e_ch}")

        try:
            for row in searches:
                seen = row.get("candidates_seen") or []
                if isinstance(seen, list):
                    for item in seen:
                        if isinstance(item, dict):
                            em = (item.get("email") or item.get("Email") or "").strip().lower()
                            if em and em != "n/a":
                                if em not in lookup: lookup[em] = {}
                                ph = (item.get("phone") or item.get("Phone") or "").strip()
                                exp = (item.get("experience") or item.get("Experience") or "").strip()
                                nm = (item.get("name") or item.get("Name") or "").strip()
                                gen = (item.get("gender") or item.get("Gender") or "").strip()
                                sk = (item.get("skills") or item.get("Skill Set") or "").strip()
                                if ph and ph != "N/A": lookup[em]["Phone"] = ph
                                if exp and exp != "N/A": lookup[em]["Experience"] = exp
                                if nm and nm != "N/A": lookup[em]["Name"] = nm
                                if gen and gen not in ["N/A", "Unknown", ""]: lookup[em]["Gender"] = gen
                                if sk and sk != "N/A": lookup[em]["Skill Set"] = sk
        except Exception as e_sh:
            logging.warning(f"Error reading search_history enrichment: {e_sh}")

    # 3. Flatten candidates_seen
    candidates_by_email = {}
    for s in filtered_searches:
        c_list = s.get("candidates_seen") or []
        s_date_str = (s.get("searched_at") or "")[:10]
        for c in c_list:
            if isinstance(c, str):
                em = c.strip().lower()
                if not em or em == 'n/a': continue
                c_name = em.split('@')[0].capitalize()
                cand = {
                    "Name": c_name,
                    "Gender": guess_gender(c_name),
                    "Email": c.strip(),
                    "Phone": "N/A",
                    "Experience": "N/A",
                    "Skill Set": s.get("job_description") or "N/A",
                    "Matched Skills": s.get("job_description") or "N/A",
                    "Match Score": "85",
                    "Match Reason": f"From search on {s_date_str}"
                }
            elif isinstance(c, dict):
                em = (c.get("email") or c.get("Email") or "").strip().lower()
                nm = (c.get("name") or c.get("Name") or "").strip()
                if not em or em == 'n/a':
                    if not nm: continue
                    em = f"noemail_{nm.lower()}"

                c_name = nm if nm else (em.split('@')[0].capitalize() if em and '@' in em else "N/A")
                c_gender = c.get("gender") or c.get("Gender") or "N/A"
                if not c_gender or str(c_gender).strip().upper() in ['N/A', 'UNKNOWN', '']:
                    c_gender = guess_gender(c_name)

                c_score = str(c.get("match_score") or c.get("Match Score") or "85").replace("%", "").strip()
                if not c_score: c_score = "85"

                c_exp = c.get("experience") or c.get("Experience") or "N/A"
                c_skills = c.get("skills") or c.get("Skill Set") or s.get("job_description") or "N/A"
                c_matched = c.get("matched_skills") or c.get("Matched Skills") or "N/A"
                if c_matched == "N/A" and c_skills != "N/A":
                    c_matched = c_skills

                cand = {
                    "Name": c_name,
                    "Gender": c_gender,
                    "Email": c.get("email") or c.get("Email") or "N/A",
                    "Phone": c.get("phone") or c.get("Phone") or "N/A",
                    "Experience": c_exp,
                    "Skill Set": c_skills,
                    "Matched Skills": c_matched,
                    "Match Score": c_score,
                    "Match Reason": c.get("match_reason") or c.get("Match Reason") or f"From search on {s_date_str}"
                }
            else:
                continue

            # Enrich from lookup map
            em_key = em.lower().strip()
            if em_key in lookup:
                info = lookup[em_key]
                if (not cand.get("Phone") or cand.get("Phone") == "N/A") and info.get("Phone"):
                    cand["Phone"] = info["Phone"]
                if (not cand.get("Experience") or cand.get("Experience") in ["N/A", "?", ""]) and info.get("Experience"):
                    cand["Experience"] = info["Experience"]
                if (not cand.get("Name") or cand.get("Name") in ["N/A", ""] or cand.get("Name") == em_key.split('@')[0].capitalize()) and info.get("Name"):
                    cand["Name"] = info["Name"]
                if (not cand.get("Gender") or cand.get("Gender") in ["N/A", "Unknown", ""]) and info.get("Gender"):
                    cand["Gender"] = info["Gender"]
                if (not cand.get("Skill Set") or cand.get("Skill Set") == "N/A") and info.get("Skill Set"):
                    cand["Skill Set"] = info["Skill Set"]

            if em and em not in candidates_by_email:
                candidates_by_email[em] = cand
            elif em and em in candidates_by_email:
                existing = candidates_by_email[em]
                for key in ["Phone", "Experience", "Name", "Gender", "Skill Set"]:
                    if (not existing.get(key) or existing.get(key) in ["N/A", "?"]) and cand.get(key) and cand.get(key) not in ["N/A", "?"]:
                        existing[key] = cand[key]

    candidates = list(candidates_by_email.values())

    # Populate experience_years for all candidates
    for c in candidates:
        yrs = parse_exp_years_helper(c.get("Experience"))
        c["experience_years"] = yrs
        c["experience_unknown"] = (yrs is None and c.get("Experience") in ['N/A', 'Unknown', ''])

    # 4. Filter by Show mode (copied / not_copied / all)
    sm_clean = (show_mode or "all").lower().strip()
    if sm_clean in ['copied', 'not_copied'] and client and m_account:
        try:
            copied_res = client.table("copied_history").select("candidate_email").eq("mailbox_account", m_account).execute()
            copied_emails = {
                (r.get("candidate_email") or "").strip().lower()
                for r in (copied_res.data or [])
                if r.get("candidate_email")
            }
            if sm_clean == 'not_copied':
                candidates = [c for c in candidates if c.get("Email", "").strip().lower() not in copied_emails]
            elif sm_clean == 'copied':
                candidates = [c for c in candidates if c.get("Email", "").strip().lower() in copied_emails]
        except Exception as e_cop:
            logging.error(f"Error checking copied_history in history search: {e_cop}")

    # 5. Filter by gender
    if gender_filter and gender_filter != 'all':
        candidates = [c for c in candidates if (c.get("Gender") or "").strip().lower() == gender_filter.lower().strip()]

    # 6. Filter by min_exp
    if min_exp is not None:
        candidates = [c for c in candidates if c.get("experience_years") is None or c.get("experience_years") >= min_exp]

    # 7. Add Rank
    for idx, c in enumerate(candidates):
        c["Rank"] = idx + 1

    return {
        "candidates": candidates,
        "total": len(candidates),
        "source": "search_history",
        "time_window": tw_clean,
        "from_dt": from_dt.isoformat() if from_dt else None,
        "to_dt": to_dt.isoformat() if to_dt else None
    }

