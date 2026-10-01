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
        
    clean_mailbox = mailbox_account.strip().lower()
    clean_email = candidate_email.strip().lower()

    # Guard against duplicate insert within last 5 seconds
    cutoff_iso = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
    try:
        recent = client.table("copied_history") \
            .select("id") \
            .eq("mailbox_account", clean_mailbox) \
            .eq("candidate_email", clean_email) \
            .gte("copied_at", cutoff_iso) \
            .execute()
        if recent.data and len(recent.data) > 0:
            logging.info(f"[copy] Skipping duplicate insert for {clean_email} (inserted in last 5s)")
            return recent.data[0]["id"]
    except Exception as e:
        logging.warning(f"Error checking recent single copied_entry: {e}")

    payload = {
        "user_email": (user_email or "").strip().lower(),
        "mailbox_account": clean_mailbox,
        "candidate_email": clean_email,
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
        
    now_dt = datetime.now(timezone.utc)
    now_iso = now_dt.isoformat()
    clean_mailbox = mailbox_account.strip().lower()
    clean_user = (user_email or "").strip().lower()
    clean_jd = (job_description or "").strip()

    # 1. Deduplicate candidate emails within the input payload
    unique_candidates = {}
    for c in candidates:
        cand_email = (c.get('email') or c.get('candidate_email') or "").strip().lower()
        if cand_email and cand_email not in unique_candidates:
            unique_candidates[cand_email] = c

    if not unique_candidates:
        return 0

    # 2. Check recent inserts within last 5 seconds to prevent duplicate POST insertions
    cutoff_iso = (now_dt - timedelta(seconds=5)).isoformat()
    recent_emails = set()
    try:
        recent_res = client.table("copied_history") \
            .select("candidate_email") \
            .eq("mailbox_account", clean_mailbox) \
            .gte("copied_at", cutoff_iso) \
            .execute()
        if recent_res.data:
            for r in recent_res.data:
                em = (r.get("candidate_email") or "").strip().lower()
                if em:
                    recent_emails.add(em)
    except Exception as e:
        logging.warning(f"Failed to fetch recent copied_history check: {e}")

    rows = []
    for cand_email, c in unique_candidates.items():
        if cand_email in recent_emails:
            logging.info(f"[copied-history-bulk] Skipping duplicate recent insert for {cand_email}")
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
        logging.info("[copied-history-bulk] All candidates skipped due to recent duplicate insert guard.")
        return 0

    try:
        res = client.table("copied_history").insert(rows).execute()
        count = len(res.data) if res.data else 0
        logging.info(f"[copied-history-bulk] inserted={count} for mailbox={clean_mailbox}")
        return count
    except Exception as e:
        logging.error(f"Error saving bulk copied_history: {e}")
        return 0

def get_never_used_candidates_range(mailbox_account: str = None, from_date: str = None, to_date: str = None, days: int = 30) -> list:
    """
    Finds candidates seen in search_history over a date range (or last N days) who have NEVER been copied.
    """
    client = db.get_supabase()
    if not client:
        return []
        
    try:
        sh_query = client.table("search_history").select("job_description, candidates_seen, searched_at, mailbox_account")
        if mailbox_account:
            sh_query = sh_query.eq("mailbox_account", mailbox_account.strip().lower())

        if from_date:
            from_dt = f"{from_date}T00:00:00Z"
            sh_query = sh_query.gte("searched_at", from_dt)
        elif days:
            try:
                days_int = int(days)
            except (ValueError, TypeError):
                days_int = 30
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days_int)).isoformat()
            sh_query = sh_query.gte("searched_at", cutoff)

        if to_date:
            to_dt = f"{to_date}T23:59:59Z"
            sh_query = sh_query.lte("searched_at", to_dt)

        sh_query = sh_query.order("searched_at", desc=True).limit(500)
        sh_res = sh_query.execute()
        search_records = sh_res.data or []

        # 2. Query copied_history & candidate_status to get all used/copied emails
        ch_query = client.table("copied_history").select("candidate_email")
        if mailbox_account:
            ch_query = ch_query.eq("mailbox_account", mailbox_account.strip().lower())
            
        ch_res = ch_query.execute()
        copied_emails = set()
        for r in (ch_res.data or []):
            em = (r.get("candidate_email") or "").strip().lower()
            if em:
                copied_emails.add(em)

        try:
            cs_query = client.table("candidate_status").select("candidate_email").eq("status", "used")
            if mailbox_account:
                cs_query = cs_query.eq("mailbox_account", mailbox_account.strip().lower())
            cs_res = cs_query.execute()
            for r in (cs_res.data or []):
                em = (r.get("candidate_email") or "").strip().lower()
                if em:
                    copied_emails.add(em)
        except Exception as e_cs:
            logging.warning(f"Could not query candidate_status for never_used exclusion: {e_cs}")

        # 3. Deduplicate seen candidates not in copied_emails
        seen_dict = {}
        for rec in search_records:
            seen_list = rec.get("candidates_seen") or []
            searched_at = rec.get("searched_at")
            jd = rec.get("job_description") or ""
            mb = rec.get("mailbox_account") or mailbox_account or ""
            if not isinstance(seen_list, list):
                continue

            for c in seen_list:
                email = ""
                name = "Candidate"
                if isinstance(c, dict):
                    email = (c.get("Email") or c.get("email") or c.get("candidate_email") or "").strip().lower()
                    name = (c.get("Name") or c.get("name") or c.get("candidate_name") or "Candidate").strip()
                elif isinstance(c, str):
                    email = c.strip().lower()

                if not email or email == 'n/a' or email in copied_emails:
                    continue

                if email not in seen_dict:
                    seen_dict[email] = {
                        "candidate_email": email,
                        "candidate_name": name if name and name.upper() != 'N/A' else "Candidate",
                        "last_seen_at": searched_at,
                        "copied_at": searched_at,
                        "job_description": jd,
                        "mailbox_account": mb,
                        "status": "new",
                        "never_used": True
                    }

        entries = list(seen_dict.values())
        entries.sort(key=lambda x: x.get("last_seen_at") or "", reverse=True)
        return entries
    except Exception as e:
        logging.error(f"Error in get_never_used_candidates_range: {e}")
        return []

