import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { Settings, X, CheckCircle2, AlertCircle, Download, Trash2 } from 'lucide-react'
import { api, apiBase } from '../api'
import ProviderSetup, { PROVIDERS } from './ProviderSetup'

function Section({ title, children }) {
  return (
    <section className="flex flex-col gap-3 border-t border-white/10 pt-4">
      <h3 className="text-[11px] uppercase tracking-wider font-mono text-cyan-400">{title}</h3>
      {children}
    </section>
  )
}

function PinSection({ token }) {
  const [pin, setPin] = useState('')
  const [confirm, setConfirm] = useState('')
  const [msg, setMsg] = useState('')
  const save = async () => {
    try {
      await api('/auth/set-pin', { method: 'POST', token, body: { new_pin: pin, confirm_pin: confirm } })
      setPin('')
      setConfirm('')
      setMsg('PIN saved. Browsers will need it to unlock JARVIS; the desktop app signs in automatically.')
    } catch (e) {
      setMsg(e.message)
    }
  }
  return (
    <Section title="App lock PIN">
      <p className="text-[11px] text-gray-500">Protects the browser version of JARVIS on this PC. At least 4 characters.</p>
      <div className="flex gap-2">
        {[
          [pin, setPin, 'New PIN'],
          [confirm, setConfirm, 'Repeat PIN'],
        ].map(([value, setter, label]) => (
          <input
            key={label}
            type="password"
            value={value}
            onChange={(e) => setter(e.target.value)}
            placeholder={label}
            aria-label={label}
            className="flex-1 bg-black/50 border border-white/10 rounded-xl px-3 py-2 text-xs focus:outline-none focus:border-cyan-400/60"
          />
        ))}
        <button onClick={save} disabled={pin.length < 4} className="px-4 py-2 rounded-xl bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 text-xs disabled:opacity-40">
          Save
        </button>
      </div>
      {msg && <p className="text-[11px] text-gray-300">{msg}</p>}
    </Section>
  )
}

