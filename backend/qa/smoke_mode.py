"""QA smoke isolation helpers (Phase 4B.18A)."""

from __future__ import annotations

import os

QA_SMOKE_ENV = 'ASTRAEDGE_QA_SMOKE'


def qa_smoke_enabled() -> bool:
    """True when /qa smoke sets ASTRAEDGE_QA_SMOKE=1 on the child process."""
    return os.environ.get(QA_SMOKE_ENV, '').strip().lower() in ('1', 'true', 'yes', 'on')


def should_skip_nested_regression() -> bool:
    """Skip nested regression subprocess suites during /qa smoke."""
    return qa_smoke_enabled()
