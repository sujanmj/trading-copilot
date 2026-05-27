/**
 * snapshotAdapter — normalize backend /api/runtime/snapshot payloads into a stable
 * frontend schema. Components should consume normalized snapshots only.
 */
(function (global) {
  'use strict';

  const LOG_PREFIX = '[SnapshotAdapter]';

  function isObject(v) {
    return v != null && typeof v === 'object' && !Array.isArray(v);
  }

  function unwrapExport(cached) {
    if (cached == null) return null;
    if (isObject(cached) && cached.error && cached.data == null
      && !cached.metrics_all_time && !cached.predictions && !cached.intelligence_journal) {
      return null;
    }
    if (isObject(cached) && cached.data !== undefined) return cached.data;
    return cached;
  }

  function asArray(v) {
    return Array.isArray(v) ? v : [];
  }

  function asString(v, fallback) {
    if (v == null || v === '') return fallback || '';
    const t = String(v).trim();
    if (!t || t.toLowerCase() === 'none' || t.toLowerCase() === 'unknown') return fallback || '';
    return t;
  }

  function normalizeBrain(intelRaw, ms, snap) {
    const intel = unwrapExport(intelRaw);
    const base = isObject(intel) ? intel : {};
    const moodSrc = base.market_mood || ms.market_mood || {};
    const rotation = base.sector_rotation || ms.sector_rotation || { bullish: [], bearish: [] };
    const opps = asArray(base.top_opportunities || base.opportunities || ms.top_opportunities);
    const risks = asArray(base.risks_and_avoids || base.risks || ms.risk_list);
    const summary = asString(base.executive_summary || base.analysis || ms.executive_summary, '');
    const actionPlan = asString(
      ms.action_plan || snap.action_plan || base.action_plan,
      ''
    );
    const selfCalibration = asString(base.self_calibration || ms.calibration, '');
    const hasContent = !!(summary || actionPlan || selfCalibration || opps.length || risks.length
      || asString(moodSrc.global_mood) || asString(moodSrc.india_outlook));

    return {
      available: hasContent || isObject(intel),
      summary: summary || 'No intelligence available',
      actionPlan: actionPlan || 'Awaiting next cycle',
      selfCalibration: selfCalibration || 'Unavailable',
      marketMood: {
        global_mood: asString(moodSrc.global_mood || base.market_bias, 'Confidence building'),
        india_outlook: asString(moodSrc.india_outlook, 'Confidence building'),
        retail_mood: asString(moodSrc.retail_mood, 'Awaiting evaluation sample'),
        confidence_level: asString(moodSrc.confidence_level || base.confidence_score, 'N/A'),
      },
      sectorRotation: {
        bullish: asArray(rotation.bullish),
        bearish: asArray(rotation.bearish),
      },
      topOpportunities: opps,
      risks,
      governmentImpact: isObject(base.government_impact) ? base.government_impact : {},
      sourcesTotal: base.sources_total != null ? base.sources_total : 8,
      sourcesUsed: base.sources_used,
    };
  }

  function normalizeExports(raw) {
    const exports = (raw && (raw.exports || raw.data)) || {};
    const ms = (raw && raw.market_snapshot) || {};
    return {
      intelligence: unwrapExport(exports.intelligence || ms.intelligence),
      india: unwrapExport(exports.india),
      markets: unwrapExport(exports.markets),
      news: unwrapExport(exports.news),
      youtube: unwrapExport(exports.youtube),
      govt: unwrapExport(exports.govt),
      inshorts: unwrapExport(exports.inshorts),
      reddit: unwrapExport(exports.reddit),
      scanner: unwrapExport(exports.scanner),
      stats: unwrapExport(exports.stats),
      history: unwrapExport(exports.history),
      activePredictions: unwrapExport(exports.active_predictions),
      predictionHistory: unwrapExport(exports.prediction_history),
      lifecycleState: unwrapExport(exports.lifecycle_state),
    };
  }

  function normalizeGlobal(raw) {
    const data = (raw && raw.data) || {};
    const overnightImpact = raw.overnight_impact || data.overnight_impact || {};
    const indiaNextOpen = raw.india_next_open || data.india_next_open
      || overnightImpact.india_next_open || {};
    const overnightTimeline = raw.overnight_timeline || data.overnight_timeline || {};
    const rs = ((raw && raw.market_snapshot) || {}).runtime_state || raw.runtime_state || {};
    const overnightPosture = rs.overnight_posture || {};
    const report = Object.keys(indiaNextOpen).length ? indiaNextOpen : overnightPosture;

    return {
      overnightImpact: isObject(overnightImpact) ? overnightImpact : {},
      indiaNextOpen: isObject(report) ? report : {},
      overnightTimeline: isObject(overnightTimeline) ? overnightTimeline : {},
      available: !!(Object.keys(report).length || Object.keys(overnightImpact).length),
    };
  }

  function normalizePanels(raw) {
    const panels = (raw && raw.panels) || {};
    const defaults = {
      brain: { status: 'waiting', message: 'Waiting for runtime snapshot…', stale: false },
      markets: { status: 'waiting', message: 'Waiting for market exports…', stale: false },
      global: { status: 'waiting', message: 'Waiting for overnight scan…', stale: false },
      journal: { status: 'waiting', message: 'Waiting for journal export…', stale: false },
      calibration: { status: 'waiting', message: 'Waiting for calibration…', stale: false },
      scanner: { status: 'waiting', message: 'Waiting for scanner…', stale: false },
      runtime: { status: 'waiting', message: 'Waiting for runtime…', stale: false },
      orchestrator: { status: 'waiting', message: 'Waiting for orchestrator…', stale: false },
    };
    const out = { ...defaults };
    Object.keys(defaults).forEach((key) => {
      if (isObject(panels[key])) out[key] = { ...defaults[key], ...panels[key] };
    });
    return out;
  }

  function detectStale(raw, ms) {
    const fresh = ms.freshness || {};
    const fs = (raw && raw.freshness_state) || {};
    const runtimePanel = ((raw && raw.panels) || {}).runtime || {};
    const rs = ms.runtime_state || raw.runtime_state || {};
    const flags = rs.secondary_flags || {};
    return !!(
      fresh.stale
      || fs.export_stale
      || flags.stale_snapshot
      || runtimePanel.stale
    );
  }

  function collectWarnings(raw, exportsNorm, brain) {
    const warnings = asArray(raw && raw.validation_warnings);
    const missing = [];
    if (!raw.snapshot_id && !raw.active_snapshot_id) missing.push('snapshot_id');
    if (!raw.generated_at && !(raw.market_snapshot || {}).generated_at) missing.push('generated_at');
    if (!brain.actionPlan || brain.actionPlan === 'Awaiting next cycle') missing.push('action_plan');
    if (!exportsNorm.intelligence) missing.push('intelligence');
    if (missing.length) {
      console.warn(LOG_PREFIX, 'payload shape mismatches:', missing.join(', '));
    }
    return { warnings, missingFields: missing };
  }

  /**
   * @param {object|null|undefined} raw - backend snapshot payload
   * @returns {object} stable frontend schema
   */
  function normalizeSnapshot(raw) {
    if (!isObject(raw)) {
      console.warn(LOG_PREFIX, 'invalid payload — using empty normalized snapshot');
      return {
        meta: {
          snapshotId: null,
          generatedAt: null,
          version: null,
          status: 'degraded',
          stale: true,
          warnings: ['invalid_payload'],
          missingFields: ['snapshot'],
        },
        brain: normalizeBrain(null, {}, {}),
        exports: normalizeExports(null),
        global: normalizeGlobal(null),
        marketSnapshot: {},
        panels: normalizePanels(null),
        actionPlan: '',
        calibrationSummary: {},
        operational: {},
        raw: null,
      };
    }

    const ms = isObject(raw.market_snapshot) ? raw.market_snapshot : {};
    const exportsNorm = normalizeExports(raw);
    const brain = normalizeBrain(exportsNorm.intelligence, ms, raw);
    const globalNorm = normalizeGlobal(raw);
    const shape = collectWarnings(raw, exportsNorm, brain);

    return {
      meta: {
        snapshotId: raw.snapshot_id || raw.active_snapshot_id || ms.snapshot_id || null,
        generatedAt: raw.generated_at || ms.generated_at || null,
        version: raw.snapshot_version != null ? raw.snapshot_version
          : ((ms.freshness || {}).snapshot_version ?? null),
        status: asString(raw.status, 'unknown'),
        stale: detectStale(raw, ms),
        warnings: shape.warnings,
        missingFields: shape.missingFields,
      },
      brain,
      exports: exportsNorm,
      global: globalNorm,
      marketSnapshot: ms,
      panels: normalizePanels(raw),
      actionPlan: brain.actionPlan,
      calibrationSummary: isObject(raw.calibration_summary) ? raw.calibration_summary : {},
      operational: isObject(raw.operational) ? raw.operational : {},
      raw,
    };
  }

  global.SnapshotAdapter = {
    normalizeSnapshot,
    unwrapExport,
  };
})(typeof window !== 'undefined' ? window : globalThis);
