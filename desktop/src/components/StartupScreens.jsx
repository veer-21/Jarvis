import { motion } from 'framer-motion'
import { Lock, Loader2, PlugZap, RefreshCw } from 'lucide-react'

export function StartingScreen({ seconds }) {
  return (
    <div className="flex h-screen w-full items-center justify-center p-8">
      <div className="glass-panel p-10 rounded-3xl flex flex-col items-center gap-4 border border-white/10 text-white">
        <Loader2 className="text-cyan-400 w-10 h-10 animate-spin" />
        <h2 className="text-lg font-light tracking-widest uppercase">Starting JARVIS</h2>
        <p className="text-xs text-gray-400">{seconds > 15 ? 'First start can take up to a minute while models load…' : 'Loading the assistant…'}</p>
      </div>
    </div>
  )
}

export function BackendUnavailableScreen({ onRetry, onOpenLogs }) {
  return (
    <div className="flex h-screen w-full items-center justify-center p-8">
      <div className="glass-panel p-10 rounded-3xl flex flex-col items-center gap-4 border border-amber-500/30 text-white max-w-md text-center">
        <PlugZap className="text-amber-400 w-10 h-10" />
        <h2 className="text-lg font-semibold">JARVIS could not start</h2>
        <p className="text-xs text-gray-300">
          The assistant engine did not respond. Try again; if it keeps failing, open the logs and send them with the “Export diagnostics” option.
        </p>
        <div className="flex gap-3">
          <button onClick={onRetry} className="px-5 py-2.5 rounded-xl bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 text-xs font-semibold flex items-center gap-1.5">
            <RefreshCw size={13} /> Try again
          </button>
          {onOpenLogs && (
            <button onClick={onOpenLogs} className="px-5 py-2.5 rounded-xl bg-white/5 text-gray-300 border border-white/10 text-xs">
              Open logs folder
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

export function LoginScreen({ pin, setPin, onSubmit, error }) {
  return (
    <div className="flex h-screen w-full items-center justify-center p-8 bg-transparent">
      <motion.form
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        onSubmit={onSubmit}
        className="glass-panel p-10 rounded-3xl flex flex-col items-center gap-5 border border-white/10"
      >
        <Lock className="text-cyan-400 w-12 h-12 mb-2" />
        <h2 className="text-xl font-light tracking-widest text-white uppercase">Unlock JARVIS</h2>
        <input
          type="password"
          autoFocus
          value={pin}
          onChange={(e) => setPin(e.target.value)}
          placeholder="PIN"
          aria-label="PIN"
          className="bg-black/40 border border-cyan-500/20 rounded-xl py-3 px-6 text-center text-white tracking-[0.5em] focus:outline-none focus:border-cyan-400/50"
        />
        {error && <p className="text-xs text-amber-300 max-w-xs text-center">{error}</p>}
        <button type="submit" className="w-full py-3 rounded-xl bg-cyan-500/20 text-cyan-300 hover:bg-cyan-500/30 tracking-widest text-sm font-semibold">
          UNLOCK
        </button>
        <p className="text-[10px] text-gray-500 max-w-xs text-center">No PIN set yet? Leave it empty and press Unlock, then set one in Settings.</p>
      </motion.form>
    </div>
  )
}
