/**
 * Headless startup smoke test — run with Electron to capture renderer console.
 * Usage: $env:API_BASE_URL='http://127.0.0.1:8000'; npx electron smoke-test.js
 */
const { app, BrowserWindow } = require('electron')
const path = require('path')

app.whenReady().then(() => {
  const win = new BrowserWindow({
    show: false,
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false,
      webviewTag: true,
      webSecurity: false,
    },
  })

  win.webContents.on('console-message', (_e, level, message, line, sourceId) => {
    console.log(`[console:${level}] ${message} (${sourceId}:${line})`)
  })

  win.webContents.on('did-fail-load', (_e, code, desc) => {
    console.error('[did-fail-load]', code, desc)
    app.exit(1)
  })

  win.loadFile(path.join(__dirname, 'index.html'))

  setTimeout(async () => {
    try {
      const report = await win.webContents.executeJavaScript(`(() => {
        const tabs = document.querySelectorAll('.tab')
        const govTab = document.querySelector('.tab[data-tab="govt"]')
        const brainBefore = document.getElementById('tab-brain')?.innerText?.slice(0, 160) || ''
        let tabSwitchOk = false
        if (govTab) {
          govTab.click()
          tabSwitchOk = document.querySelector('.tab.active')?.dataset?.tab === 'govt'
            && document.getElementById('tab-govt')?.classList.contains('active')
        }
        const askBtn = document.getElementById('askBtn')
        const askClickable = askBtn && !askBtn.disabled
        const brokerBtn = document.querySelector('.broker-btn')
        const errors = window.__startupErrors || []
        const syntaxErrors = errors.filter(e => /SyntaxError|Unexpected identifier/.test(e.message || ''))
        return {
          tabCount: tabs.length,
          tabSwitchOk,
          brainBefore,
          brainLoading: /Loading|Waiting/i.test(brainBefore),
          connected: window.apiCache?.connected,
          hasRuntime: !!window.RuntimeManager?.getState(),
          runtimeStatus: window.RuntimeManager?.getState()?.status || null,
          askClickable,
          brokerBtnCount: document.querySelectorAll('.broker-btn').length,
          syntaxErrors,
          errors,
        }
      })()`)
      console.log('[SMOKE REPORT]', JSON.stringify(report, null, 2))
      const ok = report.tabCount > 0
        && report.tabSwitchOk
        && report.hasRuntime
        && report.syntaxErrors.length === 0
        && report.askClickable
      app.exit(ok ? 0 : 2)
    } catch (e) {
      console.error('[SMOKE FAILED]', e)
      app.exit(3)
    }
  }, 10000)
})
