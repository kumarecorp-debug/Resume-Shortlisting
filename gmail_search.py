import re
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

STOP_WORDS = {
    "the", "a", "an", "in", "on", "for", "with", "to", "at", 
    "of", "by", "from", "as", "is", "are", "we", "need", "looking", "require",
    "required", "seeking", "candidate", "role", "position", "job", "hiring",
    "years", "year", "experience", "exp", "location", "remote", "hybrid",
    "responsibilities", "requirements", "develop", "maintain", "build",
    "scalable", "design", "efficient", "collaborate", "implement", "integrate",
    "optimize", "performance", "write", "participate", "troubleshoot", "debug",
    "resolve", "work", "strong", "proficiency", "knowledge", "understanding"
}

TECH_KEYWORDS = [
    'react', 'react js', 'react.js', 'reactjs', 'node.js', 'nodejs', 'node',
    'express.js', 'expressjs', 'express', 'javascript', 'typescript', 'js', 'ts',
    'redux', 'html5', 'html', 'css3', 'css', 'mongodb', 'postgresql', 'postgres',
    'mysql', 'sql', 'oracle', 'python', 'aws', 'azure', 'gcp', 'docker', 'kubernetes',
    'tailwind', 'bootstrap', 'material ui', 'jwt', 'oauth', 'rest api', 'restful', 'graphql',
    'java', 'spring boot', 'spring', 'c++', 'c#', '.net', 'django', 'flask', 'fastapi',
    'pyspark', 'spark', 'hadoop', 'databricks', 'kafka', 'airflow', 'etl', 'dbt',
    'tableau', 'power bi', 'snowflake', 'salesforce', 'sfdc', 'sap', 'grc', 'hana',
    'abap', 'scm', 'fusion', 'hcm', 'oic', 'plsql', 'jira', 'agile', 'scrum', 'devops',
    'microservices', 'next.js', 'angular', 'vue', 'golang', 'rust', 'ruby', 'rails',
    'linux', 'git', 'ci/cd', 'terraform', 'ansible', 'jenkins'
]

def extract_tech_keywords_from_jd(jd_text):
    text_lower = jd_text.lower()
    found = []
    for kw in TECH_KEYWORDS:
        pattern = r'\b' + re.escape(kw) + r'\b'
        if re.search(pattern, text_lower):
            if kw in ['node.js', 'nodejs', 'node']: display = 'Node.js'
            elif kw in ['express.js', 'expressjs', 'express']: display = 'Express'
            elif kw in ['react', 'react js', 'react.js', 'reactjs']: display = 'React'
            elif kw in ['javascript', 'js']: display = 'JavaScript'
            elif kw in ['typescript', 'ts']: display = 'TypeScript'
            elif kw in ['html5', 'html']: display = 'HTML'
            elif kw in ['css3', 'css']: display = 'CSS'
            elif kw in ['mysql', 'sql', 'postgresql', 'postgres']: display = kw.upper() if kw in ['sql', 'mysql'] else 'PostgreSQL'
            elif kw in ['aws', 'gcp', 'jwt', 'oauth', 'etl', 'dbt', 'sfdc', 'sap', 'grc', 'scm', 'hcm', 'oic']: display = kw.upper()
            else: display = kw.title()
            
            if display not in found:
                found.append(display)
    return found

