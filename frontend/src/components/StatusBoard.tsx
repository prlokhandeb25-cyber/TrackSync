import React from 'react'

interface EventEntry {
  timestamp_sim: string
  message: string
  category: string
}

interface StatusBoardProps {
  events: EventEntry[]
}

export const StatusBoard: React.FC<StatusBoardProps> = ({ events }) => {
  const getBadgeStyle = (category: string) => {
    switch (category) {
      case 'BLOCK': return 'bg-purple-500/10 text-purple-400 border-purple-500/20'
      case 'DEFECT': return 'bg-amber-500/10 text-amber-400 border-amber-500/20'
      case 'REPLAN': return 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
      default: return 'bg-slate-500/10 text-slate-400 border-slate-500/20'
    }
  }

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 shadow-xl flex flex-col h-full">
      <div className="flex items-center justify-between mb-3 border-b border-slate-800 pb-2">
        <h3 className="text-sm font-semibold text-white flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-indigo-500"></span>
          Natural-Language Control Office Feed
        </h3>
        <span className="text-xs text-slate-500">{events.length} logs recorded</span>
      </div>

      <div className="flex-1 overflow-y-auto space-y-2 max-h-64 pr-1">
        {events.length === 0 ? (
          <p className="text-xs text-slate-500 italic">No event logs recorded yet.</p>
        ) : (
          events.slice().reverse().map((ev, idx) => (
            <div key={idx} className="bg-slate-950/70 border border-slate-800 rounded-lg p-2.5 text-xs text-slate-300">
              <div className="flex items-center justify-between mb-1">
                <span className="font-mono text-slate-400 text-[11px]">{ev.timestamp_sim}</span>
                <span className={`px-1.5 py-0.5 rounded border text-[10px] uppercase font-semibold ${getBadgeStyle(ev.category)}`}>
                  {ev.category}
                </span>
              </div>
              <p className="text-slate-200 leading-relaxed">{ev.message}</p>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
