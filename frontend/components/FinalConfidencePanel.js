/**
 * Final Confidence Fusion panel (Stage 26).
 * Shadow/read-only scoring — not trade execution.
 */
(function (global) {
  'use strict';

  const REPORT_SOURCE = '/api/debug/final-confidence/report';
  const BREAKDOWN_SOURCE = '/api/debug/final-confidence';
  const CALIBRATION_SOURCE = '/api/debug/confidence-calibration';
  const WATCHLIST_SOURCE = '/api/debug/tomorrow-watchlist';
  const FETCH_MS = 12000;

  let config = {
    getApiBase: () => '',
    getHeaders: () => ({}),
  };

  function escapeHtml(text) {
    if (text == null) return '';
    return String(text)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function fmtList(items) {
    if (!items || !items.length) return '—';
    return escapeHtml(items.join(', '));
  }

  async function fetchJson(path) {
    const base = (config.getApiBase() || '').replace(/\/$/, '');
    const url = `${base}${path}${path.includes('?') ? '&' : '?'}_ts=${Date.now()}`;
    const res = await fetch(url, { headers: config.getHeaders(), cache: 'no-store' });
    if (!res.ok) throw new Error(`HTTP ${res.status} ${path}`);
    return res.json();
  }

  function decisionClass(decision) {
    const token = String(decision || '').toUpperCase();
    if (token === 'BUY_CANDIDATE') return 'fc-buy';
    if (token === 'WATCH') return 'fc-watch';
    if (token === 'AVOID') return 'fc-avoid';
    return 'fc-nodecision';
  }

  function statCard(label, value, cls) {
    return `
      <div class="fc-stat">
        <span class="fc-stat-label">${escapeHtml(label)}</span>
        <span class="fc-stat-value ${cls || ''}">${escapeHtml(String(value))}</span>
      </div>`;
  }

  function renderCandidatesTable(rows) {
    if (!rows || !rows.length) {
      return '<div class="fc-empty">No active candidates to score yet.</div>';
    }
    const body = rows.slice(0, 25).map((row) => `
      <tr>
        <td>${escapeHtml(row.ticker || '—')}</td>
        <td>${escapeHtml(row.direction || '—')}</td>
        <td>${escapeHtml(row.confidence_label || '—')}</td>
        <td class="fc-score">${escapeHtml(row.final_score != null ? row.final_score : '—')}</td>
        <td class="${decisionClass(row.decision)}">${escapeHtml(row.decision || '—')}</td>
        <td>${escapeHtml(row.total_adjustment != null ? row.total_adjustment : '—')}</td>
        <td>${fmtList(row.hard_warnings)}</td>
      </tr>`).join('');
    return `
      <table class="fc-table">
        <thead><tr>
          <th>Ticker</th><th>Direction</th><th>Confidence</th><th>Score</th><th>Decision</th><th>Adj</th><th>Hard warnings</th>
        </tr></thead>
        <tbody>${body}</tbody>
      </table>`;
  }

  function fmtRate(v) {
    if (v == null || v === '') return '—';
    const n = Number(v);
    return Number.isFinite(n) ? `${(n * 100).toFixed(1)}%` : escapeHtml(v);
  }

  function fmtError(v) {
    if (v == null || v === '') return '—';
    const n = Number(v);
    return Number.isFinite(n) ? n.toFixed(3) : escapeHtml(v);
  }

  function renderCalibrationBucketsTable(buckets) {
    if (!buckets || !buckets.length) {
      return '<div class="fc-empty">No calibration buckets yet.</div>';
    }
    const body = buckets.map((bucket) => {
      const sampleCls = bucket.sample_warning === 'low_sample' ? 'fc-cal-low-sample' : '';
      const err = bucket.calibration_error;
      let errCls = '';
      if (err != null && Number(err) <= -0.15) errCls = 'fc-cal-overconfident';
      if (err != null && Number(err) >= 0.15) errCls = 'fc-cal-underconfident';
      return `
      <tr class="${sampleCls}">
        <td>${escapeHtml(bucket.bucket || '—')}</td>
        <td>${escapeHtml(bucket.candidates != null ? bucket.candidates : '—')}</td>
        <td>${escapeHtml((bucket.wins || 0) + (bucket.losses || 0))}</td>
        <td>${fmtRate(bucket.win_rate)}</td>
        <td>${escapeHtml(bucket.avg_score != null ? bucket.avg_score : '—')}</td>
        <td class="${errCls}">${fmtError(bucket.calibration_error)}</td>
        <td>${escapeHtml(bucket.sample_warning || '—')}</td>
      </tr>`;
    }).join('');
    return `
      <table class="fc-table fc-table-compact">
        <thead><tr>
          <th>Bucket</th><th>Candidates</th><th>Resolved</th><th>Win rate</th>
          <th>Avg score</th><th>calibration_error</th><th>Sample</th>
        </tr></thead>
        <tbody>${body}</tbody>
      </table>`;
  }

  function renderCalibrationRecommendations(recommendations) {
    if (!recommendations || !recommendations.length) {
      return '<div class="fc-empty">No score adjustments recommended yet.</div>';
    }
    const body = recommendations.slice(0, 12).map((rec) => `
      <tr>
        <td>${escapeHtml(rec.bucket || '—')}</td>
        <td>${escapeHtml(rec.type || '—')}</td>
        <td>${escapeHtml(rec.strength || '—')}</td>
        <td>${escapeHtml(rec.sample_size != null ? rec.sample_size : '—')}</td>
        <td>${escapeHtml(rec.rationale || '—')}</td>
      </tr>`).join('');
    return `
      <table class="fc-table fc-table-compact">
        <thead><tr>
          <th>Bucket</th><th>Type</th><th>Strength</th><th>Sample</th><th>Rationale</th>
        </tr></thead>
        <tbody>${body}</tbody>
      </table>`;
  }

  function renderCalibrationSection(calibration) {
    if (!calibration || calibration.ok !== true) {
      return `
        <div class="fc-section">
          <div class="fc-section-title">Calibration</div>
          <div class="fc-empty">Calibration data unavailable.</div>
        </div>`;
    }
    const live = calibration.live || {};
    const historical = calibration.historical || {};
    const combined = calibration.combined || {};
    const overconfident = combined.overconfident || [];
    const underconfident = combined.underconfident || [];
    return `
      <div class="fc-section fc-calibration-section">
        <div class="fc-section-title">Calibration</div>
        <p class="fc-disclaimer fc-cal-disclaimer">Calibration is analysis only — it does not execute trades.</p>
        <div class="fc-stat-grid fc-stat-grid-4">
          ${statCard('Live resolved', live.resolved ?? 0, '')}
          ${statCard('Historical resolved', historical.resolved ?? 0, '')}
          ${statCard('Overconfident buckets', overconfident.length, 'fc-cal-overconfident')}
          ${statCard('Underconfident buckets', underconfident.length, 'fc-cal-underconfident')}
        </div>
        <div class="fc-section-subtitle">Combined buckets (${escapeHtml(combined.label || 'live first, historical fallback')})</div>
        ${renderCalibrationBucketsTable(combined.buckets || [])}
        <div class="fc-section-subtitle">Overconfident buckets</div>
        <div class="fc-cal-tags">${overconfident.length
          ? overconfident.map((b) => `<span class="fc-cal-tag fc-cal-overconfident">${escapeHtml(b.bucket)} (${fmtError(b.calibration_error)})</span>`).join(' ')
          : '—'}</div>
        <div class="fc-section-subtitle">Underconfident buckets</div>
        <div class="fc-cal-tags">${underconfident.length
          ? underconfident.map((b) => `<span class="fc-cal-tag fc-cal-underconfident">${escapeHtml(b.bucket)} (${fmtError(b.calibration_error)})</span>`).join(' ')
          : '—'}</div>
        <div class="fc-section-subtitle">Recommendations</div>
        ${renderCalibrationRecommendations(calibration.recommendations || [])}
        <div class="fc-debug-line">GET ${escapeHtml(CALIBRATION_SOURCE)}</div>
      </div>`;
  }

  function renderExternalEvidenceSection(ext, adjustment) {
    const summary = (ext && ext.external_evidence_summary) || ext || {};
    const counts = summary.counts || {};
    const stockNewsCount = summary.stock_news_count != null
      ? summary.stock_news_count
      : Object.values(counts).reduce((a, b) => a + (Number(b) || 0), 0);
    const latestTitle = (summary.latest_titles && summary.latest_titles[0])
      || (summary.items && summary.items[0] && summary.items[0].title)
      || '—';
    const adj = adjustment != null
      ? adjustment
      : (summary.score_adjustment != null ? summary.score_adjustment : 0);
    const warnings = summary.warnings && summary.warnings.length
      ? escapeHtml(summary.warnings.join(', '))
      : '—';
    return `
      <div class="fc-section-subtitle">External Evidence</div>
      <p class="fc-disclaimer fc-ext-disclaimer">External evidence is read-only and not trade execution.</p>
      <table class="fc-table fc-table-compact">
        <tbody>
          <tr><td>Stock news count</td><td>${escapeHtml(stockNewsCount)}</td></tr>
          <tr><td>Latest evidence</td><td>${escapeHtml(latestTitle)}</td></tr>
          <tr><td>Adjustment</td><td>${escapeHtml(adj)}</td></tr>
          <tr><td>Warnings</td><td>${warnings}</td></tr>
        </tbody>
      </table>`;
  }

  function renderSimulationSection(histSim) {
    if (!histSim || histSim.ok !== true) {
      return `
        <div class="fc-section-subtitle">Historical Simulation</div>
        <div class="fc-empty">No simulation evidence for this candidate.</div>`;
    }
    const adj = histSim.confidence_adjustment != null ? histSim.confidence_adjustment : '—';
    const warnings = histSim.warnings && histSim.warnings.length
      ? escapeHtml(histSim.warnings.join(', '))
      : '—';
    return `
      <div class="fc-section-subtitle">Historical Simulation</div>
      <table class="fc-table fc-table-compact">
        <tbody>
          <tr><td>Inferred strategy</td><td>${escapeHtml(histSim.inferred_strategy || '—')}</td></tr>
          <tr><td>Strategy win rate</td><td>${fmtRate(histSim.strategy_win_rate)}</td></tr>
          <tr><td>Strategy expectancy</td><td>${escapeHtml(
            histSim.strategy_expectancy_pct != null
              ? `${histSim.strategy_expectancy_pct}%`
              : '—',
          )} <span class="fc-muted">(strategy expectancy)</span></td></tr>
          <tr><td>Adjustment</td><td>${escapeHtml(adj)}</td></tr>
          <tr><td>Warnings</td><td>${warnings}</td></tr>
        </tbody>
      </table>`;
  }

  function renderScoreBreakdownList(scoreBreakdown) {
    if (!scoreBreakdown || !scoreBreakdown.length) {
      return '<div class="fc-empty">No score breakdown components.</div>';
    }
    const body = scoreBreakdown.map((item) => `
      <tr>
        <td>${escapeHtml(item.component || '—')}</td>
        <td>${escapeHtml(item.points != null ? item.points : '—')}</td>
        <td>${escapeHtml(item.reason || '—')}</td>
      </tr>`).join('');
    return `
      <table class="fc-table fc-table-compact">
        <thead><tr><th>Component</th><th>Δ</th><th>Reason</th></tr></thead>
        <tbody>${body}</tbody>
      </table>`;
  }

  function renderBreakdown(breakdown) {
    if (!breakdown || breakdown.ok !== true) {
      return '<div class="fc-empty">Score breakdown unavailable.</div>';
    }
    const adj = breakdown.adjustments || {};
    const adjRows = Object.entries(adj).map(([key, val]) => `
      <tr><td>${escapeHtml(key)}</td><td>${escapeHtml(val)}</td></tr>`).join('');
    const expl = (breakdown.explanations || []).slice(0, 12).map((line) => `
      <li>${escapeHtml(line)}</li>`).join('');
    const histSim = breakdown.historical_simulation
      || (breakdown.components && breakdown.components.historical_simulation)
      || null;
    const extEvidence = breakdown.external_evidence
      || (breakdown.components && breakdown.components.external_evidence)
      || null;
    const extAdj = breakdown.external_evidence_adjustment;
    const scoreBreakdown = breakdown.score_breakdown || [];
    return `
      <div class="fc-breakdown-grid">
        <div>
          <div class="fc-section-title">Adjustments A–H</div>
          <table class="fc-table fc-table-compact">
            <thead><tr><th>Component</th><th>Δ</th></tr></thead>
            <tbody>${adjRows || '<tr><td colspan="2">—</td></tr>'}</tbody>
          </table>
          ${renderSimulationSection(histSim)}
          ${renderExternalEvidenceSection(extEvidence, extAdj)}
        </div>
        <div>
          <div class="fc-section-title">score breakdown</div>
          <div class="fc-breakdown-meta">
            base=${escapeHtml(breakdown.base_score)} total_adj=${escapeHtml(breakdown.total_adjustment)}
            pre_cal=${escapeHtml(breakdown.pre_calibration_score != null ? breakdown.pre_calibration_score : '—')}
            final=${escapeHtml(breakdown.final_score)} decision=${escapeHtml(breakdown.decision)}
          </div>
          ${renderScoreBreakdownList(scoreBreakdown)}
          <ul class="fc-expl-list">${expl || '<li>—</li>'}</ul>
        </div>
      </div>`;
  }

  function renderTomorrowWatchlistSection(watchlist) {
    if (!watchlist || watchlist.ok !== true) {
      return `
        <div class="fc-section">
          <div class="fc-section-title">📋 Tomorrow Watchlist</div>
          <div class="fc-empty">Tomorrow watchlist unavailable.</div>
        </div>`;
    }

    const summary = watchlist.summary || {};
    const modeSummary = watchlist.market_mode_summary || {};
    const listTitle = summary.list_title || 'Tomorrow Watchlist';

    function renderList(rows, emptyText) {
      if (!rows || !rows.length) {
        return `<div class="fc-empty">${escapeHtml(emptyText)}</div>`;
      }
      const body = rows.slice(0, 15).map((row) => {
        const ext = row.external_evidence_summary || {};
        const extNote = ext.latest_titles && ext.latest_titles[0]
          ? ext.latest_titles[0]
          : (ext.summary_reason || '');
        return `
        <tr>
          <td>${escapeHtml(row.ticker || '—')}</td>
          <td class="fc-score">${escapeHtml(row.score != null ? row.score : '—')}</td>
          <td class="${decisionClass(row.decision)}">${escapeHtml(row.decision || '—')}</td>
          <td>${escapeHtml(row.reason || row.primary_label || '—')}</td>
          <td>${escapeHtml(ext.stock_news_count != null ? ext.stock_news_count : '—')}</td>
          <td>${escapeHtml(extNote || '—')}</td>
          <td>${escapeHtml(ext.score_adjustment != null ? ext.score_adjustment : '—')}</td>
          <td>${fmtList(row.warnings)}</td>
        </tr>`;
      }).join('');
      return `
        <table class="fc-table fc-table-compact">
          <thead><tr>
            <th>Ticker</th><th>Score</th><th>Decision</th><th>Reason</th>
            <th>Ext news</th><th>Latest evidence</th><th>Adj</th><th>Warnings</th>
          </tr></thead>
          <tbody>${body}</tbody>
        </table>`;
    }

    const riskNotes = (watchlist.risk_notes || []).map((note) => `
      <li>${escapeHtml(note)}</li>`).join('');

    return `
      <div class="fc-section fc-watchlist-section">
        <div class="fc-section-title">📋 Tomorrow Watchlist</div>
        <p class="fc-disclaimer fc-watchlist-disclaimer">Shadow watchlist only — not trade execution.</p>
        <p class="fc-disclaimer fc-ext-disclaimer">External evidence is read-only and not trade execution.</p>
        <div class="fc-stat-grid fc-stat-grid-4">
          ${statCard('Mode', watchlist.market_mode || modeSummary.active_mode || '—', 'fc-muted')}
          ${statCard('Watch', summary.watch ?? 0, 'fc-watch')}
          ${statCard('Avoid', summary.avoid ?? 0, 'fc-avoid')}
          ${statCard('No decision', summary.no_decision ?? 0, 'fc-nodecision')}
        </div>
        <div class="fc-watchlist-meta">
          India session: ${escapeHtml(modeSummary.india_session || '—')}
          · USA session: ${escapeHtml(modeSummary.usa_session || '—')}
        </div>
        <div class="fc-section-subtitle">${escapeHtml(listTitle)}</div>
        ${renderList(watchlist.top_watchlist, 'No watch candidates for tomorrow.')}
        <div class="fc-section-subtitle">Avoid candidates</div>
        ${renderList(watchlist.avoid, 'No avoid candidates.')}
        <div class="fc-section-subtitle">No decision / insufficient evidence</div>
        ${renderList(watchlist.no_decision, 'No no-decision candidates.')}
        ${riskNotes ? `<div class="fc-section-subtitle">Risk notes</div><ul class="fc-expl-list">${riskNotes}</ul>` : ''}
        <div class="fc-debug-line">GET ${escapeHtml(WATCHLIST_SOURCE)}</div>
      </div>`;
  }

  function renderInto(host, report, breakdown, calibration, watchlist) {
    if (!host) return;
    const topTicker = (report.top_candidates && report.top_candidates[0] && report.top_candidates[0].ticker) || '';
    const breakdownPayload = (breakdown && breakdown.breakdown) || breakdown || null;

    host.innerHTML = `
      <div class="fc-dashboard">
        <div class="fc-header-row">
          <h2 class="fc-title">🎯 Final Confidence</h2>
          <button type="button" class="refresh-btn fc-refresh-btn" id="fcRefreshBtn">↻ Refresh</button>
        </div>
        <p class="fc-disclaimer">Shadow confidence only — not trade execution.</p>
        <div class="fc-stat-grid fc-stat-grid-4">
          ${statCard('Buy candidate', report.buy_candidate ?? 0, 'fc-buy')}
          ${statCard('Watch', report.watch ?? 0, 'fc-watch')}
          ${statCard('Avoid', report.avoid ?? 0, 'fc-avoid')}
          ${statCard('No decision', report.no_decision ?? 0, 'fc-nodecision')}
        </div>
        <div class="fc-section">
          <div class="fc-section-title">Top candidates</div>
          ${renderCandidatesTable(report.top_candidates || report.rows || [])}
        </div>
        <div class="fc-section">
          <div class="fc-section-title">score breakdown${topTicker ? ` (${escapeHtml(topTicker)})` : ''}</div>
          ${renderBreakdown(breakdownPayload)}
        </div>
        ${renderCalibrationSection(calibration)}
        ${renderTomorrowWatchlistSection(watchlist)}
        <div class="fc-debug-line">GET ${escapeHtml(REPORT_SOURCE)} · ${escapeHtml(BREAKDOWN_SOURCE)}</div>
      </div>`;

    const refreshBtn = host.querySelector('#fcRefreshBtn');
    if (refreshBtn) {
      refreshBtn.addEventListener('click', () => loadInto(host));
    }
  }

  async function loadInto(host) {
    const target = host || document.getElementById('finalConfidenceHost');
    if (!target) return;
    target.innerHTML = '<div class="loading">⏳ Loading final confidence…</div>';
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), FETCH_MS);
      const base = (config.getApiBase() || '').replace(/\/$/, '');
      const headers = config.getHeaders();
      const ts = Date.now();
      const reportRes = await fetch(`${base}${REPORT_SOURCE}?limit=50&_ts=${ts}`, {
        headers,
        cache: 'no-store',
        signal: controller.signal,
      });
      const report = await reportRes.json();
      if (report.ok === false) throw new Error(report.error || 'final-confidence report failed');

      const calRes = await fetch(`${base}${CALIBRATION_SOURCE}?_ts=${ts}`, {
        headers,
        cache: 'no-store',
        signal: controller.signal,
      });
      let calibration = null;
      if (calRes.ok) calibration = await calRes.json();

      const wlRes = await fetch(`${base}${WATCHLIST_SOURCE}?limit=25&_ts=${ts}`, {
        headers,
        cache: 'no-store',
        signal: controller.signal,
      });
      let watchlist = null;
      if (wlRes.ok) watchlist = await wlRes.json();

      const topTicker = (report.top_candidates && report.top_candidates[0] && report.top_candidates[0].ticker) || '';
      let breakdown = null;
      if (topTicker) {
        const bdRes = await fetch(
          `${base}${BREAKDOWN_SOURCE}?ticker=${encodeURIComponent(topTicker)}&_ts=${ts}`,
          { headers, cache: 'no-store', signal: controller.signal },
        );
        if (bdRes.ok) breakdown = await bdRes.json();
      }
      clearTimeout(timer);
      renderInto(target, report, breakdown, calibration, watchlist);
    } catch (err) {
      target.innerHTML = `<div class="panel-error-card"><strong>Final Confidence</strong>${escapeHtml(err.message || err)}</div>`;
    }
  }

  function init(opts) {
    config.getApiBase = (opts && opts.getApiBase) || config.getApiBase;
    config.getHeaders = (opts && opts.getHeaders) || config.getHeaders;
  }

  global.FinalConfidencePanel = {
    init,
    loadInto,
    renderInto,
    renderCalibrationSection,
    renderTomorrowWatchlistSection,
    renderExternalEvidenceSection,
    CALIBRATION_SOURCE,
    WATCHLIST_SOURCE,
  };
})(typeof window !== 'undefined' ? window : global);