def detect_search_mode(term):
    """
    Detects if the search term is an email, phone, name, or general keyword.
    Returns string: 'email', 'phone', 'name', or 'keyword'.
    """
    t = term.strip()
    if not t:
        return 'keyword'
        
    # Email detection: contains @ and domain
    if re.match(r'^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$', t):
        return 'email'
        
    # Phone detection: mostly digits/dashes/spaces/plus with at least 7 digits
    digits_only = re.sub(r'\D', '', t)
    if len(digits_only) >= 7 and bool(re.match(r'^[+\d\s().-]{7,}$', t)):
        return 'phone'
        
    # Name detection: MUST be 2 to 4 words (e.g. "John Smith", "Karan Pathak", "Mohammed Sahel")
    # Single-word queries (e.g., "infoarchive", "pega", "python") are ALWAYS keyword searches!
    words = t.split()
    if 2 <= len(words) <= 4 and all(re.match(r'^[A-Za-z.\'-]+$', w) for w in words):
        upper_words = [w.upper() for w in words]
        if 'AND' not in upper_words and 'OR' not in upper_words and 'NOT' not in upper_words:
            tech_stack = set(k.lower() for k in TECH_KEYWORDS) | {
                'sql', 'sap', 'grc', 'scm', 'd365', 'crm', 'etl', 'hcm', 'oic', 'fusion', 
                'azure', 'developer', 'engineer', 'architect', 'consultant', 'lead', 
                'admin', 'administrator', 'analyst', 'manager', 'specialist', 'trainer',
                'support', 'infoarchive', 'opentext', 'documentum', 'servicenow'
            }
            if not any(w.lower() in tech_stack for w in words):
                return 'name'

    return 'keyword'