def get_never_used_candidates(mailbox_account: str = None, days: int = 30) -> list:
    """
    Finds candidates seen in search_history over the last N days who have NEVER been copied.
    """
    return get_never_used_candidates_range(mailbox_account=mailbox_account, days=days)

def get_summary(mailbox_account: str = None) -> dict:
    """
    Returns summary statistics for copied history (this_week, today, total, never_used).
    """
    client = db.get_supabase()
    if not client:
        return {"this_week": 0, "today": 0, "total": 0, "never_used": 0}
        
    try:
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        week_start = (now - timedelta(days=7)).isoformat()
        thirty_days_start = (now - timedelta(days=30)).isoformat()
        
        query = client.table("copied_history").select("id, candidate_email, copied_at")
        if mailbox_account:
            query = query.eq("mailbox_account", mailbox_account.strip().lower())
            
        res = query.execute()
        records = res.data or []
        
        seen_today = set()
        seen_week = set()
        seen_total = set()

        for r in records:
            cat = r.get("copied_at")
            em = (r.get("candidate_email") or "").strip().lower()
            if not em:
                em = str(r.get("id") or "")
            if cat:
                if cat >= thirty_days_start:
                    seen_total.add(em)
                if cat >= today_start:
                    seen_today.add(em)
                if cat >= week_start:
                    seen_week.add(em)

        never_used_list = get_never_used_candidates(mailbox_account=mailbox_account, days=30)
        never_used_cnt = len(never_used_list)
                    
        return {
            "this_week": len(seen_week),
            "today": len(seen_today),
            "total": len(seen_total),
            "never_used": never_used_cnt
        }
    except Exception as e:
        logging.error(f"Error in get_summary: {e}")
        return {"this_week": 0, "today": 0, "total": 0, "never_used": 0}

def get_copied_candidates_by_time_window(mailbox_account: str, job_query: str = "", time_window: str = "any", date_from: str = None, date_to: str = None, min_exp: float = None, gender_filter: str = "all") -> dict:
    """
    Queries copied_history table by copied_at timestamp for candidates copied in the specified date range.
    Does NOT query Gmail API or Gemini LLM.
    """
    client = db.get_supabase()
    now = datetime.now(timezone.utc)

    # 1. Compute date range for copied_at
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

    records = []
    if client:
        try:
            q = client.table("copied_history").select("id, user_email, mailbox_account, candidate_email, candidate_name, candidate_phone, job_description, copied_at, notes")
            if m_account:
                q = q.eq("mailbox_account", m_account)
            if from_dt:
                q = q.gte("copied_at", from_dt.isoformat())
            if to_dt:
                q = q.lte("copied_at", to_dt.isoformat())

            res = q.order("copied_at", desc=True).limit(500).execute()
            records = res.data or []
        except Exception as e:
            logging.error(f"Error querying copied_history in get_copied_candidates_by_time_window: {e}")

    # 2. Filter by job_query if provided
    filtered = []
    seen_emails = set()
    for r in records:
        r_jd = (r.get("job_description") or "").lower()
        if jq_clean:
            if jq_clean not in r_jd and r_jd not in jq_clean:
                words = [w for w in jq_clean.replace("and", " ").replace("or", " ").split() if len(w) > 2]
                if words and not any(w in r_jd for w in words):
                    continue

        em = (r.get("candidate_email") or "").strip().lower()
        if not em or em in seen_emails:
            continue
        seen_emails.add(em)

        c_at_str = (r.get("copied_at") or "")[:10]
        c_name = (r.get("candidate_name") or "").strip()
        cand = {
            "Rank": len(filtered) + 1,
            "Name": c_name if c_name else (em.split('@')[0].capitalize() if em else "N/A"),
            "Gender": r.get("gender") or r.get("Gender") or "N/A",
            "Email": r.get("candidate_email") or "N/A",
            "Phone": r.get("candidate_phone") or "N/A",
            "Experience": r.get("experience") or r.get("Experience") or "N/A",
            "Skill Set": r.get("job_description") or "N/A",
            "Matched Skills": r.get("matched_skills") or r.get("Matched Skills") or "N/A",
            "Match Score": "100%",
            "Match Reason": f"Copied on {c_at_str}",
            "copied_at": r.get("copied_at"),
            "Source": "copied_history"
        }
        filtered.append(cand)

    # 3. Filter by gender if specified
    if gender_filter and gender_filter != 'all':
        filtered = [c for c in filtered if (c.get("Gender") or "").strip().lower() == gender_filter.lower().strip()]

    # 4. Filter by min_exp
    if min_exp is not None:
        kept = []
        for c in filtered:
            yrs = db.parse_exp_years_helper(c.get("Experience"))
            c["experience_years"] = yrs
            if yrs is None or yrs >= min_exp:
                kept.append(c)
        filtered = kept

    for idx, c in enumerate(filtered):
        c["Rank"] = idx + 1

    return {
        "candidates": filtered,
        "total": len(filtered),
        "source": "copied_history",
        "date_field": "copied_at",
        "time_window": tw_clean,
        "explanation": "Candidates you copied in this window",
        "from_dt": from_dt.isoformat() if from_dt else None,
        "to_dt": to_dt.isoformat() if to_dt else None
    }

