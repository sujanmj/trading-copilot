import logging
import warnings
from datetime import datetime, timezone
from pathlib import Path

import yfinance as yf

from backend.utils.config import DATA_DIR
from backend.utils.market_data_validator import validate_market_snapshot, load_previous_snapshot
from backend.utils.market_hours import get_market_period
from backend.storage.json_io import atomic_write_json

logging.getLogger('yfinance').setLevel(logging.CRITICAL)
warnings.filterwarnings('ignore', category=FutureWarning)

GLOBAL_INDICES = {
    'S&P_500': '^GSPC',
    'NASDAQ': '^IXIC',
    'DOW_JONES': '^DJI',
    'CRUDE_OIL': 'CL=F',
    'GOLD': 'GC=F',
}

OUTPUT_FILE = DATA_DIR / 'global_markets.json'


def fetch_global_sentiment():
    period = get_market_period()
    print("=" * 60)
    print(f"GLOBAL MARKETS COLLECTOR | period={period}")
    print("=" * 60)

    results = {}
    for name, ticker in GLOBAL_INDICES.items():
        try:
            data = yf.download(ticker, period='5d', progress=False)
            if len(data) >= 2:
                close_yesterday = float(data['Close'].iloc[-2].item())
                close_today = float(data['Close'].iloc[-1].item())
                if close_today != close_today or close_yesterday != close_yesterday:
                    print(f"  [FAIL] {name}: NaN in yfinance data")
                    continue
                pct_change = ((close_today - close_yesterday) / close_yesterday) * 100
                results[name] = {
                    'ticker': ticker,
                    'change_pct': round(pct_change, 2),
                    'latest_price': round(close_today, 2),
                    'source': f'yfinance:{ticker}',
                }
                print(f"  [OK] {name.ljust(12)} -> {pct_change:+.2f}%")
            else:
                print(f"  [FAIL] {name.ljust(12)} -> Insufficient data")
        except Exception as e:
            print(f"  [ERROR] {name.ljust(12)} -> {e}")

    raw = {
        'last_updated': datetime.now(timezone.utc).isoformat(),
        'market_period': period,
        'markets': results,
    }

    # Normalize to validator schema
    prices = {
        k: {
            'price': v.get('latest_price'),
            'change_percent': v.get('change_pct'),
            'source': v.get('source'),
        }
        for k, v in results.items()
    }
    prev = load_previous_snapshot(OUTPUT_FILE)
    prev_prices = {
        k: {
            'price': (prev.get('markets') or {}).get(k, {}).get('latest_price'),
            'change_percent': (prev.get('markets') or {}).get(k, {}).get('change_pct'),
            'source': 'previous',
        }
        for k in GLOBAL_INDICES
    }
    validated, _ = validate_market_snapshot(
        {'prices': prices, 'last_updated': raw['last_updated'], 'total_symbols': len(GLOBAL_INDICES)},
        previous_snapshot={'prices': prev_prices},
        file_label='global',
    )

    clean_markets = {}
    for name in results:
        row = validated.get('prices', {}).get(name)
        if not row:
            continue
        clean_markets[name] = {
            'ticker': GLOBAL_INDICES[name],
            'change_pct': row.get('change_percent'),
            'latest_price': row.get('price'),
            'source': row.get('source'),
        }

    output = {
        'last_updated': raw['last_updated'],
        'market_period': period,
        'markets': clean_markets,
        'validation': validated.get('validation'),
    }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(OUTPUT_FILE, output)

    print("-" * 60)
    print('[SAVED] Global macro data ready for AI prediction engine.')
    print("=" * 60)


if __name__ == '__main__':
    fetch_global_sentiment()
