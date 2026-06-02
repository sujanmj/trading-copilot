"""Ensure project root is on sys.path for backend package imports."""

import sys
from pathlib import Path

_done = False


def setup_project_path():
    global _done
    if _done:
        return
    # backend/utils/bootstrap.py -> project root is 3 levels up
    project_root = Path(__file__).resolve().parent.parent.parent
    root_str = str(project_root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    _done = True
