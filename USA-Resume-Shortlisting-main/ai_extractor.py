import os
import json
import logging
import time
import hashlib
import threading

logger = logging.getLogger(__name__)

# Configurable parameters
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "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")
PRIMARY_MODEL = os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant")
RPM_LIMIT = int(os.environ.get("GROQ_REQUESTS_PER_MINUTE", 25))
MAX_RESUME_CHARS = int(os.environ.get("MAX_RESUME_CHARS", 4000))

# FIX 1: Trim GROQ_MODELS to fast, high-quota models confirmed working
GROQ_MODELS = [
    "llama-3.1-8b-instant",  # fastest, high ITPM
    "qwen/qwen3.8-27b",      # confirmed working
]

if PRIMARY_MODEL and PRIMARY_MODEL not in GROQ_MODELS:
    GROQ_MODELS.insert(0, PRIMARY_MODEL)

WORKING_GROQ_MODEL = None

# Thread-safe RateLimiter class
class RateLimiter:
    def __init__(self, requests_per_minute=25):
        self.min_interval = 60.0 / float(requests_per_minute)
        self.last_request_time = 0.0
        self.lock = threading.Lock()

    def wait(self, multiplier=1.0):
        with self.lock:
            now = time.time()
            interval = self.min_interval * multiplier
            elapsed = now - self.last_request_time
            if elapsed < interval:
                sleep_time = interval - elapsed
                logger.info(f"[groq] rate limiter waited {sleep_time:.1f}s")
                time.sleep(sleep_time)
            self.last_request_time = time.time()

_rate_limiter = RateLimiter(requests_per_minute=RPM_LIMIT)

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

def verify_working_model():
    """Startup probe: test models once and select first working model (FIX 1)."""
    global WORKING_GROQ_MODEL
    client = get_groq_client()
    if not client:
        return
    for model in GROQ_MODELS:
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=5,
                timeout=5.0
            )
            if resp:
                WORKING_GROQ_MODEL = model
                logger.info(f"[groq] selected working model: {model}")
                return
        except Exception as e:
            logger.info(f"[groq] model {model} probe skipped ({e})")

# Run startup probe on import
try:
    verify_working_model()
except Exception:
    pass

SYSTEM_PROMPT = """Extract resume fields as JSON:
{"name":"","email":"","phone":"","skills":"","experience":"","gender":""}
Rules: Empty string if missing. Return JSON only."""

EMPTY = {
    "name": "", "email": "", "phone": "", "skills": "",
    "experience": "", "gender": "Unknown"
}

_extraction_cache = {}  # {sha256_of_text: candidate_dict}

def _extract_with_gemini(resume_text):
    gemini_key = os.environ.get("GEMINI_API_KEY")
    if not gemini_key:
        return EMPTY
    try:
        from google import genai
        from google.genai import types
        g_client = genai.Client(api_key=gemini_key)
        resp = g_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[SYSTEM_PROMPT, resume_text[:MAX_RESUME_CHARS]],
            config=types.GenerateContentConfig(
                temperature=0,
                response_mime_type="application/json"
            )
        )
        if resp and getattr(resp, 'text', None):
            data = json.loads(resp.text)
            logger.info("[gemini] extracted via gemini-2.5-flash")
            if isinstance(data.get("skills"), list):
                data["skills"] = ", ".join(str(s) for s in data["skills"])
            return {**EMPTY, **data}
    except Exception as e:
        logger.error(f"[gemini] fallback failed: {e}")
    return EMPTY

