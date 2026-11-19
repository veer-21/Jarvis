// ─── JARVIS desktop shell ────────────────────────────────────────────────────
// Starts the JARVIS backend as a private child process, shows the app window, lives in the
// system tray, and shuts the backend down when you quit.
import { app, BrowserWindow, globalShortcut, ipcMain, Tray, Menu, nativeImage, shell } from 'electron'
import path from 'path'
import fs from 'fs'
import net from 'net'
import crypto from 'crypto'
import { spawn, execFile } from 'child_process'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const isDev = process.env.NODE_ENV === 'development'
const API_PORT = 7799
const HOTKEY = process.env.JARVIS_HOTKEY || 'CommandOrControl+Shift+J'
// Per-launch secret shared only between this process, the backend it spawns and our own
// window (over IPC). Lets the app sign in without a PIN; web pages can never read it.
const LOCAL_TOKEN = crypto.randomBytes(32).toString('hex')

if (process.env.JARVIS_DISABLE_GPU === '1') app.disableHardwareAcceleration()

let mainWindow = null
let tray = null
let backend = null
let isQuitting = false
let shownTrayHint = false

// ─── Single instance ─────────────────────────────────────────────────────────
if (!app.requestSingleInstanceLock()) {
  app.quit()
} else {
  app.on('second-instance', () => showWindow())
}

const iconPath = () => path.join(__dirname, '..', 'assets', 'icon.png')
const logsDir = () => path.join(app.getPath('userData'), 'logs')

// ─── Backend process ─────────────────────────────────────────────────────────
function backendCommand() {
  if (app.isPackaged) {
    const exe = path.join(process.resourcesPath, 'backend', 'jarvis-backend.exe')
    return { cmd: exe, args: [], cwd: path.dirname(exe) }
  }
  const root = path.resolve(__dirname, '..', '..')
  const py = process.platform === 'win32' ? path.join(root, 'venv', 'Scripts', 'python.exe') : path.join(root, 'venv', 'bin', 'python')
  return {
    cmd: fs.existsSync(py) ? py : 'python',
    args: ['-m', 'uvicorn', 'api.server:app', '--host', '127.0.0.1', '--port', String(API_PORT)],
    cwd: root,
  }
}

function portInUse(port) {
  return new Promise((resolve) => {
    const socket = net.connect(port, '127.0.0.1')
    socket.once('connect', () => {
      socket.destroy()
      resolve(true)
    })
    socket.once('error', () => resolve(false))
  })
}

async function startBackend() {
  if (await portInUse(API_PORT)) return 'external' // started outside the app (e.g. Start_Jarvis.bat): PIN login
  const { cmd, args, cwd } = backendCommand()
  fs.mkdirSync(logsDir(), { recursive: true })
  const log = fs.createWriteStream(path.join(logsDir(), 'backend.log'), { flags: 'a' })
  log.write(`\n=== ${new Date().toISOString()} starting backend ===\n`)
  backend = spawn(cmd, args, {
    cwd,
    env: { ...process.env, JARVIS_LOCAL_TOKEN: LOCAL_TOKEN, PYTHONUNBUFFERED: '1', PYTHONIOENCODING: 'utf-8' },
    windowsHide: true,
  })
  backend.stdout.pipe(log)
  backend.stderr.pipe(log)
  backend.on('error', (err) => log.write(`backend failed to start: ${err.message}\n`))
  backend.on('exit', (code) => {
    log.write(`backend exited with code ${code}\n`)
    backend = null
  })
  return 'spawned'
}

function stopBackend() {
  if (!backend) return
  const pid = backend.pid
  backend = null
  // Stop only our own backend process tree.
  if (process.platform === 'win32') execFile('taskkill', ['/PID', String(pid), '/T', '/F'], () => {})
  else process.kill(pid, 'SIGTERM')
}

