#!/usr/bin/env python3
"""Stage 50F — Groq vision fallback invoked when local OCR is weak."""

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
    print(f'MYFEED_GROQ_VISION_FALLBACK_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.my_feed import groq_vision_fallback, image_extraction

    if not hasattr(groq_vision_fallback, 'extract_market_items'):
        return _fail('groq_vision_fallback.extract_market_items missing')

    vision_called = {'count': 0}

    def _fake_vision(_image):
        vision_called['count'] += 1
        return {
            'ok': True,
            'items': [{
                'raw_market_text': 'INDmoney: CHAMBLFERT surges 5.3%',
                'cleaned_summary': 'INDmoney: CHAMBLFERT surges 5.3%',
                'detected_source_app': 'INDmoney',
                'tickers': ['CHAMBLFERT'],
                'entities': ['CHAMBLFERT'],
                'themes': [],
                'event_type': 'news',
                'sentiment': 'bullish',
                'impact_score': 72,
                'urgency': 'high',
                'suggested_action': 'WATCH FOR CONFIRMATION',
                'confirmation_required': True,
            }],
            'ignored_private_items': 0,
            'confidence': 0.91,
            'needs_text': False,
        }

    temp_path = ''
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix='.png') as tmp:
            tmp.write(b'\x89PNG\r\n')
            temp_path = tmp.name

        fake_image = type('Img', (), {'mode': 'RGB', 'size': (900, 1600)})()
        pil_mod = type(sys)('PIL')
        pil_mod.Image = type('Image', (), {'open': staticmethod(lambda _p: fake_image)})

        with patch('backend.my_feed.image_extraction.is_local_tesseract_available', return_value=True):
            with patch('backend.my_feed.image_extraction._ocr_image', return_value=('', 0.0)):
                with patch('backend.my_feed.image_extraction._preprocess_image', return_value=fake_image):
                    with patch('backend.my_feed.image_extraction._optional_vision_structured', side_effect=_fake_vision):
                        with patch.dict(sys.modules, {'PIL': pil_mod}):
                            result = image_extraction.extract_market_text_from_image_temp(temp_path)

        if vision_called['count'] < 1:
            return _fail('local OCR weak path must invoke Groq vision fallback')
        if not result.get('ok') or not result.get('vision_items'):
            return _fail(f'vision fallback must produce vision_items, got {result!r}')

        with patch.object(groq_vision_fallback, 'is_groq_vision_available', return_value=False):
            if groq_vision_fallback.extract_market_items(object()).get('ok'):
                return _fail('without Groq key vision must not succeed')
    finally:
        if temp_path:
            try:
                os.remove(temp_path)
            except OSError:
                pass

    print('MYFEED_GROQ_VISION_FALLBACK_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