def extract_fields(resume_text):
    """
    Extract candidate fields from single resume text.
    """
    global WORKING_GROQ_MODEL
    if not resume_text or not resume_text.strip():
        return EMPTY

    truncated_text = resume_text[:MAX_RESUME_CHARS]
    client = get_groq_client()
    if not client:
        return _extract_with_gemini(truncated_text)

    models_to_try = [WORKING_GROQ_MODEL] if WORKING_GROQ_MODEL else GROQ_MODELS

    for model in models_to_try:
        if not model:
            continue
        try:
            _rate_limiter.wait()
            t_start = time.time()
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": truncated_text}
                ],
                temperature=0,
                response_format={"type": "json_object"},
                max_tokens=400
            )
            elapsed = time.time() - t_start

            if response and response.choices and response.choices[0].message.content:
                content = response.choices[0].message.content.strip()
                data = json.loads(content)
                WORKING_GROQ_MODEL = model
                logger.info(f"[groq] extracted via {model} in {elapsed:.2f}s")
                if isinstance(data.get("skills"), list):
                    data["skills"] = ", ".join(str(s) for s in data["skills"])
                return {**EMPTY, **data}

        except Exception as e:
            err_str = str(e).lower()
            if "not found" in err_str or "404" in err_str:
                logger.info(f"[groq] model {model} not available, trying next")
                if WORKING_GROQ_MODEL == model:
                    WORKING_GROQ_MODEL = None
                continue
            elif "rate limit" in err_str or "429" in err_str:
                logger.info(f"[groq] rate limited on {model}, waiting 3s and retrying once")
                time.sleep(3.0)
                try:
                    _rate_limiter.wait()
                    response = client.chat.completions.create(
                        model=model,
                        messages=[
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": truncated_text}
                        ],
                        temperature=0,
                        response_format={"type": "json_object"},
                        max_tokens=400
                    )
                    if response and response.choices and response.choices[0].message.content:
                        data = json.loads(response.choices[0].message.content.strip())
                        WORKING_GROQ_MODEL = model
                        return {**EMPTY, **data}
                except Exception:
                    pass
                continue
            else:
                logger.warning(f"[groq] error on {model}: {e}")
                continue

    return _extract_with_gemini(truncated_text)

# FIX 3: Batch Extraction function (up to 5 resumes in 1 API call)
def extract_batch(resumes_batch):
    """
    Send up to 5 resumes in one Groq call (FIX 3).
    Returns list of candidate dicts in exact order.
    """
    global WORKING_GROQ_MODEL
    if not resumes_batch:
        return []

    client = get_groq_client()
    if not client:
        return [extract_fields(r) for r in resumes_batch]

    combined = "\n\n---RESUME-BREAK---\n\n".join(
        r[:MAX_RESUME_CHARS] for r in resumes_batch
    )

    batch_prompt = f"""Extract each resume below as a JSON object.
Return a JSON object with key "candidates" containing an array of candidate objects in exact order.
Each candidate object must have keys: name, email, phone, skills, experience, gender.

Resumes:
{combined}"""

    models_to_try = [WORKING_GROQ_MODEL] if WORKING_GROQ_MODEL else GROQ_MODELS

    for model in models_to_try:
        if not model:
            continue
        try:
            _rate_limiter.wait(multiplier=1.2)
            t_start = time.time()
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": batch_prompt}],
                temperature=0,
                response_format={"type": "json_object"},
                max_tokens=2000
            )
            elapsed = time.time() - t_start

            if response and response.choices and response.choices[0].message.content:
                raw_json = response.choices[0].message.content.strip()
                data = json.loads(raw_json)
                cand_list = data.get("candidates", []) if isinstance(data, dict) else []
                if isinstance(cand_list, list) and len(cand_list) == len(resumes_batch):
                    WORKING_GROQ_MODEL = model
                    logger.info(f"[groq-BATCH] Extracted {len(cand_list)} resumes via {model} in {elapsed:.2f}s")
                    results = []
                    for c in cand_list:
                        if isinstance(c.get("skills"), list):
                            c["skills"] = ", ".join(str(s) for s in c["skills"])
                        results.append({**EMPTY, **c})
                    return results
        except Exception as e:
            logger.warning(f"[groq-BATCH] batch failed on {model}: {e}")
            continue

    # Fallback to individual single extractions if batching fails
    logger.info("[groq-BATCH] Fallback to individual resume extractions")
    return [extract_fields_cached(r) for r in resumes_batch]

def extract_fields_cached(resume_text):
    if not resume_text or not resume_text.strip():
        return EMPTY
    key = hashlib.sha256(resume_text[:2000].encode('utf-8')).hexdigest()
    if key in _extraction_cache:
        logger.info("[ai] cache hit")
        return _extraction_cache[key]
    result = extract_fields(resume_text)
    _extraction_cache[key] = result
    return result
