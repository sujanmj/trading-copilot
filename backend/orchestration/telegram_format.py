"""Shared professional Telegram formatting helpers."""

from __future__ import annotations


def section(title: str, body: str) -> str:
    title = str(title or '').strip()
    body = str(body or '').strip()
    if not body:
        return ''
    return f"<b>{title}</b>\n{body}"


def signal_block(*, signal: str, risk: str, confidence: str, context: str) -> str:
    parts = [
        section('Signal', signal),
        section('Risk', risk),
        section('Confidence', confidence),
        section('Context', context),
    ]
    return '\n\n'.join(p for p in parts if p)


def professional_phrase(raw: str) -> str:
    mapping = {
        'Immediate attention required': 'High market impact detected',
        'IMMEDIATE ATTENTION REQUIRED': 'High market impact detected',
        'cache_miss': 'Context refresh',
        'truncation': 'Compression active',
        'low_novelty': 'Signal repetition detected',
    }
    out = str(raw or '')
    for old, new in mapping.items():
        out = out.replace(old, new)
    return out
