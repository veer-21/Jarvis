import { BrainCircuit } from 'lucide-react'

export default function AgentDashboard({ activeAgent, status }) {
  const agents = [
    { name: 'Planner', desc: 'Understands and plans your request' },
    { name: 'Security', desc: 'Command safety validation' },
    { name: 'Memory', desc: 'Context retrieval & summary' },
    { name: 'Tools', desc: 'Runs actions on your PC' },
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
