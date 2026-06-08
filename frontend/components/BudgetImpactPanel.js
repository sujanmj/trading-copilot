/**
 * Budget Impact Intelligence workspace (Stage 48H).
 * Theme + catalyst drilldown — cache-only lite loads on click.
 */
(function (global) {
  'use strict';

  const NON_JSON_ERROR = 'Budget API returned non-JSON. Check API route/base.';
  const CACHE_FETCH_MS = 8000;
  const FETCH_MS = CACHE_FETCH_MS;
  const REFRESH_MS = 90000;
  const CACHE_MISSING_MSG = 'Budget cache unavailable. Tap Refresh Budget Intel.';
  const CACHE_TIMEOUT_MSG = 'Budget cache request timed out. Tap Refresh Budget Intel.';
  const REFRESH_TIMEOUT_MSG = 'Budget refresh may still be running. Try again in a minute.';
  const OVERVIEW_LITE_PATH = '/api/budget/overview?cache_only=1&lite=1';
  const THEMES_LITE_PATH = '/api/budget/themes?lite=1';
  const LITE_QS = 'cache_only=1&lite=1';
  const abortMeta = new WeakMap();

  let config = {
    getApiBase: () => '',
    getHeaders: () => ({}),
  };

  let state = {
    overview: null,
    themes: null,
    selectedThemeId: null,
    selectedThemeName: null,
    selectedCatalystId: null,
    selectedCatalystHeadline: null,
    themeDetail: null,
    themeNews: null,
    themeScan: null,
    catalystDrilldown: null,
    analyzeResult: null,
  };

  let loadGeneration = 0;
  let activeController = null;

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

  function budgetFetchErrorMessage(err, controller, context) {
    if (isStaleAbort(err, controller)) return null;
    if (err && err.name === 'AbortError') {
      if (context === 'refresh') return REFRESH_TIMEOUT_MSG;
      return CACHE_TIMEOUT_MSG;
    }
    const msg = err && err.message ? String(err.message) : String(err || '');
    if (/signal is aborted/i.test(msg)) {
      return context === 'refresh' ? REFRESH_TIMEOUT_MSG : CACHE_TIMEOUT_MSG;
    }
    if (/timed out|timeout|cancelled/i.test(msg)) {
      return context === 'refresh' ? REFRESH_TIMEOUT_MSG : CACHE_TIMEOUT_MSG;
    }
    return msg || CACHE_TIMEOUT_MSG;
  }

  function renderBudgetShell(message, showRefresh) {
    const refreshBtn = showRefresh
      ? '<button type="button" class="refresh-btn bud-refresh-btn" id="budgetRefreshBtn">↻ Refresh Budget Intel</button>'
      : '';
    return `<div class="bud-dashboard">
      <div class="bud-header-row"><h2 class="bud-title">🏛️ Budget Impact Intelligence</h2></div>
      <p class="bud-disclaimer">Research only — watch/confirm. No blind entry.</p>
      <div class="panel-error-card"><p>${escapeHtml(message || CACHE_MISSING_MSG)}</p></div>
      ${refreshBtn}
    </div>`;
  }

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

  async function fetchBudgetJsonWithRetry(path, options, controller) {
    const signal = controller.signal;
    try {
      return await fetchBudgetJson(path, options, signal);
    } catch (err) {
      if (isStaleAbort(err, controller)) throw err;
      if (err && err.name === 'AbortError') throw err;
      return fetchBudgetJson(path, options, signal);
    }
  }

  function themeLitePath(themeId) {
    return `/api/budget/theme/${encodeURIComponent(themeId)}?${LITE_QS}`;
  }

  function newsLitePath(themeId) {
    return `/api/budget/news/${encodeURIComponent(themeId)}?${LITE_QS}`;
  }

  function scanLitePath(themeId, catalystId) {
    let path = `/api/budget/scan/${encodeURIComponent(themeId)}?${LITE_QS}`;
    if (catalystId) path += `&catalyst_id=${encodeURIComponent(catalystId)}`;
    return path;
  }

  function catalystLitePath(catalystId) {
    return `/api/budget/catalyst/${encodeURIComponent(catalystId)}?${LITE_QS}`;
  }

  function findThemeDisplayName(themeId) {
    const categories = (state.themes && state.themes.categories) || {};
    const keys = Object.keys(categories);
    for (let i = 0; i < keys.length; i += 1) {
      const rows = categories[keys[i]] || [];
      for (let j = 0; j < rows.length; j += 1) {
        if (rows[j].theme_id === themeId) return rows[j].display_name || themeId;
      }
    }
    const theme = (state.themeDetail && state.themeDetail.theme) || {};
    return theme.display_name || themeId;
  }

  function renderSelectionBar() {
    const themeLabel = state.selectedThemeId
      ? escapeHtml(state.selectedThemeName || findThemeDisplayName(state.selectedThemeId))
      : 'All';
    const catalystLabel = state.selectedCatalystHeadline
      ? escapeHtml(String(state.selectedCatalystHeadline).slice(0, 120))
      : 'None';
    return `<div class="bud-selection-bar glass-card">
      <div class="bud-selection-row"><span class="bud-label">Selected theme:</span> <strong>${themeLabel}</strong></div>
      <div class="bud-selection-row"><span class="bud-label">Selected catalyst:</span> <strong>${catalystLabel}</strong></div>
      <div class="bud-selection-actions">
        <button type="button" class="refresh-btn bud-clear-btn" id="budgetClearThemeBtn">Clear Theme</button>
        <button type="button" class="refresh-btn bud-clear-btn" id="budgetClearCatalystBtn">Clear Catalyst</button>
        <button type="button" class="refresh-btn bud-refresh-btn" id="budgetRefreshBtn">↻ Refresh Budget Intel</button>
      </div>
    </div>`;
  }

  function renderCatalystDrilldown(drill) {
    if (!drill || !state.selectedCatalystId) return '';
    const themes = (drill.detected_themes || []).map((t) => escapeHtml(t.display_name || t.theme_id)).join(', ');
    const listTickers = (rows) => (rows || []).map((r) => escapeHtml(r.ticker)).filter(Boolean).join(', ') || '—';
    const fresh = (drill.freshness && drill.freshness.status) || 'unknown';
    return `<div class="bud-drilldown glass-card">
      <div class="bud-section-title">Catalyst impact drilldown</div>
      <p><b>Headline:</b> ${escapeHtml(drill.headline || state.selectedCatalystHeadline || '—')}</p>
      <p><b>Direction:</b> ${escapeHtml(formatCatalystDirection(drill.direction || drill.catalyst_direction))}</p>
      <p><b>Detected themes:</b> ${themes || 'Unavailable'}</p>
      <p><b>Direct beneficiaries:</b> ${listTickers(drill.direct_beneficiaries)}</p>
      <p><b>Indirect beneficiaries:</b> ${listTickers(drill.indirect_beneficiaries)}</p>
      <p><b>Avoid / Risk:</b> ${listTickers(drill.avoid_risk)}</p>
      <p><b>Wait for confirmation:</b> ${listTickers(drill.wait_confirmation)}</p>
      <p><b>Reason:</b> ${escapeHtml(drill.reason || '—')}</p>
      <p><b>Freshness:</b> ${escapeHtml(fresh)}</p>
      <p><b>Suggested stance:</b> ${escapeHtml(drill.suggested_stance || 'Research Only')}</p>
      <p class="bud-muted">${escapeHtml(drill.confirmation || 'Confirm with price + volume + sector breadth.')}</p>
    </div>`;
  }

  function freshnessBadge(status) {
    const s = String(status || 'unknown').toLowerCase();
    const cls = s === 'fresh' ? 'bud-fresh' : (s === 'partial' ? 'bud-partial' : 'bud-stale');
    return `<span class="bud-freshness-badge ${cls}">${escapeHtml(status || 'unknown')}</span>`;
  }

  function freshnessSourceRow(label, row) {
    const r = row || {};
    const age = r.age_label || r.latest_age || 'Unavailable';
    const ts = r.timestamp ? escapeHtml(String(r.timestamp).slice(0, 19)) : 'Unavailable';
    const status = r.status || 'unavailable';
    return `<div class="bud-freshness-item">
      <div class="bud-freshness-head"><span class="bud-label">${escapeHtml(label)}</span> ${freshnessBadge(status)}</div>
      <div class="bud-freshness-meta">${escapeHtml(age)} · ${ts}</div>
    </div>`;
  }

  function renderFreshnessPanel(freshness) {
    const f = freshness || {};
    const news = f.news || {};
    const theme = f.theme_cache || {};
    const scanner = f.scanner || {};
    const budget = f.budget_cache || {};
    return `<div class="bud-freshness-panel glass-card">
      <div class="bud-section-title">Freshness</div>
      <div class="bud-freshness-grid">
        ${freshnessSourceRow('News', Object.assign({}, news, { age_label: f.latest_news_age || news.age_label }))}
        ${freshnessSourceRow('Budget theme cache', Object.assign({}, theme, { age_label: f.latest_budget_theme_cache_age || f.latest_theme_cache_age || theme.age_label }))}
        ${freshnessSourceRow('Scanner', Object.assign({}, scanner, { age_label: f.latest_scanner_age || scanner.age_label }))}
        ${freshnessSourceRow('Budget cache', Object.assign({}, budget, { age_label: f.latest_budget_cache_age || budget.age_label }))}
        <div><span class="bud-label">Status</span> ${freshnessBadge(f.status || 'unavailable')}</div>
      </div>
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

  function formatCatalystDirection(direction) {
    const d = String(direction || '').trim();
    if (!d || d === '?') return 'Neutral';
    return d;
  }

  function renderCatalystNews(catalysts) {
    const rows = catalysts || [];
    if (!rows.length) {
      return '<div class="bud-empty">No strong fresh catalyst found. Research basket only.</div>';
    }
    const body = rows.map((cat) => {
      const cid = cat.catalyst_id || '';
      const active = state.selectedCatalystId && cid === state.selectedCatalystId ? ' active' : '';
      return `<button type="button" class="bud-catalyst-row bud-catalyst-btn${active}" data-catalyst-id="${escapeHtml(cid)}" data-theme-id="${escapeHtml(cat.theme_id || state.selectedThemeId || '')}" data-headline="${escapeHtml(cat.headline || '')}">
      <div class="bud-catalyst-headline">${escapeHtml(cat.headline || '—')}</div>
      <div class="bud-catalyst-meta">Direction ${escapeHtml(formatCatalystDirection(cat.catalyst_direction))} · Impact ${escapeHtml(cat.impact_10 || '?')}/10 · Score ${escapeHtml(cat.budget_impact_score || cat.catalyst_score || '?')}</div>
      <div class="bud-catalyst-why">Why: ${escapeHtml(cat.why || '—')}</div>
    </button>`;
    }).join('');
    const title = state.selectedThemeId
      ? `Catalyst news — ${escapeHtml(state.selectedThemeName || findThemeDisplayName(state.selectedThemeId))}`
      : 'Catalyst news';
    return `<div class="bud-news-panel glass-card"><div class="bud-section-title">${title}</div>${body}</div>`;
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

  function renderStockTable(stocks, sections, sectionLabels) {
    const labels = sectionLabels || {
      positive_investment_watch: 'Positive / Investment Watch',
      indirect_watch: 'Indirect Watch',
      avoid_risk: 'Avoid / Risk',
      wait_confirmation: 'Wait for Confirmation',
      research_only: 'Research Only',
    };
    const grouped = sections || buildSectionsFromStocks(stocks || []);
    const keys = [
      'positive_investment_watch',
      'indirect_watch',
      'avoid_risk',
      'wait_confirmation',
      'research_only',
    ];
    const blocks = keys.map((key) => {
      const rows = grouped[key] || [];
      if (!rows.length) return '';
      const body = rows.map((row) => {
        if (!row.ticker) return '';
        return `<tr>
          <td>${escapeHtml(row.ticker)}</td>
          <td>${escapeHtml(row.theme || row.theme_id || '—')}</td>
          <td>${escapeHtml(row.impact_side || '—')}</td>
          <td>${escapeHtml(row.score)}</td>
          <td>${escapeHtml(row.reason || '—')}</td>
          <td>${escapeHtml(row.freshness || '—')}</td>
          <td>${escapeHtml(row.confirmation_needed || '—')}</td>
          <td>${escapeHtml(row.stance || 'Research Only')}</td>
        </tr>`;
      }).join('');
      return `<div class="bud-stock-section"><div class="bud-section-subtitle">${escapeHtml(labels[key] || key)}</div>
        <div class="bud-table-wrap"><table class="bud-table"><thead><tr>
          <th>Ticker</th><th>Theme</th><th>Impact side</th><th>Score</th><th>Reason</th><th>Freshness</th><th>Confirmation</th><th>Stance</th>
        </tr></thead><tbody>${body}</tbody></table></div></div>`;
    }).join('');
    if (!blocks.trim()) return '<div class="bud-empty">No ranked stocks — research only.</div>';
    return blocks;
  }

  function buildSectionsFromStocks(stocks) {
    const grouped = {
      positive_investment_watch: [],
      indirect_watch: [],
      avoid_risk: [],
      wait_confirmation: [],
      research_only: [],
    };
    (stocks || []).forEach((row) => {
      const key = row.section || 'research_only';
      if (grouped[key]) grouped[key].push(row);
      else grouped.research_only.push(row);
    });
    return grouped;
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
    const pos = (result.direct_beneficiaries || result.positive || []).map((p) => escapeHtml(p.ticker)).filter(Boolean).join(', ');
    const ind = (result.indirect_beneficiaries || result.indirect || []).map((p) => escapeHtml(p.ticker)).filter(Boolean).join(', ');
    const risk = (result.risks_possible_losers || result.risk || []).map((p) => escapeHtml(p.ticker)).filter(Boolean).join(', ') || 'No direct loser unless funding/tax/rate impact found.';
    const direction = result.detected_direction || result.catalyst_direction || 'Mixed';
    const stance = result.suggested_stance || result.stance || 'Research Only';
    return `<div class="bud-sim-result glass-card">
      <div class="bud-section-title">Analysis result</div>
      <p><b>Detected direction:</b> ${escapeHtml(direction)}</p>
      <p><b>Detected themes:</b> ${themes || 'Unavailable'}</p>
      <p><b>Direct beneficiaries:</b> ${pos || '—'}</p>
      <p><b>Indirect beneficiaries:</b> ${ind || '—'}</p>
      <p><b>Risks / possible losers:</b> ${risk}</p>
      <p><b>Suggested stance:</b> ${escapeHtml(stance)} — ${escapeHtml(result.confirmation || '')}</p>
    </div>`;
  }

  function renderDashboard() {
    const overview = state.overview || {};
    if (overview.cache_missing) {
      return `<div class="bud-dashboard">
        <div class="bud-header-row"><h2 class="bud-title">🏛️ Budget Impact Intelligence</h2></div>
        <div class="panel-error-card"><p>${escapeHtml(overview.message || CACHE_MISSING_MSG)}</p></div>
        <button type="button" class="refresh-btn bud-refresh-btn" id="budgetRefreshBtn">↻ Refresh Budget Intel</button>
      </div>`;
    }
    const freshness = overview.freshness || {};
    const categories = (state.themes && state.themes.categories) || {};
    let news = overview.top_catalysts || [];
    let impact = null;
    let stocks = overview.stock_rankings || [];
    let sections = overview.stock_ranking_sections || null;
    let sectionLabels = overview.section_labels || null;
    let rankingTitle = 'Stock ranking — top overall budget impact';

    if (state.selectedThemeId) {
      news = (state.themeNews && state.themeNews.catalysts) || news;
      impact = (state.themeDetail && (state.themeDetail.impact_map || (state.themeDetail.theme && state.themeDetail.theme.impact_map))) || null;
      stocks = (state.themeScan && state.themeScan.stocks) || stocks;
      sections = (state.themeScan && state.themeScan.sections) || sections;
      sectionLabels = (state.themeScan && state.themeScan.section_labels) || sectionLabels;
      rankingTitle = `Stock ranking — ${escapeHtml(state.selectedThemeName || findThemeDisplayName(state.selectedThemeId))}`;
    }

    if (state.selectedCatalystId && state.catalystDrilldown) {
      stocks = state.catalystDrilldown.stocks || stocks;
      sections = state.catalystDrilldown.stock_sections || sections;
      sectionLabels = state.catalystDrilldown.section_labels || sectionLabels;
      rankingTitle = 'Stock ranking — selected catalyst impact';
    }

    const themeHeader = state.selectedThemeId
      ? `<p class="bud-selected-theme"><b>Selected theme:</b> ${escapeHtml(state.selectedThemeName || findThemeDisplayName(state.selectedThemeId))}</p>`
      : '';

    return `<div class="bud-dashboard">
      <div class="bud-header-row">
        <div>
          <h2 class="bud-title">🏛️ Budget Impact Intelligence</h2>
          <p class="bud-subtitle">Maps budget/govt/policy/news events to theme baskets and stock impact.</p>
        </div>
      </div>
      <p class="bud-disclaimer">Research only — watch/confirm. No blind entry.</p>
      ${renderSelectionBar()}
      ${themeHeader}
      ${renderFreshnessPanel(freshness)}
      <div class="bud-layout">
        <div class="bud-left">${renderThemeCategories(categories)}</div>
        <div class="bud-right">
          ${renderCatalystNews(news)}
          ${renderCatalystDrilldown(state.catalystDrilldown)}
          ${impact ? renderImpactMap(impact) : ''}
          <div class="bud-stocks glass-card"><div class="bud-section-title">${rankingTitle}</div>${renderStockTable(stocks, sections, sectionLabels)}</div>
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
    host.querySelectorAll('.bud-catalyst-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        const cid = btn.getAttribute('data-catalyst-id');
        const tid = btn.getAttribute('data-theme-id') || state.selectedThemeId;
        const headline = btn.getAttribute('data-headline') || '';
        if (cid && tid) loadCatalystDrilldown(cid, tid, headline, host);
      });
    });
    const clearThemeBtn = host.querySelector('#budgetClearThemeBtn');
    if (clearThemeBtn) clearThemeBtn.addEventListener('click', () => clearTheme(host));
    const clearCatalystBtn = host.querySelector('#budgetClearCatalystBtn');
    if (clearCatalystBtn) clearCatalystBtn.addEventListener('click', () => clearCatalyst(host));
    const refreshBtn = host.querySelector('#budgetRefreshBtn');
    if (refreshBtn) refreshBtn.addEventListener('click', () => refreshBudget(host));
    const simBtn = host.querySelector('#budgetSimBtn');
    if (simBtn) simBtn.addEventListener('click', () => runSimulator(host));
  }

  function clearTheme(host) {
    state.selectedThemeId = null;
    state.selectedThemeName = null;
    state.themeDetail = null;
    state.themeNews = null;
    state.themeScan = null;
    clearCatalystState(false);
    host.innerHTML = renderDashboard();
    wireEvents(host);
  }

  function clearCatalystState(rerender) {
    state.selectedCatalystId = null;
    state.selectedCatalystHeadline = null;
    state.catalystDrilldown = null;
  }

  function clearCatalyst(host) {
    clearCatalystState(false);
    host.innerHTML = renderDashboard();
    wireEvents(host);
  }

  async function loadThemeDetail(themeId, host) {
    state.selectedThemeId = themeId;
    state.selectedThemeName = findThemeDisplayName(themeId);
    clearCatalystState(false);
    const controller = createAbortController('theme_detail');
    const timer = setTimeout(() => {
      abortMeta.set(controller, { reason: 'timeout' });
      controller.abort();
    }, FETCH_MS);
    try {
      const [detail, news, scan] = await Promise.all([
        fetchBudgetJson(themeLitePath(themeId), null, controller.signal),
        fetchBudgetJson(newsLitePath(themeId), null, controller.signal),
        fetchBudgetJson(scanLitePath(themeId), null, controller.signal),
      ]);
      state.themeDetail = detail;
      state.themeNews = news;
      state.themeScan = scan;
      if (detail.theme && detail.theme.display_name) {
        state.selectedThemeName = detail.theme.display_name;
      }
      host.innerHTML = renderDashboard();
      wireEvents(host);
    } catch (err) {
      const msg = budgetFetchErrorMessage(err, controller, 'theme');
      if (msg) {
        host.innerHTML = `<div class="panel-error-card"><strong>Budget theme</strong><p>${escapeHtml(msg)}</p></div>`;
      }
    } finally {
      clearTimeout(timer);
    }
  }

  async function loadCatalystDrilldown(catalystId, themeId, headline, host) {
    state.selectedCatalystId = catalystId;
    state.selectedCatalystHeadline = headline;
    if (!state.selectedThemeId && themeId) {
      state.selectedThemeId = themeId;
      state.selectedThemeName = findThemeDisplayName(themeId);
    }
    const controller = createAbortController('catalyst_detail');
    const timer = setTimeout(() => {
      abortMeta.set(controller, { reason: 'timeout' });
      controller.abort();
    }, FETCH_MS);
    try {
      const [drill, scan] = await Promise.all([
        fetchBudgetJson(catalystLitePath(catalystId), null, controller.signal),
        fetchBudgetJson(scanLitePath(themeId || state.selectedThemeId, catalystId), null, controller.signal),
      ]);
      state.catalystDrilldown = drill;
      state.themeScan = scan;
      host.innerHTML = renderDashboard();
      wireEvents(host);
    } catch (err) {
      const msg = budgetFetchErrorMessage(err, controller, 'catalyst');
      if (msg) {
        host.innerHTML = `<div class="panel-error-card"><strong>Budget catalyst</strong><p>${escapeHtml(msg)}</p></div>`;
      }
    } finally {
      clearTimeout(timer);
    }
  }

  async function refreshBudget(host) {
    host.innerHTML = '<div class="loading">⏳ Refreshing Budget Impact Intelligence…</div>';
    const controller = createAbortController('refresh');
    const timer = setTimeout(() => {
      abortMeta.set(controller, { reason: 'timeout' });
      controller.abort();
    }, REFRESH_MS);
    try {
      await fetchBudgetJson('/api/budget/refresh', { method: 'POST' }, controller.signal);
      const [overview, themes] = await Promise.all([
        fetchBudgetJsonWithRetry(OVERVIEW_LITE_PATH, null, controller),
        fetchBudgetJsonWithRetry(THEMES_LITE_PATH, null, controller),
      ]);
      state.overview = overview;
      state.themes = themes;
      if (state.selectedThemeId) {
        const tid = state.selectedThemeId;
        const scanPath = scanLitePath(tid, state.selectedCatalystId);
        const reqs = [
          fetchBudgetJson(themeLitePath(tid), null, controller.signal),
          fetchBudgetJson(newsLitePath(tid), null, controller.signal),
          fetchBudgetJson(scanPath, null, controller.signal),
        ];
        if (state.selectedCatalystId) {
          reqs.push(fetchBudgetJson(catalystLitePath(state.selectedCatalystId), null, controller.signal));
        }
        const results = await Promise.all(reqs);
        state.themeDetail = results[0];
        state.themeNews = results[1];
        state.themeScan = results[2];
        if (state.selectedCatalystId && results[3]) state.catalystDrilldown = results[3];
      }
      host.innerHTML = renderDashboard();
      wireEvents(host);
    } catch (err) {
      const msg = budgetFetchErrorMessage(err, controller, 'refresh');
      if (msg) {
        host.innerHTML = renderBudgetShell(msg, true);
        wireEvents(host);
      }
    } finally {
      clearTimeout(timer);
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
      const msg = budgetFetchErrorMessage(err, null);
      if (!msg) return;
      state.analyzeResult = { political_neutral: false, summary: msg };
      host.innerHTML = renderDashboard();
      wireEvents(host);
    }
  }

  async function loadMain(targetEl) {
    const host = targetEl || document.getElementById('budgetMainContent');
    if (!host) return;

    loadGeneration += 1;
    const myGen = loadGeneration;
    abortActiveRequest('superseded');

    host.innerHTML = '<div class="loading">⏳ Loading Budget Impact Intelligence…</div>';

    const controller = createAbortController('load');
    activeController = controller;
    const timer = setTimeout(() => {
      abortMeta.set(controller, { reason: 'timeout' });
      controller.abort();
    }, FETCH_MS);

    try {
      const [overview, themes] = await Promise.all([
        fetchBudgetJsonWithRetry(OVERVIEW_LITE_PATH, null, controller),
        fetchBudgetJsonWithRetry(THEMES_LITE_PATH, null, controller),
      ]);
      if (myGen !== loadGeneration) return;
      state.overview = overview;
      state.themes = themes;
      host.innerHTML = renderDashboard();
      wireEvents(host);
    } catch (err) {
      if (myGen !== loadGeneration) return;
      const msg = budgetFetchErrorMessage(err, controller, 'load');
      state.overview = { cache_missing: true, message: msg || CACHE_MISSING_MSG };
      state.themes = state.themes || { categories: {} };
      host.innerHTML = msg ? renderBudgetShell(msg, true) : renderDashboard();
      wireEvents(host);
    } finally {
      clearTimeout(timer);
      if (activeController === controller) activeController = null;
    }
  }

  function init(opts) {
    config.getApiBase = (opts && opts.getApiBase) || config.getApiBase;
    config.getHeaders = (opts && opts.getHeaders) || config.getHeaders;
  }

  global.BudgetImpactPanel = { init, loadMain };
})(typeof window !== 'undefined' ? window : globalThis);
