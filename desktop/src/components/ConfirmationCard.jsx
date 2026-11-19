import { useState } from 'react'
import { motion } from 'framer-motion'
import { ShieldCheck, CheckCircle2, XCircle } from 'lucide-react'

const FRIENDLY_ACTIONS = {
  smart_organize_folder: 'Organize files in a folder',
  write_file: 'Write to a file',
  safe_delete_file: 'Delete a file',
  execute_command: 'Run a system command',
  repl_execute_python: 'Run Python code',
  repl_execute_powershell: 'Run PowerShell code',
  type_text: 'Type text into another app',
  press_key: 'Press keys in another app',
  open_url: 'Open a web page',
  fetch_webpage: 'Fetch a web page',
}

const HIGH_RISK = new Set(['HIGH_RISK', 'CRITICAL'])

// Asks the owner before JARVIS does something that changes their computer or sends data out.
export default function ConfirmationCard({ confirmation, onApprove, onDeny }) {
  const [alwaysAllow, setAlwaysAllow] = useState(false)
  if (!confirmation) return null
  const { confirmation_id, tool, parameters, risk_level, risk_reason, timeout_seconds } = confirmation
  const canAlwaysAllow = !HIGH_RISK.has(risk_level)

  const action = FRIENDLY_ACTIONS[tool] || `Use the "${tool}" tool`
  const reason =
    risk_reason ||
    (HIGH_RISK.has(risk_level)
      ? 'This could change system settings, run code or delete files. JARVIS needs your explicit OK.'
      : 'This will make a change on your computer. Please confirm.')

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.95, y: -20 }}
      animate={{ opacity: 1, scale: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.95, y: -20 }}
      role="alertdialog"
      aria-label="Permission request"
      className="absolute top-14 left-6 right-6 z-50 bg-black/95 backdrop-blur-2xl border border-amber-500/40 rounded-3xl p-6 shadow-[0_15px_45px_rgba(245,158,11,0.2)] flex flex-col gap-4 text-white"
      style={{ WebkitAppRegion: 'no-drag' }}
    >
      <div className="flex items-center justify-between border-b border-white/10 pb-3">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-full bg-amber-500/20 border border-amber-500/40 flex items-center justify-center text-amber-400">
            <ShieldCheck size={18} />
          </div>
          <div>
            <h3 className="text-sm font-semibold tracking-wide text-white">JARVIS needs your permission</h3>
            <p className="text-[11px] text-gray-400">
              Nothing happens until you decide{timeout_seconds ? ` (expires in ${timeout_seconds}s)` : ''}.
            </p>
          </div>
        </div>
        <span className="px-3 py-1 rounded-full text-[10px] font-bold font-mono tracking-widest bg-amber-500/20 text-amber-300 border border-amber-500/30 uppercase">
          {(risk_level || 'CONFIRM').replace('_', ' ')}
        </span>
      </div>

      <div className="bg-white/5 rounded-2xl p-4 border border-white/5 flex flex-col gap-2">
        <span className="text-xs font-semibold text-cyan-300">{action}</span>
        <p className="text-xs text-gray-200 leading-relaxed">{reason}</p>
      </div>

      {parameters && Object.keys(parameters).length > 0 && (
        <div className="bg-black/60 rounded-xl p-3 border border-white/5 font-mono text-[11px] max-h-40 overflow-y-auto">
          <p className="text-gray-500 text-[9px] uppercase tracking-wider mb-1">Exactly what will run</p>
          <pre className="text-gray-300 whitespace-pre-wrap break-all">{JSON.stringify(parameters, null, 2)}</pre>
        </div>
      )}

      <div className="flex items-center justify-between gap-3 pt-1">
        {canAlwaysAllow ? (
          <label className="flex items-center gap-2 text-[11px] text-gray-400 cursor-pointer">
            <input type="checkbox" checked={alwaysAllow} onChange={(e) => setAlwaysAllow(e.target.checked)} />
            Always allow this action
          </label>
        ) : (
          <span className="text-[11px] text-gray-500">High-risk actions always ask.</span>
        )}
        <div className="flex items-center gap-3">
          <button
            onClick={() => onDeny(confirmation_id)}
            className="px-5 py-2.5 rounded-xl bg-red-500/20 hover:bg-red-500/30 text-red-300 border border-red-500/30 text-xs font-semibold tracking-wider transition-colors flex items-center gap-1.5"
          >
            <XCircle size={14} />
            Don&apos;t allow
          </button>
          <button
            onClick={() => onApprove(confirmation_id, canAlwaysAllow && alwaysAllow)}
            className="px-6 py-2.5 rounded-xl bg-emerald-500/30 hover:bg-emerald-500/40 text-emerald-300 border border-emerald-500/40 text-xs font-semibold tracking-wider transition-all flex items-center gap-1.5"
          >
            <CheckCircle2 size={14} />
            Allow
          </button>
        </div>
      </div>
    </motion.div>
  )
}
