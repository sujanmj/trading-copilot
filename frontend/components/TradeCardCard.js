/**
 * Paper-only intraday trade card — GET /api/trade-card (read-only, no broker actions).
 */
(function (global) {
  'use strict';

  const TRADE_CARD_SOURCE = '/api/trade-card';
  const FETCH_MS = 15000;
  const NON_JSON_ERROR = 'API JSON unavailable — endpoint returned HTML. Check API base/path.';

  let config = {
    getApiBase: () => '',
    getHeaders: () => ({}),
  };

  let lastCard = null;

  function escapeHtml(text) {
    if (text == null) return '';
    return String(text)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function statusClass(status) {
    const token = String(status || '').toUpperCase();
    if (token === 'VALID_ENTRY') return 'tc-valid';
    if (token === 'ENTRY_MISSED' || token === 'AVOID') return 'tc-missed';
    if (token.startsWith('WAIT')) return 'tc-wait';
    return 'tc-neutral';
  }

  function renderCard(card) {
    if (!card || card.ok === false) {
      return `<div class="tc-card tc-empty">${escapeHtml(card && card.reason ? card.reason : 'No trade card yet — paper only.')}</div>`;
    }
    const status = card.status || 'NO_TRADE';
    return `
      <div class="tc-card">
        <div class="tc-head">
          <span class="tc-ticker">${escapeHtml(card.ticker || '—')}</span>
          <span class="tc-status ${statusClass(status)}">${escapeHtml(status.replace(/_/g, ' '))}</span>
        </div>
        <div class="tc-grid">
          <div><span class="tc-label">Entry</span><span>${escapeHtml(card.entry_zone || '—')}</span></div>
          <div><span class="tc-label">SL</span><span>${escapeHtml(card.stop_loss != null ? card.stop_loss : '—')}</span></div>
          <div><span class="tc-label">T1</span><span>${escapeHtml(card.target_1 != null ? card.target_1 : '—')}</span></div>
          <div><span class="tc-label">R:R</span><span>${escapeHtml(card.risk_reward != null ? card.risk_reward : '—')}</span></div>
        </div>
        <div class="tc-line"><span class="tc-label">Capital</span> ${escapeHtml(card.capital_plan || 'Paper only.')}</div>
        <div class="tc-line"><span class="tc-label">Reason</span> ${escapeHtml(card.reason || '—')}</div>
        <div class="tc-line"><span class="tc-label">Invalid if</span> ${escapeHtml(card.invalid_if || '—')}</div>
        <div class="tc-foot">Paper only · Updated ${escapeHtml((card.generated_at || '—').slice(0, 19))}</div>
      </div>`;
  }

  async function fetchCard(rebuild) {
    const base = config.getApiBase() || '';
    const url = base + TRADE_CARD_SOURCE + (rebuild ? '?rebuild=true' : '');
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), FETCH_MS);
    try {
      const res = await fetch(url, { headers: config.getHeaders(), signal: controller.signal });
      if (!res.ok) throw new Error(`trade-card → ${res.status}`);
      const ct = res.headers.get('content-type') || '';
      if (!ct.includes('application/json')) throw new Error(NON_JSON_ERROR);
      lastCard = await res.json();
      return lastCard;
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
    host.innerHTML = '<div class="tc-loading">Loading trade card…</div>';
    try {
      const card = await fetchCard(false);
      host.innerHTML = renderCard(card);
    } catch (err) {
      host.innerHTML = `<div class="tc-card tc-empty">${escapeHtml(String(err.message || err))}</div>`;
    }
  }

  function injectStyles() {
    if (document.getElementById('trade-card-styles')) return;
    const style = document.createElement('style');
    style.id = 'trade-card-styles';
    style.textContent = `
      .tc-card { border: 1px solid #2a3344; border-radius: 8px; padding: 10px 12px; background: #121820; font-size: 12px; line-height: 1.45; }
      .tc-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
      .tc-ticker { font-weight: 700; font-size: 14px; color: #e8eef8; }
      .tc-status { font-size: 11px; padding: 2px 8px; border-radius: 999px; background: #1e2838; color: #9fb0cc; }
      .tc-status.tc-valid { color: #7dcea0; }
      .tc-status.tc-missed { color: #e88; }
      .tc-status.tc-wait { color: #e8c547; }
      .tc-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 6px 10px; margin-bottom: 8px; }
      .tc-label { display: block; color: #7a879c; font-size: 10px; text-transform: uppercase; letter-spacing: 0.04em; }
      .tc-line { margin-bottom: 4px; color: #c8d2e0; }
      .tc-foot { margin-top: 8px; color: #6a7588; font-size: 10px; }
      .tc-empty, .tc-loading { color: #8a96a8; padding: 8px 0; }
    `;
    document.head.appendChild(style);
  }

  function init(opts) {
    injectStyles();
    if (opts) Object.assign(config, opts);
    const reviewHost = document.getElementById('reviewTradeCard');
    const opsHost = document.getElementById('aiOpsTradeCard');
    if (reviewHost) mount(reviewHost, opts);
    if (opsHost) mount(opsHost, opts);
  }

  global.TradeCardCard = { init, mount, fetchCard, renderCard, getLastCard: () => lastCard };
})(typeof window !== 'undefined' ? window : globalThis);
