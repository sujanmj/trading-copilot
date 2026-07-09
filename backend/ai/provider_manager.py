"""
Tiered AI provider pooling — Gemini + Groq key pools, Claude strategist, health tracking.

Failover on quota / timeout / API failure; round-robin across keys for normal load.
"""

from __future__ import annotations

import os
import re
import threading
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from backend.storage.json_io import atomic_write_json
from backend.utils.config import DATA_DIR, IS_RAILWAY, load_env

load_env()

PROVIDER_HEALTH_FILE = DATA_DIR / 'provider_health.json'

MAX_FAILOVER_PER_REQUEST = 3
MAX_TIMEOUT_STRIKES = 2
BASE_COOLDOWN_SEC = 60
MAX_COOLDOWN_SEC = 3600

GEMINI_KEY_VARS = (
    'GOOGLE_API_KEY_1', 'GOOGLE_API_KEY_2', 'GOOGLE_API_KEY_3',
    'GEMINI_API_KEY_1', 'GEMINI_API_KEY_2', 'GEMINI_API_KEY_3',
    'GOOGLE_API_KEY', 'GEMINI_API_KEY',
    'GEMINI_API1', 'GEMINI_API2', 'GEMINI_API3',
)
GROQ_KEY_VARS = (
    'GROQ_API_KEY_1', 'GROQ_API_KEY_2', 'GROQ_API_KEY_3',
    'GROQ_API_KEY',
    'GROQ_API1', 'GROQ_API2', 'GROQ_API3',
)
GEMINI_LEGACY_VARS: Tuple[str, ...] = ()
GROQ_LEGACY_VARS: Tuple[str, ...] = ()
CLAUDE_KEY_VARS = ('ANTHROPIC_API_KEY', 'CLAUDE_API_KEY')
GROQ_DEFAULT_MODEL = os.environ.get('GROQ_MODEL', 'llama-3.3-70b-versatile')

ENV_TYPO_PATTERNS = (
    (re.compile(r'^GORQ_', re.I), 'GORQ → did you mean GROQ?'),
    (re.compile(r'^GOOGLE_KEY_', re.I), 'GOOGLE_KEY → did you mean GOOGLE_API_KEY?'),
)

_startup_logged = False

ENRICHMENT_UNAVAILABLE_MSG = (
    '⚠ AI enrichment temporarily unavailable.\n'
    'Core intelligence systems remain operational.'
)

_lock = threading.Lock()
_gemini_pool: Optional['GeminiPoolManager'] = None
_groq_pool: Optional['GroqPoolManager'] = None


def _log(tag: str, msg: str):
    print(f"[{tag}] {msg}")


def _mask_key(key: str) -> str:
    k = (key or '').strip()
    if len(k) < 4:
        return '***' if k else ''
    return f'...{k[-4:]}'


def _env_var_present(var: str) -> bool:
    return bool(os.environ.get(var, '').strip())


def _scan_env_typos() -> List[str]:
    warnings: List[str] = []
    for var in os.environ:
        for pattern, hint in ENV_TYPO_PATTERNS:
            if pattern.match(var):
                warnings.append(f"Found {var} in environment — {hint}")
    if not any(_env_var_present(v) for v in GROQ_KEY_VARS) and not any(_env_var_present(v) for v in GROQ_LEGACY_VARS):
        for var in os.environ:
            if 'GORQ' in var.upper() or (var.upper().startswith('GROQ') and var not in GROQ_KEY_VARS + GROQ_LEGACY_VARS):
                warnings.append(f"Possible Groq env typo: {var}")
    return warnings


def _key_registry(prefix_vars: Tuple[str, ...], legacy_vars: Tuple[str, ...] = ()) -> List[dict]:
    rows = []
    for var in prefix_vars + legacy_vars:
        val = os.environ.get(var, '').strip()
        rows.append({
            'env_var': var,
            'present': bool(val),
            'masked': _mask_key(val) if val else None,
            'source': 'railway' if IS_RAILWAY and val else ('env_file' if val else 'missing'),
        })
    return rows


