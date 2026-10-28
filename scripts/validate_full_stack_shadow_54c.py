"""Validate 54C with immutable 54B sources and frozen analysis checks."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
from scripts.validate_full_stack_runtime_54b import run, digest_data

def main():
    with tempfile.TemporaryDirectory(prefix='astraedge-54c-validation-') as isolated_dir:
        previous_db = os.environ.get('ASTRAEDGE_HISTORICAL_MARKET_DB')
        os.environ['ASTRAEDGE_HISTORICAL_MARKET_DB'] = str(Path(isolated_dir) / 'historical_market_memory.db')
        try:
            _validate()
        finally:
            if previous_db is None:
                os.environ.pop('ASTRAEDGE_HISTORICAL_MARKET_DB', None)
            else:
                os.environ['ASTRAEDGE_HISTORICAL_MARKET_DB'] = previous_db


def _validate():
    before = digest_data()
    for path in ('backend/runtime/full_stack_adapter.py', 'backend/runtime/full_stack_source.py',
                 'backend/runtime/full_stack_contract.py', 'backend/collectors/nse_preopen_iep.py'):
        assert (ROOT / path).read_bytes() == subprocess.check_output([
            'git', 'show', '35ac7d2530a8df0a740bc97d2c88657e7e4394b5:' + path]), path
    run(expected_stage='54C')
    subprocess.run([sys.executable, 'scripts/test_full_stack_shadow_54c.py'], check=True)
    subprocess.run([sys.executable, 'scripts/test_process_lock_54c.py'], check=True)
    subprocess.run([sys.executable, 'scripts/test_scheduler_supervision_54c.py'], check=True)
    subprocess.run([sys.executable, 'scripts/test_scheduler_horizon_nonblocking_54c.py'], check=True)
    subprocess.run([sys.executable, 'scripts/test_market_hours_holiday_bridge_54c.py'], check=True)
    subprocess.run([sys.executable, 'scripts/test_premarket_freshness_quality.py'], check=True)
    subprocess.run([sys.executable, 'scripts/test_telegram_outcome_tracking.py'], check=True)
    subprocess.run([sys.executable, 'scripts/test_auto_news_myfeed_ingestion.py'], check=True)
    subprocess.run([sys.executable, 'scripts/test_eod_news_digest.py'], check=True)
    subprocess.run([sys.executable, 'scripts/test_eod_stuck_recovery.py'], check=True)
    subprocess.run([sys.executable, 'scripts/test_eod_history_export_timeout.py'], check=True)
    subprocess.run([sys.executable, 'scripts/test_history_export_lifecycle_isolation.py'], check=True)
    subprocess.run([sys.executable, 'scripts/test_eod_health_observability.py'], check=True)
    subprocess.run([sys.executable, 'scripts/test_missed_session_recovery.py'], check=True)
    subprocess.run([sys.executable, 'scripts/test_historical_market_memory_db_override.py'], check=True)
    subprocess.run([sys.executable, '-m', 'py_compile', 'backend/runtime/full_stack_shadow.py',
                    'backend/trading/opening_rally_radar.py'], check=True)
    assert before == digest_data(), '54C tests changed data/'
    print('PHASE_54C_LOCAL_RELEASE_GATES_PASS; LIVE_MARKET_EVIDENCE_PENDING')


if __name__ == '__main__':
    main()
