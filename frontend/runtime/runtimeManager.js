/**
 * RuntimeManager — single coordinated refresh loop + shared runtime state.
 * All intelligence tabs subscribe here instead of polling independently.
 * Hydrates exclusively from GET /api/runtime/snapshot.
 */
(function (global) {
  'use strict';

  const DEFAULT_POLL_MS = 30000;
  const MIN_REFRESH_GAP_MS = 4000;
  const NOTIFY_DEBOUNCE_MS = 80;
  const SNAPSHOT_ENDPOINT = '/api/runtime/snapshot';

  let config = {
    getApiBase: () => '',
    getHeaders: () => ({}),
    cache: null,
    onConnectionChange: null,
    onLoadingChange: null,
  };

  let state = null;
  let normalizedState = null;
  let pollTimer = null;
  let started = false;
  let inFlight = false;
  let fetchSeq = 0;
  let lastRefreshAt = 0;
  let lastStaleForcedRefreshAt = 0;
  let lastHydrationMs = null;
  let lastFetchError = null;
  let failedWidgets = [];
  const STALE_FORCE_REFRESH_MS = 30000;
  const subscribers = new Set();
  const panelHandlers = new Map();

  let lastSnapshotHash = null;
  let panelContentHashes = {};
  let notifyTimer = null;
  let loading = false;

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
    const exports = (snapshot && (snapshot.exports || snapshot.data)) || {};
    const ms = (snapshot && snapshot.market_snapshot) || snapshot || {};
    const intel = exports.intelligence || ms.intelligence || {};
    return {
      brain: stableHash({
        i: intel,
        a: exports.active_predictions,
        ap: ms.action_plan || intel.action_plan,
      }),
      govt: stableHash(exports.govt),
      scanner: stableHash(exports.scanner),
      markets: stableHash({ m: exports.markets, i: exports.india }),
      global: stableHash({ m: exports.markets, o: snapshot && snapshot.overnight_impact, i: snapshot && snapshot.india_next_open }),
      news: stableHash({ n: exports.news, inshorts: exports.inshorts }),
      tv: stableHash(exports.youtube),
      reddit: stableHash(exports.reddit),
      stats: stableHash(exports.stats),
      history: stableHash(exports.history),
    };
  }

  function computeSnapshotHash(snapshot) {
    const panels = computePanelHashes(snapshot);
    const meta = {
      generated_at: snapshot && snapshot.generated_at,
      active_snapshot_id: snapshot && snapshot.active_snapshot_id,
      snapshot_version: snapshot && snapshot.snapshot_version,
      snapshot_id: snapshot && snapshot.snapshot_id,
      panels: snapshot && snapshot.panels,
    };
    return stableHash({ panels, meta });
  }

  function setLoading(isLoading) {
    loading = !!isLoading;
    if (typeof config.onLoadingChange === 'function') {
      try {
        config.onLoadingChange(loading);
      } catch (e) {
        console.error('[RuntimeManager] onLoadingChange error', e);
      }
    }
  }

  function notify(meta) {
    const payload = meta || {};
    subscribers.forEach((fn) => {
      try {
        fn(state, payload);
      } catch (e) {
        console.error('[RuntimeManager] subscriber error', e);
        failedWidgets.push('subscriber');
      }
    });
    panelHandlers.forEach((fn) => {
      try {
        fn(state, payload);
      } catch (e) {
        console.error('[RuntimeManager] panel handler error', e);
        failedWidgets.push('panel_handler');
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

  function mergeIntelWithSnapshot(intelRaw, snapshot) {
    const ms = (snapshot && snapshot.market_snapshot) || snapshot || {};
    const intel = unwrapExportPayload(intelRaw);
    if (!intel || typeof intel !== 'object') return intel;
    const out = { ...intel };
    if (ms.action_plan) out.action_plan = ms.action_plan;
    else if (snapshot.action_plan) out.action_plan = snapshot.action_plan;
    if (ms.sector_rotation && Object.keys(ms.sector_rotation).length) {
      out.sector_rotation = ms.sector_rotation;
    }
    if (Array.isArray(ms.top_opportunities) && ms.top_opportunities.length) {
      out.top_opportunities = ms.top_opportunities;
    }
    if (Array.isArray(ms.risk_list) && ms.risk_list.length) {
      out.risks_and_avoids = ms.risk_list;
    }
    if (ms.executive_summary) out.executive_summary = ms.executive_summary;
    if (ms.calibration != null) out.self_calibration = ms.calibration;
    return out;
  }

  function normalizeRawSnapshot(snapshot) {
    if (global.SnapshotAdapter && typeof global.SnapshotAdapter.normalizeSnapshot === 'function') {
      return global.SnapshotAdapter.normalizeSnapshot(snapshot);
    }
    return null;
  }

  function applyCacheFromSnapshot(snapshot, normalized) {
    const cache = config.cache;
    if (!cache || !snapshot) return;
    const norm = normalized || normalizeRawSnapshot(snapshot);
    const exports = norm && norm.exports
      ? norm.exports
      : (snapshot.exports || snapshot.data || {});
    const ms = (norm && norm.marketSnapshot) || snapshot.market_snapshot || {};

    cache.intelligence = mergeIntelWithSnapshot(exports.intelligence || ms.intelligence, snapshot);
    cache.indiaMarket = exports.india != null ? exports.india : unwrapExportPayload((snapshot.exports || snapshot.data || {}).india);
    cache.globalMarket = exports.markets != null ? exports.markets : unwrapExportPayload((snapshot.exports || snapshot.data || {}).markets);
    cache.news = exports.news != null ? exports.news : unwrapExportPayload((snapshot.exports || snapshot.data || {}).news);
    cache.youtube = exports.youtube != null ? exports.youtube : unwrapExportPayload((snapshot.exports || snapshot.data || {}).youtube);
    cache.govt = exports.govt != null ? exports.govt : unwrapExportPayload((snapshot.exports || snapshot.data || {}).govt);
    cache.inshorts = exports.inshorts != null ? exports.inshorts : unwrapExportPayload((snapshot.exports || snapshot.data || {}).inshorts);
    cache.reddit = exports.reddit != null ? exports.reddit : unwrapExportPayload((snapshot.exports || snapshot.data || {}).reddit);
    cache.scanner = exports.scanner != null ? exports.scanner : unwrapExportPayload((snapshot.exports || snapshot.data || {}).scanner);
    cache.stats = exports.stats != null ? exports.stats : unwrapExportPayload((snapshot.exports || snapshot.data || {}).stats);
    const msMetrics = ms.metrics || {};
    if (msMetrics.evaluated != null || msMetrics.wins != null) {
      cache.stats = {
        ...(cache.stats || {}),
        metrics_all_time: {
          ...((cache.stats && cache.stats.metrics_all_time) || {}),
          ...msMetrics,
        },
        metric_sections: msMetrics.sections || (cache.stats && cache.stats.metric_sections),
        lifecycle_calibration: ms.calibration || (cache.stats && cache.stats.lifecycle_calibration),
      };
    }
    cache.history = exports.history != null ? exports.history : unwrapExportPayload((snapshot.exports || snapshot.data || {}).history);
    cache.activePredictions = exports.activePredictions != null
      ? exports.activePredictions
      : unwrapExportPayload((snapshot.exports || snapshot.data || {}).active_predictions);
    cache.predictionHistory = exports.predictionHistory != null
      ? exports.predictionHistory
      : unwrapExportPayload((snapshot.exports || snapshot.data || {}).prediction_history);
    cache.lifecycleState = exports.lifecycleState != null
      ? exports.lifecycleState
      : unwrapExportPayload((snapshot.exports || snapshot.data || {}).lifecycle_state);
    cache.runtime = snapshot;
    cache.marketSnapshot = ms;
    cache.normalized = norm;
    cache.actionPlan = (norm && norm.actionPlan)
      || ms.action_plan || snapshot.action_plan || (cache.intelligence && cache.intelligence.action_plan) || '';
    cache.lastFetch = Date.now();
    cache.connected = snapshot.status !== 'degraded' || !!(exports.intelligence || ms.intelligence);
  }

  function invalidateCache(reason) {
    const cache = config.cache;
    if (!cache) return;
    const keys = [
      'intelligence', 'indiaMarket', 'globalMarket', 'news', 'youtube', 'govt',
      'inshorts', 'reddit', 'scanner', 'stats', 'history', 'activePredictions',
      'predictionHistory', 'lifecycleState', 'runtime', 'marketSnapshot', 'actionPlan',
    ];
    keys.forEach((k) => { cache[k] = null; });
    cache.connected = false;
    cache._invalidatedAt = Date.now();
    cache._invalidateReason = reason || 'stale';
    console.warn('[RuntimeManager] cache invalidated:', reason);
  }

  function applySnapshot(snapshot, seq, opts) {
    opts = opts || {};
    if (seq !== fetchSeq) return { ok: false, reason: 'stale_seq' };
    if (!snapshot || typeof snapshot !== 'object') {
      console.error('[RuntimeManager] applySnapshot rejected — invalid payload');
      return { ok: false, reason: 'invalid_payload' };
    }

    global.runtimeSnapshot = snapshot;
    normalizedState = normalizeRawSnapshot(snapshot);
    if (normalizedState && normalizedState.meta && normalizedState.meta.missingFields.length) {
      console.warn('[RuntimeManager] normalized snapshot missing:', normalizedState.meta.missingFields.join(', '));
    }

    const exports = snapshot.exports || snapshot.data || {};
    const ms = (normalizedState && normalizedState.marketSnapshot) || snapshot.market_snapshot || {};
    const orch = snapshot.panels && snapshot.panels.orchestrator;
    const runtimePanel = snapshot.panels && snapshot.panels.runtime;
    const hasData = !!(
      (exports.intelligence || ms.intelligence)
      || exports.scanner
      || ms.action_plan
    );

    if (!hasData && orch && orch.stale) {
      invalidateCache('orchestrator_stale');
    } else if (!hasData && runtimePanel && runtimePanel.stale && orch && !orch.gui_sync_validated) {
      invalidateCache('gui_sync_stale');
    }

    const nextHash = computeSnapshotHash(snapshot);
    const nextPanelHashes = computePanelHashes(snapshot);
    const unchanged = !opts.force && nextHash === lastSnapshotHash;

    state = snapshot;
    lastSnapshotHash = nextHash;
    panelContentHashes = nextPanelHashes;
    failedWidgets = [];

    try {
      applyCacheFromSnapshot(snapshot, normalizedState);
    } catch (e) {
      console.error('[RuntimeManager] cache apply failed', e);
      failedWidgets.push('cache_apply');
    }
    if (typeof config.onConnectionChange === 'function') {
      config.onConnectionChange(!!cacheConnected());
    }

    const notifyMeta = {
      unchanged,
      snapshotHash: nextHash,
      panelHashes: nextPanelHashes,
      hydrationMs: lastHydrationMs,
      hydrationComplete: true,
      normalized: !!normalizedState,
    };

    if (unchanged && !opts.force) {
      scheduleNotify(notifyMeta);
      return { ok: true, unchanged: true };
    }

    scheduleNotify({
      ...notifyMeta,
      unchanged: false,
    });

    if (orch && orch.stale && !hasData) {
      const now = Date.now();
      if (now - lastStaleForcedRefreshAt >= STALE_FORCE_REFRESH_MS) {
        lastStaleForcedRefreshAt = now;
        setTimeout(() => refresh({ force: true }), 2000);
      }
    }
    console.log('[RuntimeManager] snapshot applied', {
      id: normalizedState && normalizedState.meta && normalizedState.meta.snapshotId,
      status: normalizedState && normalizedState.meta && normalizedState.meta.status,
      stale: normalizedState && normalizedState.meta && normalizedState.meta.stale,
      ms: lastHydrationMs,
    });
    return { ok: true, unchanged: false };
  }

  function cacheConnected() {
    return !!(config.cache && config.cache.connected);
  }

  const FETCH_TIMEOUT_MS = 8000;

  async function fetchSnapshot() {
    const base = config.getApiBase().replace(/\/$/, '');
    const url = base + SNAPSHOT_ENDPOINT;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
    const started = Date.now();
    try {
      const res = await fetch(url, {
        method: 'GET',
        headers: config.getHeaders(),
        signal: controller.signal,
      });
      if (!res.ok) throw new Error(`${SNAPSHOT_ENDPOINT} → HTTP ${res.status}`);
      const payload = await res.json();
      if (!payload || typeof payload !== 'object') {
        throw new Error(`${SNAPSHOT_ENDPOINT} → invalid JSON payload`);
      }
      lastHydrationMs = Date.now() - started;
      lastFetchError = null;
      console.log('[RuntimeManager] fetchSnapshot success', {
        endpoint: SNAPSHOT_ENDPOINT,
        ms: lastHydrationMs,
        bytes: JSON.stringify(payload).length,
      });
      return payload;
    } catch (e) {
      lastFetchError = e.name === 'AbortError'
        ? `${SNAPSHOT_ENDPOINT} timeout (${FETCH_TIMEOUT_MS / 1000}s)`
        : `${SNAPSHOT_ENDPOINT}: ${e.message || 'fetch failed'}`;
      console.error('[RuntimeManager] fetchSnapshot failed:', lastFetchError);
      throw e;
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
    setLoading(true);
    let refreshError = null;
    try {
      const snapshot = await fetchSnapshot();
      lastRefreshAt = Date.now();
      const applied = applySnapshot(snapshot, seq, opts);
      if (!applied || !applied.ok) {
        console.warn('[RuntimeManager] applySnapshot incomplete:', applied && applied.reason);
        scheduleNotify({
          unchanged: false,
          hydrationComplete: true,
          error: (applied && applied.reason) || 'apply_failed',
          failed: true,
        });
      }
      return state;
    } catch (e) {
      const msg = e.name === 'AbortError' ? `API timeout (${FETCH_TIMEOUT_MS / 1000}s)` : (e.message || 'refresh failed');
      refreshError = msg;
      console.error('[RuntimeManager] refresh failed:', msg);
      if (config.cache) config.cache.connected = false;
      if (typeof config.onConnectionChange === 'function') {
        config.onConnectionChange(false);
      }
      return state;
    } finally {
      inFlight = false;
      setLoading(false);
      if (refreshError) {
        scheduleNotify({
          unchanged: false,
          error: refreshError,
          failed: true,
          hydrationComplete: true,
        });
      }
      console.log('[RuntimeManager] refresh cycle complete', {
        hasState: !!state,
        error: refreshError,
      });
    }
  }

  function start(pollMs) {
    if (started) return;
    started = true;
    refresh({ force: true }).catch((e) => {
      console.error('[RuntimeManager] initial refresh failed', e);
      scheduleNotify({ unchanged: false, error: e.message, failed: true });
    });
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

  function getNormalizedState() {
    return normalizedState;
  }

  function getCache() {
    return config.cache;
  }

  function getActionPlan() {
    const snap = state || {};
    const ms = snap.market_snapshot || getMarketSnapshot() || {};
    return ms.action_plan || snap.action_plan || (config.cache && config.cache.actionPlan) || '';
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

  function getHydrationDebug() {
    const snap = state || {};
    const ms = snap.market_snapshot || {};
    const payloadText = JSON.stringify(snap);
    const missing = [];
    if (!snap.snapshot_id && !snap.active_snapshot_id) missing.push('snapshot_id');
    if (!snap.generated_at) missing.push('generated_at');
    if (!ms.action_plan && !snap.action_plan) missing.push('action_plan');
    if (!(snap.exports || snap.data || {}).intelligence && !ms.intelligence) missing.push('intelligence');
    return {
      snapshot_id: snap.snapshot_id || snap.active_snapshot_id,
      snapshot_version: snap.snapshot_version || (ms.freshness || {}).snapshot_version,
      generated_at: snap.generated_at || ms.generated_at,
      payload_bytes: payloadText.length,
      hydration_ms: lastHydrationMs,
      missing_fields: missing,
      failed_widgets: failedWidgets.slice(),
      last_error: lastFetchError,
      status: snap.status || 'unknown',
      warnings: snap.validation_warnings || [],
    };
  }

  function panelChanged(panelId, previousHash) {
    return panelContentHashes[panelId] !== previousHash;
  }

  function formatFreshnessDisplay(minutes, displayFromState) {
    if (displayFromState && displayFromState !== 'freshness unavailable') {
      const bad = /^(none|null|undefined)m$/i.test(String(displayFromState).trim());
      if (!bad) return displayFromState;
    }
    if (minutes == null || minutes === '' || Number.isNaN(Number(minutes))) {
      return 'freshness unavailable';
    }
    const n = Number(minutes);
    if (!Number.isFinite(n) || n < 0) return 'freshness unavailable';
    if (n < 60) return `${n}m`;
    return `${Math.floor(n / 60)}h ${n % 60}m`;
  }

  function freshnessTierLabel(minutes, tierFromState) {
    if (tierFromState) return tierFromState;
    if (minutes == null || !Number.isFinite(Number(minutes))) return 'unavailable';
    const n = Number(minutes);
    if (n < 5) return 'healthy';
    if (n < 15) return 'aging';
    return 'stale';
  }

  function getIstDateKey(dateLike) {
    if (!dateLike) return '';
    try {
      const d = new Date(dateLike);
      return d.toLocaleDateString('en-CA', { timeZone: 'Asia/Kolkata' });
    } catch (e) {
      return String(dateLike).slice(0, 10);
    }
  }

  function getIstTradingDayKey(referenceIso) {
    return getIstDateKey(referenceIso || new Date().toISOString());
  }

  function getIstYesterdayKey(referenceIso) {
    const todayKey = getIstTradingDayKey(referenceIso);
    if (!todayKey) return '';
    const parts = todayKey.split('-').map(Number);
    const utcNoon = Date.UTC(parts[0], parts[1] - 1, parts[2], 6, 30, 0);
    const prior = new Date(utcNoon - 86400000);
    return getIstDateKey(prior.toISOString());
  }

  function getJournalDayBadge(dateStr) {
    const ms = getMarketSnapshot() || {};
    const rs = ms.runtime_state || (state && state.runtime_state) || {};
    const generated = rs.generated_at || (state && state.generated_at) || ms.generated_at;
    const todayKey = getIstTradingDayKey(generated);
    const entryKey = getIstDateKey(dateStr);
    if (!entryKey) return '—';
    if (entryKey === todayKey) return 'Today';
    if (entryKey === getIstYesterdayKey(generated)) return 'Yesterday';
    return entryKey;
  }

  function sortJournalEntries(entries) {
    return (entries || []).slice().sort((a, b) => {
      const da = getIstDateKey(a && a.date);
      const db = getIstDateKey(b && b.date);
      return db.localeCompare(da);
    });
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

  function getMarketSnapshot() {
    const snap = state || {};
    return snap.market_snapshot || snap || null;
  }

  function getCanonicalMetrics() {
    const ms = getMarketSnapshot() || {};
    const metrics = ms.metrics || {};
    const rs = ms.runtime_state || (state && state.runtime_state) || {};
    const cal = (state && state.calibration_summary) || {};
    const sections = metrics.sections || cal.metric_sections || {};
    const live = sections.live_session || cal.live_session || {};
    const hist = sections.historical_calibration || cal.historical_calibration || {};
    const archived = sections.archived || cal.archived || {};
    const counts = rs.prediction_counts || {};
    return {
      wins: metrics.wins ?? counts.wins ?? hist.wins ?? cal.wins ?? 0,
      losses: metrics.losses ?? counts.losses ?? hist.losses ?? cal.losses ?? 0,
      partials: metrics.partials ?? counts.partials ?? cal.partials ?? 0,
      resolved: metrics.resolved ?? counts.resolved ?? cal.resolved ?? 0,
      pending: live.pending ?? metrics.pending ?? counts.pending ?? cal.pending ?? 0,
      evaluated: hist.evaluated_sample ?? metrics.evaluated ?? counts.evaluated ?? cal.evaluated ?? 0,
      expired: archived.expired ?? metrics.expired ?? counts.expired ?? cal.expired ?? 0,
      neutralized: archived.neutralized ?? metrics.neutralized ?? counts.neutralized ?? cal.neutralized ?? 0,
      active_predictions: live.active_predictions ?? live.pending ?? counts.pending ?? 0,
      resolved_today: live.resolved_today ?? 0,
      win_rate: hist.win_rate ?? metrics.win_rate ?? cal.win_rate ?? null,
      win_rate_display: hist.win_rate_display ?? metrics.win_rate_display ?? cal.win_rate_display ?? null,
      statistically_confident: hist.statistically_confident ?? metrics.statistically_confident ?? cal.statistically_confident ?? false,
      sections,
      live_session: live,
      historical_calibration: hist,
      archived,
      source: metrics.source || cal.source || 'snapshot',
    };
  }

  function getRuntimeStateFields() {
    const snap = state || {};
    const ms = getMarketSnapshot() || {};
    const rs = ms.runtime_state || snap.runtime_state || {};
    const cal = snap.calibration_summary || {};
    const metrics = getCanonicalMetrics();
    return {
      lifecycle: ms.lifecycle || rs.lifecycle || {},
      regime: ms.regime || rs.regime || {},
      winRate: rs.win_rate || {
        win_rate: metrics.win_rate,
        win_rate_display: metrics.win_rate_display,
        statistically_confident: metrics.statistically_confident,
      },
      predictionCounts: rs.prediction_counts || metrics,
      canonicalMetrics: metrics,
      snapshotFreshness: ms.freshness || rs.snapshot_freshness || {},
      intelligenceStatus: rs.intelligence_status || {},
      qualityScore: ms.quality_score || rs.quality_score || {},
      calibrationSummary: cal,
      blockers: ms.blockers || snap.blockers || [],
      pipelineHealth: ms.pipeline_health || snap.pipeline_health || {},
      primaryState: snap.primary_state || rs.primary_state,
      actionPlan: getActionPlan(),
    };
  }

  function formatTimestamp() {
    const snap = state || {};
    const ms = getMarketSnapshot() || {};
    const iso = snap.generated_at || ms.generated_at;
    if (!iso) return '—';
    try {
      return new Date(iso).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });
    } catch (e) {
      return '—';
    }
  }

  function getFreshnessState() {
    const ms = getMarketSnapshot() || {};
    const fs = (state && state.freshness_state) || {};
    const runtimePanel = getPanelState('runtime');
    const fresh = ms.freshness || {};
    return {
      exportStale: !!fs.export_stale || !!fresh.stale,
      collectorsActive: !!fs.collectors_active || !!runtimePanel.collectors_active,
      partialLag: !!fs.partial_lag || !!runtimePanel.export_lag,
      tier: fresh.health_tier,
      degraded: !!fresh.degraded,
    };
  }

  function isStale() {
    const ms = getMarketSnapshot();
    if (ms && ms.freshness && ms.freshness.stale) return true;
    const rs = (ms && ms.runtime_state) || (state && state.runtime_state) || {};
    const flags = rs.secondary_flags || {};
    if (flags.stale_snapshot) return true;
    const runtimePanel = getPanelState('runtime');
    if (runtimePanel && runtimePanel.status === 'idle') return false;
    const op = state && state.operational;
    if (op && op.expect_quiet_collectors && runtimePanel && !runtimePanel.stale) return false;
    const fresh = getFreshnessState();
    if (fresh.partialLag || fresh.collectorsActive) return false;
    return !!(runtimePanel && runtimePanel.stale);
  }

  function timestampHtml(extra) {
    const snap = state || {};
    const ms = getMarketSnapshot() || {};
    const ts = formatTimestamp();
    const runtimePanel = getPanelState('runtime');
    const op = snap.operational;
    const fresh = getFreshnessState();
    const snapVer = snap.snapshot_version || runtimePanel.snapshot_version || (ms.freshness || {}).snapshot_version;
    const rs = ms.runtime_state || snap.runtime_state || {};
    const freshPanel = ms.freshness || rs.snapshot_freshness || {};
    const snapFreshRaw = runtimePanel.snapshot_freshness_display
      || freshPanel.age_display
      || runtimePanel.snapshot_freshness_minutes;
    const snapFresh = formatFreshnessDisplay(runtimePanel.snapshot_freshness_minutes ?? freshPanel.age_minutes, snapFreshRaw);
    const tier = runtimePanel.freshness_tier || freshPanel.health_tier
      || freshnessTierLabel(runtimePanel.snapshot_freshness_minutes ?? freshPanel.age_minutes);
    let statusTag = '';
    if (runtimePanel && runtimePanel.status === 'idle' && op && op.display_status) {
      statusTag = ` · <span class="runtime-idle">${op.display_status}</span>`;
    } else if (fresh.partialLag || (fresh.collectorsActive && fresh.exportStale)) {
      statusTag = ' · <span class="runtime-live">live collectors active</span>';
    } else if (fresh.degraded) {
      statusTag = ' · <span class="runtime-stale">degraded</span>';
    } else if (isStale()) {
      statusTag = ' · <span class="runtime-stale">snapshot stale</span>';
    }
    const snapTag = snapVer != null ? ` · snap v${snapVer}` : '';
    const freshTag = snapFresh && snapFresh !== 'freshness unavailable'
      ? ` · ${snapFresh} (${tier})`
      : (snapFresh === 'freshness unavailable' ? ' · freshness unavailable' : '');
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

  function unavailableBanner(reason) {
    const msg = reason || lastFetchError || 'Data unavailable';
    return `<div class="panel-status-banner stale">⚠ ${msg} — check API connection or run /refresh</div>`;
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
      degraded: fresh.degraded,
      unavailable: !!lastFetchError && !state,
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
    config.onLoadingChange = opts.onLoadingChange || config.onLoadingChange;
  }

  global.RuntimeManager = {
    getIstTradingDayKey,
    getIstYesterdayKey,
    init,
    start,
    stop,
    refresh,
    subscribe,
    registerPanel,
    getState,
    getNormalizedState,
    getMarketSnapshot,
    getCanonicalMetrics,
    getRuntimeStateFields,
    getActionPlan,
    getCache,
    getPanelState,
    getPanelHashes,
    getSnapshotHash,
    getHydrationDebug,
    getFreshnessState,
    panelChanged,
    formatTimestamp,
    isStale,
    timestampHtml,
    lifecycleMessage,
    formatAgeSeconds,
    getExportAge,
    getPanelBanner,
    unavailableBanner,
    invalidateCache,
    formatMetricDisplay,
    formatFreshnessDisplay,
    getJournalDayBadge,
    sortJournalEntries,
    getIstDateKey,
    freshnessTierLabel,
    isLoading: () => loading,
  };
})(window);
