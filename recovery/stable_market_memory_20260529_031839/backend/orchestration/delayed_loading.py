"""
Delayed loading messages — only show "Processing…" if operation exceeds 3 seconds.
"""

from __future__ import annotations

import threading
from typing import Callable, Optional

LOADING_DELAY_SEC = 3.0


def run_with_delayed_loading(
    *,
    send_fn: Callable[..., bool],
    loading_text: str,
    command: str,
    cycle_id: str = '',
    work_fn: Callable[[], None],
) -> None:
    """
    Run work_fn; send loading_text only if still running after LOADING_DELAY_SEC.
    send_fn signature: (text, command=..., cycle_id=..., message_kind='loading')
    """
    sent = {'done': False}
    timer_ref = {'timer': None}

    def _send_loading():
        if sent['done']:
            return
        try:
            send_fn(
                loading_text,
                command=command,
                cycle_id=cycle_id,
                message_kind='loading',
            )
        except TypeError:
            send_fn(loading_text)

    timer = threading.Timer(LOADING_DELAY_SEC, _send_loading)
    timer_ref['timer'] = timer
    timer.daemon = True
    timer.start()
    try:
        work_fn()
    finally:
        sent['done'] = True
        t = timer_ref.get('timer')
        if t:
            t.cancel()
