import { useState, useEffect, useRef } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Terminal, Activity, BrainCircuit, Lock } from 'lucide-react'

function App() {
  const [isAuthenticated, setIsAuthenticated] = useState(false)
  const [pin, setPin] = useState('')
  const [token, setToken] = useState('')
  const [messages, setMessages] = useState([
    { sender: 'JARVIS', text: 'System initialized. Awaiting authentication.' }
  ])
  const [input, setInput] = useState('')
  const [status, setStatus] = useState('OFFLINE')
  const [activeTab, setActiveTab] = useState('timeline')
  const [metrics, setMetrics] = useState(null)
  const wsRef = useRef(null)

  // Auto-scroll ref
  const chatEndRef = useRef(null)
  useEffect(() => { chatEndRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])

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
        setMessages([{ sender: 'JARVIS', text: 'Authentication accepted. Welcome back, sir.' }])
        connectWebSocket(data.access_token)
      } else {
        setPin('')
        alert("Access Denied: Invalid PIN")
      }
    } catch (err) {
      alert("Backend offline. Please start JARVIS API on port 7799.")
    }
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
          if (newMsgs[newMsgs.length - 1].sender === 'JARVIS') {
            newMsgs[newMsgs.length - 1].text += data.chunk
          } else {
            newMsgs.push({ sender: 'JARVIS', text: data.chunk })
          }
          return newMsgs
        })
      }
    }
    wsRef.current = ws
  }

  const sendMessage = (e) => {
    e.preventDefault()
    if (!input.trim() || !wsRef.current) return
    
    setMessages(prev => [...prev, { sender: 'YOU', text: input }])
    
    wsRef.current.send(JSON.stringify({
      command: 'chat',
      token: token,
      message: input
    }))
    
    setInput('')
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
    if (activeTab === 'metrics') {
      fetchMetrics()
      const interval = setInterval(fetchMetrics, 2000)
      return () => clearInterval(interval)
    }
  }, [activeTab, token])

  if (!isAuthenticated) {
    return (
      <div className="flex h-screen w-full items-center justify-center p-8 bg-transparent">
        <motion.form 
          initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }}
          onSubmit={handleLogin}
          className="glass-panel p-10 rounded-3xl flex flex-col items-center gap-6"
        >
          <Lock className="text-jarvis-cyan w-12 h-12 mb-2" />
          <h2 className="text-2xl font-light tracking-widest text-white uppercase">Security Override</h2>
          <input 
            type="password" autoFocus
            value={pin} onChange={(e) => setPin(e.target.value)}
            placeholder="ENTER PIN"
            className="bg-black/40 border border-jarvis-border rounded-xl py-3 px-6 text-center text-white tracking-[0.5em] focus:outline-none focus:border-jarvis-cyan/50"
          />
          <button type="submit" className="w-full py-3 rounded-xl bg-jarvis-cyan/20 text-jarvis-cyan hover:bg-jarvis-cyan/30 transition-colors tracking-widest text-sm font-semibold">
            AUTHORIZE
          </button>
        </motion.form>
      </div>
    )
  }

  return (
    <div className="flex h-screen w-full items-center justify-center p-8">
      <motion.div 
        initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }}
        className="glass-panel w-full max-w-6xl h-full max-h-[800px] rounded-3xl flex overflow-hidden relative"
      >
        <div className="w-64 border-r border-jarvis-border bg-black/20 p-6 flex flex-col gap-6">
          <div className="flex items-center gap-3">
            <div className={`w-3 h-3 rounded-full ${status === 'ONLINE' ? 'bg-green-400 animate-pulse shadow-[0_0_10px_rgba(74,222,128,0.5)]' : status === 'THINKING' ? 'bg-blue-400 animate-pulse' : status === 'SPEAKING' ? 'bg-purple-400 animate-pulse' : 'bg-red-500'}`}></div>
            <span className="font-semibold text-sm tracking-widest text-jarvis-cyan uppercase">JARVIS v4</span>
          </div>
          <nav className="flex flex-col gap-2 mt-8">
            <button onClick={() => setActiveTab('timeline')} className={`flex items-center gap-3 px-4 py-3 rounded-xl transition-colors ${activeTab === 'timeline' ? 'bg-white/5 text-white' : 'hover:bg-white/5 text-gray-400 hover:text-white'}`}>
              <Terminal size={18} className={activeTab === 'timeline' ? 'text-jarvis-cyan' : ''} />
              <span className="text-sm font-medium">Timeline</span>
            </button>
            <button onClick={() => setActiveTab('metrics')} className={`flex items-center gap-3 px-4 py-3 rounded-xl transition-colors ${activeTab === 'metrics' ? 'bg-white/5 text-white' : 'hover:bg-white/5 text-gray-400 hover:text-white'}`}>
              <Activity size={18} className={activeTab === 'metrics' ? 'text-jarvis-cyan' : ''} />
              <span className="text-sm font-medium">System Metrics</span>
            </button>
          </nav>
        </div>

        <div className="flex-1 flex flex-col relative">
          
          {activeTab === 'timeline' && (
            <>
              <div className="flex-1 overflow-y-auto p-8 space-y-6">
                {messages.map((msg, i) => (
                  <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} key={i} className={`flex ${msg.sender === 'YOU' ? 'justify-end' : 'justify-start'}`}>
                    <div className={`max-w-[70%] rounded-2xl px-6 py-4 backdrop-blur-md ${msg.sender === 'YOU' ? 'bg-jarvis-cyan/10 border border-jarvis-cyan/30 text-white' : 'bg-white/5 border border-white/10 text-gray-200'}`}>
                      <p className="text-xs font-medium mb-1 opacity-50">{msg.sender}</p>
                      <p className="leading-relaxed whitespace-pre-wrap">{msg.text}</p>
                    </div>
                  </motion.div>
                ))}
                <div ref={chatEndRef} />
              </div>

              <form onSubmit={sendMessage} className="p-6 border-t border-jarvis-border bg-black/20">
                <div className="relative flex items-center">
                  <input type="text" value={input} onChange={(e) => setInput(e.target.value)} placeholder="Command JARVIS..." className="w-full bg-black/40 border border-white/10 rounded-2xl py-4 pl-6 pr-16 text-white placeholder-gray-500 focus:outline-none focus:border-jarvis-cyan/50 focus:ring-1 focus:ring-jarvis-cyan/50 transition-all" />
                  <button type="submit" className="absolute right-4 p-2 rounded-xl bg-white/5 hover:bg-white/10 transition-colors text-jarvis-cyan">
                    <Terminal size={20} />
                  </button>
                </div>
              </form>
            </>
          )}

          {activeTab === 'metrics' && (
            <div className="flex-1 overflow-y-auto p-8 text-white">
              <h2 className="text-2xl font-light mb-6 tracking-widest uppercase">System Metrics</h2>
              {metrics ? (
                <div className="grid grid-cols-2 gap-6">
                  <div className="bg-black/40 border border-white/10 p-6 rounded-2xl">
                    <p className="text-gray-400 text-sm tracking-widest uppercase mb-2">CPU Usage</p>
                    <p className="text-3xl font-light text-jarvis-cyan">{metrics.cpu_percent}%</p>
                  </div>
                  <div className="bg-black/40 border border-white/10 p-6 rounded-2xl">
                    <p className="text-gray-400 text-sm tracking-widest uppercase mb-2">RAM Usage</p>
                    <p className="text-3xl font-light text-jarvis-cyan">{metrics.ram_used_gb} GB / {metrics.ram_total_gb} GB</p>
                  </div>
                  <div className="bg-black/40 border border-white/10 p-6 rounded-2xl">
                    <p className="text-gray-400 text-sm tracking-widest uppercase mb-2">Disk Usage</p>
                    <p className="text-3xl font-light text-jarvis-cyan">{metrics.disk_percent}%</p>
                  </div>
                  <div className="bg-black/40 border border-white/10 p-6 rounded-2xl">
                    <p className="text-gray-400 text-sm tracking-widest uppercase mb-2">Uptime</p>
                    <p className="text-3xl font-light text-jarvis-cyan">{metrics.uptime_seconds}s</p>
                  </div>
                </div>
              ) : (
                <p className="text-gray-500">Loading metrics...</p>
              )}
            </div>
          )}
          
        </div>
      </motion.div>
    </div>
  )
}

export default App
