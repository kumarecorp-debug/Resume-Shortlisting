import os
import sys

root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
usa_dir = os.path.join(root_dir, "USA-Resume-Shortlisting-main")

for d in [root_dir, usa_dir]:
    if os.path.exists(d) and d not in sys.path:
        sys.path.insert(0, d)

from app import app
