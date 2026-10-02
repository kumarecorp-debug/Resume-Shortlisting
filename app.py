from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
import re
from datetime import datetime, timezone
import pandas as pd
from io import StringIO
import sys
import logging
from contextlib import redirect_stdout, redirect_stderr
from functools import wraps
import RS_Project
import gmail_search
import os
import db
import db_copied_history
from supabase import create_client, Client

from jinja2 import ChoiceLoader, FileSystemLoader

project_root = os.path.dirname(os.path.abspath(__file__))
template_dir = os.path.join(project_root, 'templates')
static_dir = os.path.join(project_root, 'static')

app = Flask(__name__, template_folder=template_dir, static_folder=static_dir, static_url_path='/static')
app.secret_key = 'your-secret-key-here-ecorp-resume'

possible_template_dirs = [
    template_dir,
    os.path.join(project_root, 'templates'),
    os.path.join(project_root, 'USA-Resume-Shortlisting-main', 'templates'),
    os.path.join(os.path.dirname(project_root), 'templates'),
    os.path.join(os.path.dirname(project_root), 'USA-Resume-Shortlisting-main', 'templates'),
    os.path.join(os.getcwd(), 'templates')
]
existing_template_dirs = []
for d in possible_template_dirs:
    if d and os.path.exists(d) and d not in existing_template_dirs:
        existing_template_dirs.append(d)

if existing_template_dirs:
    app.jinja_loader = ChoiceLoader([FileSystemLoader(d) for d in existing_template_dirs])

from flask import send_from_directory

@app.route('/static/<path:filename>')
def serve_static_fallback(filename):
    possible_dirs = [
        static_dir,
        os.path.join(project_root, 'static'),
        os.path.join(os.path.dirname(project_root), 'static'),
        os.path.join(os.getcwd(), 'static')
    ]
    for s_dir in possible_dirs:
        if s_dir and os.path.exists(os.path.join(s_dir, filename)):
            return send_from_directory(s_dir, filename)
    return send_from_directory(static_dir, filename)

# Supabase Authentication Setup
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://fvbctgxwjrctcssckggp.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_ANON_KEY") or os.environ.get("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImZ2YmN0Z3h3anJjdGNzc2NrZ2dwIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTAxNDc1MDUsImV4cCI6MjEwNTcyMzUwNX0.Nz0G-FmUDvzKOVTmIhu8EFpYjH5EDjZO-JuSwylRCVU")
supabase_client: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

if not os.environ.get("VERCEL"):
    try:
        os.chdir(project_root)
    except Exception:
        pass

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            flash('Please sign in to access the resume shortlisting tool.', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user' in session:
        return redirect(url_for('process'))
        
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '').strip()
        
        if not email or not password:
            flash('Email and Password are required.', 'error')
            return render_template('login.jinja')
            
        try:
            res = supabase_client.auth.sign_in_with_password({
                "email": email,
                "password": password
            })
            if res.user:
                session['user'] = {
                    'id': res.user.id,
                    'email': res.user.email
                }
                flash(f'Welcome back, {res.user.email}!', 'success')
                return redirect(url_for('process'))
        except Exception as e:
            err_str = str(e)
            logging.warning(f"Supabase login failed for {email}: {err_str}")
            if "Invalid login credentials" in err_str:
                err_msg = "Invalid email or password. Please verify the credentials created in your Supabase Auth Dashboard."
            elif "Email not confirmed" in err_str:
                err_msg = "Email address has not been confirmed yet in Supabase. Please confirm it or toggle 'Auto Confirm Emails' in Supabase."
            elif "timed out" in err_str.lower() or "timeout" in err_str.lower():
                err_msg = "Network Connection Timeout. Supabase servers took too long to respond. Please check your internet connection and try clicking Sign In again."
            else:
                err_msg = err_str
            flash(f'Login failed: {err_msg}', 'error')
            
    return render_template('login.jinja')

@app.route('/logout')
def logout():
    session.pop('user', None)
    try:
        supabase_client.auth.sign_out()
    except Exception:
        pass
    flash('You have been logged out successfully.', 'success')
    return redirect(url_for('login'))

def normalize_phone(p):
    if not p: return ""
    return re.sub(r'\D', '', str(p))

def matches_phone(candidate, search_term):
    search_digits = normalize_phone(search_term)
    cand_phone = str(candidate.get("Phone", ""))
    cand_digits = normalize_phone(cand_phone)
    result = False
    if len(search_digits) >= 10 and len(cand_digits) >= 10:
        result = (search_digits[-10:] == cand_digits[-10:])
    elif search_digits and cand_digits:
        result = (search_digits == cand_digits)
    logging.info(f"[phone-match] cand_phone='{cand_phone}' cand_digits='{cand_digits}' search_digits='{search_digits}' match={result}")
    return result

def normalize_email(e):
    if not e: return ""
    return str(e).strip().lower()

def matches_email(candidate, search_term):
    t = normalize_email(search_term)
    cand_email = normalize_email(candidate.get("Email", ""))
    result = (t != "" and t == cand_email)
    logging.info(f"[email-match] cand_email='{cand_email}' search_email='{t}' match={result}")
    return result

def matches_name(candidate, search_term):
    words = [w.lower() for w in str(search_term).strip().split() if w]
    cand_name = str(candidate.get("Name", "")).lower()
    if not words or not cand_name:
        return False
    # Check word token matching
    result = all(w in cand_name for w in words)
    logging.info(f"[name-match] cand_name='{cand_name}' search_words={words} match={result}")
    return result

def parse_experience_years(text):
    """
    Parse "X years" / "X yrs" / "X years Y months" into a float.
    Returns None if unparseable.
    """
    if not text:
        return None
    t = str(text).lower().strip()
    
    # Ignore obvious non-values
    if t in ("", "n/a", "na", "none", "null", "not mentioned", "unknown"):
        return None
    
    # Pattern: "X years", "X+ years", "X.Y years", "X yrs"
    years_match = re.search(r'(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?|y)\b', t)
    months_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:months?|mos?)\b', t)
    
    years = float(years_match.group(1)) if years_match else 0.0
    months = float(months_match.group(1)) if months_match else 0.0
    
    total = years + (months / 12.0)
    
    # If we found only months, that's OK
    if years == 0 and months > 0:
        return round(months / 12.0, 1)
    
    # If we found nothing, try to grab a bare number or number within text
    if not years_match and not months_match:
        bare = re.search(r'(\d+(?:\.\d+)?)', t)
        if bare:
            return float(bare.group(1))
        return None
    
    return round(total, 1)

def filter_candidates(candidates, term):
    """
    Filters candidates depending on search mode (email, phone, name, or keyword).
    For identifier modes (email, phone, name): returns matching candidates,
    falling back to all extracted candidates if strict matching yields empty results.
    """
    mode = gmail_search.detect_search_mode(term)
    term_str = term.strip()
    
    if mode == "email":
        matched = []
        for c in candidates:
            if matches_email(c, term_str):
                c["Match Score"] = 100
                c["Match Reason"] = f"Exact Email match for {term_str}."
                matched.append(c)
        if matched:
            return matched, mode, len(matched), 0

    if mode == "phone":
        matched = []
        for c in candidates:
            if matches_phone(c, term_str):
                c["Match Score"] = 100
                c["Match Reason"] = f"Exact Phone match for {term_str}."
                matched.append(c)
        if matched:
            return matched, mode, len(matched), 0

    if mode == "name":
        matched = []
        for c in candidates:
            if matches_name(c, term_str):
                c["Match Score"] = 100
                c["Match Reason"] = f"Exact Name match for {term_str}."
                matched.append(c)
        if matched:
            return matched, mode, len(matched), 0

    return candidates, mode, len(candidates), 0

@app.template_filter('format_received_date')
def format_received_date_filter(val):
    if not val:
        return "Recent"
    try:
        from datetime import datetime
        s_val = str(val).split('T')[0]
        d = datetime.fromisoformat(s_val)
        now = datetime.now()
        if d.year == now.year:
            return d.strftime('%b %d')
        return d.strftime('%b %d, %Y')
    except Exception:
        return "Recent"

