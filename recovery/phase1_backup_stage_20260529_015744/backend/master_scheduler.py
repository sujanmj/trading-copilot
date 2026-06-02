"""Railway-compatible scheduler entry shim."""

from backend.utils.bootstrap import setup_project_path

setup_project_path()

if __name__ == '__main__':
    from backend.orchestration.master_scheduler import main

    main()
