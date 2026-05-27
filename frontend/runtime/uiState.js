/**
 * UiState — preserve expanded/collapsed UI across RuntimeManager refresh cycles.
 */
(function (global) {
  'use strict';

  const expanded = Object.create(null);
  let wired = false;

  function sectionKey(el) {
    const explicit = el.getAttribute('data-ui-section');
    if (explicit) return explicit;
    const summary = el.querySelector('summary');
    if (summary && summary.textContent) {
      return summary.textContent.trim().slice(0, 64);
    }
    return null;
  }

  function captureDetails(root) {
    const scope = root || document;
    scope.querySelectorAll('details').forEach((el) => {
      const key = sectionKey(el);
      if (key) expanded[key] = !!el.open;
    });
    return expanded;
  }

  function saveUiState(root) {
    return captureDetails(root);
  }

  function restoreUiState(root) {
    const scope = root || document;
    scope.querySelectorAll('details').forEach((el) => {
      const key = sectionKey(el);
      if (key && Object.prototype.hasOwnProperty.call(expanded, key)) {
        el.open = expanded[key];
      }
    });
  }

  function onDetailsToggle(ev) {
    const el = ev.target;
    if (!el || el.tagName !== 'DETAILS') return;
    const key = sectionKey(el);
    if (key) expanded[key] = !!el.open;
  }

  function persistExpandedSections(root) {
    captureDetails(root);
    if (wired) return;
    document.addEventListener('toggle', onDetailsToggle, true);
    wired = true;
  }

  global.UiState = {
    saveUiState,
    restoreUiState,
    persistExpandedSections,
    getExpanded: () => ({ ...expanded }),
  };
})(window);
