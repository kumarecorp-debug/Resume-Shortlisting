import logging
from datetime import datetime, timedelta, timezone
import db

def save_copied_entry(user_email: str, mailbox_account: str, candidate_email: str, candidate_name: str = "", candidate_phone: str = "", job_description: str = "", notes: str = None) -> str:
    """
    Saves an entry into copied_history table. Returns generated UUID string or None.
    """
    if not candidate_email or not mailbox_account:
        return None
        
    client = db.get_supabase()
    if not client:
        return None
        
    payload = {
        "user_email": (user_email or "").strip().lower(),
        "mailbox_account": mailbox_account.strip().lower(),
        "candidate_email": candidate_email.strip().lower(),
        "candidate_name": (candidate_name or "").strip(),
        "candidate_phone": (candidate_phone or "").strip(),
        "job_description": (job_description or "").strip(),
        "copied_at": datetime.now(timezone.utc).isoformat(),
        "notes": notes
    }
    
    try:
        res = client.table("copied_history").insert(payload).execute()
        rec_id = res.data[0]["id"] if res.data else None
        logging.info(f"[copy] mailbox={mailbox_account} cand={candidate_email} jd={job_description} rec_id={rec_id}")
        return rec_id
    except Exception as e:
        logging.error(f"Error saving copied_history: {e}")
        return None

def fetch_copied_history(mailbox_account: str = None, user_email: str = None, from_date: str = None, to_date: str = None, days: int = 30) -> list:
    """
    Queries copied_history filtered by mailbox, date range, or default last N days.
    """
    client = db.get_supabase()
    if not client:
        return []
        
    try:
        query = client.table("copied_history").select("id, user_email, mailbox_account, candidate_email, candidate_name, candidate_phone, job_description, copied_at, notes")
        
        if mailbox_account:
            query = query.eq("mailbox_account", mailbox_account.strip().lower())
            
        if user_email:
            query = query.eq("user_email", user_email.strip().lower())
            
        if from_date:
            from_dt = f"{from_date}T00:00:00Z"
            query = query.gte("copied_at", from_dt)
            
        if to_date:
            to_dt = f"{to_date}T23:59:59Z"
            query = query.lte("copied_at", to_dt)
            
        if not from_date and not to_date and days:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            query = query.gte("copied_at", cutoff)
            
        query = query.order("copied_at", desc=True).limit(500)
        res = query.execute()
        return res.data or []
    except Exception as e:
        logging.error(f"Error querying copied_history: {e}")
        return []

def check_copies_for_search(mailbox_account: str, job_description: str) -> dict:
    """
    Checks if any candidates exist in copied_history for a given (mailbox_account, job_description).
    Returns dict:
    {
      "has_copies": bool,
      "copied_count": int,
      "candidate_emails": [...],
      "candidate_names": [...]
    }
    """
    if not mailbox_account or not job_description:
        return {"has_copies": False, "copied_count": 0, "candidate_emails": [], "candidate_names": []}
        
    client = db.get_supabase()
    if not client:
        return {"has_copies": False, "copied_count": 0, "candidate_emails": [], "candidate_names": []}
        
    try:
        clean_mailbox = mailbox_account.strip().lower()
        clean_jd = job_description.strip().lower()
        
        # Query copied_history for matching mailbox
        res = client.table("copied_history") \
            .select("candidate_email, candidate_name, job_description") \
            .eq("mailbox_account", clean_mailbox) \
            .execute()
            
        data = res.data or []
        # Filter in Python by matching job_description (case-insensitive)
        matched = [c for c in data if (c.get("job_description") or "").strip().lower() == clean_jd]
        
        # Deduplicate candidates by email
        unique_cands = {}
        for c in matched:
            em = (c.get("candidate_email") or "").strip().lower()
            if em and em not in unique_cands:
                unique_cands[em] = c.get("candidate_name") or "Candidate"
                
        emails = list(unique_cands.keys())
        names = list(unique_cands.values())
        
        has_copies = len(emails) > 0
        return {
            "has_copies": has_copies,
            "copied_count": len(emails),
            "candidate_emails": emails,
            "candidate_names": names
        }
    except Exception as e:
        logging.error(f"Error in check_copies_for_search: {e}")
        return {"has_copies": False, "copied_count": 0, "candidate_emails": [], "candidate_names": []}

def save_bulk_copied_entries(user_email: str, mailbox_account: str, candidates: list, job_description: str = "") -> int:
    """
    Saves multiple entries into copied_history table in a single batch insert.
    Returns count of inserted rows.
    """
    if not mailbox_account or not candidates:
        return 0
        
    client = db.get_supabase()
    if not client:
        return 0
        
    now_iso = datetime.now(timezone.utc).isoformat()
    clean_mailbox = mailbox_account.strip().lower()
    clean_user = (user_email or "").strip().lower()
    clean_jd = (job_description or "").strip()

    rows = []
    for c in candidates:
        cand_email = (c.get('email') or c.get('candidate_email') or "").strip().lower()
        if not cand_email:
            continue
        rows.append({
            "user_email": clean_user,
            "mailbox_account": clean_mailbox,
            "candidate_email": cand_email,
            "candidate_name": (c.get('name') or c.get('candidate_name') or "").strip(),
            "candidate_phone": (c.get('phone') or c.get('candidate_phone') or "").strip(),
            "job_description": clean_jd,
            "copied_at": now_iso
        })

    if not rows:
        return 0

    try:
        res = client.table("copied_history").insert(rows).execute()
        count = len(res.data) if res.data else 0
        logging.info(f"[copied-history-bulk] inserted={count} for mailbox={clean_mailbox}")
        return count
    except Exception as e:
        logging.error(f"Error saving bulk copied_history: {e}")
        return 0

def get_summary(mailbox_account: str = None) -> dict:
    """
    Returns summary statistics for copied history (this_week, today, total).
    """
    client = db.get_supabase()
    if not client:
        return {"this_week": 0, "today": 0, "total": 0}
        
    try:
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        week_start = (now - timedelta(days=7)).isoformat()
        
        query = client.table("copied_history").select("id, copied_at")
        if mailbox_account:
            query = query.eq("mailbox_account", mailbox_account.strip().lower())
            
        res = query.execute()
        records = res.data or []
        
        total = len(records)
        today_cnt = 0
        week_cnt = 0
        
        for r in records:
            cat = r.get("copied_at")
            if cat:
                if cat >= today_start:
                    today_cnt += 1
                if cat >= week_start:
                    week_cnt += 1
                    
        return {
            "this_week": week_cnt,
            "today": today_cnt,
            "total": total
        }
    except Exception as e:
        logging.error(f"Error in get_summary: {e}")
        return {"this_week": 0, "today": 0, "total": 0}
