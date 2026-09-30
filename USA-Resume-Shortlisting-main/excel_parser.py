import os
import time
import logging
import pandas as pd

logger = logging.getLogger(__name__)

# Column aliases — map friendly names to internal field names
COLUMN_ALIASES = {
    'name': [
        'name', 'full name', 'fullname', 'candidate name',
        'trainer', 'trainer name', 'candidate', 'consultant name',
    ],
    'email': [
        'email', 'email id', 'e-mail', 'mail', 'mail id',
        'email address', 'e mail', 'emailid',
    ],
    'phone': [
        'phone', 'phone number', 'phone no', 'mobile', 'mobile no',
        'mobile number', 'contact', 'contact number', 'contact no',
        'ph', 'cell', 'cell number',
    ],
    'skills': [
        'skills', 'skill', 'skill set', 'skillset', 'skill-set',
        'technologies', 'technology', 'tech stack', 'primary skills',
        'primary skill', 'key skills', 'core skills', 'expertise',
    ],
    'experience': [
        'experience', 'exp', 'exp.', 'years of experience',
        'total experience', 'total exp', 'yrs', 'year(s)',
        'exp in years', 'experience (years)',
    ],
}

# 10-minute in-memory cache: (file_path, mtime) -> (timestamp, candidates)
_EXCEL_CACHE = {}

def _normalize_columns(df):
    """Return a dict mapping internal field -> actual column name."""
    cols_clean = [str(c).strip().lower() for c in df.columns]
    df.columns = cols_clean
    col_map = {}
    for field, aliases in COLUMN_ALIASES.items():
        # exact match first
        match = None
        for alias in aliases:
            if alias in df.columns:
                match = alias
                break
        # fallback: substring match
        if not match:
            for col in df.columns:
                for alias in aliases:
                    if alias in col:
                        match = col
                        break
                if match:
                    break
        col_map[field] = match
    return col_map

def parse_excel_to_candidates(file_path, max_rows=500):
    """
    Read an Excel file. Return a list of candidate dicts.
    Each row = one candidate.
    
    Handles:
    - xlsx via openpyxl
    - xls via xlrd / default pandas engine
    - multiple sheets (all merged)
    """
    if not os.path.exists(file_path):
        logger.warning(f"[excel] file not found: {file_path}")
        return []

    try:
        mtime = os.path.getmtime(file_path)
        cache_key = (file_path, mtime)
        now = time.time()
        if cache_key in _EXCEL_CACHE:
            ts, cached_cands = _EXCEL_CACHE[cache_key]
            if now - ts < 600: # 10 minutes cache
                logger.info(f"[excel] Returning cached {len(cached_cands)} candidates for {file_path}")
                return cached_cands
    except Exception:
        pass

    logger.info(f"[excel] parsing {file_path}")

    all_rows = []
    try:
        # Read all sheets
        is_xlsx = file_path.lower().endswith('.xlsx')
        engine = 'openpyxl' if is_xlsx else None
        
        sheets = pd.read_excel(
            file_path,
            sheet_name=None,
            engine=engine,
            dtype=str,
        )
        for sheet_name, df in sheets.items():
            if df.empty:
                continue
            df['__sheet__'] = sheet_name
            all_rows.append(df)
    except Exception as e:
        logger.error(f"[excel] failed to read {file_path}: {e}")
        return []

    if not all_rows:
        return []

    df = pd.concat(all_rows, ignore_index=True)

    # Cap rows
    if len(df) > max_rows:
        logger.info(f"[excel] {file_path} has {len(df)} rows, capping to {max_rows}")
        df = df.head(max_rows)

    col_map = _normalize_columns(df)
    logger.info(f"[excel] {file_path} column mapping: {col_map}")

    candidates = []
    for idx, row in df.iterrows():
        def get(field):
            col = col_map.get(field)
            if not col:
                return ''
            val = row.get(col, '')
            if pd.isna(val):
                return ''
            return str(val).strip()

        cand_name = get('name')
        cand_email = get('email')
        cand_phone = get('phone')
        cand_skills = get('skills')
        cand_exp = get('experience')

        cand = {
            'Name': cand_name,
            'Email': cand_email,
            'Phone': cand_phone,
            'Skill Set': cand_skills,
            'skills': cand_skills,
            'Experience': f"{cand_exp} yrs" if cand_exp and 'yr' not in cand_exp.lower() else (cand_exp or 'N/A'),
            'experience': cand_exp,
            'source': 'excel',
            'source_file': os.path.basename(file_path),
            'source_sheet': str(row.get('__sheet__', 'Sheet1')),
            'source_row': int(idx) + 2, # +2 accounts for header
        }

        # Keep only rows with SOME data
        if cand_name or cand_email or cand_skills:
            # Skip header-like rows (if any sneaked through)
            if cand_name.lower() in ('name', 'full name', 'candidate name', 'trainer', 'trainer name'):
                continue
            candidates.append(cand)

    logger.info(f"[excel] {file_path} → {len(candidates)} candidates")

    try:
        _EXCEL_CACHE[cache_key] = (time.time(), candidates)
    except Exception:
        pass

    return candidates

def excel_to_text(file_path, max_rows=100):
    """
    Convert first N rows of Excel to a CSV-like text blob.
    Used as a Gemini fallback if column detection fails.
    """
    try:
        is_xlsx = file_path.lower().endswith('.xlsx')
        engine = 'openpyxl' if is_xlsx else None
        df = pd.read_excel(file_path, engine=engine, dtype=str, nrows=max_rows)
        return df.to_csv(index=False)
    except Exception as e:
        logger.error(f"[excel] to_text failed: {e}")
        return ''
