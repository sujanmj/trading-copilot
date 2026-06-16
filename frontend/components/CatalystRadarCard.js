/**
 * Stock Catalyst Radar — GET /api/catalyst-radar (read-only, paper watch).
 */
(function (global) {
  'use strict';

  const SOURCE = '/api/catalyst-radar';
  const FETCH_MS = 15000;
  const NON_JSON_ERROR = 'API JSON unavailable — endpoint returned HTML. Check API base/path.';

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

  function priorityClass(priority) {
    const token = String(priority || '').toUpperCase();
    if (token === 'HIGH') return 'cr-high';
    if (token === 'MEDIUM') return 'cr-medium';
    if (token === 'LOW') return 'cr-low';
    return 'cr-avoid';
  }

  function sideClass(side) {
    const token = String(side || '').toUpperCase();
    if (token === 'BULLISH') return 'cr-bull';
    if (token === 'BEARISH' || token === 'RISK') return 'cr-bear';
    return 'cr-neutral';
  }

  function renderTable(radar) {
    const items = (radar && radar.priority_list) || (radar && radar.items) || [];
    if (!items.length) {
      return '<div class="cr-empty">No fresh catalysts ranked yet — paper watch only.</div>';
    }
    const rows = items.slice(0, 12).map((row) => {
      const catalyst = String(row.catalyst_type || 'GENERAL_NEWS').replace(/_/g, ' ');
      return `
        <tr>
          <td class="cr-ticker">${escapeHtml(row.ticker || '—')}</td>
          <td>${escapeHtml(catalyst)}</td>
          <td class="${sideClass(row.side)}">${escapeHtml(row.side || '—')}</td>
          <td>${escapeHtml(row.freshness_label || '—')}</td>
          <td>${row.change_pct != null ? escapeHtml((row.change_pct >= 0 ? '+' : '') + row.change_pct + '%') : '—'}</td>
          <td>${row.volume_ratio != null ? escapeHtml(row.volume_ratio + 'x') : '—'}</td>
          <td class="${priorityClass(row.priority)}">${escapeHtml(row.priority || '—')}</td>
          <td>${escapeHtml(row.trade_status || '—')}</td>
          <td class="cr-reason">${escapeHtml(row.reason || '—')}</td>
        </tr>`;
    }).join('');
    return `
      <div class="cr-wrap">
        <table class="cr-table">
          <thead>
            <tr>
              <th>Ticker</th><th>Catalyst</th><th>Side</th><th>Fresh</th>
              <th>Price</th><th>Vol</th><th>Priority</th><th>Status</th><th>Reason</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
        <div class="cr-foot">Paper only · Updated ${escapeHtml((radar.generated_at || '—').slice(0, 19))}</div>
      </div>`;
  }

  async function fetchRadar(rebuild) {
    const base = config.getApiBase() || '';
    const url = base + SOURCE + (rebuild ? '?rebuild=true' : '');
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), FETCH_MS);
    try {
      const res = await fetch(url, { headers: config.getHeaders(), signal: controller.signal });
      if (!res.ok) throw new Error(`catalyst-radar → ${res.status}`);
      const ct = res.headers.get('content-type') || '';
      if (!ct.includes('application/json')) throw new Error(NON_JSON_ERROR);
      return await res.json();
    } finally {
      clearTimeout(timer);
    }
  }

  async function mount(containerOrSelector, opts) {
    const host = typeof containerOrSelector === 'string'
      ? document.querySelector(containerOrSelector)
      : containerOrSelector;
    if (!host) return;
    if (opts) Object.assign(config, opts);
    host.innerHTML = '<div class="cr-loading">Loading catalyst radar…</div>';
    try {
      const radar = await fetchRadar(false);
      host.innerHTML = renderTable(radar);
    } catch (err) {
      host.innerHTML = `<div class="cr-empty">${escapeHtml(String(err.message || err))}</div>`;
    }
  }

  function injectStyles() {
    if (document.getElementById('catalyst-radar-styles')) return;
    const style = document.createElement('style');
    style.id = 'catalyst-radar-styles';
    style.textContent = `
      .cr-wrap { overflow-x: auto; }
      .cr-table { width: 100%; border-collapse: collapse; font-size: 11px; }
      .cr-table th, .cr-table td { border-bottom: 1px solid #2a3344; padding: 5px 6px; text-align: left; vertical-align: top; }
      .cr-table th { color: #7a879c; font-size: 10px; text-transform: uppercase; letter-spacing: 0.04em; }
      .cr-ticker { font-weight: 700; color: #e8eef8; white-space: nowrap; }
      .cr-bull { color: #7dcea0; }
      .cr-bear { color: #e88; }
      .cr-neutral { color: #9fb0cc; }
      .cr-high { color: #7dcea0; font-weight: 600; }
      .cr-medium { color: #e8c547; }
      .cr-low { color: #9fb0cc; }
      .cr-avoid { color: #e88; }
      .cr-reason { max-width: 180px; color: #8a96a8; }
      .cr-foot, .cr-empty, .cr-loading { color: #6a7588; font-size: 10px; margin-top: 6px; }
    `;
    document.head.appendChild(style);
  }

  function init(opts) {
    injectStyles();
    if (opts) Object.assign(config, opts);
    const host = document.getElementById('reviewCatalystRadar');
    if (host) mount(host, opts);
  }

  global.CatalystRadarCard = { init, mount, fetchRadar, renderTable };
})(typeof window !== 'undefined' ? window : globalThis);
