import os
import json
import sys

try:
    from google_auth_oauthlib.flow import InstalledAppFlow
except ImportError:
    print("Error: google-auth-oauthlib is not installed. Please run: pip install google-auth-oauthlib")
    sys.exit(1)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)

ACCOUNTS = {
    "1": {
        "email": "recruiter@ecorptrainings.com",
        "name": "Recruiter Account",
        "client_file": "client.json",
        "token_file": "token.json",
        "env_var": "GOOGLE_TOKEN_JSON"
    },
    "2": {
        "email": "jai.ecorp@gmail.com",
        "name": "Jai Ecorp Account",
        "client_file": "client_jai.json",
        "token_file": "token_jai.json",
        "env_var": "GOOGLE_TOKEN_JAI_JSON"
    },
    "3": {
        "email": "kumar.ecorp@gmail.com",
        "name": "Kumar Ecorp Account",
        "client_file": "client_kumar.json",
        "token_file": "token_kumar.json",
        "env_var": "GOOGLE_TOKEN_KUMAR_JSON"
    },
    "4": {
        "email": "pushpa@ecorptrainings.com",
        "name": "Pushpa Account",
        "client_file": "client_pushpa.json",
        "token_file": "token_pushpa.json",
        "env_var": "GOOGLE_TOKEN_PUSHPA_JSON"
    },
    "5": {
        "email": "mahi@ecorptrainings.com",
        "name": "Mahi Account",
        "client_file": "client_mahi.json",
        "token_file": "token_mahi.json",
        "env_var": "GOOGLE_TOKEN_MAHI_JSON"
    },
    "6": {
        "email": "contact@ecorptrainings.com",
        "name": "Contact Account",
        "client_file": "client_contact.json",
        "token_file": "token_contact.json",
        "env_var": "GOOGLE_TOKEN_CONTACT_JSON"
    }
}

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

def authorize_account(acct_info):
    email = acct_info["email"]
    client_fname = acct_info["client_file"]
    token_fname = acct_info["token_file"]
    env_var_name = acct_info["env_var"]

    print("\n" + "="*70)
    print(f"Authorizing: {acct_info['name']} ({email})")
    print("="*70)

    # Locate client secrets file
    client_path = os.path.join(SCRIPT_DIR, client_fname)
    if not os.path.exists(client_path) and os.path.exists(PARENT_DIR):
        client_path = os.path.join(PARENT_DIR, client_fname)

    if not os.path.exists(client_path):
        print(f"❌ Error: {client_fname} not found at {client_path}")
        return

    try:
        flow = InstalledAppFlow.from_client_secrets_file(client_path, SCOPES)
        try:
            creds = flow.run_local_server(port=0, prompt='consent')
        except Exception:
            creds = flow.run_local_server(port=8090, prompt='consent')

        token_json_str = creds.to_json()

        # Save to local files
        save_paths = [
            os.path.join(SCRIPT_DIR, token_fname),
            os.path.join(PARENT_DIR, token_fname) if os.path.exists(PARENT_DIR) else None
        ]
        for p in save_paths:
            if p:
                with open(p, "w", encoding="utf-8") as f:
                    f.write(token_json_str)

        print(f"\n✅ Token successfully saved to: {token_fname}")
        print("\n" + "-"*70)
        print(f"📋 FOR VERCEL DEPLOYMENT - Add this Environment Variable:")
        print(f"Key:   {env_var_name}")
        minified = json.dumps(json.loads(token_json_str))
        print(f"Value: {minified}")
        print("-"*70)

    except Exception as e:
        print(f"❌ Authorization failed for {email}: {e}")

def main():
    print("="*70)
    print("       Gmail OAuth Token Generator for Resume Shortlisting       ")
    print("="*70)
    print("Select an account to authorize in your browser:")
    for num, acct in ACCOUNTS.items():
        print(f"  [{num}] {acct['name']} ({acct['email']})")
    print("  [A] Authorize ALL 6 accounts sequentially")
    print("  [Q] Quit")
    print("="*70)

    choice = input("Enter choice (1-6, A, or Q): ").strip().upper()
    if choice == 'Q':
        print("Exiting.")
        return
    elif choice == 'A':
        for num in sorted(ACCOUNTS.keys()):
            authorize_account(ACCOUNTS[num])
    elif choice in ACCOUNTS:
        authorize_account(ACCOUNTS[choice])
    else:
        print("Invalid selection.")

if __name__ == "__main__":
    main()
