"""AstraEdge Telegram help — compact index, section help, and safe multi-part full help."""

from __future__ import annotations

from backend.config.build_info import TELEGRAM_BUILD

HELP_HEADER = '<b>🤖 AstraEdge Telegram</b>'

HELP_MAX_PART_CHARS = 3200

HELP_BLOCKS: dict[str, str] = {
    'core': """<b>Core:</b>
/status — system status
/health — runtime health
/clock — runtime UTC / IST clock
/schedule — premarket + brief schedule
/broker — broker intelligence
/missed — missed-entry opportunities logged today""",
    'qa': """<b>QA:</b>
/qa — QA help and status
/qa smoke — fast safe checks
/qa full — safe regression suite
/qa last — last QA result
/qa explain — what QA covers""",
    'trade_memory': """<b>Trade Memory:</b>
/memory — market memory dashboard
/memory stock SYMBOL — tradecard + Screener memory for symbol
/memory latest — latest tradecard memory records
/memory stats — tradecard memory counts""",
    'ai_status': """<b>AI:</b>
/api — AI/API provider status with masked keys and usage health""",
    'outcome_learning': """<b>Outcome Learning:</b>
/learn today — 09:20 + 09:31 candidate outcome resolution
/learn symbol SYMBOL — symbol outcome memory
/learn patterns — best/worst reason tags""",
    'screener': """<b>Screener / Long-term:</b>
/screener status — latest Screener import status
/screener latest — latest import summary + top long-term picks
/screener import longterm — upload CSV/XLSX or import from data/imports
/longterm — top long-term watchlist from Screener memory
/longterm explain SYMBOL — long-term ratios + tradecard memory
/longterm history — recent long-term recommendation snapshots
/longterm history SYMBOL — long-term history for symbol
/longterm memory SYMBOL — stored long-term thesis memory""",
    'weekly': """<b>Weekly Conviction:</b>
/weekly picks — weekly high-conviction research picks
/weekly history — previous weekly pick snapshots
/weekly explain SYMBOL — weekly conviction breakdown""",
    'investor': """<b>Investor Intelligence:</b>
/investor SYMBOL — shareholding and investor quality for stock
/investor weekly — investor signal for weekly candidates
/investor memory SYMBOL — investor/shareholding history""",
    'action': """<b>Action:</b>
/action plan — final action plan
/bootstrap — rebuild cached reports (background)
/today — today confluence pick
/tomorrow — tomorrow confluence pick
/why &lt;ticker&gt; — reason/risk/confirmation
/premarket — premarket top setups
/premarket full — full premarket brief""",
    'refresh': """<b>Refresh:</b>
/refresh — quick scoped refresh
/refresh quick — quick scoped refresh
/refresh scanner — refresh scanner/gainers/intraday market data
/refresh market — refresh scanner + gainers + radar inputs
/refresh status — source freshness table
/refresh full — full canonical cache refresh""",
    'aihub': """<b>AI Hub:</b>
/aihub — tab menu
/aihub full — full AI Hub summary
/aihub brain · govt · scan · market · global · news · tv · calib · journal
/aihub brain full — full brain details""",
    'feed': """<b>My Feed:</b>
/feed &lt;market news text&gt; — save text to My Feed
/feed verify FEED_ID — re-check saved feed against fresh news
/feed remove FEED_ID — remove bad feed from active memory
/feed restore FEED_ID — restore removed feed
/news refresh — refresh all trusted news sources
/news refresh SYMBOL — refresh all trusted news sources for one company/ticker
/news sources — show enabled news providers and freshness
/myfeed list — latest saved feed
/myfeed today — today's feed
/myfeed scan — tickers/themes impact
/myfeed clean-old — archive dirty image/OCR rows (admin)""",
    'macro': """<b>Macro Shock:</b>
/macro — current macro regime + trading guard
/macro today — today's macro shock memory
/macro explain — macro shock trigger + impact detail""",
    'catalyst': """<b>Catalyst Radar:</b>
/catalyst SYMBOL — catalyst state for one ticker
/catalysts — stock-specific catalyst radar
/catalysts today — today's catalyst priority list
/catalysts explain &lt;ticker&gt; — catalyst reason for ticker""",
    'opening': """<b>Opening Rally:</b>
/radar — opening rally radar (manual)
/gainers — all-cap top gainers discovery
/tradecards — quality tradecards (score ≥60, max 10)""",
    'tradecard': """<b>Trade Card:</b>
/tradecard — one-stock paper trade card
/tradecard today — today's trade card
/tradecard explain — full trade card plan notes
/tradecard journal — today's tradecard journal
/tradecard outcome — tradecard outcome summary""",
    'patterns': """<b>Chart Patterns:</b>
/patterns — scan chart patterns for /tradecards top 10
/pattern — best chart-pattern candidate from /tradecards top 10
/pattern SYMBOL — check chart pattern for one stock
/candles SYMBOL — debug candle snapshots and pattern readiness""",
    'briefs': """<b>Briefs:</b>
/news — news only
/morning — pre-market brief
/close — market close summary""",
    'snapshot': """<b>Snapshot:</b>
/full — run all read-only AstraEdge commands one by one""",
    'themes': """<b>Theme Wishlist:</b>
/theme — overview · list · search · category
/theme &lt;basket&gt; · news · scan · budget · refresh""",
    'budget': """<b>Budget Impact:</b>
/budget — overview · theme &lt;basket&gt; · analyze &lt;text&gt;""",
    'ask_ai': """<b>AI:</b>
/ask ai &lt;question&gt;""",
}

