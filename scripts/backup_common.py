"""Shared constants and helpers for backup / restore scripts."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

# Project root: scripts/ -> parent
PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKUPS_ROOT = PROJECT_ROOT / "backups"
ARCHIVE_DIR = BACKUPS_ROOT / "archive"
LATEST_STABLE_DIR = BACKUPS_ROOT / "latest_stable"

SNAPSHOT_PREFIX = "stable"

# Top-level directories copied in full (subject to EXCLUDE_NAMES / EXCLUDE_GLOBS).
INCLUDED_TOP_LEVEL_DIRS = ("backend", "frontend", "scripts", "config")

# Root-level files / globs included in every snapshot.
INCLUDED_ROOT_NAMES = (
    "requirements.txt",
    ".env.example",
    "Procfile",
    "railway.json",
    "nixpacks.toml",
    "runtime.txt",
    "run_local.py",
    "start_local.bat",
    "generate_session.py",
    "DEPLOY_CHECKLIST.md",
    "OBSERVATION_GUIDE.md",
)

INCLUDED_ROOT_GLOBS = ("README*",)

# Selective data/ content (runtime caches excluded separately).
DATA_DB_GLOBS = ("*.db", "*.db-journal", "*.db-wal", "*.db-shm", "*.sqlite", "*.sqlite3")
DATA_SUBDIRS = ("daily_reviews", "provider_analytics", "exports")

# Directories / patterns never copied into a snapshot.
EXCLUDE_DIR_NAMES = {
    ".git",
    "backups",
    "node_modules",
    "venv",
    ".venv",
    "env",
    "ENV",
    "__pycache__",
    ".pytest_cache",
    "temp",
    "cache",
    "ai_cache",
    "debug_snapshots",
    ".locks",
    "dist",
    "build",
    "out",
    "htmlcov",
    ".tox",
    ".npm",
}

EXCLUDE_FILE_SUFFIXES = (".log", ".pyc", ".pyo")

# Minimum free disk space (bytes) required before creating a backup.
MIN_FREE_DISK_BYTES = 100 * 1024 * 1024  # 100 MB

# Required paths that must exist in a valid snapshot for restore.
RESTORE_REQUIRED_DIRS = ("backend", "frontend", "scripts")
RESTORE_REQUIRED_FILES = ("manifest.json",)


def log(msg: str) -> None:
    print(msg, flush=True)


def err(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr, flush=True)


def snapshot_name_from_now(when: datetime | None = None) -> str:
    ts = when or datetime.now()
    return f"{SNAPSHOT_PREFIX}_{ts.strftime('%Y_%m_%d_%H%M%S')}"


def get_git_commit_hash(root: Path = PROJECT_ROOT) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def ensure_backup_dirs() -> None:
    for path in (BACKUPS_ROOT, ARCHIVE_DIR, LATEST_STABLE_DIR):
        path.mkdir(parents=True, exist_ok=True)


def list_snapshots() -> list[Path]:
    """Return archive snapshot directories sorted newest-first."""
    ensure_backup_dirs()
    snapshots = [
        p
        for p in ARCHIVE_DIR.iterdir()
        if p.is_dir() and p.name.startswith(f"{SNAPSHOT_PREFIX}_")
    ]
    snapshots.sort(key=lambda p: p.name, reverse=True)
    return snapshots


def resolve_snapshot(name: str | None) -> Path | None:
    if not name:
        return None
    candidate = ARCHIVE_DIR / name
    if candidate.is_dir():
        return candidate
    if not name.startswith(f"{SNAPSHOT_PREFIX}_"):
        prefixed = ARCHIVE_DIR / f"{SNAPSHOT_PREFIX}_{name}"
        if prefixed.is_dir():
            return prefixed
    return None


def should_exclude_dir(name: str) -> bool:
    return name in EXCLUDE_DIR_NAMES


def should_exclude_file(name: str) -> bool:
    lower = name.lower()
    if lower.endswith(EXCLUDE_FILE_SUFFIXES):
        return True
    if lower.endswith(".bak") or lower.endswith(".old"):
        return True
    return False


def copy_tree_filtered(src: Path, dst: Path) -> None:
    """Copy directory tree skipping excluded dirs/files."""
    if not src.is_dir():
        return
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        if item.is_dir():
            if should_exclude_dir(item.name):
                continue
            copy_tree_filtered(item, dst / item.name)
        elif item.is_file():
            if should_exclude_file(item.name):
                continue
            target = dst / item.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


def copy_file_if_exists(src: Path, dst: Path) -> bool:
    if not src.is_file():
        return False
    if should_exclude_file(src.name):
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


def copy_root_files(snapshot_dir: Path) -> list[str]:
    copied: list[str] = []
    for name in INCLUDED_ROOT_NAMES:
        src = PROJECT_ROOT / name
        if copy_file_if_exists(src, snapshot_dir / name):
            copied.append(name)
    for pattern in INCLUDED_ROOT_GLOBS:
        for src in sorted(PROJECT_ROOT.glob(pattern)):
            if src.is_file() and not should_exclude_file(src.name):
                rel = src.name
                if copy_file_if_exists(src, snapshot_dir / rel):
                    copied.append(rel)
    return copied


def copy_data_selective(snapshot_dir: Path) -> list[str]:
    """Copy sqlite DBs and non-cache data subdirs."""
    data_src = PROJECT_ROOT / "data"
    if not data_src.is_dir():
        return []

    data_dst = snapshot_dir / "data"
    copied: list[str] = []

    for pattern in DATA_DB_GLOBS:
        for db_file in sorted(data_src.glob(pattern)):
            if db_file.is_file():
                rel = db_file.relative_to(PROJECT_ROOT).as_posix()
                if copy_file_if_exists(db_file, snapshot_dir / db_file.relative_to(PROJECT_ROOT)):
                    copied.append(rel)

    for sub in DATA_SUBDIRS:
        sub_src = data_src / sub
        if sub_src.is_dir():
            copy_tree_filtered(sub_src, data_dst / sub)
            copied.append(f"data/{sub}/")

    return copied


def directory_size_bytes(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if not should_exclude_dir(d)]
        for fname in files:
            if should_exclude_file(fname):
                continue
            try:
                total += (Path(root) / fname).stat().st_size
            except OSError:
                pass
    return total


def estimate_project_backup_size() -> int:
    total = 0
    for name in INCLUDED_TOP_LEVEL_DIRS:
        total += directory_size_bytes(PROJECT_ROOT / name)
    total += directory_size_bytes(PROJECT_ROOT / "data")
    for name in INCLUDED_ROOT_NAMES:
        p = PROJECT_ROOT / name
        if p.is_file():
            total += p.stat().st_size
    for pattern in INCLUDED_ROOT_GLOBS:
        for p in PROJECT_ROOT.glob(pattern):
            if p.is_file():
                total += p.stat().st_size
    return total


def disk_free_bytes(path: Path) -> int:
    usage = shutil.disk_usage(path)
    return usage.free


def validate_backup_preflight() -> tuple[bool, str]:
    if not PROJECT_ROOT.is_dir():
        return False, f"Project root not found: {PROJECT_ROOT}"
    ensure_backup_dirs()
    test_file = BACKUPS_ROOT / ".write_test"
    try:
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink()
    except OSError as exc:
        return False, f"Backup folder not writable: {BACKUPS_ROOT} ({exc})"

    needed = estimate_project_backup_size()
    free = disk_free_bytes(BACKUPS_ROOT)
    if free < MIN_FREE_DISK_BYTES:
        return False, f"Insufficient disk space: {free // (1024 * 1024)} MB free (need at least {MIN_FREE_DISK_BYTES // (1024 * 1024)} MB)"
    if free < needed:
        return False, (
            f"Insufficient disk space for estimated backup size: "
            f"need ~{needed // (1024 * 1024)} MB, have {free // (1024 * 1024)} MB free"
        )
    return True, ""


def build_manifest(
    snapshot_name: str,
    snapshot_dir: Path,
    included_directories: Iterable[str],
    user_note: str | None = None,
) -> dict:
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "snapshot_name": snapshot_name,
        "project_size_bytes": directory_size_bytes(snapshot_dir),
        "included_directories": sorted(set(included_directories)),
        "git_commit_hash": get_git_commit_hash(),
        "user_note": user_note or None,
        "project_root": str(PROJECT_ROOT),
    }


def write_manifest(snapshot_dir: Path, manifest: dict) -> Path:
    manifest_path = snapshot_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def read_manifest(snapshot_dir: Path) -> dict | None:
    manifest_path = snapshot_dir / "manifest.json"
    if not manifest_path.is_file():
        return None
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def validate_snapshot_integrity(snapshot_dir: Path) -> tuple[bool, list[str]]:
    issues: list[str] = []
    manifest = read_manifest(snapshot_dir)
    if manifest is None:
        issues.append("manifest.json missing or invalid")
    for req_dir in RESTORE_REQUIRED_DIRS:
        if not (snapshot_dir / req_dir).is_dir():
            issues.append(f"required directory missing: {req_dir}/")
    return len(issues) == 0, issues


def update_latest_stable_pointer(snapshot_dir: Path, manifest: dict) -> None:
    """Update latest_stable symlink/junction or pointer.json fallback."""
    LATEST_STABLE_DIR.mkdir(parents=True, exist_ok=True)

    pointer = {
        "snapshot_name": manifest["snapshot_name"],
        "snapshot_path": str(snapshot_dir.resolve()),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "git_commit_hash": manifest.get("git_commit_hash"),
        "user_note": manifest.get("user_note"),
    }
    pointer_path = LATEST_STABLE_DIR / "pointer.json"
    pointer_path.write_text(json.dumps(pointer, indent=2) + "\n", encoding="utf-8")

    manifest_copy = LATEST_STABLE_DIR / "manifest.json"
    shutil.copy2(snapshot_dir / "manifest.json", manifest_copy)

    link_path = LATEST_STABLE_DIR / "snapshot"
    if link_path.exists() or link_path.is_symlink():
        if link_path.is_dir() and not link_path.is_symlink():
            shutil.rmtree(link_path)
        else:
            link_path.unlink(missing_ok=True)

    try:
        if os.name == "nt":
            subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link_path), str(snapshot_dir.resolve())],
                check=True,
                capture_output=True,
                timeout=15,
            )
        else:
            link_path.symlink_to(snapshot_dir.resolve(), target_is_directory=True)
    except (OSError, subprocess.SubprocessError):
        # pointer.json + manifest.json are sufficient on Windows without admin.
        pass
