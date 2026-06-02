/**

 * Canonical Market Memory — read-only dashboard (Shadow Advisor).

 * Fetches GET /api/debug/market-memory/dashboard?limit=50&_ts=<cache-bust>

 * No runtime snapshot / AI hub fallback.

 */

(function (global) {

  'use strict';



  const DASHBOARD_SOURCE = '/api/debug/market-memory/dashboard';

  const HISTORICAL_LEARNING_SOURCE = '/api/debug/historical-learning';

  const FINAL_CONFIDENCE_SOURCE = '/api/debug/final-confidence/report';

  const CONFIDENCE_CALIBRATION_SOURCE = '/api/debug/confidence-calibration';

  const DAILY_REPORT_PACK_SOURCE = '/api/debug/daily-report-pack';

  const DEBUG_ACTIVE_VIEW_MEMORY = 'activeView=memory';

  const FETCH_MS = 12000;



  let config = {

    getApiBase: () => '',

    getHeaders: () => ({}),

  };

  const loadingByTarget = {};

  const MEMORY_CACHE_TTL_MS = 5 * 60 * 1000;

  let dashboardCache = null;



  function escapeHtml(text) {

    if (text == null) return '';

    return String(text)

      .replace(/&/g, '&amp;')

      .replace(/</g, '&lt;')

      .replace(/>/g, '&gt;')

      .replace(/"/g, '&quot;');

  }



  function fmtWinRate(v) {

    if (v == null || v === '') return '—';

    const n = Number(v);

    return Number.isFinite(n) ? `${(n * 100).toFixed(1)}%` : escapeHtml(v);

  }



  function fmtMove(v) {

    if (v == null || v === '') return '—';

    const n = Number(v);

    if (!Number.isFinite(n)) return escapeHtml(v);

    const sign = n >= 0 ? '+' : '';

    return `${sign}${n.toFixed(2)}%`;

  }



  function fmtUpdatedAt(d) {

    if (!d) return '—';

    try {

      return d.toLocaleString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });

    } catch (e) {

      return String(d);

    }

  }



  function outcomeLabel(resolvedAs) {

    const token = String(resolvedAs || '').trim().toUpperCase();

    if (!token) return '—';

    if (token.startsWith('WIN') || token === 'WIN') return 'WIN';

    if (token.startsWith('LOSS') || token === 'LOSS') return 'LOSS';

    return token;

  }



  function outcomeClass(resolvedAs) {

    const label = outcomeLabel(resolvedAs);

    if (label === 'WIN') return 'mm-win';

    if (label === 'LOSS') return 'mm-loss';

    return 'mm-muted';

  }



  function dashboardUrl() {

    const base = config.getApiBase().replace(/\/$/, '');

    const ts = Date.now();

    return `${base}${DASHBOARD_SOURCE}?limit=50&_ts=${ts}`;

  }



  function fetchHeaders() {

    return {

      ...config.getHeaders(),

      'Cache-Control': 'no-cache, no-store, must-revalidate',

      Pragma: 'no-cache',

    };

  }



  function historicalLearningUrl(ticker) {

    const base = config.getApiBase().replace(/\/$/, '');

    const ts = Date.now();

    const suffix = ticker ? `&ticker=${encodeURIComponent(ticker)}` : '';

    return `${base}${HISTORICAL_LEARNING_SOURCE}?_ts=${ts}${suffix}`;

  }



  async function fetchDashboard() {

    const controller = new AbortController();

    const timer = setTimeout(() => controller.abort(), FETCH_MS);

    try {

      const res = await fetch(dashboardUrl(), {

        method: 'GET',

        headers: fetchHeaders(),

        cache: 'no-store',

        signal: controller.signal,

      });

      if (!res.ok) throw new Error(`dashboard → ${res.status}`);

      const data = await res.json();

      if (!data || data.ok !== true) {

        throw new Error((data && data.error) || 'dashboard ok=false');

      }

      return { data, fetchedAt: new Date() };

    } finally {

      clearTimeout(timer);

    }

  }



  async function fetchHistoricalLearning() {

    const controller = new AbortController();

    const timer = setTimeout(() => controller.abort(), FETCH_MS);

    try {

      const res = await fetch(historicalLearningUrl(), {

        method: 'GET',

        headers: fetchHeaders(),

        cache: 'no-store',

        signal: controller.signal,

      });

      if (!res.ok) throw new Error(`historical-learning → ${res.status}`);

      const data = await res.json();

      if (!data || data.ok !== true) {

        throw new Error((data && data.error) || 'historical-learning ok=false');

      }

      return data;

    } finally {

      clearTimeout(timer);

    }

  }



  function finalConfidenceUrl() {

    const base = config.getApiBase().replace(/\/$/, '');

    const ts = Date.now();

    return `${base}${FINAL_CONFIDENCE_SOURCE}?limit=50&_ts=${ts}`;

  }



  async function fetchFinalConfidence() {

    const controller = new AbortController();

    const timer = setTimeout(() => controller.abort(), FETCH_MS);

    try {

      const res = await fetch(finalConfidenceUrl(), {

        method: 'GET',

        headers: fetchHeaders(),

        cache: 'no-store',

        signal: controller.signal,

      });

      if (!res.ok) throw new Error(`final-confidence → ${res.status}`);

      const data = await res.json();

      if (!data || data.ok !== true) {

        throw new Error((data && data.error) || 'final-confidence ok=false');

      }

      return data;

    } finally {

      clearTimeout(timer);

    }

  }



  function statCard(label, value, sub, cls) {

    return `

      <div class="stat-big-card">

        <div class="stat-big-label">${escapeHtml(label)}</div>

        <div class="stat-big-value ${cls || ''}">${escapeHtml(String(value))}</div>

        ${sub ? `<div class="stat-big-sub">${escapeHtml(sub)}</div>` : ''}

      </div>`;

  }



  function learningTable(title, groupMap) {

    const entries = Object.entries(groupMap || {}).sort((a, b) => {

      const ra = (a[1] && a[1].resolved) || 0;

      const rb = (b[1] && b[1].resolved) || 0;

      return rb - ra || a[0].localeCompare(b[0]);

    });

    if (!entries.length) {

      return `

        <div class="mm-learning-block">

          <div class="mm-learning-title">${escapeHtml(title)}</div>

          <div class="mm-empty">No resolved samples yet.</div>

        </div>`;

    }

    const rows = entries.map(([key, m]) => {

      const wins = (m && m.wins) || 0;

      const losses = (m && m.losses) || 0;

      return `

        <tr>

          <td>${escapeHtml(key)}</td>

          <td>${(m && m.resolved) || 0}</td>

          <td>${fmtWinRate(m && m.win_rate)}</td>

          <td>${wins}W / ${losses}L</td>

        </tr>`;

    }).join('');

    return `

      <div class="mm-learning-block">

        <div class="mm-learning-title">${escapeHtml(title)}</div>

        <table class="mm-table mm-table-compact">

          <thead><tr><th>Group</th><th>n</th><th>Win%</th><th>W/L</th></tr></thead>

          <tbody>${rows}</tbody>

        </table>

      </div>`;

  }



  function renderDataTable(title, headers, rowsHtml, emptyMsg) {

    if (!rowsHtml) {

      return `

        <div class="glass-card mm-section">

          <h2>${escapeHtml(title)}</h2>

          <div class="mm-empty">${escapeHtml(emptyMsg || 'No rows yet.')}</div>

        </div>`;

    }

    return `

      <div class="glass-card mm-section">

        <h2>${escapeHtml(title)}</h2>

        <table class="mm-table">

          <thead><tr>${headers.map((h) => `<th>${escapeHtml(h)}</th>`).join('')}</tr></thead>

          <tbody>${rowsHtml}</tbody>

        </table>

      </div>`;

  }



  function debugFooterHtml(fetchedAt) {

    return `<div class="mm-debug-line">source=${escapeHtml(DASHBOARD_SOURCE)} ${DEBUG_ACTIVE_VIEW_MEMORY} updated=${escapeHtml(fmtUpdatedAt(fetchedAt))}</div>`;

  }



  function targetOptions(targetKey) {

    if (targetKey === 'main') {

      return { includeFreshness: true, activeView: 'memory' };

    }

    return { includeFreshness: false, activeView: 'aihub' };

  }



  function renderMemTabShortcutHtml() {

    return `

      <div class="glass-card mm-mem-shortcut">

        <div class="mm-mem-shortcut-title">📚 Market Memory</div>

        <p class="mm-mem-shortcut-desc">

          Canonical learning dashboard with predictions, outcomes, and Shadow Advisor stats.

        </p>

        <button type="button" class="refresh-btn mm-open-full-btn" data-mm-open-full="1">

          Open full Memory Dashboard

        </button>

      </div>`;

  }



  function bindMemTabShortcut(container) {

    if (!container) return;

    container.querySelectorAll('[data-mm-open-full="1"]').forEach((btn) => {

      btn.addEventListener('click', (e) => {

        e.preventDefault();

        e.stopPropagation();

        openMainView();

      });

    });

  }



  function renderMemTabShortcut() {

    const container = document.getElementById('tab-memory');

    if (!container) return;

    container.innerHTML = renderMemTabShortcutHtml();

    bindMemTabShortcut(container);

  }

  function setMemoryViewActive(active) {

    if (active && global.SourceFreshnessCard && SourceFreshnessCard.unmount) {

      SourceFreshnessCard.unmount('#sourceFreshnessCardHost');

    }

    if (global.WorkspaceManager && WorkspaceManager.setActiveWorkspace) {

      if (active) {

        const navBtn = document.getElementById('memoryNavBtn');

        WorkspaceManager.setActiveWorkspace('memory', { navBtn: navBtn || undefined });

      } else if (WorkspaceManager.closeMemoryView) {

        WorkspaceManager.closeMemoryView();

      }

      return;

    }

    const main = document.getElementById('mainWorkspace') || document.querySelector('.main');

    if (main) {

      if (active) main.classList.add('memory-view-active');

      else main.classList.remove('memory-view-active');

    }

  }



  function getCacheAgeMinutes() {

    if (!dashboardCache || !dashboardCache.fetchedAt) return null;

    return Math.floor((Date.now() - dashboardCache.fetchedAt.getTime()) / 60000);

  }



  function isMemoryCacheValid() {

    if (!dashboardCache || !dashboardCache.fetchedAt) return false;

    return (Date.now() - dashboardCache.fetchedAt.getTime()) < MEMORY_CACHE_TTL_MS;

  }



  function cacheHeaderMeta(refreshing) {

    const ageMin = getCacheAgeMinutes();

    const cacheLabel = ageMin != null
      ? `<span class="mm-cache-label">cached ${ageMin} min ago</span>`
      : '';

    const refreshLabel = refreshing
      ? `<span class="mm-refreshing-label">refreshing…</span>`
      : '';

    return `${cacheLabel}${refreshLabel}`;

  }



  function renderHeaderHtml(refreshing) {

    return `

      <div class="mm-header-row">

        <h1 class="mm-canonical-title">Canonical Market Memory</h1>

        <div class="mm-header-actions">

          ${cacheHeaderMeta(refreshing)}

          <button type="button" class="refresh-btn mm-refresh-btn" data-mm-refresh="1">↻ Refresh Memory</button>

        </div>

      </div>`;

  }



  function renderHistoricalLearningSection(historical) {

    if (!historical || historical.ok !== true) {

      return `

        <div class="glass-card mm-section">

          <h2>📜 Historical Learning</h2>

          <div class="mm-empty">Historical learning data unavailable.</div>

        </div>`;

    }

    const overall = historical.overall || {};

    const stats = historical.stats || {};

    const warnings = Array.isArray(overall.warnings) ? overall.warnings : [];

    const winRate = overall.win_rate;

    const winRateCls = winRate == null ? 'muted'

      : (winRate >= 0.6 ? 'green' : winRate >= 0.4 ? 'yellow' : 'red');

    const histTickerCount = historical.historical_ticker_count ?? 0;

    const universeCount = historical.universe_ticker_count ?? 0;

    const importReport = historical.import_report || {};

    const replayReport = historical.replay_report || {};

    const qualityAnomalies = historical.quality_anomalies ?? 0;

    const priceRows = historical.price_row_count ?? stats.historical_prices ?? 0;

    const replayCount = stats.historical_outcome_replay ?? replayReport.replayed ?? 0;



    let html = `

      <div class="glass-card mm-section">

        <h2>📜 Historical Learning</h2>

        <div class="mm-stat-grid mm-stat-grid-4">

          ${statCard('Historical tickers', histTickerCount, universeCount ? `universe ${universeCount}` : 'distinct OHLCV')}

          ${statCard('Price Rows', priceRows, 'OHLCV store')}

          ${statCard('Replays', replayCount, 'historical DB')}

          ${statCard('Win Rate', fmtWinRate(winRate), 'replay outcomes', winRateCls)}

        </div>

        <div class="mm-stat-grid mm-stat-grid-2">

          ${statCard('Import report', importReport.rows_written ?? importReport.tickers_done ?? '—', importReport.market || 'bulk import')}

          ${statCard('Replay report', replayReport.replayed ?? replayReport.checked ?? '—', replayReport.dry_run ? 'dry-run' : 'historical replay')}

          ${statCard('Quality anomalies', qualityAnomalies, 'price audit', qualityAnomalies > 0 ? 'yellow' : 'green')}

          ${statCard('Ambiguous', overall.ambiguous ?? replayReport.ambiguous ?? 0, 'same-candle hits', 'yellow')}

        </div>`;



    if (warnings.includes('ambiguous_daily_candle_present')) {

      html += `

        <div class="panel-status-banner waiting mm-price-scale-warn">

          ambiguous_daily_candle: some replays hit target and stop on the same daily candle and are excluded from win/loss counts.

        </div>`;

    }

    if (warnings.includes('low_sample_size') || replayCount < 5) {

      html += `

        <div class="panel-status-banner waiting mm-price-scale-warn">

          low sample: historical replay count is small; learning metrics may be unreliable until more bulk replay completes.

        </div>`;

    }



    const topTickers = historical.top_tickers || [];

    if (topTickers.length) {

      const rows = topTickers.slice(0, 5).map((item) => `

        <tr>

          <td>${escapeHtml(item.ticker || '—')}</td>

          <td>${fmtWinRate(item.win_rate)}</td>

          <td>${(item.wins || 0)}W / ${(item.losses || 0)}L</td>

          <td>${item.ambiguous || 0}</td>

        </tr>`).join('');

      html += `

        <div class="mm-learning-block">

          <div class="mm-learning-title">top_tickers</div>

          <table class="mm-table mm-table-compact">

            <thead><tr><th>Ticker</th><th>Win%</th><th>W/L</th><th>Ambiguous</th></tr></thead>

            <tbody>${rows}</tbody>

          </table>

        </div>`;

    }



    const samplePrices = historical.sample_prices || [];

    if (samplePrices.length) {

      const priceRows = samplePrices.slice(0, 8).map((row) => `

        <tr>

          <td>${escapeHtml(row.ticker || '—')}</td>

          <td>${escapeHtml(row.date || '—')}</td>

          <td>${escapeHtml(row.close != null ? row.close : '—')}</td>

          <td>${escapeHtml(row.source || '—')}</td>

        </tr>`).join('');

      html += `

        <div class="mm-learning-block">

          <div class="mm-learning-title">Sample price rows</div>

          <table class="mm-table mm-table-compact">

            <thead><tr><th>Ticker</th><th>Date</th><th>Close</th><th>Source</th></tr></thead>

            <tbody>${priceRows}</tbody>

          </table>

        </div>`;

    }



    const comparison = historical.comparison || {};

    const live = comparison.live_memory || {};

    const hist = comparison.historical_replay || {};

    const simulation = historical.simulation || {};

    const simStats = simulation.stats || {};

    const simRuns = Array.isArray(simulation.runs) ? simulation.runs : [];

    const simStrategies = Array.isArray(simulation.strategy_performance)
      ? simulation.strategy_performance
      : [];

    const simDisclaimer = simulation.disclaimer
      || 'Simulated predictions are backtest samples, not live predictions.';

    html += `

        <div class="mm-learning-block">

          <div class="mm-learning-title">Historical Simulation</div>

          <div class="panel-status-banner waiting mm-price-scale-warn">

            ${escapeHtml(simDisclaimer)}

          </div>

          <div class="mm-stat-grid mm-stat-grid-4">

            ${statCard('Sim runs', simStats.simulation_runs ?? simRuns.length ?? 0, 'backtest engine')}

            ${statCard('Sim predictions', simStats.simulated_predictions ?? 0, 'learning samples')}

            ${statCard('Sim win rate', fmtWinRate(simStats.sim_win_rate), 'resolved sims', simStats.sim_win_rate == null ? 'muted' : (simStats.sim_win_rate >= 0.6 ? 'green' : simStats.sim_win_rate >= 0.4 ? 'yellow' : 'red'))}

            ${statCard('Sim resolved', simStats.sim_resolved ?? 0, `${simStats.sim_wins ?? 0}W / ${simStats.sim_losses ?? 0}L`)}

          </div>`;

    if (simStrategies.length) {

      const stratRows = simStrategies.slice(0, 6).map((item) => `

        <tr>

          <td>${escapeHtml(item.strategy || '—')}</td>

          <td>${item.predictions ?? 0}</td>

          <td>${fmtWinRate(item.win_rate)}</td>

          <td>${item.expectancy_pct != null ? Number(item.expectancy_pct).toFixed(2) + '%' : '—'}</td>

          <td>${item.ambiguous ?? 0}</td>

        </tr>`).join('');

      html += `

          <table class="mm-table mm-table-compact">

            <thead><tr><th>Strategy</th><th>Predictions</th><th>Win%</th><th>Expectancy</th><th>Ambiguous</th></tr></thead>

            <tbody>${stratRows}</tbody>

          </table>`;

    } else if (simRuns.length) {

      const runRows = simRuns.slice(0, 5).map((run) => `

        <tr>

          <td>${escapeHtml(run.run_id || '—')}</td>

          <td>${escapeHtml(run.market || '—')}</td>

          <td>${run.generated_predictions ?? 0}</td>

          <td>${fmtWinRate(run.wins && run.losses ? run.wins / (run.wins + run.losses) : null)}</td>

        </tr>`).join('');

      html += `

          <table class="mm-table mm-table-compact">

            <thead><tr><th>Run</th><th>Market</th><th>Signals</th><th>Win%</th></tr></thead>

            <tbody>${runRows}</tbody>

          </table>`;

    }

    html += `

        </div>

        <div class="mm-debug-line">

          compare live=${fmtWinRate(live.win_rate)} historical=${fmtWinRate(hist.win_rate)}

          source=${escapeHtml(HISTORICAL_LEARNING_SOURCE)}

        </div>

      </div>`;

    return html;

  }



  function renderFinalConfidenceSection(finalConfidence) {

    /* Shadow confidence only — not trade execution. Calibration via CONFIDENCE_CALIBRATION_SOURCE */

    return `

      <div class="glass-card mm-section" aria-label="Final Confidence and Calibration">

        <div id="finalConfidenceHost"><div class="loading">⏳ Loading 🎯 Final Confidence &amp; Calibration…</div></div>

      </div>`;

  }



  function mountFinalConfidencePanel(finalConfidence) {

    if (!global.FinalConfidencePanel || !FinalConfidencePanel.loadInto) return;

    const host = document.getElementById('finalConfidenceHost');

    if (!host) return;

    FinalConfidencePanel.loadInto(host);

  }



  function mountDailyReportPackPanel() {

    if (!global.DailyReportPackPanel || !DailyReportPackPanel.mount) return;

    const host = document.getElementById('dailyReportPackHost');

    if (!host) return;

    DailyReportPackPanel.mount(host);

  }



  function renderDashboard(data, fetchedAt, historical, finalConfidence, refreshing) {

    const stats = data.stats || {};

    const learning = data.learning || {};

    const overall = learning.overall || {};

    const advisor = data.advisor || {};

    const priceCoverage = data.price_coverage || {};

    const outcomeAudit = data.outcome_audit || {};

    const warnings = Array.isArray(data.warnings) ? data.warnings : [];



    const winRate = overall.win_rate;

    const winRateCls = winRate == null ? 'muted'

      : (winRate >= 0.6 ? 'green' : winRate >= 0.4 ? 'yellow' : 'red');



    let html = `

      <div class="mm-dashboard">

        ${renderHeaderHtml(!!refreshing)}

        <div id="dailyReportPackHost"><div class="loading">⏳ Loading 🗂 Daily Report Pack…</div></div>

        <div class="panel-status-banner idle mm-shadow-label">Shadow Advisor only: true</div>`;



    if (warnings.includes('suspicious_price_scale_detected')) {

      html += `

        <div class="panel-status-banner waiting mm-price-scale-warn">

          Some rows were skipped due to suspicious price scale. Trusted outcomes are anomaly-free.

        </div>`;

    }



    const otherWarnings = warnings.filter((w) => w !== 'suspicious_price_scale_detected');

    if (otherWarnings.length) {

      html += `

        <div class="mm-warnings-row">

          ${otherWarnings.map((w) => `<span class="mm-warning-chip">${escapeHtml(w)}</span>`).join('')}

        </div>`;

    }



    html += `

      <div class="glass-card mm-section">

        <h2>📚 Overview</h2>

        <div class="mm-stat-grid">

          ${statCard('Predictions', stats.predictions ?? 0, 'canonical DB')}

          ${statCard('Outcomes', stats.outcomes ?? 0, 'resolved rows')}

          ${statCard('Win Rate', fmtWinRate(winRate), 'historical', winRateCls)}

          ${statCard('Wins', overall.wins ?? 0, 'resolved')}

          ${statCard('Losses', overall.losses ?? 0, 'resolved')}

          ${statCard('Unresolved', overall.unresolved_predictions ?? 0, 'pending outcomes', 'yellow')}

        </div>

      </div>



      <div class="glass-card mm-section">

        <h2>🛡 Shadow Advisor</h2>

        <div class="mm-stat-grid mm-stat-grid-4">

          ${statCard('Caution', advisor.caution ?? 0, `checked ${advisor.checked ?? 0}`)}

          ${statCard('Neutral', advisor.neutral ?? 0, advisor.shadow_mode ? 'shadow mode' : 'advisory')}

          ${statCard('Boost', advisor.boost ?? 0, 'historical edge')}

          ${statCard('Avoid', advisor.avoid_candidate ?? 0, 'weak track record', 'red')}

        </div>

      </div>



      <div class="glass-card mm-section">

        <h2>🔍 Coverage &amp; Audit</h2>

        <div class="mm-stat-grid mm-stat-grid-2">

          ${statCard('Price Symbols', priceCoverage.symbols ?? 0, 'enriched file')}

          ${statCard('Outcome Anomalies', outcomeAudit.anomalies ?? 0, `${outcomeAudit.outcomes_checked ?? 0} checked`, (outcomeAudit.anomalies || 0) > 0 ? 'red' : 'green')}

        </div>

      </div>



      <div class="glass-card mm-section">

        <h2>📈 Learning by dimension</h2>

        <div class="mm-learning-grid">

          ${learningTable('By confidence label', learning.by_confidence_label)}

          ${learningTable('By signal type', learning.by_signal_type)}

          ${learningTable('By horizon', learning.by_prediction_horizon)}

        </div>

      </div>`;



    const outcomeRows = (data.latest_outcomes || []).map((row) => `

      <tr>

        <td>${escapeHtml(row.ticker || '—')}</td>

        <td class="${outcomeClass(row.resolved_as)}">${escapeHtml(outcomeLabel(row.resolved_as))}</td>

        <td>${fmtMove(row.actual_move)}</td>

        <td>${escapeHtml(row.expiry_result || '—')}</td>

      </tr>`).join('');



    const predictionRows = (data.latest_predictions || []).map((row) => `

      <tr>

        <td>${escapeHtml(row.ticker || '—')}</td>

        <td>${escapeHtml(row.direction || '—')}</td>

        <td>${escapeHtml(row.confidence_label || row.confidence || '—')}</td>

        <td>${escapeHtml(row.source || '—')}</td>

      </tr>`).join('');



    html += renderDataTable('Latest outcomes', ['Ticker', 'Result', 'Move %', 'Expiry'], outcomeRows);

    html += renderDataTable('Latest predictions', ['Ticker', 'Direction', 'Confidence', 'Source'], predictionRows);

    html += renderFinalConfidenceSection(finalConfidence);

    html += renderHistoricalLearningSection(historical);

    html += debugFooterHtml(fetchedAt);

    html += '</div>';

    return html;

  }



  function renderErrorHtml(err, fetchedAt, options = {}) {

    const isRefreshing = Boolean(
      options?.refreshing
      || options?.state?.refreshing
      || options?.ctx?.refreshing
      || false
    );

    const msg = (err && err.message) ? err.message : String(err || 'unknown error');

    return `

      <div class="glass-card mm-dashboard">

        ${renderHeaderHtml(isRefreshing)}

        <div class="panel-error-card">

          <strong>Market Memory dashboard unavailable</strong>

          <p>${escapeHtml(msg)}</p>

        </div>

        ${debugFooterHtml(fetchedAt || new Date())}

      </div>`;

  }



  function renderLoadingHtml() {

    return `

      <div class="glass-card mm-dashboard">

        ${renderHeaderHtml(false)}

        <div class="loading">⏳ Loading Canonical Market Memory…</div>

      </div>`;

  }



  function paintDashboard(container, targetKey, payload, refreshing) {

    if (!container || !payload) return;

    const opts = targetOptions(targetKey);

    let html = '';

    if (opts.includeFreshness && global.SourceFreshnessCard && SourceFreshnessCard.renderCardHtml) {
      html += SourceFreshnessCard.renderCardHtml(payload.freshness || { ok: false, error: 'Freshness unavailable' });
    }

    html += renderDashboard(payload.data, payload.fetchedAt, payload.historical, payload.finalConfidence, refreshing);

    container.innerHTML = html;

    mountFinalConfidencePanel(payload.finalConfidence);

    mountDailyReportPackPanel();

    bindRefreshButtons(container, targetKey);

    if (opts.includeFreshness && global.SourceFreshnessCard && SourceFreshnessCard.bindActionsIn) {
      SourceFreshnessCard.bindActionsIn(container);
    }

  }



  function bindRefreshButtons(container, targetKey) {

    if (!container) return;

    container.querySelectorAll('[data-mm-refresh="1"]').forEach((btn) => {

      btn.addEventListener('click', (e) => {

        e.preventDefault();

        e.stopPropagation();

        refreshTarget(targetKey);

      });

    });

  }



  async function renderInto(container, targetKey, renderOpts) {

    if (!container) return;

    const options = renderOpts || {};

    const opts = targetOptions(targetKey);

    try {

      const freshnessPromise = (opts.includeFreshness && global.SourceFreshnessCard && SourceFreshnessCard.fetchFreshness)
        ? SourceFreshnessCard.fetchFreshness().catch(() => null)
        : Promise.resolve(null);

      const [{ data, fetchedAt }, freshness, historical, finalConfidence] = await Promise.all([
        fetchDashboard(),
        freshnessPromise,
        fetchHistoricalLearning().catch(() => null),
        fetchFinalConfidence().catch(() => null),
      ]);

      dashboardCache = { data, fetchedAt, freshness, historical, finalConfidence };

      paintDashboard(container, targetKey, dashboardCache, false);

    } catch (e) {

      if (dashboardCache && options.keepCacheOnError) {
        paintDashboard(container, targetKey, dashboardCache, false);
      } else {
        container.innerHTML = renderErrorHtml(e, new Date());
        bindRefreshButtons(container, targetKey);
      }

    }

  }



  function refreshTarget(targetKey) {

    const el = resolveTargetElement(targetKey);

    if (!el) return;

    loadInto(el, targetKey, true);

  }



  function resolveTargetElement(targetKey) {

    if (targetKey === 'main') {

      return document.getElementById('memoryMainContent')

        || document.querySelector('#memoryWorkspace #memoryMainContent');

    }

    if (targetKey === 'tab') return document.getElementById('tab-memory');

    return null;

  }



  function loadInto(container, targetKey, force) {

    if (!container) return;

    if (loadingByTarget[targetKey] && !force) return;

    const hasCache = !!dashboardCache;

    const cacheValid = isMemoryCacheValid();

    if (!force && hasCache && cacheValid) {

      paintDashboard(container, targetKey, dashboardCache, false);

      return;

    }

    if (!force && hasCache) {

      paintDashboard(container, targetKey, dashboardCache, true);

      loadingByTarget[targetKey] = true;

      renderInto(container, targetKey, { keepCacheOnError: true }).finally(() => {

        loadingByTarget[targetKey] = false;

      });

      return;

    }

    if (force && hasCache) {

      paintDashboard(container, targetKey, dashboardCache, true);

    } else {

      container.innerHTML = renderLoadingHtml();

      bindRefreshButtons(container, targetKey);

    }

    loadingByTarget[targetKey] = true;

    renderInto(container, targetKey, { keepCacheOnError: force && hasCache }).finally(() => {

      loadingByTarget[targetKey] = false;

    });

  }



  function loadTab() {

    renderMemTabShortcut();

  }



  function loadMain() {

    loadInto(document.getElementById('memoryMainContent'), 'main');

  }



  function openMainView() {

    setMemoryViewActive(true);

    loadMain();

  }



  function closeMainView() {

    if (global.WorkspaceManager && WorkspaceManager.closeMemoryView) {

      WorkspaceManager.closeMemoryView();

      return;

    }

    setMemoryViewActive(false);

    const panel = document.getElementById('memoryMainPanel');

    if (panel) panel.style.display = 'none';

  }



  function init(opts) {

    config.getApiBase = opts.getApiBase || config.getApiBase;

    config.getHeaders = opts.getHeaders || config.getHeaders;

    /* memory nav wired by WorkspaceManager.init */

  }



  global.MarketMemoryPanel = {

    init,

    loadTab,

    loadMain,

    openMainView,

    closeMainView,

    refreshTarget,

    renderMemTabShortcut,

    renderTab: loadTab,

    getDashboardCache: () => dashboardCache,

    isMemoryCacheValid,

    MEMORY_CACHE_TTL_MS,

  };

})(typeof window !== 'undefined' ? window : global);


