# Emergency Recovery Guide

Production backup and restore for **trading-copilot**. Snapshots capture code, configs, SQLite databases, and deployment files — not runtime caches or secrets committed to git.

## Quick reference

```bash
# Create a backup (recommended before any major change)
python scripts/create_backup.py

# Create a backup with a note
python scripts/create_backup.py --note "frontend stable"

# Create backup + zip archive
python scripts/create_backup.py --zip

# List available backups
python scripts/restore_backup.py --list

# Interactive restore
python scripts/restore_backup.py

# Restore a specific snapshot
python scripts/restore_backup.py --name stable_2026_05_28_021530

# Restore latest successful backup (no prompt with --yes)
python scripts/restore_backup.py --latest --yes
```

## What gets backed up

| Included | Excluded |
|----------|----------|
| `backend/`, `frontend/`, `scripts/`, `config/` | `node_modules/`, `venv/`, `.venv/` |
| SQLite DBs in `data/` (`trading_history.db`, `predictions.db`, etc.) | `data/ai_cache/`, `data/debug_snapshots/` |
| `data/daily_reviews/`, `data/provider_analytics/`, `data/exports/` | `__pycache__/`, `*.log`, `.git/` |
| `requirements.txt`, `README*`, `.env.example` | `backups/` (no recursive backup) |
| Deployment files (`Procfile`, `railway.json`, etc.) | Runtime temp/cache dirs |

Each snapshot includes a `manifest.json` with timestamp, size, git commit, and optional `--note`.

## Directory layout

```
backups/
├── README.md
├── archive/
│   └── stable_YYYY_MM_DD_HHMMSS/   # full snapshots
└── latest_stable/
    ├── pointer.json                # path to newest snapshot
    ├── manifest.json               # copy of latest manifest
    └── snapshot/                   # junction/symlink when supported
```

Snapshots are **never overwritten** and archives are **never auto-deleted**.

---

## Safe workflow before major changes

1. **Create a backup** with a descriptive note:
   ```bash
   python scripts/create_backup.py --note "before scheduler refactor"
   ```
2. Confirm `backups/latest_stable/pointer.json` points to the new snapshot.
3. Make your changes and test locally.
4. If something breaks, restore (see below) — the backup remains intact.

---

## How to restore (rollback)

Restore copies snapshot contents **into the project root**. It does **not** delete the backup.

```bash
python scripts/restore_backup.py --list
python scripts/restore_backup.py --name stable_2026_05_28_021530
```

Or restore the latest:

```bash
python scripts/restore_backup.py --latest
```

After restore:

```bash
pip install -r requirements.txt
cd frontend && npm install
# Verify config/keys.env exists and has your API keys
python run_local.py   # or your usual start command
```

---

## Recover frontend only

If only the frontend broke:

1. List backups: `python scripts/restore_backup.py --list`
2. Manually copy `frontend/` from the snapshot:
   ```powershell
   # PowerShell example
   $snap = "backups\archive\stable_2026_05_28_021530"
   Remove-Item -Recurse -Force frontend
   Copy-Item -Recurse "$snap\frontend" frontend
   cd frontend; npm install
   ```

Or run a full restore if you prefer a clean rollback.

---

## Recover database (SQLite)

Databases live in `data/`:

- `data/trading_history.db`
- `data/predictions.db`
- `data/trading_copilot.db`

To restore DBs only:

```powershell
$snap = "backups\archive\stable_2026_05_28_021530"
Copy-Item "$snap\data\*.db" data\ -Force
# Include WAL/SHM if present
Copy-Item "$snap\data\*.db-*" data\ -Force -ErrorAction SilentlyContinue
```

**Stop the application** before overwriting live database files.

---

## Rollback architecture / backend changes

For backend or orchestration regressions, use a full restore:

```bash
python scripts/create_backup.py --note "broken state before rollback"
python scripts/restore_backup.py --latest --yes
pip install -r requirements.txt
```

The pre-rollback backup preserves the broken state if you need to compare later.

---

## Integrity checks

**Before backup:** project root exists, disk space sufficient, `backups/` writable.

**Before restore:** `manifest.json` present, required dirs (`backend/`, `frontend/`, `scripts/`) exist in snapshot.

If integrity fails, pick an older snapshot from `backups/archive/`.

---

## Windows notes

- Paths use `pathlib` for cross-platform safety.
- `latest_stable/snapshot` uses a directory junction when `mklink /J` succeeds; otherwise use `pointer.json`.
- Run scripts from the project root or any directory — paths resolve automatically.

---

## Troubleshooting

| Problem | Action |
|---------|--------|
| "Insufficient disk space" | Free space on the drive hosting `backups/` |
| "Snapshot already exists" | Never overwritten by design — wait 1 second or delete old test snapshot manually |
| Restore missing API keys | Restore does not remove `config/keys.env` if not in snapshot; verify `config/` after restore |
| Empty backup list | Run `python scripts/create_backup.py` first |

---

## Sample manifest

See `backups/archive/<snapshot>/manifest.json` after your first backup. Example structure:

```json
{
  "timestamp": "2026-05-28T02:15:30+00:00",
  "snapshot_name": "stable_2026_05_28_021530",
  "project_size_bytes": 5242880,
  "included_directories": [
    "backend/",
    "config/",
    "data/",
    "frontend/",
    "root files",
    "scripts/"
  ],
  "git_commit_hash": "abc123def456",
  "user_note": "frontend stable",
  "project_root": "C:\\Users\\sujan\\trading-copilot"
}
```
