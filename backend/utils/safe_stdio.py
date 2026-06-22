"""Safe stdout/stderr helpers for smoke tests and background tasks.

Fallback order: sys.stderr/sys.stdout, sys.__stderr__/sys.__stdout__, os.devnull.
"""

from __future__ import annotations

import builtins
import os
import sys
import threading
import warnings
from typing import IO, Any

_DEVNULL_LOCK = threading.Lock()
_DEVNULL_STREAMS: dict[str, IO[str]] = {}
_FD_STREAMS: dict[str, IO[str]] = {}


def _normalized_name(name: str | None) -> str:
    return 'stderr' if name == 'stderr' else 'stdout'


def _devnull_stream(name: str) -> IO[str]:
    key = _normalized_name(name)
    with _DEVNULL_LOCK:
        stream = _DEVNULL_STREAMS.get(key)
        if stream is None or getattr(stream, 'closed', False):
            stream = open(os.devnull, 'w', encoding='utf-8', errors='replace')
            _DEVNULL_STREAMS[key] = stream
        return stream


class _FdTextStream:
    encoding = 'utf-8'
    errors = 'replace'
    closed = False

    def __init__(self, name: str) -> None:
        self.name = _normalized_name(name)
        self.fd = 2 if self.name == 'stderr' else 1

    def write(self, data: Any) -> int:
        text = str(data)
        os.write(self.fd, text.encode('utf-8', errors='replace'))
        return len(text)

    def flush(self) -> None:
        return None

    def isatty(self) -> bool:
        try:
            return os.isatty(self.fd)
        except Exception:
            return False

    def writable(self) -> bool:
        return True

    def fileno(self) -> int:
        return self.fd


def _fd_stream(name: str) -> IO[str]:
    key = _normalized_name(name)
    with _DEVNULL_LOCK:
        stream = _FD_STREAMS.get(key)
        if stream is None:
            stream = _FdTextStream(key)
            _FD_STREAMS[key] = stream
        return stream


def is_stream_usable(stream: Any) -> bool:
    """Return True when a text stream can accept writes without raising."""
    if stream is None:
        return False
    if getattr(stream, '_safe_stdio_proxy', False):
        return False
    if bool(getattr(stream, 'closed', False)):
        return False
    write = getattr(stream, 'write', None)
    if not callable(write):
        return False
    try:
        write('')
    except Exception:
        return False
    return True


def safe_stream(name: str = 'stdout', preferred: Any = None) -> IO[str]:
    """Return a writable stream, falling back to sys.__std*__ then os.devnull."""
    key = _normalized_name(name)
    if preferred is None and os.environ.get('SAFE_STDIO_FORCE_FD', '').strip().lower() in ('1', 'true', 'yes', 'on'):
        return _fd_stream(key)
    candidates = [
        preferred,
        getattr(sys, key, None),
        getattr(sys, f'__{key}__', None),
    ]
    seen: set[int] = set()
    for stream in candidates:
        if stream is None:
            continue
        stream_id = id(stream)
        if stream_id in seen:
            continue
        seen.add(stream_id)
        if is_stream_usable(stream):
            return stream
    return _devnull_stream(key)


class _NullBytesStream:
    closed = False

    def write(self, data: Any) -> int:
        try:
            return len(data)
        except Exception:
            return 0

    def flush(self) -> None:
        return None

    def close(self) -> None:
        return None

    def writable(self) -> bool:
        return True

    def fileno(self) -> int:
        return _devnull_stream('stdout').fileno()


class NullTextStream:
    """Text sink that stays writable even if held by late background writers."""

    encoding = 'utf-8'
    errors = 'replace'
    closed = False
    buffer = _NullBytesStream()

    def write(self, data: Any) -> int:
        text = str(data)
        return len(text)

    def flush(self) -> None:
        return None

    def close(self) -> None:
        return None

    def isatty(self) -> bool:
        return False

    def writable(self) -> bool:
        return True

    def fileno(self) -> int:
        return _devnull_stream('stdout').fileno()


_NULL_TEXT_STREAM = NullTextStream()


