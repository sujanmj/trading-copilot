#!/usr/bin/env python3
"""One-time refactor: move backend modules into domain folders and fix imports."""

import re
import shutil
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
PROJECT = BACKEND.parent

MOVES = {
    # ai
    'ai_router.py': 'ai/ai_router.py',
    'ai_pipeline_router.py': 'ai/ai_pipeline_router.py',
    'ai_budget_manager.py': 'ai/ai_budget_manager.py',
    'intelligence_compressor.py': 'ai/intelligence_compressor.py',
    'token_optimizer.py': 'ai/token_optimizer.py',
    'response_validator.py': 'ai/response_validator.py',
    'signal_ranker.py': 'ai/signal_ranker.py',
    'deduplicator.py': 'ai/deduplicator.py',
    # collectors
    'collector.py': 'collectors/collector.py',
    'reddit_tracker.py': 'collectors/reddit_tracker.py',
    'govt_tracker.py': 'collectors/govt_tracker.py',
    'youtube_tracker.py': 'collectors/youtube_tracker.py',
    'live_news_tracker.py': 'collectors/live_news_tracker.py',
    'telegram_scraper.py': 'collectors/telegram_scraper.py',
    'twitter_tracker.py': 'collectors/twitter_tracker.py',
    'global_collector.py': 'collectors/global_collector.py',
    'inshorts_tracker.py': 'collectors/inshorts_tracker.py',
    'nse_announcements.py': 'collectors/nse_announcements.py',
    'news_aggregator.py': 'collectors/news_aggregator.py',
    # analyzers
    'master_analyzer.py': 'analyzers/master_analyzer.py',
    'stock_scanner.py': 'analyzers/stock_scanner.py',
    'learning_engine.py': 'analyzers/learning_engine.py',
    'prediction_logger.py': 'analyzers/prediction_logger.py',
    'outcome_tracker.py': 'analyzers/outcome_tracker.py',
    'postmortem.py': 'analyzers/postmortem.py',
    'analyzer.py': 'analyzers/analyzer.py',
    'meta_labeler.py': 'analyzers/meta_labeler.py',
    'context_snapshot.py': 'analyzers/context_snapshot.py',
    # orchestration
    'master_scheduler.py': 'orchestration/master_scheduler.py',
    'scheduler.py': 'orchestration/scheduler.py',
    'telegram_listener.py': 'orchestration/telegram_listener.py',
    'telegram_brain_pusher.py': 'orchestration/telegram_brain_pusher.py',
    'alert_engine.py': 'orchestration/alert_engine.py',
    # api
    'api_server.py': 'api/api_server.py',
    # storage
    'db_manager.py': 'storage/db_manager.py',
    'db_finder.py': 'storage/db_finder.py',
    'json_io.py': 'storage/json_io.py',
    'stats_exporter.py': 'storage/stats_exporter.py',
    'history_exporter.py': 'storage/history_exporter.py',
    # utils (already have config.py and bootstrap.py)
    'process_lock.py': 'utils/process_lock.py',
    'local_logging.py': 'utils/local_logging.py',
    'nse_top500.py': 'utils/nse_top500.py',
    'translate_page.py': 'utils/translate_page.py',
    'get_session.py': 'utils/get_session.py',
    'telegram_bot.py': 'utils/telegram_bot.py',
    'force_clean.py': 'utils/force_clean.py',
    'data-audit.py': 'utils/data-audit.py',
}

