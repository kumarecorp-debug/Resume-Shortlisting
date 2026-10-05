import os
import time
import logging
import pandas as pd

logger = logging.getLogger(__name__)

# Known header keywords to look for during header row auto-detection
HEADER_KEYWORDS = {
    'name', 'candidate name', 'full name', 'fullname', 'trainer',
    'trainer name', 'consultant', 'candidate', 'consultant name',
    'email', 'email id', 'e-mail', 'mail', 'mail id', 'email address', 'emailid',
    'phone', 'mobile', 'contact', 'contact no', 'contact no.',
    'contact number', 'phone number', 'mobile no', 'mobile number', 'ph', 'cell',
    'skills', 'skill', 'skill set', 'skillset', 'primary skills',
    'key skills', 'core skills', 'resume title', 'expertise', 'technologies', 'tech stack',
    'experience', 'work exp', 'work experience', 'total experience',
    'exp', 'years of experience', 'yrs', 'exp.',
    'designation', 'current employer', 'current location',
    'preferred location', 'annual salary', 'ug course', 'pg course',
}

# Column aliases — map friendly names to internal field names
COLUMN_ALIASES = {
    'name': [
        'name', 'candidate name', 'full name', 'fullname',
        'candidate', 'trainer', 'trainer name', 'consultant name',
        'name of candidate',
    ],
    'email': [
        'email', 'email id', 'e-mail', 'mail', 'mail id',
        'email address', 'emailid', 'e mail',
    ],
    'phone': [
        'phone', 'phone number', 'phone no', 'mobile', 
        'mobile no', 'mobile no.', 'mobile number', 'contact', 
        'contact no', 'contact no.', 'contact number',
    ],
    'skills': [
        'skills', 'skill', 'skill set', 'skillset', 
        'primary skills', 'key skills', 'core skills',
        'resume title', 'resume title ', 'title', 'summary',
        'professional summary', 'profile', 'profile summary',
        'candidate profile', 'resume summary', 'headline',
        'technologies', 'tech stack', 'expertise',
    ],
    'resume_title': [
        'resume title', 'resume title ', 'title', 'summary',
        'professional summary', 'profile', 'profile summary',
        'candidate profile', 'resume summary', 'headline',
    ],
    'experience': [
        'experience', 'exp', 'work exp',
        'work experience', 'total experience', 'total exp',
        'years of experience', 'yrs', 'yrs of exp', 'year of exp',
    ],
    'designation': ['designation', 'role', 'current role'],
    'current_employer': ['current employer', 'employer', 'company'],
    'location': ['current location', 'location', 'preferred location'],
    'ug_course': ['u.g. course', 'ug course', 'ug'],
    'pg_course': ['p.g. course', 'pg course', 'pg'],
    'age_dob': ['age/date of birth', 'age', 'dob'],
}

# 10-minute in-memory cache: (file_path, mtime) -> (timestamp, candidates)
_EXCEL_CACHE = {}

def detect_header_row(file_path, sheet_name=0, max_scan=15):
    """
    Scan first N rows to find the one that looks like a table header.
    Return 0-based row index of the best candidate row.
    """
    try:
        engine = 'openpyxl' if file_path.lower().endswith('.xlsx') else 'xlrd'
        df_raw = pd.read_excel(
            file_path,
            sheet_name=sheet_name,
            header=None,
            nrows=max_scan,
            dtype=str,
            engine=engine
        )
    except Exception as e:
        logger.error(f"[excel] header detect failed for {file_path}: {e}")
        return 0

    best_idx = 0
    best_score = 0

    for idx in range(len(df_raw)):
        row = df_raw.iloc[idx]
        score = 0
        non_empty = 0
        for cell in row:
            if pd.isna(cell):
                continue
            cell_lower = str(cell).strip().lower()
            if not cell_lower:
                continue
            non_empty += 1
            for keyword in HEADER_KEYWORDS:
                if keyword in cell_lower or cell_lower in keyword:
                    score += 1
                    break

        if score >= 2 and score > best_score:
            best_score = score
            best_idx = idx

    logger.info(
        f"[excel] {file_path} (sheet={sheet_name}) header row detected at index {best_idx} (score={best_score})"
    )
    return best_idx

def find_column(df_columns, aliases):
    """
    Match any of the aliases to a real column in df_columns.
    Try exact match first, then substring match, then word-intersection match.
    """
    cols_normalized = {
        col: str(col).strip().lower().rstrip('.')
        for col in df_columns
    }

    # 1. Exact match (after normalization)
    for alias in aliases:
        alias_norm = alias.strip().lower().rstrip('.')
        for col, norm in cols_normalized.items():
            if norm == alias_norm:
                return col

    # 2. Substring match (either direction)
    for alias in aliases:
        alias_norm = alias.strip().lower()
        for col, norm in cols_normalized.items():
            if alias_norm in norm or norm in alias_norm:
                return col

    # 3. Word-level match
    for alias in aliases:
        alias_words = set(alias.lower().split())
        for col, norm in cols_normalized.items():
            col_words = set(norm.split())
            if alias_words & col_words:
                return col

    return None

def _normalize_columns(df):
    """Return a dict mapping internal field -> actual column name using find_column."""
    col_map = {}
    for field, aliases in COLUMN_ALIASES.items():
        matched_col = find_column(df.columns, aliases)
        col_map[field] = matched_col
    return col_map

