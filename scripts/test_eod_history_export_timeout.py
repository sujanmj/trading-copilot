"""Verify EOD's last export child has a finite wait boundary."""

import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.lifecycle import prediction_lifecycle_engine as lifecycle
from backend.utils import runner


def main() -> None:
    with patch('backend.utils.runner.run_script') as run_script:
        lifecycle._run_history_export()

    run_script.assert_called_once_with(
        'history_exporter.py',
        check=False,
        timeout=lifecycle.HISTORY_EXPORT_TIMEOUT_SECONDS,
    )
    assert lifecycle.HISTORY_EXPORT_TIMEOUT_SECONDS == 1200

    with patch('backend.utils.runner.subprocess.run') as subprocess_run:
        runner.run_script('history_exporter.py', timeout=1200)
    assert subprocess_run.call_args.kwargs['timeout'] == 1200
    print('EOD_HISTORY_EXPORT_TIMEOUT_PASS')


if __name__ == '__main__':
    main()
