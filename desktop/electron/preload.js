const { contextBridge, ipcRenderer } = require('electron')

const api = {
  closeWindow: () => ipcRenderer.send('window-close'),
  minimizeWindow: () => ipcRenderer.send('window-minimize'),
  maximizeWindow: () => ipcRenderer.send('window-maximize'),
  close: () => ipcRenderer.send('window-close'),
  minimize: () => ipcRenderer.send('window-minimize'),
  maximize: () => ipcRenderer.send('window-maximize'),
}

// Expose safe APIs under both electron and electronAPI for complete backwards and forwards compatibility
contextBridge.exposeInMainWorld('electronAPI', api)
contextBridge.exposeInMainWorld('electron', api)
