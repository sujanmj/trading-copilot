/**

 * Full-screen workspace router — one active view at a time (Stage 19).

 * Workspaces: placeholder | browser | memory | budget | myfeed | brokers | aihub | router

 */

(function (global) {

  'use strict';



  let activeWorkspace = 'placeholder';

  let currentWebview = null;

  let currentExternalUrl = '';

  let currentBrowserLabel = '';

  let currentSourceKey = '';

  let config = {

    getApiBase: () => '',

    getHeaders: () => ({}),

  };



  const NAV_SOURCE_FROM_LABEL = {

    MC: 'MC',

    ET: 'ET',

    Mint: 'Mint',

    NDTV: 'NDTV',

    'ET Now': 'ET Now',

    CNBC: 'CNBC',

    NSE: 'NSE',

    Reddit: 'Reddit',

    Inshorts: 'Inshorts',

    Angel: 'Angel',

    Zerodha: 'Zerodha',

    Groww: 'Groww',

    Upstox: 'Upstox',

    IndMoney: 'IndMoney',

    Portfolio: 'Portfolio',

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



  function resolveSourceKey(btn, label) {

    if (btn && btn.dataset && btn.dataset.source) {

      return String(btn.dataset.source).trim();

    }

    const text = (label || (btn && btn.textContent) || '').trim();

    const stripped = text.replace(/^[^\w]+/, '').trim();

    if (NAV_SOURCE_FROM_LABEL[stripped]) return NAV_SOURCE_FROM_LABEL[stripped];

    if (stripped.includes('Portfolio')) return 'Portfolio';

    if (stripped.includes('Inshorts')) return 'Inshorts';

    if (stripped.includes('Reddit')) return 'Reddit';

    return stripped || 'ET';

  }



  function setMemoryViewClass(active) {

    const main = $('mainWorkspace');

    if (main) main.classList.toggle('memory-view-active', !!active);

  }



  function clearNavActive() {

    document.querySelectorAll('.broker-btn, .news-btn, .primary-nav-btn, .memory-nav-btn, .workspace-nav-btn, .router-nav-btn').forEach((b) => {

      b.classList.remove('active');

    });

  }



  function mountFreshnessForWorkspace(ws) {

    if (!global.SourceFreshnessCard) return;

    SourceFreshnessCard.unmount('#sourceFreshnessCardHost');

    SourceFreshnessCard.unmount('#aiHubFreshnessHost');

    SourceFreshnessCard.unmount('#routerFreshnessHost');

    if (ws === 'router') {

      SourceFreshnessCard.mount('#routerFreshnessHost').catch(() => null);

    }

  }



  function setActiveWorkspace(ws, opts) {

    const options = opts || {};

    const next = ws || 'placeholder';

    activeWorkspace = next;



    const main = $('mainWorkspace');

    if (main) main.dataset.workspace = next;



    setMemoryViewClass(next === 'memory');



    const browserWs = $('browserWorkspace');

    const memoryWs = $('memoryMainPanel');

    const budgetWs = $('budgetMainPanel');

    const myFeedWs = $('myFeedMainPanel');

    const brokersWs = $('brokersMainPanel');

    const aihubWs = $('aiHubWorkspace');

    const routerWs = $('routerMainPanel');

    const toolbar = $('browserToolbar');

    const placeholder = $('placeholder');



    if (browserWs) browserWs.style.display = (next === 'browser' || next === 'placeholder') ? '' : 'none';

    if (memoryWs) memoryWs.style.display = next === 'memory' ? '' : 'none';

    if (budgetWs) budgetWs.style.display = next === 'budget' ? '' : 'none';

    if (myFeedWs) myFeedWs.style.display = next === 'myfeed' ? '' : 'none';

    if (brokersWs) brokersWs.style.display = next === 'brokers' ? '' : 'none';

    if (aihubWs) aihubWs.style.display = next === 'aihub' ? '' : 'none';

    if (routerWs) routerWs.style.display = next === 'router' ? '' : 'none';



    if (toolbar) toolbar.style.display = (next === 'browser') ? 'flex' : 'none';

    if (placeholder) placeholder.style.display = next === 'placeholder' ? 'flex' : 'none';



    if (next === 'placeholder' && global.SourceFeedViewer && SourceFeedViewer.hide) {

      SourceFeedViewer.hide();

      currentSourceKey = '';

      currentExternalUrl = '';

      currentBrowserLabel = '';

    }



    if (next === 'browser' && currentWebview) {

      currentWebview.style.display = '';

    } else if (currentWebview) {

      currentWebview.style.display = 'none';

    }



    if (next === 'memory') {

      const memPanel = $('memoryMainPanel');

      if (memPanel) memPanel.style.display = 'block';

      if (global.MarketMemoryPanel && MarketMemoryPanel.loadMain) {

        MarketMemoryPanel.loadMain();

      }

    } else {

      const memPanel = $('memoryMainPanel');

      if (memPanel) memPanel.style.display = 'none';

    }



    if (next === 'budget') {

      const budgetPanel = $('budgetMainPanel');

      if (budgetPanel) budgetPanel.style.display = 'block';

      if (global.BudgetImpactPanel && BudgetImpactPanel.loadMain) {

        BudgetImpactPanel.loadMain();

      }

    } else {

      const budgetPanel = $('budgetMainPanel');

      if (budgetPanel) budgetPanel.style.display = 'none';

    }



    if (next === 'myfeed') {

      const myFeedPanel = $('myFeedMainPanel');

      if (myFeedPanel) myFeedPanel.style.display = 'block';

      if (global.loadMyFeedMain) {

        global.loadMyFeedMain();

      }

    } else {

      const myFeedPanel = $('myFeedMainPanel');

      if (myFeedPanel) myFeedPanel.style.display = 'none';

    }



    if (next === 'brokers') {

      const brokersPanel = $('brokersMainPanel');

      if (brokersPanel) brokersPanel.style.display = 'block';

      if (global.BrokerIntelligencePanel && BrokerIntelligencePanel.loadMain) {

        BrokerIntelligencePanel.loadMain();

      }

    } else {

      const brokersPanel = $('brokersMainPanel');

      if (brokersPanel) brokersPanel.style.display = 'none';

    }



    if (next === 'aihub') {

      if (global.renderAllTabs) {

        try { renderAllTabs({ force: false }); } catch (e) { /* boot order */ }

      }

      if (global.MarketRouterCard && MarketRouterCard.mountCompact) {

        MarketRouterCard.mountCompact('#aiHubRouterStatusHost').catch(() => null);

      }

    }



    if (next === 'router') {

      if (global.MarketRouterCard && MarketRouterCard.mount) {

        MarketRouterCard.mount('#marketRouterCardHost', null, { force: false }).catch(() => null);

      }

    }



    if (!options.skipFreshness) {

      mountFreshnessForWorkspace(next);

    }



    if (!options.skipNav) clearNavActive();

    if (options.navBtn) options.navBtn.classList.add('active');

  }



  function updateBrowserLabel(label) {

    currentBrowserLabel = label || '';

    const el = $('browserSourceLabel');

    if (el) el.textContent = currentBrowserLabel;

  }



  function isBrowserGui() {

    return !!(global.__GUI_RUNTIME__ && global.__GUI_RUNTIME__.isBrowser);

  }



  function clearBrowserEmbed(panel) {

    if (currentWebview) {

      if (currentWebview.remove) currentWebview.remove();

      currentWebview = null;

    }

    if (panel) {

      panel.querySelectorAll('webview, iframe.browser-embed').forEach((el) => el.remove());

    }

    if (global.SourceFeedViewer && SourceFeedViewer.hide) {

      SourceFeedViewer.hide();

    }

  }



  function showSourceFeedViewer(panel, placeholder, url, label, sourceKey) {

    clearBrowserEmbed(panel);

    if (placeholder) placeholder.style.display = 'none';

    currentExternalUrl = url || '';

    currentSourceKey = sourceKey || '';

    updateBrowserLabel(label || sourceKey || url);



    const loadingBar = $('loadingBar');

    if (loadingBar) loadingBar.classList.remove('active');



    if (global.SourceFeedViewer && SourceFeedViewer.show) {

      SourceFeedViewer.show(sourceKey, url, label || sourceKey).catch(() => null);

    }

  }



  function openSourceFeed(sourceKey, url, btn, label) {

    const key = (sourceKey || resolveSourceKey(btn, label)).trim();

    if (!key) return;



    if (global.DropdownMenu && DropdownMenu.closeAll) {

      DropdownMenu.closeAll();

    } else {

      const menu = btn && btn.closest('.brokers-menu, .news-menu');

      if (menu) menu.open = false;

    }



    setActiveWorkspace('browser', { navBtn: btn, skipFreshness: false });



    const panel = $('brokerPanel');

    const placeholder = $('placeholder');

    showSourceFeedViewer(panel, placeholder, url, label || key, key);

  }



  function openBrowser(url, btn, label) {

    if (!url) return;



    const sourceKey = resolveSourceKey(btn, label);

    setActiveWorkspace('browser', { navBtn: btn, skipFreshness: false });



    const panel = $('brokerPanel');

    const placeholder = $('placeholder');

    if (placeholder) placeholder.style.display = 'none';



    currentExternalUrl = url;

    updateBrowserLabel(label || sourceKey || url);



    const loadingBar = $('loadingBar');



    if (isBrowserGui()) {

      showSourceFeedViewer(panel, placeholder, url, label, sourceKey);

      return;

    }



    clearBrowserEmbed(panel);



    const wv = document.createElement('webview');

    wv.src = url;

    wv.style.cssText = 'position:absolute;top:0;left:0;width:100%;height:100%;border:none;';

    wv.setAttribute('partition', 'persist:broker');

    wv.setAttribute('allowpopups', 'true');

    if (panel) {

      panel.style.position = 'relative';

      panel.appendChild(wv);

    }

    currentWebview = wv;



    if (loadingBar) {

      loadingBar.classList.add('active');

      loadingBar.textContent = `⏳ Loading ${url}...`;

      wv.addEventListener('did-finish-load', () => loadingBar.classList.remove('active'));

      wv.addEventListener('did-fail-load', () => {

        showSourceFeedViewer(panel, placeholder, url, label, sourceKey);

      });

    }

  }



  function bindBrowserToolbar() {

    safeToolbarBind('browserBack', () => {

      if (currentWebview && currentWebview.canGoBack && currentWebview.canGoBack()) {

        currentWebview.goBack();

      }

    });

    safeToolbarBind('browserForward', () => {

      if (currentWebview && currentWebview.canGoForward && currentWebview.canGoForward()) {

        currentWebview.goForward();

      }

    });

    safeToolbarBind('browserReload', () => {

      if (isBrowserGui()) {

        if (currentSourceKey && global.SourceFeedViewer && SourceFeedViewer.load) {

          SourceFeedViewer.load(currentSourceKey, currentExternalUrl, currentBrowserLabel).catch(() => null);

        }

        return;

      }

      if (!currentWebview) return;

      if (currentWebview.reload) currentWebview.reload();

    });

    safeToolbarBind('browserExternal', () => {

      if (currentExternalUrl) {

        window.open(currentExternalUrl, '_blank', 'noopener,noreferrer');

        return;

      }

      if (!currentWebview || !currentWebview.getURL) return;

      try {

        const { shell } = require('electron');

        shell.openExternal(currentWebview.getURL());

      } catch (e) {

        window.open(currentWebview.src, '_blank');

      }

    });

  }



  function safeToolbarBind(id, handler) {

    const el = $(id);

    if (el) el.addEventListener('click', handler);

  }



  function wireNavButtons() {

    const topbar = document.querySelector('.topbar');

    if (topbar) {

      topbar.addEventListener('click', (ev) => {

        const brokerBtn = ev.target.closest('.broker-btn');

        if (brokerBtn) {

          ev.preventDefault();

          ev.stopPropagation();

          openSourceFeed(

            brokerBtn.dataset.source,

            brokerBtn.dataset.url,

            brokerBtn,

            (brokerBtn.textContent || '').trim(),

          );

          return;

        }

        const newsBtn = ev.target.closest('.news-btn');

        if (!newsBtn) return;

        ev.preventDefault();

        ev.stopPropagation();

        openSourceFeed(

          newsBtn.dataset.source,

          newsBtn.dataset.url,

          newsBtn,

          (newsBtn.textContent || '').trim(),

        );

      });

    }



    const memoryBtn = $('memoryNavBtn');

    if (memoryBtn) {

      memoryBtn.addEventListener('click', () => {

        setActiveWorkspace('memory', { navBtn: memoryBtn });

      });

    }



    const budgetBtn = $('budgetNavBtn');

    if (budgetBtn) {

      budgetBtn.addEventListener('click', () => {

        setActiveWorkspace('budget', { navBtn: budgetBtn });

      });

    }



    const myFeedBtn = $('myFeedNavBtn');

    if (myFeedBtn) {

      myFeedBtn.addEventListener('click', () => {

        setActiveWorkspace('myfeed', { navBtn: myFeedBtn });

      });

    }



    const brokersBtn = $('brokersNavBtn');

    if (brokersBtn) {

      brokersBtn.addEventListener('click', () => {

        setActiveWorkspace('brokers', { navBtn: brokersBtn });

      });

    }



    const aihubBtn = $('aiHubNavBtn');

    if (aihubBtn) {

      aihubBtn.addEventListener('click', () => {

        setActiveWorkspace('aihub', { navBtn: aihubBtn });

      });

    }



    const routerBtn = $('routerNavBtn');

    if (routerBtn) {

      routerBtn.addEventListener('click', () => {

        setActiveWorkspace('router', { navBtn: routerBtn });

      });

    }

  }



  function clearPersistedSourceViewState() {

    const keys = [

      'trading_copilot_source_view',

      'trading_copilot_browser_source',

      'trading_copilot_last_source',

      'trading_copilot_active_workspace',

      'tradingcopilot_source_viewer',

      'tradingcopilot_last_browser_source',

    ];

    try {

      keys.forEach((key) => {

        localStorage.removeItem(key);

        sessionStorage.removeItem(key);

      });

    } catch (e) { /* storage unavailable */ }

  }



  function init(opts) {

    config.getApiBase = (opts && opts.getApiBase) || config.getApiBase;

    config.getHeaders = (opts && opts.getHeaders) || config.getHeaders;

    clearPersistedSourceViewState();

    if (global.DropdownMenu && DropdownMenu.init) {

      DropdownMenu.init();

    }

    if (global.SourceFeedViewer && SourceFeedViewer.init) {

      SourceFeedViewer.init({

        getApiBase: config.getApiBase,

        getHeaders: config.getHeaders,

      });

    }

    if (global.document && global.document.body) {

      global.document.body.classList.toggle('gui-browser-mode', isBrowserGui());

      global.document.body.classList.toggle('gui-desktop-mode', !isBrowserGui());

    }

    bindBrowserToolbar();

    wireNavButtons();

    setActiveWorkspace('placeholder', { skipNav: true, skipFreshness: true });

  }



  function closeMemoryView() {

    if (activeWorkspace === 'memory') {

      setActiveWorkspace('placeholder', { skipNav: true });

    }

  }



  global.WorkspaceManager = {

    init,

    setActiveWorkspace,

    openBrowser,

    openSourceFeed,

    closeMemoryView,

    getActiveWorkspace: () => activeWorkspace,

    getWebview: () => currentWebview,

  };



  global.activeWorkspace = activeWorkspace;

  Object.defineProperty(global, 'activeWorkspace', {

    get() { return activeWorkspace; },

    configurable: true,

  });

})(typeof window !== 'undefined' ? window : global);