import time
_copied_emails_cache = {}  # { mailbox: (timestamp, set) }

def get_cached_copied_emails(mailbox):
    clean_mb = (mailbox or '').strip().lower()
    now = time.time()
    if clean_mb in _copied_emails_cache:
        ts, cached_set = _copied_emails_cache[clean_mb]
        if now - ts < 60:
            return cached_set
    
    copied_set = set()
    try:
        client = db.get_supabase()
        if client:
            res = client.table("copied_history").select("candidate_email").eq("mailbox_account", clean_mb).execute()
            for r in (res.data or []):
                em = (r.get("candidate_email") or "").strip().lower()
                if em:
                    copied_set.add(em)
    except Exception as e_c:
        logging.warning(f"Error fetching copied emails for {clean_mb}: {e_c}")
    
    _copied_emails_cache[clean_mb] = (now, copied_set)
    return copied_set

def compute_date_display(preset, df_str, dt_str):
    if not preset or preset == 'any':
        return None
    try:
        from datetime import datetime, timedelta
        now = datetime.now()
        if preset == 'today':
            return f"Today ({now.strftime('%b %d, %Y')})"
        elif preset == 'yesterday':
            yest = now - timedelta(days=1)
            return f"Yesterday ({yest.strftime('%b %d, %Y')})"
        elif preset == '7d':
            from_d = (now - timedelta(days=6)).strftime('%b %d')
            to_d = now.strftime('%b %d, %Y')
            return f"Last 7 days ({from_d} – {to_d})"
        elif preset == '14d':
            from_d = (now - timedelta(days=13)).strftime('%b %d')
            to_d = now.strftime('%b %d, %Y')
            return f"Last 14 days ({from_d} – {to_d})"
        elif preset == '30d':
            from_d = (now - timedelta(days=29)).strftime('%b %d')
            to_d = now.strftime('%b %d, %Y')
            return f"Last 30 days ({from_d} – {to_d})"
        elif df_str and str(df_str).strip():
            d_from = datetime.fromisoformat(str(df_str).strip().split('T')[0]).strftime('%b %d, %Y')
            if dt_str and str(dt_str).strip():
                d_to = datetime.fromisoformat(str(dt_str).strip().split('T')[0]).strftime('%b %d, %Y')
                return f"{d_from} – {d_to}"
            else:
                return f"Since {d_from}"
    except Exception:
        pass
    return None

def execute_full_candidate_search(job_query, selected_account, max_candidates=200, date_preset=None, date_from=None, date_to=None, include_excel=True):
    resume_folder = RS_Project.RESUME_FOLDER
    try:
        if not os.path.exists(resume_folder):
            os.makedirs(resume_folder, exist_ok=True)
        test_file = os.path.join(resume_folder, "test_write.txt")
        with open(test_file, 'w') as f:
            f.write("Test")
        os.remove(test_file)
    except Exception:
        import tempfile
        resume_folder = os.path.join(tempfile.gettempdir(), "Resumes")
        os.makedirs(resume_folder, exist_ok=True)
        RS_Project.RESUME_FOLDER = resume_folder
        RS_Project.OUTPUT_CSV = os.path.join(resume_folder, "resume_analysis.csv")

    scan_summary = {'pdf': 0, 'docx': 0, 'xlsx': 0, 'xls': 0, 'xlsx_candidates': 0}

    stdout_buffer = StringIO()
    stderr_buffer = StringIO()
    with redirect_stdout(stdout_buffer), redirect_stderr(stderr_buffer):
        try:
            RS_Project.main(job_query, account_email=selected_account, max_candidates=max_candidates, date_preset=date_preset, date_from=date_from, date_to=date_to, include_excel=include_excel)
        except Exception as e:
            logging.error(f"Error in RS_Project.main: {e}")

    summary_file = os.path.join(RS_Project.RESUME_FOLDER, "scan_summary.json")
    if os.path.exists(summary_file):
        try:
            import json
            with open(summary_file, 'r', encoding='utf-8') as sf:
                scan_summary = json.load(sf)
        except Exception as e_sum:
            logging.warning(f"Error reading scan_summary.json: {e_sum}")

    output_csv = RS_Project.OUTPUT_CSV
    if not os.path.exists(output_csv):
        return pd.DataFrame(), scan_summary

    try:
        df = pd.read_csv(output_csv)
        if df.empty:
            return pd.DataFrame(), scan_summary
    except Exception as e:
        logging.error(f"Error reading output CSV: {e}")
        return pd.DataFrame(), scan_summary

    if not df.empty:
        # Convert DataFrame to list of dicts to run precision filtering
        records = df.to_dict(orient='records')
        filtered_records, search_mode, exact_cnt, approx_cnt = filter_candidates(records, job_query)
        
        # Sort candidates strictly by Match Score DESC (FIX 2)
        filtered_records.sort(key=lambda c: int(re.sub(r'[^\d]', '', str(c.get("Match Score", 0))) or 0), reverse=True)
        
        # Re-assign continuous ranks after sorting
        for idx, rec in enumerate(filtered_records):
            rec["Rank"] = idx + 1
            
        df = pd.DataFrame(filtered_records)

        def reorder_skills(row):
            matched = str(row.get('Matched Skills', '')).split(',')
            all_skills = str(row.get('Skill Set', '')).split(',')
            matched_clean = [m.strip().lower() for m in matched if m.strip()]
            first_part = []
            second_part = []
            for s in all_skills:
                s_clean = s.strip()
                if not s_clean: continue
                if any(m in s_clean.lower() or s_clean.lower() in m for m in matched_clean):
                    first_part.append(s_clean)
                else:
                    second_part.append(s_clean)
            return ', '.join(first_part + second_part)

        if 'Skill Set' in df.columns:
            df['Skill Set'] = df.apply(reorder_skills, axis=1)

        gender_detector = None
        try:
            import gender_guesser.detector as gender
            gender_detector = gender.Detector()
        except ImportError:
            pass

        def guess_gender(name):
            name_parts = str(name).strip().split()
            if not name_parts or name.lower() in ['verified candidate', 'candidate', 'n/a']:
                return 'Male'
            first_name = name_parts[0].capitalize()
            first_name_lower = first_name.lower()
            female_names = {
                'pooja', 'priya', 'neha', 'anjali', 'swati', 'divya', 'kavita', 'deepa', 'megha', 'shweta',
                'sunita', 'anita', 'kiran', 'rekha', 'rashmi', 'sneha', 'jyoti', 'monika', 'payal', 'richa',
                'sonam', 'smita', 'bhavna', 'sapna', 'archana', 'simran', 'preeti', 'renu', 'seema', 'tanvi',
                'radha', 'sheetal', 'harshita', 'apoorva', 'srishti', 'kriti', 'nisha', 'sakshi', 'shikha',
                'shipra', 'garima', 'pallavi', 'surabhi', 'saloni', 'sonia', 'vandana', 'komal', 'namrata'
            }
            male_exceptions = {
                'karan', 'bhavin', 'gulab', 'sudhakar', 'nagarjuna', 'krishna', 'rama', 'aditya', 'surya',
                'shiva', 'pavan', 'vijay', 'ajay', 'sanjay', 'jay', 'rahul', 'amit', 'sumit', 'vince',
                'anil', 'sunil', 'rajesh', 'suresh', 'ramesh', 'dinesh', 'manish', 'mukesh', 'nilesh',
                'harshita', 'gopal', 'mohan', 'sohan', 'rohan', 'varun', 'tarun', 'arun', 'alok', 'ashok'
            }
            if first_name_lower in female_names:
                return 'Female'
            if first_name_lower in male_exceptions:
                return 'Male'
            if gender_detector:
                gen = gender_detector.get_gender(first_name)
                if gen in ['male', 'mostly_male']: return 'Male'
                if gen in ['female', 'mostly_female']: return 'Female'
            if first_name_lower.endswith(('a', 'i')) and len(first_name_lower) > 3: 
                return 'Female'
            return 'Male'

        if 'Name' in df.columns:
            if 'Gender' not in df.columns:
                df['Gender'] = df['Name'].apply(guess_gender)
            else:
                df['Gender'] = df.apply(
                    lambda row: guess_gender(row['Name']) 
                    if pd.isna(row.get('Gender')) or str(row.get('Gender')).strip().lower() in ['unknown', 'n/a', ''] 
                    else row['Gender'], 
                    axis=1
                )

    return df, scan_summary

