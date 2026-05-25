"""Token reduction utilities — shrink prompts before expensive model calls."""

import re

DEFAULT_MAX_SECTION_CHARS = 3500
DEFAULT_MAX_PROMPT_CHARS = 28000


def estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 chars per token for English)."""
    if not text:
        return 0
    return max(1, len(text) // 4)


def truncate_text(text: str, max_chars: int, suffix: str = '\n...[truncated]') -> str:
    if not text or len(text) <= max_chars:
        return text or ''
    return text[: max_chars - len(suffix)] + suffix


def dedupe_lines(text: str) -> str:
    seen = set()
    out = []
    for line in text.splitlines():
        key = line.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(line)
    return '\n'.join(out)


def compress_section(text: str, max_chars: int = DEFAULT_MAX_SECTION_CHARS) -> str:
    if not text:
        return ''
    text = dedupe_lines(text)
    return truncate_text(text, max_chars)


def extract_symbols(text: str) -> set:
    return set(re.findall(r'\b[A-Z]{2,12}\b', text or ''))


def cap_prompt(prompt: str, max_chars: int = DEFAULT_MAX_PROMPT_CHARS) -> str:
    if len(prompt) <= max_chars:
        return prompt
    print(f"[COMPRESSOR] Prompt capped {len(prompt)} -> {max_chars} chars")
    head = prompt[: int(max_chars * 0.85)]
    tail = prompt[- int(max_chars * 0.1) :]
    return head + '\n\n...[middle truncated for token budget]...\n\n' + tail


def build_sections_blob(sections: dict, max_per_section: int = DEFAULT_MAX_SECTION_CHARS) -> str:
    parts = []
    for name, body in sections.items():
        if not body:
            continue
        compressed = compress_section(str(body), max_per_section)
        parts.append(f"=== {name.upper()} ===\n{compressed}")
    return '\n\n'.join(parts)


def adaptive_section_limit(base_limit: int, importance: float) -> int:
    """Scale section char limit by signal importance (0–1)."""
    importance = max(0.0, min(1.0, importance))
    return int(base_limit * (1.0 + importance * 0.6))
