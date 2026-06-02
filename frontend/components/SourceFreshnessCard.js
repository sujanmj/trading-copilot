/**

 * Source freshness card — Price / News / AI package / Runtime / External evidence health.

 * Fetches GET /api/debug/source-freshness (read-only).

 * Per-section refresh via POST /api/debug/refresh-local-intelligence { scope }.

 */

(function (global) {

  'use strict';



  const FRESHNESS_SOURCE = '/api/debug/source-freshness';

  const REFRESH_ENDPOINT = '/api/debug/refresh-local-intelligence';

  const REFRESH_CLI = 'python scripts\\refresh_closed_market_intelligence.py';

  const REFRESH_HELPER = 'Updates news/global/external evidence and recalculates watchlist. Does not place trades.';

  const STALE_PLANNING_MSG = 'Refresh intelligence before next-session planning.';

  const FETCH_MS = 10000;



  let config = {

    getApiBase: () => '',

    getHeaders: () => ({}),

  };



  let lastReport = null;

  let refreshing = false;

  let statusMessage = '';



  function escapeHtml(text) {

    if (text == null) return '';

    return String(text)

      .replace(/&/g, '&amp;')

      .replace(/</g, '&lt;')

      .replace(/>/g, '&gt;')

      .replace(/"/g, '&quot;');

  }



  function fmtAge(hours) {

    if (hours == null || hours === '') return '—';

    const n = Number(hours);

    if (!Number.isFinite(n)) return escapeHtml(hours);

    if (n < 1) return `${Math.round(n * 60)}m`;

    return `${n.toFixed(1)}h`;

  }



  function statusClass(status) {

    const token = String(status || '').toLowerCase();

    if (token === 'fresh') return 'sf-fresh';

    if (token === 'closed-market') return 'sf-closed';

    if (token === 'stale') return 'sf-stale';

    if (token === 'missing') return 'sf-missing';

    return 'sf-muted';

  }



  function displayStatus(status) {

    const token = String(status || '').toLowerCase();

    if (token === 'closed-market') return 'closed-market';

    return token || '—';

  }



  function warningMessages(warnings, report) {

    const list = Array.isArray(warnings) ? warnings : [];

    const msgs = [];

    if (list.includes('refresh_intelligence_before_next_session')) {

      msgs.push(STALE_PLANNING_MSG);

    }

    if (list.includes('reddit_only_news')) {

      msgs.push('News source coverage is weak — currently Reddit-heavy.');

    }

    if (list.includes('runtime_snapshot_stale') && !list.includes('refresh_intelligence_before_next_session')) {

      msgs.push('Runtime intelligence is stale. Memory dashboard remains valid but live intelligence needs refresh.');

    }

    if (list.includes('ai_package_stale') && !list.includes('refresh_intelligence_before_next_session')) {

      msgs.push('AI package is stale — run Refresh Intelligence to rebuild from latest sources.');

    }

    if (list.includes('external_evidence_stale')) {

      msgs.push('External evidence cache is stale.');

    }

    list.filter((w) => ![

      'reddit_only_news',

      'runtime_snapshot_stale',

      'ai_package_stale',

      'external_evidence_stale',

      'refresh_intelligence_before_next_session',

      'market_closed',

    ].includes(w)).forEach((w) => {

      msgs.push(String(w).replace(/_/g, ' '));

    });

    if (!msgs.length && report && report.market_closed) {

      const sources = report.sources || {};

      const staleKeys = ['news', 'ai_package', 'external_evidence'];

      const runtimeStale = (report.runtime_snapshot && report.runtime_snapshot.status === 'stale');

      const anyStale = staleKeys.some((k) => (sources[k] || {}).status === 'stale') || runtimeStale;

      if (anyStale) msgs.push(STALE_PLANNING_MSG);

    }

    return msgs;

  }



  function metricRow(label, status, ageHours, sub, scope, refreshLabel) {

    return `

      <div class="sf-metric">

        <div class="sf-metric-head">

          <div class="sf-metric-label">${escapeHtml(label)}</div>

          <button type="button" class="refresh-btn sf-section-refresh" data-sf-scope="${escapeHtml(scope)}"${refreshing ? ' disabled' : ''}>${escapeHtml(refreshLabel)}</button>

        </div>

        <div class="sf-metric-value ${statusClass(status)}">${escapeHtml(displayStatus(status))}</div>

        <div class="sf-metric-sub">${escapeHtml(fmtAge(ageHours))}${sub ? ' · ' + escapeHtml(sub) : ''}</div>

      </div>`;

  }



  function intelligenceScope(report) {

    return (report && report.market_closed) ? 'intelligence' : 'all';

  }



  function renderCardHtml(report) {

    if (!report || report.ok !== true) {

      const err = (report && report.error) || 'Freshness unavailable';

      return `

        <div class="glass-card source-freshness-card sf-error">

          <h2>🩺 Intelligence Freshness</h2>

          <div class="sf-warning-line">${escapeHtml(err)}</div>

          <button type="button" class="refresh-btn sf-refresh-btn" data-sf-scope="intelligence">Refresh Intelligence</button>

        </div>`;

    }



    const sources = report.sources || {};

    const prices = sources.prices || {};

    const news = sources.news || {};

    const aiPackage = sources.ai_package || {};

    const external = sources.external_evidence || {};

    const runtimeSnap = report.runtime_snapshot || {};

    const runtimeAge = runtimeSnap.age_hours != null ? runtimeSnap.age_hours : report.runtime_snapshot_age_hours;

    const runtimeStatus = runtimeSnap.status

      || (runtimeAge != null && Number(runtimeAge) > 2 ? 'stale' : 'fresh');

    const warnings = warningMessages(report.warnings || [], report);

    const marketLabel = report.market_status === 'open' ? 'Market open' : report.market_status === 'closed' ? 'Market closed' : 'Market unknown';

    const mainScope = intelligenceScope(report);



    let html = `

      <div class="glass-card source-freshness-card ai-freshness-strip">

        <div class="sf-head">

          <h2>🩺 Intelligence Freshness</h2>

          <span class="sf-market-badge ${report.market_status === 'open' ? 'sf-open' : 'sf-closed-badge'}">${escapeHtml(marketLabel)}</span>

        </div>

        <div class="sf-grid sf-grid-5">

          ${metricRow('Price data', prices.status, report.latest_market_data_age_hours, prices.active_source || prices.market_period || 'last session close', 'prices', 'Refresh Prices')}

          ${metricRow('News', news.status, report.news_age_hours, news.total_articles != null ? `${news.total_articles} articles` : '', 'news', 'Refresh News')}

          ${metricRow('AI package', aiPackage.status, aiPackage.age_hours != null ? aiPackage.age_hours : report.ai_package_age_hours, 'runtime export', 'runtime', 'Refresh Runtime')}

          ${metricRow('Runtime snapshot', runtimeStatus, runtimeAge, 'AI Hub cache', 'runtime', 'Refresh Runtime')}

          ${metricRow('External evidence', external.status, external.age_hours != null ? external.age_hours : report.external_evidence_age_hours, external.items != null ? `${external.items} items` : '', 'intelligence', 'Refresh Intel')}

        </div>`;



    if (warnings.length) {

      html += `<div class="sf-warnings">${warnings.map((m) => `<div class="sf-warning-line">⚠ ${escapeHtml(m)}</div>`).join('')}</div>`;

    }



    if (statusMessage) {

      html += `<div class="sf-status-msg">${escapeHtml(statusMessage)}</div>`;

    }



    html += `

        <div class="sf-actions">

          <button type="button" class="refresh-btn sf-refresh-btn" data-sf-scope="${mainScope}"${refreshing ? ' disabled' : ''}>Refresh Intelligence</button>

          <span class="sf-helper">${escapeHtml(REFRESH_HELPER)}</span>

          <span class="sf-cli-hint" title="Manual fallback">${escapeHtml(REFRESH_CLI)}</span>

        </div>

      </div>`;

    return html;

  }



  function freshnessUrl() {

    const base = config.getApiBase().replace(/\/$/, '');

    return `${base}${FRESHNESS_SOURCE}?_ts=${Date.now()}`;

  }



  function refreshUrl() {

    const base = config.getApiBase().replace(/\/$/, '');

    return `${base}${REFRESH_ENDPOINT}`;

  }



  function dashboardUrl() {

    const base = config.getApiBase().replace(/\/$/, '');

    return `${base}/api/debug/market-memory/dashboard?limit=50&_ts=${Date.now()}`;

  }



  function runtimeSnapshotUrl() {

    const base = config.getApiBase().replace(/\/$/, '');

    return `${base}/api/runtime/snapshot?_ts=${Date.now()}`;

  }



  async function fetchFreshness() {

    const controller = new AbortController();

    const timer = setTimeout(() => controller.abort(), FETCH_MS);

    try {

      const res = await fetch(freshnessUrl(), {

        method: 'GET',

        headers: {

          ...config.getHeaders(),

          'Cache-Control': 'no-cache, no-store, must-revalidate',

          Pragma: 'no-cache',

        },

        cache: 'no-store',

        signal: controller.signal,

      });

      if (!res.ok) throw new Error(`source-freshness → ${res.status}`);

      const data = await res.json();

      lastReport = data;

      return data;

    } finally {

      clearTimeout(timer);

    }

  }



  function summarizeRefreshResult(data, scope) {

    if (!data || data.ok === false) {

      return (data && data.error) ? String(data.error) : 'Refresh failed';

    }

    const parts = [];

    ['runtime', 'news', 'prices', 'memory', 'global', 'tv', 'external_evidence', 'final_confidence', 'tomorrow_watchlist'].forEach((key) => {

      const val = data[key] || (data.results && data.results[key]);

      if (val && val !== 'skipped') parts.push(`${key}: ${val}`);

    });

    const warn = Array.isArray(data.warnings) ? data.warnings : [];

    if (parts.length) {

      return `Refresh complete (${scope}) — ${parts.join(', ')}${warn.length ? '; ' + warn.join('; ') : ''}`;

    }

    if (warn.length) return `Refresh complete (${scope}) — ${warn.join('; ')}`;

    return `Refresh complete (${scope})`;

  }



  async function cacheBustRefetch(scope) {

    if (scope === 'runtime' || scope === 'all' || scope === 'intelligence' || scope === 'closed-market') {

      if (global.RuntimeManager && RuntimeManager.clearStaleCache) {

        RuntimeManager.clearStaleCache(`refresh scope=${scope}`);

      } else {

        try {

          localStorage.removeItem('trading_copilot_runtime_snapshot_v1');

          localStorage.removeItem('trading_copilot_runtime_snapshot_meta_v1');

        } catch (e) { /* ignore */ }

      }

    }

    await fetchFreshness().catch(() => null);

    if (scope === 'runtime' || scope === 'all' || scope === 'intelligence' || scope === 'closed-market') {

      if (global.RuntimeManager && RuntimeManager.refresh) {

        await RuntimeManager.refresh({ force: true }).catch(() => null);

      } else {

        await fetch(runtimeSnapshotUrl(), {

          method: 'GET',

          headers: { ...config.getHeaders(), 'Cache-Control': 'no-cache' },

          cache: 'no-store',

        }).catch(() => null);

        await fetch(`${config.getApiBase().replace(/\/$/, '')}/api/runtime_snapshot?_ts=${Date.now()}`, {

          method: 'GET',

          headers: { ...config.getHeaders(), 'Cache-Control': 'no-cache' },

          cache: 'no-store',

        }).catch(() => null);

      }

    }

    if (scope === 'memory' || scope === 'all') {

      await fetch(dashboardUrl(), {

        method: 'GET',

        headers: { ...config.getHeaders(), 'Cache-Control': 'no-cache' },

        cache: 'no-store',

      }).catch(() => null);

      if (global.MarketMemoryPanel && MarketMemoryPanel.refreshTarget

        && global.WorkspaceManager && WorkspaceManager.getActiveWorkspace() === 'memory') {

        MarketMemoryPanel.refreshTarget('main');

      }

    }

    if ((scope === 'intelligence' || scope === 'closed-market') && global.renderAllTabs) {

      try { renderAllTabs({ force: true }); } catch (e) { /* ignore */ }

    }

  }



  async function runRefreshScope(scope) {

    const token = (scope || 'intelligence').toLowerCase();

    if (refreshing) return { ok: false, error: 'refresh in progress' };

    refreshing = true;

    try {

      const res = await fetch(refreshUrl(), {

        method: 'POST',

        headers: {

          ...config.getHeaders(),

          'Content-Type': 'application/json',

        },

        body: JSON.stringify({ scope: token }),

      });

      if (!res.ok) {

        return { ok: false, error: `refresh endpoint → ${res.status}`, cli: REFRESH_CLI };

      }

      const data = await res.json();

      await cacheBustRefetch(token);

      statusMessage = summarizeRefreshResult(data, token);

      return data;

    } catch (err) {

      statusMessage = (err && err.message) || String(err);

      return { ok: false, error: statusMessage, cli: REFRESH_CLI };

    } finally {

      refreshing = false;

    }

  }



  async function runRefresh() {

    const scope = lastReport && lastReport.market_closed ? 'intelligence' : 'all';

    return runRefreshScope(scope);

  }



  function bindActions(root) {

    if (!root) return;

    root.querySelectorAll('[data-sf-scope]').forEach((btn) => {

      btn.addEventListener('click', async () => {

        const scope = btn.getAttribute('data-sf-scope') || 'intelligence';

        btn.disabled = true;

        const prevText = btn.textContent;

        btn.textContent = 'Refreshing…';

        const result = await runRefreshScope(scope);

        if (!result || result.ok === false) {

          const msg = (result && result.error) ? result.error : 'Refresh failed';

          if (!statusMessage) statusMessage = msg;

        }

        try {

          const report = await fetchFreshness();

          const cardEl = btn.closest('.source-freshness-card');

          if (cardEl) {

            cardEl.outerHTML = renderCardHtml(report);

            bindActions(cardEl.parentElement || root);

          } else {

            await mount(root, null, { force: true });

          }

        } catch (err) {

          const cardEl = btn.closest('.source-freshness-card');

          if (cardEl) {

            cardEl.outerHTML = renderCardHtml({ ok: false, error: (err && err.message) || String(err) });

            bindActions(cardEl.parentElement || root);

          }

        } finally {

          if (btn.isConnected) {

            btn.disabled = false;

            btn.textContent = prevText;

          }

        }

      });

    });

  }



  async function mount(containerOrSelector, selector, opts) {

    const options = opts || {};

    let container = containerOrSelector;

    if (typeof containerOrSelector === 'string') {

      container = document.querySelector(containerOrSelector);

    } else if (selector && typeof selector === 'string') {

      container = document.querySelector(selector);

    }

    if (!container) return null;



    if (!options.force && container.dataset.sfLoaded === '1' && lastReport) {

      container.innerHTML = renderCardHtml(lastReport);

      bindActions(container);

      return lastReport;

    }



    container.innerHTML = '<div class="glass-card source-freshness-card"><div class="loading">⏳ Loading freshness…</div></div>';

    try {

      const report = await fetchFreshness();

      container.innerHTML = renderCardHtml(report);

      container.dataset.sfLoaded = '1';

      bindActions(container);

      return report;

    } catch (err) {

      container.innerHTML = renderCardHtml({ ok: false, error: (err && err.message) || String(err) });

      bindActions(container);

      return null;

    }

  }



  function unmount(containerOrSelector) {

    let container = containerOrSelector;

    if (typeof containerOrSelector === 'string') {

      container = document.querySelector(containerOrSelector);

    }

    if (!container) return;

    container.innerHTML = '';

    delete container.dataset.sfLoaded;

    statusMessage = '';

  }



  function init(opts) {

    config.getApiBase = (opts && opts.getApiBase) || config.getApiBase;

    config.getHeaders = (opts && opts.getHeaders) || config.getHeaders;

  }



  global.SourceFreshnessCard = {

    init,

    mount,

    unmount,

    fetchFreshness,

    renderCardHtml,

    bindActionsIn: bindActions,

    runRefreshScope,

    getLastReport: () => lastReport,

    REFRESH_CLI,

    REFRESH_HELPER,

    STALE_PLANNING_MSG,

  };

})(window);