def safe_output_sink() -> NullTextStream:
    """Return a no-op stream that never becomes closed."""
    return _NULL_TEXT_STREAM


class SafeStreamProxy:
    """Logging stream that resolves stdout/stderr at write time."""

    _safe_stdio_proxy = True

    def __init__(self, name: str = 'stdout') -> None:
        self.name = _normalized_name(name)

    @property
    def encoding(self) -> str:
        return getattr(safe_stream(self.name), 'encoding', 'utf-8') or 'utf-8'

    @property
    def errors(self) -> str:
        return getattr(safe_stream(self.name), 'errors', 'replace') or 'replace'

    @property
    def closed(self) -> bool:
        return False

    def write(self, data: Any) -> int:
        text = str(data)
        try:
            return safe_stream(self.name).write(text)
        except Exception:
            try:
                return _devnull_stream(self.name).write(text)
            except Exception:
                return len(text)

    def flush(self) -> None:
        try:
            safe_stream(self.name).flush()
        except Exception:
            try:
                _devnull_stream(self.name).flush()
            except Exception:
                pass

    def isatty(self) -> bool:
        try:
            return bool(safe_stream(self.name).isatty())
        except Exception:
            return False

    def writable(self) -> bool:
        return True

    def fileno(self) -> int:
        try:
            return safe_stream(self.name).fileno()
        except Exception:
            return _devnull_stream(self.name).fileno()


def ensure_safe_standard_streams() -> None:
    """Replace closed sys.stdout/sys.stderr with writable fallbacks."""
    if not is_stream_usable(getattr(sys, 'stdout', None)):
        sys.stdout = safe_stream('stdout')
    if not is_stream_usable(getattr(sys, 'stderr', None)):
        sys.stderr = safe_stream('stderr')


def safe_print(*values: Any, file: Any = None, fallback: str = 'stdout', **kwargs: Any) -> bool:
    """Best-effort print that never raises for broken stdout/stderr."""
    target_name = _normalized_name(fallback)
    if file is not None:
        if file is getattr(sys, 'stderr', None) or file is getattr(sys, '__stderr__', None):
            target_name = 'stderr'
        elif file is getattr(sys, 'stdout', None) or file is getattr(sys, '__stdout__', None):
            target_name = 'stdout'
    target = safe_stream(target_name, preferred=file)
    try:
        builtins.print(*values, file=target, **kwargs)
        return True
    except UnicodeEncodeError:
        safe_values = [
            str(value).encode('ascii', errors='replace').decode('ascii')
            for value in values
        ]
        try:
            builtins.print(*safe_values, file=safe_stream(target_name), **kwargs)
            return True
        except Exception:
            return False
    except Exception:
        try:
            builtins.print(*values, file=_devnull_stream(target_name), **kwargs)
            return True
        except Exception:
            return False


def in_smoke_local_ci_mode() -> bool:
    return any(
        str(os.environ.get(key, '')).strip()
        for key in (
            'CI',
            'GITHUB_ACTIONS',
            'PYTEST_CURRENT_TEST',
            'RAILWAY_SMOKE_LOCAL',
            'LOCAL_DEV_MODE',
            'LOCAL_ONLY',
        )
    )


def disable_progress_output() -> None:
    """Disable common progress renderers that write to stderr."""
    os.environ.setdefault('TQDM_DISABLE', '1')
    os.environ.setdefault('RICH_NO_COLOR', '1')
    os.environ.setdefault('RICH_DISABLE', '1')
    os.environ.setdefault('NO_COLOR', '1')
    os.environ.setdefault('YFINANCE_PROGRESS', '0')


def ignore_google_generativeai_future_warning() -> None:
    warnings.filterwarnings(
        'ignore',
        category=FutureWarning,
        module=r'google\.generativeai(\..*)?$',
    )
    warnings.filterwarnings(
        'ignore',
        category=FutureWarning,
        message=r'.*google\.generativeai.*',
    )


def configure_smoke_stdio() -> None:
    """Apply stdio and progress safeguards for local smoke execution."""
    ensure_safe_standard_streams()
    if in_smoke_local_ci_mode():
        disable_progress_output()
    ignore_google_generativeai_future_warning()
