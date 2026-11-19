import { useState, useEffect, useRef, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Terminal, Activity, Volume2, VolumeX, RefreshCw, Wand2, Settings, History } from 'lucide-react'

import { api, createSocket, waitForBackend, loginWithLocalToken, loginWithPin, isDesktopApp } from './api'
import AudioVisualizer from './components/AudioVisualizer'
import AgentDashboard from './components/AgentDashboard'
import ConfirmationCard from './components/ConfirmationCard'
import SetupWizard from './components/SetupWizard'
import SettingsPanel from './components/SettingsPanel'
import ActivityPanel from './components/ActivityPanel'
import ChatPanel from './components/ChatPanel'
import { RoutineCards, TodoReminderBar, MetricsView } from './components/EverydayPanels'
import { StartingScreen, BackendUnavailableScreen, LoginScreen } from './components/StartupScreens'

const readPref = (key, fallback) => {
  try {
    const v = localStorage.getItem(key)
    return v === null ? fallback : v
  } catch {
    return fallback
  }
}
const writePref = (key, value) => {
  try {
    localStorage.setItem(key, value)
  } catch {
    /* storage unavailable */
  }
}

function App() {
  // ─── Startup & auth ──────────────────────────────────────────────────────
  const [phase, setPhase] = useState('starting') // starting | unavailable | login | ready
  const [startSeconds, setStartSeconds] = useState(0)
  const [pin, setPin] = useState('')
  const [loginError, setLoginError] = useState('')
  const [token, setToken] = useState('')
  const tokenRef = useRef('')

  // ─── Conversation & assistant state ──────────────────────────────────────
  const [messages, setMessages] = useState([{ sender: 'JARVIS', text: 'Hello! How can I help you today?' }])
  const [input, setInput] = useState('')
  const [status, setStatus] = useState('OFFLINE')
  const [activeAgent, setActiveAgent] = useState('None')
  const [pendingConfirmation, setPendingConfirmation] = useState(null)
  const socketRef = useRef(null)

  // ─── Everyday mode ───────────────────────────────────────────────────────
  const [uiMode, setUiMode] = useState(() => readPref('jarvis_desktop_mode', 'everyday'))
  const [activeTab, setActiveTab] = useState('timeline')
  const [metrics, setMetrics] = useState(null)
  const [reminders, setReminders] = useState([])
  const [todos, setTodos] = useState([])
  const [newTodoText, setNewTodoText] = useState('')
  const [voiceReplyEnabled, setVoiceReplyEnabled] = useState(() => readPref('jarvis_voice_reply', 'false') === 'true')
  const voiceReplyRef = useRef(voiceReplyEnabled)
  const [isListeningMic, setIsListeningMic] = useState(false)

  // ─── Panels ──────────────────────────────────────────────────────────────
  const [showOnboarding, setShowOnboarding] = useState(false)
  const [showSettings, setShowSettings] = useState(false)
  const [showActivity, setShowActivity] = useState(false)

  const addMessage = (msg) => setMessages((prev) => [...prev, msg])
  const systemMessage = (text) => addMessage({ sender: 'JARVIS', isSystem: true, text })

  useEffect(() => {
    voiceReplyRef.current = voiceReplyEnabled
    writePref('jarvis_voice_reply', String(voiceReplyEnabled))
  }, [voiceReplyEnabled])

  // ─── Data loaders ────────────────────────────────────────────────────────
  const fetchReminders = useCallback(async () => {
    if (!tokenRef.current) return
    try {
      const data = await api('/tasks/reminders', { token: tokenRef.current })
      setReminders(data.active_reminders || [])
    } catch {
      /* non-critical */
    }
  }, [])

  const fetchTodos = useCallback(async () => {
    if (!tokenRef.current) return
    try {
      const data = await api('/tasks/todos', { token: tokenRef.current })
      const pending = data.pending_todos || (data.items ? data.items.filter((i) => i.category === 'todo' && i.status === 'pending') : [])
      setTodos(pending)
    } catch {
      /* non-critical */
    }
  }, [])

  const refreshEveryday = useCallback(() => {
    fetchReminders()
    fetchTodos()
  }, [fetchReminders, fetchTodos])

  // ─── Voice ───────────────────────────────────────────────────────────────
  const speakText = async (text) => {
    if (!text || !voiceReplyRef.current) return
    try {
      await api('/voice/tts', { method: 'POST', token: tokenRef.current, body: { text } })
    } catch {
      if ('speechSynthesis' in window) {
        window.speechSynthesis.cancel()
        window.speechSynthesis.speak(new SpeechSynthesisUtterance(text))
      }
    }
  }

  const handleVoiceListen = async () => {
    if (isListeningMic) return
    setIsListeningMic(true)
    setStatus('LISTENING')
    try {
      const data = await api('/voice/listen', { method: 'POST', token: tokenRef.current })
      if (data.success && data.transcript) {
        addMessage({ sender: 'YOU', text: data.transcript })
        if (data.response) {
          addMessage({ sender: 'JARVIS', text: data.response })
          speakText(data.response)
        }
        refreshEveryday()
      } else {
        systemMessage(data.response || 'No speech detected.')
      }
    } catch (err) {
      systemMessage(`Voice input is unavailable: ${err.message}`)
    } finally {
      setIsListeningMic(false)
      setStatus('ONLINE')
    }
  }

  // ─── Live connection ─────────────────────────────────────────────────────
  const handleSocketMessage = useCallback(
    (data) => {
      if (data.status) {
        setStatus(data.status)
        if (data.status === 'ONLINE' || data.status === 'IDLE') refreshEveryday()
      } else if (data.chunk) {
        setMessages((prev) => {
          const next = [...prev]
          const last = next[next.length - 1]
          if (last && last.sender === 'JARVIS' && !last.isSystem && last.streaming) {
            next[next.length - 1] = { ...last, text: last.text + data.chunk }
          } else {
            next.push({ sender: 'JARVIS', text: data.chunk, streaming: true })
          }
          return next
        })
      } else if (data.type === 'stream_done') {
        setStatus('ONLINE')
        setMessages((prev) => {
          const next = [...prev]
          const last = next[next.length - 1]
          if (last && last.streaming) {
            next[next.length - 1] = { ...last, streaming: false }
            speakText(last.text)
          }
          return next
        })
      } else if (data.type === 'WAITING_FOR_CONFIRMATION') {
        setPendingConfirmation(data)
        setActiveAgent('Security')
      } else if (data.type === 'CONFIRMATION_PROCESSED' || data.type === 'CONFIRMATION_RESULT') {
        setPendingConfirmation(null)
      } else if (data.type === 'reminder_triggered') {
        refreshEveryday()
        systemMessage(`⏰ Reminder: ${data.title}${data.message ? ' - ' + data.message : ''}`)
      } else if (data.type === 'TASK_CANCELLED') {
        setStatus('IDLE')
        refreshEveryday()
        systemMessage('Task stopped.')
      } else if (data.type === 'execution_update') {
        if (data.event_type === 'STARTING_STEP') setActiveAgent('Planner')
        else if (data.event_type === 'EXECUTING_TOOL' || data.event_type === 'TOOL_OUTPUT') setActiveAgent('Tools')
        else if (data.event_type === 'STEP_SUSPENDED') setActiveAgent('Security')
        if (uiMode === 'pro') {
          systemMessage(`>>> [${data.event_type}] Step ${data.step_index}\n${JSON.stringify(data.data, null, 2)}`)
        }
      } else if (data.error) {
        systemMessage(data.error)
      }
    },
    [refreshEveryday, uiMode]
  )

  const handlerRef = useRef(handleSocketMessage)
  useEffect(() => {
    handlerRef.current = handleSocketMessage
  }, [handleSocketMessage])

  const startSession = (accessToken) => {
    tokenRef.current = accessToken
    setToken(accessToken)
    setPhase('ready')
    socketRef.current?.close()
    socketRef.current = createSocket({
      getToken: () => tokenRef.current,
      onMessage: (d) => handlerRef.current(d),
      onStatusChange: setStatus,
    })
    refreshEveryday()
    if (readPref('jarvis_onboarding_done', 'false') !== 'true') setShowOnboarding(true)
  }

  const boot = useCallback(async () => {
    setPhase('starting')
    const up = await waitForBackend({ onTick: setStartSeconds })
    if (!up) {
      setPhase('unavailable')
      return
    }
    const localToken = await loginWithLocalToken()
    if (localToken) startSession(localToken)
    else setPhase('login')
  }, [])

  useEffect(() => {
    boot()
    return () => socketRef.current?.close()
  }, [boot])

  const handleLogin = async (e) => {
    e.preventDefault()
    try {
      startSession(await loginWithPin(pin))
      setLoginError('')
    } catch (err) {
      setPin('')
      setLoginError(err.status === 429 ? err.message : err.status === 401 ? 'Wrong PIN.' : err.message)
    }
  }

  // ─── Actions ─────────────────────────────────────────────────────────────
  const sendQuery = (text) => {
    if (!text.trim()) return
    addMessage({ sender: 'YOU', text })
    if (!socketRef.current?.send({ command: 'chat', message: text })) {
      systemMessage('Not connected to JARVIS right now — reconnecting. Please try again in a moment.')
    }
  }

  const sendMessage = (e) => {
    e.preventDefault()
    if (!input.trim()) return
    sendQuery(input)
    setInput('')
  }

  const answerConfirmation = (confId, approved, alwaysAllow = false) => {
    socketRef.current?.send({ command: 'confirm', confirmation_id: confId, approved, always_allow: alwaysAllow })
    setPendingConfirmation(null)
  }

  const handleInterrupt = () => socketRef.current?.send({ command: 'interrupt' })

  const handleResetState = async () => {
    try {
      const data = await api('/tasks/reset-state', { method: 'POST', token: tokenRef.current })
      setStatus('ONLINE')
      systemMessage(data.message || 'System state reset.')
      refreshEveryday()
    } catch (err) {
      systemMessage(`Reset failed: ${err.message}`)
    }
  }

  const handleAddTodo = async (e) => {
    if (e) e.preventDefault()
    const text = newTodoText.trim()
    if (!text) return
    try {
      await api('/tasks/todos', { method: 'POST', token: tokenRef.current, body: { content: text, title: text, category: 'todo' } })
      setNewTodoText('')
      fetchTodos()
    } catch (err) {
      systemMessage(`Could not add the to-do: ${err.message}`)
    }
  }

  const handleCompleteTodo = async (itemId) => {
    try {
      await api(`/tasks/todos/${encodeURIComponent(itemId)}/complete`, { method: 'POST', token: tokenRef.current })
      fetchTodos()
    } catch (err) {
      systemMessage(`Could not complete the to-do: ${err.message}`)
    }
  }

  const handleDeleteTodo = async (itemId) => {
    try {
      await api(`/tasks/todos/${encodeURIComponent(itemId)}`, { method: 'DELETE', token: tokenRef.current })
      fetchTodos()
    } catch (err) {
      systemMessage(`Could not delete the to-do: ${err.message}`)
    }
  }

  const cancelReminder = async (reminderId) => {
    try {
      await api(`/tasks/reminders/${reminderId}`, { method: 'DELETE', token: tokenRef.current })
      fetchReminders()
    } catch (err) {
      systemMessage(`Could not cancel the reminder: ${err.message}`)
    }
  }

  const toggleUiMode = (mode) => {
    setUiMode(mode)
    writePref('jarvis_desktop_mode', mode)
  }

  // ─── Window controls (desktop app only) ──────────────────────────────────
  const desktop = typeof window !== 'undefined' ? window.jarvis || window.electron || window.electronAPI || {} : {}
  const callDesktop = (...names) => {
    for (const n of names) if (typeof desktop[n] === 'function') return desktop[n]()
  }

  useEffect(() => {
    if (!(activeTab === 'metrics' && uiMode === 'pro' && token)) return undefined
    const load = async () => {
      try {
        setMetrics(await api('/metrics', { token: tokenRef.current }))
      } catch {
        /* ignore */
      }
    }
    load()
    const interval = setInterval(load, 2000)
    return () => clearInterval(interval)
  }, [activeTab, token, uiMode])

  useEffect(() => {
    if (status === 'THINKING') setActiveAgent((a) => (a === 'None' ? 'Planner' : a))
    else setActiveAgent('None')
  }, [status])

  // ─── Render ──────────────────────────────────────────────────────────────
  if (phase === 'starting') return <StartingScreen seconds={startSeconds} />
  if (phase === 'unavailable')
    return <BackendUnavailableScreen onRetry={boot} onOpenLogs={typeof desktop.openLogs === 'function' ? desktop.openLogs : null} />
  if (phase === 'login') return <LoginScreen pin={pin} setPin={setPin} onSubmit={handleLogin} error={loginError} />

  const chat = (
    <ChatPanel
      messages={messages}
      input={input}
      setInput={setInput}
      onSubmit={sendMessage}
      onVoice={handleVoiceListen}
      isListening={isListeningMic}
      status={status}
      variant={uiMode === 'pro' ? 'pro' : 'everyday'}
    />
  )

  const topButton = (onClick, title, Icon, label) => (
    <button
      onClick={onClick}
      title={title}
      className="px-2.5 py-1 rounded-lg bg-white/5 hover:bg-white/10 text-gray-300 text-[10px] font-medium flex items-center gap-1 border border-white/5"
    >
      <Icon size={11} className="text-cyan-400" />
      {label}
    </button>
  )

  return (
    <div className="flex h-screen w-full items-center justify-center p-8 select-none">
      <motion.div
        initial={{ opacity: 0, scale: 0.97 }}
        animate={{ opacity: 1, scale: 1 }}
        className="glass-panel w-full max-w-6xl h-full max-h-[840px] rounded-3xl flex overflow-hidden relative border border-white/10 shadow-[0_20px_50px_rgba(0,0,0,0.6)]"
      >
        {/* Top bar */}
        <div
          className="absolute top-0 left-0 right-0 h-12 flex items-center justify-between px-6 z-40 border-b border-white/5 bg-black/40 backdrop-blur-md"
          style={{ WebkitAppRegion: 'drag' }}
        >
          <div className="flex items-center gap-3">
            <span
              className={`w-2 h-2 rounded-full ${status === 'OFFLINE' ? 'bg-red-500' : status === 'THINKING' ? 'bg-cyan-400 animate-pulse' : 'bg-emerald-400'}`}
              title={status === 'OFFLINE' ? 'Reconnecting…' : 'Connected'}
            />
            <span className="text-[11px] font-mono tracking-wider text-cyan-400 font-medium">JARVIS</span>
            <div className="flex items-center bg-black/60 p-0.5 rounded-xl border border-white/10 ml-3" style={{ WebkitAppRegion: 'no-drag' }}>
              {[
                ['everyday', 'Everyday Mode'],
                ['pro', 'Pro HUD Mode'],
              ].map(([mode, label]) => (
                <button
                  key={mode}
                  onClick={() => toggleUiMode(mode)}
                  className={`px-3 py-1 rounded-lg text-[10px] font-semibold ${uiMode === mode ? 'bg-cyan-500/30 text-cyan-300' : 'text-gray-400 hover:text-white'}`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          <div className="flex items-center gap-2" style={{ WebkitAppRegion: 'no-drag' }}>
            <button
              onClick={() => setVoiceReplyEnabled(!voiceReplyEnabled)}
              className={`px-2.5 py-1 rounded-lg text-[10px] font-medium flex items-center gap-1 border ${
                voiceReplyEnabled ? 'bg-purple-500/20 border-purple-400/40 text-purple-300' : 'bg-white/5 border-white/5 text-gray-400'
              }`}
              title="Speak replies out loud"
            >
              {voiceReplyEnabled ? <Volume2 size={11} /> : <VolumeX size={11} />}
              {voiceReplyEnabled ? 'Voice on' : 'Voice off'}
            </button>
            {topButton(() => setShowActivity(true), 'What JARVIS did on this PC', History, 'Activity')}
            {topButton(() => setShowSettings(true), 'Settings', Settings, 'Settings')}
            {topButton(() => setShowOnboarding(true), 'Setup wizard', Wand2, 'Setup')}
            {topButton(handleResetState, 'Cancel running tasks and reset', RefreshCw, 'Reset')}
            {status === 'THINKING' && (
              <button
                onClick={handleInterrupt}
                className="px-2.5 py-0.5 rounded-full bg-red-500/20 hover:bg-red-500/40 text-red-300 border border-red-500/40 text-[10px] font-bold uppercase"
              >
                Stop
              </button>
            )}
            {isDesktopApp() || desktop.minimize ? (
              <>
                <button onClick={() => callDesktop('minimize', 'minimizeWindow')} title="Minimize" aria-label="Minimize" className="w-3 h-3 rounded-full bg-yellow-500/50 hover:bg-yellow-500/80 ml-2" />
                <button onClick={() => callDesktop('maximize', 'maximizeWindow')} title="Maximize" aria-label="Maximize" className="w-3 h-3 rounded-full bg-green-500/50 hover:bg-green-500/80" />
                <button onClick={() => callDesktop('close', 'closeWindow')} title="Hide to tray" aria-label="Hide to tray" className="w-3 h-3 rounded-full bg-red-500/50 hover:bg-red-500/80" />
              </>
            ) : null}
          </div>
        </div>

        <AnimatePresence>
          {pendingConfirmation && (
            <ConfirmationCard
              confirmation={pendingConfirmation}
              onApprove={(id, always) => answerConfirmation(id, true, always)}
              onDeny={(id) => answerConfirmation(id, false)}
            />
          )}
        </AnimatePresence>

        <SetupWizard
          isOpen={showOnboarding}
          token={token}
          voiceReplyEnabled={voiceReplyEnabled}
          onVoiceReplyChange={setVoiceReplyEnabled}
          onClose={() => {
            setShowOnboarding(false)
            writePref('jarvis_onboarding_done', 'true')
          }}
          onFinish={(name) => {
            setShowOnboarding(false)
            writePref('jarvis_onboarding_done', 'true')
            addMessage({ sender: 'JARVIS', text: `Welcome aboard${name ? ', ' + name : ''}! How can I help you today?` })
          }}
        />
        <SettingsPanel isOpen={showSettings} token={token} onClose={() => setShowSettings(false)} />
        <ActivityPanel isOpen={showActivity} token={token} onClose={() => setShowActivity(false)} />

        {uiMode === 'everyday' ? (
          <div className="flex-1 flex flex-col pt-12 bg-zinc-950/40 h-full relative" style={{ WebkitAppRegion: 'no-drag' }}>
            <RoutineCards onRun={sendQuery} />
            <TodoReminderBar
              todos={todos}
              reminders={reminders}
              newTodoText={newTodoText}
              setNewTodoText={setNewTodoText}
              handleAddTodo={handleAddTodo}
              handleCompleteTodo={handleCompleteTodo}
              handleDeleteTodo={handleDeleteTodo}
              cancelReminder={cancelReminder}
            />
            {chat}
          </div>
        ) : (
          <>
            <div className="w-64 border-r border-white/10 bg-black/40 p-6 pt-16 flex flex-col justify-between h-full" style={{ WebkitAppRegion: 'no-drag' }}>
              <nav className="flex flex-col gap-2 mt-4">
                {[
                  ['timeline', 'Timeline', Terminal],
                  ['metrics', 'System Metrics', Activity],
                ].map(([tab, label, Icon]) => (
                  <button
                    key={tab}
                    onClick={() => setActiveTab(tab)}
                    className={`flex items-center gap-3 px-4 py-3 rounded-xl ${activeTab === tab ? 'bg-white/5 text-white' : 'text-gray-400 hover:text-white hover:bg-white/5'}`}
                  >
                    <Icon size={18} className={activeTab === tab ? 'text-cyan-400' : ''} />
                    <span className="text-sm font-medium">{label}</span>
                  </button>
                ))}
              </nav>
              <div className="flex flex-col gap-4 mt-auto">
                <AudioVisualizer status={status} />
                <AgentDashboard activeAgent={activeAgent} status={status} />
              </div>
            </div>
            <div className="flex-1 flex flex-col relative pt-12 bg-black/10" style={{ WebkitAppRegion: 'no-drag' }}>
              {activeTab === 'timeline' ? chat : <MetricsView metrics={metrics} />}
            </div>
          </>
        )}
      </motion.div>
    </div>
  )
}

export default App
