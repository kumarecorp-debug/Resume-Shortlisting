import re
import logging

logger = logging.getLogger(__name__)

def parse_terms(jd_query: str) -> list:
    """
    Parse search terms handling AND / OR and phrases.
    """
    if not jd_query or not str(jd_query).strip():
        return []

    query_lower = str(jd_query).lower().strip()

    if ' and ' in query_lower:
        terms = [t.strip() for t in query_lower.split(' and ') if t.strip()]
        return terms
    elif ' or ' in query_lower:
        terms = [t.strip() for t in query_lower.split(' or ') if t.strip()]
        return terms
    else:
        return [query_lower]

def matches_query_strict(candidate: dict, jd_query: str) -> bool:
    """
    Match the JD query against candidate fields using strict string matching (no AI hallucination).
    Supports: "python and sql", "python or sql", "python"
    """
    if not jd_query or not str(jd_query).strip():
        return True

    if not isinstance(candidate, dict):
        return False

    skills_text = str(candidate.get('skills') or candidate.get('Skill Set') or '').lower()
    title_text = str(candidate.get('resume_title') or candidate.get('Resume Title') or candidate.get('title') or '').lower()
    desig_text = str(candidate.get('designation') or candidate.get('Designation') or '').lower()
    emp_text = str(candidate.get('employer') or candidate.get('Employer') or candidate.get('Current Employer') or '').lower()
    name_text = str(candidate.get('name') or candidate.get('Name') or '').lower()
    ug_text = str(candidate.get('ug_course') or candidate.get('U.G. Course') or '').lower()
    pg_text = str(candidate.get('pg_course') or candidate.get('P.G. Course') or '').lower()

    text = ' '.join(filter(None, [skills_text, title_text, desig_text, emp_text, name_text, ug_text, pg_text]))
    text = re.sub(r'\s+', ' ', text)

    query_lower = str(jd_query).lower().strip()

    if ' and ' in query_lower:
        terms = [t.strip() for t in query_lower.split(' and ') if t.strip()]
        if not terms:
            return False
        return all(term in text for term in terms)
    elif ' or ' in query_lower:
        terms = [t.strip() for t in query_lower.split(' or ') if t.strip()]
        if not terms:
            return False
        return any(term in text for term in terms)
    else:
        return query_lower in text

def calculate_score(candidate: dict, jd_query: str) -> tuple:
    """
    Calculate match score (0-100) using strict string matching.
    Returns: (matched_skills_str, score_int, match_reason_str)
    """
    if not jd_query or not str(jd_query).strip():
        return "", 100, "General search match"

    if not isinstance(candidate, dict):
        return "", 0, "Invalid candidate data"

    skills_text = str(candidate.get('skills') or candidate.get('Skill Set') or '').lower()
    title_text = str(candidate.get('resume_title') or candidate.get('Resume Title') or candidate.get('title') or '').lower()
    desig_text = str(candidate.get('designation') or candidate.get('Designation') or '').lower()
    emp_text = str(candidate.get('employer') or candidate.get('Employer') or candidate.get('Current Employer') or '').lower()
    ug_text = str(candidate.get('ug_course') or candidate.get('U.G. Course') or '').lower()
    pg_text = str(candidate.get('pg_course') or candidate.get('P.G. Course') or '').lower()

    combined_text = ' '.join(filter(None, [skills_text, title_text, desig_text, emp_text, ug_text, pg_text]))
    combined_text = re.sub(r'\s+', ' ', combined_text)

    query_lower = str(jd_query).lower().strip()

    matched_terms = []

    if ' and ' in query_lower:
        terms = [t.strip() for t in query_lower.split(' and ') if t.strip()]
        for term in terms:
            if term in combined_text:
                matched_terms.append(term)
        total = len(terms)
        score = int((len(matched_terms) / total) * 100) if total > 0 else 0
    elif ' or ' in query_lower:
        terms = [t.strip() for t in query_lower.split(' or ') if t.strip()]
        for term in terms:
            if term in combined_text:
                matched_terms.append(term)
        total = len(terms)
        score = int((len(matched_terms) / total) * 100) if total > 0 and len(matched_terms) > 0 else 0
    else:
        terms = [query_lower]
        if query_lower in combined_text:
            matched_terms.append(query_lower)
            score = 100
        else:
            score = 0

    matched_str = ", ".join([t.title() for t in set(matched_terms)]) if matched_terms else ""

    if score > 0:
        reason = f"Candidate profile matched target keywords ({matched_str})."
    else:
        reason = "No matching keywords found in profile."

    return matched_str, score, reason

def is_valid_match(candidate: dict, jd_query: str) -> bool:
    """
    Sanity check for each candidate before returning/displaying results.
    Return True only if the query keyword actually appears in the candidate's searchable text.
    """
    return matches_query_strict(candidate, jd_query)
