"""Railway-compatible API server entry shim.

Prefer module execution:
  python -m backend.api_server
  uvicorn backend.api.api_server:app --host 0.0.0.0 --port $PORT
"""

from backend.utils.bootstrap import setup_project_path

setup_project_path()

from backend.api.api_server import app  # noqa: E402,F401

if __name__ == '__main__':
    from backend.api.api_server import main

    main()
