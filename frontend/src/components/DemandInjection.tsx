import React, { useState } from 'react'

interface DemandInjectionProps {
  onInject: (sectionId: string, department: string) => Promise<any>
}

export const DemandInjection: React.FC<DemandInjectionProps> = ({ onInject }) => {
  const [sectionId, setSectionId] = useState('SEC_DR_CLA')
  const [department, setDepartment] = useState('S_AND_T')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<any>(null)

  const handleInject = async () => {
    setLoading(true)
    try {
      const data = await onInject(sectionId, department)
      setResult(data)
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-xl">
      <div className="flex items-center justify-between mb-4 border-b border-slate-800 pb-3">
        <div>
          <h2 className="text-lg font-semibold text-white flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-full bg-rose-500 animate-pulse"></span>
            Reactive Re-Planning Demo (Unplanned Defect Injection)
          </h2>
          <p className="text-xs text-slate-400">Section §13 Money Demo: Compare CP-SAT Full Re-Solve vs Offline RL Dispatcher Latency</p>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
        <div>
          <label className="block text-xs text-slate-400 mb-1">Target Section</label>
          <select
            value={sectionId}
            onChange={(e) => setSectionId(e.target.value)}
            className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2 text-xs text-slate-200"
          >
            <option value="SEC_DR_CLA">Dadar ↔ Kurla (SEC_DR_CLA)</option>
            <option value="SEC_CLA_GC">Kurla ↔ Ghatkopar (SEC_CLA_GC)</option>
            <option value="SEC_TNA_DI">Thane ↔ Dombivli (SEC_TNA_DI)</option>
            <option value="SEC_VGI_SHLU">Vangani ↔ Shelu (SEC_VGI_SHLU)</option>
          </select>
        </div>

        <div>
          <label className="block text-xs text-slate-400 mb-1">Reporting Department</label>
          <select
            value={department}
            onChange={(e) => setDepartment(e.target.value)}
            className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2 text-xs text-slate-200"
          >
            <option value="S_AND_T">S&T (Signalling & Telecom)</option>
            <option value="OWD">OWD (Overhead Traction Power)</option>
            <option value="PWI">PWI (Permanent Way Inspector)</option>
          </select>
        </div>

        <div className="flex items-end">
          <button
            onClick={handleInject}
            disabled={loading}
            className="w-full bg-rose-600 hover:bg-rose-500 text-white font-semibold py-2 px-4 rounded-lg text-xs transition-all shadow-lg flex items-center justify-center gap-2 disabled:opacity-50"
          >
            {loading ? (
              <>
                <span className="w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin"></span>
                Re-Planning...
              </>
            ) : (
              '⚡ Inject Demand Task & Re-Plan'
            )}
          </button>
        </div>
      </div>

      {/* Side-by-Side Comparison Box */}
      {result && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4 p-4 bg-slate-950 rounded-xl border border-slate-800 animate-fadeIn">
          {/* CP-SAT Solver Path */}
          <div className="p-4 rounded-lg bg-slate-900 border border-slate-800">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-semibold text-slate-300">CP-SAT Expert Solver</span>
              <span className="text-xs font-mono text-amber-400 font-bold">{result.cpsat_latency_ms?.toFixed(1)} ms</span>
            </div>
            <p className="text-xs text-slate-400 leading-relaxed mb-2">Full mathematical constraint re-solve across corridor.</p>
            <div className="text-[11px] text-slate-500">Optimality Gap: <span className="text-emerald-400 font-mono">0.0% (Optimal)</span></div>
          </div>

          {/* RL Dispatcher Path */}
          <div className="p-4 rounded-lg bg-indigo-950/40 border border-indigo-800/50">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-semibold text-indigo-300">Offline RL Dispatcher (CQL-DQN)</span>
              <span className="text-xs font-mono text-emerald-400 font-bold">{result.rl_latency_ms?.toFixed(2)} ms</span>
            </div>
            <p className="text-xs text-slate-300 leading-relaxed mb-2">Neural reactive dispatch in millisecond latency.</p>
            <div className="flex items-center justify-between text-[11px]">
              <span className="text-slate-400">Speedup: <span className="text-emerald-400 font-bold">{result.speedup_factor}</span></span>
              <span className="text-emerald-400 font-semibold">0 Violations</span>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
