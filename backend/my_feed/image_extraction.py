"""
Shared My Feed image → market text extraction (Stage 50D).

Temp files only; never persists images. No hallucination on OCR failure.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from backend.my_feed.text_extractor import filter_market_text, split_market_notifications

_MIN_OCR_CHARS = 12
_MIN_WIDTH_UPSCALE = 800
_UPSCALE_TARGET_WIDTH = 1200


def _optional_vision_ocr_fallback(image: Any) -> str:
    """Optional vision OCR when local tesseract is weak; never exposes provider names."""
    try:
        from backend.my_feed import vision_ocr_fallback  # type: ignore

        return str(vision_ocr_fallback.extract_text(image) or '').strip()
    except (ImportError, AttributeError, Exception):
        return ''


def _preprocess_image(image: Any) -> Any:
    from PIL import ImageEnhance, ImageOps  # type: ignore

    image = ImageOps.exif_transpose(image)
    if getattr(image, 'mode', '') not in ('RGB', 'L'):
        image = image.convert('RGB')

    width, height = image.size
    if width < _MIN_WIDTH_UPSCALE and width > 0:
        scale = _UPSCALE_TARGET_WIDTH / float(width)
        image = image.resize((int(width * scale), int(height * scale)))

    # Trim typical phone status/navigation bars before OCR.
    trim_top = max(0, int(height * 0.04))
    trim_bottom = max(0, int(height * 0.03))
    if trim_top or trim_bottom:
        crop_bottom = height - trim_bottom if trim_bottom else height
        if crop_bottom > trim_top + 40:
            image = image.crop((0, trim_top, width, crop_bottom))

    image = ImageEnhance.Contrast(image).enhance(1.35)
    image = ImageEnhance.Sharpness(image).enhance(1.45)
    return image


def _run_tesseract(image: Any) -> str:
    import pytesseract  # type: ignore

    return str(pytesseract.image_to_string(image) or '').strip()


def is_local_tesseract_available() -> bool:
    try:
        import pytesseract  # type: ignore  # noqa: F401

        return True
    except ImportError:
        return False


def is_vision_ocr_fallback_available() -> bool:
    try:
        from backend.my_feed import vision_ocr_fallback

        return bool(vision_ocr_fallback.is_vision_ocr_fallback_available())
    except (ImportError, AttributeError, Exception):
        return False


def _ocr_image(image: Any, *, tesseract_available: bool = True) -> tuple[str, float]:
    processed = _preprocess_image(image)
    raw_text = _run_tesseract(processed) if tesseract_available else ''
    confidence = 0.85 if len(raw_text) >= 40 else 0.55
    if len(raw_text) < _MIN_OCR_CHARS:
        fallback = _optional_vision_ocr_fallback(processed)
        if len(fallback) >= _MIN_OCR_CHARS:
            return fallback, 0.75
    if not tesseract_available and len(raw_text) < _MIN_OCR_CHARS:
        return raw_text, 0.0
    return raw_text, confidence


def _build_result(raw_text: str, *, confidence: float, error: str = '') -> dict[str, Any]:
    split = split_market_notifications(raw_text)
    notifications = list(split.get('notifications') or [])
    ignored_private_count = int(split.get('ignored_private_count') or 0)
    combined = str(split.get('combined') or '').strip()
    extracted = filter_market_text(combined or raw_text)

    if not notifications and not combined:
        return {
            'ok': False,
            'text': raw_text,
            'notifications': [],
            'ignored_private_count': ignored_private_count,
            'needs_text': True,
            'cleaned_summary': '',
            'confidence': confidence,
            'extracted': extracted,
            'error': error or 'no_market_lines',
        }

    return {
        'ok': True,
        'text': combined or raw_text,
        'notifications': notifications,
        'ignored_private_count': ignored_private_count,
        'needs_text': False,
        'cleaned_summary': combined,
        'confidence': confidence,
        'extracted': extracted,
        'error': '',
    }


def extract_market_text_from_image_temp(image_path: str | Path) -> dict[str, Any]:
    path = Path(image_path)
    if not path.is_file():
        return {
            'ok': False,
            'text': '',
            'notifications': [],
            'ignored_private_count': 0,
            'needs_text': True,
            'error': 'missing_file',
            'extracted': {},
        }

    tesseract_available = is_local_tesseract_available()
    vision_available = is_vision_ocr_fallback_available()
    if not tesseract_available and not vision_available:
        return {
            'ok': False,
            'text': '',
            'notifications': [],
            'ignored_private_count': 0,
            'needs_text': True,
            'error': 'ocr_unavailable',
            'extracted': {},
        }

    try:
        from PIL import Image  # type: ignore
    except ImportError:
        return {
            'ok': False,
            'text': '',
            'notifications': [],
            'ignored_private_count': 0,
            'needs_text': True,
            'error': 'pil_unavailable',
            'extracted': {},
        }

    try:
        image = Image.open(path)
        raw_text, confidence = _ocr_image(image, tesseract_available=tesseract_available)
    except Exception as exc:
        return {
            'ok': False,
            'text': '',
            'notifications': [],
            'ignored_private_count': 0,
            'needs_text': True,
            'error': str(exc)[:120],
            'extracted': {},
        }

    if len(raw_text) < _MIN_OCR_CHARS:
        return {
            'ok': False,
            'text': raw_text,
            'notifications': [],
            'ignored_private_count': 0,
            'needs_text': True,
            'error': 'low_confidence',
            'extracted': {},
        }

    return _build_result(raw_text, confidence=confidence)


def extract_market_text_from_image_bytes(image_bytes: bytes, *, suffix: str = '.png') -> dict[str, Any]:
    import tempfile

    if not image_bytes:
        return {
            'ok': False,
            'text': '',
            'notifications': [],
            'ignored_private_count': 0,
            'needs_text': True,
            'error': 'empty_image',
            'extracted': {},
        }

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(image_bytes)
            temp_path = Path(tmp.name)
        return extract_market_text_from_image_temp(temp_path)
    finally:
        if temp_path is not None:
            try:
                os.remove(temp_path)
            except OSError:
                pass
