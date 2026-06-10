#!/usr/bin/env python3
"""Unit tests — My Feed OCR phone screenshot preprocessing (Stage 50D)."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'MYFEED_OCR_PREPROCESS_PHONE_SCREENSHOT_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.my_feed import image_extraction

    src = (PROJECT_ROOT / 'backend/my_feed/image_extraction.py').read_text(encoding='utf-8')
    for token in ('exif_transpose', 'ImageEnhance', 'ImageOps', '_preprocess_image', '_UPSCALE_TARGET_WIDTH'):
        if token not in src:
            return _fail(f'image_extraction missing preprocessing hook {token!r}')

    fake_image = MagicMock()
    fake_image.mode = 'RGBA'
    fake_image.size = (360, 780)
    fake_image.convert.return_value = fake_image
    fake_image.resize.return_value = fake_image
    fake_image.crop.return_value = fake_image

    fake_enhance = MagicMock()
    fake_enhance.enhance.return_value = fake_image
    fake_image_mod = types.ModuleType('PIL.Image')
    fake_image_mod.open = MagicMock(return_value=fake_image)
    fake_image_ops = types.ModuleType('PIL.ImageOps')
    fake_image_ops.exif_transpose = MagicMock(return_value=fake_image)
    fake_image_enhance = types.ModuleType('PIL.ImageEnhance')
    fake_image_enhance.Contrast = MagicMock(return_value=fake_enhance)
    fake_image_enhance.Sharpness = MagicMock(return_value=fake_enhance)
    fake_pil = types.ModuleType('PIL')
    fake_pil.Image = fake_image_mod
    fake_pil.ImageOps = fake_image_ops
    fake_pil.ImageEnhance = fake_image_enhance
    fake_tess = types.ModuleType('pytesseract')
    fake_tess.image_to_string = MagicMock(
        return_value='NIFTY futures rise on strong FII inflows across banking sector today',
    )

    with patch.dict(sys.modules, {
        'PIL': fake_pil,
        'PIL.Image': fake_image_mod,
        'PIL.ImageOps': fake_image_ops,
        'PIL.ImageEnhance': fake_image_enhance,
        'pytesseract': fake_tess,
    }):
        processed = image_extraction._preprocess_image(fake_image)

    if processed is not fake_image:
        return _fail('preprocess must return processed image')
    fake_image_ops.exif_transpose.assert_called_once()
    fake_image.resize.assert_called()
    fake_image.crop.assert_called()

    print('MYFEED_OCR_PREPROCESS_PHONE_SCREENSHOT_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
