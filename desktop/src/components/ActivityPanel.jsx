import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { History, X, CheckCircle2, XCircle, ShieldAlert, ShieldCheck, RefreshCw } from 'lucide-react'
import { api } from '../api'

const TOOL_LABELS = {
  create_reminder_or_timer: 'set a reminder',
  list_and_manage_reminders: 'checked your reminders',
  manage_personal_notes_and_todos: 'updated your to-dos',
  web_search: 'searched the web',
  search_news: 'searched the news',
  fetch_webpage: 'read a web page',
  read_and_summarize_webpage: 'summarized a web page',
  get_weather: 'checked the weather',
  read_file: 'read a file',
  write_file: 'wrote a file',
  safe_delete_file: 'deleted a file',
  list_directory: 'listed a folder',
  search_in_files: 'searched your files',
  open_application: 'opened an app',
  smart_organize_folder: 'organized a folder',
  undo_folder_organization: 'undid a folder organization',
  generate_daily_briefing: 'prepared your briefing',
  smart_clipboard_assistant: 'used the clipboard',
  compose_and_launch_message: 'drafted a message',
  get_system_info: 'checked system status',
  take_screenshot: 'took a screenshot',
  execute_command: 'ran a system command',
  repl_execute_python: 'ran Python code',
  repl_execute_powershell: 'ran PowerShell code',
  control_windows_setting: 'changed a Windows setting',
}

const label = (tool) => TOOL_LABELS[tool] || String(tool || 'an action').replace(/_/g, ' ')

function describe(entry) {
  const what = label(entry.tool)
  if (entry.kind === 'tool')
    return { icon: entry.ok ? CheckCircle2 : XCircle, tone: entry.ok ? 'text-emerald-400' : 'text-amber-300', text: entry.ok ? `JARVIS ${what}` : `Tried but failed: ${what}` }
  if (entry.kind === 'blocked') return { icon: ShieldAlert, tone: 'text-red-400', text: `Blocked: ${what}` }
  if (entry.kind === 'permission')
    return {
      icon: ShieldCheck,
      tone: entry.approved ? 'text-cyan-300' : 'text-gray-400',
      text: `You ${entry.approved ? 'allowed' : 'denied'}: ${what}${entry.always_allow ? ' (always)' : ''}`,
    }
  return { icon: History, tone: 'text-gray-400', text: entry.kind }
}

/** Everything JARVIS did on this computer, newest first. */
export default function ActivityPanel({ isOpen, token, onClose }) {
  const [entries, setEntries] = useState([])
  const [error, setError] = useState('')
  const [expanded, setExpanded] = useState(null)

  const load = async () => {
    try {
      const data = await api('/activity?limit=200', { token })
      setEntries(data.entries || [])
      setError('')
    } catch (e) {
      setError(e.message)
    }
  }

  useEffect(() => {
    if (isOpen) load()
  }, [isOpen])

  if (!isOpen) return null
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-6 bg-black/70 backdrop-blur-xl" style={{ WebkitAppRegion: 'no-drag' }}>
      <motion.div
        initial={{ opacity: 0, scale: 0.97 }}
        animate={{ opacity: 1, scale: 1 }}
        className="w-full max-w-2xl max-h-[90vh] bg-zinc-950/95 border border-white/10 rounded-3xl p-8 text-white flex flex-col gap-4"
        role="dialog"
        aria-label="Activity"
      >
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold flex items-center gap-2">
            <History size={18} className="text-cyan-400" /> Activity
          </h2>
          <div className="flex items-center gap-3">
            <button onClick={load} className="text-gray-400 hover:text-cyan-300" title="Refresh">
              <RefreshCw size={15} />
            </button>
            <button onClick={onClose} className="text-gray-400 hover:text-white" title="Close">
              <X size={18} />
            </button>
          </div>
        </div>
        <p className="text-[11px] text-gray-500">Every action JARVIS took on this PC. Arguments are shown with secrets hidden.</p>
        {error && <p className="text-xs text-amber-300">{error}</p>}
        <div className="flex-1 overflow-y-auto flex flex-col gap-1.5 select-text">
          {entries.length === 0 && <p className="text-xs text-gray-500">Nothing yet.</p>}
          {entries.map((entry, i) => {
            const d = describe(entry)
            const Icon = d.icon
            return (
              <button
                key={`${entry.ts}-${i}`}
                onClick={() => setExpanded(expanded === i ? null : i)}
                className="text-left bg-white/5 hover:bg-white/10 rounded-xl px-3 py-2 text-xs"
              >
                <div className="flex items-center justify-between gap-3">
                  <span className={`flex items-center gap-2 ${d.tone}`}>
                    <Icon size={13} /> <span className="text-gray-200">{d.text}</span>
                  </span>
                  <span className="text-[10px] text-gray-500 font-mono shrink-0">{new Date(entry.ts).toLocaleString()}</span>
                </div>
                {expanded === i && (
                  <pre className="mt-2 text-[10px] text-gray-400 whitespace-pre-wrap break-all">{JSON.stringify(entry, null, 2)}</pre>
                )}
              </button>
            )
          })}
        </div>
      </motion.div>
    </div>
  )
}
