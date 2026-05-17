const { app, BrowserWindow, session } = require('electron')
const path = require('path')

function createWindow() {
  const win = new BrowserWindow({
    width: 1400,
    height: 900,
    title: 'Trading Copilot',
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false,
      webviewTag: true,
      webSecurity: false
    }
  })

  // Allow webviews to load with proper headers
  session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
    if (details.responseHeaders) {
      delete details.responseHeaders['x-frame-options']
      delete details.responseHeaders['X-Frame-Options']
      delete details.responseHeaders['content-security-policy']
      delete details.responseHeaders['Content-Security-Policy']
    }
    callback({ responseHeaders: details.responseHeaders })
  })

  win.loadFile('index.html')
  win.maximize()
}

app.whenReady().then(() => {
  createWindow()
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})