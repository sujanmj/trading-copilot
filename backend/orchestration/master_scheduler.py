import schedule
import time
import sys
import os
import threading
from datetime import datetime
from pathlib import Path
import pytz
from concurrent.futures import ThreadPoolExecutor

from backend.utils.bootstrap import setup_project_path
from backend.utils.config import PROJECT_ROOT
from backend.utils.runner import run_script
from backend.lifecycle.lifecycle_tracing import SCHEDULER_EXIT_SINGLETON
from backend.orchestration.schedule_registry import (
    bind_primary_scheduler,
    dump_task_registry,
    get_task_registry,
    ist_daily,
    log_scheduler_tick,
    set_job_status,
    tick_ist_jobs,
)

setup_project_path()

IST = pytz.timezone('Asia/Kolkata')
PYTHON_EXE = sys.executable

_eod_thread: threading.Thread | None = None
_eod_lock = threading.Lock()
_interval_jobs_registered = False
_last_recovery_check = 0.0
RECOVERY_CHECK_SECONDS = 300


def run_standalone_script(script_name: str):
    timestamp = datetime.now(IST).strftime("%H:%M:%S")
    print(f"[{timestamp}] Running {script_name}...", flush=True)
    try:
        run_script(script_name, check=True)
    except Exception as e:
        print(f"[!] Deployment Exception executing {script_name}: {str(e)}", flush=True)


