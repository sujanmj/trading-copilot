/**
 * Market Router status card — session-aware India/USA routing.
 * Fetches GET /api/debug/market-router (read-only).
 */
(function (global) {
  'use strict';

  const ROUTER_SOURCE = '/api/debug/market-router';
  const FETCH_MS = 15000;
  const NON_JSON_ERROR = 'API JSON unavailable — endpoint returned HTML. Check API base/path.';

  let config = {
    getApiBase: () => '',
    getHeaders: () => ({}),
  };

  let lastReport = null;

  function escapeHtml(text) {
    if (text == null) return '';
    return String(text)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function fmtOpen(block) {
    if (!block || block.ok !== true) return '—';
    const local = block.next_open_local || block.next_open_utc;
    if (!local) return '—';
    const text = String(local);
    if (text.length >= 16) return text.slice(0, 16).replace('T', ' ');
    return text;
  }

  function modeClass(mode) {
    const token = String(mode || '').toUpperCase();
    if (token.includes('INDIA')) return 'mr-india';
    if (token.includes('USA')) return 'mr-usa';
    if (token.includes('RESEARCH')) return 'mr-research';
    return 'mr-muted';
  }

  function sessionClass(session) {
    const token = String(session || '').toLowerCase();
    if (token === 'regular') return 'mr-open';
    if (token === 'premarket' || token === 'postmarket') return 'mr-extended';
    return 'mr-closed';
  }

  function metricRow(label, value, sub, valueClass) {
    return `
      <div class="mr-metric">
        <div class="mr-metric-label">${escapeHtml(label)}</div>
        <div class="mr-metric-value ${valueClass || ''}">${escapeHtml(value || '—')}</div>
        ${sub ? `<div class="mr-metric-sub">${escapeHtml(sub)}</div>` : ''}
      </div>`;
  }

  function fmtHoliday(block) {
    if (!block) return '—';
    const name = block.name || 'Holiday';
    const day = block.date || '';
    const days = block.days_until;
    const suffix = days != null && days >= 0 ? ` (+${days}d)` : '';
    return day ? `${day} — ${name}${suffix}` : name;
  }

  function renderCompactStatusHtml(report) {
    if (!report || report.ok !== true) {
      const err = (report && report.error) || 'Router unavailable';
      return `<div class="mr-compact-status mr-compact-error" title="${escapeHtml(err)}"><span>🌍 ${escapeHtml(err)}</span></div>`;
    }
    const mode = report.active_mode_label || report.active_mode || '—';
    const indiaSession = report.india_session_label || report.india_session || '—';
    const nextIndia = fmtOpen(report.next_india_open);
    const parts = [
      `<span class="mr-compact-badge ${modeClass(report.active_mode)}">${escapeHtml(mode)}</span>`,
      `<span class="mr-compact-india">${escapeHtml(indiaSession)}</span>`,
    ];
    if (nextIndia && nextIndia !== '—') {
      parts.push(`<span class="mr-compact-next">Next open ${escapeHtml(nextIndia)}</span>`);
    }
    return `<div class="mr-compact-status">${parts.join('<span class="mr-compact-sep">·</span>')}</div>`;
  }

  function renderCardHtml(report) {
    if (!report || report.ok !== true) {
      const err = (report && report.error) || 'Market router unavailable';
      return `
        <div class="glass-card market-router-card mr-error">
          <h2>🌍 Market Router</h2>
          <div class="mr-warning-line">${escapeHtml(err)}</div>
        </div>`;
    }

    const india = report.india || {};
    const usa = report.usa || {};
    const warnings = Array.isArray(report.warnings) ? report.warnings : [];
    const calendar = report.holiday_calendar || {};
    const indiaCal = calendar.india || {};
    const usaCal = calendar.usa || {};
    const calStatus = calendar.holiday_calendar_status || (calendar.calendar_ok ? 'OK' : 'WARN');
    const calClass = calStatus === 'OK' ? 'mr-open' : 'mr-extended';

    let html = `
      <div class="glass-card market-router-card">
        <div class="mr-head">
          <h2>🌍 Market Router</h2>
          <span class="mr-mode-badge ${modeClass(report.active_mode)}">${escapeHtml(report.active_mode_label || report.active_mode || '—')}</span>
        </div>
        <div class="mr-grid">
          ${metricRow('Active Mode', report.active_mode_label || report.active_mode, report.routing_reason, modeClass(report.active_mode))}
          ${metricRow('India session', report.india_session_label || report.india_session, india.local_time ? india.local_time.slice(11, 19) + ' IST' : '', sessionClass(report.india_session))}
          ${metricRow('USA session', report.usa_session_label || report.usa_session, usa.local_time ? usa.local_time.slice(11, 19) + ' ET' : '', sessionClass(report.usa_session))}
          ${metricRow('Recommended focus', report.recommended_focus, null, 'mr-focus')}
          ${metricRow('Next India open', fmtOpen(report.next_india_open), report.next_india_open && report.next_india_open.next_open_date ? report.next_india_open.next_open_date : '', 'mr-muted')}
          ${metricRow('Next USA open', fmtOpen(report.next_usa_open), report.next_usa_open && report.next_usa_open.next_open_date ? report.next_usa_open.next_open_date : '', 'mr-muted')}
          ${metricRow('Holiday calendar', calStatus, calendar.calendar_ok === false ? (calendar.warnings || []).join(', ') : 'India + USA calendars loaded', calClass)}
          ${metricRow('Next India holiday', fmtHoliday(indiaCal.next_holiday), indiaCal.year ? `Year ${indiaCal.year}` : '', 'mr-muted')}
          ${metricRow('Next USA holiday', fmtHoliday(usaCal.next_holiday), usaCal.early_closes != null ? `${usaCal.early_closes} early closes` : '', 'mr-muted')}
        </div>`;

    if (usa.early_close_today || warnings.includes('usa_early_close_today')) {
      const closeTime = usa.early_close_time || (usaCal.next_early_close && usaCal.next_early_close.close_time) || '13:00';
      html += `<div class="mr-warning-line">⚠ USA early close today — regular session ends ${escapeHtml(closeTime)} ET</div>`;
    }

    if (warnings.length) {
      html += `<div class="mr-warnings">${warnings.map((w) => `<div class="mr-warning-line">⚠ ${escapeHtml(String(w).replace(/_/g, ' '))}</div>`).join('')}</div>`;
    }

    html += '</div>';
    return html;
  }

  function routerUrl() {
    const base = config.getApiBase().replace(/\/$/, '');
    return `${base}${ROUTER_SOURCE}?_ts=${Date.now()}`;
  }

  async function parseJsonResponse(res) {
    const ct = (res.headers && res.headers.get('content-type')) || '';
    const text = await res.text();
    if (!String(ct).toLowerCase().includes('application/json')) {
      const preview = text.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 120);
      throw new Error(NON_JSON_ERROR + (preview ? ` Preview: ${preview}` : ''));
    }
    return text ? JSON.parse(text) : {};
  }

  async function fetchRouter() {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), FETCH_MS);
    try {
      const res = await fetch(routerUrl(), {
        method: 'GET',
        headers: {
          ...config.getHeaders(),
          'Cache-Control': 'no-cache, no-store, must-revalidate',
          Pragma: 'no-cache',
        },
        cache: 'no-store',
        signal: controller.signal,
      });
      if (!res.ok) throw new Error(`market-router → ${res.status}`);
      const data = await parseJsonResponse(res);
      lastReport = data;
      return data;
    } catch (err) {
      if (err && err.name === 'AbortError') {
        throw new Error('Router request timed out or was cancelled.');
      }
      throw err;
    } finally {
      clearTimeout(timer);
    }
  }

  async function mountCompact(containerOrSelector, opts) {
    const options = opts || {};
    let container = containerOrSelector;
    if (typeof containerOrSelector === 'string') {
      container = document.querySelector(containerOrSelector);
    }
    if (!container) return null;

    if (!options.force && container.dataset.mrCompactLoaded === '1' && lastReport) {
      container.innerHTML = renderCompactStatusHtml(lastReport);
      return lastReport;
    }

    container.innerHTML = '<div class="mr-compact-status mr-compact-loading">🌍 Loading router…</div>';
    try {
      const report = lastReport && !options.force ? lastReport : await fetchRouter();
      container.innerHTML = renderCompactStatusHtml(report);
      container.dataset.mrCompactLoaded = '1';
      return report;
    } catch (err) {
      container.innerHTML = renderCompactStatusHtml({ ok: false, error: (err && err.message) || String(err) });
      return null;
    }
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

    if (!options.force && container.dataset.mrLoaded === '1' && lastReport) {
      container.innerHTML = renderCardHtml(lastReport);
      return lastReport;
    }

    container.innerHTML = '<div class="glass-card market-router-card"><div class="loading">⏳ Loading market router…</div></div>';
    try {
      const report = await fetchRouter();
      container.innerHTML = renderCardHtml(report);
      container.dataset.mrLoaded = '1';
      return report;
    } catch (err) {
      container.innerHTML = renderCardHtml({ ok: false, error: (err && err.message) || String(err) });
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
    delete container.dataset.mrLoaded;
  }

  function init(opts) {
    config.getApiBase = (opts && opts.getApiBase) || config.getApiBase;
    config.getHeaders = (opts && opts.getHeaders) || config.getHeaders;
  }

  global.MarketRouterCard = {
    init,
    mount,
    mountCompact,
    unmount,
    fetchRouter,
    renderCardHtml,
    renderCompactStatusHtml,
    getLastReport: () => lastReport,
  };
})(window);
