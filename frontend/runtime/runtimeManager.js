/**
 * RuntimeManager — single coordinated refresh loop + shared runtime state.
 * All intelligence tabs subscribe here instead of polling independently.
 */
(function (global) {
  'use strict';

  const DEFAULT_POLL_MS = 30000;
  const MIN_REFRESH_GAP_MS = 4000;
  const NOTIFY_DEBOUNCE_MS = 80;

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
  let lastStaleForcedRefreshAt = 0;
  const STALE_FORCE_REFRESH_MS = 30000;
  const subscribers = new Set();
  const panelHandlers = new Map();

  let lastSnapshotHash = null;
  let panelContentHashes = {};
  let notifyTimer = null;

  function stableHash(value) {
    const text = typeof value === 'string' ? value : JSON.stringify(value);
    let hash = 5381;
    for (let i = 0; i < text.length; i += 1) {
      hash = ((hash << 5) + hash) + text.charCodeAt(i);
      hash &= 0xffffffff;
    }
    return String(hash >>> 0);
  }

  function computePanelHashes(snapshot) {
    const data = (snapshot && snapshot.data) || {};
    return {
      brain: stableHash({ i: data.intelligence, a: data.active_predictions }),
      govt: stableHash(data.govt),
      scanner: stableHash(data.scanner),
      global: stableHash({ m: data.markets, o: data.overnight_impact, i: data.india_next_open }),
      news: stableHash({ n: data.news, inshorts: data.inshorts }),
      tv: stableHash(data.youtube),
      reddit: stableHash(data.reddit),
      stats: stableHash(data.stats),
      history: stableHash(data.history),
    };
  }

  function computeSnapshotHash(snapshot) {
    const panels = computePanelHashes(snapshot);
    const meta = {
      generated_at: snapshot && snapshot.generated_at,
      active_snapshot_id: snapshot && snapshot.active_snapshot_id,
      snapshot_version: snapshot && snapshot.snapshot_version,
      panels: snapshot && snapshot.panels,
    };
    return stableHash({ panels, meta });
  }

  function notify(meta) {
    const payload = meta || {};
    subscribers.forEach((fn) => {
      try {
        fn(state, payload);
      } catch (e) {
        console.error('[RuntimeManager] subscriber error', e);
      }
    });
    panelHandlers.forEach((fn) => {
      try {
        fn(state, payload);
      } catch (e) {
        console.error('[RuntimeManager] panel handler error', e);
      }
    });
  }

  function scheduleNotify(meta) {
    if (notifyTimer) clearTimeout(notifyTimer);
    notifyTimer = setTimeout(() => {
      notifyTimer = null;
      notify(meta);
    }, NOTIFY_DEBOUNCE_MS);
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

  function applySnapshot(snapshot, seq, opts) {
    opts = opts || {};
    if (seq !== fetchSeq) return false;
    if (!snapshot || typeof snapshot !== 'object') return false;

    const orch = snapshot.panels && snapshot.panels.orchestrator;
    const runtimePanel = snapshot.panels && snapshot.panels.runtime;
    const hasData = !!(snapshot.data && (snapshot.data.intelligence || snapshot.data.scanner));

    if (!hasData && orch && orch.stale) {
      invalidateCache('orchestrator_stale');
    } else if (!hasData && runtimePanel && runtimePanel.stale && orch && !orch.gui_sync_validated) {
      invalidateCache('gui_sync_stale');
    } else if (orch && orch.gui_sync_validated && runtimePanel && !runtimePanel.stale) {
      /* scheduler healthy — keep cache even if export files lag briefly */
    }

    const nextHash = computeSnapshotHash(snapshot);
    const nextPanelHashes = computePanelHashes(snapshot);
    const unchanged = !opts.force && nextHash === lastSnapshotHash;

    state = snapshot;
    lastSnapshotHash = nextHash;
    panelContentHashes = nextPanelHashes;

    try {
      applyCacheFromSnapshot(snapshot);
    } catch (e) {
      console.error('[RuntimeManager] cache apply failed', e);
    }
    if (typeof config.onConnectionChange === 'function') {
      config.onConnectionChange(!!cacheConnected());
    }

    if (unchanged) {
      return true;
    }

    scheduleNotify({
      unchanged: false,
      snapshotHash: nextHash,
      panelHashes: nextPanelHashes,
    });

    if (orch && orch.stale && !hasData) {
      const now = Date.now();
      if (now - lastStaleForcedRefreshAt >= STALE_FORCE_REFRESH_MS) {
        lastStaleForcedRefreshAt = now;
        setTimeout(() => refresh({ force: true }), 2000);
      }
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
      applySnapshot(snapshot, seq, opts);
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
    refresh({ force: true }).catch((e) => console.error('[RuntimeManager] initial refresh failed', e));
    pollTimer = setInterval(() => {
      refresh().catch((e) => console.error('[RuntimeManager] poll refresh failed', e));
    }, pollMs || DEFAULT_POLL_MS);
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
        fn(state, { unchanged: false, panelHashes: panelContentHashes, snapshotHash: lastSnapshotHash });
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
        fn(state, { unchanged: false, panelHashes: panelContentHashes, snapshotHash: lastSnapshotHash });
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

  function getPanelHashes() {
    return { ...panelContentHashes };
  }

  function getSnapshotHash() {
    return lastSnapshotHash;
  }

  function panelChanged(panelId, previousHash) {
    return panelContentHashes[panelId] !== previousHash;
  }

  function formatMetricDisplay(value, kind) {
    if (value === null || value === undefined || value === '') {
      if (kind === 'win_rate') return 'Awaiting statistical confidence';
      if (kind === 'regime') return 'Monitoring regime formation';
      if (kind === 'percent') return 'Confidence building';
      return 'Awaiting evaluation sample';
    }
    if (typeof value === 'string') {
      const t = value.trim();
      if (!t || t.toLowerCase() === 'none' || t.toLowerCase() === 'unknown' || t === '—' || t === '—%') {
        if (kind === 'win_rate') return 'Awaiting statistical confidence';
        if (kind === 'regime') return 'Monitoring regime formation';
        return 'Awaiting evaluation sample';
      }
      if (t.includes('Awaiting') || t.includes('Confidence') || t.includes('Insufficient') || t.includes('Monitoring')) {
        return t;
      }
    }
    if (kind === 'win_rate' && typeof value === 'number') {
      return `${Number(value).toFixed(1)}%`;
    }
    return String(value);
  }

  function getRuntimeStateFields() {
    const snap = state || {};
    const rs = snap.runtime_state || {};
    return {
      lifecycle: rs.lifecycle || {},
      regime: rs.regime || {},
      winRate: rs.win_rate || {},
      predictionCounts: rs.prediction_counts || {},
      snapshotFreshness: rs.snapshot_freshness || {},
      intelligenceStatus: rs.intelligence_status || {},
      qualityScore: rs.quality_score || {},
      calibrationSummary: snap.calibration_summary || {},
    };
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

  function getFreshnessState() {
    const fs = (state && state.freshness_state) || {};
    const runtimePanel = getPanelState('runtime');
    return {
      exportStale: !!fs.export_stale,
      collectorsActive: !!fs.collectors_active || !!runtimePanel.collectors_active,
      partialLag: !!fs.partial_lag || !!runtimePanel.export_lag,
    };
  }

  function isStale() {
    const runtimePanel = getPanelState('runtime');
    if (runtimePanel && runtimePanel.status === 'idle') return false;
    const op = state && state.operational;
    if (op && op.expect_quiet_collectors && runtimePanel && !runtimePanel.stale) return false;
    const fresh = getFreshnessState();
    if (fresh.partialLag || fresh.collectorsActive) return false;
    return !!(runtimePanel && runtimePanel.stale);
  }

  function timestampHtml(extra) {
    const ts = formatTimestamp();
    const runtimePanel = getPanelState('runtime');
    const op = state && state.operational;
    const fresh = getFreshnessState();
    const snapVer = (state && state.snapshot_version) || runtimePanel.snapshot_version;
    const snapFresh = runtimePanel.snapshot_freshness_minutes;
    let statusTag = '';
    if (runtimePanel && runtimePanel.status === 'idle' && op && op.display_status) {
      statusTag = ` · <span class="runtime-idle">${op.display_status}</span>`;
    } else if (fresh.partialLag || (fresh.collectorsActive && fresh.exportStale)) {
      statusTag = ' · <span class="runtime-live">live collectors active</span>';
    } else if (isStale()) {
      statusTag = ' · <span class="runtime-stale">snapshot stale</span>';
    }
    const snapTag = snapVer != null ? ` · snap v${snapVer}` : '';
    const freshTag = snapFresh != null ? ` · ${snapFresh}m old` : '';
    const suffix = extra ? ` · ${extra}` : '';
    return `<div class="timestamp runtime-ts">Updated: ${ts}${snapTag}${freshTag}${suffix}${statusTag}</div>`;
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
    const op = state && state.operational;
    const fresh = getFreshnessState();
    const isIdle = panel.status === 'idle' || (op && op.expect_quiet_collectors && panel.status === 'ready' && sourceKey in { scanner: 1, news: 1, reddit: 1, youtube: 1, inshorts: 1 });
    const panelStale = isIdle ? false : !!panel.stale;
    const orchValidated = state && state.panels && state.panels.orchestrator && state.panels.orchestrator.gui_sync_validated;
    const statsHealthy = panelId === 'stats' && orchValidated && fresh.collectorsActive;
    const showStale = panelStale && !fresh.collectorsActive && !fresh.partialLag && !statsHealthy;
    return {
      status: panel.status || 'waiting',
      message: panel.message || (isIdle && op ? op.display_message : ''),
      age: '',
      stale: showStale,
      collectorsActive: fresh.collectorsActive || fresh.partialLag,
      pipelineStatus: panel.pipeline_status || null,
      displayStatus: panel.display_status || (op && op.display_status) || null,
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
    getPanelHashes,
    getSnapshotHash,
    getFreshnessState,
    panelChanged,
    formatTimestamp,
    isStale,
    timestampHtml,
    lifecycleMessage,
    formatAgeSeconds,
    getExportAge,
    getPanelBanner,
    invalidateCache,
    formatMetricDisplay,
    getRuntimeStateFields,
  };
})(window);
