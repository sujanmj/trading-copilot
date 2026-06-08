"""
AstraEdge Theme Baskets — thematic intelligence engine (Stage 47F).

Maps news/govt/budget headlines to theme baskets, sectors, and beneficiary stocks.
User-facing label: Theme Wishlist. Research-only — watch/confirm, never buy now or guaranteed.
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
STAGE = '47F'
THEME_SCHEMA_VERSION = '47F'

# Legacy broad baskets hidden from grouped/category lists when split baskets exist.
HIDDEN_WHEN_SPLIT: dict[str, tuple[str, ...]] = {
    'ports_logistics': ('ports_shipping', 'logistics_warehousing'),
    'banking_psu_nbfc': ('psu_banks', 'private_banks', 'nbfc', 'insurance', 'amc_brokers'),
}
DEPRECATED_THEME_IDS: frozenset[str] = frozenset({
    'ports_logistics',
    'banking_psu_nbfc',
    'defence',
})
DEPRECATED_STOCK_MERGE_TARGETS: dict[str, str] = {
    'ports_logistics': 'ports_shipping',
    'banking_psu_nbfc': 'psu_banks',
    'defence': 'defence_aerospace',
}
WISHLIST_TITLE = 'AstraEdge Theme Wishlist'
NO_CATALYST_MESSAGE = 'No strong fresh catalyst found. Research basket only.'

SKIP_KEYWORDS: tuple[str, ...] = (
    'buyback',
    'dividend',
    'ex-date',
    'ex-record',
    'ex date',
    'ex record',
    'f&o',
    'f & o',
    'futures open interest',
    'stake sale',
    'ofs',
    'block deal',
    'currency defence',
    'rupee defence',
    'analyst says',
    'flashing bullish signals',
    'market crash',
    'selloff',
    'sell-off',
)

THEME_ANCHORS: dict[str, list[str]] = {
    'infrastructure': [
        'infrastructure',
        'infra project',
        'smart city',
        'metro project',
        'bridge',
        'tunnel',
        'construction capex',
        'nhai project',
        'epc contract',
        'civil engineering',
        'urban development',
    ],
    'roads_highways': [
        'road project',
        'highway project',
        'expressway',
        'bharatmala',
        'nhai',
        'toll road',
        'national highway',
        'nh-',
        'nh ',
    ],
    'railways_metro': [
        'railway',
        'rail project',
        'railways',
        'locomotive',
        'vande bharat',
        'railyard',
        'metro rail',
        'rolling stock',
        'signalling',
    ],
    'defence_aerospace': [
        'defence order',
        'defense order',
        'military',
        'army',
        'navy',
        'air force',
        'ordnance',
        'aerospace',
        'shipbuilding',
        'make in india defence',
        'defence budget',
        'defence contract',
        'defence tender',
    ],
    'tourism_temple_culture': [
        'tourism',
        'temple',
        'pilgrimage',
        'ram mandir',
        'heritage',
        'ayodhya',
        'travel demand',
        'hotel',
        'hospitality',
        'cultural corridor',
    ],
    'budget': [
        'union budget',
        'budget allocation',
        'budget capex',
        'interim budget',
        'fiscal deficit',
        'budget announcement',
    ],
}
BASKETS_FILE = get_data_path('theme_baskets.json')
CATALYST_LOG_FILE = get_data_path('theme_catalyst_log.jsonl')

FORBIDDEN_WORDS = ('buy now', 'guaranteed', 'invest now')
BUDGET_THEME_IDS = (
    'infrastructure',
    'defence_aerospace',
    'railways_metro',
    'power_grid_transmission',
    'agriculture_fertilizer',
    'housing_real_estate',
    'banking_psu_nbfc',
    'renewable_energy',
    'pli_manufacturing',
)

LEGACY_THEME_ID_MAP: dict[str, str] = {
    'railways': 'railways_metro',
    'defence': 'defence_aerospace',
    'defense': 'defence_aerospace',
    'ports_logistics': 'ports_shipping',
}

THEME_CATEGORIES: dict[str, list[str]] = {
    'Government/Budget': [
        'infrastructure', 'defence_aerospace', 'water_jal_jeevan', 'pli_manufacturing',
        'agriculture_fertilizer', 'housing_real_estate', 'renewable_energy',
        'power_grid_transmission', 'semiconductors_electronics',
    ],
    'Transport/Logistics': [
        'roads_highways', 'railways_metro', 'aviation', 'ports_shipping',
        'logistics_warehousing', 'auto_ev_batteries',
    ],
    'Digital/Communication': [
        'telecom_5g', 'it_digital_india', 'data_center_ai',
    ],
    'Finance': [
        'psu_banks', 'private_banks', 'nbfc', 'insurance', 'amc_brokers',
    ],
    'Commodities/Materials': [
        'cement_steel_paint', 'metals_mining', 'chemicals', 'sugar_ethanol', 'oil_gas_energy',
    ],
    'Consumer/India Growth': [
        'fmcg', 'retail', 'textiles', 'media_entertainment', 'tourism_temple_culture',
    ],
    'Healthcare': [
        'pharma', 'hospitals', 'diagnostics',
    ],
    'Market Risk': [
        'rbi_rates', 'currency_import_export', 'crude_sensitive', 'war_geopolitics',
    ],
}

CATEGORY_ALIASES: dict[str, str] = {
    'budget': 'Government/Budget',
    'govt': 'Government/Budget',
    'government': 'Government/Budget',
    'transport': 'Transport/Logistics',
    'logistics': 'Transport/Logistics',
    'digital': 'Digital/Communication',
    'communication': 'Digital/Communication',
    'finance': 'Finance',
    'bank': 'Finance',
    'banks': 'Finance',
    'commodities': 'Commodities/Materials',
    'materials': 'Commodities/Materials',
    'consumer': 'Consumer/India Growth',
    'healthcare': 'Healthcare',
    'health': 'Healthcare',
    'risk': 'Market Risk',
    'market_risk': 'Market Risk',
}

THEME_ALIASES: dict[str, str] = {
    'infra': 'infrastructure',
    'infrastructure': 'infrastructure',
    'roads': 'roads_highways',
    'road': 'roads_highways',
    'highways': 'roads_highways',
    'highway': 'roads_highways',
    'railway': 'railways_metro',
    'railways': 'railways_metro',
    'rail': 'railways_metro',
    'metro': 'railways_metro',
    'defence': 'defence_aerospace',
    'defense': 'defence_aerospace',
    'aerospace': 'defence_aerospace',
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
    'ports': 'ports_shipping',
    'shipping': 'ports_shipping',
    'logistics': 'logistics_warehousing',
    'warehousing': 'logistics_warehousing',
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
    'psu': 'psu_banks',
    'nbfc': 'nbfc',
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


def _canonical_theme_id(theme_id: str) -> str:
    resolved = resolve_theme_id(theme_id)
    if resolved and resolved != 'budget' and not resolved.startswith('__category_'):
        return resolved
    key = str(theme_id or '').strip().lower()
    return LEGACY_THEME_ID_MAP.get(key, key)


def _basket_skeleton(
    *,
    theme_id: str,
    display_name: str,
    category: str,
    aliases: list[str],
    keywords: list[str],
    trigger_keywords: list[str],
    direct_sectors: list[str],
    indirect_sectors: list[str],
    raw_material: list[str],
    risk_sectors: list[str],
    stocks_direct: list[str],
    stocks_indirect: list[str],
    stocks_raw: list[str],
    stocks_risk: list[str] | None = None,
    confirmation_rules: list[str],
    stale_after_hours: int = 48,
) -> dict[str, Any]:
    return {
        'theme_id': theme_id,
        'display_name': display_name,
        'category': category,
        'aliases': aliases,
        'keywords': keywords,
        'trigger_keywords': trigger_keywords,
        'direct_beneficiary_sectors': direct_sectors,
        'indirect_beneficiary_sectors': indirect_sectors,
        'raw_material_beneficiaries': raw_material,
        'risk_sectors': risk_sectors,
        'stocks': {
            'direct': stocks_direct,
            'indirect': stocks_indirect,
            'raw_material': stocks_raw,
            'avoid_or_risk': stocks_risk or [],
        },
        'confirmation_rules': confirmation_rules,
        'stale_after_hours': stale_after_hours,
    }


def _default_baskets() -> list[dict[str, Any]]:
    """Bootstrap core theme baskets."""
    defs = [
        _basket_skeleton(
            theme_id='infrastructure',
            display_name='Infrastructure',
            category='Government/Budget',
            aliases=['infra', 'infrastructure'],
            keywords=['infrastructure', 'infra', 'construction', 'epc', 'project', 'capex'],
            trigger_keywords=['road', 'highway', 'metro', 'bridge', 'tunnel', 'smart city'],
            direct_sectors=['EPC contractors', 'Construction', 'Civil engineering'],
            indirect_sectors=['Cement', 'Steel', 'Paint', 'Pipes', 'Cables', 'Logistics'],
            raw_material=['Cement', 'Steel', 'Aggregates'],
            risk_sectors=['Over-leveraged infra', 'Delayed receivables'],
            stocks_direct=['LT', 'ADANIENT', 'IRB', 'PNCINFRA', 'KNR'],
            stocks_indirect=['ULTRACEMCO', 'ACC', 'TATASTEEL', 'ASIANPAINT', 'POLYCAB'],
            stocks_raw=['SHREECEM', 'RAMCOCEM', 'SAIL'],
            confirmation_rules=['Price strength + volume', 'Sector support', 'Named order/tender'],
        ),
        _basket_skeleton(
            theme_id='roads_highways',
            display_name='Roads / Highways',
            category='Transport/Logistics',
            aliases=['roads', 'road', 'highways', 'highway'],
            keywords=['road', 'highway', 'nh', 'expressway', 'bharatmala', 'toll'],
            trigger_keywords=['road project', 'highway project', 'expressway', 'nhai'],
            direct_sectors=['Road EPC', 'Highway contractors', 'Toll operators'],
            indirect_sectors=['Cement', 'Steel', 'Bitumen', 'Equipment'],
            raw_material=['Cement', 'Steel', 'Bitumen'],
            risk_sectors=['Land acquisition delays', 'Margin compression'],
            stocks_direct=['IRB', 'PNCINFRA', 'KNR', 'GRINFRA', 'HGINFRA'],
            stocks_indirect=['ULTRACEMCO', 'ACC', 'DALBHARAT', 'TATASTEEL'],
            stocks_raw=['SHREECEM', 'RAMCOCEM'],
            confirmation_rules=['Order win confirmation', 'Volume breakout', 'Sector breadth'],
        ),
        _basket_skeleton(
            theme_id='railways_metro',
            display_name='Railways / Metro',
            category='Transport/Logistics',
            aliases=['railway', 'railways', 'rail', 'metro'],
            keywords=['railway', 'rail', 'rlys', 'train', 'locomotive', 'vande bharat', 'metro'],
            trigger_keywords=['rail project', 'railway capex', 'railyard', 'metro rail'],
            direct_sectors=['Rail EPC', 'Rolling stock', 'Signalling'],
            indirect_sectors=['Steel', 'Electricals', 'Cables', 'Logistics'],
            raw_material=['Steel', 'Aluminium'],
            risk_sectors=['Execution delays', 'PSU order timing'],
            stocks_direct=['TITAGARH', 'TEXRAIL', 'IRCON', 'RVNL', 'RAILTEL'],
            stocks_indirect=['TATASTEEL', 'POLYCAB', 'KEI', 'CONCOR'],
            stocks_raw=['SAIL', 'JINDALSTEL'],
            confirmation_rules=['Rail order/tender clarity', 'Price + volume confirm'],
        ),
        _basket_skeleton(
            theme_id='defence_aerospace',
            display_name='Defence / Aerospace',
            category='Government/Budget',
            aliases=['defence', 'defense', 'aerospace'],
            keywords=['defence', 'defense', 'military', 'army', 'navy', 'air force', 'ordnance'],
            trigger_keywords=['defence order', 'defence budget', 'make in india defence'],
            direct_sectors=['Defence OEM', 'Aerospace', 'Shipbuilding'],
            indirect_sectors=['Electronics', 'Metals', 'Precision engineering'],
            raw_material=['Specialty metals', 'Electronics components'],
            risk_sectors=['Export dependency', 'Long gestation'],
            stocks_direct=['HAL', 'BEL', 'BEML', 'COCHINSHIP', 'MAZDOCK'],
            stocks_indirect=['MTARTECH', 'DATAPATTNS', 'ASTRAMICRO'],
            stocks_raw=['HINDZINC', 'NATIONALUM'],
            confirmation_rules=['Named contract/order', 'Budget allocation clarity'],
            stale_after_hours=72,
        ),
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
    extras = _additional_baskets()
    by_id = {b['theme_id']: b for b in defs if isinstance(b, dict) and b.get('theme_id')}
    for basket in extras:
        by_id[basket['theme_id']] = basket
    return [
        _normalize_basket(b)
        for b in by_id.values()
        if str(b.get('theme_id') or '') not in DEPRECATED_THEME_IDS
    ]


def _category_for_theme_id(theme_id: str) -> str:
    for category, ids in THEME_CATEGORIES.items():
        if theme_id in ids:
            return category
    return 'Government/Budget'


def _normalize_basket(basket: dict[str, Any]) -> dict[str, Any]:
    tid = str(basket.get('theme_id') or '')
    if tid in LEGACY_THEME_ID_MAP:
        basket = dict(basket)
        basket['theme_id'] = LEGACY_THEME_ID_MAP[tid]
        tid = basket['theme_id']
    basket.setdefault('category', _category_for_theme_id(tid))
    basket.setdefault('aliases', [])
    if not basket.get('aliases'):
        for alias, resolved in THEME_ALIASES.items():
            if resolved == tid and not alias.startswith('__'):
                basket['aliases'].append(alias)
    return basket


def _additional_baskets() -> list[dict[str, Any]]:
    """Stage 47C expanded sector baskets."""
    return [
        _basket_skeleton(
            theme_id='aviation', display_name='Aviation', category='Transport/Logistics',
            aliases=['aviation', 'airline', 'airlines', 'airport'],
            keywords=['aviation', 'airline', 'airport', 'udan', 'aircraft'],
            trigger_keywords=['aviation policy', 'airport expansion', 'udan scheme'],
            direct_sectors=['Airlines', 'Airport operators', 'MRO'],
            indirect_sectors=['Tourism', 'Fuel', 'Ground handling'],
            raw_material=['ATF', 'Aircraft parts'],
            risk_sectors=['Fuel cost', 'Regulatory fare caps'],
            stocks_direct=['INDIGO', 'SPICEJET', 'GMRINFRA', 'ADANIENT'],
            stocks_indirect=['IRCTC', 'IHCL', 'BPCL'],
            stocks_raw=['IOC'],
            confirmation_rules=['Traffic recovery', 'Policy clarity', 'Volume confirm'],
        ),
        _basket_skeleton(
            theme_id='ports_shipping', display_name='Ports / Shipping', category='Transport/Logistics',
            aliases=['ports', 'shipping', 'port'],
            keywords=['port', 'shipping', 'container', 'cargo', 'maritime'],
            trigger_keywords=['port expansion', 'container traffic', 'shipping corridor'],
            direct_sectors=['Port operators', 'Shipping lines'],
            indirect_sectors=['Logistics', 'Road/rail connectivity'],
            raw_material=['Fuel', 'Equipment'],
            risk_sectors=['Global trade slowdown', 'Freight volatility'],
            stocks_direct=['ADANIPORTS', 'SCI', 'GESHIP'],
            stocks_indirect=['CONCOR', 'TCIEXP'],
            stocks_raw=['IOC'],
            confirmation_rules=['Cargo volume trend', 'Named port project'],
        ),
        _basket_skeleton(
            theme_id='logistics_warehousing', display_name='Logistics / Warehousing',
            category='Transport/Logistics',
            aliases=['logistics', 'warehousing', 'warehouse', 'cold chain'],
            keywords=['logistics', 'warehousing', 'supply chain', 'cold chain', '3pl'],
            trigger_keywords=['logistics park', 'warehouse demand', 'cold chain expansion'],
            direct_sectors=['3PL', 'Warehousing', 'Express logistics'],
            indirect_sectors=['E-commerce', 'Road transport', 'Packaging'],
            raw_material=['Fuel', 'Real estate'],
            risk_sectors=['Margin pressure', 'Competition'],
            stocks_direct=['BLUEDART', 'TCIEXP', 'MAHLOG', 'GATI'],
            stocks_indirect=['CONCOR', 'DELHIVERY'],
            stocks_raw=['IOC'],
            confirmation_rules=['Volume growth', 'Named contract', 'Sector breadth'],
        ),
        _basket_skeleton(
            theme_id='auto_ev_batteries', display_name='Auto / EV / Batteries',
            category='Transport/Logistics',
            aliases=['auto', 'ev', 'electric vehicle', 'battery'],
            keywords=['auto', 'ev', 'electric vehicle', 'battery', 'fame', 'pli auto'],
            trigger_keywords=['ev policy', 'battery plant', 'auto pli', 'fame scheme'],
            direct_sectors=['Auto OEM', 'EV', 'Battery cell'],
            indirect_sectors=['Auto ancillaries', 'Metals', 'Electronics'],
            raw_material=['Lithium', 'Copper', 'Aluminium'],
            risk_sectors=['Demand slowdown', 'Subsidy changes'],
            stocks_direct=['TATAMOTORS', 'M&M', 'MARUTI', 'EXIDE', 'AMARAJABAT'],
            stocks_indirect=['BOSCHLTD', 'MOTHERSON', 'HINDALCO'],
            stocks_raw=['HINDCOPPER'],
            confirmation_rules=['Volume trend', 'Policy clarity', 'Named order'],
        ),
        _basket_skeleton(
            theme_id='data_center_ai', display_name='Data Center / AI Infra',
            category='Digital/Communication',
            aliases=['data center', 'datacenter', 'ai infra', 'cloud infra'],
            keywords=['data center', 'data centre', 'ai infra', 'cloud', 'hyperscale'],
            trigger_keywords=['data centre investment', 'ai cloud capex', 'hyperscale facility'],
            direct_sectors=['Data centres', 'Cloud infra', 'Colocation'],
            indirect_sectors=['Power', 'Cooling', 'Networking'],
            raw_material=['Copper', 'Electronics'],
            risk_sectors=['Capex intensity', 'Power availability'],
            stocks_direct=['NTTDATA', 'BHARTIARTL', 'RELIANCE', 'TCS'],
            stocks_indirect=['POLYCAB', 'KEI', 'ABB', 'SIEMENS'],
            stocks_raw=['HINDCOPPER'],
            confirmation_rules=['Named project', 'Capex clarity', 'Volume confirm'],
        ),
        _basket_skeleton(
            theme_id='psu_banks', display_name='PSU Banks', category='Finance',
            aliases=['psu bank', 'psu banks', 'public sector bank'],
            keywords=['psu bank', 'public sector bank', 'sbi', 'pnb', 'bank recap'],
            trigger_keywords=['psu bank recap', 'psu divestment', 'credit growth'],
            direct_sectors=['PSU banks'],
            indirect_sectors=['NBFC', 'Insurance', 'Capital markets'],
            raw_material=[],
            risk_sectors=['NPA cycle', 'Rate shock'],
            stocks_direct=['SBIN', 'PNB', 'BANKBARODA', 'CANBK', 'UNIONBANK'],
            stocks_indirect=['LICHSGFIN', 'HUDCO'],
            stocks_raw=[],
            confirmation_rules=['Policy clarity', 'Credit growth trend'],
            stale_after_hours=24,
        ),
        _basket_skeleton(
            theme_id='private_banks', display_name='Private Banks', category='Finance',
            aliases=['private bank', 'private banks', 'hdfc bank', 'icici'],
            keywords=['private bank', 'hdfc bank', 'icici', 'kotak', 'axis bank'],
            trigger_keywords=['private bank earnings', 'credit growth', 'retail loan'],
            direct_sectors=['Private banks'],
            indirect_sectors=['Insurance', 'Wealth', 'Fintech'],
            raw_material=[],
            risk_sectors=['Asset quality', 'Rate shock'],
            stocks_direct=['HDFCBANK', 'ICICIBANK', 'KOTAKBANK', 'AXISBANK', 'INDUSINDBK'],
            stocks_indirect=['BAJFINANCE', 'HDFCLIFE'],
            stocks_raw=[],
            confirmation_rules=['Credit growth', 'Asset quality trend'],
            stale_after_hours=24,
        ),
        _basket_skeleton(
            theme_id='nbfc', display_name='NBFC', category='Finance',
            aliases=['nbfc', 'nbfcs', 'shadow bank'],
            keywords=['nbfc', 'shadow bank', 'microfinance', 'vehicle finance'],
            trigger_keywords=['nbfc regulation', 'microfinance growth', 'vehicle loan'],
            direct_sectors=['NBFCs', 'Microfinance', 'Vehicle finance'],
            indirect_sectors=['Banks', 'Insurance', 'Housing finance'],
            raw_material=[],
            risk_sectors=['Liquidity', 'Regulatory action'],
            stocks_direct=['BAJFINANCE', 'CHOLAFIN', 'M&MFIN', 'SHRIRAMFIN', 'LICHSGFIN'],
            stocks_indirect=['HDFCBANK', 'ICICIBANK'],
            stocks_raw=[],
            confirmation_rules=['Growth trend', 'Regulatory clarity'],
            stale_after_hours=24,
        ),
        _basket_skeleton(
            theme_id='insurance', display_name='Insurance', category='Finance',
            aliases=['insurance', 'life insurance', 'general insurance', 'lic'],
            keywords=['insurance', 'life insurance', 'general insurance', 'lic', 'premium'],
            trigger_keywords=['insurance penetration', 'lic listing', 'health insurance'],
            direct_sectors=['Life insurance', 'General insurance'],
            indirect_sectors=['Banks', 'Brokers', 'Healthcare'],
            raw_material=[],
            risk_sectors=['Claims cycle', 'Investment returns'],
            stocks_direct=['LICI', 'HDFCLIFE', 'SBILIFE', 'ICICIPRULI', 'GICRE'],
            stocks_indirect=['HDFCBANK', 'ICICIBANK'],
            stocks_raw=[],
            confirmation_rules=['Premium growth', 'Persistency trend'],
            stale_after_hours=48,
        ),
        _basket_skeleton(
            theme_id='amc_brokers', display_name='AMC / Brokers', category='Finance',
            aliases=['amc', 'broker', 'brokers', 'mutual fund', 'demat'],
            keywords=['amc', 'broker', 'mutual fund', 'demat', 'asset management'],
            trigger_keywords=['mutual fund inflows', 'retail participation', 'demat accounts'],
            direct_sectors=['AMCs', 'Brokers', 'Wealth platforms'],
            indirect_sectors=['Banks', 'Insurance', 'Fintech'],
            raw_material=[],
            risk_sectors=['Market volumes', 'Regulatory fee changes'],
            stocks_direct=['HDFCAMC', 'MFSL', 'CAMS', 'ANGELONE', 'IIFL'],
            stocks_indirect=['ICICIBANK', 'HDFCBANK'],
            stocks_raw=[],
            confirmation_rules=['AUM growth', 'Volume trend'],
            stale_after_hours=48,
        ),
        _basket_skeleton(
            theme_id='chemicals', display_name='Chemicals', category='Commodities/Materials',
            aliases=['chemical', 'chemicals', 'specialty chemical'],
            keywords=['chemical', 'specialty chemical', 'agrochemical', 'petrochemical'],
            trigger_keywords=['chemical demand', 'china chemical', 'specialty chemical expansion'],
            direct_sectors=['Specialty chemicals', 'Agrochemicals', 'Petrochemicals'],
            indirect_sectors=['Pharma', 'Textiles', 'Auto'],
            raw_material=['Crude', 'Natural gas'],
            risk_sectors=['China demand', 'Input cost volatility'],
            stocks_direct=['DEEPAKNTR', 'SRF', 'AARTIIND', 'PIDILITIND', 'UPL'],
            stocks_indirect=['TATACHEM', 'GNFC'],
            stocks_raw=['RELIANCE'],
            confirmation_rules=['Volume + margin trend', 'Named expansion'],
        ),
        _basket_skeleton(
            theme_id='sugar_ethanol', display_name='Sugar / Ethanol', category='Commodities/Materials',
            aliases=['sugar', 'ethanol', 'distillery'],
            keywords=['sugar', 'ethanol', 'distillery', 'e20', 'blending'],
            trigger_keywords=['ethanol blending', 'sugar export', 'distillery expansion'],
            direct_sectors=['Sugar mills', 'Ethanol distilleries'],
            indirect_sectors=['OMCs', 'Agri inputs'],
            raw_material=['Sugarcane', 'Molasses'],
            risk_sectors=['Policy changes', 'Crush season'],
            stocks_direct=['BALRAMCHIN', 'TRIVENI', 'EIDPARRY', 'BAJAJHIND', 'DHAMPURSUG'],
            stocks_indirect=['IOC', 'BPCL'],
            stocks_raw=['COROMANDEL'],
            confirmation_rules=['Blending policy', 'Volume trend'],
        ),
        _basket_skeleton(
            theme_id='fmcg', display_name='FMCG', category='Consumer/India Growth',
            aliases=['fmcg', 'consumer staples', 'staples'],
            keywords=['fmcg', 'consumer staples', 'rural demand', 'urban demand'],
            trigger_keywords=['rural demand recovery', 'fmcg volume growth', 'monsoon boost'],
            direct_sectors=['FMCG', 'Consumer staples'],
            indirect_sectors=['Retail', 'Packaging', 'Agri'],
            raw_material=['Palm oil', 'Packaging'],
            risk_sectors=['Input inflation', 'Weak monsoon'],
            stocks_direct=['HINDUNILVR', 'ITC', 'NESTLEIND', 'BRITANNIA', 'DABUR'],
            stocks_indirect=['MARICO', 'GODREJCP', 'TATACONSUM'],
            stocks_raw=['UPL'],
            confirmation_rules=['Volume growth', 'Rural recovery signal'],
        ),
        _basket_skeleton(
            theme_id='retail', display_name='Retail', category='Consumer/India Growth',
            aliases=['retail', 'retailer', 'organised retail'],
            keywords=['retail', 'store expansion', 'organised retail', 'ecommerce'],
            trigger_keywords=['retail expansion', 'same-store sales', 'festive demand'],
            direct_sectors=['Retail', 'E-commerce'],
            indirect_sectors=['FMCG', 'Logistics', 'Payments'],
            raw_material=['Inventory', 'Real estate'],
            risk_sectors=['Margin pressure', 'Competition'],
            stocks_direct=['TITAN', 'TRENT', 'DMART', 'SHOPERSTOP', 'JUBLFOOD'],
            stocks_indirect=['HINDUNILVR', 'DELHIVERY'],
            stocks_raw=['ITC'],
            confirmation_rules=['SSS growth', 'Festive demand confirm'],
        ),
        _basket_skeleton(
            theme_id='textiles', display_name='Textiles', category='Consumer/India Growth',
            aliases=['textile', 'textiles', 'garment', 'apparel'],
            keywords=['textile', 'garment', 'apparel', 'cotton', 'fabric'],
            trigger_keywords=['textile pli', 'garment export', 'cotton prices'],
            direct_sectors=['Textiles', 'Garments', 'Apparel'],
            indirect_sectors=['Chemicals', 'Retail', 'Exports'],
            raw_material=['Cotton', 'Polyester'],
            risk_sectors=['Input costs', 'Export demand'],
            stocks_direct=['ARVIND', 'RAYMOND', 'WELSPUNIND', 'TRIDENT', 'KPRMILL'],
            stocks_indirect=['GRASIM', 'VARDHACRLC'],
            stocks_raw=['RUPA'],
            confirmation_rules=['Order book', 'Export trend'],
        ),
        _basket_skeleton(
            theme_id='media_entertainment', display_name='Media / Entertainment',
            category='Consumer/India Growth',
            aliases=['media', 'entertainment', 'ott', 'broadcast'],
            keywords=['media', 'entertainment', 'ott', 'broadcast', 'streaming'],
            trigger_keywords=['ott subscriber', 'ad revenue', 'content deal'],
            direct_sectors=['Media', 'Broadcast', 'OTT'],
            indirect_sectors=['Telecom', 'Retail', 'Advertising'],
            raw_material=['Content', 'Sports rights'],
            risk_sectors=['Ad cycle', 'Content costs'],
            stocks_direct=['ZEEL', 'SUNTV', 'PVRINOX', 'SAREGAMA', 'NETWORK18'],
            stocks_indirect=['BHARTIARTL', 'RELIANCE'],
            stocks_raw=['TIPS'],
            confirmation_rules=['Ad recovery', 'Subscriber trend'],
        ),
        _basket_skeleton(
            theme_id='pharma', display_name='Pharma', category='Healthcare',
            aliases=['pharma', 'pharmaceutical', 'drug', 'api'],
            keywords=['pharma', 'pharmaceutical', 'drug', 'api', 'formulation'],
            trigger_keywords=['fda approval', 'us pharma', 'api export', 'formulation growth'],
            direct_sectors=['Pharma formulations', 'APIs', 'CDMO'],
            indirect_sectors=['Hospitals', 'Diagnostics', 'Chemicals'],
            raw_material=['API inputs', 'Excipients'],
            risk_sectors=['US pricing', 'Regulatory action'],
            stocks_direct=['SUNPHARMA', 'DRREDDY', 'CIPLA', 'DIVISLAB', 'LUPIN'],
            stocks_indirect=['BIOCON', 'TORNTPHARM'],
            stocks_raw=['AARTIIND'],
            confirmation_rules=['Approval clarity', 'Volume trend'],
        ),
        _basket_skeleton(
            theme_id='hospitals', display_name='Hospitals', category='Healthcare',
            aliases=['hospital', 'hospitals', 'healthcare provider'],
            keywords=['hospital', 'healthcare', 'bed capacity', 'ayushman'],
            trigger_keywords=['hospital expansion', 'bed addition', 'ayushman bharat'],
            direct_sectors=['Hospital chains', 'Healthcare providers'],
            indirect_sectors=['Pharma', 'Diagnostics', 'Insurance'],
            raw_material=['Medical equipment'],
            risk_sectors=['Regulatory', 'Doctor attrition'],
            stocks_direct=['APOLLOHOSP', 'FORTIS', 'MAXHEALTH', 'NH', 'MEDANTA'],
            stocks_indirect=['LALPATHLAB', 'METROPOLIS'],
            stocks_raw=['POLYMED'],
            confirmation_rules=['Occupancy trend', 'Expansion clarity'],
        ),
        _basket_skeleton(
            theme_id='diagnostics', display_name='Diagnostics', category='Healthcare',
            aliases=['diagnostic', 'diagnostics', 'pathology', 'lab'],
            keywords=['diagnostic', 'pathology', 'lab test', 'diagnostics chain'],
            trigger_keywords=['diagnostics expansion', 'lab network', 'preventive care'],
            direct_sectors=['Diagnostics chains', 'Pathology labs'],
            indirect_sectors=['Hospitals', 'Pharma', 'Insurance'],
            raw_material=['Reagents', 'Equipment'],
            risk_sectors=['Competition', 'Pricing pressure'],
            stocks_direct=['LALPATHLAB', 'METROPOLIS', 'THYROCARE', 'KRSNAA'],
            stocks_indirect=['APOLLOHOSP', 'MAXHEALTH'],
            stocks_raw=['TATAELXSI'],
            confirmation_rules=['Volume growth', 'Network expansion'],
        ),
        _basket_skeleton(
            theme_id='rbi_rates', display_name='RBI / Rates', category='Market Risk',
            aliases=['rbi', 'rates', 'repo rate', 'monetary policy'],
            keywords=['rbi', 'repo rate', 'monetary policy', 'rate cut', 'rate hike'],
            trigger_keywords=['rbi policy', 'repo rate', 'mpc decision', 'liquidity'],
            direct_sectors=['Banks', 'NBFCs', 'Rate-sensitive sectors'],
            indirect_sectors=['Real estate', 'Auto', 'Consumption'],
            raw_material=[],
            risk_sectors=['Rate volatility', 'Liquidity squeeze'],
            stocks_direct=['HDFCBANK', 'ICICIBANK', 'SBIN', 'BAJFINANCE', 'DLF'],
            stocks_indirect=['TATAMOTORS', 'HINDUNILVR'],
            stocks_raw=[],
            confirmation_rules=['Policy clarity', 'Sector breadth confirm'],
            stale_after_hours=24,
        ),
        _basket_skeleton(
            theme_id='currency_import_export', display_name='Currency / Import-Export',
            category='Market Risk',
            aliases=['currency', 'forex', 'rupee', 'import export', 'fx'],
            keywords=['rupee', 'forex', 'currency', 'import', 'export', 'fx'],
            trigger_keywords=['rupee weakness', 'export incentive', 'import duty', 'forex reserves'],
            direct_sectors=['Exporters', 'Importers', 'IT services'],
            indirect_sectors=['OMCs', 'Metals', 'Pharma'],
            raw_material=['Crude', 'Commodities'],
            risk_sectors=['FX volatility', 'Trade deficit'],
            stocks_direct=['TCS', 'INFY', 'HCLTECH', 'SUNPHARMA', 'DRREDDY'],
            stocks_indirect=['RELIANCE', 'IOC'],
            stocks_raw=['ONGC'],
            confirmation_rules=['FX trend', 'Named policy action'],
            stale_after_hours=24,
        ),
        _basket_skeleton(
            theme_id='crude_sensitive', display_name='Crude Sensitive', category='Market Risk',
            aliases=['crude', 'oil shock', 'brent', 'atf'],
            keywords=['crude', 'brent', 'oil price', 'atf', 'fuel cost'],
            trigger_keywords=['crude spike', 'oil shock', 'fuel price hike', 'brent surge'],
            direct_sectors=['OMCs', 'Airlines', 'Paint', 'Tyres'],
            indirect_sectors=['Logistics', 'Chemicals', 'FMCG'],
            raw_material=['Crude'],
            risk_sectors=['Margin squeeze', 'Demand destruction'],
            stocks_direct=['IOC', 'BPCL', 'HINDPETRO', 'INDIGO', 'ASIANPAINT'],
            stocks_indirect=['RELIANCE', 'BERGER'],
            stocks_raw=['ONGC'],
            confirmation_rules=['Crude trend', 'Margin impact clarity'],
            stale_after_hours=24,
        ),
        _basket_skeleton(
            theme_id='war_geopolitics', display_name='War / Geopolitics', category='Market Risk',
            aliases=['war', 'geopolitics', 'conflict', 'sanctions'],
            keywords=['war', 'geopolitics', 'conflict', 'sanctions', 'tension', 'strike'],
            trigger_keywords=['military strike', 'geopolitical tension', 'sanctions', 'conflict escalation'],
            direct_sectors=['Defence', 'Energy', 'Gold'],
            indirect_sectors=['Shipping', 'Aviation', 'IT'],
            raw_material=['Crude', 'Gold'],
            risk_sectors=['Risk-off', 'Supply disruption'],
            stocks_direct=['HAL', 'BEL', 'COCHINSHIP', 'MAZDOCK', 'GOLDETF'],
            stocks_indirect=['RELIANCE', 'ONGC', 'INDIGO'],
            stocks_raw=['TATASTEEL'],
            confirmation_rules=['Headline clarity', 'Sector reaction confirm'],
            stale_after_hours=24,
        ),
        _basket_skeleton(
            theme_id='pli_manufacturing', display_name='PLI / Manufacturing',
            category='Government/Budget',
            aliases=['pli', 'manufacturing', 'make in india'],
            keywords=['pli', 'production linked incentive', 'manufacturing', 'make in india'],
            trigger_keywords=['pli scheme', 'manufacturing incentive', 'local manufacturing'],
            direct_sectors=['Electronics', 'Auto', 'Pharma', 'Textiles'],
            indirect_sectors=['Capital goods', 'Chemicals', 'Logistics'],
            raw_material=['Components', 'Industrial inputs'],
            risk_sectors=['Execution delays', 'Import competition'],
            stocks_direct=['DIXON', 'KAYNES', 'SYRMA', 'TATASTEEL', 'SUNPHARMA'],
            stocks_indirect=['LT', 'ABB', 'SIEMENS'],
            stocks_raw=['HINDALCO'],
            confirmation_rules=['PLI approval', 'Named beneficiary', 'Volume confirm'],
            stale_after_hours=72,
        ),
    ]


def _merge_basket_stocks(target: dict[str, Any], source: dict[str, Any]) -> None:
    """Merge stock lists from deprecated basket into canonical target."""
    tgt_stocks = target.setdefault('stocks', {})
    src_stocks = source.get('stocks') or {}
    if not isinstance(tgt_stocks, dict) or not isinstance(src_stocks, dict):
        return
    for bucket in ('direct', 'indirect', 'raw_material', 'avoid_or_risk'):
        lst = tgt_stocks.setdefault(bucket, [])
        for ticker in src_stocks.get(bucket) or []:
            t = str(ticker).upper()
            if t and t not in lst:
                lst.append(t)


def migrate_theme_baskets(data: dict[str, Any]) -> dict[str, Any]:
    """Upgrade persisted baskets to Stage 47F schema."""
    canonical = {b['theme_id']: _normalize_basket(b) for b in _default_baskets()}
    existing = data.get('baskets') or []
    merged: dict[str, dict[str, Any]] = {}
    migrated = 0
    hidden = 0

    for basket in existing:
        if not isinstance(basket, dict):
            continue
        raw_tid = str(basket.get('theme_id') or '')
        if raw_tid in DEPRECATED_THEME_IDS:
            target_id = DEPRECATED_STOCK_MERGE_TARGETS.get(raw_tid, '')
            if target_id and target_id in canonical:
                _merge_basket_stocks(canonical[target_id], basket)
                migrated += 1
            hidden += 1
            continue
        tid = LEGACY_THEME_ID_MAP.get(raw_tid, raw_tid)
        base = canonical.get(tid, {})
        row = dict(base)
        row.update(basket)
        row['theme_id'] = tid
        if tid == 'defence_aerospace':
            row['category'] = 'Government/Budget'
        elif tid == 'war_geopolitics':
            row['category'] = 'Market Risk'
        merged[tid] = _normalize_basket(row)

    for tid, basket in canonical.items():
        if tid in DEPRECATED_THEME_IDS:
            continue
        merged.setdefault(tid, basket)

    prior_version = data.get('theme_schema_version')
    data['baskets'] = list(merged.values())
    data['stage'] = STAGE
    data['theme_schema_version'] = THEME_SCHEMA_VERSION
    if migrated or hidden or prior_version != THEME_SCHEMA_VERSION:
        _log(
            f'THEME_SCHEMA_MIGRATION_APPLIED version={THEME_SCHEMA_VERSION} '
            f'hidden={hidden} migrated={migrated}'
        )
    return data


def bootstrap_theme_baskets(*, force: bool = False) -> dict[str, Any]:
    """Create or migrate theme_baskets.json with full wishlist baskets."""
    if BASKETS_FILE.is_file() and not force:
        try:
            data = json.loads(BASKETS_FILE.read_text(encoding='utf-8'))
            if isinstance(data, dict) and data.get('baskets'):
                needs_migration = (
                    data.get('theme_schema_version') != THEME_SCHEMA_VERSION
                    or data.get('stage') != STAGE
                    or any(
                        isinstance(b, dict) and str(b.get('theme_id') or '') in DEPRECATED_THEME_IDS
                        for b in (data.get('baskets') or [])
                    )
                )
                if needs_migration or len(data.get('baskets') or []) < len(_default_baskets()):
                    data = migrate_theme_baskets(data)
                    atomic_write_json(BASKETS_FILE, data)
                    _log(f'migrated to {len(data.get("baskets") or [])} baskets')
                return data
        except (OSError, json.JSONDecodeError):
            pass

    baskets = _default_baskets()
    payload = {
        'stage': STAGE,
        'theme_schema_version': THEME_SCHEMA_VERSION,
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
    if not resolved or resolved == 'budget' or str(resolved).startswith('__category__'):
        return None
    if resolved in DEPRECATED_THEME_IDS:
        resolved = DEPRECATED_STOCK_MERGE_TARGETS.get(resolved, resolved)
    for basket in load_theme_baskets().get('baskets') or []:
        if isinstance(basket, dict) and basket.get('theme_id') == resolved:
            return basket
    return None


def resolve_theme_id(raw: str) -> Optional[str]:
    key = str(raw or '').strip().lower().replace('-', '_').replace(' ', '_')
    if not key:
        return None
    if key in THEME_ALIASES:
        alias = THEME_ALIASES[key]
        return alias
    if key in CATEGORY_ALIASES:
        return f'__category__:{CATEGORY_ALIASES[key]}'
    for basket in load_theme_baskets().get('baskets') or []:
        if not isinstance(basket, dict):
            continue
        tid = str(basket.get('theme_id') or '')
        if key == tid or key in tid:
            return tid
        for alias in basket.get('aliases') or []:
            if key == str(alias).lower().replace('-', '_').replace(' ', '_'):
                return tid
        display = str(basket.get('display_name') or '').lower()
        if key.replace('_', ' ') in display or key in display.replace('/', ' ').replace(' ', '_'):
            return tid
    return None


def resolve_category(raw: str) -> Optional[str]:
    key = str(raw or '').strip().lower().replace('-', '_').replace(' ', '_')
    if not key:
        return None
    if key in CATEGORY_ALIASES:
        return CATEGORY_ALIASES[key]
    for category in THEME_CATEGORIES:
        if key == category.lower().replace('/', '_').replace(' ', '_'):
            return category
        if key in category.lower():
            return category
    return None


def search_theme_baskets(keyword: str) -> list[dict[str, str]]:
    """Return baskets matching keyword in id, display name, aliases, or keywords."""
    needle = _normalize_text(keyword)
    if not needle:
        return []
    matches: list[dict[str, str]] = []
    seen: set[str] = set()
    for basket in load_theme_baskets().get('baskets') or []:
        if not isinstance(basket, dict):
            continue
        tid = str(basket.get('theme_id') or '')
        if tid in seen:
            continue
        haystacks = [
            tid,
            str(basket.get('display_name') or ''),
            str(basket.get('category') or ''),
        ]
        haystacks.extend(str(a) for a in (basket.get('aliases') or []))
        haystacks.extend(str(k) for k in (basket.get('keywords') or []))
        haystacks.extend(str(k) for k in (basket.get('trigger_keywords') or []))
        blob = _normalize_text(' '.join(haystacks))
        if needle in blob or any(needle in _normalize_text(h) for h in haystacks):
            seen.add(tid)
            matches.append({
                'theme_id': tid,
                'display_name': str(basket.get('display_name') or tid),
                'category': str(basket.get('category') or ''),
            })
    matches.sort(key=lambda r: (r.get('category', ''), r.get('display_name', '')))
    return _filter_display_baskets(matches)


def get_baskets_by_category(category: str) -> list[dict[str, str]]:
    resolved = resolve_category(category) or category
    ids = THEME_CATEGORIES.get(resolved) or []
    rows: list[dict[str, str]] = []
    for tid in ids:
        basket = get_basket_by_id(tid)
        if basket:
            rows.append({
                'theme_id': tid,
                'display_name': str(basket.get('display_name') or tid),
                'category': str(basket.get('category') or resolved),
            })
    return _filter_display_baskets(rows)


def _normalize_text(text: str) -> str:
    return re.sub(r'\s+', ' ', str(text or '').lower().strip())


def _normalize_title(title: str) -> str:
    return re.sub(r'[^a-z0-9]+', ' ', _normalize_text(title)).strip()


def _contains_any(text: str, terms: tuple[str, ...] | list[str]) -> bool:
    lower = _normalize_text(text)
    for term in terms:
        normalized = _normalize_text(term)
        if len(normalized) >= 2 and normalized in lower:
            return True
    return False


def _has_skip_signal(text: str) -> bool:
    return _contains_any(text, SKIP_KEYWORDS)


def _has_theme_anchor(headline: str, theme_id: str) -> bool:
    if _contains_any(headline, THEME_ANCHORS.get(theme_id) or []):
        return True
    basket = get_basket_by_id(theme_id) or {}
    sector_terms = list(basket.get('keywords') or []) + list(basket.get('trigger_keywords') or [])
    return _contains_any(headline, sector_terms)


def _has_strong_govt_order(headline: str, theme_id: str) -> bool:
    lower = _normalize_text(headline)
    govt = any(t in lower for t in ('govt', 'government', 'ministry', 'cabinet', 'nhai', 'union', 'budget'))
    order = any(t in lower for t in ('tender', 'order', 'contract', 'award', 'project', 'allocation', 'capex'))
    return govt and order and _has_theme_anchor(headline, theme_id)


def is_theme_catalyst_relevant(
    headline: str,
    theme_id: str,
    *,
    item: Optional[dict] = None,
) -> bool:
    """Return True only when headline has real thematic tie — not amount/corporate noise."""
    theme_id = _canonical_theme_id(theme_id)
    basket = get_basket_by_id(theme_id) or {}
    text = headline
    if item:
        text = f'{headline} {item.get("description") or ""}'
    lower = _normalize_text(text)

    if theme_id == 'defence_aerospace':
        if 'currency defence' in lower or 'rupee defence' in lower:
            military = any(
                w in lower
                for w in (
                    'military',
                    'army',
                    'navy',
                    'air force',
                    'ordnance',
                    'defence order',
                    'defence contract',
                    'defence tender',
                )
            )
            if not military:
                return False

    has_anchor = _has_theme_anchor(text, theme_id)
    has_stock = bool(_find_named_companies(text, basket))
    has_govt_order = _has_strong_govt_order(text, theme_id)

    if _has_skip_signal(text):
        if has_stock and has_anchor:
            return True
        return False

    if has_anchor or has_stock or has_govt_order:
        return True

    if _extract_crore_amount(text) > 0:
        return False

    return False


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
) -> Optional[dict[str, Any]]:
    """Compute Theme Catalyst Score components for a headline + theme."""
    theme_id = _canonical_theme_id(theme_id)
    if not is_theme_catalyst_relevant(headline, theme_id, item=item):
        return None

    basket = get_basket_by_id(theme_id) or {}
    lower = _normalize_text(headline)
    named = _find_named_companies(headline, basket)
    has_anchor = _has_theme_anchor(headline, theme_id) or bool(named)

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
    norm = _normalize_title(headline)
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

    generic_policy_phrases = (
        'may benefit',
        'policy support',
        'coming years',
        'sector may',
        'could benefit',
        'likely to benefit',
        'in focus',
        'remains in focus',
    )
    broad_policy = (
        not named
        and not order_win
        and not _has_strong_govt_order(headline, theme_id)
        and any(p in lower for p in generic_policy_phrases)
    )
    hide_from_top3 = False
    if not has_anchor:
        return None
    if broad_policy:
        impact_10 = min(impact_10, 3)
        hide_from_top3 = True
        action = 'watch only'
    else:
        action = 'watch only'
        if named and catalyst_score >= 60:
            action = 'watch for confirmation'
        elif catalyst_score >= 70 and order_tender_clarity_score >= 6:
            action = 'watch for confirmation'

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
        'hide_from_top3': hide_from_top3,
        'relevant': True,
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
        if not is_theme_catalyst_relevant(headline, tid, item=item):
            continue
        scored = score_theme_catalyst(headline, tid, item=item, seen_headlines=seen)
        if scored:
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
            norm = _normalize_title(headline)
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
    payload = migrate_theme_baskets(payload)
    payload['catalyst_cache'] = cache
    payload['cache_refreshed_at'] = _now_iso()
    payload['stage'] = STAGE
    payload['theme_schema_version'] = THEME_SCHEMA_VERSION
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


def _filter_relevant_catalysts(
    rows: list[dict[str, Any]],
    *,
    limit: int,
    for_top_display: bool = False,
) -> list[dict[str, Any]]:
    """Dedupe by normalized title; drop irrelevant and optionally broad-policy top-3 hides."""
    seen: set[str] = set()
    filtered: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get('relevant') is False:
            continue
        norm = _normalize_title(str(row.get('headline') or ''))
        if not norm or norm in seen:
            continue
        seen.add(norm)
        if for_top_display and row.get('hide_from_top3'):
            continue
        filtered.append(row)
    filtered.sort(key=lambda r: r.get('catalyst_score', 0), reverse=True)
    return filtered[:limit]


def get_theme_catalysts(
    theme_id: str,
    *,
    limit: int = 5,
    for_top_display: bool = False,
) -> list[dict[str, Any]]:
    resolved = resolve_theme_id(theme_id)
    if not resolved or resolved == 'budget':
        return []
    data = load_theme_baskets()
    cache = data.get('catalyst_cache') or {}
    rows = cache.get(resolved) or []
    if not rows:
        refresh_theme_catalyst_cache(persist=True)
        rows = (load_theme_baskets().get('catalyst_cache') or {}).get(resolved) or []
    return _filter_relevant_catalysts(rows, limit=limit, for_top_display=for_top_display)


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
    catalysts = get_theme_catalysts(theme_id, limit=3, for_top_display=True)
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


def _all_basket_ids() -> set[str]:
    return {
        str(b.get('theme_id') or '')
        for b in load_theme_baskets().get('baskets') or []
        if isinstance(b, dict) and b.get('theme_id')
    }


def _hidden_from_display_ids() -> set[str]:
    """Return legacy basket IDs to hide when split replacements exist."""
    present = _all_basket_ids()
    hidden: set[str] = set(DEPRECATED_THEME_IDS & present)
    for legacy_id, replacements in HIDDEN_WHEN_SPLIT.items():
        if legacy_id in present and all(r in present for r in replacements):
            hidden.add(legacy_id)
    return hidden


def _filter_display_baskets(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    hidden = _hidden_from_display_ids()
    return [row for row in rows if row.get('theme_id') not in hidden]


def list_all_baskets(*, include_hidden: bool = False) -> list[dict[str, str]]:
    rows = [
        {
            'theme_id': b.get('theme_id', ''),
            'display_name': b.get('display_name', ''),
            'category': b.get('category', ''),
        }
        for b in load_theme_baskets().get('baskets') or []
        if isinstance(b, dict)
    ]
    if include_hidden:
        return rows
    return _filter_display_baskets(rows)


def format_theme_list_telegram() -> str:
    lines = [f'<b>🧺 {WISHLIST_TITLE}</b>', '']
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in list_all_baskets():
        cat = row.get('category') or 'Other'
        grouped.setdefault(cat, []).append(row)
    for category in THEME_CATEGORIES:
        rows = grouped.get(category) or []
        if not rows:
            continue
        lines.append(f'<b>{category}</b>')
        for row in sorted(rows, key=lambda r: r.get('display_name', '')):
            lines.append(f"• {row.get('display_name') or row.get('theme_id')}")
        lines.append('')
    lines.extend([
        '<i>Research only — watch/confirm, no blind entry.</i>',
        'Use <code>/theme infra</code> for basket details.',
        'Use <code>/theme search bank</code> or <code>/theme category finance</code>.',
    ])
    return '\n'.join(lines)


def format_theme_overview_telegram() -> str:
    return (
        f'<b>🧺 {WISHLIST_TITLE}</b>\n\n'
        'Thematic intelligence mapping news/govt events to sectors and stocks.\n\n'
        '<b>Commands:</b>\n'
        '• <code>/theme list</code> — grouped wishlist\n'
        '• <code>/theme &lt;basket&gt;</code> — basket details\n'
        '• <code>/theme search &lt;keyword&gt;</code> — find baskets\n'
        '• <code>/theme category &lt;name&gt;</code> — baskets by category\n'
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
        'railways_metro': '🚆',
        'defence_aerospace': '🛡️',
        'tourism_temple_culture': '🛕',
    }
    emoji = emoji_map.get(str(basket.get('theme_id')), '🧺')

    lines = [f'<b>{emoji} {WISHLIST_TITLE} — {display}</b>', '']
    related = []
    if basket.get('theme_id') == 'infrastructure':
        related = ['Infrastructure', 'Roads', 'Cement', 'Steel', 'Paint']
    else:
        related = [display]
        related.extend((basket.get('indirect_beneficiary_sectors') or [])[:3])

    if basket.get('category'):
        lines.append(f"<i>Category: {basket.get('category')}</i>")
        lines.append('')
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

    catalysts = get_theme_catalysts(str(basket.get('theme_id')), limit=3, for_top_display=True)
    lines.extend(['', '<b>Latest catalysts:</b>'])
    if catalysts:
        for idx, cat in enumerate(catalysts[:3], 1):
            lines.append(
                f"{idx}. {cat.get('headline', '—')[:100]} · impact {cat.get('impact_10', '?')}/10"
            )
            lines.append(f"   Why: {cat.get('why', '—')}")
    else:
        lines.append(f'• {NO_CATALYST_MESSAGE}')

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
    catalysts = get_theme_catalysts(theme_id, limit=8, for_top_display=False)
    lines = [f'<b>📰 Theme News — {display}</b>', '']
    if not catalysts:
        lines.append(NO_CATALYST_MESSAGE)
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


def format_theme_search_telegram(keyword: str) -> str:
    rows = search_theme_baskets(keyword)
    lines = [f'<b>🔍 Theme Search — {keyword}</b>', '']
    if not rows:
        lines.append('No matching baskets.')
        lines.append('Try <code>/theme list</code> or another keyword.')
        return '\n'.join(lines)
    for row in rows:
        lines.append(
            f"• {row.get('display_name')} "
            f"(<code>{row.get('theme_id')}</code>) — {row.get('category')}"
        )
    lines.extend(['', '<i>Research only — use /theme &lt;basket&gt; for details.</i>'])
    return '\n'.join(lines)


def format_theme_category_telegram(category: str) -> str:
    resolved = resolve_category(category)
    if not resolved:
        return (
            f'Unknown category: <code>{category}</code>. '
            'Try transport, finance, healthcare, commodities, digital, budget.'
        )
    rows = get_baskets_by_category(resolved)
    lines = [f'<b>📂 {resolved}</b>', '']
    if not rows:
        lines.append('No baskets in this category.')
        return '\n'.join(lines)
    for row in rows:
        lines.append(f"• {row.get('display_name')} (<code>{row.get('theme_id')}</code>)")
    lines.extend([
        '',
        '<i>Research only — /theme &lt;basket&gt; for details.</i>',
    ])
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
    if sub == 'search' and len(parts) >= 2:
        keyword = ' '.join(parts[1:])
        return format_theme_search_telegram(keyword)
    if sub == 'category' and len(parts) >= 2:
        category_key = ' '.join(parts[1:])
        return format_theme_category_telegram(category_key)
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
    if resolved and str(resolved).startswith('__category__:'):
        return format_theme_category_telegram(str(resolved).split(':', 1)[-1])
    if resolved == 'budget':
        return format_theme_budget_telegram()
    if not resolved:
        return f'Unknown theme: <code>{theme_key}</code>. Try <code>/theme list</code>.'
    return format_theme_detail_telegram(resolved)
