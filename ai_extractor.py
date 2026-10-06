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

# PART 1 — Groq models prioritized by rate limit & capability
GROQ_MODELS = [
    'llama-3.1-8b-instant',       # 300 req/min
    'llama-3.3-70b-versatile',    # 30 req/min fallback
    'mixtral-8x7b-32768',         # fallback
    'qwen/qwen3.8-27b',           # last resort
]

if PRIMARY_MODEL and PRIMARY_MODEL not in GROQ_MODELS:
    GROQ_MODELS.insert(0, PRIMARY_MODEL)

ACTIVE_GROQ_MODEL = None

# PART 2 — Token-bucket Rate Limiter (25 requests per 60s)
class RateLimiter:
    def __init__(self, max_requests=25, window_seconds=60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.timestamps = deque()
        self.lock = threading.Lock()
    
    def acquire(self):
        with self.lock:
            now = time.time()
            # Drop timestamps older than window
            while self.timestamps and now - self.timestamps[0] > self.window_seconds:
                self.timestamps.popleft()
            # Wait if limit reached
            if len(self.timestamps) >= self.max_requests:
                sleep_until = self.timestamps[0] + self.window_seconds - now
                if sleep_until > 0:
                    logger.info(
                        f'[groq-rate] window full, waiting {sleep_until:.1f}s'
                    )
                    time.sleep(sleep_until)
                    return self.acquire()
            self.timestamps.append(time.time())

_groq_limiter = RateLimiter(max_requests=25, window_seconds=60)

groq_client = None
def get_groq_client():
    global groq_client
    api_k = os.environ.get("GROQ_API_KEY", GROQ_API_KEY)
    if not groq_client and api_k:
        try:
            from groq import Groq
            groq_client = Groq(
                api_key=api_k,
                max_retries=0,   # Disable SDK retries
                timeout=20.0
            )
        except Exception as e:
            logger.warning(f"[groq] Client init error: {e}")
    return groq_client

def pick_working_groq_model():
    """Return the first Groq model that accepts a test call."""
    client = get_groq_client()
    if not client:
        return GROQ_MODELS[0]
    for m in GROQ_MODELS:
        try:
            client.chat.completions.create(
                model=m,
                messages=[{'role': 'user', 'content': 'test'}],
                max_tokens=1,
                timeout=10
            )
            logger.info(f'[groq] selected model: {m}')
            return m
        except Exception as e:
            logger.warning(f'[groq] {m} unavailable: {e}')
            continue
    return GROQ_MODELS[-1]

def ensure_active_model():
    global ACTIVE_GROQ_MODEL
    if not ACTIVE_GROQ_MODEL:
        ACTIVE_GROQ_MODEL = pick_working_groq_model()
    return ACTIVE_GROQ_MODEL

# Startup probe
try:
    ACTIVE_GROQ_MODEL = pick_working_groq_model()
except Exception:
    ACTIVE_GROQ_MODEL = GROQ_MODELS[0]

# PART 3 — Batch extraction (5 resumes per call = 5x fewer requests)
BATCH_SYSTEM_PROMPT = """You extract candidate data from resumes.

You will receive {n} resumes separated by '---RESUME-BREAK---'.

For each resume, extract and return a JSON object with keys:
  name, email, phone, skills, experience, gender, 
  match_score (0-100), matched_skills, match_reason

Return a JSON object with a single key "candidates" containing 
an array of {n} objects in the same order as the input.

Return valid JSON only. No markdown."""

def extract_batch(resume_texts, jd):
    """Extract up to 5 resumes in one Groq call."""
    if not resume_texts:
        return []

    client = get_groq_client()
    if not client:
        return []

    model = ensure_active_model()
    combined = '\n\n---RESUME-BREAK---\n\n'.join(
        (t or '')[:MAX_RESUME_CHARS] for t in resume_texts
    )
    prompt = f"""Target JD: {jd}

Resumes:
{combined}
"""
    _groq_limiter.acquire()
    try:
        t_start = time.time()
        response = client.chat.completions.create(
            model=model,
            messages=[
                {'role': 'system', 
                 'content': BATCH_SYSTEM_PROMPT.format(n=len(resume_texts))},
                {'role': 'user', 'content': prompt}
            ],
            temperature=0,
            response_format={'type': 'json_object'},
            max_tokens=4000
        )
        elapsed = time.time() - t_start
        content = response.choices[0].message.content
        data = json.loads(content)
        candidates = data.get('candidates', [])
        logger.info(f"[groq-BATCH] Extracted {len(candidates)} candidates via {model} in {elapsed:.2f}s")
        return candidates
    except Exception as e:
        logger.warning(f"[groq-BATCH] batch failed on {model}: {e}")
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
    client = get_groq_client()
    if not client:
        return EMPTY
    model = ensure_active_model()
    _groq_limiter.acquire()
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": resume_text[:MAX_RESUME_CHARS]}
            ],
            temperature=0,
            response_format={"type": "json_object"},
            max_tokens=500
        )
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