FULL_HELP_ORDER: tuple[str, ...] = (
    'core',
    'qa',
    'trade_memory',
    'ai_status',
    'outcome_learning',
    'screener',
    'weekly',
    'investor',
    'action',
    'refresh',
    'aihub',
    'feed',
    'macro',
    'catalyst',
    'opening',
    'tradecard',
    'patterns',
    'briefs',
    'snapshot',
    'themes',
    'budget',
    'ask_ai',
)

SECTION_ROUTES: dict[str, tuple[str, ...]] = {
    'core': ('core',),
    'qa': ('qa',),
    'memory': ('trade_memory', 'outcome_learning'),
    'ai': ('ai_status', 'aihub', 'ask_ai'),
    'screener': ('screener',),
    'weekly': ('weekly',),
    'investor': ('investor',),
    'feed': ('feed',),
    'macro': ('macro',),
    'catalyst': ('catalyst',),
    'trade': ('action', 'opening', 'tradecard'),
    'patterns': ('patterns',),
    'briefs': ('briefs', 'snapshot'),
    'themes': ('themes', 'budget'),
}

SECTION_LABELS: dict[str, str] = {
    'core': 'Core',
    'qa': 'QA',
    'memory': 'Memory',
    'ai': 'AI',
    'screener': 'Screener',
    'weekly': 'Weekly',
    'investor': 'Investor',
    'feed': 'Feed',
    'macro': 'Macro',
    'catalyst': 'Catalyst',
    'trade': 'Trade',
    'patterns': 'Patterns',
    'briefs': 'Briefs',
    'themes': 'Themes',
}

HELP_TEXT = f'{HELP_HEADER}\n\n' + '\n\n'.join(HELP_BLOCKS[key] for key in FULL_HELP_ORDER)


def format_help_index() -> str:
    """Compact /help index — short enough to avoid Telegram truncation."""
    return f"""<b>🤖 AstraEdge Help</b>
Use section help to avoid Telegram truncation.

<b>Sections:</b>
/help core — status, health, schedule
/help qa — QA commands
/help memory — trade, Screener, investor memory
/help ai — API + Ask AI
/help screener — Screener and longterm
/help weekly — weekly conviction
/help investor — investor/shareholding intelligence
/help feed — My Feed and news
/help macro — macro shock
/help catalyst — catalysts
/help trade — radar, gainers, tradecards
/help patterns — chart patterns and candles
/help briefs — news, morning, close, full
/help themes — theme wishlist and budget

<b>Full:</b>
/help full — send complete help in multiple safe parts

Build: {TELEGRAM_BUILD}"""


def format_help_section(section: str) -> str:
    """Return one section's command list."""
    key = str(section or '').strip().lower()
    block_keys = SECTION_ROUTES.get(key)
    if not block_keys:
        return (
            f'{format_help_index()}\n\n'
            f'Unknown section {section!r}. Use /help for section names.'
        )
    label = SECTION_LABELS.get(key, key.title())
    body = '\n\n'.join(HELP_BLOCKS[block_key] for block_key in block_keys)
    return f'<b>🤖 AstraEdge Help — {label}</b>\n\n{body}\n\nBuild: {TELEGRAM_BUILD}'


def _pack_sections(sections: list[str], max_chars: int) -> list[str]:
    """Split section blocks into parts at section boundaries."""
    parts: list[str] = []
    current: list[str] = []
    current_len = 0

    for section in sections:
        addition = len(section) + (2 if current else 0)
        if current and current_len + addition > max_chars:
            parts.append('\n\n'.join(current))
            current = [section]
            current_len = len(section)
        else:
            current.append(section)
            current_len += addition

    if current:
        parts.append('\n\n'.join(current))
    return parts


def format_help_full_parts(*, max_chars: int = HELP_MAX_PART_CHARS) -> list[str]:
    """Return full help split into safely sized Telegram messages."""
    sections = [HELP_BLOCKS[key] for key in FULL_HELP_ORDER]
    bodies = _pack_sections(sections, max_chars)
    total = len(bodies)
    parts: list[str] = []
    for index, body in enumerate(bodies, start=1):
        header = f'<b>AstraEdge Help — Part {index}/{total}</b>\n\n'
        if index == 1:
            header = f'{HELP_HEADER}\n\n{header}'
        text = header + body
        if index == total:
            text += f'\n\nBuild: {TELEGRAM_BUILD}'
        parts.append(text)
    return parts


def resolve_help_messages(args: str) -> list[str]:
    """Resolve /help variants to one or more message bodies."""
    arg = str(args or '').strip().lower()
    if not arg:
        return [format_help_index()]
    if arg in ('full', 'all'):
        return format_help_full_parts()
    if arg in SECTION_ROUTES:
        return [format_help_section(arg)]
    return [format_help_index()]
