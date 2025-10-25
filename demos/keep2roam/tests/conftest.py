# [AUTO] ensure package root is on sys.path for imports like 'from models import X'
import sys, pathlib
_pkg_root = pathlib.Path(__file__).resolve().parents[1]
p = str(_pkg_root)
if p not in sys.path:
    sys.path.insert(0, p)