def run_all_collectors_parallel(push_telegram_brain: bool = False, run_analyzer: bool = True):
    from backend.utils.market_hours import get_collection_profile
    profile = get_collection_profile()
    period = profile.get('period', 'unknown')
    print("\n" + "=" * 60, flush=True)
    print(f"[*] Ingestion Layer | period={period} @ {datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
    print("=" * 60, flush=True)

    run_standalone_script("collector.py")

    if profile.get('run_parallel_ingestion'):
        ingestion_scripts = [
            "global_collector.py",
            "live_news_tracker.py",
            "nse_announcements.py",
            "inshorts_tracker.py",
            "youtube_tracker.py",
            "govt_tracker.py",
            "telegram_scraper.py",
            "twitter_tracker.py",
            "reddit_tracker.py",
        ]
        with ThreadPoolExecutor(max_workers=len(ingestion_scripts)) as executor:
            executor.map(run_standalone_script, ingestion_scripts)
    elif profile.get('run_global_overnight'):
        print(f"[COLLECTOR] {period} — overnight global/macro ingestion only", flush=True)
        for script in ("global_collector.py", "live_news_tracker.py", "govt_tracker.py"):
            run_standalone_script(script)
    else:
        print(f"[COLLECTOR] {period} — skipping parallel news/social ingestion", flush=True)

    print("[+] Data ingestion complete.", flush=True)
    if profile.get('run_scanner'):
        run_standalone_script("stock_scanner.py")
    else:
        print(f"[COLLECTOR] {period} — skipping scanner", flush=True)
    if run_analyzer and profile.get('run_analyzer'):
        run_standalone_script("master_analyzer.py")
    elif not profile.get('run_analyzer'):
        print(f"[COLLECTOR] {period} — skipping analyzer (low-power mode)", flush=True)
    if push_telegram_brain:
        run_standalone_script("telegram_brain_pusher.py")


def run_collectors_only():
    """After-hours low-power ingestion — no AI synthesis."""
    run_all_collectors_parallel(push_telegram_brain=False, run_analyzer=False)


def run_alert_scheduler_tick():
    from backend.orchestration.alert_scheduler import tick
    try:
        result = tick()
        if result.get('sent') or result.get('skipped'):
            print(
                f"[ALERTS] tick sent={result['sent']} skipped={result.get('skipped', 0)} "
                f"actions={result.get('actions')}",
                flush=True,
            )
    except Exception as e:
        print(f"[!] Alert scheduler tick failed: {e}", flush=True)


def run_full_cycle(brief_name: str = "Scheduled", push_brain: bool = False):
    """Collect data + optional analyzer; smart alerts handled by alert_scheduler."""
    print(f"\n[*] Full Cycle: {brief_name} @ {datetime.now(IST).strftime('%H:%M:%S IST')}", flush=True)
    run_all_collectors_parallel(push_telegram_brain=push_brain, run_analyzer=True)


def _run_eod_lifecycle_impl(force: bool = False, trigger: str = 'scheduled'):
    """Execute EOD lifecycle — runs on worker thread so scheduler loop stays alive."""
    set_job_status('eod_lifecycle', 'running')
    print("\n" + "=" * 60, flush=True)
    print(
        f"[*] Post-Market Lifecycle Pipeline: {datetime.now(IST).strftime('%H:%M:%S IST')} "
        f"trigger={trigger} force={force}",
        flush=True,
    )
    print("=" * 60, flush=True)
    try:
        from backend.lifecycle.prediction_lifecycle_engine import run_end_of_day_cycle
        result = run_end_of_day_cycle(force=force)
        status = result.get('status', 'unknown')
        print(f"[EOD TASK COMPLETE] status={status} trigger={trigger}", flush=True)
        print(f"[EOD PIPELINE] cycle finished status={status}", flush=True)
        if result.get('errors'):
            for err in result['errors'][:8]:
                print(f"  [!] {err}", flush=True)
        if status in ('ok', 'skipped'):
            set_job_status('eod_lifecycle', 'completed')
            try:
                from backend.runtime.snapshot_orchestrator import run_snapshot_cycle
                snap_result = run_snapshot_cycle(trigger=f'eod:{trigger}')
                print(f"[SNAPSHOT] committed ok={snap_result.get('ok')} id={snap_result.get('snapshot_id')}", flush=True)
            except Exception as snap_exc:
                print(f"[!] Snapshot orchestrator after EOD: {snap_exc}", flush=True)
        else:
            set_job_status('eod_lifecycle', f'failed:{status}')
    except Exception as e:
        set_job_status('eod_lifecycle', f'failed:{e}')
        print(f"[EOD TASK COMPLETE] status=failed trigger={trigger} error={e}", flush=True)
        print(f"[!] EOD lifecycle pipeline failed: {e}", flush=True)
        try:
            from backend.lifecycle.lifecycle_tracing import log_error
            log_error('run_post_market_pipeline', e, stage='eod_lifecycle')
        except Exception:
            pass
        print("[LIFECYCLE] Falling back to legacy post-market sequence...", flush=True)
        try:
            run_standalone_script("outcome_tracker.py")
            run_full_cycle("Post-Market")
            run_standalone_script("meta_labeler.py")
            run_standalone_script("prediction_logger.py")
            run_standalone_script("stats_exporter.py")
            run_standalone_script("history_exporter.py")
        except Exception as fb:
            print(f"[!] Legacy fallback also failed: {fb}", flush=True)


def run_post_market_pipeline(force: bool = False, trigger: str = 'scheduled'):
    """Start EOD lifecycle on a dedicated thread — avoid blocking scheduler heartbeat."""
    global _eod_thread
    with _eod_lock:
        if _eod_thread and _eod_thread.is_alive():
            print(f"[EOD PIPELINE] Already running — skip duplicate trigger ({trigger})", flush=True)
            return
        print(f"[EOD TASK FIRING] trigger={trigger} force={force}", flush=True)
        _eod_thread = threading.Thread(
            target=_run_eod_lifecycle_impl,
            kwargs={'force': force, 'trigger': trigger},
            name='EOD-Lifecycle',
            daemon=False,
        )
        _eod_thread.start()
        print("[EOD PIPELINE] Lifecycle thread started", flush=True)


# ── IST daily jobs (Railway-safe — host TZ may be UTC) ─────────────────────
@ist_daily(2, 0, name='overnight_global_ingest')
def _job_overnight_global_ingest():
    """Continuous overnight global/macro symbol tracking."""
    run_standalone_script('global_collector.py')


@ist_daily(4, 0, name='us_close_scan')
def _job_us_close_scan():
    from backend.intelligence.global_intelligence_engine import run_us_close_scan
    run_us_close_scan()


@ist_daily(4, 15, name='macro_synthesis')
def _job_macro_synthesis():
    from backend.intelligence.global_intelligence_engine import run_macro_synthesis
    run_macro_synthesis()


@ist_daily(5, 0, name='overnight_brief')
def _job_overnight_brief():
    from backend.intelligence.global_intelligence_engine import run_india_next_open_report
    run_india_next_open_report(run_analyzer=True)


@ist_daily(8, 30, name='premarket_report_pack')
def _job_premarket_report_pack():
    from backend.scheduler.daily_report_pack_job import run_daily_report_pack_job

    result = run_daily_report_pack_job(mode='premarket')
    print(
        f"[DAILY_PACK_JOB] premarket generated={result.get('generated')} "
        f"mode={result.get('market_mode')} warnings={len(result.get('warnings') or [])}",
        flush=True,
    )


@ist_daily(8, 30, name='premarket_scanner')
def _job_premarket_scanner():
    from backend.intelligence.global_intelligence_engine import run_premarket_scanner
    run_premarket_scanner()


@ist_daily(9, 0, name='market_open_refresh')
def _job_market_open_refresh():
    from backend.intelligence.global_intelligence_engine import run_market_open_refresh
    run_market_open_refresh()


@ist_daily(8, 0, name='outcome_tracker')
def _job_outcome_tracker():
    run_standalone_script("outcome_tracker.py")


@ist_daily(8, 45, name='pre_market')
def _job_pre_market():
    run_full_cycle("Pre-Market")


@ist_daily(12, 0, name='midday')
def _job_midday():
    run_full_cycle("Midday")


@ist_daily(15, 35, name='market_close_intel')
def _job_market_close_intel():
    try:
        from backend.intelligence.market_close_intelligence import build_market_close_report
        from backend.orchestration import telegram_alert_engine as alert_engine
        report = build_market_close_report()
        alert_engine.try_close_summary()
        print(f"[MARKET CLOSE] report generated sectors={report.get('dominant_sectors')}", flush=True)
    except Exception as e:
        print(f"[!] Market close intelligence failed: {e}", flush=True)


@ist_daily(16, 30, name='postmarket_report_pack')
def _job_postmarket_report_pack():
    from backend.scheduler.daily_report_pack_job import run_daily_report_pack_job

    result = run_daily_report_pack_job(mode='postmarket', allow_runtime=True)
    print(
        f"[DAILY_PACK_JOB] postmarket generated={result.get('generated')} "
        f"mode={result.get('market_mode')} warnings={len(result.get('warnings') or [])}",
        flush=True,
    )


@ist_daily(7, 0, weekdays_only=False, name='research_mode_report_pack')
def _job_research_mode_report_pack():
    from backend.scheduler.daily_report_pack_job import run_daily_report_pack_job

    result = run_daily_report_pack_job(mode='research')
    print(
        f"[DAILY_PACK_JOB] research generated={result.get('generated')} "
        f"mode={result.get('market_mode')} warnings={len(result.get('warnings') or [])}",
        flush=True,
    )


@ist_daily(15, 45, name='eod_lifecycle')
def _job_eod_lifecycle():
    run_post_market_pipeline(force=False, trigger='scheduled:15:45')


@ist_daily(23, 0, name='us_pulse')
def _job_us_pulse():
    run_full_cycle("US Pulse")


# ── Intraday IST slots (weekdays) ─────────────────────────────────────────
intraday_slots = [
    "09:30", "10:00", "10:30", "11:00", "11:30",
    "12:00", "12:30", "13:00", "13:30", "14:00",
    "14:30", "15:00", "15:30",
]


def _make_intraday_job(slot: str):
    hour, minute = map(int, slot.split(':'))

    @ist_daily(hour, minute, name=f'intraday_{slot}')
    def _job():
        run_full_cycle(brief_name=f"Intraday {slot}")

    return _job


for slot in intraday_slots:
    _make_intraday_job(slot)


def run_scheduled_collection():
    """Market-hours-aware scheduled ingestion."""
    from backend.utils.market_hours import get_collection_profile
    profile = get_collection_profile()
    period = profile.get('period')
    if period == 'night':
        print("[COLLECTOR] Night mode — skip scheduled collection", flush=True)
        return
    if profile.get('lightweight_only'):
        print(f"[COLLECTOR] {period} — lightweight India collector only", flush=True)
        run_standalone_script("collector.py")
        return
    run_collectors_only()


def run_outcome_horizon_tick():
    """Evaluate 15m/1h/intraday signal horizons during market hours."""
    try:
        from backend.utils.market_hours import get_market_period
        from backend.analytics.signal_outcomes import evaluate_due_horizons
        if get_market_period() != 'market':
            return
        result = evaluate_due_horizons()
        if result.get('evaluated'):
            print(f"[OUTCOME LEARN] evaluated {result['evaluated']} horizons", flush=True)
    except Exception as e:
        print(f"[!] Outcome horizon tick failed: {e}", flush=True)


def run_stability_watchdog_tick():
    try:
        from backend.production.stability_monitor import tick_async_watchdog
        return tick_async_watchdog()
    except Exception as e:
        print(f"[!] Stability watchdog tick failed: {e}", flush=True)
        return {'error': str(e)}


def run_pending_cleanup_tick():
    try:
        from backend.lifecycle.pending_cleanup_daemon import tick_pending_cleanup
        return tick_pending_cleanup()
    except Exception as e:
        print(f"[!] Pending cleanup tick failed: {e}", flush=True)
        return {'error': str(e)}


# Interval jobs — registered only when primary scheduler main() runs
def register_interval_jobs():
    global _interval_jobs_registered
    if _interval_jobs_registered:
        return
    _interval_jobs_registered = True
    schedule.every(30).minutes.do(run_scheduled_collection)
    schedule.every(1).minutes.do(run_alert_scheduler_tick)
    schedule.every(15).minutes.do(run_outcome_horizon_tick)
    schedule.every(30).minutes.do(run_pending_cleanup_tick)
    schedule.every(10).minutes.do(run_stability_watchdog_tick)
    schedule.every(60).minutes.do(dump_task_registry)
    print("[SCHEDULER] Interval jobs registered (primary singleton)", flush=True)


def _run_boot_cycle_async():
    """Boot full cycle on background thread — must not block IST tick loop."""
    try:
        from backend.utils.config import DATA_DIR
        intel_path = DATA_DIR / 'unified_intelligence.json'
        skip_boot = False
        if intel_path.exists():
            age_min = (time.time() - intel_path.stat().st_mtime) / 60
            if age_min < 120:
                skip_boot = True
                print(f"[SCHEDULER] Boot full cycle skipped — intelligence {int(age_min)}m old", flush=True)
        if not skip_boot:
            run_full_cycle("Boot Startup")
    except Exception as e:
        print(f"[SCHEDULER] Boot cycle error (non-fatal): {e}", flush=True)


def _maybe_periodic_eod_recovery():
    global _last_recovery_check
    now = time.time()
    if now - _last_recovery_check < RECOVERY_CHECK_SECONDS:
        return
    _last_recovery_check = now
    try:
        from backend.orchestration.eod_recovery import maybe_trigger_eod_recovery
        maybe_trigger_eod_recovery('periodic')
    except Exception as e:
        print(f"[EOD RECOVERY] Periodic check failed: {e}", flush=True)


def main():
    from backend.utils.process_lock import try_acquire_lock, release_lock, clear_stale_lock

    if not try_acquire_lock('master_scheduler'):
        if clear_stale_lock('master_scheduler') and try_acquire_lock('master_scheduler'):
            print("[ORCHESTRATOR] stale lock detected — re-acquired after cleanup", flush=True)
        else:
            print("[SKIP] master_scheduler already running", flush=True)
            print("[SCHEDULER SINGLETON ACTIVE] Guard exit — primary scheduler lock held", flush=True)
            sys.exit(SCHEDULER_EXIT_SINGLETON)

    try:
        from backend.orchestration.orchestrator_state import mark_primary_acquired
        mark_primary_acquired(os.getpid())
    except Exception as e:
        print(f"[ORCHESTRATOR] primary mark failed: {e}", flush=True)

    if not bind_primary_scheduler():
        print("[WARN] Primary scheduler registry already bound in-process", flush=True)

    register_interval_jobs()

    print("=" * 60, flush=True)
    print("TRADING COPILOT - MASTER ORCHESTRATOR LAUNCHED", flush=True)
    print(f"Boot Time: {datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S IST')}", flush=True)
    print(f"Host TZ: {time.tzname} | IST now: {datetime.now(IST).strftime('%H:%M:%S')}", flush=True)
    print("=" * 60, flush=True)
    print("[SCHEDULER HEALTHY] Lock acquired — orchestrator running", flush=True)
    if os.environ.get('LOCAL_DEV_MODE') == '1':
        print("[LOCAL RUNTIME] scheduler PRIMARY (in-process, no cloud locks)", flush=True)
    dump_task_registry()

    threading.Thread(target=_run_boot_cycle_async, name='Boot-Cycle', daemon=True).start()
    print("[SCHEDULER] Boot cycle running in background — IST tick loop starting", flush=True)

    try:
        from backend.orchestration.eod_recovery import run_startup_eod_recovery
        run_startup_eod_recovery()
    except Exception as e:
        print(f"[EOD RECOVERY] Startup recovery check failed: {e}", flush=True)

    last_registry_dump = time.time()

    try:
        while True:
            log_scheduler_tick()
            tick_ist_jobs()
            schedule.run_pending()
            _maybe_periodic_eod_recovery()
            if time.time() - last_registry_dump > 3600:
                dump_task_registry()
                last_registry_dump = time.time()
            time.sleep(1)
    finally:
        release_lock('master_scheduler')


if __name__ == "__main__":
    setup_project_path()
    main()
