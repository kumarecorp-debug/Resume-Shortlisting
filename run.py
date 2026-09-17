import os
import sys
import runpy

if __name__ == '__main__':
    current_dir = os.path.dirname(os.path.abspath(__file__))
    inner_dir = os.path.join(current_dir, "USA-Resume-Shortlisting-main")
    target_app = os.path.join(inner_dir, "app.py")
    
    if os.path.exists(target_app):
        sys.path.insert(0, inner_dir)
        os.chdir(inner_dir)
        runpy.run_path(target_app, run_name='__main__')
    else:
        print(f"File {target_app} not found.")
