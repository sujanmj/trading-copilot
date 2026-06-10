#!/usr/bin/env python3
"""Stage 50E — Railway OCR fallback path available when tesseract missing."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'MYFEED_OCR_RAILWAY_FALLBACK_AVAILABLE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    vision_path = PROJECT_ROOT / 'backend/my_feed/vision_ocr_fallback.py'
    if not vision_path.is_file():
        return _fail('vision_ocr_fallback.py must exist')

    extraction_src = (PROJECT_ROOT / 'backend/my_feed/image_extraction.py').read_text(encoding='utf-8')
    intake_src = (PROJECT_ROOT / 'backend/telegram/my_feed_intake.py').read_text(encoding='utf-8')
    if 'is_vision_ocr_fallback_available' not in extraction_src:
        return _fail('image_extraction must expose is_vision_ocr_fallback_available')
    if 'ocr_unavailable' not in extraction_src:
        return _fail('image_extraction must return ocr_unavailable when no OCR paths exist')
    if 'extract_market_text_from_image_temp' not in intake_src:
        return _fail('Telegram photo intake must call extract_market_text_from_image_temp')

    from backend.my_feed import image_extraction, vision_ocr_fallback

    fake_image = MagicMock()
    with patch.object(vision_ocr_fallback, 'extract_text', return_value='INDmoney: CHAMBLFERT surges 5.3% today'):
        text = vision_ocr_fallback.extract_text(fake_image)
    if 'CHAMBLFERT' not in text:
        return _fail('vision fallback must return extracted market text')

    temp_path = ''
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix='.png') as tmp:
            tmp.write(b'\x89PNG\r\n')
            temp_path = tmp.name

        with patch('backend.my_feed.image_extraction.is_local_tesseract_available', return_value=False):
            with patch('backend.my_feed.image_extraction.is_vision_ocr_fallback_available', return_value=True):
                with patch('backend.my_feed.image_extraction._ocr_image', return_value=('INDmoney: CHAMBLFERT surges 5.3%', 0.75)):
                    pil_mod = MagicMock()
                    pil_mod.Image.open.return_value = fake_image
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
    finally:
        if temp_path:
            try:
                os.remove(temp_path)
            except OSError:
                pass

    vision_src = vision_path.read_text(encoding='utf-8')
    if 'generativelanguage.googleapis.com' not in vision_src:
        return _fail('vision fallback must use safe in-memory vision request path')

    print('MYFEED_OCR_RAILWAY_FALLBACK_AVAILABLE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