/** Settings: AI providers, saved permissions, privacy and diagnostics. */
export default function SettingsPanel({ isOpen, token, onClose }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [providerId, setProviderId] = useState('gemini')
  const [exporting, setExporting] = useState(false)

  const load = async () => {
    try {
      setData(await api('/settings', { token }))
      setError('')
    } catch (e) {
      setError(e.message)
    }
  }

  useEffect(() => {
    if (isOpen) load()
  }, [isOpen])

  const update = async (changes) => {
    try {
      await api('/settings', { method: 'PUT', token, body: changes })
      await load()
    } catch (e) {
      setError(e.message)
    }
  }

  const exportDiagnostics = async () => {
    setExporting(true)
    try {
      const res = await fetch(apiBase() + '/diagnostics/export', { headers: { Authorization: `Bearer ${token}` } })
      if (!res.ok) throw new Error(`Export failed (${res.status})`)
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `jarvis-diagnostics-${new Date().toISOString().slice(0, 10)}.zip`
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      setError(e.message)
    } finally {
      setExporting(false)
    }
  }

  if (!isOpen) return null
  const settings = data?.settings || {}
  const configured = data?.secrets_configured || {}
  const health = data?.provider_health?.providers || {}
  const allowed = settings.always_allow_tools || []

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-6 bg-black/70 backdrop-blur-xl" style={{ WebkitAppRegion: 'no-drag' }}>
      <motion.div
        initial={{ opacity: 0, scale: 0.97 }}
        animate={{ opacity: 1, scale: 1 }}
        className="w-full max-w-2xl max-h-[90vh] overflow-y-auto bg-zinc-950/95 border border-white/10 rounded-3xl p-8 text-white flex flex-col gap-5"
        role="dialog"
        aria-label="Settings"
      >
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold flex items-center gap-2">
            <Settings size={18} className="text-cyan-400" /> Settings
          </h2>
          <button onClick={onClose} className="text-gray-400 hover:text-white" title="Close settings">
            <X size={18} />
          </button>
        </div>
        {error && <p className="text-xs text-amber-300">{error}</p>}

        <Section title="AI providers">
          <div className="flex flex-wrap gap-2">
            {PROVIDERS.map((p) => {
              const h = health[p.id]
              const isSet = p.secret ? configured[p.secret] : true
              return (
                <button
                  key={p.id}
                  onClick={() => setProviderId(p.id)}
                  className={`px-3 py-1.5 rounded-xl border text-xs flex items-center gap-1 ${
                    providerId === p.id ? 'border-cyan-400/60 bg-cyan-500/10' : 'border-white/10 bg-white/5 text-gray-300'
                  }`}
                >
                  {p.name}
                  {p.secret && isSet && (h && !h.available ? <AlertCircle size={12} className="text-amber-300" /> : <CheckCircle2 size={12} className="text-emerald-400" />)}
                </button>
              )
            })}
          </div>
          <ProviderSetup
            token={token}
            providerId={providerId}
            configured={configured[PROVIDERS.find((p) => p.id === providerId)?.secret]}
            onSaved={load}
          />
          <label className="flex items-center justify-between text-xs text-gray-300">
            Main AI
            <select
              value={settings.primary_engine || 'gemini'}
              onChange={(e) => update({ primary_engine: e.target.value })}
              className="bg-black/50 border border-white/10 rounded-lg px-2 py-1 text-xs"
            >
              <option value="gemini">Google Gemini</option>
              <option value="groq">Groq</option>
            </select>
          </label>
          <p className="text-[11px] text-gray-500">
            If the main AI is unavailable, JARVIS automatically uses the others you configured, then local Ollama. Model changes apply after a restart.
          </p>
        </Section>

        <Section title="Saved permissions">
          {allowed.length === 0 ? (
            <p className="text-xs text-gray-500">No actions are pre-approved. JARVIS asks every time.</p>
          ) : (
            allowed.map((tool) => (
              <div key={tool} className="flex items-center justify-between text-xs bg-white/5 rounded-xl px-3 py-2">
                <span className="font-mono">{tool}</span>
                <button
                  onClick={() => update({ always_allow_tools: allowed.filter((t) => t !== tool) })}
                  className="text-gray-400 hover:text-red-400 flex items-center gap-1"
                >
                  <Trash2 size={12} /> Ask again
                </button>
              </div>
            ))
          )}
        </Section>

        <Section title="Voice">
          <label className="flex items-center justify-between text-xs text-gray-300">
            Spoken replies voice
            <select
              value={settings.voice_engine || 'sapi'}
              onChange={(e) => update({ voice_engine: e.target.value })}
              className="bg-black/50 border border-white/10 rounded-lg px-2 py-1 text-xs"
            >
              <option value="sapi">Windows voice (offline, private)</option>
              <option value="edge-tts">Microsoft Edge neural voice (online)</option>
            </select>
          </label>
          <label className="flex items-center justify-between text-xs text-gray-300 cursor-pointer">
            Use Google speech recognition when offline recognition isn&apos;t installed (sends audio to Google)
            <input
              type="checkbox"
              checked={!!settings.cloud_speech_fallback}
              onChange={(e) => update({ cloud_speech_fallback: e.target.checked })}
            />
          </label>
          <p className="text-[11px] text-gray-500">Voice changes apply after a restart. Hold F9 to talk when no wake-word key is set.</p>
        </Section>

        <PinSection token={token} />

        <Section title="Privacy & support">
          <label className="flex items-center justify-between text-xs text-gray-300 cursor-pointer">
            Send anonymous crash reports (off by default)
            <input
              type="checkbox"
              checked={!!settings.crash_reports_enabled}
              onChange={(e) => update({ crash_reports_enabled: e.target.checked })}
            />
          </label>
          <button
            onClick={exportDiagnostics}
            disabled={exporting}
            className="self-start px-4 py-2 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 text-xs flex items-center gap-1.5"
          >
            <Download size={13} /> {exporting ? 'Preparing…' : 'Export diagnostics (no keys or messages)'}
          </button>
        </Section>
      </motion.div>
    </div>
  )
}
