// Runs in the sandboxed renderer before the app UI. Exposes a tiny, explicit API; the page
// gets no Node.js access.
const { contextBridge, ipcRenderer } = require('electron')

const windowControls = {
  minimize: () => ipcRenderer.send('window-minimize'),
  maximize: () => ipcRenderer.send('window-maximize'),
  close: () => ipcRenderer.send('window-close'), // hides to tray
  // legacy names used by older UI builds
  minimizeWindow: () => ipcRenderer.send('window-minimize'),
  maximizeWindow: () => ipcRenderer.send('window-maximize'),
  closeWindow: () => ipcRenderer.send('window-close'),
}

contextBridge.exposeInMainWorld('jarvis', {
  apiBase: 'http://127.0.0.1:7799',
  getLocalToken: () => ipcRenderer.invoke('jarvis:get-local-token'),
  openExternal: (url) => ipcRenderer.invoke('jarvis:open-external', url),
  openLogs: () => ipcRenderer.invoke('jarvis:open-logs'),
  quit: () => ipcRenderer.send('app-quit'),
  ...windowControls,
})
contextBridge.exposeInMainWorld('electronAPI', windowControls)
contextBridge.exposeInMainWorld('electron', windowControls)
