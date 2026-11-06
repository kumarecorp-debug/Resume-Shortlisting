import os
import sys
import traceback

root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
usa_dir = os.path.join(root_dir, "USA-Resume-Shortlisting-main")

for d in [root_dir, usa_dir]:
    if os.path.exists(d) and d not in sys.path:
        sys.path.insert(0, d)

try:
    from app import app
except Exception as e:
    err_tb = traceback.format_exc()
    from flask import Flask, Response
    app = Flask(__name__)
    @app.route('/', defaults={'path': ''})
    @app.route('/<path:path>')
    def catch_all(path):
        return Response(
            f"<html><head><title>Startup Error</title></head><body style='font-family:sans-serif;padding:30px;background:#f8f9fa;'><h2>Application Startup Error</h2><pre style='background:#fff;border:1px solid #ccc;padding:15px;border-radius:6px;overflow:auto;'>{err_tb}</pre></body></html>",
            mimetype="text/html",
            status=500
        )
