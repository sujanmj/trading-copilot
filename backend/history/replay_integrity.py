"""Replay integrity validation for history exports."""

from __future__ import annotations

from typing import List, Tuple


def validate_history_export(output: dict) -> Tuple[bool, List[str]]:
    issues: List[str] = []
    if not isinstance(output, dict):
        return False, ['export is not a dict']
    if output.get('error'):
        issues.append(f"export error: {output.get('error')}")
    periods = output.get('periods')
    if not isinstance(periods, dict) or not periods:
        issues.append('periods missing or empty')
    journal = output.get('intelligence_journal') or {}
    if journal.get('status') == 'degraded':
        issues.append(f"journal degraded: {journal.get('reason', 'unknown')}")
    total_db = output.get('total_in_db') or {}
    try:
        from backend.storage.history_exporter import get_db_path
        import sqlite3
        db_path = get_db_path()
        if db_path.exists():
            conn = sqlite3.connect(str(db_path))
            try:
                pred_count = conn.execute('SELECT COUNT(*) FROM predictions').fetchone()[0]
                exported_preds = int(total_db.get('predictions') or 0)
                if exported_preds and pred_count and exported_preds > pred_count * 1.05:
                    issues.append(f'exported predictions {exported_preds} exceeds db {pred_count}')
            finally:
                conn.close()
    except Exception as exc:
        issues.append(f'db cross-check skipped: {exc}')
    for name, period in (periods or {}).items():
        stats = (period or {}).get('stats') or {}
        wins = int(stats.get('wins') or 0)
        losses = int(stats.get('losses') or 0)
        evaluated = int(stats.get('evaluated') or 0)
        if evaluated and wins + losses > evaluated + int(stats.get('neutral') or 0) + 5:
            issues.append(f'period {name} stats inconsistent')
    return (len(issues) == 0, issues)