def _load_keys(prefix_vars: Tuple[str, ...], legacy_vars: Tuple[str, ...] = ()) -> List[Tuple[str, str]]:
    keys: List[Tuple[str, str]] = []
    seen_vals: set[str] = set()
    for var in prefix_vars + legacy_vars:
        val = os.environ.get(var, '').strip()
        if not val or val in seen_vals:
            continue
        keys.append((var, val))
        seen_vals.add(val)
    return keys


def get_provider_env_diagnostics() -> dict:
    """Safe env/registry diagnostics for OPS and debug endpoints."""
    gemini_registry = _key_registry(GEMINI_KEY_VARS, GEMINI_LEGACY_VARS)
    groq_registry = _key_registry(GROQ_KEY_VARS, GROQ_LEGACY_VARS)
    claude_registry = _key_registry(CLAUDE_KEY_VARS)
    claude_key = ''
    for var in CLAUDE_KEY_VARS:
        claude_key = os.environ.get(var, '').strip()
        if claude_key:
            break
    gemini_loaded = sum(1 for r in gemini_registry if r.get('present'))
    groq_loaded = sum(1 for r in groq_registry if r.get('present'))
    typos = _scan_env_typos()
    warnings = list(typos)
    if gemini_loaded == 0:
        warnings.append('Gemini pool empty — set GOOGLE_API_KEY_1/2/3 (or GOOGLE_API_KEY legacy)')
    if groq_loaded == 0:
        warnings.append('Groq pool empty — set GROQ_API_KEY_1/2/3 (or GROQ_API_KEY legacy)')
    if not claude_key:
        warnings.append('Claude key missing — ANTHROPIC_API_KEY not set (strategic tier only)')
    return {
        'railway': IS_RAILWAY,
        'gemini_loaded': gemini_loaded,
        'groq_loaded': groq_loaded,
        'claude_loaded': bool(claude_key) and (claude_key.startswith('sk-ant-') or len(claude_key) > 12),
        'gemini_keys': gemini_registry,
        'groq_keys': groq_registry,
        'claude_keys': claude_registry,
        'claude_masked': _mask_key(claude_key) if claude_key else None,
        'typo_warnings': typos,
        'warnings': warnings,
        'conversational_provider': 'groq' if groq_loaded else ('gemini' if gemini_loaded else 'none'),
    }


def log_provider_startup_diagnostics(*, force: bool = False) -> dict:
    global _startup_logged
    diag = get_provider_env_diagnostics()
    if _startup_logged and not force:
        return diag
    _startup_logged = True
    _log('AI PROVIDERS', f"Gemini loaded: {diag['gemini_loaded']}")
    _log('AI PROVIDERS', f"Groq loaded: {diag['groq_loaded']}")
    _log('AI PROVIDERS', f"Claude loaded: {'yes' if diag['claude_loaded'] else 'no'}")
    _log('AI PROVIDERS', f"Conversational route: {diag['conversational_provider']}")
    if diag['gemini_loaded'] == 0:
        _log('AI PROVIDERS', 'ERROR Gemini pool empty — check GOOGLE_API_KEY_1/2/3 on Railway')
    if diag['groq_loaded'] == 0:
        _log('AI PROVIDERS', 'ERROR Groq pool empty — check GROQ_API_KEY_1/2/3 on Railway')
    for warn in diag.get('typo_warnings') or []:
        _log('AI PROVIDERS', f"WARN {warn}")
    for row in (diag.get('gemini_keys') or []) + (diag.get('groq_keys') or []):
        if row.get('present'):
            _log('AI PROVIDERS', f"  {row['env_var']} -> {row['masked']} ({row.get('source')})")
    return diag


def _is_quota_error(error: str) -> bool:
    e = (error or '').lower()
    return '429' in e or 'quota' in e or 'resource_exhausted' in e or 'rate limit' in e


