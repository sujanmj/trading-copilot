"""Standalone history exports must not mark the EOD pipeline as running."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.history import history_engine


def main() -> None:
    with tempfile.TemporaryDirectory(prefix='history-lifecycle-test-') as temp_dir:
        heartbeat_path = Path(temp_dir) / 'history_engine_heartbeat.json'
        with patch.object(history_engine, 'HEARTBEAT_FILE', heartbeat_path), patch(
            'backend.lifecycle.lifecycle_tracing.update_heartbeat'
        ) as lifecycle_heartbeat:
            history_engine.update_history_heartbeat(status='running', detail='export started')
            history_engine.update_history_heartbeat(status='ok', detail='export validated')

        lifecycle_heartbeat.assert_not_called()
        saved = json.loads(heartbeat_path.read_text(encoding='utf-8'))
        assert saved['status'] == 'ok'
        assert saved['detail'] == 'export validated'
        assert saved['last_successful_history']

    print('HISTORY_EXPORT_LIFECYCLE_ISOLATION_PASS')


if __name__ == '__main__':
    main()
