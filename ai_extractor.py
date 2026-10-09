import os
import json
import logging
import time
import hashlib
import threading
import re
from collections import deque
from dotenv import load_dotenv

# Auto-load environment variables from .env if present
load_dotenv()

logger = logging.getLogger(__name__)

# Try new Google GenAI SDK first, fall back to legacy
try:
    from google import genai as new_genai
    HAS_NEW_GENAI = True
except ImportError:
    HAS_NEW_GENAI = False

try:
    import google.generativeai as genai
    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False
    genai = None

# Gemini Models configuration — updated for 2026 model availability
VALID_GEMINI_MODELS = [
    'gemini-3.8-flash',
    'gemini-3.5-flash-lite',
    'gemini-2.5-flash',
    'gemini-2.0-flash',
    'gemini-1.5-flash',
    'gemini-1.5-pro',
    'gemini-flash-latest'
]

GEMINI_PRIMARY_MODEL = os.getenv('GEMINI_PRIMARY_MODEL', 'gemini-3.8-flash')
GEMINI_FALLBACK_1 = os.getenv('GEMINI_FALLBACK_MODEL_1', 'gemini-3.5-flash-lite')
GEMINI_FALLBACK_2 = os.getenv('GEMINI_FALLBACK_MODEL_2', 'gemini-2.5-flash')
GEMINI_FALLBACK_3 = os.getenv('GEMINI_FALLBACK_MODEL_3', 'gemini-flash-latest')

raw_gemini_models = [
    GEMINI_PRIMARY_MODEL,
    GEMINI_FALLBACK_1,
    GEMINI_FALLBACK_2,
    GEMINI_FALLBACK_3
]

GEMINI_MODELS = [m for m in raw_gemini_models if m in VALID_GEMINI_MODELS]
for default_m in ['gemini-3.8-flash', 'gemini-3.5-flash-lite', 'gemini-2.5-flash', 'gemini-flash-latest']:
    if default_m not in GEMINI_MODELS:
        GEMINI_MODELS.append(default_m)

# Configurable Parameters & Batch Sizes
GROQ_API_KEY_1 = os.environ.get("GROQ_API_KEY_1", os.environ.get("GROQ_API_KEY", "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"))
GROQ_API_KEY_2 = os.environ.get("GROQ_API_KEY_2", GROQ_API_KEY_1)
GROQ_KEYS = [k for k in [GROQ_API_KEY_1, GROQ_API_KEY_2] if k and k.strip()]

_key_idx = 0
_key_lock = threading.Lock()

def get_next_groq_key():
    global _key_idx
    with _key_lock:
        key = GROQ_KEYS[_key_idx % len(GROQ_KEYS)]
        _key_idx += 1
        return key

MAX_RESUME_CHARS = int(os.environ.get("MAX_RESUME_CHARS", 2500))
MAX_CHARS_PER_RESUME = 2500
BATCH_SIZE = 2
BATCH_SIZE_GEMINI = 2
BATCH_SIZE_GROQ = 2

# Groq Preferred Models — updated for 2026 (Qwen available on free tier)
# Llama 3.x moved to enterprise-only; mixtral/gemma2 decommissioned
PREFERRED_GROQ_MODELS = [
    'qwen/qwen3.6-27b',
    'qwen/qwen3.8-27b',
    'openai/gpt-oss-20b',
    'openai/gpt-oss-120b',
    'meta-llama/llama-4-scout-17b-16e-instruct',
    'llama-3.3-70b-versatile',
    'llama-3.1-8b-instant',
]

groq_client = None

def get_groq_client():
    key = get_next_groq_key()
    try:
        from groq import Groq
        return Groq(
            api_key=key,
            max_retries=0,
            timeout=20.0
        )
    except Exception as e:
        logger.warning(f"[groq] Client init error: {e}")
        return None

ACTIVE_GROQ_MODELS = []

def discover_groq_models():
    """Query Groq API and filter against working preferred models."""
    global ACTIVE_GROQ_MODELS
    client = get_groq_client()
    if not client:
        ACTIVE_GROQ_MODELS = list(PREFERRED_GROQ_MODELS)
        return ACTIVE_GROQ_MODELS

    try:
        resp = client.models.list()
        available = {m.id for m in resp.data}
        chain = [m for m in PREFERRED_GROQ_MODELS if m in available]
        if not chain:
            chain = list(PREFERRED_GROQ_MODELS)
        ACTIVE_GROQ_MODELS = chain
        logger.info(f'[groq-startup] Active Groq models: {ACTIVE_GROQ_MODELS}')
    except Exception as e:
        logger.warning(f'[groq-startup] Model discovery error ({e}), using default preferred list')
        ACTIVE_GROQ_MODELS = list(PREFERRED_GROQ_MODELS)
    return ACTIVE_GROQ_MODELS

