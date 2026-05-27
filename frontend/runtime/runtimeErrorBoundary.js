/**
 * RuntimeErrorBoundary — global frontend protection against hydration/render crashes.
 * Shows degraded fallback UI instead of freezing the app.
 */
(function (global) {
  'use strict';

  const LOG_PREFIX = '[RuntimeErrorBoundary]';
  let installed = false;
  let lastError = null;
  let errorCount = 0;

  function escapeHtml(text) {
    return String(text || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  function fallbackBannerHtml(message) {
    const msg = message || lastError || 'Runtime exception contained — degraded mode active.';
    return (
      '<div class="runtime-error-boundary" role="alert">' +
      '⚠ <strong>Runtime protected</strong> · ' + escapeHtml(msg) +
      '</div>'
    );
  }

  function showFallback(message) {
    lastError = message || lastError;
    errorCount += 1;
    console.error(LOG_PREFIX, 'fallback shown:', lastError);

    const banner = document.getElementById('runtimeDegradedBanner');
    if (banner) {
      banner.innerHTML = fallbackBannerHtml(lastError);
      banner.style.display = 'block';
    }

    const bar = document.getElementById('loadingBar');
    if (bar) bar.classList.remove('active');

    try {
      if (global.RuntimeManager && typeof global.RuntimeManager.forceFinishHydration === 'function') {
        global.RuntimeManager.forceFinishHydration(lastError || 'Runtime exception — degraded cache');
      }
    } catch (e) {
      console.error(LOG_PREFIX, 'forceFinishHydration failed', e);
    }
  }

  function runSafe(label, fn, fallbackFn) {
    try {
      return fn();
    } catch (e) {
      console.error(LOG_PREFIX, label, e);
      showFallback((e && e.message) || String(e));
      if (typeof fallbackFn === 'function') {
        try { return fallbackFn(e); } catch (e2) { console.error(LOG_PREFIX, label + ' fallback failed', e2); }
      }
      return null;
    }
  }

  async function runSafeAsync(label, fn, fallbackFn) {
    try {
      return await fn();
    } catch (e) {
      console.error(LOG_PREFIX, label, e);
      showFallback((e && e.message) || String(e));
      if (typeof fallbackFn === 'function') {
        try { return await fallbackFn(e); } catch (e2) { console.error(LOG_PREFIX, label + ' fallback failed', e2); }
      }
      return null;
    }
  }

  function install(opts) {
    if (installed) return;
    installed = true;
    opts = opts || {};

    global.addEventListener('error', (event) => {
      const msg = event.message || 'Unknown script error';
      console.error(LOG_PREFIX, 'window.error', msg, event.filename, event.lineno);
      showFallback(msg);
      if (typeof opts.onError === 'function') opts.onError(event);
    });

    global.addEventListener('unhandledrejection', (event) => {
      const reason = event.reason;
      const msg = reason && reason.message ? reason.message : String(reason || 'Unhandled promise rejection');
      console.error(LOG_PREFIX, 'unhandledrejection', msg);
      showFallback(msg);
      if (typeof opts.onError === 'function') opts.onError(event);
    });

    console.log(LOG_PREFIX, 'installed');
  }

  global.RuntimeErrorBoundary = {
    install,
    showFallback,
    runSafe,
    runSafeAsync,
    getLastError: () => lastError,
    getErrorCount: () => errorCount,
    fallbackBannerHtml,
  };
})(typeof window !== 'undefined' ? window : globalThis);
