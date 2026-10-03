"""Validate 54C with immutable 54B sources and frozen analysis checks."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
from scripts.validate_full_stack_runtime_54b import run, digest_data

if __name__ == '__main__':
    before = digest_data()
    for path in ('backend/runtime/full_stack_adapter.py', 'backend/runtime/full_stack_source.py',
                 'backend/runtime/full_stack_contract.py', 'backend/collectors/nse_preopen_iep.py'):
        assert (ROOT / path).read_bytes() == subprocess.check_output([
            'git', 'show', '35ac7d2530a8df0a740bc97d2c88657e7e4394b5:' + path]), path
    run(expected_stage='54C')
    subprocess.run([sys.executable, 'scripts/test_full_stack_shadow_54c.py'], check=True)
    subprocess.run([sys.executable, '-m', 'py_compile', 'backend/runtime/full_stack_shadow.py',
                    'backend/trading/opening_rally_radar.py'], check=True)
    assert before == digest_data(), '54C tests changed data/'
    print('PHASE_54C_LOCAL_RELEASE_GATES_PASS; LIVE_MARKET_EVIDENCE_PENDING')