def is_valid_data_row(row, col_map):
    """Return True if this row has real candidate data."""
    name = str(row.get(col_map.get('name'), '') if col_map.get('name') else '').strip()
    email = str(row.get(col_map.get('email'), '') if col_map.get('email') else '').strip()

    # Skip if name is a header-like string or '#'
    if name.lower() in ('name', 'candidate name', '#', 'full name', 'candidate', 'trainer'):
        return False

    # Require at least non-empty name or non-empty email
    return bool(name) or bool(email)

def read_excel_safe(file_path, sheet_name=None, max_rows=None, header=0):
    """
    Safely read Excel file selecting explicit engines with header row offset:
    - openpyxl for .xlsx
    - xlrd for .xls
    """
    fn_lower = file_path.lower()
    try:
        if fn_lower.endswith('.xlsx'):
            return pd.read_excel(file_path, sheet_name=sheet_name, header=header, engine='openpyxl', dtype=str, nrows=max_rows)
        elif fn_lower.endswith('.xls'):
            return pd.read_excel(file_path, sheet_name=sheet_name, header=header, engine='xlrd', dtype=str, nrows=max_rows)
        else:
            return pd.read_excel(file_path, sheet_name=sheet_name, header=header, dtype=str, nrows=max_rows)
    except Exception as e:
        logger.error(f"[excel] {file_path} read failed with engine: {e}")
        try:
            return pd.read_excel(file_path, sheet_name=sheet_name, header=header, dtype=str, nrows=max_rows)
        except Exception as e2:
            logger.error(f"[excel] {file_path} read failed completely: {e2}")
            return None

def parse_excel_to_candidates(file_path, max_rows=500):
    """
    Read an Excel file. Auto-detect header row and return candidate dicts.
    Each row = one candidate.
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
            if now - ts < 600:
                logger.info(f"[excel] Returning cached {len(cached_cands)} candidates for {file_path}")
                return cached_cands
    except Exception:
        pass

    logger.info(f"[excel] parsing {file_path}")

    all_rows = []
    try:
        # Detect header row first
        header_idx = detect_header_row(file_path)
        sheets = read_excel_safe(file_path, sheet_name=None, header=header_idx)
        if sheets is None:
            return []

        if isinstance(sheets, dict):
            for sheet_name, df in sheets.items():
                if df is None or df.empty:
                    continue
                df = df.dropna(how='all')
                df['__sheet__'] = sheet_name
                all_rows.append(df)
        elif isinstance(sheets, pd.DataFrame):
            if not sheets.empty:
                sheets = sheets.dropna(how='all')
                sheets['__sheet__'] = 'Sheet1'
                all_rows.append(sheets)
    except Exception as e:
        logger.error(f"[excel] failed to parse sheets for {file_path}: {e}")
        return []

    if not all_rows:
        return []

    df = pd.concat(all_rows, ignore_index=True)

    # Cap rows
    if len(df) > max_rows:
        logger.info(f"[excel] {file_path} has {len(df)} rows, capping to {max_rows}")
        df = df.head(max_rows)

    col_map = _normalize_columns(df)
    logger.info(f"[excel] {file_path} header row: {header_idx}")
    logger.info(f"[excel] {file_path} actual columns: {list(df.columns)}")
    logger.info(f"[excel] {file_path} column mapping: {col_map}")

    candidates = []
    for idx, row in df.iterrows():
        if not is_valid_data_row(row, col_map):
            continue

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
        cand_title = get('resume_title')
        cand_exp = get('experience')
        cand_desig = get('designation')
        cand_emp = get('current_employer')
        cand_ug = get('ug_course')
        cand_pg = get('pg_course')

        text_parts = []
        if cand_title:
            text_parts.append(cand_title)
        if cand_skills and cand_skills != cand_title:
            text_parts.append(cand_skills)
        if cand_desig:
            text_parts.append(cand_desig)
        if cand_emp:
            text_parts.append(cand_emp)
        if cand_ug:
            text_parts.append(cand_ug)
        if cand_pg:
            text_parts.append(cand_pg)

        combined_skills = " ".join(filter(None, text_parts)).strip()
        if not combined_skills:
            combined_skills = cand_skills or cand_title or 'N/A'

        cand = {
            'Name': cand_name,
            'Email': cand_email,
            'Phone': cand_phone,
            'Skill Set': combined_skills,
            'skills': combined_skills,
            'resume_title': cand_title or cand_skills,
            'Resume Title': cand_title or cand_skills,
            'Experience': f"{cand_exp} yrs" if cand_exp and 'yr' not in cand_exp.lower() else (cand_exp or 'N/A'),
            'experience': cand_exp,
            'Designation': cand_desig,
            'Employer': cand_emp,
            'Location': get('location'),
            'source': 'excel',
            'source_file': os.path.basename(file_path),
            'source_sheet': str(row.get('__sheet__', 'Sheet1')),
            'source_row': int(idx) + header_idx + 2,
        }

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
        header_idx = detect_header_row(file_path)
        df = read_excel_safe(file_path, max_rows=max_rows, header=header_idx)
        if df is None:
            return ''
        if isinstance(df, dict):
            dfs = [d.dropna(how='all') for d in df.values() if isinstance(d, pd.DataFrame) and not d.empty]
            if dfs:
                df = pd.concat(dfs, ignore_index=True)
            else:
                return ''
        return df.to_csv(index=False)
    except Exception as e:
        logger.error(f"[excel] to_text failed: {e}")
        return ''
