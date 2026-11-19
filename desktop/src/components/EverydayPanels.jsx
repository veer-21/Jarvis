import { Sparkles, CheckSquare, Clock } from 'lucide-react'

export const ROUTINES = [
  { title: 'Morning Briefing', desc: 'Weather, tasks, system stats', cmd: 'Give me my daily briefing', icon: '🌅' },
  { title: 'Organize Downloads', desc: 'Clean cluttered files safely', cmd: 'Preview organizing my Downloads folder', icon: '📁' },
  { title: 'Draft an Email', desc: 'Help me draft a professional email', cmd: 'Help me draft a professional email', icon: '✉️' },
  { title: 'Read My Screen', desc: 'Summarize active window', cmd: 'Read and summarize the text on my screen', icon: '🖥️' },
  { title: 'Show My To-Dos', desc: 'View & manage daily tasks', cmd: 'Show my personal to-do list and pending tasks', icon: '📝' },
  { title: 'Clipboard Helper', desc: 'Check clipboard & format', cmd: 'Check clipboard history and format text', icon: '📋' },
  { title: 'Quick Reminder', desc: 'Break timer in 15 mins', cmd: 'Remind me in 15 minutes to take a break', icon: '⏰' },
  { title: 'Health Check', desc: 'Speed, CPU & RAM status', cmd: "Check my computer's speed, CPU, and memory", icon: '⚡' },
]

export function RoutineCards({ onRun }) {
  return (
    <div className="p-6 pb-2 border-b border-white/5">
      <div className="flex items-center justify-between mb-3">
        <span className="text-[11px] font-semibold text-gray-300 flex items-center gap-1.5">
          <Sparkles size={13} className="text-cyan-400" />
          1-Click Daily Routines
        </span>
      </div>
      <div className="grid grid-cols-4 lg:grid-cols-8 gap-2.5">
        {ROUTINES.map((card) => (
          <button
            key={card.title}
            onClick={() => onRun(card.cmd)}
            className="flex flex-col text-left p-2.5 rounded-2xl bg-white/5 hover:bg-cyan-500/10 border border-white/5 hover:border-cyan-500/30 transition-all group"
          >
            <span className="text-lg mb-0.5">{card.icon}</span>
            <span className="text-xs font-semibold text-gray-200 group-hover:text-cyan-300 truncate">{card.title}</span>
            <span className="text-[10px] text-gray-500 line-clamp-1">{card.desc}</span>
          </button>
        ))}
      </div>
    </div>
  )
}

/** "My To-Dos" quick-add plus to-do and reminder chips. */
export function TodoReminderBar({ todos, reminders, newTodoText, setNewTodoText, handleAddTodo, handleCompleteTodo, handleDeleteTodo, cancelReminder }) {
  return (
    <div className="px-6 py-2.5 bg-cyan-950/20 border-b border-cyan-500/20 flex flex-col gap-2">
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-3 flex-1 min-w-0">
          <div className="flex items-center gap-1.5 text-cyan-400 text-xs font-semibold shrink-0">
            <CheckSquare size={13} />
            <span>My To-Dos ({todos.length}):</span>
          </div>
          <form onSubmit={handleAddTodo} className="flex items-center gap-1.5 flex-1 max-w-sm">
            <input
              type="text"
              value={newTodoText}
              onChange={(e) => setNewTodoText(e.target.value)}
              placeholder="+ Add quick task (press Enter)…"
              aria-label="Add a to-do"
              className="w-full bg-black/40 border border-cyan-500/20 focus:border-cyan-400/50 rounded-lg px-2.5 py-1 text-xs text-white placeholder-gray-500 focus:outline-none"
            />
          </form>
        </div>
        {reminders.length > 0 && (
          <div className="flex items-center gap-1.5 text-cyan-400 text-xs font-semibold shrink-0">
            <Clock size={13} />
            <span>Active Reminders ({reminders.length}):</span>
          </div>
        )}
      </div>

      <div className="flex items-center gap-2 overflow-x-auto py-0.5">
        {todos.length === 0 && reminders.length === 0 && (
          <span className="text-[11px] text-gray-500 italic">No pending to-dos or active reminders. Type a quick task above!</span>
        )}
        {todos.map((todo) => (
          <div key={todo.item_id} className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-cyan-500/10 border border-cyan-500/30 text-xs text-gray-200 shrink-0">
            <button onClick={() => handleCompleteTodo(todo.item_id)} title="Mark as done" className="w-4 h-4 rounded-full flex items-center justify-center text-cyan-400 hover:text-emerald-300 text-[10px] font-bold">
              ✓
            </button>
            <span className="font-medium max-w-[200px] truncate" title={todo.content || todo.title}>
              {todo.content || todo.title}
            </span>
            <button onClick={() => handleDeleteTodo(todo.item_id)} title="Delete task" className="w-4 h-4 rounded-full flex items-center justify-center text-gray-400 hover:text-red-400">
              ✕
            </button>
          </div>
        ))}
        {reminders.map((rem) => (
          <div key={rem.reminder_id} className="flex items-center gap-2 px-2.5 py-1 rounded-full bg-purple-500/10 border border-purple-500/30 text-xs text-purple-200 shrink-0">
            <Clock size={11} className="text-purple-400" />
            <span className="font-medium text-purple-100">{rem.title}</span>
            <span className="text-[10px] text-purple-300/80 font-mono">
              {rem.trigger_at ? new Date(rem.trigger_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : 'Pending'}
            </span>
            <button onClick={() => cancelReminder(rem.reminder_id)} title="Cancel reminder" className="w-4 h-4 rounded-full flex items-center justify-center text-gray-400 hover:text-red-400">
              ✕
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}

export function MetricsView({ metrics }) {
  return (
    <div className="flex-1 overflow-y-auto p-8 text-white select-text">
      <h2 className="text-xl font-light mb-6 tracking-widest uppercase text-cyan-400 font-mono border-b border-white/10 pb-2">System Metrics</h2>
      {metrics ? (
        <div className="grid grid-cols-2 gap-6">
          {[
            ['CPU Usage', `${metrics.cpu_percent}%`],
            ['RAM Usage', `${metrics.ram_used_gb} GB / ${metrics.ram_total_gb} GB`],
            ['Disk Usage', `${metrics.disk_percent}%`],
            ['Uptime', `${metrics.uptime_seconds}s`],
          ].map(([label, value]) => (
            <div key={label} className="bg-black/40 border border-white/5 p-6 rounded-2xl">
              <p className="text-gray-400 text-xs tracking-widest uppercase mb-2 font-mono">{label}</p>
              <p className="text-3xl font-light text-cyan-400">{value}</p>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-gray-500 font-mono text-sm animate-pulse">Loading metrics…</p>
      )}
    </div>
  )
}
