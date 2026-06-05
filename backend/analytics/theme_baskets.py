"""
AstraEdge Theme Baskets — thematic intelligence engine (Stage 47A).

Maps news/govt/budget headlines to theme baskets, sectors, and beneficiary stocks.
Research-only wording — watch/confirm, never buy now or guaranteed.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from backend.storage.data_paths import get_data_path
from backend.storage.json_io import atomic_write_json

IST = ZoneInfo('Asia/Kolkata')
STAGE = '47A'
BASKETS_FILE = get_data_path('theme_baskets.json')
CATALYST_LOG_FILE = get_data_path('theme_catalyst_log.jsonl')

FORBIDDEN_WORDS = ('buy now', 'guaranteed', 'invest now')
BUDGET_THEME_IDS = (
    'infrastructure',
    'defence',
    'railways',
    'power_grid_transmission',
    'agriculture_fertilizer',
    'housing_real_estate',
    'banking_psu_nbfc',
    'renewable_energy',
)

THEME_ALIASES: dict[str, str] = {
    'infra': 'infrastructure',
    'infrastructure': 'infrastructure',
    'roads': 'roads_highways',
    'road': 'roads_highways',
    'highways': 'roads_highways',
    'highway': 'roads_highways',
    'railway': 'railways',
    'railways': 'railways',
    'rail': 'railways',
    'defence': 'defence',
    'defense': 'defence',
    'renewable': 'renewable_energy',
    'renewables': 'renewable_energy',
    'power': 'power_grid_transmission',
    'grid': 'power_grid_transmission',
    'transmission': 'power_grid_transmission',
    'housing': 'housing_real_estate',
    'real_estate': 'housing_real_estate',
    'realestate': 'housing_real_estate',
    'cement': 'cement_steel_paint',
    'steel': 'cement_steel_paint',
    'paint': 'cement_steel_paint',
    'ports': 'ports_logistics',
    'logistics': 'ports_logistics',
    'agriculture': 'agriculture_fertilizer',
    'fertilizer': 'agriculture_fertilizer',
    'fertiliser': 'agriculture_fertilizer',
    'semiconductor': 'semiconductors_electronics',
    'semiconductors': 'semiconductors_electronics',
    'electronics': 'semiconductors_electronics',
    'tourism': 'tourism_temple_culture',
    'temple': 'tourism_temple_culture',
    'culture': 'tourism_temple_culture',
    'banking': 'banking_psu_nbfc',
    'psu': 'banking_psu_nbfc',
    'nbfc': 'banking_psu_nbfc',
    'it': 'it_digital_india',
    'digital': 'it_digital_india',
    'oil': 'oil_gas_energy',
    'gas': 'oil_gas_energy',
    'energy': 'oil_gas_energy',
    'metals': 'metals_mining',
    'mining': 'metals_mining',
    'telecom': 'telecom_5g',
    '5g': 'telecom_5g',
    'water': 'water_jal_jeevan',
    'jal': 'water_jal_jeevan',
    'jeevan': 'water_jal_jeevan',
    'budget': 'budget',
}


def _log(msg: str) -> None:
    print(f'[THEME_BASKETS] {msg}', flush=True)


def _now_iso() -> str:
    return datetime.now(IST).replace(microsecond=0).isoformat()


def _default_baskets() -> list[dict[str, Any]]:
    """Bootstrap 18 default theme baskets."""
    defs = [
        {
            'theme_id': 'infrastructure',
            'display_name': 'Infrastructure',
            'keywords': ['infrastructure', 'infra', 'construction', 'epc', 'project', 'capex'],
            'trigger_keywords': ['road', 'highway', 'metro', 'bridge', 'tunnel', 'smart city'],
            'direct_beneficiary_sectors': ['EPC contractors', 'Construction', 'Civil engineering'],
            'indirect_beneficiary_sectors': ['Cement', 'Steel', 'Paint', 'Pipes', 'Cables', 'Logistics'],
            'raw_material_beneficiaries': ['Cement', 'Steel', 'Aggregates'],
            'risk_sectors': ['Over-leveraged infra', 'Delayed receivables'],
            'stocks': {
                'direct': ['LT', 'ADANIENT', 'IRB', 'PNCINFRA', 'KNR'],
                'indirect': ['ULTRACEMCO', 'ACC', 'TATASTEEL', 'ASIANPAINT', 'POLYCAB'],
                'raw_material': ['SHREECEM', 'RAMCOCEM', 'SAIL'],
                'avoid_or_risk': ['YESBANK'],
            },
            'confirmation_rules': ['Price strength + volume', 'Sector support', 'Named order/tender'],
            'stale_after_hours': 48,
        },
        {
            'theme_id': 'roads_highways',
            'display_name': 'Roads / Highways',
            'keywords': ['road', 'highway', 'nh', 'expressway', 'bharatmala', 'toll'],
            'trigger_keywords': ['road project', 'highway project', 'expressway', 'nhai'],
            'direct_beneficiary_sectors': ['Road EPC', 'Highway contractors', 'Toll operators'],
            'indirect_beneficiary_sectors': ['Cement', 'Steel', 'Bitumen', 'Equipment'],
            'raw_material_beneficiaries': ['Cement', 'Steel', 'Bitumen'],
            'risk_sectors': ['Land acquisition delays', 'Margin compression'],
            'stocks': {
                'direct': ['IRB', 'PNCINFRA', 'KNR', 'GRINFRA', 'HGINFRA'],
                'indirect': ['ULTRACEMCO', 'ACC', 'DALBHARAT', 'TATASTEEL'],
                'raw_material': ['SHREECEM', 'RAMCOCEM'],
                'avoid_or_risk': [],
            },
            'confirmation_rules': ['Order win confirmation', 'Volume breakout', 'Sector breadth'],
            'stale_after_hours': 48,
        },
        {
            'theme_id': 'railways',
            'display_name': 'Railways',
            'keywords': ['railway', 'rail', 'rlys', 'train', 'locomotive', 'vande bharat'],
            'trigger_keywords': ['rail project', 'railway capex', 'railyard', 'metro rail'],
            'direct_beneficiary_sectors': ['Rail EPC', 'Rolling stock', 'Signalling'],
            'indirect_beneficiary_sectors': ['Steel', 'Electricals', 'Cables', 'Logistics'],
            'raw_material_beneficiaries': ['Steel', 'Aluminium'],
            'risk_sectors': ['Execution delays', 'PSU order timing'],
            'stocks': {
                'direct': ['TITAGARH', 'TEXRAIL', 'IRCON', 'RVNL', 'RAILTEL'],
                'indirect': ['TATASTEEL', 'POLYCAB', 'KEI', 'CONCOR'],
                'raw_material': ['SAIL', 'JINDALSTEL'],
                'avoid_or_risk': [],
            },
            'confirmation_rules': ['Rail order/tender clarity', 'Price + volume confirm'],
            'stale_after_hours': 48,
        },
        {
            'theme_id': 'defence',
            'display_name': 'Defence',
            'keywords': ['defence', 'defense', 'military', 'army', 'navy', 'air force', 'ordnance'],
            'trigger_keywords': ['defence order', 'defence budget', 'make in india defence'],
            'direct_beneficiary_sectors': ['Defence OEM', 'Aerospace', 'Shipbuilding'],
            'indirect_beneficiary_sectors': ['Electronics', 'Metals', 'Precision engineering'],
            'raw_material_beneficiaries': ['Specialty metals', 'Electronics components'],
            'risk_sectors': ['Export dependency', 'Long gestation'],
            'stocks': {
                'direct': ['HAL', 'BEL', 'BEML', 'COCHINSHIP', 'MAZDOCK'],
                'indirect': ['MTARTECH', 'DATAPATTNS', 'ASTRAMICRO'],
                'raw_material': ['HINDZINC', 'NATIONALUM'],
                'avoid_or_risk': [],
            },
            'confirmation_rules': ['Named contract/order', 'Budget allocation clarity'],
            'stale_after_hours': 72,
        },
        {
            'theme_id': 'renewable_energy',
            'display_name': 'Renewable Energy',
            'keywords': ['renewable', 'solar', 'wind', 'green energy', 'clean energy'],
            'trigger_keywords': ['solar project', 'wind farm', 'renewable target', 'green hydrogen'],
            'direct_beneficiary_sectors': ['Solar EPC', 'Wind OEM', 'IPP'],
            'indirect_beneficiary_sectors': ['Cables', 'Transformers', 'Metals'],
            'raw_material_beneficiaries': ['Polysilicon supply chain', 'Copper'],
            'risk_sectors': ['Tariff uncertainty', 'Import dependency'],
            'stocks': {
                'direct': ['ADANIGREEN', 'NTPC', 'TATAPOWER', 'SUZLON', 'WAAREE'],
                'indirect': ['POLYCAB', 'KEI', 'HINDCOPPER'],
                'raw_material': ['HINDCOPPER', 'NATIONALUM'],
                'avoid_or_risk': [],
            },
            'confirmation_rules': ['Project commissioning', 'Policy clarity', 'Volume confirm'],
            'stale_after_hours': 48,
        },
        {
            'theme_id': 'power_grid_transmission',
            'display_name': 'Power / Grid / Transmission',
            'keywords': ['power', 'grid', 'transmission', 'distribution', 'electricity'],
            'trigger_keywords': ['transmission line', 'grid expansion', 'power project'],
            'direct_beneficiary_sectors': ['Power transmission', 'Grid EPC', 'Transformers'],
            'indirect_beneficiary_sectors': ['Cables', 'Switchgear', 'EPC'],
            'raw_material_beneficiaries': ['Copper', 'Aluminium'],
            'risk_sectors': ['Regulatory delays', 'Discom health'],
            'stocks': {
                'direct': ['POWERGRID', 'ADANITRANS', 'TARIL', 'KEC'],
                'indirect': ['POLYCAB', 'KEI', 'ABB', 'SIEMENS'],
                'raw_material': ['HINDCOPPER', 'NATIONALUM'],
                'avoid_or_risk': [],
            },
            'confirmation_rules': ['Tender award', 'Grid capex headline', 'Sector support'],
            'stale_after_hours': 48,
        },
        {
            'theme_id': 'housing_real_estate',
            'display_name': 'Housing / Real Estate',
            'keywords': ['housing', 'real estate', 'property', 'affordable housing', 'rera'],
            'trigger_keywords': ['housing scheme', 'real estate boost', 'home loan'],
            'direct_beneficiary_sectors': ['Real estate developers', 'Housing finance'],
            'indirect_beneficiary_sectors': ['Cement', 'Tiles', 'Paints', 'Home finance'],
            'raw_material_beneficiaries': ['Cement', 'Steel', 'Tiles'],
            'risk_sectors': ['Inventory overhang', 'Rate sensitivity'],
            'stocks': {
                'direct': ['DLF', 'GODREJPROP', 'OBEROIRLTY', 'LODHA', 'PRESTIGE'],
                'indirect': ['ULTRACEMCO', 'ASIANPAINT', 'KAJARIACER', 'HDFC'],
                'raw_material': ['SHREECEM', 'ACC'],
                'avoid_or_risk': [],
            },
            'confirmation_rules': ['Sales momentum', 'Policy support clarity', 'Volume confirm'],
            'stale_after_hours': 72,
        },
        {
            'theme_id': 'cement_steel_paint',
            'display_name': 'Cement / Steel / Paint',
            'keywords': ['cement', 'steel', 'paint', 'building material'],
            'trigger_keywords': ['cement demand', 'steel prices', 'infra demand'],
            'direct_beneficiary_sectors': ['Cement', 'Steel', 'Paints'],
            'indirect_beneficiary_sectors': ['Logistics', 'Mining', 'Distribution'],
            'raw_material_beneficiaries': ['Iron ore', 'Limestone', 'Coal'],
            'risk_sectors': ['China demand shock', 'Input cost spike'],
            'stocks': {
                'direct': ['ULTRACEMCO', 'SHREECEM', 'TATASTEEL', 'JSWSTEEL', 'ASIANPAINT'],
                'indirect': ['ACC', 'AMBUJACEM', 'SAIL', 'BERGER'],
                'raw_material': ['NMDC', 'COALINDIA'],
                'avoid_or_risk': [],
            },
            'confirmation_rules': ['Volume + price trend', 'Infra order linkage'],
            'stale_after_hours': 48,
        },
        {
            'theme_id': 'ports_logistics',
            'display_name': 'Ports / Logistics',
            'keywords': ['port', 'logistics', 'shipping', 'cargo', 'supply chain'],
            'trigger_keywords': ['port expansion', 'logistics corridor', 'container traffic'],
            'direct_beneficiary_sectors': ['Port operators', 'Logistics', 'Shipping'],
            'indirect_beneficiary_sectors': ['Road/rail connectivity', 'Warehousing'],
            'raw_material_beneficiaries': ['Fuel', 'Equipment'],
            'risk_sectors': ['Global trade slowdown', 'Freight rate volatility'],
            'stocks': {
                'direct': ['ADANIPORTS', 'CONCOR', 'GATI', 'BLUEDART'],
                'indirect': ['IRB', 'TCIEXP', 'MAHLOG'],
                'raw_material': ['IOC', 'BPCL'],
                'avoid_or_risk': [],
            },
            'confirmation_rules': ['Cargo volume trend', 'Named port project'],
            'stale_after_hours': 48,
        },
        {
            'theme_id': 'agriculture_fertilizer',
            'display_name': 'Agriculture / Fertilizer',
            'keywords': ['agriculture', 'fertilizer', 'fertiliser', 'farm', 'kisan', 'crop'],
            'trigger_keywords': ['fertilizer subsidy', 'agri budget', 'monsoon', 'msp'],
            'direct_beneficiary_sectors': ['Fertilizers', 'Agri inputs', 'Irrigation'],
            'indirect_beneficiary_sectors': ['Rural consumption', 'Tractors', 'Seeds'],
            'raw_material_beneficiaries': ['Potash', 'Urea inputs'],
            'risk_sectors': ['Monsoon risk', 'Subsidy timing'],
            'stocks': {
                'direct': ['COROMANDEL', 'CHAMBLFERT', 'GNFC', 'RCF', 'NFL'],
                'indirect': ['UPL', 'PIIND', 'ESCORTS', 'M&M'],
                'raw_material': ['GSFC'],
                'avoid_or_risk': [],
            },
            'confirmation_rules': ['Policy/subsidy clarity', 'Seasonal demand confirm'],
            'stale_after_hours': 72,
        },
        {
            'theme_id': 'semiconductors_electronics',
            'display_name': 'Semiconductors / Electronics',
            'keywords': ['semiconductor', 'chip', 'electronics', 'fab', 'pli'],
            'trigger_keywords': ['semiconductor plant', 'chip manufacturing', 'electronics pli'],
            'direct_beneficiary_sectors': ['Electronics manufacturing', 'EMS', 'Semiconductors'],
            'indirect_beneficiary_sectors': ['Capital goods', 'Industrial gases', 'IT hardware'],
            'raw_material_beneficiaries': ['Silicon', 'Specialty chemicals'],
            'risk_sectors': ['Import dependency', 'Long gestation'],
            'stocks': {
                'direct': ['DIXON', 'KAYNES', 'SYRMA', 'HCLTECH'],
                'indirect': ['ABB', 'SIEMENS', 'LT', 'TATAELXSI'],
                'raw_material': ['DEEPAKNTR', 'AARTIIND'],
                'avoid_or_risk': [],
            },
            'confirmation_rules': ['PLI approval', 'Named fab/project', 'Order book clarity'],
            'stale_after_hours': 72,
        },
        {
            'theme_id': 'tourism_temple_culture',
            'display_name': 'Tourism / Temple / Culture',
            'keywords': ['tourism', 'temple', 'pilgrimage', 'heritage', 'travel', 'hotel'],
            'trigger_keywords': ['tourism boost', 'ram mandir', 'pilgrimage', 'cultural corridor'],
            'direct_beneficiary_sectors': ['Hotels', 'Travel', 'Hospitality', 'Airlines'],
            'indirect_beneficiary_sectors': ['Railways', 'Local infra', 'F&B', 'Retail'],
            'raw_material_beneficiaries': ['Construction materials'],
            'risk_sectors': ['Seasonality', 'Event-driven hype'],
            'stocks': {
                'direct': ['INDIGO', 'IRCTC', 'LEMONTREE', 'CHALET', 'EIHOTEL'],
                'indirect': ['ITC', 'TITAGARH', 'IRCON', 'TATACONSUM'],
                'raw_material': ['ULTRACEMCO', 'ASIANPAINT'],
                'avoid_or_risk': [],
            },
            'confirmation_rules': ['Footfall/traffic data', 'Named contractor if any', 'Volume confirm'],
            'stale_after_hours': 48,
        },
        {
            'theme_id': 'banking_psu_nbfc',
            'display_name': 'Banking / PSU / NBFC',
            'keywords': ['banking', 'bank', 'psu', 'nbfc', 'credit', 'lending'],
            'trigger_keywords': ['bank recap', 'psu divestment', 'credit growth', 'rbi'],
            'direct_beneficiary_sectors': ['Banks', 'NBFCs', 'PSU financials'],
            'indirect_beneficiary_sectors': ['Insurance', 'Capital markets', 'Fintech'],
            'raw_material_beneficiaries': [],
            'risk_sectors': ['NPA cycle', 'Rate shock', 'Regulatory action'],
            'stocks': {
                'direct': ['SBIN', 'PNB', 'BANKBARODA', 'HDFCBANK', 'ICICIBANK'],
                'indirect': ['BAJFINANCE', 'CHOLAFIN', 'LICHSGFIN'],
                'raw_material': [],
                'avoid_or_risk': ['YESBANK'],
            },
            'confirmation_rules': ['Policy clarity', 'Credit growth trend', 'No blind entry'],
            'stale_after_hours': 24,
        },
        {
            'theme_id': 'it_digital_india',
            'display_name': 'IT / Digital India',
            'keywords': ['it', 'digital india', 'software', 'tech', 'data centre', 'cloud'],
            'trigger_keywords': ['digital india', 'it spending', 'data centre', 'ai policy'],
            'direct_beneficiary_sectors': ['IT services', 'SaaS', 'Data centres'],
            'indirect_beneficiary_sectors': ['Telecom', 'Electronics', 'Fintech'],
            'raw_material_beneficiaries': ['Hardware supply chain'],
            'risk_sectors': ['US client slowdown', 'Margin pressure'],
            'stocks': {
                'direct': ['TCS', 'INFY', 'HCLTECH', 'WIPRO', 'PERSISTENT'],
                'indirect': ['BHARTIARTL', 'TATAELXSI', 'COFORGE'],
                'raw_material': ['DIXON'],
                'avoid_or_risk': [],
            },
            'confirmation_rules': ['Deal wins', 'Sector breadth', 'Volume confirm'],
            'stale_after_hours': 48,
        },
        {
            'theme_id': 'oil_gas_energy',
            'display_name': 'Oil / Gas / Energy',
            'keywords': ['oil', 'gas', 'petroleum', 'refinery', 'lng', 'energy'],
            'trigger_keywords': ['fuel price', 'oil subsidy', 'gas pipeline', 'refinery expansion'],
            'direct_beneficiary_sectors': ['OMCs', 'Upstream', 'Refining'],
            'indirect_beneficiary_sectors': ['Logistics', 'Chemicals', 'Power'],
            'raw_material_beneficiaries': ['Crude linkage'],
            'risk_sectors': ['Crude volatility', 'Regulatory pricing'],
            'stocks': {
                'direct': ['RELIANCE', 'ONGC', 'IOC', 'BPCL', 'GAIL'],
                'indirect': ['PETRONET', 'IGL', 'MGL', 'HINDPETRO'],
                'raw_material': ['OIL'],
                'avoid_or_risk': [],
            },
            'confirmation_rules': ['Policy clarity', 'Margin trend', 'Sector support'],
            'stale_after_hours': 24,
        },
        {
            'theme_id': 'metals_mining',
            'display_name': 'Metals / Mining',
            'keywords': ['metal', 'mining', 'iron ore', 'aluminium', 'zinc', 'copper'],
            'trigger_keywords': ['mining auction', 'metal demand', 'commodity rally'],
            'direct_beneficiary_sectors': ['Mining', 'Metals', 'Smelting'],
            'indirect_beneficiary_sectors': ['Infra', 'Auto', 'Capital goods'],
            'raw_material_beneficiaries': ['Ore', 'Coal'],
            'risk_sectors': ['China demand', 'Global commodity shock'],
            'stocks': {
                'direct': ['TATASTEEL', 'JSWSTEEL', 'HINDALCO', 'VEDL', 'NMDC'],
                'indirect': ['SAIL', 'JINDALSTEL', 'HINDZINC', 'NATIONALUM'],
                'raw_material': ['COALINDIA', 'MOIL'],
                'avoid_or_risk': [],
            },
            'confirmation_rules': ['Price trend + volume', 'Demand headline clarity'],
            'stale_after_hours': 48,
        },
        {
            'theme_id': 'telecom_5g',
            'display_name': 'Telecom / 5G',
            'keywords': ['telecom', '5g', 'spectrum', 'broadband', 'mobile'],
            'trigger_keywords': ['5g rollout', 'spectrum auction', 'telecom capex'],
            'direct_beneficiary_sectors': ['Telecom operators', 'Tower cos', 'Network gear'],
            'indirect_beneficiary_sectors': ['Fiber', 'Data centres', 'Handsets'],
            'raw_material_beneficiaries': ['Electronics components'],
            'risk_sectors': ['ARPU pressure', 'Capex intensity'],
            'stocks': {
                'direct': ['BHARTIARTL', 'IDEA', 'INDUSTOWER', 'HFCL'],
                'indirect': ['TEJASNET', 'STLTECH', 'ITI', 'DIXON'],
                'raw_material': ['KAYNES'],
                'avoid_or_risk': ['IDEA'],
            },
            'confirmation_rules': ['Capex/spectrum clarity', 'ARPU trend', 'Volume confirm'],
            'stale_after_hours': 48,
        },
        {
            'theme_id': 'water_jal_jeevan',
            'display_name': 'Water / Jal Jeevan',
            'keywords': ['water', 'jal jeevan', 'jal', 'irrigation', 'pipeline', 'sanitation'],
            'trigger_keywords': ['jal jeevan mission', 'water project', 'irrigation scheme'],
            'direct_beneficiary_sectors': ['Water EPC', 'Pipes', 'Pumps', 'Treatment'],
            'indirect_beneficiary_sectors': ['Cement', 'Electricals', 'Rural infra'],
            'raw_material_beneficiaries': ['PVC', 'Steel pipes'],
            'risk_sectors': ['Execution delays', 'State-level funding'],
            'stocks': {
                'direct': ['L&T', 'JISLJALEQS', 'AQUA', 'FINPIPE', 'PRAJIND'],
                'indirect': ['POLYCAB', 'KEI', 'CROMPTON', 'KSB'],
                'raw_material': ['SUPREMEIND', 'APLAPOLLO'],
                'avoid_or_risk': [],
            },
            'confirmation_rules': ['Named state/project', 'Tender clarity', 'Volume confirm'],
            'stale_after_hours': 72,
        },
    ]
    return defs


def bootstrap_theme_baskets(*, force: bool = False) -> dict[str, Any]:
    """Create theme_baskets.json with 18 default baskets if missing."""
    if BASKETS_FILE.is_file() and not force:
        try:
            data = json.loads(BASKETS_FILE.read_text(encoding='utf-8'))
            if isinstance(data, dict) and data.get('baskets'):
                return data
        except (OSError, json.JSONDecodeError):
            pass

    baskets = _default_baskets()
    payload = {
        'stage': STAGE,
        'generated_at': _now_iso(),
        'baskets': baskets,
        'catalyst_cache': {},
    }
    atomic_write_json(BASKETS_FILE, payload)
    _log(f'bootstrapped {len(baskets)} default baskets')
    return payload


def load_theme_baskets() -> dict[str, Any]:
    data = bootstrap_theme_baskets()
    if not isinstance(data, dict):
        return {'baskets': _default_baskets(), 'catalyst_cache': {}}
    data.setdefault('baskets', _default_baskets())
    data.setdefault('catalyst_cache', {})
    return data


def get_basket_by_id(theme_id: str) -> Optional[dict[str, Any]]:
    resolved = resolve_theme_id(theme_id)
    if not resolved or resolved == 'budget':
        return None
    for basket in load_theme_baskets().get('baskets') or []:
        if isinstance(basket, dict) and basket.get('theme_id') == resolved:
            return basket
    return None


def resolve_theme_id(raw: str) -> Optional[str]:
    key = str(raw or '').strip().lower().replace('-', '_').replace(' ', '_')
    if not key:
        return None
    if key in THEME_ALIASES:
        return THEME_ALIASES[key]
    for basket in load_theme_baskets().get('baskets') or []:
        if not isinstance(basket, dict):
            continue
        tid = str(basket.get('theme_id') or '')
        if key == tid or key in tid:
            return tid
        display = str(basket.get('display_name') or '').lower()
        if key.replace('_', ' ') in display or key in display.replace('/', ' ').replace(' ', '_'):
            return tid
    return None


def _normalize_text(text: str) -> str:
    return re.sub(r'\s+', ' ', str(text or '').lower().strip())


def _extract_crore_amount(text: str) -> float:
    lower = _normalize_text(text)
    patterns = [
        r'₹\s*([\d,]+(?:\.\d+)?)\s*(?:lakh\s*)?crore',
        r'rs\.?\s*([\d,]+(?:\.\d+)?)\s*(?:lakh\s*)?crore',
        r'([\d,]+(?:\.\d+)?)\s*(?:lakh\s*)?crore',
    ]
    for pat in patterns:
        m = re.search(pat, lower)
        if m:
            try:
                val = float(m.group(1).replace(',', ''))
                if 'lakh crore' in lower:
                    val *= 100000
                return val
            except ValueError:
                pass
    return 0.0


COMPANY_ALIASES: dict[str, str] = {
    'l&t': 'LT',
    'larsen': 'LT',
    'larsen & toubro': 'LT',
    'ultratech': 'ULTRACEMCO',
    'tata steel': 'TATASTEEL',
    'jsw steel': 'JSWSTEEL',
    'adanient': 'ADANIENT',
    'irb infra': 'IRB',
}


def _find_named_companies(headline: str, basket: dict) -> list[str]:
    lower = _normalize_text(headline)
    found: list[str] = []
    for alias, ticker in COMPANY_ALIASES.items():
        if alias in lower:
            found.append(ticker)
    stocks = basket.get('stocks') or {}
    for bucket in ('direct', 'indirect', 'raw_material'):
        for ticker in stocks.get(bucket) or []:
            t = str(ticker).lower()
            if t and t in lower:
                found.append(str(ticker).upper())
    return list(dict.fromkeys(found))


def _match_themes_for_headline(headline: str, *, item: Optional[dict] = None) -> list[str]:
    lower = _normalize_text(headline)
    if item:
        desc = _normalize_text(str(item.get('description') or ''))
        lower = f'{lower} {desc}'
    matched: list[str] = []
    for basket in load_theme_baskets().get('baskets') or []:
        if not isinstance(basket, dict):
            continue
        tid = basket.get('theme_id')
        terms = (
            list(basket.get('keywords') or [])
            + list(basket.get('trigger_keywords') or [])
            + list(basket.get('direct_beneficiary_sectors') or [])
        )
        for term in terms:
            t = _normalize_text(term)
            if len(t) >= 3 and t in lower:
                matched.append(str(tid))
                break
    # Cross-theme links for known examples
    if any(w in lower for w in ('road project', 'highway project', 'road project')):
        for tid in ('infrastructure', 'roads_highways', 'cement_steel_paint'):
            if tid not in matched:
                matched.append(tid)
    if any(w in lower for w in ('ram mandir', 'tourism boost', 'pilgrimage', 'temple tourism')):
        for tid in ('tourism_temple_culture', 'infrastructure'):
            if tid not in matched:
                matched.append(tid)
    return matched


def score_theme_catalyst(
    headline: str,
    theme_id: str,
    *,
    item: Optional[dict] = None,
    seen_headlines: Optional[set[str]] = None,
) -> dict[str, Any]:
    """Compute Theme Catalyst Score components for a headline + theme."""
    basket = get_basket_by_id(theme_id) or {}
    lower = _normalize_text(headline)
    named = _find_named_companies(headline, basket)

    crore = _extract_crore_amount(headline)
    event_size_score = min(10.0, 3.0 + (crore / 5000.0) * 7.0) if crore else 2.0

    govt_terms = ('govt', 'government', 'ministry', 'cabinet', 'nhai', 'nh', 'rbi', 'budget', 'union')
    govt_authority_score = 8.0 if any(t in lower for t in govt_terms) else 2.0

    order_win = any(w in lower for w in ('wins', 'won', 'bags', 'awarded')) and any(
        w in lower for w in ('order', 'contract', 'project', 'tender')
    )
    named_company_score = 10.0 if named else (8.0 if order_win else (4.0 if any(
        s.lower() in lower for s in (basket.get('direct_beneficiary_sectors') or [])
    ) else 1.0))

    sector_terms = list(basket.get('keywords') or []) + list(basket.get('trigger_keywords') or [])
    sector_hits = sum(1 for t in sector_terms if _normalize_text(t) in lower)
    sector_specificity_score = min(10.0, 2.0 + sector_hits * 2.5)

    budget_amount_score = min(10.0, 2.0 + (crore / 10000.0) * 8.0) if crore else 1.0

    locations = ('delhi', 'mumbai', 'up', 'uttar pradesh', 'maharashtra', 'gujarat', 'karnataka', 'ayodhya')
    location_relevance_score = 6.0 if any(loc in lower for loc in locations) else 2.0

    order_terms = ('tender', 'order', 'project', 'contract', 'award', 'capex', 'allocation')
    order_tender_clarity_score = 8.0 if any(t in lower for t in order_terms) else 2.0

    market_confirmation_score = 3.0
    if item and (item.get('affected_stocks') or item.get('tickers')):
        market_confirmation_score = 5.0

    duplicate_penalty = 0.0
    norm = re.sub(r'[^a-z0-9]+', ' ', lower).strip()
    if seen_headlines is not None:
        if norm in seen_headlines:
            duplicate_penalty = 4.0
        else:
            seen_headlines.add(norm)

    clickbait_penalty = 0.0
    try:
        from backend.orchestration.alert_quality_filters import is_clickbait_headline
        if is_clickbait_headline(headline):
            clickbait_penalty = 5.0
    except Exception:
        if any(w in lower for w in ('shocking', 'you won', 'guaranteed', 'must buy')):
            clickbait_penalty = 5.0

    already_priced_in_penalty = 3.0 if any(
        w in lower for w in ('rally continues', 'already priced', 'hits record high', '52-week high')
    ) else 0.0

    raw_total = (
        event_size_score
        + govt_authority_score
        + named_company_score
        + sector_specificity_score
        + budget_amount_score
        + location_relevance_score
        + order_tender_clarity_score
        + market_confirmation_score
        - duplicate_penalty
        - clickbait_penalty
        - already_priced_in_penalty
    )
    impact_10 = max(1, min(10, int(round(raw_total / 5.0))))
    catalyst_score = max(0, min(100, int(round(raw_total * 2.0))))

    broad_policy = (
        not named
        and crore <= 0
        and order_tender_clarity_score < 5
        and sector_specificity_score < 5
    )
    action = 'watch only'
    if named and catalyst_score >= 60:
        action = 'watch for confirmation'
    elif catalyst_score >= 70 and order_tender_clarity_score >= 6:
        action = 'watch for confirmation'
    if broad_policy:
        action = 'watch only'

    why_parts = []
    if govt_authority_score >= 6:
        why_parts.append('govt/project signal')
    if crore:
        why_parts.append(f'₹{crore:,.0f} crore scale')
    if sector_specificity_score >= 5:
        why_parts.append('sector specific')
    if named:
        why_parts.append(f'named: {", ".join(named[:3])}')
    if order_tender_clarity_score >= 6:
        why_parts.append('order/tender clarity')
    if not why_parts:
        why_parts.append('broad policy headline')

    return {
        'theme_id': theme_id,
        'headline': headline[:240],
        'impact_10': impact_10,
        'catalyst_score': catalyst_score,
        'action': action,
        'why': ' + '.join(why_parts),
        'named_companies': named,
        'broad_policy': broad_policy,
        'components': {
            'event_size_score': event_size_score,
            'govt_authority_score': govt_authority_score,
            'named_company_score': named_company_score,
            'sector_specificity_score': sector_specificity_score,
            'budget_amount_score': budget_amount_score,
            'location_relevance_score': location_relevance_score,
            'order_tender_clarity_score': order_tender_clarity_score,
            'market_confirmation_score': market_confirmation_score,
            'duplicate_penalty': duplicate_penalty,
            'clickbait_penalty': clickbait_penalty,
            'already_priced_in_penalty': already_priced_in_penalty,
        },
        'matched_at': _now_iso(),
    }


def _append_catalyst_log(entry: dict[str, Any]) -> None:
    CATALYST_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CATALYST_LOG_FILE, 'a', encoding='utf-8') as fh:
        fh.write(json.dumps(entry, ensure_ascii=False, default=str) + '\n')


def _load_news_items() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for rel in ('news_feed.json', 'govt_intelligence.json'):
        path = get_data_path(rel)
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            continue
        if rel == 'news_feed.json':
            for row in data.get('articles') or []:
                if isinstance(row, dict) and row.get('title'):
                    items.append(row)
        else:
            for key in ('high_impact_items', 'medium_impact_items', 'items', 'analyzed_items'):
                rows = data.get(key)
                if isinstance(rows, list):
                    for row in rows:
                        if isinstance(row, dict) and row.get('title'):
                            items.append(row)
    return items


def match_headline_to_themes(headline: str, *, item: Optional[dict] = None) -> list[dict[str, Any]]:
    """Match a headline to themes with catalyst scores."""
    theme_ids = _match_themes_for_headline(headline, item=item)
    seen: set[str] = set()
    results = []
    for tid in theme_ids:
        scored = score_theme_catalyst(headline, tid, item=item, seen_headlines=seen)
        results.append(scored)
    results.sort(key=lambda r: r.get('catalyst_score', 0), reverse=True)
    return results


def refresh_theme_catalyst_cache(*, persist: bool = True) -> dict[str, Any]:
    """Scan news/govt feeds and rebuild per-theme catalyst cache."""
    items = _load_news_items()
    cache: dict[str, list[dict[str, Any]]] = {}
    total_matches = 0
    seen_global: set[str] = set()

    for item in items[:200]:
        headline = str(item.get('title') or '')
        if not headline:
            continue
        matches = match_headline_to_themes(headline, item=item)
        for match in matches:
            tid = match.get('theme_id')
            if not tid:
                continue
            norm = re.sub(r'[^a-z0-9]+', ' ', _normalize_text(headline)).strip()
            if norm in seen_global:
                match['components']['duplicate_penalty'] = max(
                    match['components'].get('duplicate_penalty', 0), 4.0
                )
            seen_global.add(norm)
            cache.setdefault(str(tid), []).append(match)
            if persist:
                _append_catalyst_log({
                    'stage': STAGE,
                    'theme_id': tid,
                    'headline': headline[:240],
                    'source': item.get('source'),
                    'impact_10': match.get('impact_10'),
                    'catalyst_score': match.get('catalyst_score'),
                    'action': match.get('action'),
                    'matched_at': _now_iso(),
                })
            total_matches += 1

    for tid, rows in cache.items():
        rows.sort(key=lambda r: r.get('catalyst_score', 0), reverse=True)
        cache[tid] = rows[:12]

    payload = load_theme_baskets()
    payload['catalyst_cache'] = cache
    payload['cache_refreshed_at'] = _now_iso()
    payload['stage'] = STAGE
    if persist:
        atomic_write_json(BASKETS_FILE, payload)

    _log(f'refreshed catalyst cache — themes={len(cache)} matches={total_matches}')
    return {
        'ok': True,
        'stage': STAGE,
        'themes_matched': len(cache),
        'total_matches': total_matches,
        'refreshed_at': payload['cache_refreshed_at'],
        'catalyst_cache': cache,
    }


def get_theme_catalysts(theme_id: str, *, limit: int = 5) -> list[dict[str, Any]]:
    resolved = resolve_theme_id(theme_id)
    if not resolved or resolved == 'budget':
        return []
    data = load_theme_baskets()
    cache = data.get('catalyst_cache') or {}
    rows = cache.get(resolved) or []
    if not rows:
        refresh_theme_catalyst_cache(persist=True)
        rows = (load_theme_baskets().get('catalyst_cache') or {}).get(resolved) or []
    return rows[:limit]


def _basket_is_stale(basket: dict) -> bool:
    data = load_theme_baskets()
    refreshed = data.get('cache_refreshed_at') or data.get('generated_at')
    if not refreshed:
        return True
    try:
        ts = datetime.fromisoformat(str(refreshed))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=IST)
        age_h = (datetime.now(IST) - ts.astimezone(IST)).total_seconds() / 3600.0
        stale_after = float(basket.get('stale_after_hours') or 48)
        return age_h > stale_after
    except (TypeError, ValueError):
        return True


def rank_theme_stocks(theme_id: str, *, limit: int = 5) -> list[dict[str, Any]]:
    basket = get_basket_by_id(theme_id)
    if not basket:
        return []
    catalysts = get_theme_catalysts(theme_id, limit=3)
    top_catalyst_score = max((c.get('catalyst_score') or 0) for c in catalysts) if catalysts else 35
    named_in_news = set()
    for c in catalysts:
        for n in c.get('named_companies') or []:
            named_in_news.add(str(n).upper())

    ranked: list[dict[str, Any]] = []
    stocks = basket.get('stocks') or {}
    weights = {'direct': 20, 'indirect': 10, 'raw_material': 5}
    labels = {
        'direct': 'Direct beneficiary',
        'indirect': 'Indirect beneficiary',
        'raw_material': 'Raw material beneficiary',
    }
    for bucket, bonus in weights.items():
        for ticker in stocks.get(bucket) or []:
            t = str(ticker).upper()
            score = top_catalyst_score + bonus
            if t in named_in_news:
                score += 15
            action = 'watch for confirmation' if score >= 65 else 'watch only'
            ranked.append({
                'ticker': t,
                'bucket': bucket,
                'label': labels[bucket],
                'score': min(100, int(score)),
                'action': action,
                'confirm': 'Confirm with price strength + volume + sector support',
            })
    ranked.sort(key=lambda r: r.get('score', 0), reverse=True)
    return ranked[:limit]


def add_stock_to_basket(theme_id: str, ticker: str, bucket: str) -> dict[str, Any]:
    resolved = resolve_theme_id(theme_id)
    bucket_norm = str(bucket or '').strip().lower()
    bucket_map = {
        'direct': 'direct',
        'indirect': 'indirect',
        'raw': 'raw_material',
        'raw_material': 'raw_material',
        'risk': 'avoid_or_risk',
        'avoid': 'avoid_or_risk',
        'avoid_or_risk': 'avoid_or_risk',
    }
    target_bucket = bucket_map.get(bucket_norm)
    if not resolved or not target_bucket:
        return {'ok': False, 'error': 'invalid theme or bucket'}
    t = str(ticker or '').strip().upper()
    if not t:
        return {'ok': False, 'error': 'ticker required'}

    data = load_theme_baskets()
    for basket in data.get('baskets') or []:
        if basket.get('theme_id') != resolved:
            continue
        stocks = basket.setdefault('stocks', {})
        for key in ('direct', 'indirect', 'raw_material', 'avoid_or_risk'):
            lst = stocks.setdefault(key, [])
            if t in lst:
                lst.remove(t)
        stocks.setdefault(target_bucket, []).append(t)
        atomic_write_json(BASKETS_FILE, data)
        return {'ok': True, 'theme_id': resolved, 'ticker': t, 'bucket': target_bucket}
    return {'ok': False, 'error': 'theme not found'}


def remove_stock_from_basket(theme_id: str, ticker: str) -> dict[str, Any]:
    resolved = resolve_theme_id(theme_id)
    t = str(ticker or '').strip().upper()
    if not resolved or not t:
        return {'ok': False, 'error': 'invalid theme or ticker'}
    data = load_theme_baskets()
    removed = False
    for basket in data.get('baskets') or []:
        if basket.get('theme_id') != resolved:
            continue
        stocks = basket.get('stocks') or {}
        for key in ('direct', 'indirect', 'raw_material', 'avoid_or_risk'):
            lst = stocks.get(key) or []
            if t in lst:
                lst.remove(t)
                removed = True
        if removed:
            atomic_write_json(BASKETS_FILE, data)
            return {'ok': True, 'theme_id': resolved, 'ticker': t}
    return {'ok': False, 'error': 'ticker not in basket'}


def list_all_baskets() -> list[dict[str, str]]:
    return [
        {
            'theme_id': b.get('theme_id', ''),
            'display_name': b.get('display_name', ''),
        }
        for b in load_theme_baskets().get('baskets') or []
        if isinstance(b, dict)
    ]


def format_theme_list_telegram() -> str:
    lines = ['<b>🧺 AstraEdge Theme Baskets</b>', '']
    for row in list_all_baskets():
        lines.append(f"• {row.get('display_name') or row.get('theme_id')}")
    lines.extend([
        '',
        '<i>Research only — watch/confirm, no blind entry.</i>',
        'Use <code>/theme infra</code> for basket details.',
    ])
    return '\n'.join(lines)


def format_theme_overview_telegram() -> str:
    return (
        '<b>🧺 AstraEdge Theme Baskets</b>\n\n'
        'Thematic intelligence mapping news/govt events to sectors and stocks.\n\n'
        '<b>Commands:</b>\n'
        '• <code>/theme list</code> — all baskets\n'
        '• <code>/theme infra</code> — basket details\n'
        '• <code>/theme news infra</code> — matched catalysts\n'
        '• <code>/theme scan infra</code> — ranked watchlist\n'
        '• <code>/theme budget</code> — budget-sensitive themes\n'
        '• <code>/theme refresh</code> — rebuild catalyst cache\n\n'
        '<i>Watch only until price + volume confirms. No blind entry.</i>'
    )


def format_theme_budget_telegram() -> str:
    lines = [
        '<b>🏛️ Budget Theme Monitor</b>',
        '',
        'Top themes likely affected by budget/govt spending:',
    ]
    names = []
    for tid in BUDGET_THEME_IDS:
        basket = get_basket_by_id(tid)
        if basket:
            names.append(str(basket.get('display_name') or tid))
    lines.append(', '.join(names) + '.')
    lines.extend([
        '',
        '<i>Watch only — confirm named orders and sector breadth before acting.</i>',
        'No blind entry. Research only until fresh confirmation.',
    ])
    return '\n'.join(lines)


def format_theme_detail_telegram(theme_id: str) -> str:
    basket = get_basket_by_id(theme_id)
    if not basket:
        return f'Unknown theme: <code>{theme_id}</code>. Try <code>/theme list</code>.'

    stale = _basket_is_stale(basket)
    display = basket.get('display_name') or theme_id
    emoji_map = {
        'infrastructure': '🏗️',
        'roads_highways': '🛣️',
        'railways': '🚆',
        'defence': '🛡️',
        'tourism_temple_culture': '🛕',
    }
    emoji = emoji_map.get(str(basket.get('theme_id')), '🧺')

    related = []
    if basket.get('theme_id') == 'infrastructure':
        related = ['Infrastructure', 'Roads', 'Cement', 'Steel', 'Paint']
    else:
        related = [display]
        related.extend((basket.get('indirect_beneficiary_sectors') or [])[:3])

    lines = [f'<b>{emoji} AstraEdge Theme Basket — {display}</b>', '']
    if stale:
        lines.append('<i>Research only — catalyst cache stale. Run /theme refresh.</i>')
        lines.append('')

    lines.append('<b>Theme impact:</b>')
    lines.append(' · '.join(related[:6]))

    lines.extend(['', '<b>Direct beneficiaries:</b>'])
    for sector in (basket.get('direct_beneficiary_sectors') or [])[:5]:
        lines.append(f'• {sector}')
    for t in (basket.get('stocks') or {}).get('direct') or []:
        lines.append(f'• {t}')

    lines.extend(['', '<b>Indirect beneficiaries:</b>'])
    for sector in (basket.get('indirect_beneficiary_sectors') or [])[:5]:
        lines.append(f'• {sector}')

    catalysts = get_theme_catalysts(str(basket.get('theme_id')), limit=3)
    lines.extend(['', '<b>Latest catalysts:</b>'])
    if catalysts:
        for idx, cat in enumerate(catalysts[:3], 1):
            lines.append(
                f"{idx}. {cat.get('headline', '—')[:100]} · impact {cat.get('impact_10', '?')}/10"
            )
            lines.append(f"   Why: {cat.get('why', '—')}")
    else:
        lines.append('• No fresh catalysts — research only until /theme refresh.')

    ranked = rank_theme_stocks(str(basket.get('theme_id')), limit=3)
    lines.extend(['', '<b>Top watch:</b>'])
    if ranked:
        for idx, row in enumerate(ranked[:3], 1):
            lines.append(
                f"{idx}. {row.get('ticker')} — {row.get('label')} · Score {row.get('score')}"
            )
            lines.append(f"   {row.get('confirm')}")
            lines.append(f"   {row.get('action', 'watch only').title()}")
    else:
        lines.append('• No ranked stocks — research only.')

    lines.extend([
        '',
        '<b>Risk:</b>',
        'Broad theme may already be priced in.',
        'Prefer named/order-linked companies over generic sector names.',
        '',
        '<i>Watch only — confirm with price strength + volume. No blind entry.</i>',
    ])
    text = '\n'.join(lines)
    for forbidden in FORBIDDEN_WORDS:
        if forbidden in text.lower():
            text = text.replace(forbidden, 'watch')
    return text


def format_theme_news_telegram(theme_id: str) -> str:
    basket = get_basket_by_id(theme_id)
    if not basket:
        return f'Unknown theme: <code>{theme_id}</code>.'
    display = basket.get('display_name') or theme_id
    catalysts = get_theme_catalysts(theme_id, limit=8)
    lines = [f'<b>📰 Theme News — {display}</b>', '']
    if not catalysts:
        lines.append('No matched catalysts. Run <code>/theme refresh</code> for fresh scan.')
        lines.append('<i>Research only — watch for confirmation.</i>')
        return '\n'.join(lines)
    for idx, cat in enumerate(catalysts, 1):
        lines.append(f"{idx}. {cat.get('headline', '—')[:120]}")
        lines.append(
            f"   Impact {cat.get('impact_10', '?')}/10 · "
            f"Score {cat.get('catalyst_score', '?')} · {cat.get('action', 'watch only')}"
        )
        lines.append(f"   Why: {cat.get('why', '—')}")
    lines.extend(['', '<i>Watch only — no blind entry until price + volume confirms.</i>'])
    return '\n'.join(lines)


def format_theme_scan_telegram(theme_id: str) -> str:
    basket = get_basket_by_id(theme_id)
    if not basket:
        return f'Unknown theme: <code>{theme_id}</code>.'
    display = basket.get('display_name') or theme_id
    ranked = rank_theme_stocks(theme_id, limit=8)
    lines = [f'<b>🔎 Theme Scan — {display}</b>', '']
    if not ranked:
        lines.append('No stocks ranked — research only.')
        return '\n'.join(lines)
    for idx, row in enumerate(ranked, 1):
        lines.append(
            f"{idx}. {row.get('ticker')} — {row.get('label')} · Score {row.get('score')}"
        )
        lines.append(f"   {row.get('confirm')}")
        lines.append(f"   {row.get('action', 'watch only').title()}")
    lines.extend(['', '<i>Watch only — confirm after price strength + volume.</i>'])
    return '\n'.join(lines)


def handle_theme_command(args: str) -> str:
    """Dispatch /theme subcommands."""
    raw = str(args or '').strip()
    if not raw:
        return format_theme_overview_telegram()

    parts = raw.split()
    sub = parts[0].lower()

    if sub == 'list':
        return format_theme_list_telegram()
    if sub == 'budget':
        return format_theme_budget_telegram()
    if sub == 'refresh':
        result = refresh_theme_catalyst_cache(persist=True)
        return (
            '<b>🔄 Theme catalyst refresh</b>\n'
            f"Themes matched: {result.get('themes_matched', 0)}\n"
            f"Total matches: {result.get('total_matches', 0)}\n"
            f"Refreshed: {result.get('refreshed_at', '—')}\n"
            '<i>Research only — manual refresh, no automatic alerts.</i>'
        )
    if sub == 'add' and len(parts) >= 4:
        result = add_stock_to_basket(parts[1], parts[2], parts[3])
        if result.get('ok'):
            return (
                f"Added <code>{result['ticker']}</code> to "
                f"<code>{result['theme_id']}</code> ({result['bucket']})."
            )
        return f"Add failed: {result.get('error', 'unknown')}"
    if sub == 'remove' and len(parts) >= 3:
        result = remove_stock_from_basket(parts[1], parts[2])
        if result.get('ok'):
            return f"Removed <code>{result['ticker']}</code> from <code>{result['theme_id']}</code>."
        return f"Remove failed: {result.get('error', 'unknown')}"

    if sub == 'news' and len(parts) >= 2:
        theme_key = ' '.join(parts[1:])
        resolved = resolve_theme_id(theme_key)
        if not resolved:
            return f'Unknown theme: <code>{theme_key}</code>.'
        return format_theme_news_telegram(resolved)

    if sub == 'scan' and len(parts) >= 2:
        theme_key = ' '.join(parts[1:])
        resolved = resolve_theme_id(theme_key)
        if not resolved:
            return f'Unknown theme: <code>{theme_key}</code>.'
        return format_theme_scan_telegram(resolved)

    theme_key = ' '.join(parts)
    resolved = resolve_theme_id(theme_key)
    if resolved == 'budget':
        return format_theme_budget_telegram()
    if not resolved:
        return f'Unknown theme: <code>{theme_key}</code>. Try <code>/theme list</code>.'
    return format_theme_detail_telegram(resolved)
