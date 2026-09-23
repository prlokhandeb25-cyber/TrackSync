import React, { useState, useEffect } from 'react'
import { MapComponent } from './components/Map'
import { StatusBoard } from './components/StatusBoard'
import { CompatibilityMatrixView } from './components/CompatibilityMatrix'
import { TaskPool } from './components/TaskPool'
import { DemandInjection } from './components/DemandInjection'
import { RLComparison } from './components/RLComparison'
import { ImpactTab } from './components/ImpactTab'

export default function App() {
  const [activeTab, setActiveTab] = useState<'map' | 'matrix' | 'demand' | 'rl' | 'impact'>('map')
  const [simState, setSimState] = useState<any>({
    sim_time_str: 'Mon 08:30',
    is_running: false,
    speed_multiplier: 1.0,
    sections: [],
    train_positions: [],
    active_tasks: [],
    recent_events: []
  })
  const [matrixData, setMatrixData] = useState<any>({ matrix: {}, active_tasks: [] })
  const [impactData, setImpactData] = useState<any>({})
  const [rlData, setRlData] = useState<any[]>([])

  // WebSocket connection for live sim streaming
  useEffect(() => {
    const ws = new WebSocket(`ws://${window.location.host}/ws/state`)
    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        setSimState(data)
      } catch (e) {
        console.error(e)
      }
    }
    return () => ws.close()
  }, [])

  // Fetch initial API REST endpoints
  useEffect(() => {
    fetch('/api/compatibility/matrix')
      .then(res => res.json())
      .then(data => setMatrixData(data))
      .catch(err => console.error(err))

    fetch('/api/metrics/impact')
      .then(res => res.json())
      .then(data => setImpactData(data.metrics || {}))
      .catch(err => console.error(err))

    fetch('/api/rl/comparison')
      .then(res => res.json())
      .then(data => setRlData(data.rows || []))
      .catch(err => console.error(err))
  }, [])

  const handleSimControl = (action: string, speed?: number) => {
    fetch('/api/sim/control', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, speed_multiplier: speed || 1.0 })
    })
      .then(res => res.json())
      .then(data => setSimState(data))
      .catch(err => console.error(err))
  }

  const handleDemandInject = async (sectionId: string, department: string) => {
    const res = await fetch('/api/tasks/demand', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ section_id: sectionId, department })
    })
    const data = await res.json()
    // Refresh compatibility matrix
    fetch('/api/compatibility/matrix').then(r => r.json()).then(d => setMatrixData(d))
    return data
  }

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans">
      {/* Top Header */}
      <header className="bg-slate-900 border-b border-slate-800 px-6 py-3 flex flex-col sm:flex-row items-center justify-between gap-4 sticky top-0 z-50">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-indigo-600 to-purple-500 flex items-center justify-center font-bold text-white shadow-lg">
            RB
          </div>
          <div>
            <h1 className="text-base font-bold text-white tracking-wide">RailBlock AI</h1>
            <p className="text-xs text-slate-400">Automatic Block Planning for Indian Railways</p>
          </div>
        </div>

        {/* Live Controls & Sim Status Header */}
        <div className="flex items-center gap-4 text-xs">
          <div className="bg-slate-950 border border-slate-800 rounded-lg px-3 py-1.5 flex items-center gap-2">
            <span className="text-slate-400">Sim Clock:</span>
            <span className="font-mono font-bold text-indigo-400">{simState.sim_time_str}</span>
          </div>

          <div className="flex items-center gap-1 bg-slate-950 p-1 rounded-lg border border-slate-800">
            <button
              onClick={() => handleSimControl(simState.is_running ? 'pause' : 'play')}
              className={`px-3 py-1 rounded font-semibold transition-all ${simState.is_running ? 'bg-amber-600 text-white' : 'bg-emerald-600 text-white'}`}
            >
              {simState.is_running ? 'Pause Sim' : 'Play Sim'}
            </button>
            <button
              onClick={() => handleSimControl('speed', 4.0)}
              className="px-2 py-1 rounded text-slate-400 hover:text-white transition-all font-mono"
            >
              4x
            </button>
            <button
              onClick={() => handleSimControl('speed', 16.0)}
              className="px-2 py-1 rounded text-slate-400 hover:text-white transition-all font-mono"
            >
              16x
            </button>
          </div>
        </div>
      </header>

      {/* Navigation Tabs */}
      <div className="bg-slate-900/60 border-b border-slate-800 px-6 py-2 flex items-center gap-2 overflow-x-auto text-xs">
        <button
          onClick={() => setActiveTab('map')}
          className={`px-4 py-2 rounded-lg font-medium transition-all ${activeTab === 'map' ? 'bg-indigo-600 text-white shadow-lg' : 'text-slate-400 hover:bg-slate-800/60 hover:text-slate-200'}`}
        >
          Live Corridor Map & Events
        </button>
        <button
          onClick={() => setActiveTab('matrix')}
          className={`px-4 py-2 rounded-lg font-medium transition-all ${activeTab === 'matrix' ? 'bg-indigo-600 text-white shadow-lg' : 'text-slate-400 hover:bg-slate-800/60 hover:text-slate-200'}`}
        >
          Department Compatibility Matrix
        </button>
        <button
          onClick={() => setActiveTab('demand')}
          className={`px-4 py-2 rounded-lg font-medium transition-all ${activeTab === 'demand' ? 'bg-rose-600 text-white shadow-lg' : 'text-slate-400 hover:bg-slate-800/60 hover:text-slate-200'}`}
        >
          ⚡ Demand Defect Injection Demo
        </button>
        <button
          onClick={() => setActiveTab('rl')}
          className={`px-4 py-2 rounded-lg font-medium transition-all ${activeTab === 'rl' ? 'bg-indigo-600 text-white shadow-lg' : 'text-slate-400 hover:bg-slate-800/60 hover:text-slate-200'}`}
        >
          Offline RL Benchmarks
        </button>
        <button
          onClick={() => setActiveTab('impact')}
          className={`px-4 py-2 rounded-lg font-medium transition-all ${activeTab === 'impact' ? 'bg-emerald-600 text-white shadow-lg' : 'text-slate-400 hover:bg-slate-800/60 hover:text-slate-200'}`}
        >
          Before/After Impact (J5)
        </button>
      </div>

      {/* Main Content Body */}
      <main className="flex-1 p-6 space-y-6 max-w-7xl w-full mx-auto">
        {activeTab === 'map' && (
          <div className="space-y-6">
            <MapComponent
              stations={simState.stations.length ? simState.stations : [
                { id: "CSMT", name: "CSMT", lat: 18.9400, lon: 72.8353, tier: "TIER_1" },
                { id: "BYC", name: "Byculla", lat: 18.9744, lon: 72.8324, tier: "TIER_2" },
                { id: "DR", name: "Dadar", lat: 19.0178, lon: 72.8478, tier: "TIER_1" },
                { id: "CLA", name: "Kurla", lat: 19.0650, lon: 72.8794, tier: "TIER_1" },
                { id: "GC", name: "Ghatkopar", lat: 19.0864, lon: 72.9081, tier: "TIER_2" },
                { id: "TNA", name: "Thane", lat: 19.1860, lon: 72.9759, tier: "TIER_1" },
                { id: "DI", name: "Dombivli", lat: 19.2184, lon: 73.0867, tier: "TIER_2" },
                { id: "KYN", name: "Kalyan", lat: 19.2354, lon: 73.1306, tier: "TIER_1" },
                { id: "ABH", name: "Ambernath", lat: 19.1994, lon: 73.1950, tier: "TIER_2" },
                { id: "BUD", name: "Badlapur", lat: 19.1656, lon: 73.2325, tier: "TIER_2" },
                { id: "VGI", name: "Vangani", lat: 19.1123, lon: 73.2845, tier: "TIER_3" },
                { id: "SHLU", name: "Shelu", lat: 19.0765, lon: 73.3102, tier: "TIER_3" },
                { id: "NRL", name: "Neral", lat: 19.0300, lon: 73.3180, tier: "TIER_3" },
                { id: "BVS", name: "Bhivpuri Road", lat: 18.9760, lon: 73.3150, tier: "TIER_3" },
                { id: "KJT", name: "Karjat", lat: 18.9100, lon: 73.3300, tier: "TIER_2" }
              ]}
              sections={simState.sections}
              trainPositions={simState.train_positions}
            />

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <StatusBoard events={simState.recent_events} />
              <TaskPool tasks={simState.active_tasks} />
            </div>
          </div>
        )}

        {activeTab === 'matrix' && (
          <CompatibilityMatrixView
            matrix={matrixData.matrix}
            tasks={matrixData.active_tasks || []}
          />
        )}

        {activeTab === 'demand' && (
          <DemandInjection onInject={handleDemandInject} />
        )}

        {activeTab === 'rl' && (
          <RLComparison rows={rlData} />
        )}

        {activeTab === 'impact' && (
          <ImpactTab metrics={impactData} />
        )}
      </main>

      {/* Bottom Footer */}
      <footer className="border-t border-slate-800 px-6 py-3 text-center text-xs text-slate-500">
        RailBlock AI — Smart India Hackathon Prototype · Powered by OR-Tools CP-SAT & Offline RL (CQL-DQN)
      </footer>
    </div>
  )
}
