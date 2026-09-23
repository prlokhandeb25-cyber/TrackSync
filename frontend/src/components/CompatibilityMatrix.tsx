import React, { useState } from 'react'

interface CompatibilityVerdict {
  value: string
  reason: string
  rule_id: string
  zone_relation: string
}

interface TaskItem {
  id: string
  department: string
  task_type: string
  section_id: string
}

interface MatrixProps {
  matrix: { [key: string]: { [key: string]: CompatibilityVerdict } }
  tasks: TaskItem[]
}

export const CompatibilityMatrixView: React.FC<MatrixProps> = ({ matrix, tasks }) => {
  const [isManualMode, setIsManualMode] = useState(false)
  const [hoveredCell, setHoveredCell] = useState<{ t1: string; t2: string; verdict: CompatibilityVerdict } | null>(null)

  const getCellBg = (value: string) => {
    if (isManualMode) {
      return 'bg-amber-950/40 border-amber-800/50 text-amber-300'
    }
    switch (value) {
      case 'COMPATIBLE': return 'bg-emerald-950/60 border-emerald-700/50 text-emerald-400'
      case 'REQUIRES_IWP': return 'bg-amber-950/60 border-amber-700/50 text-amber-400'
      case 'INCOMPATIBLE': return 'bg-rose-950/60 border-rose-700/50 text-rose-400'
      default: return 'bg-slate-800 border-slate-700 text-slate-400'
    }
  }

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-xl">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between mb-4 gap-3">
        <div>
          <h2 className="text-lg font-semibold text-white flex items-center gap-2">
            Automated Department Compatibility Matrix
          </h2>
          <p className="text-xs text-slate-400">Rules R0–R4 cross-department geometric resolution (S&T, OWD, PWI)</p>
        </div>

        <div className="flex items-center gap-2 bg-slate-950 p-1 rounded-lg border border-slate-800 text-xs">
          <button
            onClick={() => setIsManualMode(false)}
            className={`px-3 py-1.5 rounded-md font-medium transition-all ${!isManualMode ? 'bg-indigo-600 text-white shadow' : 'text-slate-400 hover:text-slate-200'}`}
          >
            RailBlock AI (Automated)
          </button>
          <button
            onClick={() => setIsManualMode(true)}
            className={`px-3 py-1.5 rounded-md font-medium transition-all ${isManualMode ? 'bg-amber-600 text-white shadow' : 'text-slate-400 hover:text-slate-200'}`}
          >
            Manual Coordination (Today)
          </button>
        </div>
      </div>

      <div className="mb-4 p-3 rounded-lg border text-xs flex items-center justify-between bg-slate-950 border-slate-800">
        <div>
          <span className="font-semibold text-slate-300">Mode: </span>
          <span className={isManualMode ? "text-amber-400 font-bold" : "text-emerald-400 font-bold"}>
            {isManualMode ? "Manual Phone/Meeting Negotiations" : "Computed Geometric Compatibility Matrix"}
          </span>
        </div>
        <div>
          <span className="font-semibold text-slate-300">Estimated Coordination Time: </span>
          <span className={isManualMode ? "text-rose-400 font-bold" : "text-emerald-400 font-bold"}>
            {isManualMode ? "~4.0 Hours per conflict" : "< 0.012 Seconds"}
          </span>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-xs text-center border-collapse">
          <thead>
            <tr>
              <th className="p-2 border border-slate-800 bg-slate-950 text-slate-400 font-medium">Active Tasks</th>
              {tasks.map(t => (
                <th key={t.id} className="p-2 border border-slate-800 bg-slate-950 text-slate-300 font-mono text-[11px]">
                  <div>{t.id}</div>
                  <div className="text-[10px] text-slate-500">{t.department}</div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {tasks.map(t1 => (
              <tr key={t1.id}>
                <td className="p-2 border border-slate-800 bg-slate-950 text-slate-300 font-mono text-left text-[11px]">
                  <div>{t1.id} ({t1.department})</div>
                  <div className="text-[10px] text-slate-500">{t1.section_id}</div>
                </td>
                {tasks.map(t2 => {
                  const verdict = matrix[t1.id]?.[t2.id] || { value: 'COMPATIBLE', reason: 'Compatible', rule_id: 'R4', zone_relation: 'DISJOINT' }
                  return (
                    <td
                      key={t2.id}
                      onMouseEnter={() => setHoveredCell({ t1: t1.id, t2: t2.id, verdict })}
                      onMouseLeave={() => setHoveredCell(null)}
                      className={`p-2 border font-medium cursor-pointer transition-all hover:scale-105 ${getCellBg(verdict.value)}`}
                    >
                      {isManualMode ? 'MANUAL' : verdict.value === 'COMPATIBLE' ? 'COMPAT' : verdict.value === 'REQUIRES_IWP' ? 'IWP' : 'INCOMP'}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-4 p-3 bg-slate-950 rounded-lg border border-slate-800 text-xs min-h-[50px] flex items-center">
        {hoveredCell ? (
          <div>
            <span className="font-semibold text-indigo-400">[{hoveredCell.verdict.rule_id}] </span>
            <span className="text-slate-200">{hoveredCell.verdict.reason}</span>
            <span className="ml-2 text-slate-500 font-mono text-[11px]">({hoveredCell.verdict.zone_relation})</span>
          </div>
        ) : (
          <p className="text-slate-500 italic">Hover any matrix cell to inspect automated rule rationale and geometry relation.</p>
        )}
      </div>
    </div>
  )
}
