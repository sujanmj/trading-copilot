"""
Temporary screenshot OCR for My Feed (Stage 50A).

Images are written to a temp file, OCR'd, then deleted immediately.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any


def extract_text_from_image_bytes(image_bytes: bytes, *, suffix: str = '.png') -> dict[str, Any]:
    if not image_bytes:
        return {'ok': False, 'text': '', 'confidence': 0.0, 'error': 'empty_image'}

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(image_bytes)
            temp_path = Path(tmp.name)

        try:
            from PIL import Image  # type: ignore
        except ImportError:
            return {'ok': False, 'text': '', 'confidence': 0.0, 'error': 'pil_unavailable'}

        try:
            import pytesseract  # type: ignore
        except ImportError:
            return {'ok': False, 'text': '', 'confidence': 0.0, 'error': 'tesseract_unavailable'}

        image = Image.open(temp_path)
        text = str(pytesseract.image_to_string(image) or '').strip()
        confidence = 0.85 if len(text) >= 40 else 0.45 if len(text) >= 12 else 0.2
        ok = confidence >= 0.45 and len(text) >= 12
        return {'ok': ok, 'text': text, 'confidence': confidence, 'error': '' if ok else 'low_confidence'}
    except Exception as exc:
        return {'ok': False, 'text': '', 'confidence': 0.0, 'error': str(exc)[:120]}
    finally:
        if temp_path is not None:
            try:
                os.remove(temp_path)
            except OSError:
                pass
