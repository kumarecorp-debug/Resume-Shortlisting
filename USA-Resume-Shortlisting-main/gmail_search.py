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
        
    # Name detection: 1-4 word alphabetic string (e.g. "John Smith", "Karan Pathak") without boolean ops
    words = t.split()
    if 1 <= len(words) <= 4 and all(re.match(r'^[A-Za-z.\'-]+$', w) for w in words):
        upper_words = [w.upper() for w in words]
        if 'AND' not in upper_words and 'OR' not in upper_words and 'NOT' not in upper_words:
            # If word is not a known tech stack keyword (like Python, React, Java, AWS, etc.)
            tech_stack = set(k.lower() for k in TECH_KEYWORDS) | {'sql', 'sap', 'grc', 'scm', 'd365', 'crm', 'etl', 'hcm', 'oic', 'fusion', 'azure'}
            if not any(w.lower() in tech_stack for w in words):
                return 'name'

    return 'keyword'

def build_gmail_search_query(job_description, days_back=None):
    """
    Constructs an optimized Gmail search query matching Gmail UI search semantics.
    Handles:
      1. Identifier searches (Email, Phone, Name) -> Exact string matching without splitting
      2. Explicit boolean short queries (e.g. 'Python AND SQL', 'React OR Node')
      3. Short keyword queries (e.g. 'SFDC agentic core workflows')
      4. Full long Job Descriptions -> Automatically extracts core tech stack
    """
    cleaned_jd = job_description.strip() if job_description else ""
    if not cleaned_jd:
        return "has:attachment"

    mode = detect_search_mode(cleaned_jd)
    if mode in ['email', 'phone', 'name']:
        # Exact quote search for identifiers to avoid splitting (e.g., "vallir63@gmail.com")
        kw_query = f'"{cleaned_jd}"'
    else:
        words = re.findall(r'\b[A-Za-z0-9+#.]+\b', cleaned_jd)
        is_long_jd = len(words) > 12 or '\n' in cleaned_jd or len(cleaned_jd) > 120

        if is_long_jd:
            # Long Job Description: Extract core technical skills
            extracted_skills = extract_tech_keywords_from_jd(cleaned_jd)
            if extracted_skills:
                top_skills = extracted_skills[:10]
                kw_query = "(" + " OR ".join(top_skills) + ")"
            else:
                distinct_tokens = [w for w in words if w.lower() not in STOP_WORDS and len(w) > 2][:8]
                if distinct_tokens:
                    kw_query = "(" + " OR ".join(distinct_tokens) + ")"
                else:
                    kw_query = ""
        else:
            # Short Query
            has_explicit_or = bool(re.search(r'\bOR\b', cleaned_jd, flags=re.IGNORECASE))
            has_explicit_and = bool(re.search(r'\bAND\b', cleaned_jd, flags=re.IGNORECASE))

            if has_explicit_or:
                branches = [b.strip() for b in re.split(r'\bOR\b', cleaned_jd, flags=re.IGNORECASE) if b.strip()]
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
                    kw_query = cleaned_jd

            elif has_explicit_and:
                branches = [b.strip() for b in re.split(r'\bAND\b', cleaned_jd, flags=re.IGNORECASE) if b.strip()]
                valid_tokens = []
                for branch in branches:
                    branch_tokens = [t for t in re.findall(r'[a-zA-Z0-9+#.]+', branch) if t.lower() not in STOP_WORDS]
                    if branch_tokens:
                        valid_tokens.append(" ".join(branch_tokens))
                if len(valid_tokens) > 1:
                    kw_query = " ".join(valid_tokens)
                elif valid_tokens:
                    kw_query = valid_tokens[0]
                else:
                    kw_query = cleaned_jd

            else:
                # Multi-word searches without explicit AND/OR: Default to OR-joining
                tokens = [t for t in re.findall(r'[a-zA-Z0-9+#.]+', cleaned_jd) if t.lower() not in STOP_WORDS and len(t) > 1]
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
                    kw_query = cleaned_jd

    if kw_query:
        full_query = f"{kw_query}"
    else:
        full_query = "has:attachment"

    if days_back:
        from datetime import datetime, timedelta
        start_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y/%m/%d')
        full_query += f" after:{start_date}"

    logging.info(f"Generated Gmail search query: {full_query}")
    return full_query