discover_groq_models()

def get_active_groq_models():
    global ACTIVE_GROQ_MODELS
    if not ACTIVE_GROQ_MODELS:
        return discover_groq_models()
    return ACTIVE_GROQ_MODELS

class RateLimiter:
    def __init__(self, max_per_min=25):
        self.max = max_per_min
        self.timestamps = deque()
        self.lock = threading.Lock()

    def acquire(self, status_callback=None):
        while True:
            with self.lock:
                now = time.time()
                while self.timestamps and now - self.timestamps[0] > 60:
                    self.timestamps.popleft()

                if len(self.timestamps) < self.max:
                    self.timestamps.append(now)
                    return

                oldest = self.timestamps[0]
                wait = max(1.0, 60 - (now - oldest) + 0.5)

            if status_callback and wait > 2:
                status_callback({
                    'waiting': True,
                    'wait_seconds': round(wait, 1),
                    'waiting_message': f'AI rate limit — waiting {wait:.0f}s'
                })

            logger.info(f'[groq-rate] waiting {wait:.1f}s')
            time.sleep(wait)

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

_ai_cache = {}

def get_batch_cache_key(resume_texts, jd):
    combined_hash = hashlib.sha256((f"{jd}:" + "||".join((t or '')[:1000] for t in resume_texts)).encode('utf-8')).hexdigest()
    return combined_hash

def call_gemini_with_fallback(prompt, status_callback=None):
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not gemini_key:
        raise Exception("Gemini API key missing")
    if not HAS_NEW_GENAI and not HAS_GEMINI:
        raise Exception("No Gemini SDK available")

    last_error = None

    for model_name in GEMINI_MODELS:
        for attempt in range(2):
            try:
                # Prefer new SDK (google-genai)
                if HAS_NEW_GENAI:
                    def _gen(mn=model_name, key=gemini_key):
                        client = new_genai.Client(api_key=key)
                        response = client.models.generate_content(
                            model=mn,
                            contents=prompt,
                            config=new_genai.types.GenerateContentConfig(
                                response_mime_type='application/json'
                            )
                        )
                        return response
                else:
                    genai.configure(api_key=gemini_key, transport='rest')
                    def _gen(mn=model_name):
                        model = genai.GenerativeModel(mn)
                        return model.generate_content(
                            prompt,
                            generation_config={"response_mime_type": "application/json"}
                        )

                res = call_with_timeout(_gen, timeout_sec=60)
                # Handle both SDK response formats
                text = None
                if hasattr(res, 'text') and res.text:
                    text = res.text
                elif hasattr(res, 'candidates') and res.candidates:
                    try:
                        text = res.candidates[0].content.parts[0].text
                    except Exception:
                        pass
                if text:
                    logger.info(f'[gemini] succeeded via {model_name}')
                    return text, model_name
            except Exception as e:
                err_str = str(e).lower()
                last_error = e

                if '404' in err_str or 'not found' in err_str or '503' in err_str or 'unavailable' in err_str or 'capacity' in err_str:
                    logger.warning(f"[gemini] model {model_name} unavailable ({e}), trying next model")
                    break

                if '429' in err_str or 'resourceexhausted' in err_str or 'quota' in err_str or 'rate' in err_str:
                    # Extract retry delay
                    retry_after = 5
                    if hasattr(e, 'retry_delay') and hasattr(e.retry_delay, 'seconds'):
                        retry_after = e.retry_delay.seconds
                    # If retry delay is huge (quota exhausted for the day), skip this model entirely
                    if retry_after > 120:
                        logger.warning(f"[gemini] model {model_name} daily quota exhausted (retry in {retry_after}s), skipping")
                        break
                    logger.warning(f"[gemini] rate limited, waiting {retry_after}s for {model_name}")
                    if status_callback:
                        status_callback({'waiting': True, 'wait_seconds': retry_after + 2, 'waiting_message': f'Gemini rate limit — waiting {retry_after+2}s'})
                    time.sleep(retry_after + 2)
                    continue

                logger.warning(f"[gemini] error for model {model_name}: {e}")
                break

    raise Exception(f"All Gemini models failed: {last_error}")

