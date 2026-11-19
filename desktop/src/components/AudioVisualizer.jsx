import { motion, AnimatePresence } from 'framer-motion'

export default function AudioVisualizer({ status }) {
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