@app.route('/', methods=['GET', 'POST'])
@app.route('/process', methods=['GET', 'POST'])
@login_required
def process():
    available_accounts = list(RS_Project.SUPPORTED_ACCOUNTS.values())
    default_account = "recruiter@ecorptrainings.com"
    
    # Support URL parameters for GET searches (e.g. /process?jd=sql&date_preset=7d&exp=5)
    is_get_search = request.method == 'GET' and (request.args.get('jd') or request.args.get('job_query'))

    if request.method == 'POST' or is_get_search:
        import uuid
        job_query = (request.form.get('job_query') or request.args.get('jd') or request.args.get('job_query') or '').strip()
        raw_acct = request.form.get('account_email') or request.form.get('mailbox') or request.args.get('account_email') or request.args.get('mailbox') or session.get('selected_account') or default_account
        if isinstance(raw_acct, dict):
            selected_account = raw_acct.get('email', default_account)
        else:
            selected_account = str(raw_acct).strip() if raw_acct else default_account
        session['selected_account'] = selected_account

        time_window = request.form.get('time_window') or request.args.get('time_window') or request.form.get('date_preset') or request.args.get('date_preset') or 'any'
        date_preset = time_window
        date_from = request.form.get('date_from') or request.args.get('date_from') or ''
        date_to = request.form.get('date_to') or request.args.get('date_to') or ''
        show_mode = request.form.get('show_mode') or request.args.get('show_mode') or 'all'

        include_excel_val = request.form.get('include_excel') if request.method == 'POST' else request.args.get('include_excel')
        include_excel = False if include_excel_val in ('0', 'false', 'False') else True

        if time_window == 'custom' and date_from and date_to:
            if date_from > date_to:
                flash('From date must be before or equal to To date.', 'error')

        if not job_query:
            flash('Please enter a job description, role, or keywords.', 'error')
            return render_template(
                'process.jinja',
                job_query=None,
                job_role=None,
                selected_account=selected_account,
                available_accounts=available_accounts,
                table_data=[],
                columns=[],
                search_id=None,
                total_matches=0,
                page_size=25,
                time_window=time_window,
                date_preset=date_preset,
                date_from=date_from,
                date_to=date_to,
                show_mode=show_mode,
                include_excel=include_excel,
                scan_summary=None
            )

        min_exp_raw = request.form.get('min_exp') or request.args.get('min_exp') or request.args.get('exp')
        try:
            min_exp = float(min_exp_raw) if min_exp_raw is not None and str(min_exp_raw).strip() != '' else None
        except (ValueError, TypeError):
            min_exp = None

        max_candidates = int(request.form.get('max_candidates') or request.args.get('max_candidates') or 50)
        user_search_mode = request.form.get('search_mode') or request.args.get('search_mode') or ('history' if time_window != 'any' else 'live')

        # SHOW = COPIED MODE: Filter by copied_history.copied_at timestamp (No Gmail / Gemini API calls)
        if show_mode == 'copied':
            copied_res = db_copied_history.get_copied_candidates_by_time_window(
                mailbox_account=selected_account,
                job_query=job_query,
                time_window=time_window,
                date_from=date_from,
                date_to=date_to,
                min_exp=min_exp
            )
            all_records = copied_res.get('candidates', [])
            total_matches = len(all_records)
            search_id = str(uuid.uuid4())
            db.cache_search_results(search_id, all_records)
            date_display = compute_date_display(time_window, date_from, date_to)

            logging.info(f"[search] mode={user_search_mode} show={show_mode} date_field=copied_at range={date_from}..{date_to} mailbox={selected_account} jd={job_query} total={total_matches}")

            return render_template(
                'process.jinja',
                job_query=job_query,
                job_role=job_query,
                selected_account=selected_account,
                available_accounts=available_accounts,
                table_data=all_records,
                columns=["Rank", "Name", "Gender", "Email", "Phone", "Experience", "Skill Set", "Matched Skills", "Match Score", "Match Reason"],
                search_id=search_id,
                total_matches=total_matches,
                max_candidates=max_candidates,
                min_exp=min_exp,
                time_window=time_window,
                date_preset=date_preset,
                date_from=date_from,
                date_to=date_to,
                show_mode=show_mode,
                search_mode=user_search_mode,
                search_source='copied_history',
                date_field='copied_at',
                explanation='Candidates you copied in this window',
                date_display=date_display,
                resolved_gmail_query=f"DB copied_history: copied_at in window {time_window}",
                include_excel=include_excel,
                scan_summary={"pdf": 0, "docx": 0, "xlsx": 0, "xls": 0, "xlsx_candidates": 0, "source": "copied"}
            )

        # HISTORY SEARCH MODE: If user chose history OR if a Time Window filter is active (!= 'any')
        if user_search_mode == 'history' or (user_search_mode != 'live' and time_window and time_window != 'any'):
            hist_res = db.search_candidates_from_history(
                mailbox_account=selected_account,
                job_query=job_query,
                time_window=time_window,
                date_from=date_from,
                date_to=date_to,
                show_mode=show_mode,
                min_exp=min_exp
            )
            all_records = hist_res.get('candidates', [])
            total_matches = len(all_records)
            search_id = str(uuid.uuid4())
            db.cache_search_results(search_id, all_records)
            date_display = compute_date_display(time_window, date_from, date_to)
            search_source = "search_history"
            scan_summary = {"pdf": 0, "docx": 0, "xlsx": 0, "xls": 0, "xlsx_candidates": 0, "source": "history"}
            resolved_gmail_query = f"DB search_history: searched_at >= {time_window}"
            logging.info(f"[search] mode={user_search_mode} show={show_mode} date_field=received_at range={date_from}..{date_to} mailbox={selected_account} jd={job_query} total={total_matches}")

            if not all_records:
                flash(f'No candidate records found in search history matching "{job_query}" for window [{time_window}].', 'info')

            return render_template(
                'process.jinja',
                job_query=job_query,
                job_role=job_query,
                selected_account=selected_account,
                available_accounts=available_accounts,
                table_data=all_records,
                columns=["Rank", "Name", "Gender", "Email", "Phone", "Experience", "Skill Set", "Matched Skills", "Match Score", "Match Reason"],
                search_id=search_id,
                total_matches=total_matches,
                max_candidates=max_candidates,
                min_exp=min_exp,
                time_window=time_window,
                date_preset=date_preset,
                date_from=date_from,
                date_to=date_to,
                show_mode=show_mode,
                search_mode='history',
                search_source=search_source,
                date_display=date_display,
                resolved_gmail_query=resolved_gmail_query,
                include_excel=include_excel,
                scan_summary=scan_summary
            )

        # LIVE GMAIL SEARCH MODE: Query Gmail API live
        df, scan_summary = execute_full_candidate_search(
            job_query, 
            selected_account, 
            max_candidates=max_candidates,
            date_preset=date_preset,
            date_from=date_from,
            date_to=date_to,
            include_excel=include_excel
        )
        
        date_display = compute_date_display(time_window, date_from, date_to)
        resolved_gmail_query = gmail_search.build_gmail_search_query(job_query, date_preset=time_window, date_from=date_from, date_to=date_to)

        if df.empty:
            flash(f'No candidate resumes found for "{job_query}" in mailbox {selected_account}. Try broader search terms.', 'error')
            return render_template(
                'process.jinja',
                job_query=job_query,
                job_role=job_query,
                selected_account=selected_account,
                available_accounts=available_accounts,
                table_data=[],
                columns=[],
                search_id=None,
                total_matches=0,
                max_candidates=max_candidates,
                min_exp=min_exp,
                time_window=time_window,
                date_preset=date_preset,
                date_from=date_from,
                date_to=date_to,
                show_mode=show_mode,
                search_mode='live',
                search_source='gmail',
                date_display=date_display,
                resolved_gmail_query=resolved_gmail_query,
                include_excel=include_excel,
                scan_summary=scan_summary
            )

        # Attach persistent candidate status from Supabase
        if not df.empty and 'Email' in df.columns:
            emails_list = df['Email'].dropna().tolist()
            status_map = db.get_candidate_statuses(selected_account, emails_list)
            df['Status'] = df['Email'].apply(lambda e: status_map.get(str(e).strip().lower(), 'new'))
        else:
            df['Status'] = 'new'

        columns_order = [
            "Rank", "Source", "Status", "Name", "Gender", "Email", "Phone", "Experience", "Skill Set", "Matched Skills", "Match Score", "Match Reason", "ReceivedAt"
        ]
        columns_order = [col for col in columns_order if col in df.columns]
        
        all_records = df.fillna("N/A").to_dict(orient='records')
        total_matches = len(all_records)
        search_id = str(uuid.uuid4())

        # Save Search History in Supabase with FULL Candidate Details
        try:
            user_email = session.get('user', {}).get('email') if isinstance(session.get('user'), dict) else selected_account
            cand_list_full = [
                {
                    "name": str(r.get("Name", "")),
                    "gender": str(r.get("Gender", "N/A")),
                    "email": str(r.get("Email", "")),
                    "phone": str(r.get("Phone", "")),
                    "experience": str(r.get("Experience", "")),
                    "skills": str(r.get("Skill Set", "")),
                    "matched_skills": str(r.get("Matched Skills", "")),
                    "match_score": str(r.get("Match Score", "")),
                    "match_reason": str(r.get("Match Reason", ""))
                }
                for r in all_records
            ]
            db.save_search_history(
                user_email=user_email,
                mailbox_account=selected_account,
                job_description=job_query,
                batch_size=max_candidates,
                results_count=total_matches,
                candidates_seen=cand_list_full
            )
        except Exception as e_hist:
            logging.warning(f"Error saving search history: {e_hist}")

        # Detect search mode metadata
        mode_records, search_mode, exact_cnt, approx_cnt = filter_candidates(all_records, job_query)
        
        # Apply min_exp filter server-side
        hidden_by_exp = 0
        if min_exp is not None:
            kept = []
            for c in mode_records:
                years = parse_experience_years(c.get("Experience") or c.get("experience"))
                c["experience_years"] = years
                if years is None:
                    c["experience_unknown"] = True
                    kept.append(c)
                elif years >= min_exp:
                    kept.append(c)
                else:
                    hidden_by_exp += 1
            mode_records = kept
        else:
            for c in mode_records:
                c["experience_years"] = parse_experience_years(c.get("Experience") or c.get("experience"))

        # Apply show_mode filter (all / copied / not_copied)
        if show_mode and show_mode != 'all':
            copied_emails = get_cached_copied_emails(selected_account)
            if show_mode == 'not_copied':
                mode_records = [c for c in mode_records if (c.get('Email') or c.get('email') or '').strip().lower() not in copied_emails]
            elif show_mode == 'copied':
                mode_records = [c for c in mode_records if (c.get('Email') or c.get('email') or '').strip().lower() in copied_emails]

        # Sort by experience_years DESC (nulls last) if specified or default match score
        mode_records.sort(
            key=lambda c: (c.get("experience_years") is not None, c.get("experience_years") or -1),
            reverse=True
        )

        logging.info(f"[search] mailbox={selected_account} jd={job_query} time_window={time_window} date_from={date_from} date_to={date_to} show_mode={show_mode} total={total_matches} shown={len(mode_records)}")

        return render_template(
            'process.jinja',
            job_query=job_query,
            job_role=job_query,
            selected_account=selected_account,
            available_accounts=available_accounts,
            table_data=mode_records,
            columns=columns_order,
            search_id=search_id,
            total_matches=total_matches,
            max_candidates=max_candidates,
            search_mode=search_mode,
            exact_matches=exact_cnt,
            approx_matches=approx_cnt,
            min_exp=min_exp,
            hidden_by_experience=hidden_by_exp,
            time_window=time_window,
            date_preset=date_preset,
            date_from=date_from,
            date_to=date_to,
            show_mode=show_mode,
            date_display=date_display,
            resolved_gmail_query=resolved_gmail_query,
            include_excel=include_excel,
            scan_summary=scan_summary
        )

    raw_acct = request.args.get('account_email') or request.args.get('mailbox') or session.get('selected_account') or default_account
    if isinstance(raw_acct, dict):
        selected_account = raw_acct.get('email', default_account)
    else:
        selected_account = str(raw_acct).strip() if raw_acct else default_account
    return render_template(
        'process.jinja',
        job_query=None,
        job_role=None,
        selected_account=selected_account,
        available_accounts=available_accounts,
        table_data=[],
        columns=[],
        search_id=None,
        total_matches=0,
        page_size=25,
        date_preset='any',
        date_from='',
        date_to='',
        date_display=None
    )

