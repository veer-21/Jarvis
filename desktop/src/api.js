// ─── JARVIS backend client ───────────────────────────────────────────────────
// One place for the backend address, authentication and the live WebSocket.
// In the desktop app the Electron preload injects `window.jarvis` (backend URL and a
// per-launch local token); in a browser the UI is served by the backend itself.

const DEFAULT_BASE = 'http://127.0.0.1:7799'

export function apiBase() {
  const injected = typeof window !== 'undefined' && window.jarvis && window.jarvis.apiBase
  if (injected) return injected
  // Served by the JARVIS backend itself (any port except the Vite dev server's 3000)
  if (typeof window !== 'undefined' && window.location.protocol.startsWith('http') && window.location.port !== '3000') {
    return window.location.origin
  }
  return DEFAULT_BASE
}

export function isDesktopApp() {
  return typeof window !== 'undefined' && !!window.jarvis
}

export class ApiError extends Error {
  constructor(status, message) {
    super(message)
    this.status = status
  }
}

function errorText(data, fallback) {
  if (!data) return fallback
  if (typeof data.detail === 'string') return data.detail
  if (Array.isArray(data.detail)) return data.detail.map((d) => d.msg || JSON.stringify(d)).join('; ')
  return data.message || fallback
}

export async function api(path, { method = 'GET', body, token, signal } = {}) {
  const headers = {}
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (token) headers['Authorization'] = `Bearer ${token}`
  let res
  try {
    res = await fetch(apiBase() + path, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal,
    })
  } catch (e) {
    throw new ApiError(0, 'JARVIS is not reachable. It may still be starting up.')
  }
  let data = null
  try {
    data = await res.json()
  } catch {
    data = null
  }
  if (!res.ok) throw new ApiError(res.status, errorText(data, res.statusText))
  return data
}

export async function isBackendUp() {
  try {
    const res = await fetch(apiBase() + '/health')
    return res.ok
  } catch {
    return false
  }
}

/** Poll /health until the backend answers (it can take a while on first start). */
export async function waitForBackend({ timeoutMs = 90000, intervalMs = 1000, onTick } = {}) {
  const started = Date.now()
  while (Date.now() - started < timeoutMs) {
    if (await isBackendUp()) return true
    if (onTick) onTick(Math.round((Date.now() - started) / 1000))
    await new Promise((r) => setTimeout(r, intervalMs))
  }
  return false
}

/** Desktop app: log in with the per-launch secret shared by Electron (no PIN needed). */
export async function loginWithLocalToken() {
  if (!window.jarvis || typeof window.jarvis.getLocalToken !== 'function') return null
  const secret = await window.jarvis.getLocalToken()
  if (!secret) return null
  try {
    const data = await api('/auth/local', { method: 'POST', body: { token: secret } })
    return data.access_token
  } catch {
    return null // backend was started outside the app (e.g. Start_Jarvis.bat): fall back to PIN
  }
}

export async function loginWithPin(pin) {
  const data = await api('/auth/login', { method: 'POST', body: { pin } })
  return data.access_token
}

/**
 * Live connection to the assistant. Reconnects with exponential backoff and
 * re-authenticates after every reconnect.
 */
export function createSocket({ getToken, onMessage, onStatusChange }) {
  let ws = null
  let closed = false
  let attempt = 0
  let timer = null

  const connect = () => {
    ws = new WebSocket(apiBase().replace(/^http/, 'ws') + '/ws/jarvis')
    ws.onopen = () => {
      attempt = 0
      onStatusChange('ONLINE')
      const t = getToken()
      if (t) ws.send(JSON.stringify({ command: 'auth', token: t }))
    }
    ws.onmessage = (event) => {
      try {
        onMessage(JSON.parse(event.data))
      } catch {
        /* ignore malformed frames */
      }
    }
    ws.onclose = () => {
      onStatusChange('OFFLINE')
      if (closed) return
      const delay = Math.min(1000 * 2 ** attempt, 15000)
      attempt += 1
      timer = setTimeout(connect, delay)
    }
    ws.onerror = () => {
      try {
        ws.close()
      } catch {
        /* already closed */
      }
    }
  }

  connect()

  return {
    send(payload) {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ ...payload, token: getToken() }))
        return true
      }
      return false
    },
    close() {
      closed = true
      clearTimeout(timer)
      if (ws) ws.close()
    },
  }
}
