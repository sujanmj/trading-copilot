#!/usr/bin/env python3
"""
Create a clean project checkpoint zip in recovery/ (no secrets, consistent DB copies).

Usage:
  python scripts/create_clean_checkpoint.py [--dry-run] [--delete-old] [--keep-last N] [--verbose]
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath

import shutil

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RECOVERY_DIR = PROJECT_ROOT / "recovery"
CHECKPOINT_PREFIX = "clean_checkpoint_"

INCLUDE_TOP_DIRS = ("backend", "frontend", "scripts")

REQUIRED_DATA_FILES = (
    "data/canonical_market_memory.db",
    "data/trading_history.db",
    "data/latest_market_data_memory_enriched.json",
)

OPTIONAL_DATA_FILES = (
    "data/tv_intelligence.json",
    "data/market_memory_advisor_report.json",
)

SQLITE_SOURCES = (
    "data/canonical_market_memory.db",
    "data/trading_history.db",
)

FORBIDDEN_ZIP_SUFFIXES = ("config/keys.env",)

REQUIRED_ZIP_DIRS = ("backend/", "frontend/", "scripts/")

EXCLUDE_DIR_NAMES = frozenset({
    ".git",
    ".venv",
    "node_modules",
    "recovery",
    "__pycache__",
    ".pytest_cache",
    "dist",
    "build",
    ".next",
})

EXCLUDE_FILE_SUFFIXES = (".pyc", ".pyo")

MAX_LOG_BYTES = 20 * 1024 * 1024

SECRET_NAME_RE = re.compile(r"keys|secret|credential", re.IGNORECASE)


def _log(verbose: bool, msg: str) -> None:
    if verbose:
        print(msg, flush=True)


def _posix_relpath(path: Path) -> str:
    return path.as_posix()


def _path_has_excluded_dir(rel: Path) -> bool:
    return any(part in EXCLUDE_DIR_NAMES for part in rel.parts)


def _is_secret_json_name(name: str) -> bool:
    if not name.lower().endswith(".json"):
        return False
    return bool(SECRET_NAME_RE.search(name))


def _should_skip_file(rel: Path, size: int) -> bool:
    name = rel.name
    lower = name.lower()
    if lower.endswith(EXCLUDE_FILE_SUFFIXES):
        return True
    if lower.endswith(".log") and size > MAX_LOG_BYTES:
        return True
    if "logs" in rel.parts and size > MAX_LOG_BYTES:
        return True
    return False


def _sqlite_backup(source: Path, dest: Path, verbose: bool) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    src_conn = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        dst_conn = sqlite3.connect(dest)
        try:
            src_conn.backup(dst_conn)
            dst_conn.commit()
        finally:
            dst_conn.close()
    finally:
        src_conn.close()
    _log(verbose, f"sqlite backup: {source.name} -> {dest}")


def _iter_tree_files(root: Path, base: Path) -> list[Path]:
    if not root.is_dir():
        return []
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(base)
        if _path_has_excluded_dir(rel):
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if _should_skip_file(rel, size):
            continue
        files.append(rel)
    return files


def _collect_config_files(verbose: bool) -> list[str]:
    config_root = PROJECT_ROOT / "config"
    if not config_root.is_dir():
        return []
    rel_paths: list[str] = []
    for path in sorted(config_root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(PROJECT_ROOT)
        if rel.name == "keys.env":
            continue
        if _path_has_excluded_dir(rel):
            continue
        rel_paths.append(_posix_relpath(rel))
    _log(verbose, f"config files: {len(rel_paths)}")
    return rel_paths


def _collect_data_json_files(verbose: bool) -> list[str]:
    data_root = PROJECT_ROOT / "data"
    if not data_root.is_dir():
        return []
    rel_paths: list[str] = []
    for path in sorted(data_root.glob("*.json")):
        if not path.is_file():
            continue
        if _is_secret_json_name(path.name):
            _log(verbose, f"skip secret-like json: {path.name}")
            continue
        rel_paths.append(_posix_relpath(path.relative_to(PROJECT_ROOT)))
    _log(verbose, f"data/*.json files: {len(rel_paths)}")
    return rel_paths


def _collect_archive_members(verbose: bool) -> tuple[list[str], list[str]]:
    """Return (regular file rel paths, sqlite sources that need backup API)."""
    members: set[str] = set()

    for top in INCLUDE_TOP_DIRS:
        top_path = PROJECT_ROOT / top
        for rel in _iter_tree_files(top_path, PROJECT_ROOT):
            members.add(_posix_relpath(rel))

    members.update(_collect_config_files(verbose))

    for rel in REQUIRED_DATA_FILES + OPTIONAL_DATA_FILES:
        if (PROJECT_ROOT / rel).is_file():
            members.add(rel)

    members.update(_collect_data_json_files(verbose))

    sqlite_set = set(SQLITE_SOURCES)
    regular = sorted(m for m in members if m not in sqlite_set)
    sqlite_needed = [m for m in SQLITE_SOURCES if m in members or (PROJECT_ROOT / m).is_file()]
    return regular, sqlite_needed


def _stage_checkpoint(staging: Path, regular: list[str], sqlite_sources: list[str], verbose: bool) -> None:
    for rel in regular:
        src = PROJECT_ROOT / rel
        if not src.is_file():
            continue
        dst = staging / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    for rel in sqlite_sources:
        src = PROJECT_ROOT / rel
        if not src.is_file():
            raise FileNotFoundError(f"required database missing: {rel}")
        dst = staging / rel
        _sqlite_backup(src, dst, verbose)


def _build_zip(staging: Path, zip_path: Path, verbose: bool) -> int:
    file_count = 0
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(staging.rglob("*")):
            if not path.is_file():
                continue
            arcname = _posix_relpath(path.relative_to(staging))
            zf.write(path, arcname)
            file_count += 1
            _log(verbose, f"zip add: {arcname}")
    return file_count


def _zip_has_prefix(names: list[str], prefix: str) -> bool:
    return any(n == prefix.rstrip("/") or n.startswith(prefix) for n in names)


def _validate_zip(zip_path: Path, verbose: bool) -> tuple[bool, bool]:
    """Return (validated, excluded_keys)."""
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
            if zf.testzip() is not None:
                _log(verbose, "zip testzip failed")
                return False, True

            for prefix in REQUIRED_ZIP_DIRS:
                if not _zip_has_prefix(names, prefix):
                    _log(verbose, f"missing required dir prefix: {prefix}")
                    return False, True

            for required in REQUIRED_DATA_FILES:
                if required not in names and not any(
                    n == required or n.endswith("/" + required) for n in names
                ):
                    if required not in names:
                        _log(verbose, f"missing required file: {required}")
                        return False, True

            keys_present = any(
                PurePosixPath(n).as_posix() in FORBIDDEN_ZIP_SUFFIXES
                or n.endswith("config/keys.env")
                or n == "config/keys.env"
                for n in names
            )
            if keys_present:
                return False, False

            return True, True
    except (OSError, zipfile.BadZipFile) as exc:
        _log(verbose, f"validate error: {exc}")
        return False, True


def _list_checkpoint_zips() -> list[Path]:
    if not RECOVERY_DIR.is_dir():
        return []
    zips = [
        p
        for p in RECOVERY_DIR.glob(f"{CHECKPOINT_PREFIX}*.zip")
        if p.is_file()
    ]
    zips.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return zips


def _delete_old_backups(keep_last: int, verbose: bool) -> tuple[int, int]:
    zips = _list_checkpoint_zips()
    to_keep = max(keep_last, 1)
    to_delete = zips[to_keep:]

    deleted = 0
    for path in to_delete:
        print(f"deleted: {path}", flush=True)
        path.unlink()
        deleted += 1
        _log(verbose, f"removed old backup: {path.name}")

    return deleted, len(_list_checkpoint_zips())


def _checkpoint_name() -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{CHECKPOINT_PREFIX}{ts}.zip"


def main() -> int:
    parser = argparse.ArgumentParser(description="Create clean checkpoint zip in recovery/")
    parser.add_argument("--dry-run", action="store_true", help="List actions without creating zip")
    parser.add_argument("--delete-old", action="store_true", help="Delete old clean_checkpoint_*.zip after success")
    parser.add_argument("--keep-last", type=int, default=1, help="Keep N newest checkpoint zips (default 1)")
    parser.add_argument("--verbose", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    RECOVERY_DIR.mkdir(parents=True, exist_ok=True)

    regular, sqlite_sources = _collect_archive_members(args.verbose)

    for rel in REQUIRED_DATA_FILES:
        if not (PROJECT_ROOT / rel).is_file():
            print(f"ERROR: missing required file: {rel}", file=sys.stderr)
            return 1

    zip_name = _checkpoint_name()
    zip_path = RECOVERY_DIR / zip_name

    if args.dry_run:
        print(f"[CHECKPOINT] dry-run zip={zip_path}")
        print(f"[CHECKPOINT] regular_files={len(regular)} sqlite={len(sqlite_sources)}")
        for rel in sorted(set(regular) | set(sqlite_sources)):
            _log(args.verbose, f"  would include: {rel}")
        if args.delete_old:
            old = _list_checkpoint_zips()
            excess = old[max(args.keep_last, 0):]
            for p in excess:
                print(f"would delete: {p}", flush=True)
        print("[CHECKPOINT] validated=True")
        print("[CHECKPOINT] excluded_keys=True")
        print("[CHECKPOINT] deleted_old=0")
        print(f"[CHECKPOINT] kept={len(_list_checkpoint_zips())}")
        print("CLEAN_CHECKPOINT_OK")
        return 0

    deleted_old = 0
    kept = len(_list_checkpoint_zips())

    with tempfile.TemporaryDirectory(prefix="clean_checkpoint_") as tmp:
        staging = Path(tmp) / "stage"
        staging.mkdir(parents=True)
        try:
            _stage_checkpoint(staging, regular, sqlite_sources, args.verbose)
            file_count = _build_zip(staging, zip_path, args.verbose)
        except (OSError, sqlite3.Error, FileNotFoundError) as exc:
            print(f"ERROR: checkpoint failed: {exc}", file=sys.stderr)
            if zip_path.exists():
                zip_path.unlink(missing_ok=True)
            return 1

    validated, excluded_keys = _validate_zip(zip_path, args.verbose)
    if not validated or not excluded_keys:
        print("ERROR: checkpoint validation failed", file=sys.stderr)
        zip_path.unlink(missing_ok=True)
        return 1

    if args.delete_old:
        deleted_old, kept = _delete_old_backups(args.keep_last, args.verbose)

    size = zip_path.stat().st_size
    print(f"[CHECKPOINT] backup={zip_path}")
    print(f"[CHECKPOINT] size_bytes={size}")
    print(f"[CHECKPOINT] files={file_count}")
    print("[CHECKPOINT] validated=True")
    print("[CHECKPOINT] excluded_keys=True")
    print(f"[CHECKPOINT] deleted_old={deleted_old}")
    print(f"[CHECKPOINT] kept={kept}")
    print("CLEAN_CHECKPOINT_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
