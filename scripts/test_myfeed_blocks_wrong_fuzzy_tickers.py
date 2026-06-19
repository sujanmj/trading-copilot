#!/usr/bin/env python3
"""Stage 50Y — block PTC/PARAS/IDEA/CHINA fuzzy false positives."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'MYFEED_BLOCKS_WRONG_FUZZY_TICKERS_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.my_feed.feed_verification import normalize_claim

    adani_rough = normalize_claim('adani lost airport contract to kenya')
    adani_ports = normalize_claim(
        'Adani Ports to invest $850 million in AI, technology upgrades and cargo capacity expansion'
    )
    china_kenya = normalize_claim(
        'China wins $2.9 billion Kenya airport deal, about 50% higher than shelved Adani proposal'
    )

    for bad in ('PTC', 'PARAS', 'IOB', 'KEI'):
        if bad in (adani_rough.get('tickers') or []):
            return _fail(f'rough adani feed must not map to {bad}')
        if bad in (adani_ports.get('tickers') or []):
            return _fail(f'Adani Ports feed must not map to {bad}')

    if 'IDEA' in (china_kenya.get('tickers') or []) or 'CHINA' in (china_kenya.get('tickers') or []):
        return _fail('China/Kenya headline must not map to IDEA or CHINA tickers')

    ptc_ok = normalize_claim('PTC India wins power trading contract renewal')
    if 'PTC' not in (ptc_ok.get('tickers') or []):
        return _fail('PTC allowed only with PTC India evidence')

    paras_ok = normalize_claim('Paras Defence secures new order from defence ministry')
    if 'PARAS' not in (paras_ok.get('tickers') or []):
        return _fail('PARAS allowed only with Paras Defence evidence')

    idea_ok = normalize_claim('Vodafone Idea raises funds for network upgrade')
    if 'IDEA' not in (idea_ok.get('tickers') or []):
        return _fail('IDEA allowed only with Vodafone Idea evidence')

    print('MYFEED_BLOCKS_WRONG_FUZZY_TICKERS_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