@app.route('/debug-status')
def debug_status():
    status_info = db.get_table_debug_status()
    return jsonify(status_info)

@app.route('/debug-models')
def debug_models():
    """Calls Gemini ListModels API and returns available model names."""
    try:
        from google import genai
        api_key = os.environ.get("GEMINI_API_KEY", "")
        if not api_key and hasattr(RS_Project, 'GEMINI_API_KEY'):
            api_key = RS_Project.GEMINI_API_KEY
        if not api_key:
            return jsonify({'success': False, 'error': 'GEMINI_API_KEY environment variable not set'}), 400
            
        client = RS_Project.genai_client if getattr(RS_Project, 'genai_client', None) else genai.Client(api_key=api_key)
        models_pager = client.models.list()
        model_names = [m.name for m in models_pager if hasattr(m, 'name')]
        return jsonify({'success': True, 'count': len(model_names), 'models': model_names})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/history')
@login_required
def search_history_page():
    available_accounts = list(RS_Project.SUPPORTED_ACCOUNTS.values())
    selected_account = request.args.get('account_email', '')
    from_date = request.args.get('from', '')
    to_date = request.args.get('to', '')
    try:
        days = int(request.args.get('days', 30))
    except (ValueError, TypeError):
        days = 30

    history_records = db.get_search_history(
        mailbox_account=selected_account if selected_account else None,
        from_date=from_date if from_date else None,
        to_date=to_date if to_date else None,
        days=days
    )

    # Format timestamps into user's local time zone with 12-hour AM/PM format
    from datetime import datetime
    formatted_records = []
    for rec in history_records:
        rec_copy = dict(rec)
        raw_ts = rec_copy.get('searched_at', '')
        if raw_ts:
            try:
                # Handle ISO 8601 strings from Supabase (e.g., 2026-09-26T05:22:00+00:00 or 2026-09-26T05:22:00.123456+00:00)
                clean_ts = raw_ts.replace('Z', '+00:00')
                dt_utc = datetime.fromisoformat(clean_ts)
                
                # Convert UTC to local user timezone offset (+05:30 IST / user browser)
                # If naive, assume UTC
                if dt_utc.tzinfo is None:
                    dt_utc = dt_utc.replace(tzinfo=timezone.utc)
                
                dt_local = dt_utc.astimezone()
                rec_copy['formatted_time'] = dt_local.strftime('%Y-%m-%d %I:%M %p')
            except Exception as ex_ts:
                logging.warning(f"Error parsing timestamp {raw_ts}: {ex_ts}")
                rec_copy['formatted_time'] = raw_ts[:16].replace('T', ' ')
        else:
            rec_copy['formatted_time'] = 'N/A'
        formatted_records.append(rec_copy)

    return render_template(
        'history.jinja',
        available_accounts=available_accounts,
        selected_account=selected_account,
        from_date=from_date,
        to_date=to_date,
        days=days,
        history_records=formatted_records
    )

@app.route('/api/history')
@login_required
def api_get_history():
    from_date = request.args.get('from')
    to_date = request.args.get('to')
    try:
        days = int(request.args.get('days', 30))
    except (ValueError, TypeError):
        days = 30
    mailbox = request.args.get('account_email')

    records = db.get_search_history(
        mailbox_account=mailbox,
        from_date=from_date,
        to_date=to_date,
        days=days
    )
    return jsonify({'success': True, 'count': len(records), 'history': records})

