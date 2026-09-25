import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
inner_dir = os.path.join(current_dir, "USA-Resume-Shortlisting-main")

if inner_dir not in sys.path:
    sys.path.insert(0, inner_dir)

from db import *
