import os
import json
import logging
import hashlib

logger = logging.getLogger(__name__)

# Primary Groq Configuration
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "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")
DEFAULT_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")

GROQ_MODELS_TO_TRY = [
    DEFAULT_MODEL,
    "qwen/qwen3.8-27b",
    "openai/gpt-oss-20b",
    "openai/gpt-oss-120b"
]
WORKING_GROQ_MODEL = None

groq_client = None
if GROQ_API_KEY:
    try:
        from groq import Groq
        groq_client = Groq(api_key=GROQ_API_KEY)
        logger.info(f"[groq] Client initialized with primary model list {GROQ_MODELS_TO_TRY}")
    except Exception as e:
        logger.warning(f"[groq] Could not initialize Groq client: {e}")

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

def get_groq_client():
    global groq_client
    api_k = os.environ.get("GROQ_API_KEY", GROQ_API_KEY)
    if not groq_client and api_k:
        try:
            from groq import Groq
            groq_client = Groq(api_key=api_k)
        except Exception as e:
            logger.warning(f"[groq] Client init error: {e}")
    return groq_client

def extract_fields(resume_text):
    """
    Extract candidate fields from resume text.
    Tries Groq models first (with working model caching), falls back to Gemini if Groq fails.
    """
    global WORKING_GROQ_MODEL
    if not resume_text or not resume_text.strip():
        return EMPTY

    client = get_groq_client()

    # --- Try Groq first ---
    if client:
        models = [WORKING_GROQ_MODEL] if WORKING_GROQ_MODEL else GROQ_MODELS_TO_TRY
        for m_name in models:
            if not m_name: continue
            try:
                response = client.chat.completions.create(
                    model=m_name,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": resume_text[:12000]}
                    ],
                    temperature=0,
                    response_format={"type": "json_object"},
                    timeout=30
                )
                if response and response.choices and response.choices[0].message.content:
                    content = response.choices[0].message.content.strip()
                    data = json.loads(content)
                    WORKING_GROQ_MODEL = m_name
                    logger.info(f"[groq] extracted via {m_name}")
                    
                    # Normalize skills list if returned as array
                    if isinstance(data.get("skills"), list):
                        data["skills"] = ", ".join(str(s) for s in data["skills"])
                    return {**EMPTY, **data}
            except Exception as e:
                err_msg = str(e)
                if "model_not_found" in err_msg or "does not exist" in err_msg or "404" in err_msg:
                    logger.warning(f"[groq] model {m_name} not available, trying next fallback model...")
                    if WORKING_GROQ_MODEL == m_name:
                        WORKING_GROQ_MODEL = None
                else:
                    logger.warning(f"[groq] failed on {m_name}: {e}")

    # --- Fallback: Gemini (optional, single attempt on gemini-2.5-flash) ---
    gemini_key = os.environ.get("GEMINI_API_KEY")
    if gemini_key:
        try:
            from google import genai
            from google.genai import types
            g_client = genai.Client(api_key=gemini_key)
            resp = g_client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[SYSTEM_PROMPT, resume_text[:12000]],
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
            logger.error(f"[gemini] fallback also failed: {e}")

    return EMPTY

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
