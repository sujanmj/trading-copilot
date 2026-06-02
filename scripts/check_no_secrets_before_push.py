#!/usr/bin/env python3
"""
Pre-push secret guard (Stage 46B).

Usage:
  python scripts/check_no_secrets_before_push.py

Uses git ls-files / git check-ignore. Does not print secret values.
Prints NO_SECRETS_BEFORE_PUSH_OK on success.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    os.chdir(PROJECT_ROOT)

STAGE_MARKER = 'RAILWAY_STAGE_46B_NO_SECRETS_PUSH'

RAW_SECRET_PATTERNS = (
    re.compile(r'AIza[0-9A-Za-z\-_]{20,}'),
    re.compile(r'sk-[a-zA-Z0-9]{20,}'),
    re.compile(r'bot[0-9]{8,}:[A-Za-z0-9_-]{20,}'),
)

TELEGRAM_TOKEN_ASSIGN = re.compile(
    r'TELEGRAM_BOT_TOKEN\s*=\s*["\']?[0-9]{8,}:[A-Za-z0-9_-]{20,}',
    re.IGNORECASE,
)

SCAN_SUFFIXES = ('.py', '.js', '.ts', '.tsx', '.json', '.md', '.toml', '.yaml', '.yml')
SCAN_ROOTS = ('backend', 'scripts', 'config', 'docs', 'frontend')

IGNORED_PATH_FRAGMENTS = (
    'config/keys.env',
    '.venv/',
    'venv/',
    'node_modules/',
    'recovery/',
    '__pycache__/',
)


def _fail(msg: str) -> int:
    print(f'NO_SECRETS_BEFORE_PUSH_FAIL: {msg}', file=sys.stderr)
    return 1


def _git_ls_files() -> list[str]:
    proc = subprocess.run(
        ['git', 'ls-files'],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        return []
    return [line.strip().replace('\\', '/') for line in (proc.stdout or '').splitlines() if line.strip()]


def _git_check_ignore(path: str) -> bool:
    proc = subprocess.run(
        ['git', 'check-ignore', '-q', path],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        timeout=15,
    )
    return proc.returncode == 0


def _check_keys_env_not_tracked(tracked: list[str]) -> str | None:
    if any(p.replace('\\', '/') == 'config/keys.env' for p in tracked):
        return 'config/keys.env is git-tracked'
    keys_path = PROJECT_ROOT / 'config' / 'keys.env'
    if keys_path.is_file() and not _git_check_ignore('config/keys.env'):
        return 'config/keys.env exists but is not gitignored'
    return None


def _check_venv_not_tracked(tracked: list[str]) -> str | None:
    for rel in tracked:
        norm = rel.replace('\\', '/')
        if norm.startswith('.venv/') or norm.startswith('venv/'):
            return f'venv path tracked: {rel}'
    if (PROJECT_ROOT / '.venv').is_dir() and not _git_check_ignore('.venv'):
        return '.venv/ is not gitignored'
    return None


def _check_recovery_zips_not_tracked(tracked: list[str]) -> str | None:
    for rel in tracked:
        norm = rel.replace('\\', '/')
        if norm.endswith('.zip') and ('recovery/' in norm or 'backup' in norm.lower()):
            return f'recovery/backup zip tracked: {rel}'
    return None


def _check_data_db_not_tracked(tracked: list[str]) -> str | None:
    for rel in tracked:
        norm = rel.replace('\\', '/')
        if norm.startswith('data/') and norm.endswith('.db'):
            return f'data DB tracked: {rel}'
        if norm.endswith('.sqlite') or norm.endswith('.sqlite3'):
            if not norm.startswith('recovery/'):
                return f'database file tracked: {rel}'
    return None


def _should_scan(rel: str) -> bool:
    norm = rel.replace('\\', '/')
    if not norm.startswith(SCAN_ROOTS):
        return False
    if any(frag in norm for frag in IGNORED_PATH_FRAGMENTS):
        return False
    path = PROJECT_ROOT / rel
    if not path.is_file():
        return False
    return path.suffix in SCAN_SUFFIXES or norm.endswith('.md')


def _check_no_raw_secrets_in_tracked(tracked: list[str]) -> str | None:
    for rel in tracked:
        if not _should_scan(rel):
            continue
        try:
            text = (PROJECT_ROOT / rel).read_text(encoding='utf-8', errors='ignore')
        except OSError:
            continue
        if TELEGRAM_TOKEN_ASSIGN.search(text):
            return f'TELEGRAM_BOT_TOKEN value in tracked file: {rel}'
        for pattern in RAW_SECRET_PATTERNS:
            if pattern.search(text):
                return f'possible raw API key in tracked file: {rel}'
    return None


def run_checks() -> str | None:
    tracked = _git_ls_files()
    if not tracked:
        return 'git ls-files returned no files (not a git repo?)'

    checks = (
        ('keys_env', _check_keys_env_not_tracked),
        ('venv', _check_venv_not_tracked),
        ('recovery_zips', _check_recovery_zips_not_tracked),
        ('data_db', _check_data_db_not_tracked),
        ('raw_secrets', _check_no_raw_secrets_in_tracked),
    )

    for name, fn in checks:
        err = fn(tracked)
        status = 'ok' if err is None else 'fail'
        print(f'[NO_SECRETS] {name}={status}')
        if err:
            return err
    return None


def main() -> int:
    err = run_checks()
    if err:
        return _fail(err)
    print(STAGE_MARKER)
    print('NO_SECRETS_BEFORE_PUSH_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