def build_gmail_search_query(job_description, days_back=None, date_preset=None, date_from=None, date_to=None, **kwargs):
    """
    Constructs an optimized Gmail search query matching Gmail UI search semantics.
    Handles:
      1. Identifier searches (Email, Phone, Name) -> Exact string matching without splitting
      2. Explicit boolean short queries (e.g. 'Python AND SQL', 'React OR Node')
      3. Short keyword queries (e.g. 'infoarchive', 'SFDC agentic core workflows')
      4. Full long Job Descriptions -> Automatically extracts core tech stack
      5. Date Range Filters (newer_than:7d, 14d, 30d, after:YYYY/MM/DD, before:YYYY/MM/DD)
    """
    if not job_description:
        kw_query = ""
    else:
        cleaned_jd = job_description.strip()
        lines = [l.strip() for l in cleaned_jd.splitlines() if l.strip()]
        normalized_jd = " ".join(lines)
        if not normalized_jd:
            kw_query = ""
        else:
            mode = detect_search_mode(normalized_jd)
            if mode in ['email', 'phone', 'name']:
                kw_query = f'"{normalized_jd}"'
            else:
                words = re.findall(r'\b[A-Za-z0-9+#.]+\b', normalized_jd)
                is_long_jd = len(words) > 12 or len(normalized_jd) > 120 or len(lines) >= 4

                if is_long_jd:
                    extracted_skills = extract_tech_keywords_from_jd(normalized_jd)
                    if extracted_skills:
                        top_skills = extracted_skills[:10]
                        kw_query = "(" + " OR ".join(top_skills) + ")"
                    else:
                        distinct_tokens = [w for w in words if w.lower() not in STOP_WORDS and len(w) >= 2][:8]
                        if distinct_tokens:
                            kw_query = "(" + " OR ".join(distinct_tokens) + ")"
                        else:
                            kw_query = f'"{normalized_jd}"'
                else:
                    has_explicit_or = bool(re.search(r'\bOR\b', normalized_jd, flags=re.IGNORECASE))
                    has_explicit_and = bool(re.search(r'\bAND\b', normalized_jd, flags=re.IGNORECASE))

                    if has_explicit_or:
                        branches = [b.strip() for b in re.split(r'\bOR\b', normalized_jd, flags=re.IGNORECASE) if b.strip()]
                        valid_branches = []
                        for branch in branches:
                            branch_tokens = [t for t in re.findall(r'[a-zA-Z0-9+#.]+', branch) if t.lower() not in STOP_WORDS and t.lower() != "and"]
                            if branch_tokens:
                                valid_branches.append(" ".join(branch_tokens))
                        if len(valid_branches) > 1:
                            kw_query = "(" + " OR ".join(valid_branches) + ")"
                        elif valid_branches:
                            kw_query = valid_branches[0]
                        else:
                            kw_query = normalized_jd

                    elif has_explicit_and:
                        branches = [b.strip() for b in re.split(r'\bAND\b', normalized_jd, flags=re.IGNORECASE) if b.strip()]
                        valid_tokens = []
                        for branch in branches:
                            branch_tokens = [t for t in re.findall(r'[a-zA-Z0-9+#.]+', branch) if t.lower() not in STOP_WORDS]
                            if branch_tokens:
                                valid_tokens.append(" ".join(branch_tokens))
                        if len(valid_tokens) > 1:
                            kw_query = "(" + " OR ".join(valid_tokens) + ")"
                        elif valid_tokens:
                            kw_query = valid_tokens[0]
                        else:
                            kw_query = normalized_jd

                    else:
                        tokens = [t for t in re.findall(r'[a-zA-Z0-9+#.]+', normalized_jd) if t.lower() not in STOP_WORDS]
                        if not tokens:
                            tokens = [w for w in words if w.lower() not in STOP_WORDS]
                        if not tokens:
                            tokens = words

                        expanded_tokens = []
                        for t in tokens:
                            expanded_tokens.append(t)
                            if t.upper() == "SFDC" and "Salesforce" not in expanded_tokens:
                                expanded_tokens.append("Salesforce")

                        if len(expanded_tokens) > 1:
                            kw_query = "(" + " OR ".join(expanded_tokens) + ")"
                        elif len(expanded_tokens) == 1:
                            kw_query = expanded_tokens[0]
                        else:
                            kw_query = normalized_jd

    date_clause = ""
    preset = str(date_preset).strip().lower() if date_preset else ""

    if preset == "today":
        date_clause = "newer_than:1d"
    elif preset == "yesterday":
        date_clause = "newer_than:2d older_than:1d"
    elif preset == "7d":
        date_clause = "newer_than:7d"
    elif preset == "14d":
        date_clause = "newer_than:14d"
    elif preset == "30d":
        date_clause = "newer_than:30d"
    elif preset == "custom":
        if date_from and date_to:
            try:
                from datetime import datetime, timedelta
                df_clean = str(date_from).strip().split('T')[0].replace('-', '/')
                dt_str = str(date_to).strip().split('T')[0]
                dt_obj = datetime.strptime(dt_str, '%Y-%m-%d') + timedelta(days=1)
                dt_clean = dt_obj.strftime('%Y/%m/%d')
                date_clause = f"after:{df_clean} before:{dt_clean}"
            except Exception as e_date:
                logging.warning(f"Error formatting custom dates ({date_from}, {date_to}): {e_date}")
                if date_from:
                    df_clean = str(date_from).strip().split('T')[0].replace('-', '/')
                    date_clause += f" after:{df_clean}"
                if date_to:
                    dt_clean = str(date_to).strip().split('T')[0].replace('-', '/')
                    date_clause += f" before:{dt_clean}"

    if not date_clause and not preset:
        if date_from and str(date_from).strip():
            df_clean = str(date_from).strip().split('T')[0].replace('-', '/')
            date_clause += f" after:{df_clean}"
        if date_to and str(date_to).strip():
            dt_clean = str(date_to).strip().split('T')[0].replace('-', '/')
            date_clause += f" before:{dt_clean}"

    if not date_clause and days_back:
        from datetime import datetime, timedelta
        start_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y/%m/%d')
        date_clause = f"after:{start_date}"

    GMAIL_ATTACHMENT_FILTER = "(filename:pdf OR filename:docx OR filename:xlsx OR filename:xls)"

    if date_clause:
        full_query = f"has:attachment {GMAIL_ATTACHMENT_FILTER} {date_clause} {kw_query}".strip() if kw_query else f"has:attachment {GMAIL_ATTACHMENT_FILTER} {date_clause}"
    else:
        full_query = f"has:attachment {GMAIL_ATTACHMENT_FILTER} {kw_query}".strip() if kw_query else f"has:attachment {GMAIL_ATTACHMENT_FILTER}"

    logging.info(f"Generated Gmail search query: {full_query}")
    return full_query

