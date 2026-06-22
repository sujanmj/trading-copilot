"""Subprocess runner for backend scripts — module-based execution."""

import os
import subprocess
import sys
from typing import Dict, Optional

from backend.utils.config import PROJECT_ROOT
from backend.utils.safe_stdio import safe_stream

# Legacy script filename -> Python module
SCRIPT_MODULES = {
    'collector.py': 'backend.collectors.collector',
    'global_collector.py': 'backend.collectors.global_collector',
    'live_news_tracker.py': 'backend.collectors.live_news_tracker',
    'nse_announcements.py': 'backend.collectors.nse_announcements',
    'inshorts_tracker.py': 'backend.collectors.inshorts_tracker',
    'youtube_tracker.py': 'backend.collectors.youtube_tracker',
    'govt_tracker.py': 'backend.collectors.govt_tracker',
    'telegram_scraper.py': 'backend.collectors.telegram_scraper',
    'twitter_tracker.py': 'backend.collectors.twitter_tracker',
    'reddit_tracker.py': 'backend.collectors.reddit_tracker',
    'news_aggregator.py': 'backend.collectors.news_aggregator',
    'stock_scanner.py': 'backend.analyzers.stock_scanner',
    'master_analyzer.py': 'backend.analyzers.master_analyzer',
    'outcome_tracker.py': 'backend.analyzers.outcome_tracker',
    'meta_labeler.py': 'backend.analyzers.meta_labeler',
    'prediction_logger.py': 'backend.analyzers.prediction_logger',
    'analyzer.py': 'backend.analyzers.analyzer',
    'alert_engine.py': 'backend.orchestration.alert_engine',
    'telegram_brain_pusher.py': 'backend.orchestration.telegram_brain_pusher',
    'stats_exporter.py': 'backend.storage.stats_exporter',
    'history_exporter.py': 'backend.storage.history_exporter',
    'master_scheduler.py': 'backend.orchestration.master_scheduler',
    'telegram_listener.py': 'backend.orchestration.telegram_listener',
}


def resolve_module(name: str) -> Optional[str]:
    """Resolve legacy script name or short module alias to Python module path."""
    if name in SCRIPT_MODULES:
        return SCRIPT_MODULES[name]
    key = name if name.endswith('.py') else f'{name}.py'
    return SCRIPT_MODULES.get(key)


def _base_env(extra: Optional[Dict[str, str]] = None) -> dict:
    env = os.environ.copy()
    env['PYTHONIOENCODING'] = 'utf-8'
    env['PYTHONUTF8'] = '1'
    env['PYTHONPATH'] = str(PROJECT_ROOT)
    if extra:
        env.update(extra)
    return env


def module_for_script(script_name: str) -> Optional[str]:
    return resolve_module(script_name)


def run_module(module: str, check: bool = False, extra_env: Optional[Dict[str, str]] = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, '-m', module],
        env=_base_env(extra_env),
        cwd=str(PROJECT_ROOT),
        check=check,
    )


def run_script(script_name: str, check: bool = False, extra_env: Optional[Dict[str, str]] = None) -> subprocess.CompletedProcess:
    module = module_for_script(script_name)
    if not module:
        raise FileNotFoundError(f'Unknown script: {script_name}')
    return run_module(module, check=check, extra_env=extra_env)


def popen_script(
    script_name: str,
    stdout=None,
    stderr=None,
    extra_env: Optional[Dict[str, str]] = None,
    args: Optional[list] = None,
) -> subprocess.Popen:
    module = module_for_script(script_name)
    if not module:
        raise FileNotFoundError(f'Unknown script: {script_name}')
    cmd = [sys.executable, '-m', module]
    if args:
        cmd.extend(args)
    if stdout is not None and not isinstance(stdout, int):
        stdout = safe_stream('stdout', preferred=stdout)
    if stderr is not None and not isinstance(stderr, int):
        stderr = safe_stream('stderr', preferred=stderr)
    return subprocess.Popen(
        cmd,
        env=_base_env(extra_env),
        cwd=str(PROJECT_ROOT),
        stdout=stdout,
        stderr=stderr,
        bufsize=1,
    )


def run_script_capture(
    script_name: str,
    timeout: int = 120,
    extra_env: Optional[Dict[str, str]] = None,
    args: Optional[list] = None,
) -> dict:
    module = module_for_script(script_name)
    if not module:
        return {'success': False, 'error': f'Unknown script: {script_name}'}
    cmd = [sys.executable, '-m', module]
    if args:
        cmd.extend(args)
    try:
        proc = subprocess.run(
            cmd,
            env=_base_env(extra_env),
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        stdout = proc.stdout or ''
        stderr = proc.stderr or ''
        return {
            'success': proc.returncode == 0,
            'returncode': proc.returncode,
            'stdout': stdout[-8000:] if len(stdout) > 8000 else stdout,
            'stderr': stderr[-8000:] if len(stderr) > 8000 else stderr,
        }
    except subprocess.TimeoutExpired as e:
        stdout = (e.stdout or '') if isinstance(e.stdout, str) else (e.stdout.decode('utf-8', errors='replace') if e.stdout else '')
        stderr = (e.stderr or '') if isinstance(e.stderr, str) else (e.stderr.decode('utf-8', errors='replace') if e.stderr else '')
        return {
            'success': False,
            'returncode': -1,
            'stdout': stdout[-8000:] if len(stdout) > 8000 else stdout,
            'stderr': (stderr + f'\n[TIMEOUT] Exceeded {timeout}s limit')[-8000:],
        }
    except Exception as e:
        return {
            'success': False,
            'returncode': -1,
            'stdout': '',
            'stderr': str(e),
        }
