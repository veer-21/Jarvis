import { useState, useEffect, useRef } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { 
  Terminal, Activity, BrainCircuit, Lock, Volume2, 
  Sparkles, Clock, Folder, CheckCircle2, XCircle, AlertCircle, 
  ShieldCheck, Sliders, RefreshCw, ChevronRight, Wand2
} from 'lucide-react'

// ─── Sub-Components ─────────────────────────────────────────────────────────

function AudioVisualizer({ status }) {
  return (
    <div className="flex flex-col items-center justify-center p-4 bg-black/40 border border-white/5 rounded-2xl relative overflow-hidden h-28">
      <div className="absolute inset-0 bg-gradient-to-t from-cyan-500/5 to-transparent pointer-events-none"></div>
      
      <div className="relative flex items-center justify-center w-16 h-16">
        <AnimatePresence>
          {status === 'LISTENING' && (
            <>
              <motion.div 
                className="absolute w-full h-full rounded-full border border-cyan-400/40"
                initial={{ scale: 0.8, opacity: 0.8 }}
                animate={{ scale: [1, 1.8, 1], opacity: [0.8, 0, 0.8] }}
                transition={{ repeat: Infinity, duration: 1.5, ease: "easeInOut" }}
              />
              <motion.div 
                className="absolute w-full h-full rounded-full border border-cyan-400/20"
                initial={{ scale: 0.8, opacity: 0.6 }}
                animate={{ scale: [1, 2.2, 1], opacity: [0.6, 0, 0.6] }}
                transition={{ repeat: Infinity, duration: 1.5, ease: "easeInOut", delay: 0.3 }}
              />
            </>
          )}
          {status === 'SPEAKING' && (
            <>
              <motion.div 
                className="absolute w-full h-full rounded-full border border-purple-400/40"
                initial={{ scale: 0.8, opacity: 0.8 }}
                animate={{ scale: [1, 1.5, 1], opacity: [0.8, 0.2, 0.8] }}
                transition={{ repeat: Infinity, duration: 1.2, ease: "easeOut" }}
              />
              <motion.div 
                className="absolute w-full h-full rounded-full border border-purple-400/20"
                initial={{ scale: 0.8, opacity: 0.6 }}
                animate={{ scale: [1, 2.0, 1], opacity: [0.6, 0.1, 0.6] }}
                transition={{ repeat: Infinity, duration: 1.2, ease: "easeOut", delay: 0.2 }}
              />
            </>
          )}
          {status === 'THINKING' && (
            <motion.div 
              className="absolute w-full h-full rounded-full border-2 border-dashed border-cyan-400/45"
              animate={{ rotate: 360 }}
              transition={{ repeat: Infinity, duration: 3, ease: "linear" }}
            />
          )}
        </AnimatePresence>

        <motion.div 
          className={`w-10 h-10 rounded-full filter blur-[1px] ${
            status === 'LISTENING' 
              ? 'bg-cyan-400 shadow-[0_0_15px_rgba(34,211,238,0.6)]' 
              : status === 'SPEAKING' 
              ? 'bg-purple-500 shadow-[0_0_15px_rgba(168,85,247,0.6)]' 
              : status === 'THINKING' 
              ? 'bg-cyan-500/80 shadow-[0_0_12px_rgba(6,182,212,0.4)]' 
              : 'bg-emerald-500/80 shadow-[0_0_12px_rgba(16,185,129,0.3)]'
          }`}
          animate={
            status === 'LISTENING'
              ? { scale: [1, 1.25, 0.95, 1.2, 1] }
              : status === 'SPEAKING'
              ? { scale: [1, 1.15, 1, 1.1, 1] }
              : status === 'THINKING'
              ? { scale: [1, 0.9, 1] }
              : { scale: [1, 1.05, 1] }
          }
          transition={{
            repeat: Infinity,
            duration: status === 'LISTENING' ? 0.8 : status === 'SPEAKING' ? 1.0 : 2.0,
            ease: "easeInOut"
          }}
        />
      </div>
      <span className="text-[9px] tracking-widest text-white/40 uppercase mt-2 font-mono">
        {status === 'LISTENING' ? 'Vocal Input Active' : status === 'SPEAKING' ? 'JARVIS Responding' : status === 'THINKING' ? 'Cognitive Reasoning' : 'Monitor Idle'}
      </span>
    </div>
  )
}

