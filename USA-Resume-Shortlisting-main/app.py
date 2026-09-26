from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
import re
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
from supabase import create_client, Client

project_root = os.path.dirname(os.path.abspath(__file__))
template_dir = os.path.join(project_root, 'templates')
static_dir = os.path.join(project_root, 'static')

app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
app.secret_key = 'your-secret-key-here-ecorp-resume'

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

def execute_full_candidate_search(job_query, selected_account, max_candidates=200):
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

    stdout_buffer = StringIO()
    stderr_buffer = StringIO()
    with redirect_stdout(stdout_buffer), redirect_stderr(stderr_buffer):
        try:
            RS_Project.main(job_query, account_email=selected_account, max_candidates=max_candidates)
        except Exception as e:
            logging.error(f"Error in RS_Project.main: {e}")

    output_csv = RS_Project.OUTPUT_CSV
    if not os.path.exists(output_csv):
        return pd.DataFrame()

    try:
        df = pd.read_csv(output_csv)
        if df.empty:
            return pd.DataFrame()
    except Exception as e:
        logging.error(f"Error reading output CSV: {e}")
        return pd.DataFrame()

    if not df.empty:
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

        if 'Experience' in df.columns:
            def extract_years(exp):
                import re
                match = re.search(r'[\d.]+', str(exp))
                if match: return float(match.group())
                return 0.0
            df['Exp_Num'] = df['Experience'].apply(extract_years)
            df = df.sort_values(by=['Exp_Num'], ascending=[False]).reset_index(drop=True)
            df['Rank'] = range(1, len(df) + 1)

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
                'harish', 'gopal', 'mohan', 'sohan', 'rohan', 'varun', 'tarun', 'arun', 'alok', 'ashok'
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

    return df

