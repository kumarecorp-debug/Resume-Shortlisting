import os
import sys
import importlib.util

current_dir = os.path.dirname(os.path.abspath(__file__))
inner_dir = os.path.join(current_dir, "USA-Resume-Shortlisting-main")

if inner_dir not in sys.path:
    sys.path.insert(0, inner_dir)

try:
    os.chdir(inner_dir)
except Exception:
    pass

inner_app_path = os.path.join(inner_dir, "app.py")
spec = importlib.util.spec_from_file_location("main_app", inner_app_path)
main_app_module = importlib.util.module_from_spec(spec)
sys.modules["main_app"] = main_app_module
spec.loader.exec_module(main_app_module)

app = main_app_module.app

if __name__ == '__main__':
    app.run(debug=True)