def _is_timeout_error(error: str) -> bool:
    e = (error or '').lower()
    return 'timeout' in e or 'timed out' in e or 'connection' in e


def _slot_template(slot_id: str, key: str) -> dict:
    return {
        'slot_id': slot_id,
        'key_id': slot_id,
        'active': True,
        'cooldown_until': 0.0,
        'consecutive_failures': 0,
        'quota_failures': 0,
        'timeout_failures': 0,
        'failover_count': 0,
        'avg_latency_ms': 0.0,
        'latency_samples': 0,
        'last_success': None,
        'last_success_at': None,
        'last_used_at': None,
        'last_error': None,
        'error_count_today': 0,
        'rate_limit_errors_today': 0,
        'requests_today': 0,
        'estimated_tokens_today': 0,
        'stats_date': None,
        'health_score': 1.0,
        'has_key': bool(key),
    }


class ProviderPool:
    """Base pool — sequential failover from primary active slot."""

    provider_name: str = 'unknown'
    role: str = 'general'

    def __init__(self, provider_name: str, role: str, key_pairs: List[Tuple[str, str]]):
        self.provider_name = provider_name
        self.role = role
        self._key_vars: Tuple[str, ...] = ()
        self._legacy_vars: Tuple[str, ...] = ()
        self._keys = key_pairs
        self._active_index = 0
        self._state = self._load_state()

    def reload_keys_from_env(self, prefix_vars: Tuple[str, ...], legacy_vars: Tuple[str, ...] = ()):
        self._key_vars = prefix_vars
        self._legacy_vars = legacy_vars
        fresh = _load_keys(prefix_vars, legacy_vars)
        if len(fresh) != len(self._keys) or any(a[0] != b[0] for a, b in zip(fresh, self._keys)):
            self._keys = fresh
            self._state = self._load_state()
        else:
            self._keys = fresh
            for idx, (var, key) in enumerate(self._keys):
                sid = f"{self.provider_name}-{idx + 1}"
                slot = self._state.setdefault('slots', {}).setdefault(sid, _slot_template(sid, key))
                slot['has_key'] = bool(key)
                slot['env_var'] = var

    def _recover_expired_cooldowns(self) -> int:
        now = time.time()
        recovered = 0
        for slot_id, slot in (self._state.get('slots') or {}).items():
            cd = float(slot.get('cooldown_until') or 0)
            if cd > 0 and now >= cd:
                slot['cooldown_until'] = 0.0
                slot['active'] = True
                slot['consecutive_failures'] = 0
                slot['health_score'] = min(1.0, float(slot.get('health_score', 0.5)) + 0.1)
                self._state['slots'][slot_id] = slot
                recovered += 1
                _log('PROVIDER RECOVER', f'{slot_id} cooldown expired — slot reactivated')
        if recovered:
            self._persist()
        return recovered

    def _load_state(self) -> dict:
        all_state = _read_global_state()
        pool = all_state.get('pools', {}).get(self.provider_name) or {}
        slots = pool.get('slots') or {}
        for idx, (env_var, key) in enumerate(self._keys):
            sid = f"{self.provider_name}-{idx + 1}"
            if sid not in slots:
                slots[sid] = _slot_template(sid, key)
            else:
                slots[sid]['has_key'] = bool(key)
                slots[sid]['key_id'] = sid
            slots[sid]['env_var'] = env_var
        pool['slots'] = slots
        pool['active_slot'] = pool.get('active_slot') or (f"{self.provider_name}-1" if self._keys else None)
        pool['role'] = self.role
        return pool

    def _persist(self):
        all_state = _read_global_state()
        all_state.setdefault('pools', {})[self.provider_name] = self._state
        all_state['updated_at'] = datetime.now().isoformat()
        atomic_write_json(PROVIDER_HEALTH_FILE, all_state)

    def _ensure_daily_stats(self, slot: dict) -> dict:
        today = datetime.now().date().isoformat()
        if slot.get('stats_date') != today:
            slot['stats_date'] = today
            slot['error_count_today'] = 0
            slot['rate_limit_errors_today'] = 0
            slot['requests_today'] = 0
            slot['estimated_tokens_today'] = 0
        return slot

    def _advance_round_robin(self) -> int:
        if not self._keys:
            return 0
        idx = int(self._state.get('round_robin_index') or 0) % len(self._keys)
        self._state['round_robin_index'] = (idx + 1) % len(self._keys)
        return idx

    def _slot_ids_ordered(self) -> List[str]:
        if not self._keys:
            return []
        ids = [f"{self.provider_name}-{i + 1}" for i in range(len(self._keys))]
        start = self._advance_round_robin()
        return ids[start:] + ids[:start]

    def _slot_ids_standby_order(self) -> List[str]:
        """Non-mutating order for health summaries."""
        if not self._keys:
            return []
        ids = [f"{self.provider_name}-{i + 1}" for i in range(len(self._keys))]
        active = self._state.get('active_slot')
        if active in ids:
            idx = ids.index(active)
            return ids[idx:] + ids[:idx]
        return ids

    def _get_key_for_slot(self, slot_id: str) -> Optional[str]:
        try:
            idx = int(slot_id.rsplit('-', 1)[1]) - 1
            if 0 <= idx < len(self._keys):
                return self._keys[idx][1]
        except (ValueError, IndexError):
            pass
        return None

    def _in_cooldown(self, slot: dict) -> bool:
        return time.time() < float(slot.get('cooldown_until') or 0)

    def _cooldown_seconds(self, slot: dict, *, quota: bool = False) -> int:
        failures = int(slot.get('consecutive_failures') or 0)
        base = BASE_COOLDOWN_SEC * 2 if quota else BASE_COOLDOWN_SEC
        return min(MAX_COOLDOWN_SEC, base * max(1, 2 ** min(failures, 5)))

    def _apply_cooldown(self, slot_id: str, *, quota: bool = False):
        slot = self._state['slots'].get(slot_id) or {}
        sec = self._cooldown_seconds(slot, quota=quota)
        slot['cooldown_until'] = time.time() + sec
        slot['active'] = False
        self._state['slots'][slot_id] = slot
        _log('PROVIDER COOLDOWN', f'{slot_id} {sec}s (quota={quota})')
        try:
            from backend.analytics.provider_analytics import record_cooldown
            record_cooldown(self.provider_name, slot_id)
        except Exception:
            pass

    def record_success(self, slot_id: str, latency_ms: float = 0.0):
        with _lock:
            slot = self._state['slots'].setdefault(slot_id, _slot_template(slot_id, ''))
            slot = self._ensure_daily_stats(slot)
            slot['requests_today'] = int(slot.get('requests_today') or 0) + 1
            slot['consecutive_failures'] = 0
            slot['active'] = True
            slot['cooldown_until'] = 0.0
            now_iso = datetime.now().isoformat()
            slot['last_success'] = now_iso
            slot['last_success_at'] = now_iso
            slot['last_used_at'] = now_iso
            slot['last_error'] = None
            slot['health_score'] = min(1.0, float(slot.get('health_score', 0.8)) + 0.05)
            n = int(slot.get('latency_samples') or 0)
            avg = float(slot.get('avg_latency_ms') or 0)
            slot['avg_latency_ms'] = round((avg * n + latency_ms) / (n + 1), 1) if latency_ms else avg
            slot['latency_samples'] = n + 1 if latency_ms else n
            self._state['active_slot'] = slot_id
            self._persist()

    def record_failure(self, slot_id: str, error: str, *, quota: bool = False, timeout: bool = False):
        with _lock:
            slot = self._state['slots'].setdefault(slot_id, _slot_template(slot_id, ''))
            slot = self._ensure_daily_stats(slot)
            slot['requests_today'] = int(slot.get('requests_today') or 0) + 1
            slot['last_used_at'] = datetime.now().isoformat()
            slot['consecutive_failures'] = int(slot.get('consecutive_failures') or 0) + 1
            slot['error_count_today'] = int(slot.get('error_count_today') or 0) + 1
            slot['last_error'] = (error or '')[:300]
            slot['health_score'] = max(0.0, float(slot.get('health_score', 1.0)) - 0.15)
            if quota:
                slot['quota_failures'] = int(slot.get('quota_failures') or 0) + 1
                slot['rate_limit_errors_today'] = int(slot.get('rate_limit_errors_today') or 0) + 1
            if timeout:
                slot['timeout_failures'] = int(slot.get('timeout_failures') or 0) + 1
            self._state['slots'][slot_id] = slot
            self._persist()

    def execute_with_failover(
        self,
        call_fn: Callable[[str, str], Tuple[dict, float]],
        *,
        model_label: str = '',
        _recovery_retry: bool = True,
    ) -> Tuple[dict, dict]:
        """
        call_fn(api_key, slot_id) -> (result_dict, latency_ms)
        Returns (result, meta) where meta has slot_id, failovers, degraded.
        """
        if not self._keys:
            return (
                {'success': False, 'error': f'No {self.provider_name} keys configured', 'text': ''},
                {'degraded': True, 'reason': 'no_keys'},
            )

        self._recover_expired_cooldowns()

        meta = {'provider': self.provider_name, 'failovers': 0, 'slot_id': None, 'degraded': False}
        last_error = ''
        attempts = 0
        skipped_cooldown = 0

        for slot_id in self._slot_ids_ordered():
            if attempts >= MAX_FAILOVER_PER_REQUEST:
                break
            slot = self._state['slots'].get(slot_id) or {}
            if self._in_cooldown(slot):
                skipped_cooldown += 1
                continue
            api_key = self._get_key_for_slot(slot_id)
            if not api_key:
                continue

            attempts += 1
            _log('AI ROUTE', f'{self.provider_name}_pool -> {slot_id} active')
            t0 = time.time()
            try:
                result, latency_ms = call_fn(api_key, slot_id)
            except Exception as e:
                result = {'success': False, 'error': str(e), 'text': ''}
                latency_ms = (time.time() - t0) * 1000

            if result.get('success'):
                self.record_success(slot_id, latency_ms)
                meta['slot_id'] = slot_id
                meta['latency_ms'] = round(latency_ms, 1)
                if model_label:
                    result['model'] = model_label
                result['provider_slot'] = slot_id
                return result, meta

            err = str(result.get('error') or '')
            last_error = err
            quota = _is_quota_error(err)
            timeout = _is_timeout_error(err)
            self.record_failure(slot_id, err, quota=quota, timeout=timeout)
            slot = self._state['slots'].get(slot_id) or {}

            should_failover = quota or timeout or int(slot.get('consecutive_failures') or 0) >= MAX_TIMEOUT_STRIKES
            if should_failover:
                self._apply_cooldown(slot_id, quota=quota)
                slot['failover_count'] = int(slot.get('failover_count') or 0) + 1
                self._state['slots'][slot_id] = slot
                meta['failovers'] += 1
                self._persist()
                _log('PROVIDER FAILOVER', f'{self.provider_name} {slot_id} -> next ({err[:80]})')
                continue

        if attempts == 0 and skipped_cooldown and self._keys and _recovery_retry:
            recovered = self._recover_expired_cooldowns()
            if recovered:
                return self.execute_with_failover(call_fn, model_label=model_label, _recovery_retry=False)

        meta['degraded'] = True
        if attempts == 0 and skipped_cooldown:
            last_error = last_error or f'all {self.provider_name} slots in cooldown'
            _log('PROVIDER DEGRADED', f'{self.provider_name} all slots cooling down ({skipped_cooldown} skipped)')
        out = {'success': False, 'error': last_error or 'all pool slots failed', 'text': ''}
        out['user_message'] = ENRICHMENT_UNAVAILABLE_MSG
        return out, meta

    def is_degraded(self) -> bool:
        if not self._keys:
            return True
        self._recover_expired_cooldowns()
        now = time.time()
        for slot_id in self._slot_ids_standby_order():
            slot = self._state['slots'].get(slot_id) or {}
            if self._get_key_for_slot(slot_id) and now >= float(slot.get('cooldown_until') or 0):
                return False
        return True

    def summary(self) -> dict:
        slots_out = []
        now = time.time()
        for slot_id in sorted(self._state.get('slots', {}).keys()):
            s = dict(self._state['slots'][slot_id])
            cd = float(s.get('cooldown_until') or 0)
            if cd > now:
                s['cooldown_remaining_sec'] = int(cd - now)
                s['status'] = 'cooldown'
            elif s.get('has_key'):
                s['status'] = 'active' if slot_id == self._state.get('active_slot') else 'standby'
            else:
                s['status'] = 'no_key'
            s.pop('latency_samples', None)
            slots_out.append(s)
        return {
            'provider': self.provider_name,
            'role': self.role,
            'active_slot': self._state.get('active_slot'),
            'degraded': self.is_degraded(),
            'slots': slots_out,
            'total_failovers': sum(int(s.get('failover_count') or 0) for s in slots_out),
        }


