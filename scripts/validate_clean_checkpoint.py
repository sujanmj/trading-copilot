#!/usr/bin/env python3
"""
Validate the latest recovery/clean_checkpoint_*.zip.

Usage:
  python scripts/validate_clean_checkpoint.py

Prints exactly CLEAN_CHECKPOINT_VALIDATE_OK on success; exits 1 on failure.
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path, PurePosixPath

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RECOVERY_DIR = PROJECT_ROOT / "recovery"
CHECKPOINT_GLOB = "clean_checkpoint_*.zip"

REQUIRED_DIRS = ("backend/", "frontend/", "scripts/")
REQUIRED_FILES = (
    "data/canonical_market_memory.db",
    "data/trading_history.db",
    "data/latest_market_data_memory_enriched.json",
)
FORBIDDEN = "config/keys.env"


def _fail(msg: str) -> int:
    print(f"CLEAN_CHECKPOINT_VALIDATE_FAIL: {msg}", file=sys.stderr)
    return 1


def _latest_checkpoint() -> Path | None:
    if not RECOVERY_DIR.is_dir():
        return None
    zips = sorted(
        RECOVERY_DIR.glob(CHECKPOINT_GLOB),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return zips[0] if zips else None


def _normalize_name(name: str) -> str:
    return PurePosixPath(name.replace("\\", "/")).as_posix()


def _has_dir_prefix(names: list[str], prefix: str) -> bool:
    return any(
        n == prefix.rstrip("/") or n.startswith(prefix)
        for n in names
    )


def main() -> int:
    latest = _latest_checkpoint()
    if latest is None:
        return _fail(f"no checkpoint zip matching {CHECKPOINT_GLOB} in {RECOVERY_DIR}")

    try:
        with zipfile.ZipFile(latest, "r") as zf:
            if zf.testzip() is not None:
                return _fail(f"corrupt zip: {latest.name}")

            names = [_normalize_name(n) for n in zf.namelist()]

            for prefix in REQUIRED_DIRS:
                if not _has_dir_prefix(names, prefix):
                    return _fail(f"missing directory prefix: {prefix}")

            for required in REQUIRED_FILES:
                if required not in names:
                    return _fail(f"missing required file: {required}")

            if FORBIDDEN in names or any(n.endswith("/keys.env") and "config" in n for n in names):
                return _fail("config/keys.env must not be present")

    except (OSError, zipfile.BadZipFile) as exc:
        return _fail(f"cannot open zip: {exc}")

    print("CLEAN_CHECKPOINT_VALIDATE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
