#!/usr/bin/env python3
"""Stage 50F — Railway OCR fallback uses Groq vision when tesseract missing."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'MYFEED_OCR_RAILWAY_FALLBACK_AVAILABLE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    vision_path = PROJECT_ROOT / 'backend/my_feed/groq_vision_fallback.py'
    if not vision_path.is_file():
        return _fail('groq_vision_fallback.py must exist')

    extraction_src = (PROJECT_ROOT / 'backend/my_feed/image_extraction.py').read_text(encoding='utf-8')
    if 'groq_vision_fallback' not in extraction_src:
        return _fail('image_extraction must use groq_vision_fallback')

    from backend.my_feed import groq_vision_fallback, image_extraction

    temp_path = ''
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix='.png') as tmp:
            tmp.write(b'\x89PNG\r\n')
            temp_path = tmp.name

        fake_image = object()
        pil_mod = type(sys)('PIL')
        pil_mod.Image = type('Image', (), {'open': staticmethod(lambda _p: fake_image)})

        with patch('backend.my_feed.image_extraction.is_local_tesseract_available', return_value=False):
            with patch('backend.my_feed.image_extraction.is_vision_ocr_fallback_available', return_value=True):
                with patch('backend.my_feed.image_extraction._ocr_image', return_value=('INDmoney: CHAMBLFERT surges 5.3%', 0.75)):
                    with patch.dict(sys.modules, {'PIL': pil_mod}):
                        result = image_extraction.extract_market_text_from_image_temp(temp_path)

        if not result.get('ok'):
            return _fail(f'vision-backed extraction should succeed, got {result!r}')
        if 'CHAMBLFERT' not in str(result.get('text') or ''):
            return _fail('vision-backed extraction must preserve CHAMBLFERT')

        with patch('backend.my_feed.image_extraction.is_local_tesseract_available', return_value=False):
            with patch('backend.my_feed.image_extraction.is_vision_ocr_fallback_available', return_value=False):
                blocked = image_extraction.extract_market_text_from_image_temp(temp_path)
        if not blocked.get('needs_text') or blocked.get('error') != 'ocr_unavailable':
            return _fail(f'expected ocr_unavailable needs_text, got {blocked!r}')

        with patch.object(groq_vision_fallback, 'is_groq_vision_available', return_value=False):
            empty = groq_vision_fallback.extract_market_items(fake_image)
        if empty.get('ok'):
            return _fail('without Groq key vision must not succeed')
    finally:
        if temp_path:
            try:
                os.remove(temp_path)
            except OSError:
                pass

    print('MYFEED_OCR_RAILWAY_FALLBACK_AVAILABLE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
