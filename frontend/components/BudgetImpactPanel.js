/**
 * Budget Impact Intelligence workspace (Stage 48A).
 * Theme Wishlist engine — research-only watch/confirm stances.
 */
(function (global) {
  'use strict';

  const NON_JSON_ERROR = 'Budget API returned non-JSON. Check API route/base.';
  const FETCH_MS = 20000;

  let config = {
    getApiBase: () => '',
    getHeaders: () => ({}),
  };

  let state = {
    overview: null,
    themes: null,
    selectedThemeId: null,
    themeDetail: null,
    themeNews: null,
    themeScan: null,
    analyzeResult: null,
  };

  function escapeHtml(text) {
    if (text == null) return '';
    return String(text)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
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

  async function fetchBudgetJson(path, options, signal) {
    const base = (config.getApiBase() || '').replace(/\/$/, '');
    const url = `${base}${path}${path.indexOf('?') >= 0 ? '&' : '?'}_ts=${Date.now()}`;
    const res = await fetch(url, {
      method: (options && options.method) || 'GET',
      headers: Object.assign({ 'Content-Type': 'application/json' }, config.getHeaders(), (options && options.headers) || {}),
      body: options && options.body ? JSON.stringify(options.body) : undefined,
      cache: 'no-store',
      signal,
    });
    if (!res.ok) throw new Error(`HTTP ${res.status} ${path}`);
    return parseJsonResponse(res, path);
  }

  function freshnessBadge(status) {
    const s = String(status || 'unknown').toLowerCase();
    const cls = s === 'fresh' ? 'bud-fresh' : (s === 'partial' ? 'bud-partial' : 'bud-stale');
    return `<span class="bud-freshness-badge ${cls}">${escapeHtml(status || 'unknown')}</span>`;
  }

  function renderFreshnessPanel(freshness) {
    const f = freshness || {};
    return `<div class="bud-freshness-panel glass-card">
      <div class="bud-section-title">Freshness</div>
      <div class="bud-freshness-grid">
        <div><span class="bud-label">News</span> ${escapeHtml(f.latest_news_age || '—')}</div>
        <div><span class="bud-label">Theme cache</span> ${escapeHtml(f.latest_theme_cache_age || '—')}</div>
        <div><span class="bud-label">Scanner</span> ${escapeHtml(f.latest_scanner_age || '—')}</div>
        <div><span class="bud-label">Status</span> ${freshnessBadge(f.status)}</div>
      </div>
      <button type="button" class="refresh-btn bud-refresh-btn" id="budgetRefreshBtn">↻ Refresh Budget Intel</button>
    </div>`;
  }

  function renderThemeCategories(categories) {
    if (!categories || !Object.keys(categories).length) {
      return '<div class="bud-empty">No theme categories loaded.</div>';
    }
    const blocks = Object.keys(categories).map((cat) => {
      const rows = categories[cat] || [];
      const items = rows.map((row) => {
        const tid = row.theme_id || '';
        const active = state.selectedThemeId === tid ? ' active' : '';
        return `<button type="button" class="bud-theme-chip${active}" data-theme-id="${escapeHtml(tid)}">${escapeHtml(row.display_name || tid)}</button>`;
      }).join('');
      return `<details class="bud-category" open><summary>${escapeHtml(cat)}</summary><div class="bud-theme-chips">${items}</div></details>`;
    }).join('');
    return `<div class="bud-categories glass-card"><div class="bud-section-title">Theme categories</div>${blocks}</div>`;
  }

  function renderCatalystNews(catalysts) {
    const rows = catalysts || [];
    if (!rows.length) {
      return '<div class="bud-empty">No strong fresh catalyst found. Research basket only.</div>';
    }
    const body = rows.map((cat) => `<div class="bud-catalyst-row">
      <div class="bud-catalyst-headline">${escapeHtml(cat.headline || '—')}</div>
      <div class="bud-catalyst-meta">Impact ${escapeHtml(cat.impact_10 || '?')}/10 · Score ${escapeHtml(cat.budget_impact_score || cat.catalyst_score || '?')}</div>
      <div class="bud-catalyst-why">Why: ${escapeHtml(cat.why || '—')}</div>
    </div>`).join('');
    return `<div class="bud-news-panel glass-card"><div class="bud-section-title">Catalyst news</div>${body}</div>`;
  }

  function renderImpactMap(impact) {
    const m = impact || {};
    const list = (title, arr) => {
      const items = (arr || []).slice(0, 8).map((x) => `<li>${escapeHtml(x)}</li>`).join('');
      return `<div class="bud-impact-col"><div class="bud-impact-title">${escapeHtml(title)}</div><ul>${items || '<li>—</li>'}</ul></div>`;
    };
    return `<div class="bud-impact-map glass-card">
      <div class="bud-section-title">Impact map — ${escapeHtml(m.display_name || m.theme_id || 'Theme')}</div>
      <div class="bud-impact-grid">
        ${list('Direct beneficiaries', m.direct_beneficiaries)}
        ${list('Indirect beneficiaries', m.indirect_beneficiaries)}
        ${list('Risks / possible losers', m.risks)}
      </div>
    </div>`;
  }

  function renderStockTable(stocks) {
    const rows = stocks || [];
    if (!rows.length) return '<div class="bud-empty">No ranked stocks — research only.</div>';
    const body = rows.map((row) => `<tr>
      <td>${escapeHtml(row.ticker)}</td>
      <td>${escapeHtml(row.theme || row.theme_id || '—')}</td>
      <td>${escapeHtml(row.impact_side || '—')}</td>
      <td>${escapeHtml(row.score)}</td>
      <td>${escapeHtml(row.reason || '—')}</td>
      <td>${escapeHtml(row.freshness || '—')}</td>
      <td>${escapeHtml(row.confirmation_needed || '—')}</td>
      <td>${escapeHtml(row.stance || 'Research Only')}</td>
    </tr>`).join('');
    return `<div class="bud-table-wrap"><table class="bud-table"><thead><tr>
      <th>Ticker</th><th>Theme</th><th>Impact side</th><th>Score</th><th>Reason</th><th>Freshness</th><th>Confirmation</th><th>Stance</th>
    </tr></thead><tbody>${body}</tbody></table></div>`;
  }

  function renderSimulatorResult(result) {
    if (!result) return '';
    if (result.political_neutral) {
      return `<div class="bud-sim-result glass-card">
        <div class="bud-section-title">Policy continuity mode</div>
        <p>${escapeHtml(result.summary || '')}</p>
        <p><b>Stance:</b> ${escapeHtml(result.stance || 'Wait for Confirmation')}</p>
      </div>`;
    }
    const themes = (result.detected_themes || []).map((t) => escapeHtml(t.display_name || t.theme_id)).join(', ');
    const pos = (result.positive || []).map((p) => escapeHtml(p.ticker)).join(', ');
    const ind = (result.indirect || []).map((p) => escapeHtml(p.ticker)).join(', ');
    const risk = (result.risk || []).map((p) => escapeHtml(p.ticker)).join(', ') || 'No direct loser unless funding/tax/rate impact found.';
    return `<div class="bud-sim-result glass-card">
      <div class="bud-section-title">Analysis result</div>
      <p><b>Detected themes:</b> ${themes || '—'}</p>
      <p><b>Positive:</b> ${pos || '—'}</p>
      <p><b>Indirect:</b> ${ind || '—'}</p>
      <p><b>Risk:</b> ${risk}</p>
      <p><b>Stance:</b> ${escapeHtml(result.stance || 'Research Only')} — ${escapeHtml(result.confirmation || '')}</p>
    </div>`;
  }

  function renderDashboard() {
    const overview = state.overview || {};
    const freshness = overview.freshness || {};
    const categories = (state.themes && state.themes.categories) || {};
    const news = (state.themeNews && state.themeNews.catalysts) || overview.top_catalysts || [];
    const impact = (state.themeDetail && state.themeDetail.impact_map) || null;
    const stocks = (state.themeScan && state.themeScan.stocks) || overview.stock_rankings || [];

    return `<div class="bud-dashboard">
      <div class="bud-header-row">
        <div>
          <h2 class="bud-title">🏛️ Budget Impact Intelligence</h2>
          <p class="bud-subtitle">Maps budget/govt/policy/news events to theme baskets and stock impact.</p>
        </div>
      </div>
      <p class="bud-disclaimer">Research only — watch/confirm. No blind entry.</p>
      ${renderFreshnessPanel(freshness)}
      <div class="bud-layout">
        <div class="bud-left">${renderThemeCategories(categories)}</div>
        <div class="bud-right">
          ${renderCatalystNews(news)}
          ${impact ? renderImpactMap(impact) : ''}
          <div class="bud-stocks glass-card"><div class="bud-section-title">Stock ranking</div>${renderStockTable(stocks)}</div>
        </div>
      </div>
      <div class="bud-simulator glass-card">
        <div class="bud-section-title">Budget event simulator</div>
        <textarea id="budgetSimInput" class="bud-sim-input" rows="3" placeholder="Paste budget/govt news here…"></textarea>
        <button type="button" class="refresh-btn" id="budgetSimBtn">Analyze news</button>
        ${renderSimulatorResult(state.analyzeResult)}
      </div>
    </div>`;
  }

  function wireEvents(host) {
    host.querySelectorAll('.bud-theme-chip').forEach((btn) => {
      btn.addEventListener('click', () => {
        const tid = btn.getAttribute('data-theme-id');
        if (tid) loadThemeDetail(tid, host);
      });
    });
    const refreshBtn = host.querySelector('#budgetRefreshBtn');
    if (refreshBtn) refreshBtn.addEventListener('click', () => refreshBudget(host));
    const simBtn = host.querySelector('#budgetSimBtn');
    if (simBtn) simBtn.addEventListener('click', () => runSimulator(host));
  }

  async function loadThemeDetail(themeId, host) {
    state.selectedThemeId = themeId;
    try {
      const [detail, news, scan] = await Promise.all([
        fetchBudgetJson(`/api/budget/theme/${encodeURIComponent(themeId)}`),
        fetchBudgetJson(`/api/budget/news/${encodeURIComponent(themeId)}`),
        fetchBudgetJson(`/api/budget/scan/${encodeURIComponent(themeId)}`),
      ]);
      state.themeDetail = detail;
      state.themeNews = news;
      state.themeScan = scan;
      host.innerHTML = renderDashboard();
      wireEvents(host);
    } catch (err) {
      host.innerHTML = `<div class="panel-error-card"><strong>Budget theme</strong><p>${escapeHtml(err.message || String(err))}</p></div>`;
    }
  }

  async function refreshBudget(host) {
    try {
      state.overview = await fetchBudgetJson('/api/budget/refresh', { method: 'POST' });
      host.innerHTML = renderDashboard();
      wireEvents(host);
    } catch (err) {
      host.innerHTML = `<div class="panel-error-card"><strong>Budget refresh</strong><p>${escapeHtml(err.message || String(err))}</p></div>`;
    }
  }

  async function runSimulator(host) {
    const input = host.querySelector('#budgetSimInput');
    const text = input ? String(input.value || '').trim() : '';
    if (!text) return;
    try {
      state.analyzeResult = await fetchBudgetJson('/api/budget/analyze-news', {
        method: 'POST',
        body: { text },
      });
      host.innerHTML = renderDashboard();
      wireEvents(host);
      const ta = host.querySelector('#budgetSimInput');
      if (ta) ta.value = text;
    } catch (err) {
      state.analyzeResult = { political_neutral: false, summary: err.message || String(err) };
      host.innerHTML = renderDashboard();
      wireEvents(host);
    }
  }

  async function loadMain(targetEl) {
    const host = targetEl || document.getElementById('budgetMainContent');
    if (!host) return;
    host.innerHTML = '<div class="loading">⏳ Loading Budget Impact Intelligence…</div>';
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), FETCH_MS);
    try {
      const [overview, themes] = await Promise.all([
        fetchBudgetJson('/api/budget/overview', null, controller.signal),
        fetchBudgetJson('/api/budget/themes', null, controller.signal),
      ]);
      state.overview = overview;
      state.themes = themes;
      host.innerHTML = renderDashboard();
      wireEvents(host);
    } catch (err) {
      host.innerHTML = `<div class="panel-error-card"><strong>Budget Impact Intelligence</strong><p>${escapeHtml(err.message || String(err))}</p></div>`;
    } finally {
      clearTimeout(timer);
    }
  }

  function init(opts) {
    config.getApiBase = (opts && opts.getApiBase) || config.getApiBase;
    config.getHeaders = (opts && opts.getHeaders) || config.getHeaders;
  }

  global.BudgetImpactPanel = { init, loadMain };
})(typeof window !== 'undefined' ? window : globalThis);
