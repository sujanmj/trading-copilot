/**
 * Broker prediction intelligence workspace (Stage 23).
 * External broker/app evidence — not our final prediction.
 */
(function (global) {
  'use strict';

  const INTEL_SOURCE = '/api/debug/broker-intelligence';
  const COLLECTOR_SOURCE = '/api/debug/broker-app-collector';
  const COVERAGE_SOURCE = '/api/debug/external-source-coverage';
  const COMPARE_SOURCE = '/api/debug/our-vs-broker';
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

  function fmtPct(v) {
    if (v == null || v === '') return '—';
    const n = Number(v);
    return Number.isFinite(n) ? `${(n * 100).toFixed(1)}%` : escapeHtml(v);
  }

  function formatClassLabel(raw) {
    const map = {
      broker_prediction_candidate: 'Broker candidate',
      stock_news_evidence: 'Stock news',
      market_context: 'Market context',
      macro_context: 'Macro context',
    };
    const key = String(raw || '').trim();
    return map[key] || key || '—';
  }

  function directionBadgeClass(direction) {
    const token = String(direction || '').trim().toUpperCase();
    if (!token || token === '—') return 'bi-dir-neutral';
    if (token.includes('BULL') || token.includes('LONG') || token.includes('BUY') || token.includes('UP')) return 'bi-dir-bull';
    if (token.includes('BEAR') || token.includes('SHORT') || token.includes('SELL') || token.includes('DOWN')) return 'bi-dir-bear';
    return 'bi-dir-neutral';
  }

  function renderDirectionBadge(direction) {
    const label = direction || '—';
    return `<span class="bi-direction-badge ${directionBadgeClass(label)}">${escapeHtml(label)}</span>`;
  }

  function renderEvidenceTable(rows, opts) {
    const options = opts || {};
    const limit = options.limit != null ? options.limit : 6;
    const classHeader = options.classHeader || 'Class/Source';
    const directionKey = options.directionKey || 'direction';
    const classKey = options.classKey || 'classification';
    const titleKey = options.titleKey || 'title';
    if (!rows || !rows.length) {
      return '<div class="bi-empty">—</div>';
    }
    const body = rows.slice(0, limit).map((row) => {
      const ticker = row.ticker || '—';
      const direction = row[directionKey] || row.direction || row.stance || '—';
      const clsRaw = row[classKey] || row.classification || row.broker_source || '—';
      const clsLabel = formatClassLabel(clsRaw);
      const title = row[titleKey] || row.headline || row.notes || '—';
      const titleEsc = escapeHtml(title);
      const clsEsc = escapeHtml(clsLabel);
      const clsTitleEsc = escapeHtml(clsRaw);
      return `<tr>
        <td class="bi-col-ticker">${escapeHtml(ticker)}</td>
        <td class="bi-col-direction">${renderDirectionBadge(direction)}</td>
        <td class="bi-col-class" title="${clsTitleEsc}">${clsEsc}</td>
        <td class="bi-col-title" title="${titleEsc}">${titleEsc}</td>
      </tr>`;
    }).join('');
    return `<table class="bi-table bi-evidence-table"><thead><tr>
      <th class="bi-col-ticker">Ticker</th>
      <th class="bi-col-direction">Direction</th>
      <th class="bi-col-class">${escapeHtml(classHeader)}</th>
      <th class="bi-col-title">Title</th>
    </tr></thead><tbody>${body}</tbody></table>`;
  }

  async function fetchJson(path) {
    const base = config.getApiBase() || '';
    const url = `${base.replace(/\/$/, '')}${path}${path.includes('?') ? '&' : '?'}_ts=${Date.now()}`;
    const res = await fetch(url, { headers: config.getHeaders(), cache: 'no-store' });
    if (!res.ok) throw new Error(`HTTP ${res.status} ${path}`);
    return res.json();
  }

  function renderSourceTable(sources) {
    if (!sources || !sources.length) {
      return '<div class="bi-empty">No broker sources in market memory yet.</div>';
    }
    const rows = sources.map((s) => {
      const align = s.alignment_rate != null ? fmtPct(s.alignment_rate) : '—';
      const rel = s.reliability_score != null ? Number(s.reliability_score).toFixed(2) : '—';
      return `<tr>
        <td>${escapeHtml(s.broker_source)}</td>
        <td>${escapeHtml(s.pick_count)}</td>
        <td>${align}</td>
        <td>${escapeHtml(rel)}</td>
      </tr>`;
    }).join('');
    return `<table class="bi-table"><thead><tr>
      <th>Source</th><th>Picks</th><th>Align w/ ours</th><th>Reliability</th>
    </tr></thead><tbody>${rows}</tbody></table>`;
  }

  function renderCompareSummary(cmp) {
    if (!cmp || cmp.ok !== true) {
      return '<div class="bi-empty">Comparison unavailable.</div>';
    }
    return `<div class="bi-stat-grid bi-stat-grid-4">
      <div class="bi-stat"><span class="bi-stat-label">Agreements</span><span class="bi-stat-value bi-ok">${escapeHtml(cmp.agreements)}</span></div>
      <div class="bi-stat"><span class="bi-stat-label">Conflicts</span><span class="bi-stat-value bi-warn">${escapeHtml(cmp.conflicts)}</span></div>
      <div class="bi-stat"><span class="bi-stat-label">Unclear</span><span class="bi-stat-value">${escapeHtml(cmp.unclear)}</span></div>
      <div class="bi-stat"><span class="bi-stat-label">Agreement rate</span><span class="bi-stat-value">${fmtPct(cmp.agreement_rate)}</span></div>
    </div>`;
  }

  function renderStats(stats) {
    const s = stats || {};
    return `<div class="bi-stat-grid">
      <div class="bi-stat"><span class="bi-stat-label">Broker picks</span><span class="bi-stat-value">${escapeHtml(s.broker_predictions ?? 0)}</span></div>
      <div class="bi-stat"><span class="bi-stat-label">Sources</span><span class="bi-stat-value">${escapeHtml(s.unique_sources ?? 0)}</span></div>
      <div class="bi-stat"><span class="bi-stat-label">Tickers</span><span class="bi-stat-value">${escapeHtml(s.unique_tickers ?? 0)}</span></div>
    </div>`;
  }

  function renderBrokerWriteReviewSection(review) {
    if (!review || review.ok !== true) {
      return `<div class="bi-section broker-write-review">
        <div class="bi-section-title">Broker DB Write Review</div>
        <div class="bi-empty">Broker write review unavailable. Run collector with --write-review-only.</div>
        <p class="bi-muted bi-warn">Only write-safe items can enter broker prediction memory.</p>
      </div>`;
    }
    return `<div class="bi-section broker-write-review">
      <div class="bi-section-title">Broker DB Write Review</div>
      <p class="bi-muted bi-warn">Only write-safe items can enter broker prediction memory.</p>
      <div class="bi-stat-grid bi-stat-grid-4">
        <div class="bi-stat"><span class="bi-stat-label">Write safe</span><span class="bi-stat-value bi-ok">${escapeHtml(review.write_safe ?? 0)}</span></div>
        <div class="bi-stat"><span class="bi-stat-label">Review only</span><span class="bi-stat-value bi-warn">${escapeHtml(review.review_only ?? 0)}</span></div>
        <div class="bi-stat"><span class="bi-stat-label">Rejected</span><span class="bi-stat-value">${escapeHtml(review.rejected ?? 0)}</span></div>
        <div class="bi-stat"><span class="bi-stat-label">Duplicates</span><span class="bi-stat-value">${escapeHtml(review.duplicates ?? 0)}</span></div>
      </div>
    </div>`;
  }

  function renderExternalEvidenceSection(evidence) {
    if (!evidence || evidence.ok !== true) {
      return `<div class="bi-section external-evidence">
        <div class="bi-section-title">External Evidence</div>
        <div class="bi-empty">External evidence unavailable.</div>
        <p class="bi-muted">External evidence is separated from our final prediction.</p>
      </div>`;
    }
    const renderRows = (rows) => renderEvidenceTable(rows, { limit: 6 });
    return `<div class="bi-section external-evidence">
      <div class="bi-section-title">External Evidence</div>
      <p class="bi-muted">External evidence is separated from our final prediction.</p>
      <div class="bi-stat-grid bi-stat-grid-4">
        <div class="bi-stat"><span class="bi-stat-label">Broker candidates</span><span class="bi-stat-value">${escapeHtml(evidence.broker_prediction_candidate ?? 0)}</span></div>
        <div class="bi-stat"><span class="bi-stat-label">Stock news</span><span class="bi-stat-value">${escapeHtml(evidence.stock_news_evidence ?? 0)}</span></div>
        <div class="bi-stat"><span class="bi-stat-label">Market context</span><span class="bi-stat-value">${escapeHtml(evidence.market_context ?? 0)}</span></div>
        <div class="bi-stat"><span class="bi-stat-label">Macro context</span><span class="bi-stat-value">${escapeHtml(evidence.macro_context ?? 0)}</span></div>
      </div>
      <div class="bi-section-subtitle">Broker candidates</div>
      ${renderRows(evidence.broker_candidates)}
      <div class="bi-section-subtitle">Stock news evidence</div>
      ${renderRows(evidence.stock_news)}
      <div class="bi-section-subtitle">Market context</div>
      ${renderRows(evidence.market_context_items || evidence.market_context)}
      <div class="bi-section-subtitle">Macro context</div>
      ${renderRows(evidence.macro_context_items || evidence.macro_context)}
    </div>`;
  }

  function renderExternalSourceCoverage(coverage) {
    if (!coverage || coverage.ok !== true) {
      return `<div class="bi-section external-source-coverage">
        <div class="bi-section-title">External Source Coverage</div>
        <div class="bi-empty">External source coverage unavailable.</div>
        <p class="bi-muted">External evidence only — not our final prediction.</p>
      </div>`;
    }
    const warnings = (coverage.warnings || []).map((w) => `<li>${escapeHtml(w)}</li>`).join('');
    const sources = (coverage.latest_sources || coverage.sources || []).slice(0, 8)
      .map((s) => `<span class="bi-tag">${escapeHtml(s)}</span>`).join(' ');
    return `<div class="bi-section external-source-coverage">
      <div class="bi-section-title">External Source Coverage</div>
      <p class="bi-muted">External evidence only — not our final prediction.</p>
      <div class="bi-stat-grid bi-stat-grid-4">
        <div class="bi-stat"><span class="bi-stat-label">Collected</span><span class="bi-stat-value">${escapeHtml(coverage.collected_items ?? 0)}</span></div>
        <div class="bi-stat"><span class="bi-stat-label">Sources</span><span class="bi-stat-value">${escapeHtml(coverage.source_count ?? 0)}</span></div>
        <div class="bi-stat"><span class="bi-stat-label">Unique tickers</span><span class="bi-stat-value">${escapeHtml(coverage.unique_tickers ?? 0)}</span></div>
        <div class="bi-stat"><span class="bi-stat-label">Broker DB picks</span><span class="bi-stat-value">${escapeHtml(coverage.broker_db_pick_count ?? 0)}</span></div>
      </div>
      <div class="bi-section-subtitle">Latest sources</div>
      <div class="bi-tag-row">${sources || '<span class="bi-muted">—</span>'}</div>
      ${warnings ? `<div class="bi-section-subtitle">Warnings</div><ul class="bi-expl-list">${warnings}</ul>` : ''}
      <div class="bi-debug-line">GET ${escapeHtml(COVERAGE_SOURCE)}</div>
    </div>`;
  }

  function renderCollectorSection(collector) {
    if (!collector || collector.ok !== true) {
      return `<div class="bi-section broker-app-collector">
        <div class="bi-section-title">Latest collected external ideas</div>
        <div class="bi-empty">No collector cache yet. Run <code>python scripts/collect_broker_app_predictions.py</code>.</div>
        <p class="bi-muted">Collected external evidence — not our prediction.</p>
      </div>`;
    }
    const summary = collector.summary || {};
    const items = collector.items || [];
    const table = items.length
      ? renderEvidenceTable(items, {
        limit: 12,
        directionKey: 'stance',
        classKey: 'broker_source',
        titleKey: 'headline',
      })
      : '<div class="bi-empty">Collector cache is empty for the current filters.</div>';
    return `<div class="bi-section broker-app-collector">
      <div class="bi-section-title">Latest collected external ideas</div>
      <p class="bi-muted">Collected external evidence — not our prediction.</p>
      <div class="bi-stat-grid bi-stat-grid-4">
        <div class="bi-stat"><span class="bi-stat-label">Cached</span><span class="bi-stat-value">${escapeHtml(summary.total ?? items.length ?? 0)}</span></div>
        <div class="bi-stat"><span class="bi-stat-label">Watch</span><span class="bi-stat-value">${escapeHtml(summary.watch ?? 0)}</span></div>
        <div class="bi-stat"><span class="bi-stat-label">Bullish</span><span class="bi-stat-value">${escapeHtml(summary.bullish ?? 0)}</span></div>
        <div class="bi-stat"><span class="bi-stat-label">Bearish</span><span class="bi-stat-value">${escapeHtml(summary.bearish ?? 0)}</span></div>
      </div>
      ${table}
    </div>`;
  }

  function renderImportHint(dashboard) {
    const collect = dashboard.collect_hint || 'python scripts/collect_broker_app_predictions.py --dry-run --limit 30';
    const hint = dashboard.import_hint || 'python scripts/collect_broker_app_predictions.py --write-broker-db';
    return `<div class="bi-import-box">
      <div class="bi-section-title">Collect &amp; import</div>
      <p class="bi-muted">Collect real picks from public RSS feeds (Moneycontrol, ET, LiveMint, etc.), then import into market memory:</p>
      <pre class="bi-cli">${escapeHtml(collect)}</pre>
      <p class="bi-muted">Manual inbox: copy <code>data/broker_prediction_inbox.example.json</code> or run import only:</p>
      <pre class="bi-cli">${escapeHtml(hint)}</pre>
      <p class="bi-muted">Manual inbox import (optional):</p>
      <pre class="bi-cli">python scripts/import_broker_predictions.py --file data/broker_prediction_inbox.json</pre>
      <p class="bi-muted">EOD gainers/losers are rejected (outcomes, not predictions).</p>
    </div>`;
  }

  function renderInto(host, dashboard, comparison, collector, coverage) {
    if (!host) return;
    const stats = dashboard.stats || dashboard;
    const sources = dashboard.source_performance || [];
    const disclaimer = dashboard.disclaimer || 'External broker/app evidence — not our final prediction.';
    const externalEvidence = (collector && collector.external_evidence) || (coverage && coverage.external_evidence) || null;
    const brokerWriteReview = (coverage && coverage.broker_write_review)
      || (collector && collector.broker_write_review)
      || null;

    host.innerHTML = `
      <div class="bi-dashboard">
        <div class="bi-header-row">
          <h2 class="bi-title">🏦 Broker Prediction Intelligence</h2>
          <button type="button" class="refresh-btn bi-refresh-btn" id="brokersRefreshBtn">↻ Refresh</button>
        </div>
        <p class="bi-disclaimer">${escapeHtml(disclaimer)}</p>
        <p class="bi-shadow-label">External broker/app evidence — not our final prediction.</p>
        ${renderStats(stats)}
        ${renderExternalEvidenceSection(externalEvidence)}
        ${renderBrokerWriteReviewSection(brokerWriteReview)}
        ${renderExternalSourceCoverage(coverage || (collector && collector.external_source_coverage))}
        ${renderCollectorSection(collector)}
        <div class="bi-section">
          <div class="bi-section-title">Our predictions vs brokers</div>
          ${renderCompareSummary(comparison || dashboard.our_vs_broker)}
        </div>
        <div class="bi-section">
          <div class="bi-section-title">Source performance</div>
          ${renderSourceTable(sources)}
        </div>
        ${renderImportHint(dashboard)}
        <div class="bi-debug-line">GET ${escapeHtml(INTEL_SOURCE)} · ${escapeHtml(COLLECTOR_SOURCE)} · ${escapeHtml(COVERAGE_SOURCE)} · ${escapeHtml(COMPARE_SOURCE)}</div>
      </div>`;

    const refreshBtn = host.querySelector('#brokersRefreshBtn');
    if (refreshBtn) {
      refreshBtn.addEventListener('click', () => loadMain(host));
    }
  }

  async function loadMain(targetEl) {
    const host = targetEl || document.getElementById('brokersMainContent');
    if (!host) return;
    host.innerHTML = '<div class="loading">⏳ Loading broker intelligence…</div>';
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), FETCH_MS);
      const base = (config.getApiBase() || '').replace(/\/$/, '');
      const headers = config.getHeaders();
      const ts = Date.now();
      const [dashRes, cmpRes, collectorRes, coverageRes] = await Promise.all([
        fetch(`${base}${INTEL_SOURCE}?_ts=${ts}`, { headers, cache: 'no-store', signal: controller.signal }),
        fetch(`${base}${COMPARE_SOURCE}?_ts=${ts}`, { headers, cache: 'no-store', signal: controller.signal }),
        fetch(`${base}${COLLECTOR_SOURCE}?_ts=${ts}`, { headers, cache: 'no-store', signal: controller.signal }),
        fetch(`${base}${COVERAGE_SOURCE}?_ts=${ts}`, { headers, cache: 'no-store', signal: controller.signal }),
      ]);
      clearTimeout(timer);
      const dashboard = await dashRes.json();
      const comparison = cmpRes.ok ? await cmpRes.json() : null;
      const collector = collectorRes.ok ? await collectorRes.json() : null;
      const coverage = coverageRes.ok ? await coverageRes.json() : null;
      if (dashboard.ok === false) throw new Error(dashboard.error || 'broker-intelligence failed');
      renderInto(host, dashboard, comparison, collector, coverage);
    } catch (err) {
      host.innerHTML = `<div class="panel-error-card"><strong>Broker intelligence</strong>${escapeHtml(err.message || err)}</div>`;
    }
  }

  function init(opts) {
    config.getApiBase = (opts && opts.getApiBase) || config.getApiBase;
    config.getHeaders = (opts && opts.getHeaders) || config.getHeaders;
  }

  global.BrokerIntelligencePanel = {
    init,
    loadMain,
    renderInto,
  };
})(typeof window !== 'undefined' ? window : global);
