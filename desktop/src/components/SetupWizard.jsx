import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { Wand2, ChevronRight, CheckCircle2, AlertCircle, RefreshCw, ShieldCheck } from 'lucide-react'
import { api } from '../api'
import ProviderSetup, { PROVIDERS } from './ProviderSetup'

const STEPS = ['About you', 'Choose your AI', 'Privacy & permissions', 'Ready check']

/** First-run setup: name, AI provider (with key test), privacy summary, readiness check. */
export default function SetupWizard({ isOpen, token, onClose, onFinish, voiceReplyEnabled, onVoiceReplyChange }) {
  const [step, setStep] = useState(0)
  const [userName, setUserName] = useState('')
  const [city, setCity] = useState('')
  const [providerId, setProviderId] = useState('gemini')
  const [configured, setConfigured] = useState({})
  const [diagnostics, setDiagnostics] = useState(null)
  const [loadingDiag, setLoadingDiag] = useState(false)
  const [saving, setSaving] = useState(false)

  const refreshSettings = () =>
    api('/settings', { token })
      .then((s) => setConfigured(s.secrets_configured || {}))
      .catch(() => {})

  const fetchDiagnostics = async () => {
    setLoadingDiag(true)
    try {
      setDiagnostics(await api('/onboarding/diagnostics', { token }))
    } catch {
      setDiagnostics(null)
    } finally {
      setLoadingDiag(false)
    }
  }

  useEffect(() => {
    if (isOpen) refreshSettings()
  }, [isOpen])

  useEffect(() => {
    if (isOpen && step === 3) fetchDiagnostics()
  }, [isOpen, step])

  const finish = async () => {
    setSaving(true)
    try {
      await api('/onboarding/configure', {
        method: 'POST',
        token,
        body: { user_name: userName || undefined, preferred_city: city || undefined },
      })
    } catch {
      /* name/city are optional */
    } finally {
      setSaving(false)
      onFinish(userName)
    }
  }

  if (!isOpen) return null
  const anyCloudKey = configured.GEMINI_API_KEY || configured.GROQ_API_KEY || configured.OPENAI_API_KEY

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-6 bg-black/80 backdrop-blur-xl" style={{ WebkitAppRegion: 'no-drag' }}>
      <motion.div
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        className="w-full max-w-xl bg-zinc-950/90 border border-cyan-500/30 rounded-3xl p-8 text-white flex flex-col gap-6"
        role="dialog"
        aria-label="JARVIS setup"
      >
        <div className="flex items-center justify-between border-b border-white/10 pb-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-2xl bg-cyan-500/20 border border-cyan-500/40 flex items-center justify-center text-cyan-400">
              <Wand2 size={20} />
            </div>
            <div>
              <h2 className="text-base font-semibold">Welcome to JARVIS</h2>
              <p className="text-xs text-gray-400">{STEPS[step]}</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-xs font-mono text-cyan-400">
              Step {step + 1} of {STEPS.length}
            </span>
            <button onClick={onClose} className="text-gray-400 hover:text-white p-1 rounded-lg text-sm" title="Close setup">
              ✕
            </button>
          </div>
        </div>

        {step === 0 && (
          <div className="flex flex-col gap-4">
            <p className="text-xs text-gray-300">What should JARVIS call you, and where are you? (Used for greetings, weather and briefings.)</p>
            <input
              type="text"
              placeholder="Your name"
              value={userName}
              onChange={(e) => setUserName(e.target.value)}
              className="bg-black/50 border border-white/10 rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-cyan-400/60"
            />
            <input
              type="text"
              placeholder="Your city (optional)"
              value={city}
              onChange={(e) => setCity(e.target.value)}
              className="bg-black/50 border border-white/10 rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-cyan-400/60"
            />
          </div>
        )}

        {step === 1 && (
          <div className="flex flex-col gap-4">
            <p className="text-xs text-gray-300">
              JARVIS needs an AI model to think. Pick one — you can add more later in Settings.
              {anyCloudKey ? ' A key is already configured, so you can also skip this step.' : ''}
            </p>
            <div className="grid grid-cols-2 gap-2">
              {PROVIDERS.map((p) => (
                <button
                  key={p.id}
                  onClick={() => setProviderId(p.id)}
                  className={`text-left p-3 rounded-xl border text-xs transition-colors ${
                    providerId === p.id ? 'border-cyan-400/60 bg-cyan-500/10 text-white' : 'border-white/10 bg-white/5 text-gray-300 hover:border-white/20'
                  }`}
                >
                  <span className="font-semibold flex items-center gap-1">
                    {p.name}
                    {p.secret && configured[p.secret] && <CheckCircle2 size={12} className="text-emerald-400" />}
                  </span>
                </button>
              ))}
            </div>
            <ProviderSetup
              token={token}
              providerId={providerId}
              configured={providerId !== 'ollama' && configured[PROVIDERS.find((p) => p.id === providerId)?.secret]}
              makePrimary
              onSaved={refreshSettings}
            />
          </div>
        )}

        {step === 2 && (
          <div className="flex flex-col gap-3 text-xs text-gray-200">
            <div className="flex items-start gap-2">
              <ShieldCheck size={16} className="text-emerald-400 shrink-0 mt-0.5" />
              <p>
                <b>Your data stays on this PC.</b> Memories, conversations, reminders and settings are stored in your Windows user folder. API keys are kept in Windows Credential Manager.
              </p>
            </div>
            <div className="flex items-start gap-2">
              <ShieldCheck size={16} className="text-emerald-400 shrink-0 mt-0.5" />
              <p>
                <b>What is sent to the AI provider:</b> your messages and the relevant memories needed to answer them. Nothing is sent to us — there is no telemetry unless you turn on crash reports in Settings.
              </p>
            </div>
            <div className="flex items-start gap-2">
              <ShieldCheck size={16} className="text-emerald-400 shrink-0 mt-0.5" />
              <p>
                <b>JARVIS asks before acting.</b> Deleting or writing files, running code, typing into apps and similar actions always show a permission prompt. Secrets (.env files, SSH keys, browser passwords) are never read. Everything it does is listed under Activity.
              </p>
            </div>
            <label className="flex items-center gap-2 mt-2 cursor-pointer">
              <input type="checkbox" checked={voiceReplyEnabled} onChange={(e) => onVoiceReplyChange(e.target.checked)} />
              Speak replies out loud
            </label>
          </div>
        )}

        {step === 3 && (
          <div className="flex flex-col gap-3">
            <div className="flex items-center justify-between">
              <p className="text-xs text-gray-300">Checking what is ready on this PC:</p>
              <button onClick={fetchDiagnostics} className="text-gray-400 hover:text-cyan-400" title="Check again">
                <RefreshCw size={14} className={loadingDiag ? 'animate-spin' : ''} />
              </button>
            </div>
            {diagnostics ? (
              [
                { key: 'llm', label: 'AI model', ready: diagnostics.llm_ready, optional: false },
                { key: 'stt', label: 'Microphone & speech recognition', ready: diagnostics.voice_stt_ready, optional: true },
                { key: 'tts', label: 'Spoken replies', ready: diagnostics.voice_tts_ready, optional: true },
                { key: 'browser', label: 'Browser automation', ready: diagnostics.browser_ready, optional: true },
                { key: 'ocr', label: 'Reading text on screen', ready: diagnostics.ocr_ready, optional: true },
              ].map((item) => (
                <div key={item.key} className="flex items-center justify-between p-3 rounded-xl bg-white/5 border border-white/5">
                  <span className="text-xs text-gray-200">{item.label}</span>
                  <span
                    className={`text-[11px] font-mono px-2 py-0.5 rounded-full flex items-center gap-1 ${
                      item.ready
                        ? 'bg-emerald-500/20 text-emerald-400'
                        : item.optional
                        ? 'bg-white/5 text-gray-400'
                        : 'bg-amber-500/20 text-amber-300'
                    }`}
                  >
                    {item.ready ? <CheckCircle2 size={12} /> : <AlertCircle size={12} />}
                    {item.ready ? 'Ready' : item.optional ? 'Optional' : 'Needs setup'}
                  </span>
                </div>
              ))
            ) : (
              <p className="text-xs text-gray-400">{loadingDiag ? 'Checking…' : 'Could not run the check.'}</p>
            )}
          </div>
        )}

        <div className="flex justify-between items-center">
          <button onClick={() => (step === 0 ? onClose() : setStep(step - 1))} className="text-xs text-gray-400 hover:text-white">
            {step === 0 ? 'Skip setup' : 'Back'}
          </button>
          {step < STEPS.length - 1 ? (
            <button
              onClick={() => setStep(step + 1)}
              className="px-6 py-2.5 rounded-xl bg-cyan-500/20 hover:bg-cyan-500/30 text-cyan-300 border border-cyan-500/40 text-xs font-semibold flex items-center gap-1"
            >
              Next <ChevronRight size={14} />
            </button>
          ) : (
            <button
              onClick={finish}
              disabled={saving}
              className="px-6 py-2.5 rounded-xl bg-gradient-to-r from-cyan-500 to-blue-600 text-white font-semibold text-xs"
            >
              {saving ? 'Saving…' : 'Finish setup'}
            </button>
          )}
        </div>
      </motion.div>
    </div>
  )
}