function AgentDashboard({ activeAgent, status }) {
  const agents = [
    { name: 'Commander', desc: 'Intent classification & routing' },
    { name: 'Security', desc: 'Command safety validation' },
    { name: 'Memory', desc: 'Context retrieval & summary' },
    { name: 'Operator', desc: 'System tool execution' },
    { name: 'Refiner', desc: 'Workflow optimization' }
  ]

  return (
    <div className="flex flex-col gap-3 p-4 bg-black/40 border border-white/5 rounded-2xl">
      <span className="text-[9px] tracking-widest text-cyan-400 uppercase font-mono border-b border-white/10 pb-1.5 mb-1 flex items-center gap-1.5">
        <BrainCircuit size={12} className={status === 'THINKING' ? 'animate-pulse text-cyan-400' : 'text-cyan-600'} />
        Cognitive Agent Registry
      </span>
      <div className="flex flex-col gap-2">
        {agents.map((agent) => {
          const isActive = status === 'THINKING' && activeAgent === agent.name
          return (
            <div key={agent.name} className={`flex items-center justify-between transition-all duration-300 ${isActive ? 'opacity-100 scale-[1.02]' : 'opacity-30'}`}>
              <div className="flex flex-col">
                <span className={`text-xs font-mono font-medium ${isActive ? 'text-cyan-400' : 'text-gray-300'}`}>{agent.name}</span>
                <span className="text-[8px] text-gray-500 leading-none">{agent.desc}</span>
              </div>
              <div className={`w-1.5 h-1.5 rounded-full ${isActive ? 'bg-cyan-400 animate-pulse shadow-[0_0_8px_rgba(34,211,238,0.8)]' : 'bg-gray-700'}`}></div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ─── Human-Friendly Security Confirmation Card ───────────────────────────────

function ConfirmationCard({ confirmation, onApprove, onDeny }) {
  if (!confirmation) return null
  const { confirmation_id, tool, parameters, risk_level, risk_reason, action } = confirmation

  const friendlyAction = action || (
    tool === 'smart_organize_folder' ? 'Organize files in folder' :
    tool === 'control_windows_setting' ? `Adjust Windows setting (${parameters?.setting || 'System'})` :
    tool === 'drop_table' ? 'Drop Database Table' :
    `Execute ${tool}`
  )

  const friendlyReason = risk_reason || (
    risk_level === 'HIGH_RISK' ? 'This action could alter system settings or delete files. Jarvis requires your explicit authorization before proceeding.' :
    'This action will make changes on your computer. Please confirm to proceed.'
  )

  return (
    <motion.div 
      initial={{ opacity: 0, scale: 0.95, y: -20 }}
      animate={{ opacity: 1, scale: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.95, y: -20 }}
      className="absolute top-14 left-6 right-6 z-50 bg-black/95 backdrop-blur-2xl border border-amber-500/40 rounded-3xl p-6 shadow-[0_15px_45px_rgba(245,158,11,0.2)] flex flex-col gap-4 text-white"
      style={{ WebkitAppRegion: 'no-drag' }}
    >
      <div className="flex items-center justify-between border-b border-white/10 pb-3">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-full bg-amber-500/20 border border-amber-500/40 flex items-center justify-center text-amber-400">
            <ShieldCheck size={18} />
          </div>
          <div>
            <h3 className="text-sm font-semibold tracking-wide text-white">
              Jarvis Permission Request
            </h3>
            <p className="text-[11px] text-gray-400">Human-in-the-loop Security Gate</p>
          </div>
        </div>
        <span className="px-3 py-1 rounded-full text-[10px] font-bold font-mono tracking-widest bg-amber-500/20 text-amber-300 border border-amber-500/30 uppercase">
          {risk_level || 'CONFIRMATION REQUIRED'}
        </span>
      </div>

      <div className="bg-white/5 rounded-2xl p-4 border border-white/5 flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <span className="text-xs text-gray-400">Proposed Action:</span>
          <span className="text-xs font-semibold text-cyan-400 font-mono">{friendlyAction}</span>
        </div>
        <p className="text-xs text-gray-200 leading-relaxed mt-1">
          {friendlyReason}
        </p>
      </div>

      {parameters && Object.keys(parameters).length > 0 && (
        <div className="bg-black/60 rounded-xl p-3 border border-white/5 font-mono text-[11px] max-h-24 overflow-y-auto">
          <p className="text-gray-500 text-[9px] uppercase tracking-wider mb-1">Parameters:</p>
          <pre className="text-gray-300 whitespace-pre-wrap">{JSON.stringify(parameters, null, 2)}</pre>
        </div>
      )}

      <div className="flex items-center justify-end gap-3 pt-2">
        <button
          onClick={() => onDeny(confirmation_id)}
          className="px-5 py-2.5 rounded-xl bg-red-500/20 hover:bg-red-500/30 text-red-300 border border-red-500/30 text-xs font-semibold tracking-wider transition-colors flex items-center gap-1.5"
        >
          <XCircle size={14} />
          Cancel Safely
        </button>
        <button
          onClick={() => onApprove(confirmation_id)}
          className="px-6 py-2.5 rounded-xl bg-emerald-500/30 hover:bg-emerald-500/40 text-emerald-300 border border-emerald-500/40 text-xs font-semibold tracking-wider transition-all shadow-[0_0_20px_rgba(16,185,129,0.25)] flex items-center gap-1.5"
        >
          <CheckCircle2 size={14} />
          Approve Action
        </button>
      </div>
    </motion.div>
  )
}

// ─── First-Run Onboarding Wizard Modal ───────────────────────────────────────

function OnboardingModal({ isOpen, onClose, onFinish }) {
  const [step, setStep] = useState(1)
  const [userName, setUserName] = useState('')
  const [city, setCity] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [diagnostics, setDiagnostics] = useState(null)
  const [loadingDiag, setLoadingDiag] = useState(false)
  const [saving, setSaving] = useState(false)

  const fetchDiagnostics = async () => {
    setLoadingDiag(true)
    try {
      const res = await fetch('http://localhost:7799/onboarding/diagnostics')
      if (res.ok) {
        setDiagnostics(await res.json())
      }
    } catch (e) {
      console.warn("Diagnostics check error:", e)
    } finally {
      setLoadingDiag(false)
    }
  }

  useEffect(() => {
    if (isOpen && step === 2) {
      fetchDiagnostics()
    }
  }, [isOpen, step])

  const handleSaveConfig = async () => {
    setSaving(true)
    try {
      await fetch('http://localhost:7799/onboarding/configure', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_name: userName || undefined,
          preferred_city: city || undefined,
          gemini_api_key: apiKey || undefined,
        })
      })
    } catch (err) {
      console.warn("Onboarding config save error:", err)
    } finally {
      setSaving(false)
      onFinish(userName)
    }
  }

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-6 bg-black/80 backdrop-blur-xl" style={{ WebkitAppRegion: 'no-drag' }}>
      <motion.div 
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        exit={{ opacity: 0, scale: 0.95 }}
        className="w-full max-w-lg bg-zinc-950/90 border border-cyan-500/30 rounded-3xl p-8 shadow-[0_20px_60px_rgba(6,182,212,0.15)] text-white flex flex-col gap-6"
      >
        {/* Wizard Header */}
        <div className="flex items-center justify-between border-b border-white/10 pb-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-2xl bg-cyan-500/20 border border-cyan-500/40 flex items-center justify-center text-cyan-400">
              <Wand2 size={20} />
            </div>
            <div>
              <h2 className="text-base font-semibold text-white">Welcome to JARVIS</h2>
              <p className="text-xs text-gray-400">Personal AI Operating System Setup</p>
            </div>
          </div>
          <span className="text-xs font-mono text-cyan-400 font-semibold">Step {step} of 3</span>
        </div>

        {/* Step 1: User Profile */}
        {step === 1 && (
          <div className="flex flex-col gap-4">
            <p className="text-xs text-gray-300">
              Tell Jarvis what to call you and set your location for accurate morning briefings, weather, and timers.
            </p>
            <div className="flex flex-col gap-2">
              <label className="text-[11px] text-gray-400 uppercase tracking-wider font-mono">Your Name</label>
              <input 
                type="text"
                placeholder="e.g. Tony, Alex, Sir"
                value={userName}
                onChange={e => setUserName(e.target.value)}
                className="bg-black/50 border border-white/10 rounded-xl px-4 py-3 text-sm text-white focus:outline-none focus:border-cyan-400/60"
              />
            </div>
            <div className="flex flex-col gap-2">
              <label className="text-[11px] text-gray-400 uppercase tracking-wider font-mono">Preferred City</label>
              <input 
                type="text"
                placeholder="e.g. San Francisco, London, Tokyo"
                value={city}
                onChange={e => setCity(e.target.value)}
                className="bg-black/50 border border-white/10 rounded-xl px-4 py-3 text-sm text-white focus:outline-none focus:border-cyan-400/60"
              />
            </div>
            <div className="flex justify-end gap-3 mt-4">
              <button 
                onClick={() => setStep(2)}
                className="px-6 py-2.5 rounded-xl bg-cyan-500/20 hover:bg-cyan-500/30 text-cyan-300 border border-cyan-500/40 text-xs font-semibold tracking-wider flex items-center gap-1"
              >
                Next Step <ChevronRight size={14} />
              </button>
            </div>
          </div>
        )}

        {/* Step 2: Diagnostic Check */}
        {step === 2 && (
          <div className="flex flex-col gap-4">
            <div className="flex items-center justify-between">
              <p className="text-xs text-gray-300">Hardware & AI Readiness Diagnostics:</p>
              <button onClick={fetchDiagnostics} className="text-gray-400 hover:text-cyan-400 transition-colors">
                <RefreshCw size={14} className={loadingDiag ? 'animate-spin' : ''} />
              </button>
            </div>

            {loadingDiag ? (
              <p className="text-xs text-gray-400 animate-pulse font-mono py-4 text-center">Checking AI engines & audio devices...</p>
            ) : diagnostics ? (
              <div className="flex flex-col gap-2.5">
                {[
                  { key: 'llm', label: 'AI Reasoning Engine', ready: diagnostics.llm_ready },
                  { key: 'voice_stt', label: 'Microphone & Speech Recognition', ready: diagnostics.voice_stt_ready },
                  { key: 'voice_tts', label: 'Voice Response Audio Engine', ready: diagnostics.voice_tts_ready },
                  { key: 'browser', label: 'Browser Automation (Playwright)', ready: diagnostics.browser_ready },
                  { key: 'ocr', label: 'Screen OCR & Text Reading', ready: diagnostics.ocr_ready }
                ].map(item => (
                  <div key={item.key} className="flex items-center justify-between p-3 rounded-xl bg-white/5 border border-white/5">
                    <span className="text-xs text-gray-200">{item.label}</span>
                    <span className={`text-[11px] font-mono px-2 py-0.5 rounded-full flex items-center gap-1 ${item.ready ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30' : 'bg-amber-500/20 text-amber-300 border border-amber-500/30'}`}>
                      {item.ready ? <CheckCircle2 size={12} /> : <AlertCircle size={12} />}
                      {item.ready ? 'Ready' : 'Setup Needed'}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-amber-300">Could not retrieve diagnostics automatically. Make sure JARVIS backend is running.</p>
            )}

            <div className="flex justify-between items-center mt-4">
              <button onClick={() => setStep(1)} className="text-xs text-gray-400 hover:text-white">Back</button>
              <button 
                onClick={() => setStep(3)}
                className="px-6 py-2.5 rounded-xl bg-cyan-500/20 hover:bg-cyan-500/30 text-cyan-300 border border-cyan-500/40 text-xs font-semibold tracking-wider flex items-center gap-1"
              >
                Next Step <ChevronRight size={14} />
              </button>
            </div>
          </div>
        )}

        {/* Step 3: AI Key & Ready */}
        {step === 3 && (
          <div className="flex flex-col gap-4">
            <p className="text-xs text-gray-300">
              Optional: Enter your Google Gemini API key to activate cloud reasoning. If you already have it in your .env file, you can finish immediately.
            </p>
            <div className="flex flex-col gap-2">
              <label className="text-[11px] text-gray-400 uppercase tracking-wider font-mono">Gemini API Key (Optional)</label>
              <input 
                type="password"
                placeholder="AIzaSy..."
                value={apiKey}
                onChange={e => setApiKey(e.target.value)}
                className="bg-black/50 border border-white/10 rounded-xl px-4 py-3 text-sm text-white focus:outline-none focus:border-cyan-400/60"
              />
              <span className="text-[10px] text-gray-500">Keys are encrypted on your local disk and never sent to external telemetry.</span>
            </div>

            <div className="flex justify-between items-center mt-4">
              <button onClick={() => setStep(2)} className="text-xs text-gray-400 hover:text-white">Back</button>
              <button 
                onClick={handleSaveConfig}
                disabled={saving}
                className="px-6 py-2.5 rounded-xl bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-400 hover:to-blue-500 text-white font-semibold text-xs tracking-wider shadow-[0_0_20px_rgba(6,182,212,0.3)] transition-all flex items-center gap-1.5"
              >
                {saving ? 'Saving...' : 'Finish Setup & Launch'}
              </button>
            </div>
          </div>
        )}
      </motion.div>
    </div>
  )
}

// ─── Main Application Component ─────────────────────────────────────────────

function App() {
  const [isAuthenticated, setIsAuthenticated] = useState(false)
  const [pin, setPin] = useState('')
  const [token, setToken] = useState('')
  const [messages, setMessages] = useState([
    { sender: 'JARVIS', text: 'System initialized. Everyday Mode active and ready for your commands.' }
  ])
  const [input, setInput] = useState('')
  const [status, setStatus] = useState('OFFLINE')
  const [activeTab, setActiveTab] = useState('timeline')
  const [metrics, setMetrics] = useState(null)
  const [activeAgent, setActiveAgent] = useState('None')
  const [pendingConfirmation, setPendingConfirmation] = useState(null)
  
  // Everyday Mode state
  const [uiMode, setUiMode] = useState(() => {
    return localStorage.getItem('jarvis_desktop_mode') || 'everyday'
  })
  const [showOnboarding, setShowOnboarding] = useState(false)
  const [reminders, setReminders] = useState([])
  const wsRef = useRef(null)
  const chatEndRef = useRef(null)

  useEffect(() => { 
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' }) 
  }, [messages])

  const toggleUiMode = (newMode) => {
    setUiMode(newMode)
    localStorage.setItem('jarvis_desktop_mode', newMode)
  }

  const handleLogin = async (e) => {
    e.preventDefault()
    try {
      const res = await fetch('http://localhost:7799/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pin })
      })
      if (res.ok) {
        const data = await res.json()
        setToken(data.access_token)
        setIsAuthenticated(true)
        setMessages([{ sender: 'JARVIS', text: 'Authentication accepted. Welcome back, Sir.' }])
        connectWebSocket(data.access_token)
        fetchReminders(data.access_token)
      } else {
        setPin('')
        alert("Access Denied: Invalid PIN")
      }
    } catch (err) {
      alert("Backend offline. Please start JARVIS API on port 7799.")
    }
  }

  const fetchReminders = async (authToken) => {
    try {
      const res = await fetch('http://localhost:7799/tasks/reminders', {
        headers: { 'Authorization': `Bearer ${authToken || token}` }
      })
      if (res.ok) {
        const data = await res.json()
        setReminders(data.active_reminders || [])
      }
    } catch (e) {}
  }

  const connectWebSocket = (authToken) => {
    const ws = new WebSocket('ws://localhost:7799/ws/jarvis')
    ws.onopen = () => setStatus('ONLINE')
    ws.onclose = () => setStatus('OFFLINE')
    
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data)
      if (data.status) {
        setStatus(data.status)
      } else if (data.chunk) {
        setMessages(prev => {
          const newMsgs = [...prev]
          if (newMsgs[newMsgs.length - 1]?.sender === 'JARVIS') {
            newMsgs[newMsgs.length - 1].text += data.chunk
          } else {
            newMsgs.push({ sender: 'JARVIS', text: data.chunk })
          }
          return newMsgs
        })
      } else if (data.type === 'WAITING_FOR_CONFIRMATION') {
        setPendingConfirmation(data)
        setActiveAgent('Security')
        setMessages(prev => [
          ...prev,
          { 
            sender: 'JARVIS [SECURITY]', 
            text: `[CONFIRMATION REQUIRED] Action: ${data.action || data.tool}\nReason: ${data.risk_reason || 'Requires confirmation'}\nRisk: ${data.risk_level}`,
            isSystem: true
          }
        ])
      } else if (data.type === 'CONFIRMATION_PROCESSED' || data.type === 'CONFIRMATION_RESULT') {
        setPendingConfirmation(null)
      } else if (data.type === 'reminder_triggered') {
        fetchReminders()
        setMessages(prev => [
          ...prev,
          {
            sender: 'JARVIS [REMINDER]',
            text: `⏰ Reminder Triggered: ${data.title}${data.message ? ' - ' + data.message : ''}`,
            isSystem: true
          }
        ])
      } else if (data.type === 'TASK_CANCELLED') {
        setStatus('IDLE')
        setMessages(prev => [
          ...prev,
          { 
            sender: 'JARVIS [SYSTEM]', 
            text: `>>> Task execution interrupted and cancelled.`,
            isSystem: true
          }
        ])
      } else if (data.type === 'execution_update') {
        if (data.event_type === 'STARTING_STEP') setActiveAgent('Commander')
        else if (data.event_type === 'EXECUTING_TOOL') setActiveAgent('Operator')
        else if (data.event_type === 'TOOL_OUTPUT') setActiveAgent('Operator')
        else if (data.event_type === 'STEP_SUSPENDED') setActiveAgent('Security')
        
        if (uiMode === 'pro') {
          setMessages(prev => [
            ...prev,
            { 
              sender: 'JARVIS [SYSTEM]', 
              text: `>>> [${data.event_type}] Step ${data.step_index}\n${JSON.stringify(data.data, null, 2)}`,
              isSystem: true
            }
          ])
        }
      }
    }
    wsRef.current = ws
  }

  const sendQuery = (text) => {
    if (!text.trim() || !wsRef.current) return
    setMessages(prev => [...prev, { sender: 'YOU', text }])
    wsRef.current.send(JSON.stringify({
      command: 'chat',
      token: token,
      message: text
    }))
  }

  const sendMessage = (e) => {
    e.preventDefault()
    if (!input.trim()) return
    sendQuery(input)
    setInput('')
  }

  const handleApproveConfirmation = (confId) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        command: 'confirm',
        confirmation_id: confId,
        approved: true,
        token: token
      }))
    }
    setPendingConfirmation(null)
  }

  const handleDenyConfirmation = (confId) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        command: 'confirm',
        confirmation_id: confId,
        approved: false,
        token: token
      }))
    }
    setPendingConfirmation(null)
  }

  const handleInterrupt = () => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        command: 'interrupt',
        token: token
      }))
    }
  }

  const getElectron = () => (typeof window !== 'undefined' ? (window.electron || window.electronAPI || {}) : {})

  const handleMinimize = () => {
    const el = getElectron()
    if (typeof el.minimize === 'function') el.minimize()
    else if (typeof el.minimizeWindow === 'function') el.minimizeWindow()
  }

  const handleMaximize = () => {
    const el = getElectron()
    if (typeof el.maximize === 'function') el.maximize()
    else if (typeof el.maximizeWindow === 'function') el.maximizeWindow()
  }

  const handleClose = () => {
    const el = getElectron()
    if (typeof el.close === 'function') el.close()
    else if (typeof el.closeWindow === 'function') el.closeWindow()
  }

  const fetchMetrics = async () => {
    if (!token) return
    try {
      const res = await fetch('http://localhost:7799/metrics', {
        headers: { 'Authorization': `Bearer ${token}` }
      })
      if (res.ok) setMetrics(await res.json())
    } catch (e) {}
  }

  useEffect(() => {
    if (activeTab === 'metrics' && uiMode === 'pro') {
      fetchMetrics()
      const interval = setInterval(fetchMetrics, 2000)
      return () => clearInterval(interval)
    }
  }, [activeTab, token, uiMode])

  useEffect(() => {
    if (status === 'THINKING') {
      if (activeAgent === 'None') setActiveAgent('Commander')
    } else {
      setActiveAgent('None')
    }
  }, [status])

  if (!isAuthenticated) {
    return (
      <div className="flex h-screen w-full items-center justify-center p-8 bg-transparent">
        <motion.form 
          initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }}
          onSubmit={handleLogin}
          className="glass-panel p-10 rounded-3xl flex flex-col items-center gap-6 border border-white/10"
        >
          <Lock className="text-cyan-400 w-12 h-12 mb-2" />
          <h2 className="text-2xl font-light tracking-widest text-white uppercase">Security Override</h2>
          <input 
            type="password" autoFocus
            value={pin} onChange={(e) => setPin(e.target.value)}
            placeholder="ENTER PIN"
            className="bg-black/40 border border-cyan-500/20 rounded-xl py-3 px-6 text-center text-white tracking-[0.5em] focus:outline-none focus:border-cyan-400/50"
          />
          <button type="submit" className="w-full py-3 rounded-xl bg-cyan-500/20 text-cyan-300 hover:bg-cyan-500/30 transition-colors tracking-widest text-sm font-semibold">
            AUTHORIZE
          </button>
        </motion.form>
      </div>
    )
  }

  return (
    <div className="flex h-screen w-full items-center justify-center p-8 select-none">
      <motion.div 
        initial={{ opacity: 0, scale: 0.97 }} animate={{ opacity: 1, scale: 1 }}
        className="glass-panel w-full max-w-6xl h-full max-h-[840px] rounded-3xl flex overflow-hidden relative border border-white/10 shadow-[0_20px_50px_rgba(0,0,0,0.6)]"
      >
        {/* Top-Bar with Mode Switch and Window Controls */}
        <div className="absolute top-0 left-0 right-0 h-12 flex items-center justify-between px-6 z-50 cursor-default border-b border-white/5 bg-black/40 backdrop-blur-md" style={{ WebkitAppRegion: 'drag' }}>
          <div className="flex items-center gap-3">
            <Volume2 size={13} className={`${status === 'SPEAKING' ? 'text-purple-400 animate-bounce' : status === 'LISTENING' ? 'text-cyan-400 animate-pulse' : 'text-white/30'}`} />
            <span className="text-[11px] font-mono tracking-wider text-cyan-400 font-medium">JARVIS v4.0</span>
            
            {/* Mode Switch Toggle */}
            <div className="flex items-center bg-black/60 p-0.5 rounded-xl border border-white/10 ml-3" style={{ WebkitAppRegion: 'no-drag' }}>
              <button
                onClick={() => toggleUiMode('everyday')}
                className={`px-3 py-1 rounded-lg text-[10px] font-semibold transition-all ${
                  uiMode === 'everyday' 
                    ? 'bg-cyan-500/30 text-cyan-300 shadow-[0_0_10px_rgba(6,182,212,0.3)]' 
                    : 'text-gray-400 hover:text-white'
                }`}
              >
                Everyday Mode
              </button>
              <button
                onClick={() => toggleUiMode('pro')}
                className={`px-3 py-1 rounded-lg text-[10px] font-semibold transition-all ${
                  uiMode === 'pro' 
                    ? 'bg-purple-500/30 text-purple-300 shadow-[0_0_10px_rgba(168,85,247,0.3)]' 
                    : 'text-gray-400 hover:text-white'
                }`}
              >
                Pro HUD Mode
              </button>
            </div>
          </div>

          <div className="flex items-center gap-2" style={{ WebkitAppRegion: 'no-drag' }}>
            <button
              onClick={() => setShowOnboarding(true)}
              className="px-2.5 py-1 rounded-lg bg-white/5 hover:bg-white/10 text-gray-300 text-[10px] font-medium flex items-center gap-1 border border-white/5 transition-colors mr-2"
              title="First-run Setup Wizard"
            >
              <Wand2 size={11} className="text-cyan-400" />
              Setup Wizard
            </button>

            {status === 'THINKING' && (
              <button 
                onClick={handleInterrupt}
                className="px-2.5 py-0.5 mr-2 rounded-full bg-red-500/20 hover:bg-red-500/40 text-red-300 border border-red-500/40 text-[10px] font-mono font-bold tracking-wider uppercase transition-colors"
              >
                Interrupt
              </button>
            )}
            <button onClick={handleMinimize} title="Minimize" className="w-3 h-3 rounded-full bg-yellow-500/50 hover:bg-yellow-500/80 transition-all border border-yellow-400/20 focus:outline-none"></button>
            <button onClick={handleMaximize} title="Maximize" className="w-3 h-3 rounded-full bg-green-500/50 hover:bg-green-500/80 transition-all border border-green-400/20 focus:outline-none"></button>
            <button onClick={handleClose} title="Close" className="w-3 h-3 rounded-full bg-red-500/50 hover:bg-red-500/80 transition-all border border-red-400/20 focus:outline-none"></button>
          </div>
        </div>

        {/* Confirmation Modal */}
        <AnimatePresence>
          {pendingConfirmation && (
            <ConfirmationCard 
              confirmation={pendingConfirmation}
              onApprove={handleApproveConfirmation}
              onDeny={handleDenyConfirmation}
            />
          )}
        </AnimatePresence>

        {/* Onboarding Wizard Modal */}
        <OnboardingModal 
          isOpen={showOnboarding}
          onClose={() => setShowOnboarding(false)}
          onFinish={(name) => {
            setShowOnboarding(false)
            setMessages(prev => [
              ...prev,
              { sender: 'JARVIS', text: `Welcome aboard${name ? ', ' + name : ''}! All systems are calibrated. How can I help you today?` }
            ])
          }}
        />

        {/* ─── Everyday Assistant View vs Pro HUD View ──────────────────── */}

        {uiMode === 'everyday' ? (
          <div className="flex-1 flex flex-col pt-12 bg-zinc-950/40 h-full relative" style={{ WebkitAppRegion: 'no-drag' }}>
            {/* Daily Routine Cards Grid */}
            <div className="p-6 pb-2 border-b border-white/5">
              <div className="flex items-center justify-between mb-3">
                <span className="text-[11px] font-semibold text-gray-300 flex items-center gap-1.5">
                  <Sparkles size={13} className="text-cyan-400" />
                  1-Click Daily Routines
                </span>
                <span className="text-[10px] text-gray-500 font-mono">Ready to assist</span>
              </div>
              <div className="grid grid-cols-5 gap-3">
                {[
                  { title: "Morning Briefing", desc: "Weather, tasks, system stats", cmd: "Give me my daily briefing", icon: "🌅" },
                  { title: "Organize Downloads", desc: "Clean cluttered files safely", cmd: "Preview organizing my Downloads folder", icon: "📁" },
                  { title: "Read My Screen", desc: "Summarize active window", cmd: "Read and summarize the text on my screen", icon: "🖥️" },
                  { title: "Quick Reminder", desc: "Break timer in 15 mins", cmd: "Remind me in 15 minutes to take a break", icon: "⏰" },
                  { title: "Health Check", desc: "Speed, CPU & RAM status", cmd: "Check my computer's speed, CPU, and memory", icon: "⚡" },
                ].map((card, idx) => (
                  <button
                    key={idx}
                    onClick={() => sendQuery(card.cmd)}
                    className="flex flex-col text-left p-3 rounded-2xl bg-white/5 hover:bg-cyan-500/10 border border-white/5 hover:border-cyan-500/30 transition-all group"
                  >
                    <span className="text-xl mb-1">{card.icon}</span>
                    <span className="text-xs font-semibold text-gray-200 group-hover:text-cyan-300 transition-colors">{card.title}</span>
                    <span className="text-[10px] text-gray-500 line-clamp-1">{card.desc}</span>
                  </button>
                ))}
              </div>
            </div>

            {/* Conversational Stream */}
            <div className="flex-1 overflow-y-auto p-6 space-y-4 select-text">
              {messages.map((msg, i) => (
                <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} key={i} className={`flex ${msg.sender === 'YOU' ? 'justify-end' : 'justify-start'}`}>
                  <div className={`max-w-[70%] rounded-2xl px-5 py-3.5 backdrop-blur-md ${
                    msg.sender === 'YOU' 
                      ? 'bg-cyan-500/15 border border-cyan-400/30 text-white' 
                      : msg.isSystem 
                      ? 'bg-black/60 border border-emerald-500/20 text-emerald-300 font-mono text-xs' 
                      : 'bg-white/5 border border-white/10 text-gray-100 shadow-[0_4px_12px_rgba(0,0,0,0.15)]'
                  }`}>
                    <p className="text-[10px] font-mono tracking-wider mb-1 opacity-50">{msg.sender}</p>
                    <p className="leading-relaxed whitespace-pre-wrap text-sm">{msg.text}</p>
                  </div>
                </motion.div>
              ))}
              <div ref={chatEndRef} />
            </div>

            {/* Input Bar */}
            <form onSubmit={sendMessage} className="p-6 pt-3 border-t border-white/5 bg-black/30">
              <div className="relative flex items-center">
                <input 
                  type="text" 
                  value={input} 
                  onChange={(e) => setInput(e.target.value)} 
                  placeholder="Ask Jarvis to organize files, summarize a document, set a reminder, or search the web..." 
                  className="w-full bg-black/50 border border-white/10 rounded-2xl py-4 pl-6 pr-14 text-white placeholder-gray-500 focus:outline-none focus:border-cyan-400/50 focus:ring-1 focus:ring-cyan-400/40 transition-all font-light text-sm" 
                />
                <button type="submit" className="absolute right-4 p-2.5 rounded-xl bg-cyan-500/20 hover:bg-cyan-500/30 text-cyan-300 transition-colors">
                  <Sparkles size={16} />
                </button>
              </div>
            </form>
          </div>
        ) : (
          /* ─── Pro HUD Mode (Developer & Power User Area) ────────────────── */
          <>
            <div className="w-66 border-r border-white/10 bg-black/40 p-6 pt-16 flex flex-col justify-between h-full" style={{ WebkitAppRegion: 'no-drag' }}>
              <div className="flex flex-col gap-6">
                <div className="flex items-center gap-3">
                  <div className={`w-3 h-3 rounded-full ${
                    status === 'ONLINE' ? 'bg-green-400 shadow-[0_0_10px_rgba(74,222,128,0.5)]' :
                    status === 'THINKING' ? 'bg-cyan-400 animate-pulse shadow-[0_0_10px_rgba(34,211,238,0.5)]' :
                    status === 'SPEAKING' ? 'bg-purple-400 animate-pulse shadow-[0_0_10px_rgba(168,85,247,0.5)]' :
                    status === 'LISTENING' ? 'bg-cyan-300 animate-pulse shadow-[0_0_12px_rgba(34,211,238,0.8)]' :
                    'bg-red-500'
                  }`}></div>
                  <span className="font-semibold text-xs tracking-widest text-cyan-400 uppercase">PRO HUD</span>
                </div>
                
                <nav className="flex flex-col gap-2 mt-4">
                  <button onClick={() => setActiveTab('timeline')} className={`flex items-center gap-3 px-4 py-3 rounded-xl transition-colors ${activeTab === 'timeline' ? 'bg-white/5 text-white' : 'hover:bg-white/5 text-gray-400 hover:text-white'}`}>
                    <Terminal size={18} className={activeTab === 'timeline' ? 'text-cyan-400' : ''} />
                    <span className="text-sm font-medium">Timeline</span>
                  </button>
                  <button onClick={() => setActiveTab('metrics')} className={`flex items-center gap-3 px-4 py-3 rounded-xl transition-colors ${activeTab === 'metrics' ? 'bg-white/5 text-white' : 'hover:bg-white/5 text-gray-400 hover:text-white'}`}>
                    <Activity size={18} className={activeTab === 'metrics' ? 'text-cyan-400' : ''} />
                    <span className="text-sm font-medium">System Metrics</span>
                  </button>
                </nav>
              </div>

              <div className="flex flex-col gap-4 mt-auto">
                <AudioVisualizer status={status} />
                <AgentDashboard activeAgent={activeAgent} status={status} />
              </div>
            </div>

            <div className="flex-1 flex flex-col relative pt-12 bg-black/10" style={{ WebkitAppRegion: 'no-drag' }}>
              {activeTab === 'timeline' && (
                <>
                  <div className="flex-1 overflow-y-auto p-8 space-y-6 select-text">
                    {messages.map((msg, i) => (
                      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} key={i} className={`flex ${msg.sender === 'YOU' ? 'justify-end' : 'justify-start'}`}>
                        <div className={`max-w-[75%] rounded-2xl px-6 py-4 backdrop-blur-md ${msg.sender === 'YOU' ? 'bg-cyan-500/10 border border-cyan-400/30 text-white' : msg.isSystem ? 'bg-black/60 border border-emerald-500/20 text-emerald-400 font-mono text-xs shadow-[0_4px_12px_rgba(0,0,0,0.3)]' : 'bg-white/5 border border-white/10 text-gray-200 shadow-[0_4px_12px_rgba(0,0,0,0.15)]'}`}>
                          <p className="text-[10px] font-mono tracking-wider mb-1 opacity-45">{msg.sender}</p>
                          <p className="leading-relaxed whitespace-pre-wrap">{msg.text}</p>
                        </div>
                      </motion.div>
                    ))}
                    <div ref={chatEndRef} />
                  </div>

                  <form onSubmit={sendMessage} className="p-6 border-t border-white/10 bg-black/20">
                    <div className="relative flex items-center">
                      <input type="text" value={input} onChange={(e) => setInput(e.target.value)} placeholder="Command JARVIS..." className="w-full bg-black/45 border border-white/10 rounded-2xl py-4 pl-6 pr-16 text-white placeholder-gray-500 focus:outline-none focus:border-cyan-400/50 focus:ring-1 focus:ring-cyan-400/50 transition-all font-light text-sm" />
                      <button type="submit" className="absolute right-4 p-2 rounded-xl bg-white/5 hover:bg-white/10 transition-colors text-cyan-400">
                        <Terminal size={20} />
                      </button>
                    </div>
                  </form>
                </>
              )}

              {activeTab === 'metrics' && (
                <div className="flex-1 overflow-y-auto p-8 text-white select-text">
                  <h2 className="text-xl font-light mb-6 tracking-widest uppercase text-cyan-400 font-mono border-b border-white/10 pb-2">System Metrics</h2>
                  {metrics ? (
                    <div className="grid grid-cols-2 gap-6">
                      <div className="bg-black/40 border border-white/5 p-6 rounded-2xl backdrop-blur-md">
                        <p className="text-gray-400 text-xs tracking-widest uppercase mb-2 font-mono">CPU Usage</p>
                        <p className="text-3xl font-light text-cyan-400">{metrics.cpu_percent}%</p>
                      </div>
                      <div className="bg-black/40 border border-white/5 p-6 rounded-2xl backdrop-blur-md">
                        <p className="text-gray-400 text-xs tracking-widest uppercase mb-2 font-mono">RAM Usage</p>
                        <p className="text-3xl font-light text-cyan-400">{metrics.ram_used_gb} GB / {metrics.ram_total_gb} GB</p>
                      </div>
                      <div className="bg-black/40 border border-white/5 p-6 rounded-2xl backdrop-blur-md">
                        <p className="text-gray-400 text-xs tracking-widest uppercase mb-2 font-mono">Disk Usage</p>
                        <p className="text-3xl font-light text-cyan-400">{metrics.disk_percent}%</p>
                      </div>
                      <div className="bg-black/40 border border-white/5 p-6 rounded-2xl backdrop-blur-md">
                        <p className="text-gray-400 text-xs tracking-widest uppercase mb-2 font-mono">Uptime</p>
                        <p className="text-3xl font-light text-cyan-400">{metrics.uptime_seconds}s</p>
                      </div>
                    </div>
                  ) : (
                    <p className="text-gray-500 font-mono text-sm animate-pulse">Establishing diagnostic connection...</p>
                  )}
                </div>
              )}
            </div>
          </>
        )}
      </motion.div>
    </div>
  )
}

export default App
