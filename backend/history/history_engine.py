"""History export orchestration with heartbeat and integrity validation."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, Optional

import pytz

from backend.storage.json_io import atomic_write_json
from backend.utils.config import DATA_DIR

IST = pytz.timezone('Asia/Kolkata')
HEARTBEAT_FILE = DATA_DIR / 'history_engine_heartbeat.json'


def _now_iso() -> str:
    return datetime.now(IST).isoformat()


def update_history_heartbeat(*, status: str, detail: str = '', extra: Optional[dict] = None) -> dict:
    payload = {
        'status': status,
        'heartbeat_at': _now_iso(),
        'last_successful_history': None,
        'detail': detail,
    }
    if HEARTBEAT_FILE.exists():
        try:
            prev = json.loads(HEARTBEAT_FILE.read_text(encoding='utf-8'))
            if isinstance(prev, dict):
                payload['last_successful_history'] = prev.get('last_successful_history')
        except Exception:
            pass
    if status == 'ok':
        payload['last_successful_history'] = _now_iso()
    if extra:
        payload.update(extra)
    atomic_write_json(HEARTBEAT_FILE, payload)
    try:
        from backend.lifecycle.lifecycle_tracing import update_heartbeat
        update_heartbeat(
            pipeline_status='RUNNING',
            current_stage='history_export',
            extra={'history_engine_status': status, 'history_engine_detail': detail},
        )
    except Exception:
        pass
    return payload


def get_history_heartbeat() -> dict:
    if not HEARTBEAT_FILE.exists():
        return {'status': 'unknown', 'heartbeat_at': None, 'last_successful_history': None}
    try:
        return json.loads(HEARTBEAT_FILE.read_text(encoding='utf-8'))
    except Exception:
        return {'status': 'degraded', 'heartbeat_at': None, 'last_successful_history': None}


def run_history_export() -> Dict[str, Any]:
    """Export history with integrity checks — fail visibly on corruption."""
    from backend.history.replay_integrity import validate_history_export
    from backend.storage.history_exporter import build_export

    update_history_heartbeat(status='running', detail='export started')
    try:
        output = build_export()
        ok, issues = validate_history_export(output)
        if not ok:
            update_history_heartbeat(status='failed', detail='; '.join(issues[:3]))
            raise RuntimeError(f'History integrity failed: {issues[0]}')
        manifest = {
            'export_id': f"hist_{datetime.now(IST).strftime('%Y%m%d_%H%M%S')}",
            'validated_at': _now_iso(),
            'periods': list((output.get('periods') or {}).keys()),
            'journal_entries': len(((output.get('intelligence_journal') or {}).get('entries') or [])),
            'integrity_ok': True,
        }
        output['export_manifest'] = manifest
        atomic_write_json(DATA_DIR / 'history_data.json', output)
        update_history_heartbeat(status='ok', detail='export validated', extra={'manifest': manifest})
        return output
    except Exception as exc:
        update_history_heartbeat(status='failed', detail=str(exc)[:200])
        raise
