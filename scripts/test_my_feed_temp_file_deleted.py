#!/usr/bin/env python3
"""Unit tests — screenshot OCR temp file deleted (Stage 50A)."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'MY_FEED_TEMP_FILE_DELETED_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.my_feed import screenshot_ocr

    temp_name = str(PROJECT_ROOT / 'data' / '__ocr_temp_test__.png')
    removed_paths: list[str] = []

    class _FakeTmp:
        def __init__(self, *args, **kwargs):
            self.name = temp_name

        def write(self, _data):
            Path(self.name).write_bytes(b'fake')

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    fake_image_mod = types.ModuleType('PIL.Image')
    fake_image_mod.open = MagicMock(return_value=MagicMock())
    fake_pil = types.ModuleType('PIL')
    fake_pil.Image = fake_image_mod
    fake_tess = types.ModuleType('pytesseract')
    fake_tess.image_to_string = MagicMock(
        return_value='NIFTY opens higher on strong global cues across sectors',
    )

    with patch.object(screenshot_ocr.tempfile, 'NamedTemporaryFile', _FakeTmp):
        with patch.object(screenshot_ocr.os, 'remove', side_effect=lambda p: removed_paths.append(str(p))):
            with patch.dict(sys.modules, {'PIL': fake_pil, 'PIL.Image': fake_image_mod, 'pytesseract': fake_tess}):
                result = screenshot_ocr.extract_text_from_image_bytes(b'\x89PNG')

    if not result.get('ok'):
        return _fail(f'expected OCR ok got {result!r}')
    if temp_name not in removed_paths:
        return _fail(f'temp file must be removed after OCR, removed={removed_paths!r}')

    print('MY_FEED_TEMP_FILE_DELETED_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
