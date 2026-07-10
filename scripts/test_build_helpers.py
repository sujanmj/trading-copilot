#!/usr/bin/env python3
"""Shared helpers for build-label assertions in test scripts."""

from __future__ import annotations

from typing import Callable


def expected_build_label() -> str:
    from backend.config.build_info import TELEGRAM_BUILD

    return TELEGRAM_BUILD


def current_build_stage() -> str:
    from backend.config.build_info import BUILD_STAGE

    return BUILD_STAGE


def expected_help_build_line() -> str:
    return f'Build: {expected_build_label()}'


def expected_health_build_line() -> str:
    return f'Telegram build: <code>{expected_build_label()}</code>'


def assert_current_build_in_text(text: str) -> str | None:
    label = expected_build_label()
    if label not in str(text or ''):
        return f'expected {label!r} in text'
    return None


def assert_canonical_build(fail_fn: Callable[[str], int]) -> int:
    """Verify runtime re-exports match canonical build_info."""
    from backend.config import build_info
    from backend.config.local_safe_mode import (
        ASTRAEDGE_BUILD_STAGE,
        ASTRAEDGE_TELEGRAM_BUILD,
        get_astraedge_build_stage,
    )

    if ASTRAEDGE_TELEGRAM_BUILD != build_info.TELEGRAM_BUILD:
        return fail_fn(
            f'runtime TELEGRAM_BUILD mismatch: {ASTRAEDGE_TELEGRAM_BUILD!r} '
            f'!= {build_info.TELEGRAM_BUILD!r}'
        )
    if ASTRAEDGE_BUILD_STAGE != build_info.BUILD_STAGE:
        return fail_fn(
            f'runtime BUILD_STAGE mismatch: {ASTRAEDGE_BUILD_STAGE!r} '
            f'!= {build_info.BUILD_STAGE!r}'
        )
    if get_astraedge_build_stage() != build_info.BUILD_STAGE:
        return fail_fn(
            f'get_astraedge_build_stage mismatch: {get_astraedge_build_stage()!r} '
            f'!= {build_info.BUILD_STAGE!r}'
        )
    if ASTRAEDGE_TELEGRAM_BUILD != f'{build_info.PRODUCT_NAME} {build_info.BUILD_STAGE}':
        return fail_fn(
            f'build label format mismatch: {ASTRAEDGE_TELEGRAM_BUILD!r}'
        )
    return 0
