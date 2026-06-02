/**
 * Daily Report Pack panel — shadow aggregated local intelligence summary.
 */
(function (global) {
  'use strict';

  const PACK_SOURCE = '/api/debug/daily-report-pack';
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

  function statCard(label, value, cls) {
    return `
      <div class="fc-stat">
        <span class="fc-stat-label">${escapeHtml(label)}</span>
        <span class="fc-stat-value ${cls || ''}">${escapeHtml(String(value))}</span>
      </div>`;
  }

  function renderWatchRows(rows) {
    if (!rows || !rows.length) {
      return '<div class="fc-empty">No watch candidates in pack.</div>';
    }
    const body = rows.slice(0, 10).map((row) => `
      <tr>
        <td>${escapeHtml(row.ticker || '—')}</td>
        <td>${escapeHtml(row.score != null ? row.score : '—')}</td>
        <td>${escapeHtml(row.decision || '—')}</td>
        <td>${escapeHtml(row.reason || '—')}</td>
      </tr>`).join('');
    return `
      <table class="fc-table fc-table-compact">
        <thead><tr><th>Ticker</th><th>Score</th><th>Decision</th><th>Reason</th></tr></thead>
        <tbody>${body}</tbody>
      </table>`;
  }

  function renderFileCards(files) {
    if (!files) return '';
    return Object.entries(files).map(([key, path]) => `
      <div class="fc-stat">
        <span class="fc-stat-label">${escapeHtml(key)}</span>
        <span class="fc-stat-value fc-muted">${escapeHtml(path)}</span>
      </div>`).join('');
  }

  function renderExternalEvidenceSection(ext) {
    if (!ext || ext.ok !== true) {
      return `
        <div class="fc-section-subtitle">External Evidence</div>
        <div class="fc-empty">External evidence unavailable.</div>
        <p class="fc-muted">External evidence is separated from our final prediction.</p>`;
    }
    const rows = (ext.top_evidence_items || []).slice(0, 8).map((row) => `
      <tr>
        <td>${escapeHtml(row.classification || '—')}</td>
        <td>${escapeHtml(row.ticker || '—')}</td>
        <td>${escapeHtml(row.direction || '—')}</td>
        <td>${escapeHtml(row.title || '—')}</td>
      </tr>`).join('');
    const table = rows
      ? `<table class="fc-table fc-table-compact"><thead><tr><th>Class</th><th>Ticker</th><th>Dir</th><th>Title</th></tr></thead><tbody>${rows}</tbody></table>`
      : '<div class="fc-empty">No external evidence items in pack.</div>';
    return `
      <div class="fc-section-subtitle">External Evidence</div>
      <p class="fc-muted">External evidence is separated from our final prediction.</p>
      <div class="fc-stat-grid fc-stat-grid-4">
        ${statCard('Broker candidates', ext.broker_prediction_candidate ?? 0, 'fc-muted')}
        ${statCard('Stock news', ext.stock_news_evidence ?? 0, 'fc-muted')}
        ${statCard('Market context', ext.market_context ?? 0, 'fc-muted')}
        ${statCard('Macro context', ext.macro_context ?? 0, 'fc-muted')}
      </div>
      <div class="fc-section-subtitle">Top evidence items</div>
      ${table}`;
  }

  function renderExternalCoverageSection(ext) {
    if (!ext || ext.ok !== true) {
      return `
        <div class="fc-section-subtitle">External Source Coverage</div>
        <div class="fc-empty">External source coverage unavailable.</div>
        <p class="fc-muted">External evidence only — not our final prediction.</p>`;
    }
    const warnings = (ext.warnings || []).map((w) => `<li>${escapeHtml(w)}</li>`).join('');
    const sources = (ext.latest_sources || []).map((s) => `<span class="fc-tag">${escapeHtml(s)}</span>`).join(' ');
    return `
      <div class="fc-section-subtitle">External Source Coverage</div>
      <p class="fc-muted">External evidence only — not our final prediction.</p>
      <div class="fc-stat-grid fc-stat-grid-4">
        ${statCard('Collected', ext.collected_items ?? 0, 'fc-muted')}
        ${statCard('Sources', ext.source_count ?? 0, 'fc-muted')}
        ${statCard('Unique tickers', ext.unique_tickers ?? 0, 'fc-muted')}
        ${statCard('Broker DB picks', ext.broker_db_pick_count ?? 0, 'fc-muted')}
      </div>
      <div class="fc-section-subtitle">Latest sources</div>
      <div class="fc-tag-row">${sources || '<span class="fc-muted">—</span>'}</div>
      ${warnings ? `<div class="fc-section-subtitle">Warnings</div><ul class="fc-expl-list">${warnings}</ul>` : ''}`;
  }

  function renderBrokerWriteReviewSection(review) {
    if (!review || review.ok !== true) {
      return `
        <div class="fc-section-subtitle">Broker DB Write Review</div>
        <div class="fc-empty">Broker write review unavailable.</div>
        <p class="fc-muted">Only write-safe items can enter broker prediction memory.</p>`;
    }
    return `
      <div class="fc-section-subtitle">Broker DB Write Review</div>
      <p class="fc-muted">Only write-safe items can enter broker prediction memory.</p>
      <div class="fc-stat-grid fc-stat-grid-4">
        ${statCard('Write safe', review.write_safe ?? 0, 'fc-ok')}
        ${statCard('Review only', review.review_only ?? 0, 'fc-warn')}
        ${statCard('Rejected', review.rejected ?? 0, 'fc-muted')}
        ${statCard('Candidates', review.total_candidates ?? 0, 'fc-muted')}
      </div>`;
  }

  function renderPackHtml(pack) {
    if (!pack || pack.ok !== true) {
      return `
        <div class="glass-card fc-section drp-panel">
          <h2>🗂 Daily Report Pack</h2>
          <div class="fc-empty">Daily report pack unavailable.</div>
        </div>`;
    }

    const tw = pack.tomorrow_watchlist || {};
    const fc = pack.final_confidence || {};
    const cal = pack.confidence_calibration || {};
    const sim = pack.historical_simulation || {};
    const ext = pack.external_source_coverage || {};
    const extEvidence = pack.external_evidence || {};
    const brokerWriteReview = pack.broker_write_review || {};
    const riskNotes = (pack.risk_notes || []).map((note) => `<li>${escapeHtml(note)}</li>`).join('');

    return `
      <div class="glass-card fc-section drp-panel">
        <div class="fc-header-row">
          <h2 class="fc-title">🗂 Daily Report Pack</h2>
        </div>
        <p class="fc-disclaimer">Daily report pack is shadow analysis only — not trade execution.</p>
        <div class="fc-stat-grid fc-stat-grid-4">
          ${statCard('Generated', (pack.generated_at || '—').slice(0, 19).replace('T', ' '), 'fc-muted')}
          ${statCard('Mode', pack.market_mode || '—', 'fc-muted')}
          ${statCard('Watch', tw.watch ?? 0, 'fc-watch')}
          ${statCard('Avoid', tw.avoid ?? 0, 'fc-avoid')}
        </div>
        <div class="fc-stat-grid fc-stat-grid-4">
          ${statCard('No decision', tw.no_decision ?? 0, 'fc-nodecision')}
          ${statCard('Final checked', fc.checked ?? 0, 'fc-muted')}
          ${statCard('Calibration recs', cal.recommendations ?? 0, 'fc-muted')}
          ${statCard('Sim predictions', sim.simulated_predictions ?? 0, 'fc-muted')}
        </div>
        <div class="fc-section-subtitle">Top watch candidates</div>
        ${renderWatchRows(tw.top_watchlist || [])}
        ${renderExternalEvidenceSection(extEvidence)}
        ${renderBrokerWriteReviewSection(brokerWriteReview)}
        ${renderExternalCoverageSection(ext)}
        ${riskNotes ? `<div class="fc-section-subtitle">Risk notes</div><ul class="fc-expl-list">${riskNotes}</ul>` : ''}
        <div class="fc-section-subtitle">Report files</div>
        <div class="fc-stat-grid fc-stat-grid-3">${renderFileCards(pack.files || {})}</div>
        <div class="fc-debug-line">GET ${escapeHtml(PACK_SOURCE)}</div>
      </div>`;
  }

  async function fetchPack() {
    const base = config.getApiBase().replace(/\/$/, '');
    const res = await fetch(`${base}${PACK_SOURCE}?_ts=${Date.now()}`, {
      headers: config.getHeaders(),
      cache: 'no-store',
    });
    if (!res.ok) throw new Error(`daily-report-pack → ${res.status}`);
    return res.json();
  }

  async function mount(containerOrSelector) {
    let container = containerOrSelector;
    if (typeof containerOrSelector === 'string') {
      container = document.querySelector(containerOrSelector);
    }
    if (!container) return null;
    container.innerHTML = '<div class="loading">⏳ Loading daily report pack…</div>';
    try {
      const pack = await fetchPack();
      container.innerHTML = renderPackHtml(pack);
      return pack;
    } catch (err) {
      container.innerHTML = renderPackHtml({ ok: false, error: err.message || String(err) });
      return null;
    }
  }

  function init(opts) {
    config.getApiBase = (opts && opts.getApiBase) || config.getApiBase;
    config.getHeaders = (opts && opts.getHeaders) || config.getHeaders;
  }

  global.DailyReportPackPanel = {
    init,
    mount,
    renderPackHtml,
    fetchPack,
    PACK_SOURCE,
  };
})(window);