def call_groq_with_fallback(messages, max_tokens=1500, timeout_sec=30, status_callback=None):
    client = get_groq_client()
    if not client:
        raise Exception("Groq client not initialized")

    models_to_try = get_active_groq_models()
    last_error = None

    # Models that support json_object response format
    JSON_OBJECT_MODELS = {
        'llama-3.3-70b-versatile', 'llama-3.1-8b-instant',
        'mixtral-8x7b-32768', 'gemma2-9b-it'
    }

    for model in models_to_try:
        for attempt in range(2):
            try:
                _groq_limiter.acquire(status_callback=status_callback)
                # Only use json_object mode for models that support it
                use_json_format = model in JSON_OBJECT_MODELS
                def _api_call(mod=model, use_json=use_json_format):
                    kwargs = {
                        'model': mod,
                        'messages': messages,
                        'temperature': 0,
                        'max_tokens': max_tokens
                    }
                    if use_json:
                        kwargs['response_format'] = {'type': 'json_object'}
                    return client.chat.completions.create(**kwargs)

                response = call_with_timeout(_api_call, timeout_sec=timeout_sec)
                logger.info(f'[groq] succeeded via {model}')
                return response, model
            except Exception as e:
                err_str = str(e)
                err_lower = err_str.lower()
                last_error = e

                if 'rate limit' in err_lower or '429' in err_lower or 'too many requests' in err_lower:
                    match = re.search(r'try again in (\d+\.?\d*)s', err_str, re.IGNORECASE)
                    wait = float(match.group(1)) + 2 if match else 20.0
                    logger.warning(f"[groq] rate limited on {model}, waiting {wait:.1f}s")
                    if status_callback:
                        status_callback({'waiting': True, 'wait_seconds': round(wait, 1), 'waiting_message': f'Groq rate limit — waiting {round(wait)}s'})
                    time.sleep(wait)
                    # Retry once after backoff
                    try:
                        _groq_limiter.acquire(status_callback=status_callback)
                        response = call_with_timeout(_api_call, timeout_sec=timeout_sec)
                        logger.info(f'[groq] retry succeeded via {model}')
                        return response, model
                    except Exception as e_retry:
                        logger.warning(f'[groq] retry failed for {model}: {e_retry}')
                        last_error = e_retry
                        continue
                elif '404' in err_lower or 'not exist' in err_lower:
                    logger.warning(f'[groq] {model}: model 404 does not exist')
                    break
                elif 'decommission' in err_lower:
                    logger.warning(f'[groq] {model}: model decommissioned')
                    break
                else:
                    logger.warning(f'[groq] {model} failed: {e}')
                    break

    raise Exception(f'All Groq models failed: {last_error}')

BATCH_SYSTEM_PROMPT = """You extract candidate data from resumes.

Return ONLY compact JSON. No explanations. No markdown.

For each resume return an object with SHORT keys:
  n  = name
  e  = email
  p  = phone
  s  = skills (comma-separated, max 150 chars)
  x  = experience (years or short text, max 30 chars)
  g  = gender (Male/Female/Unknown)
  sc = match_score (0-100 integer)
  ms = matched_skills (comma-separated, max 100 chars)
  mr = match_reason (max 80 chars)

SCORING RULES:
  - If resume has NO skills matching the target JD -> sc=0
  - If resume has SOME matching skills -> sc proportional to percentage of JD skills matched (e.g., 2 of 4 = 50)
  - NEVER assign sc between 30 and 50 for unrelated resumes
  - If you cannot determine a match, set sc=0 and mr="No match"

Return: {"c":[{"n":"...","e":"...",...}, ...]}
"""

KEY_MAP = {
    'n': 'name', 'e': 'email', 'p': 'phone',
    's': 'skills', 'x': 'experience', 'g': 'gender',
    'sc': 'match_score', 'ms': 'matched_skills',
    'mr': 'match_reason',
}

def expand_keys(item):
    if not isinstance(item, dict):
        return {}
    return {KEY_MAP.get(k, k): v for k, v in item.items()}

