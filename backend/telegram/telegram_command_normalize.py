"""
Telegram command normalization — slashless aliases, typo fixes, suggestions (Stage 48J).
"""

from __future__ import annotations

THEME_RESERVED_WORDS = frozenset({
    'overview', 'list', 'search', 'category', 'news', 'scan', 'budget', 'refresh',
})

AIHUB_TAB_TYPO_ALIASES: dict[str, str] = {
    'callib': 'calib',
    'calibb': 'calib',
    'calibration': 'calib',
    'calibrate': 'calib',
    'journals': 'journal',
    'markets': 'market',
}

_COMMAND_SUGGESTIONS: dict[str, str] = {
    'action': '/action plan',
    'aihun': '/aihub',
    'aihubb': '/aihub',
    'callib': '/aihub calib',
    'calibrate': '/aihub calib',
    'calibration': '/aihub calib',
    'calibb': '/aihub calib',
    'theme': '/theme',
    'budget': '/budget',
    'helpp': '/help',
    'stat': '/status',
    'premarket': '/premarket',
}

_ARGS_SUGGESTIONS: dict[tuple[str, str], str] = {
    ('theme', 'overview'): '/theme',
    ('theme', 'search'): '/theme search <keyword>',
    ('theme', 'category'): '/theme category <name>',
    ('budget', 'overview'): '/budget',
    ('budget', 'theme'): '/budget theme <basket>',
    ('budget', 'analyze'): '/budget analyze <text>',
}


def normalize_parsed_command(cmd: str, args: str) -> tuple[str, str]:
    """Normalize cmd/args after parse_command — safe slashless + action alias."""
    cmd_norm = str(cmd or '').strip().lower()
    args_norm = str(args or '').strip()
    if cmd_norm == 'action' and (not args_norm or args_norm.lower() == 'plan'):
        return 'action', 'plan'
    return cmd_norm, args_norm


def normalize_aihub_tab(tab: str) -> str:
    """Map typo aliases to canonical AIHub tab names before dispatch."""
    key = str(tab or '').strip().lower()
    if not key:
        return ''
    if key in ('full', 'all', 'brain full'):
        return key
    return AIHUB_TAB_TYPO_ALIASES.get(key, key)


def suggest_command(cmd: str, args: str = '') -> str | None:
    """Return a friendly Did you mean suggestion, or None."""
    cmd_key = str(cmd or '').strip().lower()
    args_key = str(args or '').strip().lower()
    if (cmd_key, args_key) in _ARGS_SUGGESTIONS:
        return _ARGS_SUGGESTIONS[(cmd_key, args_key)]
    if cmd_key in _COMMAND_SUGGESTIONS:
        return _COMMAND_SUGGESTIONS[cmd_key]
    if args_key in AIHUB_TAB_TYPO_ALIASES:
        return f'/aihub {AIHUB_TAB_TYPO_ALIASES[args_key]}'
    return None


def format_unknown_command_response(cmd: str, args: str = '') -> str:
    """Unknown command with optional Did you mean line."""
    cmd_disp = str(cmd or '').strip().lower() or '—'
    lines = [f'Unknown command: <code>{cmd_disp}</code>']
    suggestion = suggest_command(cmd, args)
    if suggestion:
        lines.append(f'Did you mean {suggestion}?')
    else:
        lines.append('Type /help for allowed commands.')
    return '\n'.join(lines)


def format_unknown_aihub_tab(tab: str) -> str:
    """Friendly AIHub unknown tab — menu + examples, not harsh unknown."""
    from backend.telegram.response_format import format_aihub_menu

    key = str(tab or '').strip().lower() or '—'
    return (
        f'Unknown AI Hub tab: <code>{key}</code>\n'
        f'{format_aihub_menu()}\n'
        'Examples: /aihub scan · /aihub market · /aihub calib'
    )


def format_theme_search_usage() -> str:
    return (
        '<b>Theme search</b>\n'
        'Use <code>/theme search bank</code>\n'
        'Use <code>/theme search rail</code>\n'
        'Use <code>/theme search defence</code>'
    )


def format_theme_category_usage() -> str:
    from backend.analytics.theme_baskets import THEME_CATEGORIES

    cats = ', '.join(sorted(THEME_CATEGORIES.keys()))
    return (
        '<b>Theme categories</b>\n'
        f'Available: {cats}\n'
        'Use <code>/theme category transport</code> or <code>/theme category finance</code>.'
    )


def format_budget_theme_usage() -> str:
    return (
        '<b>Budget theme</b>\n'
        'Use <code>/budget theme &lt;basket&gt;</code>\n'
        'Example: <code>/budget theme infra</code>'
    )


def format_budget_analyze_usage() -> str:
    return (
        '<b>Budget analyze</b>\n'
        'Use <code>/budget analyze &lt;text&gt;</code>\n'
        'Example: <code>/budget analyze FM capex push for railways</code>'
    )