IMPORT_REPLACEMENTS = [
    (r'\bfrom config import\b', 'from backend.utils.config import'),
    (r'\bimport config\b', 'import backend.utils.config as config'),
    (r'\bfrom json_io import\b', 'from backend.storage.json_io import'),
    (r'\bfrom ai_router import\b', 'from backend.ai.ai_router import'),
    (r'\bfrom response_validator import\b', 'from backend.ai.response_validator import'),
    (r'\bfrom ai_pipeline_router import\b', 'from backend.ai.ai_pipeline_router import'),
    (r'\bfrom ai_budget_manager import\b', 'from backend.ai.ai_budget_manager import'),
    (r'\bfrom intelligence_compressor import\b', 'from backend.ai.intelligence_compressor import'),
    (r'\bfrom token_optimizer import\b', 'from backend.ai.token_optimizer import'),
    (r'\bfrom deduplicator import\b', 'from backend.ai.deduplicator import'),
    (r'\bfrom signal_ranker import\b', 'from backend.ai.signal_ranker import'),
    (r'\bfrom db_manager import\b', 'from backend.storage.db_manager import'),
    (r'\bfrom db_finder import\b', 'from backend.storage.db_finder import'),
    (r'\bfrom process_lock import\b', 'from backend.utils.process_lock import'),
    (r'\bfrom local_logging import\b', 'from backend.utils.local_logging import'),
    (r'\bfrom learning_engine import\b', 'from backend.analyzers.learning_engine import'),
    (r'\bfrom prediction_logger import\b', 'from backend.analyzers.prediction_logger import'),
    (r'\bfrom history_exporter import\b', 'from backend.storage.history_exporter import'),
    (r'\bfrom stats_exporter import\b', 'from backend.storage.stats_exporter import'),
    (r'\bfrom postmortem import\b', 'from backend.analyzers.postmortem import'),
    (r'\bfrom context_snapshot import\b', 'from backend.analyzers.context_snapshot import'),
    (r'\bfrom nse_top500 import\b', 'from backend.utils.nse_top500 import'),
]

PATH_FIXES = [
    (r"Path\(__file__\)\.parent\.parent / 'data'", "Path(__file__).resolve().parent.parent.parent.parent / 'data'"),
    (r'Path\(__file__\)\.parent\.parent / "data"', 'Path(__file__).resolve().parent.parent.parent.parent / "data"'),
    (r"Path\(__file__\)\.resolve\(\)\.parent\.parent", "BACKEND_DIR.parent if 'BACKEND_DIR' in dir() else Path(__file__).resolve().parent.parent.parent.parent"),
]

def patch_content(text: str, filepath: Path) -> str:
    for pattern, repl in IMPORT_REPLACEMENTS:
        text = re.sub(pattern, repl, text)
    # Remove legacy sys.path hacks
    text = re.sub(r"sys\.path\.insert\(0, str\(Path\(__file__\)\.parent\)\)\n", '', text)
    text = re.sub(r"sys\.path\.insert\(0, str\(Path\(__file__\)\.parent\.parent\)\)\n", '', text)
    # Fix BACKEND_DIR in collectors that used parent.parent for data
    if 'collectors' in str(filepath) or 'analyzers' in str(filepath) or 'orchestration' in str(filepath):
        text = text.replace(
            "Path(__file__).parent.parent / 'data'",
            "Path(__file__).resolve().parent.parent.parent / 'data'",
        )
        text = text.replace(
            'Path(__file__).parent.parent / "data"',
            'Path(__file__).resolve().parent.parent.parent / "data"',
        )
        text = text.replace(
            "Path(__file__).resolve().parent.parent / 'config'",
            "Path(__file__).resolve().parent.parent.parent / 'config'",
        )
        text = text.replace(
            "Path(__file__).parent.parent / 'config'",
            "Path(__file__).resolve().parent.parent.parent / 'config'",
        )
    return text


def main():
    for pkg in ('ai', 'collectors', 'analyzers', 'orchestration', 'api', 'storage', 'utils', 'prompts'):
        (BACKEND / pkg).mkdir(parents=True, exist_ok=True)
        init = BACKEND / pkg / '__init__.py'
        if not init.exists():
            init.write_text('', encoding='utf-8')
    if not (BACKEND / '__init__.py').exists():
        (BACKEND / '__init__.py').write_text('', encoding='utf-8')

    for src_name, dest_rel in MOVES.items():
        src = BACKEND / src_name
        dest = BACKEND / dest_rel
        if not src.exists():
            if dest.exists():
                continue
            print(f'SKIP missing: {src_name}')
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        content = src.read_text(encoding='utf-8')
        content = patch_content(content, dest)
        dest.write_text(content, encoding='utf-8')
        if src != dest:
            src.unlink()
            print(f'MOVED {src_name} -> {dest_rel}')

    # Patch all py files under backend (including moved)
    for py in BACKEND.rglob('*.py'):
        if py.name == 'refactor_move.py':
            continue
        text = py.read_text(encoding='utf-8')
        new_text = patch_content(text, py)
        if new_text != text:
            py.write_text(new_text, encoding='utf-8')

    # Remove old root config if duplicate
    old_config = BACKEND / 'config.py'
    if old_config.exists():
        old_config.unlink()

    print('Done.')


if __name__ == '__main__':
    main()