class GeminiPoolManager(ProviderPool):
    def __init__(self):
        keys = _load_keys(GEMINI_KEY_VARS, GEMINI_LEGACY_VARS)
        super().__init__('gemini', 'intelligence_engine', keys)
        self._key_vars = GEMINI_KEY_VARS
        self._legacy_vars = GEMINI_LEGACY_VARS


class GroqPoolManager(ProviderPool):
    def __init__(self):
        keys = _load_keys(GROQ_KEY_VARS, GROQ_LEGACY_VARS)
        super().__init__('groq', 'conversational_runtime', keys)
        self._key_vars = GROQ_KEY_VARS
        self._legacy_vars = GROQ_LEGACY_VARS


class ClaudeProvider:
    """Single-key strategist with ANTHROPIC/CLAUDE env aliases."""

    role = 'premium_strategist'

    def __init__(self):
        self._key = ''
        self._env_var = ''
        for var in CLAUDE_KEY_VARS:
            val = os.environ.get(var, '').strip()
            if val:
                self._key = val
                self._env_var = var
                break

    def is_available(self) -> bool:
        return bool(self._key) and (self._key.startswith('sk-ant-') or len(self._key) > 12)

    def summary(self) -> dict:
        return {
            'provider': 'claude',
            'role': self.role,
            'active_slot': 'claude-1' if self.is_available() else None,
            'degraded': not self.is_available(),
            'slots': [{
                'slot_id': 'claude-1',
                'key_id': 'claude-1',
                'status': 'standby' if self.is_available() else 'no_key',
                'has_key': self.is_available(),
                'health_score': 1.0 if self.is_available() else 0.0,
            }],
            'total_failovers': 0,
        }


