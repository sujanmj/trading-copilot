/**
 * Broker prediction intelligence workspace (Stage 48L).
 * Cache-first mount — heavy refresh only via Refresh Brokers.
 */
(function (global) {
  'use strict';

  const OVERVIEW_LITE_PATH = '/api/brokers/overview?cache_only=1&lite=1';
  const TICKER_LITE_PATH = '/api/brokers/ticker';
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
  let selectedTicker = '';

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
      <div class="bi-header-row"><h2 class="bi-title">🏦 Broker Intelligence</h2></div>
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

  function renderConsensusRow(row, clickable) {
    const ticker = row.ticker || '—';
    const label = row.consensus_label || 'Unknown';
    const score = row.confidence_score != null ? row.confidence_score : '—';
    const action = row.suggested_action || 'Research Only';
    const cls = clickable ? 'bi-ticker-link' : '';
    const data = clickable ? ` data-ticker="${escapeHtml(ticker)}"` : '';
    return `<tr class="${cls}"${data}>
      <td class="bi-col-ticker">${escapeHtml(ticker)}</td>
      <td>${escapeHtml(label)}</td>
      <td>${escapeHtml(score)}</td>
      <td>${escapeHtml(action)}</td>
    </tr>`;
  }

  function renderConsensusTable(rows, clickable) {
    if (!rows || !rows.length) return '<div class="bi-empty">—</div>';
    const body = rows.map((r) => renderConsensusRow(r, clickable)).join('');
    return `<table class="bi-table bi-consensus-table"><thead><tr>
      <th>Ticker</th><th>Consensus</th><th>Score</th><th>Stance</th>
    </tr></thead><tbody>${body}</tbody></table>`;
  }

  function renderEvidenceTable(rows, opts) {
    const options = opts || {};
    const limit = options.limit != null ? options.limit : 6;
    if (!rows || !rows.length) return '<div class="bi-empty">—</div>';
    const body = rows.slice(0, limit).map((row) => {
      const ticker = row.ticker || '—';
      const house = row.broker_house || row.source || '—';
      const headline = row.headline || row.title || '—';
      const rating = row.rating || row.action || '—';
      return `<tr>
        <td class="bi-col-ticker">${escapeHtml(ticker)}</td>
        <td>${escapeHtml(house)}</td>
        <td>${escapeHtml(rating)}</td>
        <td class="bi-col-title" title="${escapeHtml(headline)}">${escapeHtml(headline)}</td>
      </tr>`;
    }).join('');
    return `<table class="bi-table bi-evidence-table"><thead><tr>
      <th>Ticker</th><th>Source</th><th>Rating</th><th>Headline</th>
    </tr></thead><tbody>${body}</tbody></table>`;
  }

  function renderFreshnessSection(overview) {
    const fresh = overview.freshness || {};
    const status = fresh.status || (overview.stale ? 'stale' : 'unknown');
    const tracked = overview.tracked_tickers != null ? overview.tracked_tickers : '—';
    const reason = overview.stale_reason ? `<p class="bi-muted bi-warn">${escapeHtml(overview.stale_reason)}</p>` : '';
    return `<div class="bi-section">
      <div class="bi-section-title">Freshness</div>
      <div class="bi-stat-grid bi-stat-grid-3">
        <div class="bi-stat"><span class="bi-stat-label">Status</span><span class="bi-stat-value">${escapeHtml(status)}</span></div>
        <div class="bi-stat"><span class="bi-stat-label">Tracked tickers</span><span class="bi-stat-value">${escapeHtml(tracked)}</span></div>
        <div class="bi-stat"><span class="bi-stat-label">Generated</span><span class="bi-stat-value">${escapeHtml(overview.generated_at || '—')}</span></div>
      </div>
      ${reason}
    </div>`;
  }

  function renderImpactSection(overview) {
    const today = overview.impact_today || [];
    const tomorrow = overview.impact_tomorrow || [];
    return `<div class="bi-section">
      <div class="bi-section-title">Impact on Today / Tomorrow</div>
      <div class="bi-section-subtitle">Today</div>
      ${today.length ? today.map((r) => `<div class="bi-impact-row">• ${escapeHtml(r.ticker)} · ${escapeHtml(r.impact || '—')} · ${escapeHtml(r.suggested_action || 'Research Only')}</div>`).join('') : '<div class="bi-empty">—</div>'}
      <div class="bi-section-subtitle">Tomorrow</div>
      ${tomorrow.length ? tomorrow.map((r) => `<div class="bi-impact-row">• ${escapeHtml(r.ticker)} · ${escapeHtml(r.impact || '—')} · ${escapeHtml(r.suggested_action || 'Research Only')}</div>`).join('') : '<div class="bi-empty">—</div>'}
      <p class="bi-muted">Evidence only — not a trade signal.</p>
    </div>`;
  }

  function renderTrackedTickerChips(tickers) {
    if (!tickers || !tickers.length) return '';
    const chips = tickers.map((t) =>
      `<button type="button" class="bi-ticker-chip bi-ticker-link" data-ticker="${escapeHtml(t)}">${escapeHtml(t)}</button>`
    ).join('');
    return `<div class="bi-section">
      <div class="bi-section-title">Tracked Tickers</div>
      <div class="bi-ticker-chips">${chips}</div>
    </div>`;
  }

  function renderNeutralSection(overview) {
    const rows = overview.top_neutral || [];
    if (!rows.length) return '';
    return `<div class="bi-section">
      <div class="bi-section-title">Neutral / Other Evidence</div>
      ${renderConsensusTable(rows, true)}
    </div>`;
  }

  function renderDrilldownSection(detail) {
    if (!detail || !detail.found) {
      return `<div class="bi-section" id="biDrilldownSection">
        <div class="bi-section-title">Ticker Drilldown</div>
        <div class="bi-empty">Click a ticker above to view consensus and evidence.</div>
      </div>`;
    }
    const c = detail.consensus || {};
    const evidence = detail.evidence || c.evidence || [];
    return `<div class="bi-section" id="biDrilldownSection">
      <div class="bi-section-title">Ticker Drilldown — ${escapeHtml(detail.ticker)}</div>
      <div class="bi-stat-grid bi-stat-grid-4">
        <div class="bi-stat"><span class="bi-stat-label">Consensus</span><span class="bi-stat-value">${escapeHtml(c.consensus_label || 'Unknown')}</span></div>
        <div class="bi-stat"><span class="bi-stat-label">Score</span><span class="bi-stat-value">${escapeHtml(c.confidence_score != null ? c.confidence_score : '—')}</span></div>
        <div class="bi-stat"><span class="bi-stat-label">Freshness</span><span class="bi-stat-value">${escapeHtml(c.freshness || '—')}</span></div>
        <div class="bi-stat"><span class="bi-stat-label">Stance</span><span class="bi-stat-value">${escapeHtml(c.suggested_action || 'Research Only')}</span></div>
      </div>
      ${renderEvidenceTable(evidence, { limit: 8 })}
      <p class="bi-muted">Watch for confirmation — external evidence only.</p>
    </div>`;
  }

  function bindRefreshButton(host) {
    const refreshBtn = host && host.querySelector('#brokersRefreshBtn');
    if (refreshBtn) {
      refreshBtn.addEventListener('click', () => refreshBrokers(host));
    }
  }

  function bindTickerLinks(host, onSelect) {
    if (!host) return;
    host.querySelectorAll('.bi-ticker-link').forEach((row) => {
      row.addEventListener('click', () => {
        const ticker = row.getAttribute('data-ticker');
        if (ticker && onSelect) onSelect(ticker);
      });
    });
  }

  function renderInto(host, overview, drilldown) {
    if (!host) return;
    const disclaimer = overview.disclaimer || 'External broker/app evidence — not our final prediction.';
    const staleBanner = overview.stale
      ? '<p class="bi-muted bi-warn">Cached broker data is stale. Showing last snapshot.</p>'
      : '';

    host.innerHTML = `
      <div class="bi-dashboard">
        <div class="bi-header-row">
          <h2 class="bi-title">🏦 Broker Intelligence</h2>
          <button type="button" class="refresh-btn bi-refresh-btn" id="brokersRefreshBtn">↻ Refresh Brokers</button>
        </div>
        ${staleBanner}
        <p class="bi-disclaimer">${escapeHtml(disclaimer)}</p>
        ${renderFreshnessSection(overview)}
        ${renderTrackedTickerChips(overview.tracked_ticker_names || [])}
        <div class="bi-section">
          <div class="bi-section-title">Top Positive</div>
          ${renderConsensusTable(overview.top_positive || [], true)}
        </div>
        <div class="bi-section">
          <div class="bi-section-title">Top Negative</div>
          ${renderConsensusTable(overview.top_negative || [], true)}
        </div>
        ${renderNeutralSection(overview)}
        ${renderDrilldownSection(drilldown)}
        <div class="bi-section external-evidence">
          <div class="bi-section-title">External Evidence</div>
          <p class="bi-muted">External evidence is separated from our final prediction.</p>
          ${renderEvidenceTable(overview.evidence_items || overview.broker_mentions || [], { limit: 8 })}
        </div>
        ${renderImpactSection(overview)}
        <div class="bi-debug-line">GET ${escapeHtml(OVERVIEW_LITE_PATH)} · POST ${escapeHtml(REFRESH_PATH)}</div>
      </div>`;

    bindRefreshButton(host);
    bindTickerLinks(host, (ticker) => loadTickerDrilldown(host, overview, ticker));
  }

  async function loadTickerDrilldown(host, overview, ticker) {
    selectedTicker = ticker;
    const drillSection = host.querySelector('#biDrilldownSection');
    if (drillSection) {
      drillSection.innerHTML = '<div class="loading">⏳ Loading ticker drilldown…</div>';
    }
    const controller = createAbortController('ticker');
    const timer = setTimeout(() => controller.abort(), CACHE_FETCH_MS);
    try {
      const path = `${TICKER_LITE_PATH}/${encodeURIComponent(ticker)}?cache_only=1&lite=1`;
      const detail = await fetchBrokerJson(path, null, controller.signal);
      const section = host.querySelector('#biDrilldownSection');
      if (section) {
        const wrapper = document.createElement('div');
        wrapper.innerHTML = renderDrilldownSection(detail);
        section.replaceWith(wrapper.firstElementChild);
      } else {
        renderInto(host, overview, detail);
      }
    } catch (err) {
      const msg = formatFetchError(err, controller, 'cache');
      if (msg && drillSection) {
        drillSection.innerHTML = `<div class="panel-error-card"><p>${escapeHtml(msg)}</p></div>`;
      }
    } finally {
      clearTimeout(timer);
    }
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
      renderInto(host, overview, null);
      if (selectedTicker) {
        await loadTickerDrilldown(host, overview, selectedTicker);
      }
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
