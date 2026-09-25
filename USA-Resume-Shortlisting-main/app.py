from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
import re
import pandas as pd
from io import StringIO
import sys
import logging
from contextlib import redirect_stdout, redirect_stderr
from functools import wraps
import RS_Project
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

@app.route('/', methods=['GET', 'POST'])
@app.route('/process', methods=['GET', 'POST'])
@login_required
def process():
    available_accounts = list(RS_Project.SUPPORTED_ACCOUNTS.values())
    default_account = "recruiter@ecorptrainings.com"

    if request.method == 'POST':
        # Accepts job description, role keywords, or Job ID
        job_query = request.form.get('job_query') or request.form.get('job_id') or request.form.get('job_description')
        selected_account = request.form.get('account_email') or session.get('selected_account', default_account)
        selected_account = selected_account.strip()
        session['selected_account'] = selected_account
        
        try:
            max_candidates = int(request.form.get('max_candidates', 25))
        except (ValueError, TypeError):
            max_candidates = 25

        if job_query:
            job_query = job_query.strip()

        if not job_query:
            flash('Job Description or Keywords are required to search for resumes', 'error')
            return render_template(
                'process.jinja',
                job_query=None,
                job_role=None,
                selected_account=selected_account,
                available_accounts=available_accounts,
                max_candidates=max_candidates,
                table_data=[],
                columns=[]
            )

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
                flash(f'Error processing resumes for {selected_account}: {str(e)}', 'error')
                logging.error(f"Error in processing: {e}")
                logging.error(f"Captured stdout: {stdout_buffer.getvalue()}")
                logging.error(f"Captured stderr: {stderr_buffer.getvalue()}")
                return render_template(
                    'process.jinja',
                    job_query=job_query,
                    job_role=job_query,
                    selected_account=selected_account,
                    available_accounts=available_accounts,
                    table_data=[],
                    columns=[]
                )

        stdout_output = stdout_buffer.getvalue()
        stderr_output = stderr_buffer.getvalue()
        logging.info(f"RS_Project.main stdout: {stdout_output}")
        logging.info(f"RS_Project.main stderr: {stderr_output}")

        output_csv = RS_Project.OUTPUT_CSV
        if not os.path.exists(output_csv):
            error_message = f'No resumes found matching "{job_query}" in mailbox {selected_account}. Please check your mailbox.'
            flash(error_message, 'error')
            logging.error(f"Output CSV not found: {output_csv}")
            return render_template(
                'process.jinja',
                job_query=job_query,
                job_role=job_query,
                selected_account=selected_account,
                available_accounts=available_accounts,
                table_data=[],
                columns=[]
            )

        try:
            df = pd.read_csv(output_csv)
            if df.empty:
                flash(f'No candidate resumes found for "{job_query}" in mailbox {selected_account}. Try broader search terms.', 'error')
                logging.warning(f"Output CSV is empty: {output_csv}")
                return render_template(
                    'process.jinja',
                    job_query=job_query,
                    job_role=job_query,
                    selected_account=selected_account,
                    available_accounts=available_accounts,
                    table_data=[],
                    columns=[]
                )
        except Exception as e:
            flash(f'Failed to read results: {str(e)}', 'error')
            logging.error(f"Error reading CSV: {e}")
            return render_template(
                'process.jinja',
                job_query=job_query,
                job_role=job_query,
                selected_account=selected_account,
                available_accounts=available_accounts,
                table_data=[],
                columns=[]
            )

        # Apply requested transformations
        if not df.empty:
            # 1. Reorder Skill Set
            def reorder_skills(row):
                matched = str(row.get('Matched Skills', '')).split(',')
                all_skills = str(row.get('Skill Set', '')).split(',')
                matched_clean = [m.strip().lower() for m in matched if m.strip()]
                
                first_part = []
                second_part = []
                
                for s in all_skills:
                    s_clean = s.strip()
                    if not s_clean: continue
                    # check if skill is in matched or matched in skill
                    if any(m in s_clean.lower() or s_clean.lower() in m for m in matched_clean):
                        first_part.append(s_clean)
                    else:
                        second_part.append(s_clean)
                
                return ', '.join(first_part + second_part)

            if 'Skill Set' in df.columns:
                df['Skill Set'] = df.apply(reorder_skills, axis=1)

            # 2. Extract numeric experience and sort descending (Higher to Lower)
            if 'Experience' in df.columns:
                def extract_years(exp):
                    import re
                    match = re.search(r'[\d.]+', str(exp))
                    if match: return float(match.group())
                    return 0.0
                
                df['Exp_Num'] = df['Experience'].apply(extract_years)
                # Sort by experience descending (Higher to Lower)
                df = df.sort_values(by=['Exp_Num'], ascending=[False]).reset_index(drop=True)
                df['Rank'] = range(1, len(df) + 1)
            
            # 3. Add Gender using gender-guesser or simple heuristic
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

                # Explicit Indian Female First Names
                female_names = {
                    'pooja', 'priya', 'neha', 'anjali', 'swati', 'divya', 'kavita', 'deepa', 'megha', 'shweta',
                    'sunita', 'anita', 'kiran', 'rekha', 'rashmi', 'sneha', 'jyoti', 'monika', 'payal', 'richa',
                    'sonam', 'smita', 'bhavna', 'sapna', 'archana', 'simran', 'preeti', 'renu', 'seema', 'tanvi',
                    'radha', 'sheetal', 'harshita', 'apoorva', 'srishti', 'kriti', 'nisha', 'sakshi', 'shikha',
                    'shipra', 'garima', 'pallavi', 'surabhi', 'saloni', 'sonia', 'vandana', 'komal', 'namrata'
                }
                
                # Explicit Indian Male First Names (often ending in -a or -i)
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
                    
                # Precise Fallback heuristic (only 'a' or 'i' at end for female names, provided it's not in male list)
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

        # Attach persistent candidate status from Supabase
        if not df.empty and 'Email' in df.columns:
            emails_list = df['Email'].dropna().tolist()
            status_map = db.get_candidate_statuses(selected_account, emails_list)
            df['Status'] = df['Email'].apply(lambda e: status_map.get(str(e).strip().lower(), 'new'))
        else:
            df['Status'] = 'new'

        # Define standard display columns
        columns_order = [
            "Rank", "Status", "Name", "Gender", "Email", "Phone", "Experience", "Skill Set", "Matched Skills", "Match Score", "Match Reason"
        ]
        columns_order = [col for col in columns_order if col in df.columns]
        table_data = df[columns_order].fillna("N/A").to_dict(orient='records')

        # Save Search History in Supabase
        try:
            user_email = session.get('user', {}).get('email') if isinstance(session.get('user'), dict) else selected_account
            cand_list = df[['Name', 'Email']].fillna('N/A').to_dict(orient='records') if not df.empty and 'Name' in df.columns and 'Email' in df.columns else []
            db.save_search_history(
                user_email=user_email,
                mailbox_account=selected_account,
                job_description=job_query,
                batch_size=max_candidates,
                results_count=len(table_data),
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
            max_candidates=max_candidates,
            table_data=table_data,
            columns=columns_order
        )

    selected_account = request.args.get('account_email') or session.get('selected_account', default_account)
    return render_template(
        'process.jinja',
        job_query=None,
        job_role=None,
        selected_account=selected_account,
        available_accounts=available_accounts,
        max_candidates=25,
        table_data=[],
        columns=[]
    )

