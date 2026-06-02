const { app, BrowserWindow, session, shell } = require('electron')
const path = require('path')

function createWindow() {
  const win = new BrowserWindow({
    width: 1400,
    height: 900,
    title: 'AstraEdge AI',
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js'),
      webviewTag: true
    }
  })

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

app.on('web-contents-created', (_event, contents) => {
  if (contents.getType() === 'webview') {
    contents.setWindowOpenHandler(({ url }) => {
      shell.openExternal(url)
      return { action: 'deny' }
    })
  }
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})
