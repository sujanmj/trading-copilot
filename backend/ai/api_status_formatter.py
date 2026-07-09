"""Safe Telegram /api status — masked keys only."""

from __future__ import annotations

from backend.trading.candidate_outcome_learning import AI_EXPLAIN_CAP


def _mask_last4(masked: str | None) -> str:
    text = str(masked or '').strip()
    if not text:
        return ''
    if text.startswith('...'):
        return text
    if '…' in text:
        parts = text.split('…')
        if parts and len(parts[-1]) >= 4:
            return f'...{parts[-1][-4:]}'
    if len(text) >= 4:
        return f'...{text[-4:]}'
    return '***'


def _provider_line(name: str, registry_rows: list[dict], pool_summary: dict) -> str:
    present = [r for r in registry_rows if r.get('present')]
    slots = pool_summary.get('slots') or []
    active = sum(1 for s in slots if s.get('has_key') and s.get('status') != 'cooldown')
    cooling = sum(1 for s in slots if s.get('status') == 'cooldown')
    masked = ','.join(_mask_last4(r.get('masked')) for r in present if r.get('masked')) or '—'
    status = 'CONFIGURED' if present else 'MISSING'
    return (
        f'{name}: {status} · keys={len(present)} · active={active} · '
        f'cooling={cooling} · masked={masked}'
    )


def format_api_status_telegram() -> str:
    from backend.ai.ai_pool_router import OUTCOME_EXPLAINER_ROUTE
    from backend.ai.provider_manager import get_provider_env_diagnostics, get_provider_ops_summary
    from backend.analytics.provider_analytics import get_ai_runtime_stats_payload
    from backend.trading.candidate_outcome_learning import learning_stats

    diag = get_provider_env_diagnostics()
    ops = get_provider_ops_summary()
    providers = ops.get('providers') or {}
    runtime = get_ai_runtime_stats_payload()
    learn = learning_stats()
    providers_runtime = runtime.get('providers') or {}

    groq_stats = providers_runtime.get('groq') or {}
    gemini_stats = providers_runtime.get('gemini') or {}
    claude_stats = providers_runtime.get('claude') or {}
    rate_limits = 0
    for pool_name in ('groq', 'gemini'):
        for slot in (providers.get(pool_name) or {}).get('slots') or []:
            rate_limits += int(slot.get('rate_limit_errors_today') or slot.get('quota_failures') or 0)
    last_error = '—'
    for pool_name in ('groq', 'gemini', 'claude'):
        for slot in (providers.get(pool_name) or {}).get('slots') or []:
            err = str(slot.get('last_error') or '').strip()
            if err:
                last_error = err[:120]
                break
        if last_error != '—':
            break

    route = ' -> '.join(f'{p.title()} pool' if p != 'claude' else 'Claude' for p in OUTCOME_EXPLAINER_ROUTE)
    lines = [
        '<b>API STATUS</b>',
        'AI router: auto',
        f'Outcome explainer route: {route}',
        f'Daily AI explanation cap: {AI_EXPLAIN_CAP}',
        '',
        '<b>Providers:</b>',
        _provider_line('Groq', diag.get('groq_keys') or [], providers.get('groq') or {}),
        _provider_line('Gemini', diag.get('gemini_keys') or [], providers.get('gemini') or {}),
        _provider_line('Claude', diag.get('claude_keys') or [], providers.get('claude') or {}),
        '',
        '<b>Usage today:</b>',
        f"groq_requests={int(groq_stats.get('requests_today') or 0)}",
        f"gemini_requests={int(gemini_stats.get('requests_today') or 0)}",
        f"claude_requests={int(claude_stats.get('requests_today') or 0)}",
        f"ai_explanations_used_today={int(learn.get('ai_explanations_used_today') or 0)}",
        f'rate_limit_errors={rate_limits}',
        f'last_error={last_error}',
        '',
        '<b>Limits:</b>',
        'context_window_tokens=configured_per_model',
        'max_output_tokens=configured_per_use_case',
        'rpm/tpm/rpd=local_budget_only',
        'remaining_quota=not_available_from_provider',
    ]
    return '\n'.join(lines)