@app.route('/debug-status')
def debug_status():
    status_info = db.get_table_debug_status()
    return jsonify(status_info)

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

    return render_template(
        'history.jinja',
        available_accounts=available_accounts,
        selected_account=selected_account,
        from_date=from_date,
        to_date=to_date,
        days=days,
        history_records=history_records
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

@app.route('/mark-status', methods=['POST'])
@app.route('/api/candidate-status', methods=['POST'])
@login_required
def mark_candidate_status():
    data = request.get_json(silent=True) or request.form.to_dict() or {}
    mailbox_account = data.get('mailbox_account') or session.get('selected_account', 'recruiter@ecorptrainings.com')
    candidate_email = data.get('candidate_email') or data.get('email')
    candidate_name = data.get('candidate_name') or data.get('name') or ''
    status = data.get('status', 'used')
    notes = data.get('notes')

    if not candidate_email:
        return jsonify({'success': False, 'error': 'Candidate email is required'}), 400

    success = db.update_candidate_status(mailbox_account, candidate_email, candidate_name, status, notes)
    return jsonify({'success': success, 'status': status, 'email': candidate_email})

@app.route('/bulk-mark', methods=['POST'])
@login_required
def bulk_mark_candidate_status():
    data = request.get_json(silent=True) or {}
    mailbox_account = data.get('mailbox_account') or session.get('selected_account', 'recruiter@ecorptrainings.com')
    candidates = data.get('candidates', [])
    status = data.get('status', 'used')

    if not candidates:
        return jsonify({'success': False, 'error': 'No candidates provided'}), 400

    count = db.bulk_update_candidate_status(mailbox_account, candidates, status)
    return jsonify({'success': True, 'count': count, 'status': status})

if __name__ == '__main__':
    app.run(debug=True)