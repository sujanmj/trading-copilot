"""Railway-compatible API server entry shim."""

from backend.utils.bootstrap import setup_project_path

setup_project_path()

from backend.api.api_server import app  # noqa: E402,F401

if __name__ == '__main__':
    from backend.api.api_server import main

    main()
