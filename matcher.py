import re
import logging

logger = logging.getLogger(__name__)

_WHITESPACE_RE = re.compile(r'\s+')

def parse_terms(jd_query: str) -> dict:
    """
    Parse query once into a dict, reuse across candidate checks.
    Returns dict: {'type': 'and'|'or'|'single', 'terms': [...]}
    """
    if not jd_query or not str(jd_query).strip():
        return {'type': 'single', 'terms': []}

    q = str(jd_query).lower().strip()
    if ' and ' in q:
        terms = [t.strip() for t in q.split(' and ') if t.strip()]
        return {'type': 'and', 'terms': terms}
    elif ' or ' in q:
        terms = [t.strip() for t in q.split(' or ') if t.strip()]
        return {'type': 'or', 'terms': terms}
    else:
        return {'type': 'single', 'terms': [q]}

def matches_query_strict(candidate: dict, jd_query: str, query_terms: dict = None) -> bool:
    """
    Fast precompiled strict string matching for candidate records.
    """
    if not jd_query or not str(jd_query).strip():
        return True

    if not isinstance(candidate, dict):
        return False

    if query_terms is None:
        query_terms = parse_terms(jd_query)

    terms = query_terms.get('terms', [])
    if not terms:
        return True

    skills_text = str(candidate.get('skills') or candidate.get('Skill Set') or '')
    title_text = str(candidate.get('resume_title') or candidate.get('Resume Title') or candidate.get('title') or '')
    desig_text = str(candidate.get('designation') or candidate.get('Designation') or '')
    emp_text = str(candidate.get('employer') or candidate.get('Employer') or candidate.get('Current Employer') or '')
    name_text = str(candidate.get('name') or candidate.get('Name') or '')

    text = ' '.join(filter(None, [skills_text, title_text, desig_text, emp_text, name_text]))
    text = _WHITESPACE_RE.sub(' ', text).lower()

    q_type = query_terms.get('type')
    if q_type == 'and':
        return all(t in text for t in terms)
    elif q_type == 'or':
        return any(t in text for t in terms)
    else:
        return terms[0] in text

def calculate_score(candidate: dict, jd_query: str, query_terms: dict = None) -> tuple:
    """
    Calculate match score (0-100) using strict string matching.
    Returns: (matched_skills_str, score_int, match_reason_str)
    """
    if not jd_query or not str(jd_query).strip():
        return "", 100, "General search match"

    if not isinstance(candidate, dict):
        return "", 0, "Invalid candidate data"

    if query_terms is None:
        query_terms = parse_terms(jd_query)

    terms = query_terms.get('terms', [])
    if not terms:
        return "", 100, "General search match"

    skills_text = str(candidate.get('skills') or candidate.get('Skill Set') or '')
    title_text = str(candidate.get('resume_title') or candidate.get('Resume Title') or candidate.get('title') or '')
    desig_text = str(candidate.get('designation') or candidate.get('Designation') or '')
    emp_text = str(candidate.get('employer') or candidate.get('Employer') or candidate.get('Current Employer') or '')
    ug_text = str(candidate.get('ug_course') or candidate.get('U.G. Course') or '')
    pg_text = str(candidate.get('pg_course') or candidate.get('P.G. Course') or '')

    combined_text = ' '.join(filter(None, [skills_text, title_text, desig_text, emp_text, ug_text, pg_text]))
    combined_text = _WHITESPACE_RE.sub(' ', combined_text).lower()

    matched_terms = [t for t in terms if t in combined_text]
    total = len(terms)

    q_type = query_terms.get('type')
    if q_type in ('and', 'or'):
        score = int((len(matched_terms) / total) * 100) if total > 0 else 0
    else:
        score = 100 if matched_terms else 0

    matched_str = ", ".join([t.title() for t in set(matched_terms)]) if matched_terms else ""

    if score > 0:
        reason = f"Candidate profile matched target keywords ({matched_str})."
    else:
        reason = "No matching keywords found in profile."

    return matched_str, score, reason

def is_valid_match(candidate: dict, jd_query: str, query_terms: dict = None) -> bool:
    return matches_query_strict(candidate, jd_query, query_terms=query_terms)
