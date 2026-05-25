"""Atomic JSON file writes — avoids partial/corrupt files on crash."""

import json
from pathlib import Path


def atomic_write_json(filepath, data):
    filepath = Path(filepath)
    tmp = filepath.with_suffix('.tmp')
    filepath.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, default=str, ensure_ascii=False)
        tmp.replace(filepath)
    except Exception as e:
        if tmp.exists():
            tmp.unlink()
        raise e
