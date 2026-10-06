import os
import json
import logging
import time
import hashlib
import threading
from collections import deque

logger = logging.getLogger(__name__)

# Configurable parameters
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "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")
PRIMARY_MODEL = os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant")
RPM_LIMIT = int(os.environ.get("GROQ_REQUESTS_PER_MINUTE", 25))
MAX_RESUME_CHARS = int(os.environ.get("MAX_RESUME_CHARS", 4000))
BATCH_SIZE = int(os.environ.get("GROQ_BATCH_SIZE", 5))

PREFERRED_MODELS = [
    'llama-3.1-8b-instant',
    'llama-3.3-70b-versatile',
    'llama-3.3-70b-specdec',
    'llama3-70b-8192',
    'llama3-8b-8192',
    'gemma2-9b-it',
    'qwen/qwen3.8-27b',
]

FALLBACK_MODELS = [
    'llama-3.1-8b-instant',
    'llama-3.3-70b-versatile',
    'gemma2-9b-it',
]

groq_client = None

def get_groq_client():
    global groq_client
    api_k = os.environ.get("GROQ_API_KEY", GROQ_API_KEY)
    if not groq_client and api_k:
        try:
            from groq import Groq
            groq_client = Groq(
                api_key=api_k,
                max_retries=0,
                timeout=20.0
            )
        except Exception as e:
            logger.warning(f"[groq] Client init error: {e}")
    return groq_client

def init_groq_models():
    client = get_groq_client()
    available = []
    if client:
        try:
            models = client.models.list()
            available = [m.id for m in models.data]
            logger.info(f'[groq-startup] Available models: {available}')
        except Exception as e:
            logger.warning(f'[groq-startup] Could not list models: {e}')

    active = None
    for model in PREFERRED_MODELS:
        if available and model in available:
            active = model
            break
    if not active:
        active = available[0] if available else 'qwen/qwen3.8-27b'

    logger.info(f'[groq-startup] Using model: {active}')
    return active, available

ACTIVE_GROQ_MODEL, AVAILABLE_MODELS = init_groq_models()

class RateLimiter:
    def __init__(self, max_per_min=25):
        self.max = max_per_min
        self.timestamps = deque()
        self.lock = threading.Lock()
        self.last_wait_msg = None
        self.last_wait_sec = 0

    def acquire(self):
        while True:
            with self.lock:
                now = time.time()
                while self.timestamps and now - self.timestamps[0] > 60:
                    self.timestamps.popleft()

                if len(self.timestamps) < self.max:
                    self.timestamps.append(now)
                    self.last_wait_msg = None
                    self.last_wait_sec = 0
                    return

                oldest = self.timestamps[0]
                wait = 60 - (now - oldest) + 0.5
                self.last_wait_sec = round(wait)
                self.last_wait_msg = f"AI rate limit — waiting {round(wait)}s"

            if wait > 15:
                logger.info(f'[groq-rate] waiting {wait:.1f}s (long)')
                time.sleep(wait)
            elif wait > 3:
                logger.info(f'[groq-rate] waiting {wait:.1f}s')
                time.sleep(wait)
            else:
                time.sleep(max(wait, 1.0))

_groq_limiter = RateLimiter(max_per_min=25)

def call_with_timeout(fn, timeout_sec=30):
    result = {'value': None, 'error': None}
    def target():
        try:
            result['value'] = fn()
        except Exception as e:
            result['error'] = e

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(timeout_sec)

    if t.is_alive():
        raise TimeoutError(f'Call timed out after {timeout_sec}s')
    if result['error']:
        raise result['error']
    return result['value']

def call_groq_with_fallback(messages, max_tokens=1500):
    client = get_groq_client()
    if not client:
        raise Exception("Groq client not initialized")

    candidate_models = []
    if ACTIVE_GROQ_MODEL:
        candidate_models.append(ACTIVE_GROQ_MODEL)
    for m in FALLBACK_MODELS:
        if m not in candidate_models:
            candidate_models.append(m)

    for model in candidate_models:
        try:
            _groq_limiter.acquire()
            def _api_call(mod=model):
                return client.chat.completions.create(
                    model=mod,
                    messages=messages,
                    temperature=0,
                    response_format={'type': 'json_object'},
                    max_tokens=max_tokens
                )

            response = call_with_timeout(_api_call, timeout_sec=30)
            return response, model
        except Exception as e:
            err_str = str(e)
            if '429' in err_str or 'rate' in err_str.lower() or 'too many requests' in err_str.lower():
                logger.warning(f'[groq] {model} rate-limited, trying next model: {e}')
                continue
            else:
                logger.error(f'[groq] {model} failed: {e}')
                continue
    raise Exception('All Groq models failed or rate-limited')

