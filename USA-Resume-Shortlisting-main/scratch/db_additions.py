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
        # Query search_history records for this mailbox
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
            .select("id, user_email, mailbox_account, job_description, batch_size, results_count, searched_at")
            
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
