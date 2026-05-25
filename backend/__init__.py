"""Trading Copilot backend package."""

import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
_root = str(_project_root)
if _root not in sys.path:
    sys.path.insert(0, _root)
