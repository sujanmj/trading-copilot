const { contextBridge, shell } = require('electron')
const path = require('path')

try {
  require('dotenv').config({ path: path.join(__dirname, '..', 'config', 'keys.env') })
} catch (e) {
  /* keys.env optional for local GUI */
}

contextBridge.exposeInMainWorld('electronAPI', {
  isElectron: true,
  openExternal: (url) => {
    if (url) shell.openExternal(String(url))
  },
  env: {
    API_BASE_URL: process.env.API_BASE_URL || '',
    API_KEY: process.env.API_KEY || '',
  },
})
