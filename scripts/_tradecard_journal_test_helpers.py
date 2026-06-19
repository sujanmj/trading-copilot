"""Shared helpers for Stage 50Z tradecard journal tests."""

from __future__ import annotations

import json
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch


@contextmanager
def isolated_tradecard_journal():
    tmp = tempfile.mkdtemp()
    journal = Path(tmp) / 'tradecard_journal.jsonl'
    with patch('backend.trading.tradecard_journal.JOURNAL_FILE', journal):
        yield journal


@contextmanager
def isolated_tradecard_latest():
    tmp = tempfile.mkdtemp()
    latest = Path(tmp) / 'tradecard_latest_by_chat.json'
    with patch('backend.trading.tradecard_latest.LATEST_FILE', latest):
        yield latest


@contextmanager
def isolated_tradecard_path_samples():
    tmp = tempfile.mkdtemp()
    samples = Path(tmp) / 'tradecard_path_samples.jsonl'
    with patch('backend.trading.tradecard_journal.PATH_SAMPLES_FILE', samples):
        yield samples


@contextmanager
def isolated_tradecard_store():
    """Isolate journal + path samples together."""
    tmp = tempfile.mkdtemp()
    journal = Path(tmp) / 'tradecard_journal.jsonl'
    samples = Path(tmp) / 'tradecard_path_samples.jsonl'
    with patch('backend.trading.tradecard_journal.JOURNAL_FILE', journal), \
         patch('backend.trading.tradecard_journal.PATH_SAMPLES_FILE', samples):
        yield journal, samples


def sample_valid_card(**overrides):
    card = {
        'generated_at': '2026-06-19T10:00:00+05:30',
        'session_date': '2026-06-19',
        'ticker': 'NILKAMAL',
        'status': 'VALID_ENTRY',
        'current_price': 1345.0,
        'entry_zone': '1342.31–1349.03',
        'stop_loss': 1336.93,
        'target_1': 1358.45,
        'target_2': 1367.19,
        'confidence': 'MEDIUM',
        'reason': 'paper watch entry',
        'source_label': 'Source: scanner-confirmed',
    }
    card.update(overrides)
    return card


def sample_sutlejtex_card(**overrides):
    card = {
        'generated_at': '2026-06-19T10:15:00+05:30',
        'session_date': '2026-06-19',
        'ticker': 'SUTLEJTEX',
        'status': 'VALID_ENTRY',
        'current_price': 52.0,
        'entry_zone': '51.50–52.50',
        'stop_loss': 50.0,
        'target_1': 54.0,
        'target_2': 56.0,
        'confidence': 'MEDIUM',
        'reason': 'paper watch entry',
        'source_label': 'Source: scanner-confirmed',
    }
    card.update(overrides)
    return card


def nilkamal_levels() -> tuple[float, float, float, float, float]:
    card = sample_valid_card()
    from backend.trading.tradecard_journal import parse_entry_bounds

    entry_low, entry_high = parse_entry_bounds(card['entry_zone'])
    return entry_low, entry_high, float(card['stop_loss']), float(card['target_1']), float(card['target_2'])


def sutlejtex_levels() -> tuple[float, float, float, float, float]:
    card = sample_sutlejtex_card()
    from backend.trading.tradecard_journal import parse_entry_bounds

    entry_low, entry_high = parse_entry_bounds(card['entry_zone'])
    return entry_low, entry_high, float(card['stop_loss']), float(card['target_1']), float(card['target_2'])