// ─── Window ──────────────────────────────────────────────────────────────────
function isOwnPage(url) {
  return url.startsWith('file://') || (isDev && url.startsWith('http://localhost:3000'))
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 900,
    minHeight: 620,
    frame: false,
    transparent: true,
    show: false,
    icon: iconPath(),
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  })
  mainWindow.once('ready-to-show', () => mainWindow.show())

  if (isDev) mainWindow.loadURL('http://localhost:3000')
  else mainWindow.loadFile(path.join(__dirname, '..', 'dist', 'index.html'))

  // Links open in the user's browser, never inside the app window.
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https:\/\//.test(url)) shell.openExternal(url)
    return { action: 'deny' }
  })
  mainWindow.webContents.on('will-navigate', (event, url) => {
    if (!isOwnPage(url)) event.preventDefault()
  })

  // Closing hides to the tray; "Quit JARVIS" in the tray menu really exits.
  mainWindow.on('close', (event) => {
    if (isQuitting) return
    event.preventDefault()
    mainWindow.hide()
    if (!shownTrayHint && tray && process.platform === 'win32') {
      shownTrayHint = true
      tray.displayBalloon({
        iconType: 'info',
        title: 'JARVIS is still running',
        content: `Open it again from the tray icon or with ${HOTKEY.replace('CommandOrControl', 'Ctrl')}.`,
      })
    }
  })
}

function showWindow() {
  if (!mainWindow) return
  if (mainWindow.isMinimized()) mainWindow.restore()
  mainWindow.show()
  mainWindow.focus()
}

function toggleWindow() {
  if (!mainWindow) return
  if (mainWindow.isVisible() && mainWindow.isFocused()) mainWindow.hide()
  else showWindow()
}

function quitApp() {
  isQuitting = true
  app.quit()
}

function createTray() {
  tray = new Tray(nativeImage.createFromPath(iconPath()).resize({ width: 16, height: 16 }))
  tray.setToolTip('JARVIS')
  tray.setContextMenu(
    Menu.buildFromTemplate([
      { label: 'Open JARVIS', click: showWindow },
      { label: `Show / hide  (${HOTKEY.replace('CommandOrControl', 'Ctrl')})`, click: toggleWindow },
      { type: 'separator' },
      { label: 'Open logs folder', click: () => shell.openPath(logsDir()) },
      { label: 'Quit JARVIS', click: quitApp },
    ])
  )
  tray.on('click', toggleWindow)
}

function registerHotkey() {
  try {
    if (!globalShortcut.register(HOTKEY, toggleWindow)) console.warn(`Hotkey ${HOTKEY} is taken by another app.`)
  } catch (err) {
    console.warn(`Could not register hotkey ${HOTKEY}:`, err)
  }
}

async function setupAutoUpdate() {
  if (!app.isPackaged) return
  try {
    const { default: updater } = await import('electron-updater')
    updater.autoUpdater.checkForUpdatesAndNotify()
  } catch (err) {
    console.warn('Auto-update unavailable:', err.message)
  }
}

// ─── IPC (only for our own window) ───────────────────────────────────────────
function fromOwnWindow(event) {
  return mainWindow && event.sender === mainWindow.webContents && isOwnPage(event.senderFrame.url)
}

ipcMain.handle('jarvis:get-local-token', (event) => (fromOwnWindow(event) ? LOCAL_TOKEN : null))
ipcMain.handle('jarvis:open-external', (event, url) => {
  if (fromOwnWindow(event) && typeof url === 'string' && /^https:\/\//.test(url)) shell.openExternal(url)
})
ipcMain.handle('jarvis:open-logs', (event) => {
  if (fromOwnWindow(event)) shell.openPath(logsDir())
})
ipcMain.on('window-minimize', () => mainWindow?.minimize())
ipcMain.on('window-maximize', () => {
  if (!mainWindow) return
  if (mainWindow.isMaximized()) mainWindow.restore()
  else mainWindow.maximize()
})
ipcMain.on('window-close', () => mainWindow?.close())
ipcMain.on('app-quit', (event) => {
  if (fromOwnWindow(event)) quitApp()
})

// ─── Lifecycle ───────────────────────────────────────────────────────────────
app.whenReady().then(async () => {
  await startBackend()
  createWindow()
  createTray()
  registerHotkey()
  setupAutoUpdate()
})

app.on('before-quit', () => {
  isQuitting = true
  stopBackend()
})
app.on('window-all-closed', () => {
  /* keep running in the tray */
})
app.on('will-quit', () => globalShortcut.unregisterAll())
