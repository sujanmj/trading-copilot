/**
 * Internal Source Feed Viewer — cached articles from local API (Stage 44G).
 */
(function (global) {
  'use strict';

  const FEED_SOURCE = '/api/debug/source-feed';
  const FETCH_MS = 12000;

  let config = {
    getApiBase: () => '',
    getHeaders: () => ({}),
  };

  let state = {
    sourceKey: '',
    externalUrl: '',
    label: '',
    filter: '',
    lastPayload: null,
  };

  function $(id) {
    return document.getElementById(id);
  }

  function escapeHtml(text) {
    if (text == null) return '';
    return String(text)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function formatClassLabel(raw) {
    const map = {
      broker_candidates: 'Broker candidate',
      broker_prediction_candidate: 'Broker candidate',
      stock_news: 'Stock news',
      stock_news_evidence: 'Stock news',
      market_context: 'Market context',
      macro_context: 'Macro context',
      headline: 'Headline',
      social: 'Social',
      reject: 'Filtered',
    };
    const key = String(raw || '').trim();
    return map[key] || key || '—';
  }

  function directionBadgeClass(direction) {
    const token = String(direction || '').trim().toUpperCase();
    if (!token || token === '—' || token === 'NEUTRAL') return 'sfv-dir-neutral';
    if (token.includes('BULL') || token.includes('LONG') || token.includes('BUY') || token === 'UP') return 'sfv-dir-bull';
    if (token.includes('BEAR') || token.includes('SHORT') || token.includes('SELL') || token === 'DOWN') return 'sfv-dir-bear';
    if (token.includes('WATCH')) return 'sfv-dir-watch';
    return 'sfv-dir-neutral';
  }

  async function fetchFeed(sourceKey) {
    const base = (config.getApiBase() || '').replace(/\/$/, '');
    const url = `${base}${FEED_SOURCE}?source=${encodeURIComponent(sourceKey)}&limit=100&_ts=${Date.now()}`;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), FETCH_MS);
    try {
      const res = await fetch(url, {
        headers: config.getHeaders(),
        cache: 'no-store',
        signal: controller.signal,
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    } finally {
      clearTimeout(timer);
    }
  }

  function filteredItems(items) {
    const q = (state.filter || '').trim().toLowerCase();
    if (!q) return items || [];
    return (items || []).filter((row) => {
      const hay = [
        row.title,
        row.ticker,
        row.classification,
        row.direction,
        row.source,
      ].join(' ').toLowerCase();
      return hay.includes(q);
    });
  }

  function renderRows(items) {
    if (!items.length) {
      return `<div class="sfv-empty">No cached items for this source yet. Use Refresh Source or Open External.</div>`;
    }
    const body = items.map((row) => {
      const ticker = row.ticker || '—';
      const cls = formatClassLabel(row.classification);
      const dir = row.direction || 'NEUTRAL';
      const title = row.title || '—';
      const src = row.source || '—';
      const ext = row.url ? `<button type="button" class="sfv-link-btn sfv-row-external" data-url="${escapeHtml(row.url)}">Open External</button>` : '<span class="sfv-muted">—</span>';
      return `<tr>
        <td class="sfv-col-ticker">${escapeHtml(ticker)}</td>
        <td class="sfv-col-type">${escapeHtml(cls)}</td>
        <td class="sfv-col-direction"><span class="sfv-direction-badge ${directionBadgeClass(dir)}">${escapeHtml(dir)}</span></td>
        <td class="sfv-col-title" title="${escapeHtml(title)}">${escapeHtml(title)}</td>
        <td class="sfv-col-source" title="${escapeHtml(src)}">${escapeHtml(src)}</td>
        <td class="sfv-col-external">${ext}</td>
      </tr>`;
    }).join('');
    return `<div class="sfv-table-wrap"><table class="sfv-table"><thead><tr>
      <th>Ticker</th><th>Type</th><th>Direction</th><th>Title</th><th>Source</th><th>Open External</th>
    </tr></thead><tbody>${body}</tbody></table></div>`;
  }

  function renderMeta(payload) {
    const p = payload || {};
    const counts = p.counts || {};
    const parts = [
      `Total ${counts.total != null ? counts.total : 0}`,
      `Stock ${counts.stock_news != null ? counts.stock_news : 0}`,
      `Market ${counts.market_context != null ? counts.market_context : 0}`,
      `Macro ${counts.macro_context != null ? counts.macro_context : 0}`,
      `Broker ${counts.broker_candidates != null ? counts.broker_candidates : 0}`,
    ];
    return parts.join(' · ');
  }

  function bindPanelEvents(root) {
    if (!root) return;
    const filterInput = root.querySelector('#sfvFilterInput');
    if (filterInput) {
      filterInput.addEventListener('input', () => {
        state.filter = filterInput.value;
        const host = root.querySelector('#sfvTableHost');
        if (host && state.lastPayload) {
          host.innerHTML = renderRows(filteredItems(state.lastPayload.items));
        }
      });
    }
    root.querySelectorAll('.sfv-row-external').forEach((btn) => {
      btn.addEventListener('click', () => {
        const url = btn.getAttribute('data-url');
        if (url) window.open(url, '_blank', 'noopener,noreferrer');
      });
    });
    const refreshBtn = root.querySelector('#sfvRefreshBtn');
    if (refreshBtn) {
      refreshBtn.addEventListener('click', () => {
        load(state.sourceKey, state.externalUrl, state.label).catch(() => null);
      });
    }
    const backBtn = root.querySelector('#sfvBackBtn');
    if (backBtn) {
      backBtn.addEventListener('click', () => {
        hide();
        if (global.WorkspaceManager) {
          if (WorkspaceManager.setActiveWorkspace) {
            WorkspaceManager.setActiveWorkspace('placeholder', { skipNav: true });
          }
        }
      });
    }
    const externalBtn = root.querySelector('#sfvOpenExternalBtn');
    if (externalBtn) {
      externalBtn.addEventListener('click', () => {
        if (state.externalUrl) {
          window.open(state.externalUrl, '_blank', 'noopener,noreferrer');
        }
      });
    }
  }

  function ensureRoot() {
    let root = $('sourceFeedViewer');
    if (root) return root;
    const panel = $('brokerPanel');
    if (!panel) return null;
    root = document.createElement('div');
    root.id = 'sourceFeedViewer';
    root.className = 'source-feed-viewer';
    root.style.display = 'none';
    panel.appendChild(root);
    return root;
  }

  function renderShell(loading) {
    const p = state.lastPayload || {};
    const label = p.source_label || state.label || state.sourceKey || 'Source';
    const type = p.source_type || 'news';
    const updated = p.last_updated || '—';
    return `
      <div class="sfv-card">
        <div class="sfv-header">
          <div>
            <h2 class="sfv-title">${escapeHtml(label)}</h2>
            <div class="sfv-sub">Type: ${escapeHtml(type)} · Last updated: ${escapeHtml(updated)}</div>
            <div class="sfv-counts">${escapeHtml(renderMeta(p))}</div>
          </div>
          <div class="sfv-actions">
            <button type="button" class="sfv-action-btn" id="sfvOpenExternalBtn">Open External</button>
            <button type="button" class="sfv-action-btn" id="sfvRefreshBtn">Refresh Source</button>
            <button type="button" class="sfv-action-btn sfv-back" id="sfvBackBtn">Back to Dashboard</button>
          </div>
        </div>
        <div class="sfv-toolbar">
          <input type="search" id="sfvFilterInput" class="sfv-filter" placeholder="Search ticker, title, type…" value="${escapeHtml(state.filter)}" />
        </div>
        <div id="sfvTableHost" class="sfv-body">${loading ? '<div class="sfv-loading">⏳ Loading cached feed…</div>' : renderRows(filteredItems(p.items || []))}</div>
      </div>`;
  }

  function hideEmbed() {
    if (global.WorkspaceManager && WorkspaceManager.getWebview) {
      const wv = WorkspaceManager.getWebview();
      if (wv && wv.style) wv.style.display = 'none';
    }
    const panel = $('brokerPanel');
    if (panel) {
      panel.querySelectorAll('webview, iframe.browser-embed').forEach((el) => {
        el.style.display = 'none';
      });
    }
    const placeholder = $('placeholder');
    if (placeholder) placeholder.style.display = 'none';
  }

  function hide() {
    const root = $('sourceFeedViewer');
    if (root) {
      root.style.display = 'none';
      root.innerHTML = '';
    }
    state.sourceKey = '';
    state.externalUrl = '';
    state.label = '';
    state.filter = '';
    state.lastPayload = null;
  }

  async function load(sourceKey, externalUrl, label) {
    const root = ensureRoot();
    if (!root) return;
    state.sourceKey = sourceKey || '';
    state.externalUrl = externalUrl || '';
    state.label = label || sourceKey || '';
    hideEmbed();
    root.style.display = 'flex';
    root.innerHTML = renderShell(true);
    bindPanelEvents(root);

    try {
      const payload = await fetchFeed(sourceKey);
      state.lastPayload = payload && payload.ok ? payload : { items: [], source_label: label };
      root.innerHTML = renderShell(false);
      bindPanelEvents(root);
    } catch (e) {
      state.lastPayload = { items: [], source_label: label, warnings: ['fetch_failed'] };
      root.innerHTML = renderShell(false);
      bindPanelEvents(root);
      const host = root.querySelector('#sfvTableHost');
      if (host) {
        host.innerHTML = '<div class="sfv-empty">Could not load cached feed. Use Refresh Source or Open External.</div>';
      }
    }
  }

  function show(sourceKey, externalUrl, label) {
    return load(sourceKey, externalUrl, label);
  }

  function init(opts) {
    config.getApiBase = (opts && opts.getApiBase) || config.getApiBase;
    config.getHeaders = (opts && opts.getHeaders) || config.getHeaders;
  }

  global.SourceFeedViewer = {
    init,
    show,
    load,
    hide,
  };
})(typeof window !== 'undefined' ? window : global);
