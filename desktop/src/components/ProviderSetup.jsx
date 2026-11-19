import { useEffect, useState } from 'react'
import { CheckCircle2, AlertCircle, Loader2, ExternalLink } from 'lucide-react'
import { api } from '../api'

export const PROVIDERS = [
  {
    id: 'gemini',
    secret: 'GEMINI_API_KEY',
    name: 'Google Gemini',
    blurb: 'Recommended. Free tier available, strong at tools and long conversations.',
    keyUrl: 'https://aistudio.google.com/apikey',
    placeholder: 'AIza...',
  },
  {
    id: 'groq',
    secret: 'GROQ_API_KEY',
    name: 'Groq',
    blurb: 'Very fast responses. Free tier available.',
    keyUrl: 'https://console.groq.com/keys',
    placeholder: 'gsk_...',
  },
  {
    id: 'openai',
    secret: 'OPENAI_API_KEY',
    name: 'OpenAI',
    blurb: 'Paid. Used as an extra fallback when configured.',
    keyUrl: 'https://platform.openai.com/api-keys',
    placeholder: 'sk-...',
  },
  {
    id: 'ollama',
    secret: null,
    name: 'Local AI (Ollama)',
    blurb: 'Private and offline. Runs on your PC; needs a reasonably powerful computer.',
    keyUrl: 'https://ollama.com/download',
  },
]

function openExternal(url) {
  if (window.jarvis && typeof window.jarvis.openExternal === 'function') window.jarvis.openExternal(url)
  else window.open(url, '_blank', 'noopener')
}

/**
 * Configure one AI provider: test a key (lists models only, no cost) and store it in the
 * Windows Credential Manager via the backend. Keys are never shown again after saving.
 */
export default function ProviderSetup({ token, providerId, configured, onSaved, makePrimary = false }) {
  const provider = PROVIDERS.find((p) => p.id === providerId) || PROVIDERS[0]
  const [key, setKey] = useState('')
  const [state, setState] = useState({ kind: 'idle', message: '' })
  const [ollama, setOllama] = useState(null)

  useEffect(() => {
    setKey('')
    setState({ kind: 'idle', message: '' })
    if (provider.id === 'ollama') {
      api('/settings/ollama', { token })
        .then(setOllama)
        .catch(() => setOllama({ running: false, models: [] }))
    }
  }, [provider.id, token])

  const test = async () => {
    setState({ kind: 'busy', message: 'Checking…' })
    try {
      const res = await api('/settings/test-provider', {
        method: 'POST',
        token,
        body: { provider: provider.id, api_key: key || undefined },
      })
      setState(res.ok ? { kind: 'ok', message: 'Key works.' } : { kind: 'error', message: res.message || 'Key rejected.' })
      return res.ok
    } catch (e) {
      setState({ kind: 'error', message: e.message })
      return false
    }
  }

  const save = async () => {
    if (provider.id === 'ollama') {
      const model = ollama?.models?.[0]
      await api('/settings', { method: 'PUT', token, body: { ollama_model: model || null } })
      setState({ kind: 'ok', message: 'Local AI will be used when cloud AI is unavailable.' })
      onSaved && onSaved(provider.id)
      return
    }
    if (!key.trim()) {
      setState({ kind: 'error', message: 'Paste your API key first.' })
      return
    }
    if (!(await test())) return
    try {
      await api('/settings/secrets', { method: 'PUT', token, body: { name: provider.secret, value: key.trim() } })
      if (makePrimary && (provider.id === 'gemini' || provider.id === 'groq')) {
        await api('/settings', { method: 'PUT', token, body: { primary_engine: provider.id } })
      }
      setKey('')
      setState({ kind: 'ok', message: 'Saved securely in Windows Credential Manager. Restart JARVIS to use it.' })
      onSaved && onSaved(provider.id)
    } catch (e) {
      setState({ kind: 'error', message: e.message })
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="text-xs text-gray-300">{provider.blurb}</p>

      {provider.id === 'ollama' ? (
        <div className="rounded-xl bg-white/5 border border-white/5 p-3 text-xs text-gray-200">
          {ollama === null && <span className="text-gray-400">Looking for Ollama on this PC…</span>}
          {ollama && ollama.running && (
            <span>
              Ollama is running{ollama.models.length ? ` with ${ollama.models.length} model(s): ${ollama.models.slice(0, 3).join(', ')}` : ', but no models are installed yet (run: ollama pull llama3.2)'}.
            </span>
          )}
          {ollama && !ollama.running && (
            <span>
              Ollama is not running.{' '}
              <button className="text-cyan-300 underline" onClick={() => openExternal(provider.keyUrl)}>
                Download Ollama
              </button>
              , install it, then run <span className="font-mono">ollama pull llama3.2</span>.
            </span>
          )}
        </div>
      ) : (
        <>
          <div className="flex items-center justify-between">
            <label className="text-[11px] text-gray-400 uppercase tracking-wider font-mono">
              {provider.name} API key {configured ? '(already set — paste to replace)' : ''}
            </label>
            <button className="text-[11px] text-cyan-300 flex items-center gap-1" onClick={() => openExternal(provider.keyUrl)}>
              Get a key <ExternalLink size={11} />
            </button>
          </div>
          <input
            type="password"
            autoComplete="off"
            placeholder={provider.placeholder}
            value={key}
            onChange={(e) => setKey(e.target.value)}
            className="bg-black/50 border border-white/10 rounded-xl px-4 py-3 text-sm text-white focus:outline-none focus:border-cyan-400/60"
          />
        </>
      )}

      <div className="flex items-center justify-between gap-3">
        <span
          className={`text-[11px] flex items-center gap-1 ${
            state.kind === 'ok' ? 'text-emerald-400' : state.kind === 'error' ? 'text-amber-300' : 'text-gray-500'
          }`}
        >
          {state.kind === 'busy' && <Loader2 size={12} className="animate-spin" />}
          {state.kind === 'ok' && <CheckCircle2 size={12} />}
          {state.kind === 'error' && <AlertCircle size={12} />}
          {state.message}
        </span>
        <div className="flex gap-2">
          {provider.id !== 'ollama' && (
            <button
              onClick={test}
              disabled={!key || state.kind === 'busy'}
              className="px-4 py-2 rounded-xl bg-white/5 hover:bg-white/10 text-gray-200 border border-white/10 text-xs disabled:opacity-40"
            >
              Test
            </button>
          )}
          <button
            onClick={save}
            disabled={state.kind === 'busy' || (provider.id === 'ollama' && !ollama?.running)}
            className="px-4 py-2 rounded-xl bg-cyan-500/20 hover:bg-cyan-500/30 text-cyan-300 border border-cyan-500/40 text-xs font-semibold disabled:opacity-40"
          >
            {provider.id === 'ollama' ? 'Use local AI' : 'Save key'}
          </button>
        </div>
      </div>
    </div>
  )
}
