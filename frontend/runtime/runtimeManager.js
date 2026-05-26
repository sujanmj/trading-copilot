/**
 * RuntimeManager — single coordinated refresh loop + shared runtime state.
 * All intelligence tabs subscribe here instead of polling independently.
 */
(function (global) {
  'use strict';

  const DEFAULT_POLL_MS = 30000;
  const MIN_REFRESH_GAP_MS = 4000;

  let config = {
    getApiBase: () => '',
    getHeaders: () => ({}),
    cache: null,
    onConnectionChange: null,
  };

  let state = null;
  let pollTimer = null;
  let started = false;
  let inFlight = false;
  let fetchSeq = 0;
  let lastRefreshAt = 0;
  const subscribers = new Set();
  const panelHandlers = new Map();

  function notify() {
    subscribers.forEach((fn) => {
      try {
        fn(state);
      } catch (e) {
        console.error('[RuntimeManager] subscriber error', e);
      }
    });
    panelHandlers.forEach((fn) => {
      try {
        fn(state);
      } catch (e) {
        console.error('[RuntimeManager] panel handler error', e);
      }
    });
  }

  function applyCacheFromSnapshot(snapshot) {
    const cache = config.cache;
    if (!cache || !snapshot) return;
    const data = snapshot.data || {};
    cache.intelligence = data.intelligence;
    cache.indiaMarket = data.india;
    cache.globalMarket = data.markets;
    cache.news = data.news;
    cache.youtube = data.youtube;
    cache.govt = data.govt;
    cache.inshorts = data.inshorts;
    cache.reddit = data.reddit;
    cache.scanner = data.scanner;
    cache.stats = data.stats;
    cache.history = data.history;
    cache.runtime = snapshot;
    cache.lastFetch = Date.now();
    cache.connected = snapshot.status !== 'degraded';
  }

  function applySnapshot(snapshot, seq) {
    if (seq !== fetchSeq) return false;
    state = snapshot;
    applyCacheFromSnapshot(snapshot);
    if (typeof config.onConnectionChange === 'function') {
      config.onConnectionChange(!!cacheConnected());
    }
    notify();
    return true;
  }

  function cacheConnected() {
    return !!(config.cache && config.cache.connected);
  }

  async function fetchSnapshot() {
    const base = config.getApiBase().replace(/\/$/, '');
    const res = await fetch(base + '/api/runtime_snapshot', {
      method: 'GET',
      headers: config.getHeaders(),
    });
    if (!res.ok) throw new Error(`runtime_snapshot → ${res.status}`);
    return res.json();
  }

  async function refresh(opts) {
    opts = opts || {};
    const now = Date.now();
    if (inFlight && !opts.force) return state;
    if (!opts.force && now - lastRefreshAt < MIN_REFRESH_GAP_MS) return state;

    const seq = ++fetchSeq;
    inFlight = true;
    try {
      const snapshot = await fetchSnapshot();
      lastRefreshAt = Date.now();
      applySnapshot(snapshot, seq);
      return state;
    } catch (e) {
      console.error('[RuntimeManager] refresh failed:', e.message);
      if (config.cache) config.cache.connected = false;
      if (typeof config.onConnectionChange === 'function') {
        config.onConnectionChange(false);
      }
      return state;
    } finally {
      inFlight = false;
    }
  }

  function start(pollMs) {
    if (started) return;
    started = true;
    refresh({ force: true });
    pollTimer = setInterval(() => refresh(), pollMs || DEFAULT_POLL_MS);
  }

  function stop() {
    started = false;
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  function subscribe(fn) {
    if (typeof fn !== 'function') return () => {};
    subscribers.add(fn);
    if (state) {
      try {
        fn(state);
      } catch (e) {
        console.error('[RuntimeManager] subscriber error', e);
      }
    }
    return () => subscribers.delete(fn);
  }

  function registerPanel(panelId, fn) {
    if (!panelId || typeof fn !== 'function') return () => {};
    panelHandlers.set(panelId, fn);
    if (state) {
      try {
        fn(state);
      } catch (e) {
        console.error('[RuntimeManager] panel handler error', e);
      }
    }
    return () => panelHandlers.delete(panelId);
  }

  function getState() {
    return state;
  }

  function getCache() {
    return config.cache;
  }

  function getPanelState(panelId) {
    const panels = (state && state.panels) || {};
    return panels[panelId] || { status: 'waiting', message: 'Waiting for runtime snapshot…', stale: false };
  }

  function formatTimestamp() {
    const iso = state && state.generated_at;
    if (!iso) return '—';
    try {
      return new Date(iso).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });
    } catch (e) {
      return '—';
    }
  }

  function isStale() {
    const runtimePanel = getPanelState('runtime');
    return !!(runtimePanel && runtimePanel.stale);
  }

  function timestampHtml(extra) {
    const ts = formatTimestamp();
    const staleTag = isStale() ? ' · <span class="runtime-stale">snapshot stale</span>' : '';
    const suffix = extra ? ` · ${extra}` : '';
    return `<div class="timestamp runtime-ts">Updated: ${ts}${suffix}${staleTag}</div>`;
  }

  function lifecycleMessage(panelId, fallback) {
    const panel = getPanelState(panelId);
    if (panel.message) return panel.message;
    return fallback || '';
  }

  function init(opts) {
    config.getApiBase = opts.getApiBase || config.getApiBase;
    config.getHeaders = opts.getHeaders || config.getHeaders;
    config.cache = opts.cache || config.cache;
    config.onConnectionChange = opts.onConnectionChange || config.onConnectionChange;
  }

  global.RuntimeManager = {
    init,
    start,
    stop,
    refresh,
    subscribe,
    registerPanel,
    getState,
    getCache,
    getPanelState,
    formatTimestamp,
    isStale,
    timestampHtml,
    lifecycleMessage,
  };
})(window);
