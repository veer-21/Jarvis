import { useEffect, useRef } from 'react'
import { motion } from 'framer-motion'
import { Mic, Sparkles, Terminal } from 'lucide-react'

/** Conversation stream + input bar. `variant` is 'everyday' or 'pro' (styling only). */
export default function ChatPanel({ messages, input, setInput, onSubmit, onVoice, isListening, status, variant = 'everyday' }) {
  const endRef = useRef(null)
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const pro = variant === 'pro'
  return (
    <>
      <div className={`flex-1 overflow-y-auto ${pro ? 'p-8 space-y-6' : 'p-6 space-y-4'} select-text`} aria-live="polite">
        {messages.map((msg, i) => (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            key={i}
            className={`flex ${msg.sender === 'YOU' ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`${pro ? 'max-w-[75%] px-6 py-4' : 'max-w-[70%] px-5 py-3.5'} rounded-2xl backdrop-blur-md ${
                msg.sender === 'YOU'
                  ? 'bg-cyan-500/15 border border-cyan-400/30 text-white'
                  : msg.isSystem
                  ? 'bg-black/60 border border-emerald-500/20 text-emerald-300 font-mono text-xs'
                  : 'bg-white/5 border border-white/10 text-gray-100'
              }`}
            >
              <p className="text-[10px] font-mono tracking-wider mb-1 opacity-50">{msg.sender}</p>
              <p className="leading-relaxed whitespace-pre-wrap text-sm">{msg.text}</p>
            </div>
          </motion.div>
        ))}
        <div ref={endRef} />
      </div>

      <form onSubmit={onSubmit} className={`${pro ? 'p-6 border-white/10 bg-black/20' : 'p-6 pt-3 border-white/5 bg-black/30'} border-t`}>
        <div className="relative flex items-center">
          <button
            type="button"
            onClick={onVoice}
            disabled={isListening}
            className={`p-3 mr-3 rounded-2xl border transition-all flex items-center justify-center shrink-0 ${
              isListening || status === 'LISTENING'
                ? 'bg-red-500/30 border-red-400 text-red-300 animate-pulse'
                : 'bg-white/5 hover:bg-cyan-500/20 border-white/10 text-cyan-300'
            }`}
            title="Speak to JARVIS"
            aria-label="Speak to JARVIS"
          >
            <Mic size={18} className={isListening ? 'animate-bounce' : ''} />
          </button>
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            aria-label="Message JARVIS"
            placeholder={pro ? 'Command JARVIS…' : 'Ask JARVIS to organize files, summarize a document, set a reminder, or search the web…'}
            className="w-full bg-black/50 border border-white/10 rounded-2xl py-4 pl-6 pr-14 text-white placeholder-gray-500 focus:outline-none focus:border-cyan-400/50 transition-all font-light text-sm"
          />
          <button type="submit" className="absolute right-4 p-2.5 rounded-xl bg-cyan-500/20 hover:bg-cyan-500/30 text-cyan-300" aria-label="Send">
            {pro ? <Terminal size={18} /> : <Sparkles size={16} />}
          </button>
        </div>
      </form>
    </>
  )
}
