/**
 * AI Ops / Logs — lightweight observability drawer for Trading Copilot GUI.
 * Lazy-loads debug data only when panel is open; polling stops when closed.
 */
(function (global) {
  'use strict';

  const POLL_MS = 8000;
  const ALERT_POLL_MS = 30000;
  const STORAGE_KEY = 'tradingcopilot_aiops_seen';

  let config = {
    getApiBase: () => '',
    getHeaders: () => ({}),
  };
  let open = false;
  let pollTimer = null;
  let alertTimer = null;
  let loadedOnce = false;
  let lastAlertSignature = '';

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

  async function checkAlertsOnly() {
    if (open) return;
    try {
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

    $('aiOpsStatusGrid').innerHTML = renderStatGrid([
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

    const intelAge = intelFresh.age_seconds;
    const intelStale = intelFresh.status === 'stale';
    const staleThreshold = health.watchdog_stale_threshold_seconds ?? obs.watchdog_stale_threshold_seconds;
    $('aiOpsHealth').innerHTML = renderList(
      [
        `Intelligence: ${intelFresh.status || 'unknown'}${intelAge != null ? ` (${intelAge}s)` : ''}`,
        staleThreshold != null ? `Watchdog threshold: ${staleThreshold}s (${health.watchdog_mode || obs.watchdog_mode || '—'})` : null,
        intelStale ? '⚠ Stale intelligence — watchdog may recover (regime-aware)' : null,
        quality.repetition_suppressed_count != null
          ? `Repetition suppressed: ${quality.repetition_suppressed_count}`
          : obs.repetition_suppressed_count != null
            ? `Repetition suppressed: ${obs.repetition_suppressed_count}`
            : null,
        delta.semantic_changed === false && delta.hash_changed
          ? 'Cache: semantic hash stable (full hash noise ignored)'
          : null,
        `Scheduler lock: ${jobs.master_scheduler ? (jobs.master_scheduler.alive ? 'running' : 'idle') : '—'}`,
        `Analyzer lock: ${jobs.master_analyzer ? (jobs.master_analyzer.alive ? 'running' : 'idle') : '—'}`,
        health.delta_trigger_reason && health.delta_trigger_reason !== 'none'
          ? `Delta trigger: ${health.delta_trigger_reason}`
          : null,
        warnings.length ? `⚠ ${warnings.length} quality warning(s)` : null,
      ].filter(Boolean),
      'Health data unavailable'
    );

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

    $('aiOpsFooter').textContent = `Updated ${new Date().toLocaleTimeString('en-IN')} · ${obs.latest_cycle_id || 'no cycle'}`;
  }

  async function refreshPanel() {
    const statusEl = $('aiOpsLoadStatus');
    if (statusEl) statusEl.textContent = 'Syncing…';
    try {
      const [health, preservation, compression, routing, delta, quality, explanations, telegram] = await Promise.all([
        fetchJson('/api/health', false),
        fetchJson('/api/debug/preservation', true),
        fetchJson('/api/debug/compression', true),
        fetchJson('/api/debug/ai-routing', true),
        fetchJson('/api/debug/delta-analysis', true),
        fetchJson('/api/debug/quality', true),
        fetchJson('/api/debug/explanations', true),
        fetchJson('/api/debug/telegram-alerts', true).catch(() => ({})),
      ]);

      const data = { health, preservation, compression, routing, delta, quality, explanations, telegram };
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
    if (alertTimer) return;
    alertTimer = setInterval(checkAlertsOnly, ALERT_POLL_MS);
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
    bindUi();
    checkAlertsOnly();
    startAlertPolling();
  }

  global.AIOpsPanel = {
    init,
    open: openPanel,
    close: closePanel,
    toggle: togglePanel,
    refresh: refreshPanel,
    checkAlerts: checkAlertsOnly,
  };
})(window);
