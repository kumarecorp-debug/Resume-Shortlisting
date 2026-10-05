import os
import json
import hashlib
import time
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

if os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
    import tempfile
    BASE_CACHE_DIR = Path(tempfile.gettempdir()) / 'cache'
else:
    BASE_CACHE_DIR = Path('cache')

EXCEL_CACHE_DIR = BASE_CACHE_DIR / 'excel_candidates'
PDF_CACHE_DIR = BASE_CACHE_DIR / 'pdf_extractions'

def ensure_cache_dirs():
    global EXCEL_CACHE_DIR, PDF_CACHE_DIR
    try:
        EXCEL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        PDF_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        import tempfile
        BASE_CACHE_DIR = Path(tempfile.gettempdir()) / 'cache'
        EXCEL_CACHE_DIR = BASE_CACHE_DIR / 'excel_candidates'
        PDF_CACHE_DIR = BASE_CACHE_DIR / 'pdf_extractions'
        try:
            EXCEL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            PDF_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.warning(f"[cache] Failed to create cache dir: {e}")

try:
    ensure_cache_dirs()
except Exception as e:
    logger.warning(f"[cache] Init warning: {e}")

def get_file_cache_key(file_path: str) -> str:
    try:
        stat = os.stat(file_path)
        raw = f"{file_path}|{stat.st_size}|{int(stat.st_mtime)}"
        return hashlib.md5(raw.encode('utf-8')).hexdigest()
    except Exception:
        return hashlib.md5(file_path.encode('utf-8')).hexdigest()

def get_bytes_cache_key(data_bytes: bytes, filename: str = "") -> str:
    h = hashlib.md5(data_bytes).hexdigest()
    clean_fn = "".join(c for c in filename if c.isalnum() or c in "._-")
    return f"{clean_fn}_{h}"

def get_cached_excel(file_path: str):
    key = get_file_cache_key(file_path)
    cache_file = EXCEL_CACHE_DIR / f"{key}.json"
    if cache_file.exists():
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                candidates = json.load(f)
            return candidates
        except Exception as e:
            logger.warning(f"[excel-cache] corrupt cache for {file_path}, rebuilding: {e}")
    return None

def set_cached_excel(file_path: str, candidates: list):
    try:
        key = get_file_cache_key(file_path)
        cache_file = EXCEL_CACHE_DIR / f"{key}.json"
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(candidates, f)
    except Exception as e:
        logger.warning(f"[excel-cache] write failed for {file_path}: {e}")

def get_cached_pdf(cache_key: str):
    cache_file = PDF_CACHE_DIR / f"{cache_key}.json"
    if cache_file.exists():
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"[pdf-cache] corrupt cache for {cache_key}: {e}")
    return None

def set_cached_pdf(cache_key: str, data: dict):
    try:
        cache_file = PDF_CACHE_DIR / f"{cache_key}.json"
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(data, f)
    except Exception as e:
        logger.warning(f"[pdf-cache] write failed for {cache_key}: {e}")

def cleanup_stale_cache(max_age_days=30):
    cutoff = time.time() - (max_age_days * 86400)
    for c_dir in [EXCEL_CACHE_DIR, PDF_CACHE_DIR]:
        if not c_dir.exists():
            continue
        for f in c_dir.iterdir():
            try:
                if f.is_file() and f.stat().st_mtime < cutoff:
                    f.unlink(missing_ok=True)
            except Exception:
                pass

try:
    cleanup_stale_cache()
except Exception as ex:
    logger.warning(f"[cache] Stale cache cleanup error: {ex}")
