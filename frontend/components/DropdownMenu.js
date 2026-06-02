/**
 * BROKERS / NEWS dropdown — click-outside, Escape, single-open (Stage 44J).
 */
(function (global) {
  'use strict';

  const MENU_SELECTOR = '.brokers-menu, .news-menu';

  function allMenus() {
    return Array.from(document.querySelectorAll(MENU_SELECTOR));
  }

  function closeAll() {
    allMenus().forEach((menu) => {
      menu.open = false;
    });
  }

  function closeOthers(exceptMenu) {
    allMenus().forEach((menu) => {
      if (menu !== exceptMenu) menu.open = false;
    });
  }

  function init() {
    allMenus().forEach((menu) => {
      menu.addEventListener('toggle', () => {
        if (menu.open) closeOthers(menu);
      });
      const panel = menu.querySelector('.brokers-menu-panel, .news-menu-panel');
      if (panel) {
        panel.addEventListener('click', (ev) => {
          ev.stopPropagation();
        });
      }
    });

    document.addEventListener('click', (ev) => {
      if (ev.target.closest(MENU_SELECTOR)) return;
      closeAll();
    });

    document.addEventListener('keydown', (ev) => {
      if (ev.key === 'Escape') closeAll();
    });
  }

  global.DropdownMenu = {
    init,
    closeAll,
  };
})(typeof window !== 'undefined' ? window : global);
