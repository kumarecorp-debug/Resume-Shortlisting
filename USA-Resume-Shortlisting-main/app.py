from flask import Flask, render_template, request, redirect, url_for, flash, session
import re
import pandas as pd
from io import StringIO
import sys
import logging
from contextlib import redirect_stdout, redirect_stderr
import RS_Project
import os

project_root = os.path.dirname(os.path.abspath(__file__))
template_dir = os.path.join(project_root, 'templates')
static_dir = os.path.join(project_root, 'static')

app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
app.secret_key = 'your-secret-key-here-ecorp-resume'

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

try:
    os.chdir(project_root)
except Exception:
    pass

@app.route('/', methods=['GET', 'POST'])
@app.route('/process', methods=['GET', 'POST'])
def process():
    available_accounts = list(RS_Project.SUPPORTED_ACCOUNTS.values())
    default_account = "recruiter@ecorptrainings.com"

    if request.method == 'POST':
        # Accepts job description, role keywords, or Job ID
        job_query = request.form.get('job_query') or request.form.get('job_id') or request.form.get('job_description')
        selected_account = request.form.get('account_email') or session.get('selected_account', default_account)
        selected_account = selected_account.strip()
        session['selected_account'] = selected_account

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
                RS_Project.main(job_query, account_email=selected_account)
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

        # Define standard display columns
        columns_order = [
            "Rank", "Name", "Email", "Phone", "Experience", "Skill Set", "Matched Skills", "Match Score", "Match Reason"
        ]
        columns_order = [col for col in columns_order if col in df.columns]
        table_data = df[columns_order].fillna("N/A").to_dict(orient='records')

        return render_template(
            'process.jinja',
            job_query=job_query,
            job_role=job_query,
            selected_account=selected_account,
            available_accounts=available_accounts,
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
        table_data=[],
        columns=[]
    )

if __name__ == '__main__':
    app.run(debug=True)