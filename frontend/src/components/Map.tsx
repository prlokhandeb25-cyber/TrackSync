import React from 'react'

interface Station {
  id: string
  name: string
  lat: number
  lon: number
  tier: string
}

interface Section {
  id: string
  from_station: string
  to_station: string
  status: string
}

interface TrainPosition {
  train_id: string
  train_number: string
  train_class: string
  station_name: string
  lat: number
  lon: number
  status: string
}

interface MapProps {
  stations: Station[]
  sections: Section[]
  trainPositions: TrainPosition[]
}

export const MapComponent: React.FC<MapProps> = ({ stations, sections, trainPositions }) => {
  const getStatusColor = (status: string) => {
    switch (status) {
      case 'FIT': return '#10b981'
      case 'SICK': return '#f59e0b'
      case 'CAUTION_ORDER': return '#f97316'
      case 'STOP_AND_START': return '#ef4444'
      case 'BLOCK_ACTIVE': return '#8b5cf6'
      default: return '#10b981'
    }
  }

  const stationXMap: { [key: string]: number } = {
    "CSMT": 50, "BYC": 110, "DR": 170, "CLA": 230, "GC": 290,
    "TNA": 360, "DI": 430, "KYN": 500, "ABH": 570, "BUD": 630,
    "VGI": 690, "SHLU": 750, "NRL": 810, "BVS": 870, "KJT": 930
  }

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 shadow-xl">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-lg font-semibold text-white flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 animate-pulse"></span>
            Live Corridor Map — Central Main Line (CSMT ↔ Karjat)
          </h2>
          <p className="text-xs text-slate-400">Section Track Statuses & Real-Time Service Occupancy</p>
        </div>
        <div className="flex items-center gap-3 text-xs">
          <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full bg-emerald-500"></span> FIT</span>
          <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full bg-amber-500"></span> SICK (TSR 30)</span>
          <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full bg-orange-500"></span> CAUTION</span>
          <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full bg-red-500"></span> STOP & START</span>
          <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full bg-purple-500"></span> BLOCK ACTIVE</span>
        </div>
      </div>

      <div className="relative w-full h-48 bg-slate-950 rounded-lg overflow-x-auto border border-slate-800 flex items-center px-4">
        <svg viewBox="0 0 1000 160" className="w-full h-full min-w-[800px]">
          {sections.map((sec) => {
            const x1 = stationXMap[sec.from_station] || 50
            const x2 = stationXMap[sec.to_station] || 100
            const strokeColor = getStatusColor(sec.status)

            return (
              <g key={sec.id}>
                <line
                  x1={x1}
                  y1={80}
                  x2={x2}
                  y2={80}
                  stroke={strokeColor}
                  strokeWidth={6}
                  strokeLinecap="round"
                  className="transition-colors duration-500"
                />
                <line
                  x1={x1}
                  y1={92}
                  x2={x2}
                  y2={92}
                  stroke={strokeColor}
                  strokeWidth={3}
                  strokeDasharray="4 2"
                  opacity={0.7}
                />
              </g>
            )
          })}

          {stations.map((st) => {
            const cx = stationXMap[st.id] || 50
            const isTier1 = st.tier === 'TIER_1'

            return (
              <g key={st.id} className="cursor-pointer group">
                <circle
                  cx={cx}
                  cy={80}
                  r={isTier1 ? 8 : 5}
                  fill={isTier1 ? "#6366f1" : "#cbd5e1"}
                  stroke="#0f172a"
                  strokeWidth={2}
                />
                <text
                  x={cx}
                  y={115}
                  textAnchor="middle"
                  fill="#94a3b8"
                  fontSize={10}
                  fontWeight={isTier1 ? "bold" : "normal"}
                  className="group-hover:fill-white transition-colors"
                >
                  {st.id}
                </text>
              </g>
            )
          })}

          {trainPositions.map((tp, idx) => {
            const cx = stationXMap[tp.station_name] || (100 + (idx * 60) % 800)
            const isSuburban = tp.train_class === 'SUBURBAN_LOCAL'

            return (
              <g key={`${tp.train_id}-${idx}`}>
                {isSuburban ? (
                  <circle cx={cx} cy={74} r={4} fill="#38bdf8" stroke="#0284c7" strokeWidth={1} />
                ) : (
                  <rect x={cx - 5} y={69} width={10} height={10} fill="#f43f5e" rx={2} />
                )}
              </g>
            )
          })}
        </svg>
      </div>
    </div>
  )
}