@app.route('/api/history/<search_id>')
@login_required
def api_get_history_item(search_id):
    item = db.get_search_history_item(search_id)
    if not item:
        return jsonify({'success': False, 'error': 'Search history record not found'}), 404
    
    c_seen = item.get('candidates_seen') or []
    normalized = []
    if isinstance(c_seen, list):
        for c in c_seen:
            if isinstance(c, dict):
                nm = c.get('Name') or c.get('name') or (c.get('Email') or c.get('email') or '').split('@')[0] or 'Candidate'
                em = c.get('Email') or c.get('email') or 'N/A'
                c['Name'] = nm
                c['name'] = nm
                c['Email'] = em
                c['email'] = em
                normalized.append(c)
            elif isinstance(c, str):
                em = c
                nm = c.split('@')[0] if '@' in c else c
                normalized.append({'Name': nm, 'name': nm, 'Email': em, 'email': em})
    item['candidates_seen'] = normalized

    return jsonify({'success': True, 'data': item})

@app.route('/api/history/latest', methods=['GET'])
@login_required
def api_history_latest():
    mailbox = request.args.get('mailbox', '').strip()
    jd = request.args.get('jd', '').strip()
    if not mailbox or not jd:
        return jsonify({'found': False, 'error': 'mailbox and jd query params are required'}), 400

    rec = db.get_latest_search_history(mailbox, jd)
    if not rec:
        logging.info(f"[popup-A] jd={jd} last_searched_at=None results=0 (not found)")
        return jsonify({'found': False})

    searched_at = rec.get('searched_at', '')
    results_count = rec.get('results_count', 0)
    candidates_seen = rec.get('candidates_seen', [])
    cand_emails = []
    if isinstance(candidates_seen, list):
        for c in candidates_seen:
            if isinstance(c, dict) and c.get('Email'):
                cand_emails.append(c.get('Email').strip().lower())
            elif isinstance(c, str):
                cand_emails.append(c.strip().lower())

    # Count how many of these candidate emails are stored as 'used' (copied) in candidate_status DB
    copied_count = 0
    if cand_emails:
        statuses = db.get_candidate_statuses(mailbox, cand_emails)
        copied_count = sum(1 for st in statuses.values() if st == 'used')

    logging.info(f"[popup-A] jd={jd} last_searched_at={searched_at} results={results_count} copied={copied_count}")
    return jsonify({
        'found': True,
        'searched_at': searched_at,
        'results_count': results_count,
        'copied_count': copied_count,
        'candidates_seen': cand_emails,
        'search_id': rec.get('id')
    })

@app.route('/api/history/delta', methods=['GET'])
@login_required
def api_history_delta():
    mailbox = request.args.get('mailbox', '').strip()
    jd = request.args.get('jd', '').strip()
    if not mailbox or not jd:
        return jsonify({'has_previous': False, 'error': 'mailbox and jd query params are required'}), 400

    rec = db.get_latest_search_history(mailbox, jd)
    if not rec:
        logging.info(f"[popup-B] jd={jd} new=0 total=0 (no previous search)")
        return jsonify({'has_previous': False})

    searched_at_str = rec.get('searched_at', '')
    if not searched_at_str:
        return jsonify({'has_previous': False})

    from datetime import datetime, timezone
    try:
        clean_ts = searched_at_str.replace('Z', '+00:00')
        dt_last = datetime.fromisoformat(clean_ts)
        if dt_last.tzinfo is None:
            dt_last = dt_last.replace(tzinfo=timezone.utc)
    except Exception as e_ts:
        logging.warning(f"Error parsing searched_at for delta: {e_ts}")
        return jsonify({'has_previous': False})

    # Check if within last 30 days
    now_utc = datetime.now(timezone.utc)
    if (now_utc - dt_last).days > 30:
        return jsonify({'has_previous': False})

    # Lightweight Gmail search query with after:YYYY/MM/DD
    date_str = dt_last.strftime('%Y/%m/%d')
    base_query = gmail_search.build_gmail_search_query(jd)
    full_query = f"{base_query} after:{date_str}"

    new_count = 0
    total_count = rec.get('results_count', 0)
    try:
        service = RS_Project.auto_authenticate_google(account_email=mailbox)
        res = service.users().messages().list(userId='me', q=full_query, maxResults=100).execute()
        msgs = res.get('messages', [])
        new_count = len(msgs)
    except Exception as e_gm:
        logging.warning(f"Error in Gmail delta count query: {e_gm}")
        new_count = 0

    total_combined = total_count + new_count
    logging.info(f"[popup-B] jd={jd} new={new_count} total={total_combined}")
    return jsonify({
        'has_previous': True,
        'last_searched_at': searched_at_str,
        'new_count': new_count,
        'total_count': total_combined,
        'after_date': date_str
    })

@app.route('/api/history/suggestions', methods=['GET'])
@login_required
def api_history_suggestions():
    mailbox = request.args.get('mailbox', '').strip()
    records = db.get_recent_unique_searches(mailbox_account=mailbox if mailbox else None, limit=10)

    items = []
    for rec in records:
        items.append({
            'jd': rec.get('job_description', ''),
            'last_searched_at': rec.get('searched_at', ''),
            'results_count': rec.get('results_count', 0),
            'new_count': 0
        })

    logging.info(f"[suggest] {len(items)} items")
    return jsonify(items)

@app.route('/api/candidate/statuses', methods=['GET'])
@login_required
def api_get_candidate_statuses():
    mailbox = request.args.get('mailbox') or request.args.get('mailbox_account') or session.get('selected_account', 'recruiter@ecorptrainings.com')
    emails_str = request.args.get('emails', '')
    emails_list = [e.strip() for e in emails_str.split(',') if e.strip()]
    statuses = db.get_candidate_statuses(mailbox, emails_list)
    return jsonify({'success': True, 'statuses': statuses})

@app.route('/api/candidate/status', methods=['POST'])
@app.route('/mark-status', methods=['POST'])
@app.route('/api/candidate-status', methods=['POST'])
@login_required
def mark_candidate_status():
    data = request.get_json(silent=True) or request.form.to_dict() or {}
    mailbox_account = data.get('mailbox_account') or data.get('mailbox') or session.get('selected_account', 'recruiter@ecorptrainings.com')
    candidate_email = data.get('candidate_email') or data.get('email')
    candidate_name = data.get('candidate_name') or data.get('name') or ''
    status = data.get('status', 'used')
    notes = data.get('notes')

    if not candidate_email:
        return jsonify({'success': False, 'error': 'Candidate email is required'}), 400

    success = db.update_candidate_status(mailbox_account, candidate_email, candidate_name, status, notes)
    return jsonify({'success': success, 'status': status, 'email': candidate_email})

@app.route('/api/candidate/bulk_status', methods=['POST'])
@app.route('/bulk-mark', methods=['POST'])
@login_required
def bulk_mark_candidate_status():
    data = request.get_json(silent=True) or {}
    mailbox_account = data.get('mailbox_account') or data.get('mailbox') or session.get('selected_account', 'recruiter@ecorptrainings.com')
    candidates = data.get('candidates') or data.get('items', [])
    status = data.get('status', 'used')

    if not candidates:
        return jsonify({'success': False, 'error': 'No candidates provided'}), 400

    count = db.bulk_update_candidate_status(mailbox_account, candidates, status)
    return jsonify({'success': True, 'count': count, 'status': status})

# ============================================================
# COPIED HISTORY ENDPOINTS
# ============================================================
import db_copied_history

@app.route('/api/copied-history', methods=['POST'])
@login_required
def api_save_copied_history():
    data = request.get_json(silent=True) or request.form.to_dict() or {}
    user_email = session.get('user', {}).get('email') if isinstance(session.get('user'), dict) else None
    mailbox = data.get('mailbox_account') or data.get('mailbox') or session.get('selected_account', 'recruiter@ecorptrainings.com')
    candidate_email = data.get('candidate_email') or data.get('email')
    candidate_name = data.get('candidate_name') or data.get('name') or ''
    candidate_phone = data.get('candidate_phone') or data.get('phone') or ''
    job_description = data.get('job_description') or data.get('jd') or ''
    notes = data.get('notes')

    if not candidate_email:
        return jsonify({'success': False, 'error': 'Candidate email is required'}), 400

    rec_id = db_copied_history.save_copied_entry(
        user_email=user_email,
        mailbox_account=mailbox,
        candidate_email=candidate_email,
        candidate_name=candidate_name,
        candidate_phone=candidate_phone,
        job_description=job_description,
        notes=notes
    )
    return jsonify({'success': True, 'id': rec_id})