BATCH_SYSTEM_PROMPT = """You extract candidate data from resumes.
Return ONLY compact JSON. No explanations.

For each resume, return:
{"n":"name","e":"email","p":"phone","s":"skills","x":"exp","g":"gender","sc":score,"ms":"matched","mr":"reason"}

Return: {"c":[{"n":"...",...}, ...]}"""

def extract_batch(resume_texts, jd):
    if not resume_texts:
        return []

    combined = '\n\n---RESUME-BREAK---\n\n'.join(
        (t or '')[:MAX_RESUME_CHARS] for t in resume_texts
    )
    prompt = f"""Target JD: {jd}

Resumes:
{combined}
"""
    messages = [
        {'role': 'system', 'content': BATCH_SYSTEM_PROMPT},
        {'role': 'user', 'content': prompt}
    ]

    try:
        t_start = time.time()
        response, used_model = call_groq_with_fallback(messages, max_tokens=1500)
        elapsed = time.time() - t_start
        content = response.choices[0].message.content
        data = json.loads(content)
        raw_candidates = data.get('c', []) or data.get('candidates', [])

        candidates = []
        for item in raw_candidates:
            if not isinstance(item, dict):
                continue
            name = item.get('n') or item.get('name') or ''
            email = item.get('e') or item.get('email') or ''
            phone = item.get('p') or item.get('phone') or ''
            skills = str(item.get('s') or item.get('skills') or '')[:200]
            exp = str(item.get('x') or item.get('experience') or '')[:50]
            gender = item.get('g') or item.get('gender') or 'Unknown'
            score = item.get('sc') if item.get('sc') is not None else item.get('match_score', 0)
            ms = str(item.get('ms') or item.get('matched_skills') or '')[:200]
            mr = str(item.get('mr') or item.get('match_reason') or '')[:300]

            candidates.append({
                "name": name,
                "email": email,
                "phone": phone,
                "skills": skills,
                "experience": exp,
                "gender": gender,
                "match_score": score,
                "matched_skills": ms,
                "match_reason": mr
            })

        logger.info(f"[groq-BATCH] Extracted {len(candidates)} candidates via {used_model} in {elapsed:.2f}s")
        return candidates
    except Exception as e:
        logger.warning(f"[groq-BATCH] batch failed: {e}")
        return []

SYSTEM_PROMPT = """Extract resume fields as JSON:
{"name":"","email":"","phone":"","skills":"","experience":"","gender":"","match_score":75,"matched_skills":"","match_reason":""}
Rules: Empty string if missing. Return JSON only."""

EMPTY = {
    "name": "", "email": "", "phone": "", "skills": "",
    "experience": "", "gender": "Unknown", "match_score": 0,
    "matched_skills": "", "match_reason": ""
}

_extraction_cache = {}

def extract_fields(resume_text):
    """Single resume extraction fallback."""
    if not resume_text or not resume_text.strip():
        return EMPTY
    try:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": resume_text[:MAX_RESUME_CHARS]}
        ]
        response, used_model = call_groq_with_fallback(messages, max_tokens=500)
        if response and response.choices and response.choices[0].message.content:
            data = json.loads(response.choices[0].message.content.strip())
            return {**EMPTY, **data}
    except Exception as e:
        logger.warning(f"[groq] single extraction failed: {e}")
    return EMPTY

def extract_fields_cached(resume_text, progress=None):
    if not resume_text or not resume_text.strip():
        if progress and hasattr(progress, 'increment'):
            progress.increment()
        return EMPTY
    key = hashlib.sha256(resume_text[:2000].encode('utf-8')).hexdigest()
    if key in _extraction_cache:
        logger.info("[ai] cache hit")
        if progress and hasattr(progress, 'increment'):
            progress.increment()
        return _extraction_cache[key]
    result = extract_fields(resume_text)
    _extraction_cache[key] = result
    if progress and hasattr(progress, 'increment'):
        progress.increment()
    return result
