import { app, BrowserWindow, globalShortcut, ipcMain } from 'electron'
import path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

app.commandLine.appendSwitch('disable-gpu');
app.commandLine.appendSwitch('disable-gpu-compositing');
app.commandLine.appendSwitch('disable-gpu-rasterization');
app.disableHardwareAcceleration();

let mainWindow

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    frame: false, // Frameless window for the floating look
    transparent: true, // Transparent background for glassmorphism
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
    },
  })

  // In development, load from the Vite dev server
  if (process.env.NODE_ENV === 'development') {
    mainWindow.loadURL('http://localhost:3000')
    // mainWindow.webContents.openDevTools()
  } else {
    // In production, load the built index.html
    mainWindow.loadFile(path.join(__dirname, '../dist/index.html'))
  }

  // Hide instead of close to keep JARVIS running in background
  mainWindow.on('close', (event) => {
    if (!app.isQuiting) {
      event.preventDefault()
      mainWindow.hide()
    }
  })
}

app.whenReady().then(() => {
  createWindow()

  // Register window control IPC listeners for frontend React interactions
  ipcMain.on('window-close', () => {
    if (mainWindow) {
      // Triggers window close event, which will be intercepted to hide it
      mainWindow.close()
    }
  })

  ipcMain.on('window-minimize', () => {
    if (mainWindow) {
      mainWindow.minimize()
    }
  })

  ipcMain.on('window-maximize', () => {
    if (mainWindow) {
      if (mainWindow.isMaximized()) {
        mainWindow.restore()
      } else {
        mainWindow.maximize()
      }
    }
  })

  const toggleJarvisWindow = () => {
    if (!mainWindow) return
    if (mainWindow.isVisible()) {
      mainWindow.hide()
    } else {
      mainWindow.show()
      mainWindow.focus()
    }
  }

  // Global shortcut to toggle JARVIS window instantly: Alt+Space and fallback CommandOrControl+Shift+J
  try {
    const okAltSpace = globalShortcut.register('Alt+Space', toggleJarvisWindow)
    if (!okAltSpace) {
      console.warn('Alt+Space global shortcut registration failed, falling back to CommandOrControl+Shift+J.')
    }
  } catch (err) {
    console.warn('Could not register Alt+Space global shortcut:', err)
  }

  try {
    globalShortcut.register('CommandOrControl+Shift+J', toggleJarvisWindow)
  } catch (err) {
    console.warn('Could not register CommandOrControl+Shift+J global shortcut:', err)
  }

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})

app.on('will-quit', () => {
  globalShortcut.unregisterAll()
})