@app.route('/api/copied-history/bulk', methods=['POST'])
@login_required
def api_bulk_save_copied_history():
    data = request.get_json(silent=True) or request.form.to_dict() or {}
    user_email = session.get('user', {}).get('email') if isinstance(session.get('user'), dict) else None
    mailbox = data.get('mailbox_account') or data.get('mailbox') or session.get('selected_account', 'recruiter@ecorptrainings.com')
    job_description = data.get('job_description') or data.get('jd') or ''
    candidates = data.get('candidates') or []

    if not candidates:
        return jsonify({'success': False, 'error': 'No candidates provided'}), 400

    inserted_count = db_copied_history.save_bulk_copied_entries(
        user_email=user_email,
        mailbox_account=mailbox,
        candidates=candidates,
        job_description=job_description
    )
    return jsonify({'success': True, 'inserted': inserted_count})

@app.route('/api/copied-history', methods=['GET'])
@login_required
def api_get_copied_history():
    user_email = session.get('user', {}).get('email') if isinstance(session.get('user'), dict) else None
    mailbox = request.args.get('mailbox') or request.args.get('mailbox_account')
    mode = (request.args.get('mode') or 'copied').strip().lower()
    period_label = (request.args.get('period_label') or request.args.get('period') or request.args.get('filter') or '30d').strip().lower()
    
    from_date = request.args.get('from')
    to_date = request.args.get('to')
    
    try:
        days = int(request.args.get('days', 30))
    except (ValueError, TypeError):
        days = 30

    if period_label == 'never_used' or mode == 'not_copied':
        entries = db_copied_history.get_never_used_candidates_range(
            mailbox_account=mailbox,
            from_date=from_date,
            to_date=to_date,
            days=days
        )
        logging.info(f"[copied-history] mode={mode} period={period_label} from={from_date} to={to_date} results={len(entries)}")
        return jsonify({
            'success': True,
            'count': len(entries),
            'total': len(entries),
            'total_unique': len(entries),
            'raw_total': len(entries),
            'history': entries,
            'entries': entries,
            'raw_history': entries,
            'mode': mode,
            'period_label': period_label,
            'date_from': from_date,
            'date_to': to_date,
            'filter': period_label
        })

    raw_entries = db_copied_history.fetch_copied_history(
        mailbox_account=mailbox,
        user_email=user_email,
        from_date=from_date,
        to_date=to_date,
        days=days
    )

    grouped = {}
    for item in raw_entries:
        key = (
            (item.get('mailbox_account') or '').strip().lower(),
            (item.get('candidate_email') or '').strip().lower()
        )
        if key not in grouped:
            grouped[key] = []
        grouped[key].append(item)

    deduped_entries = []
    for key, items in grouped.items():
        latest_item = dict(items[0])
        latest_item['copy_count'] = len(items)
        latest_item['all_timestamps'] = [it.get('copied_at') for it in items if it.get('copied_at')]
        deduped_entries.append(latest_item)

    deduped_entries.sort(key=lambda x: x.get('copied_at') or '', reverse=True)

    logging.info(f"[copied-history] mode={mode} period={period_label} from={from_date} to={to_date} results={len(deduped_entries)}")

    return jsonify({
        'success': True,
        'count': len(deduped_entries),
        'total': len(deduped_entries),
        'total_unique': len(deduped_entries),
        'raw_total': len(raw_entries),
        'history': deduped_entries,
        'entries': deduped_entries,
        'raw_history': raw_entries,
        'mode': mode,
        'period_label': period_label,
        'date_from': from_date,
        'date_to': to_date,
        'filter': period_label
    })

@app.route('/api/candidates/never-used', methods=['GET'])
@login_required
def api_get_never_used_candidates():
    mailbox = request.args.get('mailbox') or request.args.get('mailbox_account')
    try:
        days = int(request.args.get('days', 30))
    except (ValueError, TypeError):
        days = 30

    entries = db_copied_history.get_never_used_candidates(mailbox_account=mailbox, days=days)
    return jsonify({
        'success': True,
        'entries': entries,
        'total': len(entries)
    })

@app.route('/api/search-history/latest', methods=['GET'])
@login_required
def api_get_latest_search_history():
    mailbox = request.args.get('mailbox') or request.args.get('mailbox_account') or ''
    jd = request.args.get('jd') or request.args.get('job_description') or ''
    rec = db.get_latest_search_history(mailbox, jd)
    if rec:
        return jsonify({
            'success': True,
            'found': True,
            'searched_at': rec.get('searched_at'),
            'id': rec.get('id'),
            'results_count': rec.get('results_count', 0)
        })
    return jsonify({'success': True, 'found': False})

@app.route('/api/gmail/count', methods=['GET'])
@login_required
def api_gmail_count():
    mailbox = request.args.get('mailbox') or session.get('selected_account', 'recruiter@ecorptrainings.com')
    jd = request.args.get('jd') or ''
    preset = request.args.get('date_preset') or 'any'
    df = request.args.get('date_from') or ''
    dt = request.args.get('date_to') or ''

    if not jd.strip():
        return jsonify({'count': 0})

    try:
        from gmail_search import build_gmail_search_query
        query = build_gmail_search_query(jd, date_preset=preset, date_from=df, date_to=dt)
        service = RS_Project.auto_authenticate_google(mailbox.lower().strip())
        res = service.users().messages().list(userId='me', q=query, maxResults=100).execute()
        count = len(res.get('messages', []))
        return jsonify({'count': count})
    except Exception as e:
        logging.warning(f"Error getting gmail count: {e}")
        return jsonify({'count': 0})



@app.route('/api/copied-history/summary', methods=['GET'])
@login_required
def api_copied_history_summary():
    mailbox = request.args.get('mailbox') or request.args.get('mailbox_account')
    summary = db_copied_history.get_summary(mailbox_account=mailbox)
    return jsonify(summary)

@app.route('/api/copied-history/check', methods=['GET'])
@login_required
def api_copied_history_check():
    mailbox = request.args.get('mailbox') or request.args.get('mailbox_account') or session.get('selected_account', 'recruiter@ecorptrainings.com')
    jd = request.args.get('jd') or request.args.get('job_description') or ''
    res = db_copied_history.check_copies_for_search(mailbox_account=mailbox, job_description=jd)
    return jsonify(res)

@app.route('/api/copied-history/export', methods=['GET'])
@login_required
def api_copied_history_export():
    mailbox = request.args.get('mailbox') or request.args.get('mailbox_account')
    entries = db_copied_history.fetch_copied_history(mailbox_account=mailbox, days=365)
    
    headers = ["ID", "User Email", "Mailbox Account", "Candidate Name", "Candidate Email", "Candidate Phone", "Job Description", "Copied At"]
    csv_lines = [",".join(headers)]
    
    for item in entries:
        row = [
            f'"{str(item.get("id", "")).replace('"', '""')}"',
            f'"{str(item.get("user_email", "")).replace('"', '""')}"',
            f'"{str(item.get("mailbox_account", "")).replace('"', '""')}"',
            f'"{str(item.get("candidate_name", "")).replace('"', '""')}"',
            f'"{str(item.get("candidate_email", "")).replace('"', '""')}"',
            f'"{str(item.get("candidate_phone", "")).replace('"', '""')}"',
            f'"{str(item.get("job_description", "")).replace('"', '""')}"',
            f'"{str(item.get("copied_at", "")).replace('"', '""')}"'
        ]
        csv_lines.append(",".join(row))
        
    csv_body = "\n".join(csv_lines)
    return csv_body, 200, {
        'Content-Type': 'text/csv; charset=utf-8',
        'Content-Disposition': f'attachment; filename=Copied_History_{datetime.now().strftime("%Y%m%d")}.csv'
    }

