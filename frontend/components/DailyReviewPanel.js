/**
 * Daily Intelligence Review — strategic end-of-day journal (not OPS debug).
 */
(function (global) {
  'use strict';

  let config = { getApiBase: () => '', getHeaders: () => ({}) };
  let open = false;

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

  function fmtPct(v) {
    if (v == null || v === '') return '—';
    const n = Number(v);
    return Number.isFinite(n) ? `${n}%` : escapeHtml(v);
  }

  async function fetchReview(rebuild) {
    const base = config.getApiBase().replace(/\/$/, '');
    const q = rebuild ? '?rebuild=1' : '';
    const res = await fetch(base + '/api/daily-review' + q, {
      method: 'GET',
      headers: config.getHeaders(),
    });
    if (!res.ok) throw new Error(`daily-review → ${res.status}`);
    return res.json();
  }

  function stat(label, value, cls) {
    return `
      <div class="ai-review-stat">
        <span class="ai-review-stat-label">${escapeHtml(label)}</span>
        <span class="ai-review-stat-value ${cls || ''}">${escapeHtml(value)}</span>
      </div>`;
  }

  function renderReview(data) {
    const day = data.market_day_classification || {};
    const perf = data.performance_summary || {};
    const hi = data.highlights || {};
    const regime = data.regime_analysis || {};
    const tg = data.telegram || {};
    const summary = data.daily_summary || {};
    const warnings = data.warnings || [];

    $('reviewHero').innerHTML = `
      <div class="ai-review-day-badge">${escapeHtml(day.label || 'MIXED SESSION')}</div>
      <div class="ai-review-hero-sub">${escapeHtml(day.reason || '')}</div>
      <div class="ai-review-hero-meta">
        Regime <strong>${escapeHtml(summary.regime || day.regime || '—')}</strong>
        · IQ <strong>${summary.quality_iq != null ? summary.quality_iq : '—'}</strong>
        · ${escapeHtml(data.date || '')}
      </div>
      <div class="ai-review-observation">${escapeHtml(data.observation || '')}</div>
    `;

    $('reviewPerformance').innerHTML = `
      <div class="ai-review-stat-grid">
        ${stat('Signals', String(perf.signals_generated ?? '—'))}
        ${stat('High conf', String(perf.high_confidence_signals ?? '—'))}
        ${stat('Useful', String(perf.useful_signals ?? '—'), 'ai-review-ok')}
        ${stat('False +', String(perf.false_positives ?? '—'), perf.false_positives > 0 ? 'ai-review-warn' : '')}
        ${stat('Suppressed', String(perf.suppressed_alerts ?? '—'))}
        ${stat('Missed', String(perf.missed_opportunities ?? '—'))}
        ${stat('TG precision', fmtPct(perf.telegram_precision_pct), '')}
        ${stat('Calibration', perf.confidence_calibration_quality || '—')}
      </div>`;

    const winLines = [
      hi.best_bullish ? `BEST BULLISH: ${hi.best_bullish.label}` : null,
      hi.best_bearish ? `BEST BEARISH: ${hi.best_bearish.label}` : null,
      hi.highest_confidence_winner ? `HIGH CONF WIN: ${hi.highest_confidence_winner.label}` : null,
      hi.biggest_miss ? `FAILED: ${hi.biggest_miss.label}` : null,
      hi.worst_false_positive ? `FALSE POS: ${hi.worst_false_positive.label}` : null,
      hi.strongest_contradiction
        ? `CONTRADICTION: ${hi.strongest_contradiction.summary} — ${hi.strongest_contradiction.detail || ''}`
        : null,
    ].filter(Boolean);

    $('reviewHighlights').innerHTML = winLines.length
      ? `<ul class="ai-review-list">${winLines.map((l) => `<li>${escapeHtml(l)}</li>`).join('')}</ul>`
      : '<div class="ai-review-empty">Outcome samples still collecting — check back after market close.</div>';

    const timeline = (regime.timeline || []).map(
      (t) => `
        <div class="ai-review-timeline-row">
          <span class="ai-review-time">${escapeHtml(t.time || '—')}</span>
          <div>
            <div class="ai-review-timeline-label">${escapeHtml(t.transition || '')}</div>
            <div class="ai-review-timeline-note">${escapeHtml(t.note || '')}</div>
          </div>
        </div>`
    ).join('');

    $('reviewRegime').innerHTML =
      timeline ||
      '<div class="ai-review-empty">No regime transitions logged for this session.</div>';

    $('reviewWarnings').innerHTML = warnings.length
      ? warnings
          .map(
            (w) =>
              `<div class="ai-review-warning-chip ai-review-sev-${escapeHtml(w.severity || 'medium')}">${escapeHtml(w.message || w.code)}</div>`
          )
          .join('')
      : '<div class="ai-review-empty">No actionable quality warnings today.</div>';

    $('reviewTelegram').innerHTML = `
      <div class="ai-review-stat-grid">
        ${stat('Sent', String(tg.alerts_sent ?? 0))}
        ${stat('Suppressed', String(tg.alerts_suppressed ?? 0))}
        ${stat('Useful est', tg.estimated_useful_alerts != null ? String(tg.estimated_useful_alerts) : '—', 'ai-review-ok')}
        ${stat('Dup block', String(tg.duplicate_blocks ?? 0))}
        ${stat('Low conf skip', String(tg.low_confidence_skips ?? 0))}
        ${stat('Cooldown', String(tg.cooldown_blocks ?? 0))}
        ${stat('Emergency', String(tg.emergency_alerts ?? 0))}
        ${stat('Precision', fmtPct(tg.telegram_precision_pct))}
      </div>`;

    $('reviewSummaryBlock').textContent = data.copy_text || 'Review summary unavailable.';

    $('reviewFooter').textContent = `Generated ${data.generated_at ? new Date(data.generated_at).toLocaleTimeString('en-IN') : '—'}`;
  }

  async function refreshPanel(rebuild) {
    const statusEl = $('reviewLoadStatus');
    if (statusEl) statusEl.textContent = 'Loading…';
    try {
      const data = await fetchReview(rebuild);
      renderReview(data);
      if (statusEl) statusEl.textContent = data.status === 'degraded' ? 'Degraded' : '';
    } catch (e) {
      if (statusEl) statusEl.textContent = 'Offline';
      $('reviewHero').innerHTML = `<div class="ai-review-empty">Could not load review: ${escapeHtml(e.message)}</div>`;
    }
  }

  function closePanel() {
    open = false;
    $('reviewDrawer').classList.remove('open');
    $('reviewBackdrop').classList.remove('open');
  }

  function openPanel() {
    open = true;
    $('reviewDrawer').classList.add('open');
    $('reviewBackdrop').classList.add('open');
    refreshPanel(false);
  }

  async function copyReview() {
    const text = $('reviewSummaryBlock').textContent || '';
    try {
      await navigator.clipboard.writeText(text);
      const btn = $('reviewCopyBtn');
      if (btn) {
        const prev = btn.textContent;
        btn.textContent = 'COPIED';
        setTimeout(() => { btn.textContent = prev; }, 1500);
      }
    } catch (e) {
      /* fallback for older webviews */
      const ta = document.createElement('textarea');
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
    }
  }

  function init(opts) {
    config.getApiBase = opts.getApiBase || config.getApiBase;
    config.getHeaders = opts.getHeaders || config.getHeaders;

    const btn = $('reviewBtn');
    const closeBtn = $('reviewClose');
    const backdrop = $('reviewBackdrop');
    const copyBtn = $('reviewCopyBtn');
    const refreshBtn = $('reviewRefreshBtn');

    if (btn) btn.addEventListener('click', openPanel);
    if (closeBtn) closeBtn.addEventListener('click', closePanel);
    if (backdrop) backdrop.addEventListener('click', closePanel);
    if (copyBtn) copyBtn.addEventListener('click', copyReview);
    if (refreshBtn) refreshBtn.addEventListener('click', () => refreshPanel(true));
  }

  global.DailyReviewPanel = { init, openPanel, closePanel, refreshPanel };
})(typeof window !== 'undefined' ? window : global);
