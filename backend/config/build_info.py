"""
Canonical AstraEdge build/version metadata — single source of truth.

Runtime display, /health, /status, help text, and tests should read from here
(or from local_safe_mode re-exports) instead of hardcoding build labels.
"""

from __future__ import annotations

PRODUCT_NAME = 'AstraEdge'
BUILD_STAGE = '52P'
TELEGRAM_BUILD = f'{PRODUCT_NAME} {BUILD_STAGE}'
RELEASE_CHANNEL = 'production'
BUILD_DISPLAY = TELEGRAM_BUILD


def get_build_stage() -> str:
    """Short deployment stage id shared by /status, build-info, and smoke checks."""
    return BUILD_STAGE
