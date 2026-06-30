const { contextBridge, ipcRenderer } = require('electron')

// Expose safe APIs to the React renderer process
contextBridge.exposeInMainWorld('electronAPI', {
  // We can add window controls (minimize, close) here later
  closeWindow: () => ipcRenderer.send('window-close'),
  minimizeWindow: () => ipcRenderer.send('window-minimize'),
})
