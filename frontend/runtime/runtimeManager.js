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

  function unwrapExportPayload(cached) {
    if (cached == null) return null;
    if (cached.error && cached.data == null && !cached.metrics_all_time && !cached.predictions) {
      return null;
    }
    return cached.data !== undefined ? cached.data : cached;
  }

  function applyCacheFromSnapshot(snapshot) {
    const cache = config.cache;
    if (!cache || !snapshot) return;
    const data = snapshot.data || {};
    cache.intelligence = unwrapExportPayload(data.intelligence);
    cache.indiaMarket = unwrapExportPayload(data.india);
    cache.globalMarket = unwrapExportPayload(data.markets);
    cache.news = unwrapExportPayload(data.news);
    cache.youtube = unwrapExportPayload(data.youtube);
    cache.govt = unwrapExportPayload(data.govt);
    cache.inshorts = unwrapExportPayload(data.inshorts);
    cache.reddit = unwrapExportPayload(data.reddit);
    cache.scanner = unwrapExportPayload(data.scanner);
    cache.stats = unwrapExportPayload(data.stats);
    cache.history = unwrapExportPayload(data.history);
    cache.activePredictions = unwrapExportPayload(data.active_predictions);
    cache.predictionHistory = unwrapExportPayload(data.prediction_history);
    cache.lifecycleState = unwrapExportPayload(data.lifecycle_state);
    cache.runtime = snapshot;
    cache.lastFetch = Date.now();
    cache.connected = snapshot.status !== 'degraded';
  }

  function invalidateCache(reason) {
    const cache = config.cache;
    if (!cache) return;
    const keys = [
      'intelligence', 'indiaMarket', 'globalMarket', 'news', 'youtube', 'govt',
      'inshorts', 'reddit', 'scanner', 'stats', 'history', 'activePredictions',
      'predictionHistory', 'lifecycleState', 'runtime',
    ];
    keys.forEach((k) => { cache[k] = null; });
    cache.connected = false;
    cache._invalidatedAt = Date.now();
    cache._invalidateReason = reason || 'stale';
    console.warn('[RuntimeManager] cache invalidated:', reason);
  }

  function applySnapshot(snapshot, seq) {
    if (seq !== fetchSeq) return false;
    const orch = snapshot && snapshot.panels && snapshot.panels.orchestrator;
    const runtimePanel = snapshot && snapshot.panels && snapshot.panels.runtime;
    if (orch && orch.stale) {
      invalidateCache('orchestrator_stale');
    } else if (runtimePanel && runtimePanel.stale && orch && !orch.gui_sync_validated) {
      invalidateCache('gui_sync_stale');
    }
    state = snapshot;
    applyCacheFromSnapshot(snapshot);
    if (typeof config.onConnectionChange === 'function') {
      config.onConnectionChange(!!cacheConnected());
    }
    notify();
    if (orch && orch.stale) {
      setTimeout(() => refresh({ force: true }), 2000);
    }
    return true;
  }

  function cacheConnected() {
    return !!(config.cache && config.cache.connected);
  }

  const FETCH_TIMEOUT_MS = 20000;

  async function fetchSnapshot() {
    const base = config.getApiBase().replace(/\/$/, '');
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
    try {
      const res = await fetch(base + '/api/runtime_snapshot', {
        method: 'GET',
        headers: config.getHeaders(),
        signal: controller.signal,
      });
      if (!res.ok) throw new Error(`runtime_snapshot → ${res.status}`);
      return res.json();
    } finally {
      clearTimeout(timer);
    }
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
      const msg = e.name === 'AbortError' ? 'API timeout (20s)' : e.message;
      console.error('[RuntimeManager] refresh failed:', msg);
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

  function formatAgeSeconds(sec) {
    if (sec == null || sec === '') return '';
    const n = Number(sec);
    if (!Number.isFinite(n)) return '';
    if (n < 60) return `${n}s ago`;
    if (n < 3600) return `${Math.floor(n / 60)}m ago`;
    return `${Math.floor(n / 3600)}h ago`;
  }

  function getExportAge(sourceKey) {
    const src = (state && state.source_status && state.source_status[sourceKey]) || {};
    if (src.status === 'missing') return 'Export not generated yet';
    if (src.age_seconds != null) return `Export age: ${formatAgeSeconds(src.age_seconds)}`;
    return '';
  }

  function getPanelBanner(panelId, sourceKey) {
    const panel = getPanelState(panelId);
    const age = sourceKey ? getExportAge(sourceKey) : '';
    return {
      status: panel.status || 'waiting',
      message: panel.message || '',
      age: age,
      stale: !!panel.stale,
      pipelineStatus: panel.pipeline_status || null,
    };
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
    formatAgeSeconds,
    getExportAge,
    getPanelBanner,
    invalidateCache,
  };
})(window);