def _read_global_state() -> dict:
    if not PROVIDER_HEALTH_FILE.exists():
        return {'pools': {}, 'updated_at': None}
    try:
        import json
        with open(PROVIDER_HEALTH_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {'pools': {}}
    except Exception:
        return {'pools': {}}


def get_gemini_pool() -> GeminiPoolManager:
    global _gemini_pool
    load_env()
    if _gemini_pool is None:
        _gemini_pool = GeminiPoolManager()
    else:
        _gemini_pool.reload_keys_from_env(GEMINI_KEY_VARS, GEMINI_LEGACY_VARS)
    return _gemini_pool


def get_groq_pool() -> GroqPoolManager:
    global _groq_pool
    load_env()
    if _groq_pool is None:
        _groq_pool = GroqPoolManager()
    else:
        _groq_pool.reload_keys_from_env(GROQ_KEY_VARS, GROQ_LEGACY_VARS)
    return _groq_pool


def get_claude_provider() -> ClaudeProvider:
    return ClaudeProvider()


def get_degraded_status() -> dict:
    gem = get_gemini_pool()
    groq = get_groq_pool()
    claude = get_claude_provider()
    gem_deg = gem.is_degraded()
    groq_deg = groq.is_degraded()
    return {
        'gemini_degraded': gem_deg,
        'groq_degraded': groq_deg,
        'claude_available': claude.is_available(),
        'conversational_degraded': groq_deg and gem_deg,
        'intelligence_degraded': gem_deg,
        'mode': (
            'operational_only' if gem_deg and groq_deg and not claude.is_available()
            else 'conversational_fallback' if gem_deg and not groq_deg
            else 'intelligence_fallback' if groq_deg and not gem_deg
            else 'normal'
        ),
        'enrichment_message': ENRICHMENT_UNAVAILABLE_MSG if gem_deg else None,
    }


def get_provider_ops_summary() -> dict:
    log_provider_startup_diagnostics()
    gem = get_gemini_pool().summary()
    groq = get_groq_pool().summary()
    claude = get_claude_provider().summary()
    degraded = get_degraded_status()
    env_diag = get_provider_env_diagnostics()
    return {
        'status': 'ok',
        'degraded': degraded,
        'env_diagnostics': env_diag,
        'providers': {
            'gemini': gem,
            'groq': groq,
            'claude': claude,
        },
        'routing_roles': {
            'gemini': 'intelligence · compression · synthesis · commentary',
            'groq': 'Telegram Q&A · operator chat · lightweight explanations',
            'claude': 'final synthesis · contradiction-heavy strategic reasoning only',
        },
        'active_conversational_provider': env_diag.get('conversational_provider'),
        'updated_at': _read_global_state().get('updated_at'),
    }


def get_provider_debug_registry() -> dict:
    """Extended registry for /api/debug/providers."""
    ops = get_provider_ops_summary()
    env_diag = ops.get('env_diagnostics') or get_provider_env_diagnostics()
    providers = ops.get('providers') or {}
    registry = {}
    for name, pdata in providers.items():
        slots = []
        for s in pdata.get('slots') or []:
            slots.append({
                'slot_id': s.get('slot_id'),
                'env_var': s.get('env_var'),
                'status': s.get('status'),
                'active': s.get('status') == 'active',
                'has_key': s.get('has_key'),
                'cooldown_remaining_sec': s.get('cooldown_remaining_sec'),
                'consecutive_failures': s.get('consecutive_failures'),
                'quota_failures': s.get('quota_failures'),
                'failover_count': s.get('failover_count'),
                'last_error': s.get('last_error'),
                'last_success': s.get('last_success'),
                'health_score': s.get('health_score'),
            })
        registry[name] = {
            'loaded': pdata.get('active_slot') is not None or any(x.get('has_key') for x in slots),
            'degraded': pdata.get('degraded'),
            'active_slot': pdata.get('active_slot'),
            'role': pdata.get('role'),
            'slots': slots,
        }
    return {
        'env': env_diag,
        'registry': registry,
        'degraded': ops.get('degraded'),
        'active_conversational_provider': env_diag.get('conversational_provider'),
    }


def resolve_use_case_tier(use_case: str) -> str:
    """Return: conversational | gemini | strategic"""
    conversational = {
        'ask_basic', 'ask_conversational', 'telegram_ask', 'ops_assistant',
        'lightweight_summary', 'ask_haiku', 'alert_analysis',
    }
    strategic = {
        'final_synthesis', 'manual_refresh', 'overnight_brief', 'premarket_brief',
        'postmortem', 'ask_deep', 'sonnet', 'fixops_report_analyzer',
    }
    if use_case in strategic:
        return 'strategic'
    if use_case in conversational:
        return 'conversational'
    return 'gemini'
