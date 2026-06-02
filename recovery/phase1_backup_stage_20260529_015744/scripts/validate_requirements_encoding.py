#!/usr/bin/env python3
"""
Validate requirements.txt encoding and pip-parseable package lines.

Prevents Windows UTF-16 / null-byte corruption from breaking Railway deploys.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS = ROOT / "requirements.txt"

PACKAGE_LINE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._\-]*"
    r"(?:\[[^\]]+\])?"
    r"(?:==|>=|<=|~=|!=|>|<)?"
    r".*$"
)


def detect_encoding(raw: bytes) -> str:
    if raw.startswith(b"\xff\xfe"):
        return "UTF-16 LE (BOM)"
    if raw.startswith(b"\xfe\xff"):
        return "UTF-16 BE (BOM)"
    if raw.startswith(b"\xef\xbb\xbf"):
        return "UTF-8 (BOM)"
    if b"\x00" in raw:
        return "UTF-16 LE (no BOM, null-byte interleave)"
    try:
        raw.decode("utf-8")
        return "UTF-8"
    except UnicodeDecodeError:
        return "unknown / non-UTF-8"


def validate(path: Path = REQUIREMENTS) -> int:
    if not path.exists():
        print(f"ERROR: missing {path}")
        return 1

    raw = path.read_bytes()
    encoding = detect_encoding(raw)
    null_count = raw.count(b"\x00")

    print(f"file: {path}")
    print(f"encoding_detected: {encoding}")
    print(f"size_bytes: {len(raw)}")
    print(f"null_byte_count: {null_count}")

    errors: list[str] = []

    if null_count:
        errors.append(f"null bytes present ({null_count})")

    if encoding != "UTF-8":
        errors.append(f"expected UTF-8 plain text, got {encoding}")

    if raw.startswith(b"\xef\xbb\xbf"):
        errors.append("UTF-8 BOM present (prefer BOM-free UTF-8)")

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        errors.append(f"UTF-8 decode failed: {exc}")
        text = ""

    if text and "\r\n" in text:
        print("note: CRLF line endings detected (LF preferred but acceptable)")

    package_lines = 0
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        package_lines += 1
        if "\x00" in stripped:
            errors.append(f"line {lineno}: contains null character")
        if not PACKAGE_LINE.match(stripped):
            errors.append(f"line {lineno}: malformed package line: {stripped!r}")

    print(f"package_lines: {package_lines}")

    if errors:
        print("RESULT: FAIL")
        for err in errors:
            print(f"  - {err}")
        return 1

    print("RESULT: OK — UTF-8, no null bytes, package lines look valid")
    return 0


if __name__ == "__main__":
    sys.exit(validate())