@app.route('/', methods=['GET', 'POST'])
@app.route('/process', methods=['GET', 'POST'])
@login_required
def process():
    available_accounts = list(RS_Project.SUPPORTED_ACCOUNTS.values())
    default_account = available_accounts[0] if available_accounts else "recruiter@ecorptrainings.com"
    
    if request.method == 'POST':
        import uuid
        job_query = request.form.get('job_query', '').strip()
        selected_account = request.form.get('account_email', default_account)
        session['selected_account'] = selected_account

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
                page_size=25
            )

        max_candidates = int(request.form.get('max_candidates', 50))
        df = execute_full_candidate_search(job_query, selected_account, max_candidates=max_candidates)
        
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
                max_candidates=max_candidates
            )

        # Attach persistent candidate status from Supabase
        if not df.empty and 'Email' in df.columns:
            emails_list = df['Email'].dropna().tolist()
            status_map = db.get_candidate_statuses(selected_account, emails_list)
            df['Status'] = df['Email'].apply(lambda e: status_map.get(str(e).strip().lower(), 'new'))
        else:
            df['Status'] = 'new'

        columns_order = [
            "Rank", "Status", "Name", "Gender", "Email", "Phone", "Experience", "Skill Set", "Matched Skills", "Match Score", "Match Reason"
        ]
        columns_order = [col for col in columns_order if col in df.columns]
        all_records = df[columns_order].fillna("N/A").to_dict(orient='records')
        total_matches = len(all_records)
        search_id = str(uuid.uuid4())

        # Save Search History in Supabase
        try:
            user_email = session.get('user', {}).get('email') if isinstance(session.get('user'), dict) else selected_account
            cand_list = df[['Name', 'Email']].fillna('N/A').to_dict(orient='records') if not df.empty and 'Name' in df.columns and 'Email' in df.columns else []
            db.save_search_history(
                user_email=user_email,
                mailbox_account=selected_account,
                job_description=job_query,
                batch_size=max_candidates,
                results_count=total_matches,
                candidates_seen=cand_list
            )
        except Exception as e_hist:
            logging.warning(f"Error saving search history: {e_hist}")

        return render_template(
            'process.jinja',
            job_query=job_query,
            job_role=job_query,
            selected_account=selected_account,
            available_accounts=available_accounts,
            table_data=all_records,
            columns=columns_order,
            search_id=search_id,
            total_matches=total_matches,
            max_candidates=max_candidates
        )

    selected_account = request.args.get('account_email') or session.get('selected_account', default_account)
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
        page_size=25
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
                cand_emails.append(c.get('Email'))
            elif isinstance(c, str):
                cand_emails.append(c)

    logging.info(f"[popup-A] jd={jd} last_searched_at={searched_at} results={results_count}")
    return jsonify({
        'found': True,
        'searched_at': searched_at,
        'results_count': results_count,
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
        service = RS_Project.get_gmail_service(account_email=mailbox)
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

    from datetime import datetime, timezone
    now_utc = datetime.now(timezone.utc)

    items = []
    for rec in records:
        jd = rec.get('job_description', '')
        searched_at_str = rec.get('searched_at', '')
        results_count = rec.get('results_count', 0)

        new_count = 0
        if searched_at_str:
            try:
                clean_ts = searched_at_str.replace('Z', '+00:00')
                dt_last = datetime.fromisoformat(clean_ts)
                if dt_last.tzinfo is None:
                    dt_last = dt_last.replace(tzinfo=timezone.utc)
                diff_days = (now_utc - dt_last).days
                if diff_days <= 30:
                    date_str = dt_last.strftime('%Y/%m/%d')
                    base_query = gmail_search.build_gmail_search_query(jd)
                    full_query = f"{base_query} after:{date_str}"
                    try:
                        service = RS_Project.get_gmail_service(account_email=mailbox if mailbox else 'recruiter@ecorptrainings.com')
                        res = service.users().messages().list(userId='me', q=full_query, maxResults=50).execute()
                        msgs = res.get('messages', [])
                        new_count = len(msgs)
                    except Exception:
                        new_count = 0
            except Exception:
                pass

        items.append({
            'jd': jd,
            'last_searched_at': searched_at_str,
            'results_count': results_count,
            'new_count': new_count
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

@app.route('/api/search', methods=['GET'])
@login_required
def api_search():
    import uuid
    job_query = request.args.get('jd') or request.args.get('job_query') or request.args.get('q', '')
    selected_account = request.args.get('mailbox') or request.args.get('account_email') or session.get('selected_account', 'recruiter@ecorptrainings.com')
    search_id = request.args.get('search_id')
    hide_used = request.args.get('hide_used', 'false').lower() in ['true', '1', 'yes']
    try:
        offset = int(request.args.get('offset', 0))
    except (ValueError, TypeError):
        offset = 0
    try:
        limit = int(request.args.get('limit', 25))
    except (ValueError, TypeError):
        limit = 25

    if offset > 0 and search_id:
        cached = db.get_cached_results(search_id, offset, limit)
        if not cached.get('expired'):
            logging.info(f"Load More: search_id={search_id} offset={offset} limit={limit}")
            candidates = cached.get('results', [])
            total = cached.get('total', 0)
            
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
                "total": total,
                "offset": offset,
                "limit": limit,
                "hidden_used_count": hidden_used_count,
                "has_more": (offset + limit) < total
            })
        else:
            logging.info("Search cache expired or missing; rerunning")

    try:
        max_candidates = int(request.args.get('max_candidates', 50))
    except (ValueError, TypeError):
        max_candidates = 50

    df = execute_full_candidate_search(job_query, selected_account, max_candidates=max_candidates)
    total = len(df)
    logging.info(f"Search started: JD={job_query} mailbox={selected_account} max_candidates={max_candidates} total={total}")

    columns_order = [
        "Rank", "Status", "Name", "Gender", "Email", "Phone", "Experience", "Skill Set", "Matched Skills", "Match Score", "Match Reason"
    ]
    cols = [c for c in columns_order if c in df.columns]
    all_records = df[cols].fillna("N/A").to_dict(orient='records')

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
        "has_more": (offset + limit) < total
    })

if __name__ == '__main__':
    app.run(debug=True)