@app.route('/debug-copied', methods=['GET'])
def debug_copied():
    client = db.get_supabase()
    connected = (client is not None)
    row_count = 0
    recent_5 = []
    table_exists = False
    
    if connected:
        try:
            res = client.table("copied_history").select("*").order("copied_at", desc=True).limit(5).execute()
            recent_5 = res.data or []
            table_exists = True
            
            cnt_res = client.table("copied_history").select("id", count="exact").execute()
            row_count = cnt_res.count if hasattr(cnt_res, 'count') and cnt_res.count is not None else len(recent_5)
        except Exception as e:
            logging.error(f"Error in /debug-copied: {e}")
            table_exists = False
            
    return jsonify({
        "table_exists": table_exists,
        "row_count": row_count,
        "recent_5": recent_5,
        "supabase_connected": connected
    })

@app.route('/debug-copy-test', methods=['POST'])
def debug_copy_test():
    try:
        client = db.get_supabase()
        resp = client.table('copied_history').insert({
            'mailbox_account': 'debug@test.com',
            'candidate_email': 'debug@example.com',
            'candidate_name': 'Debug Candidate',
            'candidate_phone': '+91 00000-00000',
            'job_description': 'debug',
        }).execute()
        return jsonify({"ok": True, "response": resp.data})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route('/api/search/from-history', methods=['GET'])
@login_required
def api_search_from_history():
    mailbox = request.args.get('mailbox') or request.args.get('account_email') or session.get('selected_account') or 'recruiter@ecorptrainings.com'
    jd = request.args.get('jd') or request.args.get('job_query') or ''
    time_window = request.args.get('time_window') or request.args.get('date_preset') or 'any'
    date_from = request.args.get('date_from') or request.args.get('from_date') or ''
    date_to = request.args.get('date_to') or request.args.get('to_date') or ''
    show_mode = request.args.get('show_mode') or 'all'
    gender_filter = request.args.get('gender') or 'all'
    
    min_exp_raw = request.args.get('min_exp') or request.args.get('exp')
    min_exp = None
    if min_exp_raw is not None and str(min_exp_raw).strip() != '':
        try:
            min_exp = float(min_exp_raw)
        except (ValueError, TypeError):
            pass

    if show_mode == 'copied':
        res = db_copied_history.get_copied_candidates_by_time_window(
            mailbox_account=mailbox,
            job_query=jd,
            time_window=time_window,
            date_from=date_from,
            date_to=date_to,
            min_exp=min_exp,
            gender_filter=gender_filter
        )
        logging.info(f"[search] mode=from_history show={show_mode} date_field=copied_at range={date_from}..{date_to} mailbox={mailbox} jd={jd} total={res.get('total', 0)}")
        return jsonify(res)

    res = db.search_candidates_from_history(
        mailbox_account=mailbox,
        job_query=jd,
        time_window=time_window,
        date_from=date_from,
        date_to=date_to,
        show_mode=show_mode,
        min_exp=min_exp,
        gender_filter=gender_filter
    )
    logging.info(f"[search] mode=from_history show={show_mode} date_field=received_at range={date_from}..{date_to} mailbox={mailbox} jd={jd} total={res.get('total', 0)}")
    return jsonify(res)

@app.route('/api/search', methods=['GET', 'POST'])
@login_required
def api_search():
    import uuid
    job_query = request.args.get('jd') or request.args.get('job_query') or request.args.get('q') or request.form.get('jd') or request.form.get('job_query') or ''
    selected_account = request.args.get('mailbox') or request.args.get('account_email') or request.form.get('mailbox') or session.get('selected_account', 'recruiter@ecorptrainings.com')
    search_id = request.args.get('search_id') or request.form.get('search_id')
    hide_used = (request.args.get('hide_used') or request.form.get('hide_used') or 'false').lower() in ['true', '1', 'yes']

    time_window = request.args.get('time_window') or request.args.get('date_preset') or request.form.get('time_window') or request.form.get('date_preset') or 'any'
    date_from = request.args.get('date_from') or request.form.get('date_from') or ''
    date_to = request.args.get('date_to') or request.form.get('date_to') or ''
    show_mode = request.args.get('show_mode') or request.form.get('show_mode') or 'all'

    if show_mode == 'copied':
        res = db_copied_history.get_copied_candidates_by_time_window(
            mailbox_account=selected_account,
            job_query=job_query,
            time_window=time_window,
            date_from=date_from,
            date_to=date_to,
            min_exp=None
        )
        logging.info(f"[search] mode=api_search show={show_mode} date_field=copied_at range={date_from}..{date_to} mailbox={selected_account} jd={job_query} total={res.get('total', 0)}")
        return jsonify(res)

    if time_window == 'custom':
        if not date_from or not date_to:
            return jsonify({"error": "Custom range requires both dates"}), 400
        for d in (date_from, date_to):
            if not re.match(r'^\d{4}-\d{2}-\d{2}$', d):
                return jsonify({"error": "Invalid date format. Use YYYY-MM-DD"}), 400
        if date_from > date_to:
            return jsonify({"error": "From date must be before To date"}), 400

    min_exp_raw = request.args.get('min_exp') or request.form.get('min_exp')
    try:
        min_exp = float(min_exp_raw) if min_exp_raw is not None and str(min_exp_raw).strip() != '' else None
    except (ValueError, TypeError):
        min_exp = None

    try:
        offset = int(request.args.get('offset') or request.form.get('offset') or 0)
    except (ValueError, TypeError):
        offset = 0
    try:
        limit = int(request.args.get('limit') or request.form.get('limit') or 25)
    except (ValueError, TypeError):
        limit = 25

    resolved_gmail_query = gmail_search.build_gmail_search_query(job_query, date_preset=time_window, date_from=date_from, date_to=date_to)

    if offset > 0 and search_id:
        cached = db.get_cached_results(search_id, offset, limit)
        if not cached.get('expired'):
            logging.info(f"Load More: search_id={search_id} offset={offset} limit={limit}")
            candidates = cached.get('results', [])
            total = cached.get('total', 0)
            
            # Apply min_exp filtering on cached load more
            hidden_exp_count = 0
            if min_exp is not None:
                kept = []
                for c in candidates:
                    years = parse_experience_years(c.get("Experience") or c.get("experience"))
                    c["experience_years"] = years
                    if years is None:
                        c["experience_unknown"] = True
                        kept.append(c)
                    elif years >= min_exp:
                        kept.append(c)
                    else:
                        hidden_exp_count += 1
                candidates = kept
            else:
                for c in candidates:
                    c["experience_years"] = parse_experience_years(c.get("Experience") or c.get("experience"))

            if show_mode and show_mode != 'all':
                copied_emails = get_cached_copied_emails(selected_account)
                if show_mode == 'not_copied':
                    candidates = [c for c in candidates if (c.get('Email') or c.get('email') or '').strip().lower() not in copied_emails]
                elif show_mode == 'copied':
                    candidates = [c for c in candidates if (c.get('Email') or c.get('email') or '').strip().lower() in copied_emails]

            candidates.sort(
                key=lambda c: (c.get("experience_years") is not None, c.get("experience_years") or -1),
                reverse=True
            )

            if candidates:
                emails = [c.get('Email') for c in candidates if c.get('Email')]
                status_map = db.get_candidate_statuses(selected_account, emails)
                for c in candidates:
                    c['Status'] = status_map.get(str(c.get('Email')).strip().lower(), 'new')
                    
            hidden_used_count = 0
            if hide_used:
                orig_len = len(candidates)
                candidates = [c for c in candidates if c.get('Status') != 'used']
                hidden_used_count = orig_len - len(candidates)

            return jsonify({
                "search_id": search_id,
                "candidates": candidates,
                "total": len(candidates),
                "offset": offset,
                "limit": limit,
                "hidden_used_count": hidden_used_count,
                "hidden_by_experience": hidden_exp_count,
                "min_exp_applied": min_exp,
                "time_window": time_window,
                "date_from": date_from,
                "date_to": date_to,
                "show_mode": show_mode,
                "resolved_gmail_query": resolved_gmail_query,
                "has_more": (offset + limit) < total
            })
        else:
            logging.info("Search cache expired or missing; rerunning")

    try:
        max_candidates = int(request.args.get('max_candidates') or request.form.get('max_candidates') or 50)
    except (ValueError, TypeError):
        max_candidates = 50

    df, scan_summary = execute_full_candidate_search(job_query, selected_account, max_candidates=max_candidates, date_preset=time_window, date_from=date_from, date_to=date_to)
    
    if df.empty:
        return jsonify({
            "search_id": str(uuid.uuid4()),
            "candidates": [],
            "total": 0,
            "offset": offset,
            "limit": limit,
            "hidden_used_count": 0,
            "hidden_by_experience": 0,
            "time_window": time_window,
            "date_from": date_from,
            "date_to": date_to,
            "show_mode": show_mode,
            "resolved_gmail_query": resolved_gmail_query,
            "has_more": False
        })

    columns_order = [
        "Rank", "Source", "Status", "Name", "Gender", "Email", "Phone", "Experience", "Skill Set", "Matched Skills", "Match Score", "Match Reason"
    ]
    cols = [c for c in columns_order if c in df.columns]
    all_records = df.fillna("N/A").to_dict(orient='records')

    hidden_exp_count = 0
    if min_exp is not None:
        kept = []
        for c in all_records:
            years = parse_experience_years(c.get("Experience") or c.get("experience"))
            c["experience_years"] = years
            if years is None:
                c["experience_unknown"] = True
                kept.append(c)
            elif years >= min_exp:
                kept.append(c)
            else:
                hidden_exp_count += 1
        all_records = kept
    else:
        for c in all_records:
            c["experience_years"] = parse_experience_years(c.get("Experience") or c.get("experience"))

    if show_mode and show_mode != 'all':
        copied_emails = get_cached_copied_emails(selected_account)
        if show_mode == 'not_copied':
            all_records = [c for c in all_records if (c.get('Email') or c.get('email') or '').strip().lower() not in copied_emails]
        elif show_mode == 'copied':
            all_records = [c for c in all_records if (c.get('Email') or c.get('email') or '').strip().lower() in copied_emails]

    total = len(all_records)

    all_records.sort(
        key=lambda c: (c.get("experience_years") is not None, c.get("experience_years") or -1),
        reverse=True
    )

    logging.info(f"[search] mailbox={selected_account} jd={job_query} time_window={time_window} date_from={date_from} date_to={date_to} show_mode={show_mode} total={total} hidden_exp={hidden_exp_count} returned={len(all_records)}")

    search_id = search_id or str(uuid.uuid4())
    db.cache_search_results(search_id, all_records)

    sliced_records = all_records[offset:offset+limit]
    hidden_used_count = 0
    if sliced_records:
        emails = [c.get('Email') for c in sliced_records if c.get('Email')]
        status_map = db.get_candidate_statuses(selected_account, emails)
        for c in sliced_records:
            c['Status'] = status_map.get(str(c.get('Email')).strip().lower(), 'new')
            
        if hide_used:
            orig_len = len(sliced_records)
            sliced_records = [c for c in sliced_records if c.get('Status') != 'used']
            hidden_used_count = orig_len - len(sliced_records)

    return jsonify({
        "search_id": search_id,
        "candidates": sliced_records,
        "total": total,
        "offset": offset,
        "limit": limit,
        "hidden_used_count": hidden_used_count,
        "hidden_by_experience": hidden_exp_count,
        "min_exp_applied": min_exp,
        "time_window": time_window,
        "date_from": date_from,
        "date_to": date_to,
        "show_mode": show_mode,
        "resolved_gmail_query": resolved_gmail_query,
        "has_more": (offset + limit) < total
    })