def extract_batch(resume_texts, jd, status_callback=None):
    if not resume_texts:
        return []

    cache_key = get_batch_cache_key(resume_texts, jd)
    if cache_key in _ai_cache:
        logger.info(f"[extract] cache hit for batch {cache_key[:8]}")
        return _ai_cache[cache_key]

    combined = '\n\n---RESUME-BREAK---\n\n'.join(
        (t or '')[:MAX_RESUME_CHARS] for t in resume_texts
    )
    prompt = f"{BATCH_SYSTEM_PROMPT}\n\nTarget JD: {jd}\n\nResumes:\n{combined}\n"

    raw_candidates = []
    used_provider = "none"

    # 1. Try Groq as PRIMARY extractor
    messages = [
        {'role': 'system', 'content': BATCH_SYSTEM_PROMPT},
        {'role': 'user', 'content': f"Target JD: {jd}\n\nResumes:\n{combined}"}
    ]
    try:
        response, used_model = call_groq_with_fallback(messages, max_tokens=1500, status_callback=status_callback)
        content = response.choices[0].message.content
        data = json.loads(content)
        raw_candidates = data.get('c', []) or data.get('candidates', [])
        used_provider = f"groq ({used_model})"
    except Exception as e_groq:
        logger.warning(f"[groq] Groq primary extraction failed ({e_groq}), falling back to Gemini")
        raw_candidates = []

    # 2. Try Gemini as OPTIONAL FALLBACK if Groq returned no candidates or failed
    if not raw_candidates:
        gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
        if gemini_key and (HAS_NEW_GENAI or HAS_GEMINI):
            try:
                text_resp, used_model = call_gemini_with_fallback(prompt, status_callback=status_callback)
                # Strip markdown code fences if present
                text_clean = text_resp.strip()
                if text_clean.startswith('```'):
                    import re as _re
                    text_clean = _re.sub(r'^```[a-z]*\n?', '', text_clean)
                    text_clean = _re.sub(r'\n?```$', '', text_clean).strip()
                data = json.loads(text_clean)
                raw_candidates = data.get('c', []) or data.get('candidates', [])
                used_provider = f"gemini ({used_model})"
            except Exception as e_gemini:
                logger.error(f"[gemini] Gemini fallback extraction failed: {e_gemini}")
                raw_candidates = []
        else:
            if not gemini_key:
                logger.warning("[gemini] GEMINI_API_KEY missing — skipped fallback")

    candidates = []
    for raw in raw_candidates:
        if not isinstance(raw, dict):
            continue
        item = expand_keys(raw)
        name = item.get('name') or ''
        email = item.get('email') or ''
        phone = item.get('phone') or ''
        skills = str(item.get('skills') or '')[:200]
        exp = str(item.get('experience') or '')[:50]
        gender = item.get('gender') or 'Unknown'
        score = item.get('match_score') if item.get('match_score') is not None else 0
        ms = str(item.get('matched_skills') or '')[:200]
        mr = str(item.get('match_reason') or '')[:300]

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

    # FIX 5: Better logging
    if candidates:
        logger.info(f"[extract] {len(candidates)} candidates via {used_provider}")
        _ai_cache[cache_key] = candidates
    else:
        logger.warning(f"[extract] all providers failed for batch")

    return candidates

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
        gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
        if HAS_GEMINI and gemini_key:
            try:
                text_resp, used_model = call_gemini_with_fallback(f"{SYSTEM_PROMPT}\n\nResume:\n{resume_text[:MAX_RESUME_CHARS]}")
                data = json.loads(text_resp)
                return {**EMPTY, **data}
            except Exception:
                pass
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": resume_text[:MAX_RESUME_CHARS]}
        ]
        response, used_model = call_groq_with_fallback(messages, max_tokens=500)
        if response and response.choices and response.choices[0].message.content:
            data = json.loads(response.choices[0].message.content.strip())
            return {**EMPTY, **data}
    except Exception as e:
        logger.warning(f"[extract] single extraction failed: {e}")
    return EMPTY

def extract_fields_cached(resume_text, progress=None):
    if not resume_text or not resume_text.strip():
        if progress and hasattr(progress, 'increment'):
            progress.increment()
        return EMPTY
    key = hashlib.sha256(resume_text[:2000].encode('utf-8')).hexdigest()
    if key in _extraction_cache:
        logger.info("[extract] cache hit")
        if progress and hasattr(progress, 'increment'):
            progress.increment()
        return _extraction_cache[key]
    result = extract_fields(resume_text)
    _extraction_cache[key] = result
    if progress and hasattr(progress, 'increment'):
        progress.increment()
    return result
