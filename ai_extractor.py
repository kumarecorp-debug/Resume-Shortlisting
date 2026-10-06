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
FALLBACK_MODELS_ENV = os.environ.get("GROQ_MODELS_FALLBACK", "llama-3.3-70b-versatile,qwen/qwen3.8-27b,openai/gpt-oss-20b")
RPM_LIMIT = int(os.environ.get("GROQ_REQUESTS_PER_MINUTE", 25))
MAX_RESUME_CHARS = int(os.environ.get("MAX_RESUME_CHARS", 8000))

# Build model priority list cleanly
GROQ_MODELS = [PRIMARY_MODEL]
for m in FALLBACK_MODELS_ENV.split(","):
    m_clean = m.strip()
    if m_clean and m_clean not in GROQ_MODELS:
        GROQ_MODELS.append(m_clean)

WORKING_GROQ_MODEL = None

# Thread-safe RateLimiter class (FIX 2)
class RateLimiter:
    def __init__(self, requests_per_minute=25):
        self.min_interval = 60.0 / float(requests_per_minute)
        self.last_request_time = 0.0
        self.lock = threading.Lock()

    def wait(self):
        with self.lock:
            now = time.time()
            elapsed = now - self.last_request_time
            if elapsed < self.min_interval:
                sleep_time = self.min_interval - elapsed
                logger.info(f"[groq] rate limiter waited {sleep_time:.1f}s")
                time.sleep(sleep_time)
            self.last_request_time = time.time()

_rate_limiter = RateLimiter(requests_per_minute=RPM_LIMIT)

# Disable SDK internal retries (FIX 3)
groq_client = None
def get_groq_client():
    global groq_client
    api_k = os.environ.get("GROQ_API_KEY", GROQ_API_KEY)
    if not groq_client and api_k:
        try:
            from groq import Groq
            groq_client = Groq(
                api_key=api_k,
                max_retries=0,   # Disable SDK internal retries (FIX 3)
                timeout=20.0     # 20 sec timeout
            )
        except Exception as e:
            logger.warning(f"[groq] Client init error: {e}")
    return groq_client

SYSTEM_PROMPT = """You are a resume information extraction engine.
Given raw resume text, extract these fields and return ONLY valid JSON:
{
  "name": "full name",
  "email": "email address",
  "phone": "phone with country code if available",
  "skills": "comma-separated list of technical skills",
  "experience": "total years of experience as a number e.g. 5.5",
  "gender": "Male or Female or Unknown"
}
Rules:
- If a field is missing, use empty string "".
- Return valid JSON only. No markdown. No explanation."""

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
    Extract candidate fields from resume text.
    Tries Groq models in order with RateLimiter wait and manual 429 short backoff.
    Falls back to Gemini if all Groq attempts fail.
    """
    global WORKING_GROQ_MODEL
    if not resume_text or not resume_text.strip():
        return EMPTY

    # FIX 6: Truncate input resume text to MAX_RESUME_CHARS
    truncated_text = resume_text[:MAX_RESUME_CHARS]

    client = get_groq_client()
    if not client:
        return _extract_with_gemini(truncated_text)

    models_to_try = [WORKING_GROQ_MODEL] if WORKING_GROQ_MODEL else GROQ_MODELS

    for model in models_to_try:
        if not model:
            continue
        try:
            # FIX 2: Rate limiter wait before every call
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
                max_tokens=500
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
            if "not found" in err_str or "404" in err_str or "does not exist" in err_str:
                logger.info(f"[groq] model {model} not available, trying next")
                if WORKING_GROQ_MODEL == model:
                    WORKING_GROQ_MODEL = None
                continue
            elif "rate limit" in err_str or "429" in err_str or "rate_limit_exceeded" in err_str:
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
                        max_tokens=500
                    )
                    if response and response.choices and response.choices[0].message.content:
                        data = json.loads(response.choices[0].message.content.strip())
                        WORKING_GROQ_MODEL = model
                        logger.info(f"[groq] retry succeeded on {model}")
                        if isinstance(data.get("skills"), list):
                            data["skills"] = ", ".join(str(s) for s in data["skills"])
                        return {**EMPTY, **data}
                except Exception as ex2:
                    logger.warning(f"[groq] retry also failed on {model}: {ex2}")
                continue
            else:
                logger.warning(f"[groq] error on {model}: {e}")
                continue

    # All Groq models failed, fallback to Gemini
    return _extract_with_gemini(truncated_text)

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
