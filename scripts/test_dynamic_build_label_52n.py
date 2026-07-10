#!/usr/bin/env python3
"""AstraEdge 52N — dynamic build label hygiene."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)
os.environ.setdefault('DISABLE_TELEGRAM', '1')
os.environ.setdefault('DISABLE_TELEGRAM_SENDS', '1')

OLD_BUILD_LABELS = (
    'AstraEdge 52H',
    'AstraEdge 52I',
    'AstraEdge 52I-A',
    'AstraEdge 52J',
    'AstraEdge 52K',
    'AstraEdge 52L',
    'AstraEdge 52M',
    'AstraEdge 52N',
)
SMOKE_SCRIPTS = (
    'scripts/test_qa_smoke_isolation_4b18a.py',
    'scripts/test_qa_command_4b16.py',
    'scripts/test_help_pagination_52l.py',
    'scripts/test_telegram_stage_51a_canonical_routing.py',
    'scripts/test_build_info_stage_matches_status.py',
)


def _fail(msg: str) -> int:
    print(f'DYNAMIC_BUILD_LABEL_52N_FAIL: {msg}', file=sys.stderr)
    return 1


def test_build_info_matches_runtime() -> int:
    from scripts.test_build_helpers import assert_canonical_build

    return assert_canonical_build(_fail)


def test_health_uses_canonical_build() -> int:
    from backend.telegram.lazy_command_runner import format_canonical_health_text
    from scripts.test_build_helpers import expected_build_label, expected_health_build_line

    health = format_canonical_health_text()
    if expected_health_build_line() not in health:
        return _fail(f'/health missing {expected_health_build_line()!r}')
    err = __import__('scripts.test_build_helpers', fromlist=['assert_current_build_in_text']).assert_current_build_in_text(health)
    if err:
        return _fail(err)
    if expected_build_label() not in health:
        return _fail(f'/health missing label {expected_build_label()!r}')
    return 0


def test_qa_smoke_expected_build() -> int:
    from backend.config.build_info import TELEGRAM_BUILD
    from backend.qa.qa_runner import format_qa_result, get_qa_status, run_qa_smoke
    from scripts.test_build_helpers import expected_build_label

    if TELEGRAM_BUILD != expected_build_label():
        return _fail('build_info TELEGRAM_BUILD != helper expected_build_label()')
    status_text = get_qa_status()
    if f'Build: {expected_build_label()}' not in status_text:
        return _fail('QA status missing canonical build label')
    result = run_qa_smoke()
    text = format_qa_result(result)
    if 'QA SMOKE — PASS' not in text:
        return _fail(f'QA smoke must PASS, got {text.splitlines()[0]!r}')
    return 0


def test_help_uses_canonical_build() -> int:
    from backend.telegram.help_text import format_help_index
    from scripts.test_build_helpers import expected_help_build_line

    text = format_help_index()
    if expected_help_build_line() not in text:
        return _fail(f'help index missing {expected_help_build_line()!r}')
    return 0


def test_smoke_scripts_avoid_hardcoded_old_labels() -> int:
    assertion_pattern = re.compile(
        r"(if\s+.*!=\s*'AstraEdge\s+(?:52[HIJKLM]|52I-A)|"
        r"'AstraEdge\s+(?:52[HIJKLM]|52I-A)'\s+not\s+in|"
        r"expected\s+AstraEdge\s+(?:52[HIJKLM]|52I-A))",
        re.IGNORECASE,
    )
    for rel in SMOKE_SCRIPTS:
        src = (PROJECT_ROOT / rel).read_text(encoding='utf-8')
        for label in OLD_BUILD_LABELS:
            if f"'{label}'" in src and 'OLD_BUILD_LABELS' not in src:
                # allow historical docstrings only when not in assertion-like lines
                for line_no, line in enumerate(src.splitlines(), start=1):
                    if f"'{label}'" in line and not line.strip().startswith('"""') and not line.strip().startswith("'''"):
                        if 'OLD_BUILD_LABELS' in line or 'Phase' in line or '—' in line:
                            continue
                        return _fail(f'{rel}:{line_no} still hardcodes {label!r}')
        for line_no, line in enumerate(src.splitlines(), start=1):
            if assertion_pattern.search(line) and 'OLD_BUILD_LABELS' not in line:
                return _fail(f'{rel}:{line_no} has hardcoded build assertion: {line.strip()!r}')
    return 0


def main() -> int:
    tests = (
        test_build_info_matches_runtime,
        test_health_uses_canonical_build,
        test_help_uses_canonical_build,
        test_smoke_scripts_avoid_hardcoded_old_labels,
        test_qa_smoke_expected_build,
    )
    for test in tests:
        err = test()
        if err:
            return err
    print('DYNAMIC_BUILD_LABEL_52N_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