_count_cache = {}  # {cache_key: (count, timestamp)}

def build_gmail_query_for_window(time_window):
    """Return the date clause for the Gmail query."""
    if time_window == 'today':
        return "newer_than:1d"
    elif time_window == 'yesterday':
        return "newer_than:2d older_than:1d"
    elif time_window == '7d':
        return "newer_than:7d"
    elif time_window == '14d':
        return "newer_than:14d"
    elif time_window == '30d':
        return "newer_than:30d"
    return ""

@app.route('/api/gmail/count', methods=['GET'])
def gmail_count():
    mailbox = request.args.get('mailbox', '').strip()
    jd = request.args.get('jd', '').strip() or request.args.get('job_query', '').strip()
    time_window = request.args.get('time_window', '').strip() or request.args.get('date_preset', '').strip()

    if not mailbox or not jd or not time_window:
        return jsonify({"error": "missing params"}), 400

    if time_window in ('any', 'custom'):
        return jsonify({"count": 0, "time_window": time_window, "cached": True})

    cache_key = f"{mailbox}|{jd}|{time_window}"
    now = time.time()
    if cache_key in _count_cache:
        cached_count, cached_ts = _count_cache[cache_key]
        if now - cached_ts < 60:
            from datetime import datetime
            return jsonify({
                "count": cached_count,
                "time_window": time_window,
                "cached": True,
                "computed_at": datetime.utcnow().isoformat() + 'Z'
            })

    try:
        query = gmail_search.build_gmail_search_query(jd, date_preset=time_window)
        if not query:
            date_clause = build_gmail_query_for_window(time_window)
            query = f"has:attachment {date_clause} {jd}".strip()
        elif "has:attachment" not in query:
            query = f"has:attachment {query}".strip()

        service = RS_Project.auto_authenticate_google(mailbox)
        results = service.users().messages().list(
            userId='me', q=query, maxResults=1
        ).execute()
        count = results.get('resultSizeEstimate', 0)
    except Exception as e:
        err_str = str(e)
        logging.error(f"[count] gmail fetch failed: {e}")
        status_code = 429 if "429" in err_str or "userRateLimitExceeded" in err_str else 500
        return jsonify({"error": "gmail_error", "detail": err_str}), status_code

    _count_cache[cache_key] = (count, now)
    from datetime import datetime
    logging.info(f"[count] mailbox={mailbox} jd={jd} tw={time_window} count={count} cached=False")

    return jsonify({
        "count": count,
        "time_window": time_window,
        "cached": False,
        "computed_at": datetime.utcnow().isoformat() + 'Z'
    })

@app.route('/debug-parse-exp', methods=['GET'])

def debug_parse_exp():
    text = request.args.get('text', '')
    parsed = parse_experience_years(text)
    return jsonify({"text": text, "parsed": parsed})

@app.route('/debug-phone-match', methods=['GET'])
def debug_phone_match():
    term = request.args.get('term', '')
    mailbox = request.args.get('mailbox') or session.get('selected_account', 'recruiter@ecorptrainings.com')
    search_digits = normalize_phone(term)
    last_10 = search_digits[-10:] if len(search_digits) >= 10 else search_digits
    
    df = execute_full_candidate_search(term, mailbox, max_candidates=200)
    candidates = df.to_dict(orient='records') if not df.empty else []
    
    matches = []
    matches_count = 0
    for cand in candidates:
        is_match = matches_phone(cand, term)
        if is_match:
            matches_count += 1
        matches.append({
            "name": cand.get("Name", ""),
            "phone": cand.get("Phone", ""),
            "match": is_match
        })
        
    return jsonify({
        "search_digits": search_digits,
        "last_10": last_10,
        "candidates_checked": len(candidates),
        "matches_found": matches_count,
        "matches": matches
    })

@app.route('/debug/extract-text/<path:filename>')
@login_required
def debug_extract_text(filename):
    """Show what text is being sent to Gemini for a given resume file."""
    import RS_Project
    filepath = os.path.join(RS_Project.RESUME_FOLDER, filename)
    if not os.path.exists(filepath):
        return jsonify({'error': 'file not found'}), 404
    
    try:
        with open(filepath, 'rb') as f:
            file_bytes = f.read()
        text = RS_Project.extract_text_from_bytes(file_bytes, filename)
    except Exception as e:
        return jsonify({'error': f'Failed to extract text: {e}'}), 500
    
    return jsonify({
        'file': filename,
        'text_length': len(text),
        'first_1000_chars': text[:1000],
        'extracted_name_fallback': RS_Project.extract_name_from_resume_text(text)
    })

if __name__ == '__main__':
    app.run(debug=True)