/**
 * AI Ops / Logs — lightweight observability drawer for Trading Copilot GUI.
 * Lazy-loads debug data only when panel is open; polling stops when closed.
 */
(function (global) {
  'use strict';

  const POLL_MS = 8000;

  let config = {
    getApiBase: () => '',
    getHeaders: () => ({}),
    getRuntimeState: () => null,
  };
  let open = false;
  let pollTimer = null;
  let loadedOnce = false;
  let lastAlertSignature = '';
  let runtimeUnsub = null;

  const STORAGE_KEY = 'tradingcopilot_aiops_seen';

  function $(id) {
    return document.getElementById(id);
  }

  function escapeHtml(text) {
    if (text == null) return '';
    return String(text)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function fmtScore(v) {
    if (v == null || v === '') return '—';
    const n = Number(v);
    return Number.isFinite(n) ? n.toFixed(2) : escapeHtml(v);
  }

  function scoreClass(v, warnBelow) {
    const n = Number(v);
    if (!Number.isFinite(n)) return '';
    return n < warnBelow ? 'ai-ops-warn' : 'ai-ops-ok';
  }

  async function fetchJson(path, requireAuth) {
    const base = config.getApiBase().replace(/\/$/, '');
    const headers = requireAuth ? config.getHeaders() : { Accept: 'application/json' };
    const res = await fetch(base + path, { method: 'GET', headers });
    if (!res.ok) throw new Error(`${path} → ${res.status}`);
    return res.json();
  }

  function loadSeenState() {
    try {
      return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
    } catch (e) {
      return {};
    }
  }

  function saveSeenState(state) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch (e) { /* ignore */ }
  }

  function alertSignature(data) {
    const h = data.health || {};
    const obs = h.pipeline_observability || {};
    const expl = data.explanations || {};
    const warnings = (expl.latest && expl.latest.warnings) || [];
    return [
      obs.latest_cycle_id || '',
      warnings.length,
      h.delta_trigger_reason || '',
      h.last_quality_score || '',
    ].join('|');
  }

  function updateAlertDot(hasUnread) {
    const btn = $('aiOpsBtn');
    if (!btn) return;
    btn.classList.toggle('has-alert', !!hasUnread);
  }

  function markAlertsSeen(data) {
    const sig = alertSignature(data);
    lastAlertSignature = sig;
    saveSeenState({ signature: sig, at: Date.now() });
    updateAlertDot(false);
  }

  function computeUnread(data) {
    const sig = alertSignature(data);
    const seen = loadSeenState();
    const warnings = ((data.explanations || {}).latest || {}).warnings || [];
    const health = data.health || {};
    const iq = Number(health.last_quality_score);
    const hasQualityIssue = Number.isFinite(iq) && iq < 0.55;
    const hasWarnings = warnings.length > 0;
    const staleReuse = Number((health.pipeline_observability || {}).stale_reuse_count || 0) >= 5;
    const deltaHot = String(health.delta_trigger_reason || '').includes('preservation');

    if (!seen.signature) {
      return hasWarnings || hasQualityIssue;
    }
    if (sig !== seen.signature && (hasWarnings || hasQualityIssue || staleReuse || deltaHot)) {
      return true;
    }
    return false;
  }

  function buildHealthFromRuntime(runtime) {
    if (!runtime || !runtime.ops) return {};
    const ops = runtime.ops;
    const health = ops.health || {};
    return {
      ...health,
      operational: runtime.operational || health.operational,
      provider_analytics: ops.provider_analytics || health.provider_analytics,
      provider_ops: ops.provider_ops || health.provider_ops,
      operational_alerts: ops.operational_alerts || health.operational_alerts,
      pipeline_observability: ops.pipeline_observability || health.pipeline_observability,
    };
  }

  async function checkAlertsOnly() {
    if (open) return;
    try {
      const runtime = config.getRuntimeState ? config.getRuntimeState() : null;
      if (runtime) {
        const data = {
          health: buildHealthFromRuntime(runtime),
          explanations: runtime.explanations || {},
        };
        updateAlertDot(computeUnread(data));
        if (!lastAlertSignature) lastAlertSignature = alertSignature(data);
        return;
      }
      const [health, explanations] = await Promise.all([
        fetchJson('/api/health', false),
        fetchJson('/api/debug/explanations', true).catch(() => ({})),
      ]);
      const data = { health, explanations };
      updateAlertDot(computeUnread(data));
      if (!lastAlertSignature) lastAlertSignature = alertSignature(data);
    } catch (e) {
      /* silent background check */
    }
  }

  function buildTimeline(health, delta, routing, quality, compression, explanations) {
    const items = [];
    const push = (label, detail) => {
      items.push({
        time: new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' }),
        label,
        detail: detail || '',
      });
    };

    (delta.delta_reasons || []).forEach((r) => push('Delta detected', r));
    if (delta.reuse_previous) push('Analysis skipped', 'Reused prior intelligence');
    if (delta.why_ran_or_skipped) push('Delta gate', delta.why_ran_or_skipped);

    const gemini = (compression.gemini_decision || {});
    if (gemini.used) push('Gemini compression', `${gemini.input_tokens || '?'} → ${gemini.output_tokens || '?'} tok`);
    else if (gemini.skipped) push('Gemini skipped', gemini.decision_reason || 'regime preserve');
    else if (gemini.passthrough) push('Compression', 'Passthrough — input below threshold');

    const expl = (explanations.latest && explanations.latest.explanations) || {};
    if (expl.why_signal_preserved) push('Preservation', expl.why_signal_preserved);
    if (expl.why_regime_changed) push('Regime', expl.why_regime_changed);

    const route = routing.why_gemini_or_claude || {};
    if (route.claude_ran) push('Claude synthesis', route.claude_model || 'triggered');
    else if (route.skipped_reason) push('Claude skipped', route.skipped_reason);

    (routing.routing_events || []).slice(-4).forEach((ev) => {
      push(ev.event || 'routing', `${ev.tier || ''} ${ev.use_case || ''} ${ev.reason || ''}`.trim());
    });

    if (quality.intelligence_quality_score != null) {
      push('Quality score', fmtScore(quality.intelligence_quality_score));
    }

    if (health.delta_trigger_reason && health.delta_trigger_reason !== 'none') {
      push('Watchdog delta', health.delta_trigger_reason);
    }

    return items.slice(-14).reverse();
  }

  function renderStatGrid(stats) {
    return stats
      .map(
        (s) => `
      <div class="ai-ops-stat">
        <span class="ai-ops-stat-label">${escapeHtml(s.label)}</span>
        <span class="ai-ops-stat-value ${s.cls || ''}">${escapeHtml(s.value)}</span>
      </div>`
      )
      .join('');
  }

  function renderTimeline(items) {
    if (!items.length) {
      return '<div class="ai-ops-empty">No recent AI events — run an analysis cycle.</div>';
    }
    return items
      .map(
        (it) => `
      <div class="ai-ops-timeline-row">
        <span class="ai-ops-time">${escapeHtml(it.time)}</span>
        <div>
          <div class="ai-ops-timeline-label">${escapeHtml(it.label)}</div>
          <div class="ai-ops-timeline-detail">${escapeHtml(it.detail)}</div>
        </div>
      </div>`
      )
      .join('');
  }

  function renderList(lines, emptyMsg) {
    if (!lines || !lines.length) return `<div class="ai-ops-empty">${escapeHtml(emptyMsg)}</div>`;
    return `<ul class="ai-ops-list">${lines.map((l) => `<li>${escapeHtml(l)}</li>`).join('')}</ul>`;
  }

  function renderPanel(data) {
    const health = data.health || {};
    const obs = health.pipeline_observability || {};
    const budget = health.ai_budget || {};
    const quality = data.quality || {};
    const preservation = data.preservation || {};
    const routing = data.routing || {};
    const delta = data.delta || {};
    const compression = data.compression || {};
    const explanations = data.explanations || {};
    const expl = (explanations.latest && explanations.latest.explanations) || {};
    const warnings = (explanations.latest && explanations.latest.warnings) || [];

    const cacheEntries = ((routing.cache || {}).entries) ?? '—';
    const cacheHits = (routing.routing_events || []).filter((e) => e.event === 'cache_hit').length;
    const cacheRate = routing.routing_events && routing.routing_events.length
      ? `${Math.round((cacheHits / routing.routing_events.length) * 100)}%`
      : '—';

    const intelFresh = (health.source_status && health.source_status.intelligence) || {};
    const jobs = health.running_jobs || {};

    const operational = health.operational || {};
    $('aiOpsStatusGrid').innerHTML = renderStatGrid([
      {
        label: 'Ops mode',
        value: operational.display_status || health.operational_status || '—',
        cls: operational.night_mode ? '' : 'ai-ops-ok',
      },
      { label: 'AI Budget', value: `$${budget.spent ?? '—'} / $${budget.limit ?? '—'}` },
      { label: 'Remaining', value: `$${obs.ai_budget_remaining ?? budget.remaining ?? '—'}` },
      { label: 'Regime', value: health.market_regime || obs.market_regime || '—' },
      { label: 'Compression', value: health.compression_mode || obs.compression_mode || '—' },
      {
        label: 'Quality IQ',
        value: fmtScore(health.last_quality_score ?? quality.intelligence_quality_score),
        cls: scoreClass(health.last_quality_score ?? quality.intelligence_quality_score, 0.55),
      },
      { label: 'Cache', value: `${cacheRate} (${cacheEntries} entries)` },
      {
        label: 'Low-cost',
        value: routing.low_cost_mode ? 'ON' : 'OFF',
        cls: routing.low_cost_mode ? 'ai-ops-warn' : '',
      },
      { label: 'Cycle', value: obs.latest_cycle_id || preservation.cycle_id || '—' },
      { label: 'Watchdog', value: obs.watchdog_mode || health.watchdog_mode || '—' },
      {
        label: 'Sent diversity',
        value: fmtScore(quality.sentiment_diversity_score ?? obs.sentiment_diversity_score),
        cls: scoreClass(quality.sentiment_diversity_score ?? obs.sentiment_diversity_score, 0.45),
      },
      {
        label: 'Novelty',
        value: fmtScore(quality.novelty_avg_score ?? obs.novelty_avg_score),
        cls: scoreClass(quality.novelty_avg_score ?? obs.novelty_avg_score, 3.0),
      },
      {
        label: 'Truncation',
        value: fmtScore(quality.truncation_severity ?? quality.compression_ratio),
        cls: scoreClass(quality.truncation_severity ?? quality.compression_ratio, 0.25),
      },
      {
        label: 'Market src',
        value: obs.market_active_source || '—',
        cls: obs.market_source_degraded ? 'ai-ops-warn' : '',
      },
      {
        label: 'Angel/Yahoo',
        value: `${obs.market_angel_count ?? '—'}/${obs.market_yahoo_fallback_count ?? '—'}`,
      },
    ]);

    $('aiOpsTimeline').innerHTML = renderTimeline(
      buildTimeline(health, delta, routing, quality, compression, explanations)
    );

    const contraLines = ((preservation.contradiction_blocks || {}).contradictions || []).map(
      (c) => `[${c.type}] ${c.summary}`
    );
    const bypass = (preservation.bypassed_compression_items || []).map(
      (b) => `${b.kind || '?'} ${b.ticker || ''} impact=${b.impact_score}`
    );
    const rawPreview = String(preservation.raw_signals_preserved || '')
      .split('\n')
      .filter(Boolean)
      .slice(0, 6);

    $('aiOpsPreservation').innerHTML =
      renderList(contraLines, 'No active contradictions') +
      (bypass.length
        ? `<div class="ai-ops-subhead">Bypass</div>${renderList(bypass, '')}`
        : '') +
      (rawPreview.length
        ? `<div class="ai-ops-subhead">Raw signals</div>${renderList(rawPreview, '')}`
        : '');

    $('aiOpsRouting').innerHTML = renderList(
      [
        expl.why_claude_ran,
        expl.why_gemini_used,
        expl.why_cache_skipped,
        routing.last_expensive_call_reason
          ? `Last expensive: ${JSON.stringify(routing.last_expensive_call_reason).slice(0, 120)}`
          : null,
      ].filter(Boolean),
      'No routing explainability yet'
    );

    const prov = (routing.providers || health.provider_ops || {});
    const envDiag = prov.env_diagnostics || health.provider_ops?.env_diagnostics || {};
    const degraded = prov.degraded || {};
    const gem = (prov.providers || {}).gemini || {};
    const groq = (prov.providers || {}).groq || {};
    const claude = (prov.providers || {}).claude || {};
    const slotLine = (p, label) => {
      const active = p.active_slot || '—';
      const st = p.degraded ? 'degraded' : 'healthy';
      const fails = p.total_failovers || 0;
      return `${label}: ${active} · ${st} · failovers ${fails}`;
    };
    const slotDetails = []
      .concat((gem.slots || []).map((s) => `${s.slot_id} → ${s.status}${s.cooldown_remaining_sec ? ` (${s.cooldown_remaining_sec}s)` : ''}`))
      .concat((groq.slots || []).map((s) => `${s.slot_id} → ${s.status}${s.cooldown_remaining_sec ? ` (${s.cooldown_remaining_sec}s)` : ''}`));
    $('aiOpsProviders').innerHTML =
      renderStatGrid([
        { label: 'Mode', value: degraded.mode || '—', cls: degraded.mode && degraded.mode !== 'normal' ? 'ai-ops-warn' : '' },
        { label: 'Gemini', value: `${envDiag.gemini_loaded ?? '—'} loaded` },
        { label: 'Groq', value: `${envDiag.groq_loaded ?? '—'} loaded` },
        { label: 'Claude', value: envDiag.claude_loaded ? 'yes' : 'no', cls: envDiag.claude_loaded ? '' : 'ai-ops-warn' },
        { label: 'Conv route', value: envDiag.conversational_provider || prov.active_conversational_provider || '—' },
      ]) +
      renderList(
        [
          slotLine(gem, 'Gemini pool'),
          slotLine(groq, 'Groq pool'),
          claude.active_slot ? 'Claude → strategist standby' : 'Claude → no key',
          envDiag.gemini_loaded === 0 ? '⚠ Gemini env missing (GOOGLE_API_KEY_1/2/3)' : null,
          envDiag.groq_loaded === 0 ? '⚠ Groq env missing (GROQ_API_KEY_1/2/3)' : null,
          ...(envDiag.typo_warnings || []).map((w) => `⚠ ${w}`),
          ...(envDiag.warnings || []).slice(0, 3).map((w) => `⚠ ${w}`),
          degraded.enrichment_message ? 'Enrichment fallback active' : null,
        ].filter(Boolean),
        'Provider data unavailable'
      ) +
      (slotDetails.length
        ? `<div class="ai-ops-subhead">Pool slots</div>${renderList(slotDetails.slice(0, 8), '')}`
        : '');

    const rt = health.provider_analytics || {};
    const rtProv = rt.providers || {};
    const rtGem = rtProv.gemini || {};
    const rtGroq = rtProv.groq || {};
    const rtClaude = rtProv.claude || {};
    const fmtLat = (ms) => (ms ? `${(ms / 1000).toFixed(1)}s` : '—');
    const runtimeLines = (rt.summary_lines || []).length
      ? rt.summary_lines
      : [
          `Gemini: ${rtGem.requests_today || 0} requests · ${rtGem.failovers || 0} failovers · avg ${fmtLat(rtGem.avg_latency_ms)}`,
          `Groq: ${rtGroq.requests_today || 0} requests · ${rtGroq.failovers || 0} failovers · avg ${fmtLat(rtGroq.avg_latency_ms)}`,
          `Claude: ${rt.claude_strategic_runs || 0} strategic runs · avg ${fmtLat(rtClaude.avg_latency_ms)}`,
        ];
    const runtimeEl = $('aiOpsRuntime');
    if (runtimeEl) {
      runtimeEl.innerHTML =
        renderStatGrid([
          { label: 'AI uptime', value: rt.ai_uptime_pct != null ? `${rt.ai_uptime_pct}%` : '—',
            cls: scoreClass(rt.ai_uptime_pct, 95) },
          { label: 'Degraded', value: rt.degraded_mode || degraded.mode || 'normal',
            cls: (rt.degraded_mode || degraded.mode) !== 'normal' ? 'ai-ops-warn' : '' },
          { label: 'Cache hits', value: String(rt.cache_hits_today ?? '—') },
          { label: 'TG throttle', value: String(rt.throttle_blocks_today ?? '—'),
            cls: (rt.throttle_blocks_today || 0) > 0 ? 'ai-ops-warn' : '' },
          { label: 'Conv load', value: rt.conversational_load && rt.conversational_load.pct
            ? Object.entries(rt.conversational_load.pct).map(([k, v]) => `${k} ${v}%`).join(' · ')
            : '—' },
          { label: 'Claude strat', value: String(rt.claude_strategic_runs ?? '—') },
        ]) +
        `<div class="ai-ops-subhead">Requests / provider</div>${renderList(runtimeLines, 'No AI requests yet today')}` +
        `<div class="ai-ops-subhead">Quota pressure</div>${renderList(
          ['gemini', 'groq', 'claude'].map((n) => {
            const p = rtProv[n] || {};
            const req = p.requests_today || 0;
            const qf = p.quota_failures || 0;
            const pct = req ? Math.round(100 * qf / req) : 0;
            return `${n}: ${qf} quota events (${pct}% pressure)`;
          }),
          'No quota events'
        )}` +
        `<div class="ai-ops-subhead">Uptime scores</div>${renderList(
          ['gemini', 'groq', 'claude'].map((n) => {
            const p = rtProv[n] || {};
            return `${n}: ${p.uptime_score != null ? p.uptime_score : '—'}% · degraded ${p.degraded_count || 0}`;
          }),
          '—'
        )}`;
    }

    const tg = data.telegram || {};
    const tgObs = tg.telegram_alerts || tg;
    const sentToday = tgObs.alerts_sent_today ?? 0;
    const suppressed = tgObs.suppressed_today ?? 0;
    const dupes = tgObs.duplicate_blocks ?? 0;
    const lowConf = tgObs.low_confidence_skips ?? 0;
    const cooldowns = tgObs.cooldown_blocks ?? 0;
    const recentSent = (tgObs.recent_sent || []).slice(-6);
    const recentSup = (tgObs.recent_suppressed || []).slice(-4);
    const recentLines = [
      ...recentSent.map((e) => `[SENT] ${e.category || ''} ${e.detail || ''}`.trim()),
      ...recentSup.map((e) => `[SKIP] ${e.reason || ''} ${e.category || ''} ${e.detail || ''}`.trim()),
    ];

    $('aiOpsTelegram').innerHTML =
      renderStatGrid([
        { label: 'Sent today', value: String(sentToday) },
        { label: 'Suppressed', value: String(suppressed), cls: suppressed > 0 ? 'ai-ops-warn' : '' },
        { label: 'Dup blocks', value: String(dupes) },
        { label: 'Low conf skip', value: String(lowConf) },
        { label: 'Cooldown blk', value: String(cooldowns) },
        { label: 'Emergency', value: String(tgObs.emergency_triggers ?? 0) },
        { label: 'Mode', value: tg.night_mode ? 'NIGHT' : tg.after_hours ? 'AFTER HOURS' : 'MARKET' },
      ]) +
      `<div class="ai-ops-subhead">Recent</div>${renderList(recentLines, 'No alert events yet today')}`;

    const rel = data.reliability || {};
    const exec = rel.execution || {};
    const hist = rel.confidence_histogram || exec.confidence_distribution || {};
    const histLines = Object.entries(hist).map(([k, v]) => `${k}: ${v}`);
    const relEl = $('aiOpsReliability');
    if (relEl) {
      relEl.innerHTML =
        renderStatGrid([
          {
            label: 'Reliability IQ',
            value: fmtScore(exec.ai_reliability_score ?? obs.ai_reliability_score),
            cls: scoreClass(exec.ai_reliability_score ?? obs.ai_reliability_score, 0.55),
          },
          { label: 'Hallucinations', value: String(exec.hallucination_detections ?? obs.hallucination_detections ?? 0),
            cls: (exec.hallucination_detections ?? 0) > 0 ? 'ai-ops-warn' : '' },
          { label: 'Schema fails', value: String(exec.schema_failures ?? obs.schema_failures ?? 0) },
          { label: 'Retries', value: String(exec.retry_counts ?? obs.validation_retries ?? 0) },
          { label: 'Fallbacks', value: String(exec.safe_fallbacks ?? obs.safe_fallbacks ?? 0),
            cls: (exec.safe_fallbacks ?? 0) > 0 ? 'ai-ops-warn' : '' },
          { label: 'Avg latency', value: exec.avg_ai_latency_ms != null ? `${exec.avg_ai_latency_ms}ms` : '—' },
          { label: 'Cache hit', value: exec.cache_hit_rate != null ? `${Math.round(exec.cache_hit_rate * 100)}%` : '—' },
          { label: 'TG suppress', value: exec.telegram_suppression_rate != null ? `${Math.round(exec.telegram_suppression_rate * 100)}%` : '—' },
        ]) +
        `<div class="ai-ops-subhead">Confidence distribution</div>${renderList(histLines, 'No confidence samples yet')}` +
        `<div class="ai-ops-subhead">Recent reliability events</div>${renderList(
          (rel.recent_logs || []).slice(-6).map((e) => `${e.event || '?'} ${e.cycle_id || ''}`.trim()),
          'No reliability events logged yet'
        )}`;
    }

    const cal = data.calibration || {};
    const calEl = $('aiOpsCalibration');
    if (calEl) {
      const bands = ((cal.confidence_calibration || {}).bands || []).slice(0, 6);
      const regimes = ((cal.regime_performance || {}).regimes || []).slice(0, 6);
      const types = ((cal.signal_quality || {}).signal_types || []).slice(0, 6);
      const bandLines = bands.map(
        (b) => `${b.confidence_band}: ${b.precision_pct}% precision (n=${b.samples}, move ${b.avg_move_pct}%)`
      );
      const regimeLines = regimes.map(
        (r) => `${r.regime}: ${r.alert_precision_pct}% alert precision (n=${r.samples})`
      );
      const typeLines = types.map(
        (t) => `${t.signal_type}: ${t.precision_pct}% precision (n=${t.samples})`
      );
      const memory = cal.intelligence_memory || {};
      calEl.innerHTML =
        renderStatGrid([
          {
            label: 'Signal accuracy',
            value: cal.signal_accuracy_pct != null ? `${cal.signal_accuracy_pct}%` : '—',
            cls: cal.signal_accuracy_pct != null && cal.signal_accuracy_pct < 50 ? 'ai-ops-warn' : '',
          },
          {
            label: 'TG precision',
            value: cal.telegram_precision_proxy != null ? `${cal.telegram_precision_proxy}%` : '—',
          },
          {
            label: 'Min samples',
            value: String(cal.min_samples_global ?? '—'),
          },
          {
            label: 'Status',
            value: cal.status || '—',
            cls: cal.status === 'degraded' ? 'ai-ops-warn' : '',
          },
        ]) +
        `<div class="ai-ops-subhead">Confidence calibration</div>${renderList(bandLines, 'Insufficient samples — collecting outcomes')}` +
        `<div class="ai-ops-subhead">Regime performance</div>${renderList(regimeLines, 'No regime stats yet')}` +
        `<div class="ai-ops-subhead">Top signal types</div>${renderList(typeLines, 'No signal type stats yet')}` +
        `<div class="ai-ops-subhead">What AI gets right</div>${renderList(
          (memory.successful_patterns || []).slice(0, 4),
          'Patterns will appear after enough evaluated outcomes'
        )}`;
    }

    const lifecycle = data.lifecycle || {};
    const lcEl = $('aiOpsLifecycle');
    if (lcEl) {
      const states = lifecycle.prediction_states || {};
      const stateLines = Object.entries(states).map(([k, v]) => `${k}: ${v}`);
      const calSnap = lifecycle.calibration || {};
      const pipelineStatus = lifecycle.pipeline_status || (lifecycle.evaluation_cycle_complete ? 'COMPLETE' : 'STALE');
      const statsAge = lifecycle.stats_age_minutes != null
        ? `${lifecycle.stats_age_minutes}m`
        : ((data.sourceStatus && data.sourceStatus.stats && data.sourceStatus.stats.age_seconds != null)
          ? `${Math.round(data.sourceStatus.stats.age_seconds / 60)}m`
          : null);
      const historyAge = lifecycle.history_age_minutes != null
        ? `${lifecycle.history_age_minutes}m`
        : ((data.sourceStatus && data.sourceStatus.history && data.sourceStatus.history.age_seconds != null)
          ? `${Math.round(data.sourceStatus.history.age_seconds / 60)}m`
          : null);
      const statusCls = pipelineStatus === 'COMPLETE' ? 'ai-ops-ok'
        : pipelineStatus === 'RECOVERING' ? 'ai-ops-warn'
        : pipelineStatus === 'RUNNING' ? 'ai-ops-warn'
        : pipelineStatus === 'FAILED' ? 'ai-ops-warn'
        : 'ai-ops-warn';
      lcEl.innerHTML =
        renderStatGrid([
          {
            label: 'Lifecycle',
            value: pipelineStatus,
            cls: statusCls,
          },
          {
            label: 'EOD cycle',
            value: lifecycle.evaluation_cycle_complete ? 'COMPLETE' : (pipelineStatus === 'RUNNING' ? 'RUNNING' : 'PENDING'),
            cls: lifecycle.evaluation_cycle_complete ? 'ai-ops-ok' : 'ai-ops-warn',
          },
          {
            label: 'Active',
            value: String(lifecycle.active_predictions ?? lifecycle.active_count ?? '—'),
          },
          {
            label: 'Archived',
            value: String(lifecycle.archived_predictions ?? lifecycle.archived_count ?? '—'),
          },
          {
            label: 'Invalidated',
            value: String(lifecycle.stale_invalidated ?? '—'),
            cls: (lifecycle.stale_invalidated || 0) > 0 ? 'ai-ops-warn' : '',
          },
          {
            label: 'Unresolved',
            value: String(lifecycle.unresolved_predictions ?? '—'),
            cls: (lifecycle.unresolved_predictions || 0) > 0 ? 'ai-ops-warn' : '',
          },
          {
            label: 'Review',
            value: lifecycle.review_fresh ? 'FRESH' : 'STALE',
            cls: lifecycle.review_fresh ? 'ai-ops-ok' : 'ai-ops-warn',
          },
          {
            label: 'Calibration',
            value: lifecycle.calibration_fresh ? 'FRESH' : 'WAITING',
            cls: lifecycle.calibration_fresh ? 'ai-ops-ok' : 'ai-ops-warn',
          },
          {
            label: 'Win rate',
            value: calSnap.win_rate != null ? `${calSnap.win_rate}%` : '—',
          },
          {
            label: 'Exports',
            value: lifecycle.exports_fresh ? 'SYNCED' : 'STALE',
            cls: lifecycle.exports_fresh ? 'ai-ops-ok' : 'ai-ops-warn',
          },
        ]) +
        `<div class="ai-ops-subhead">Status</div>${renderList(
          [
            lifecycle.current_stage ? `Stage: ${lifecycle.current_stage}` : null,
            lifecycle.last_eod_cycle_at ? `Last cycle: ${lifecycle.last_eod_cycle_at.slice(0, 19)}` : null,
            lifecycle.last_failure_reason ? `Last failure: ${lifecycle.last_failure_reason}` : null,
            lifecycle.last_successful_eod ? `Last successful EOD: ${lifecycle.last_successful_eod.slice(0, 19)}` : null,
            lifecycle.last_stats_export ? `Stats export: ${lifecycle.last_stats_export.slice(0, 19)}` : null,
            lifecycle.last_history_export ? `History export: ${lifecycle.last_history_export.slice(0, 19)}` : null,
            lifecycle.last_calibration_export ? `Calibration export: ${lifecycle.last_calibration_export.slice(0, 19)}` : null,
            lifecycle.recovery_reason ? `Recovery: ${lifecycle.recovery_reason}` : null,
            statsAge != null ? `Stats export age: ${statsAge}` : null,
            historyAge != null ? `History export age: ${historyAge}` : null,
            lifecycle.message,
          ].filter(Boolean),
          'Post-market evaluation runs at 15:45 IST'
        )}` +
        (lifecycle.scheduler_tasks && lifecycle.scheduler_tasks.tasks
          ? `<div class="ai-ops-subhead">Scheduler tasks (IST)</div>${renderList(
              lifecycle.scheduler_tasks.tasks.slice(0, 8).map(
                (t) => `${t.name}: ${t.status} @ ${t.schedule}`
              ),
              'Scheduler registry unavailable'
            )}`
          : '') +
        `<div class="ai-ops-subhead">Prediction states</div>${renderList(stateLines, 'No evaluated predictions yet')}`;
    }

    const adaptive = cal.adaptive_calibration || {};
    const adaptEl = $('aiOpsAdaptive');
    if (adaptEl) {
      const tuning = adaptive.adaptive_tuning || [];
      const regimeLearn = adaptive.regime_learning || [];
      const activeAdj = adaptive.active_adjustments || [];
      adaptEl.innerHTML =
        renderStatGrid([
          {
            label: 'Learning',
            value: adaptive.learning_active ? 'ACTIVE' : 'COLLECTING',
            cls: adaptive.learning_active ? 'ai-ops-ok' : 'ai-ops-warn',
          },
          {
            label: 'Realism',
            value: adaptive.confidence_realism_line || '—',
            cls: String(adaptive.confidence_realism_line || '').includes('inflation') ? 'ai-ops-warn' : '',
          },
          {
            label: 'Realism score',
            value: adaptive.confidence_realism_score != null ? String(adaptive.confidence_realism_score) : '—',
          },
          {
            label: 'Last adapt',
            value: adaptive.last_applied_at ? adaptive.last_applied_at.slice(0, 10) : '—',
          },
        ]) +
        `<div class="ai-ops-subhead">Active tuning</div>${renderList(
          tuning.length ? tuning : activeAdj.map((a) => `${a.parameter || a.key} ${a.cumulative_delta_pct >= 0 ? '+' : ''}${a.cumulative_delta_pct != null ? a.cumulative_delta_pct : a.pct_display || ''}%`),
          'No active adjustments — within baseline'
        )}` +
        `<div class="ai-ops-subhead">Regime learning</div>${renderList(regimeLearn, 'Regime patterns building…')}` +
        `<div class="ai-ops-subhead">Safety caps</div>${renderList(
          [
            adaptive.safety_caps ? `Max/cycle: ${Math.round((adaptive.safety_caps.max_delta_per_cycle || 0.02) * 100)}%` : null,
            adaptive.safety_caps ? `Max cumulative: ${Math.round((adaptive.safety_caps.max_cumulative || 0.15) * 100)}%` : null,
            adaptive.safety_caps ? `Cooldown: ${adaptive.safety_caps.cooldown_hours || 24}h` : null,
          ].filter(Boolean),
          '—'
        )}`;
    }

    const intelAge = intelFresh.age_seconds;
    const intelStale = intelFresh.status === 'stale';
    const intelIdle = intelFresh.status === 'idle' || operational.expect_quiet_collectors;
    const staleThreshold = health.watchdog_stale_threshold_seconds ?? obs.watchdog_stale_threshold_seconds;
    const opAlerts = health.operational_alerts || {};
    const opEvents = (opAlerts.recent_events || []).slice(0, 6);
    const opEventLines = opEvents.map((e) => {
      const tg = e.telegram && e.telegram !== 'not_evaluated' ? ` · TG:${e.telegram}` : '';
      return `${e.severity || '?'} · ${e.code || 'event'} — ${(e.message || '').slice(0, 72)}${tg}`;
    });
    $('aiOpsHealth').innerHTML = renderList(
      [
        `Intelligence: ${intelFresh.status || 'unknown'}${intelAge != null ? ` (${intelAge}s)` : ''}`,
        operational.display_message ? `Session: ${operational.display_message}` : null,
        staleThreshold != null ? `Watchdog threshold: ${staleThreshold}s (${health.watchdog_mode || obs.watchdog_mode || '—'})` : null,
        intelStale && !intelIdle ? '⚠ Stale intelligence — watchdog may recover (market hours)' : null,
        intelIdle && !intelStale ? '🌙 Collectors idle — expected outside market session' : null,
        opAlerts.counters
          ? `Alert router: ${opAlerts.counters.telegram_sent || 0} TG sent · ${opAlerts.counters.telegram_suppressed || 0} suppressed · ${opAlerts.counters.ops_logged || 0} logged`
          : null,
        quality.repetition_suppressed_count != null
          ? `Repetition suppressed: ${quality.repetition_suppressed_count}`
          : obs.repetition_suppressed_count != null
            ? `Repetition suppressed: ${obs.repetition_suppressed_count}`
            : null,
        delta.semantic_changed === false && delta.hash_changed
          ? 'Cache: semantic hash stable (full hash noise ignored)'
          : null,
        obs.market_source_degraded ? '⚠ Market source degraded — preserved snapshots in use' : null,
        obs.market_active_source ? `Market feed: ${obs.market_active_source} (Angel ${obs.market_angel_count ?? 0} / Yahoo ${obs.market_yahoo_fallback_count ?? 0})` : null,
        `Scheduler lock: ${jobs.master_scheduler ? (jobs.master_scheduler.alive ? 'running' : 'idle') : '—'}`,
        `Analyzer lock: ${jobs.master_analyzer ? (jobs.master_analyzer.alive ? 'running' : 'idle') : '—'}`,
        health.delta_trigger_reason && health.delta_trigger_reason !== 'none'
          ? `Delta trigger: ${health.delta_trigger_reason}`
          : null,
        warnings.length ? `⚠ ${warnings.length} quality warning(s)` : null,
      ].filter(Boolean),
      'Health data unavailable'
    ) +
    (opEventLines.length
      ? `<div class="ai-ops-subhead">Operational events (OPS only)</div>${renderList(opEventLines, 'No operational events yet')}`
      : '');

    if (warnings.length) {
      $('aiOpsWarnings').innerHTML = warnings
        .map((w) => {
          const label = w.code === 'overtruncation_risk' ? 'OVERTRUNCATION'
            : w.code === 'low_novelty' ? 'LOW NOVELTY'
            : w.code === 'sentiment_collapse_risk' ? 'SENTIMENT COLLAPSE'
            : w.code;
          return `<div class="ai-ops-warning-chip">${escapeHtml(label)}: ${fmtScore(w.value)}</div>`;
        })
        .join('');
      $('aiOpsWarnings').style.display = 'flex';
    } else {
      $('aiOpsWarnings').innerHTML = '';
      $('aiOpsWarnings').style.display = 'none';
    }

    const runtimeTs = (global.RuntimeManager && RuntimeManager.formatTimestamp)
      ? RuntimeManager.formatTimestamp()
      : new Date().toLocaleTimeString('en-IN');
    $('aiOpsFooter').textContent = `Updated ${runtimeTs} · ${obs.latest_cycle_id || 'no cycle'}`;
  }

  async function refreshPanel() {
    const statusEl = $('aiOpsLoadStatus');
    if (statusEl) statusEl.textContent = 'Syncing…';
    try {
      const runtime = config.getRuntimeState ? config.getRuntimeState() : null;
      const health = buildHealthFromRuntime(runtime);
      const explanations = (runtime && runtime.explanations) || {};

      const [preservation, compression, routing, delta, quality, telegram, reliability, calibration, lifecycle] = await Promise.all([
        fetchJson('/api/debug/preservation', true),
        fetchJson('/api/debug/compression', true),
        fetchJson('/api/debug/ai-routing', true),
        fetchJson('/api/debug/delta-analysis', true),
        fetchJson('/api/debug/quality', true),
        fetchJson('/api/debug/telegram-alerts', true).catch(() => ({})),
        fetchJson('/api/debug/reliability', true).catch(() => ({})),
        fetchJson('/api/debug/calibration', true).catch(() => ({})),
        fetchJson('/api/debug/lifecycle', true).catch(() => ({})),
      ]);

      const debugLc = lifecycle.lifecycle || lifecycle;
      const runtimeLc = runtime && (runtime.lifecycle_summary || (runtime.panels && runtime.panels.lifecycle));
      const mergedLc = Object.assign({}, runtimeLc || {}, debugLc || {});

      const data = {
        health,
        preservation,
        compression,
        routing,
        delta,
        quality,
        explanations,
        telegram,
        reliability,
        calibration,
        lifecycle: mergedLc,
        sourceStatus: (runtime && runtime.source_status) || {},
      };
      renderPanel(data);
      markAlertsSeen(data);
      if (statusEl) statusEl.textContent = '';
    } catch (e) {
      if (statusEl) statusEl.textContent = 'Offline';
      $('aiOpsStatusGrid').innerHTML = `<div class="ai-ops-empty">Could not load AI ops: ${escapeHtml(e.message)}</div>`;
    }
  }

  function startPolling() {
    stopPolling();
    pollTimer = setInterval(refreshPanel, POLL_MS);
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  function startAlertPolling() {
    /* Alerts driven by RuntimeManager subscription — no independent timer. */
  }

  function onRuntimeUpdate(runtime) {
    if (!runtime) return;
    if (open) {
      refreshPanel();
    } else {
      const data = {
        health: buildHealthFromRuntime(runtime),
        explanations: runtime.explanations || {},
      };
      updateAlertDot(computeUnread(data));
    }
  }

  function openPanel() {
    open = true;
    $('aiOpsDrawer').classList.add('open');
    $('aiOpsBackdrop').classList.add('open');
    if (!loadedOnce) {
      loadedOnce = true;
      refreshPanel();
    } else {
      refreshPanel();
    }
    startPolling();
  }

  function closePanel() {
    open = false;
    $('aiOpsDrawer').classList.remove('open');
    $('aiOpsBackdrop').classList.remove('open');
    stopPolling();
    checkAlertsOnly();
  }

  function togglePanel() {
    if (open) closePanel();
    else openPanel();
  }

  function bindUi() {
    $('aiOpsBtn').addEventListener('click', togglePanel);
    $('aiOpsClose').addEventListener('click', closePanel);
    $('aiOpsBackdrop').addEventListener('click', closePanel);
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && open) closePanel();
    });
  }

  function init(opts) {
    config.getApiBase = opts.getApiBase || config.getApiBase;
    config.getHeaders = opts.getHeaders || config.getHeaders;
    config.getRuntimeState = opts.getRuntimeState || config.getRuntimeState;
    bindUi();
    if (opts.subscribeRuntime) {
      runtimeUnsub = opts.subscribeRuntime(onRuntimeUpdate);
    }
    checkAlertsOnly();
  }

  global.AIOpsPanel = {
    init,
    open: openPanel,
    close: closePanel,
    toggle: togglePanel,
    refresh: refreshPanel,
    checkAlerts: checkAlertsOnly,
    onRuntimeUpdate,
  };
})(window);
