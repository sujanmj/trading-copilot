/**
 * Broker prediction intelligence workspace (Stage 48E).
 * Cache-first mount — heavy refresh only via Refresh Brokers.
 */
(function (global) {
  'use strict';

  const OVERVIEW_LITE_PATH = '/api/brokers/overview?cache_only=1&lite=1';
  const REFRESH_PATH = '/api/brokers/refresh';
  const CACHE_FETCH_MS = 8000;
  const REFRESH_MS = 90000;
  const CACHE_MISSING_MSG = 'Broker cache unavailable. Tap Refresh Brokers.';
  const CACHE_TIMEOUT_MSG = 'Broker cache request timed out. Tap Refresh Brokers.';
  const REFRESH_TIMEOUT_MSG = 'Broker refresh may still be running. Try again in a minute.';
  const NON_JSON_ERROR = 'API returned HTML/non-JSON. Check API base/path.';
  const abortMeta = new WeakMap();

  let config = {
    getApiBase: () => '',
    getHeaders: () => ({}),
  };

  let loadGeneration = 0;
  let activeController = null;
  let refreshBusy = false;

  function createAbortController(reason) {
    const controller = new AbortController();
    abortMeta.set(controller, { reason: reason || 'unknown' });
    return controller;
  }

  function abortActiveRequest(reason) {
    if (activeController) {
      abortMeta.set(activeController, { reason: reason || 'superseded' });
      activeController.abort();
      activeController = null;
    }
  }

  function isStaleAbort(err, controller) {
    if (!err || err.name !== 'AbortError') return false;
    const meta = abortMeta.get(controller) || {};
    return meta.reason === 'superseded' || meta.reason === 'cleanup' || meta.reason === 'strict_mode';
  }

  function brokerFetchErrorMessage(err, controller, context) {
    if (isStaleAbort(err, controller)) return null;
    if (err && err.name === 'AbortError') {
      return context === 'refresh' ? REFRESH_TIMEOUT_MSG : CACHE_TIMEOUT_MSG;
    }
    const msg = err && err.message ? String(err.message) : String(err || '');
    if (/signal is aborted/i.test(msg) || /AbortError/i.test(msg)) {
      return context === 'refresh' ? REFRESH_TIMEOUT_MSG : CACHE_TIMEOUT_MSG;
    }
    if (/timed out|timeout|cancelled/i.test(msg)) {
      return context === 'refresh' ? REFRESH_TIMEOUT_MSG : CACHE_TIMEOUT_MSG;
    }
    return msg || CACHE_TIMEOUT_MSG;
  }

  function renderBrokerShell(message, showRefresh, stale) {
    const staleBanner = stale
      ? '<p class="bi-muted bi-warn">Cached broker data is stale. Showing last snapshot.</p>'
      : '';
    const refreshBtn = showRefresh
      ? '<button type="button" class="refresh-btn bi-refresh-btn" id="brokersRefreshBtn">↻ Refresh Brokers</button>'
      : '';
    return `<div class="bi-dashboard">
      <div class="bi-header-row"><h2 class="bi-title">🏦 Broker Prediction Intelligence</h2></div>
      <p class="bi-disclaimer">External broker/app evidence — not our final prediction.</p>
      ${staleBanner}
      <div class="panel-error-card"><p>${escapeHtml(message || CACHE_MISSING_MSG)}</p></div>
      ${refreshBtn}
    </div>`;
  }

  async function parseJsonResponse(res, path) {
    const ct = (res.headers && res.headers.get('content-type')) || '';
    const text = await res.text();
    if (!String(ct).toLowerCase().includes('application/json')) {
      const preview = text.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 120);
      throw new Error(NON_JSON_ERROR + (preview ? ` Preview: ${preview}` : ''));
    }
    try {
      return text ? JSON.parse(text) : {};
    } catch (err) {
      throw new Error(`${NON_JSON_ERROR} ${path}`);
    }
  }

  function formatFetchError(err, controller, context) {
    const clean = brokerFetchErrorMessage(err, controller, context);
    if (clean) return clean;
    if (!err) return CACHE_TIMEOUT_MSG;
    return err.message || String(err);
  }

  async function fetchBrokerJson(path, options, signal) {
    const base = (config.getApiBase() || '').replace(/\/$/, '');
    const url = `${base}${path}${path.indexOf('?') >= 0 ? '&' : '?'}_ts=${Date.now()}`;
    let res;
    try {
      res = await fetch(url, {
        method: (options && options.method) || 'GET',
        headers: Object.assign({ 'Content-Type': 'application/json' }, config.getHeaders(), (options && options.headers) || {}),
        body: options && options.body ? JSON.stringify(options.body) : undefined,
        cache: 'no-store',
        signal,
      });
    } catch (err) {
      if (err && err.name === 'AbortError') throw err;
      throw err;
    }
    if (!res.ok) throw new Error(`HTTP ${res.status} ${path}`);
    return parseJsonResponse(res, path);
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

  function bindRefreshButton(host) {
    const refreshBtn = host && host.querySelector('#brokersRefreshBtn');
    if (refreshBtn) {
      refreshBtn.addEventListener('click', () => refreshBrokers(host));
    }
  }

  function overviewToRenderParts(overview) {
    const dashboard = overview.dashboard || {
      ok: true,
      stats: overview.stats || {},
      source_performance: (overview.brokers || []).map((row) => ({
        broker_source: row.source || row.broker_source,
        pick_count: row.picks || row.pick_count,
        alignment_rate: row.accuracy || row.alignment_rate,
      })),
      disclaimer: overview.disclaimer,
    };
    if (!dashboard.source_performance && overview.brokers && overview.brokers.length) {
      dashboard.source_performance = overview.brokers.map((row) => ({
        broker_source: row.source || row.broker_source,
        pick_count: row.picks || row.pick_count,
        alignment_rate: row.accuracy || row.alignment_rate,
      }));
    }
    return {
      dashboard,
      comparison: overview.comparison || null,
      collector: overview.collector || null,
      coverage: overview.coverage || null,
    };
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
      <div class="bi-debug-line">GET ${escapeHtml(OVERVIEW_LITE_PATH)} · POST ${escapeHtml(REFRESH_PATH)}</div>
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

  function renderInto(host, dashboard, comparison, collector, coverage, overviewMeta) {
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
          <button type="button" class="refresh-btn bi-refresh-btn" id="brokersRefreshBtn">↻ Refresh Brokers</button>
        </div>
        ${overviewMeta && overviewMeta.stale ? '<p class="bi-muted bi-warn">Cached broker data is stale. Showing last snapshot.</p>' : ''}
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
        <div class="bi-debug-line">GET ${escapeHtml(OVERVIEW_LITE_PATH)} · POST ${escapeHtml(REFRESH_PATH)}</div>
      </div>`;

    bindRefreshButton(host);
  }

  async function loadCacheOverview(host, generation) {
    abortActiveRequest('superseded');
    const controller = createAbortController('load');
    activeController = controller;
    const timer = setTimeout(() => controller.abort(), CACHE_FETCH_MS);
    try {
      const overview = await fetchBrokerJson(OVERVIEW_LITE_PATH, null, controller.signal);
      if (generation !== loadGeneration) return;
      if (overview.cache_missing) {
        host.innerHTML = renderBrokerShell(overview.message || CACHE_MISSING_MSG, true, false);
        bindRefreshButton(host);
        return;
      }
      const parts = overviewToRenderParts(overview);
      renderInto(host, parts.dashboard, parts.comparison, parts.collector, parts.coverage, overview);
    } catch (err) {
      if (generation !== loadGeneration) return;
      if (isStaleAbort(err, controller)) return;
      const msg = formatFetchError(err, controller, 'cache');
      host.innerHTML = renderBrokerShell(msg, true, false);
      bindRefreshButton(host);
    } finally {
      clearTimeout(timer);
      if (activeController === controller) activeController = null;
    }
  }

  async function refreshBrokers(targetEl) {
    const host = targetEl || document.getElementById('brokersMainContent');
    if (!host || refreshBusy) return;
    refreshBusy = true;
    abortActiveRequest('superseded');
    host.innerHTML = '<div class="loading">⏳ Refreshing broker intelligence…</div>';
    const controller = createAbortController('refresh');
    const timer = setTimeout(() => controller.abort(), REFRESH_MS);
    try {
      await fetchBrokerJson(REFRESH_PATH, { method: 'POST' }, controller.signal);
      refreshBusy = false;
      await loadMain(host);
    } catch (err) {
      refreshBusy = false;
      const msg = formatFetchError(err, controller, 'refresh');
      host.innerHTML = renderBrokerShell(msg, true, false);
      bindRefreshButton(host);
    } finally {
      clearTimeout(timer);
    }
  }

  async function loadMain(targetEl) {
    const host = targetEl || document.getElementById('brokersMainContent');
    if (!host) return;
    loadGeneration += 1;
    const generation = loadGeneration;
    host.innerHTML = '<div class="loading">⏳ Loading broker intelligence…</div>';
    await loadCacheOverview(host, generation);
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
