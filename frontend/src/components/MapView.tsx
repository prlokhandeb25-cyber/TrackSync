import { useMemo } from 'react'
import type { NetworkData, TrainDot } from '../api'

/* Geographic SVG drawn from the real station coordinates - no map tiles, so nothing here
   can fail on a conference wifi during the demo. Sections are coloured by track status,
   which is the only place colour carries meaning. */

const W = 760
const H = 470
const PAD = 46

const STATUS_COLOR: Record<string, string> = {
  FIT: 'var(--fit)',
  SICK: 'var(--sick)',
  CAUTION_ORDER: 'var(--caution)',
  STOP_AND_START: 'var(--stopstart)',
}

export default function MapView({
  net, trains, totalActive, truncated, clock, selected, onSelect,
}: {
  net: NetworkData
  trains: TrainDot[]
  totalActive: number
  truncated: number
  clock: string
  selected: string | null
  onSelect: (id: string | null) => void
}) {
  const project = useMemo(() => {
    const lats = net.stations.map(s => s.lat)
    const lons = net.stations.map(s => s.lon)
    const minLat = Math.min(...lats), maxLat = Math.max(...lats)
    const minLon = Math.min(...lons), maxLon = Math.max(...lons)
    // Keep the corridor's real aspect ratio: latitude degrees are ~1.06x longitude at 19N,
    // and squashing it would misrepresent the geography for no gain.
    const spanLon = Math.max(1e-6, maxLon - minLon)
    const spanLat = Math.max(1e-6, maxLat - minLat)
    const scale = Math.min((W - PAD * 2) / spanLon, (H - PAD * 2) / spanLat)
    const ox = (W - spanLon * scale) / 2
    const oy = (H - spanLat * scale) / 2
    return (lat: number, lon: number): [number, number] => [
      ox + (lon - minLon) * scale,
      oy + (maxLat - lat) * scale,
    ]
  }, [net])

  const byCode = useMemo(
    () => Object.fromEntries(net.stations.map(s => [s.code, s])), [net])

  return (
    <div className="map-wrap">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Corridor map with live train positions">
        <rect x={0} y={0} width={W} height={H} fill="#0a0e14" />

        {/* sections, coloured by track status */}
        {net.sections.map(sec => {
          const a = byCode[sec.from], b = byCode[sec.to]
          if (!a || !b) return null
          const [x1, y1] = project(a.lat, a.lon)
          const [x2, y2] = project(b.lat, b.lon)
          const on = selected === sec.id
          return (
            <g key={sec.id} onClick={() => onSelect(on ? null : sec.id)} style={{ cursor: 'pointer' }}>
              <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="transparent" strokeWidth={14} />
              <line
                x1={x1} y1={y1} x2={x2} y2={y2}
                stroke={STATUS_COLOR[sec.status] ?? 'var(--fit)'}
                strokeWidth={sec.status === 'FIT' ? (on ? 5 : 3) : (on ? 6 : 4.5)}
                strokeLinecap="round"
                opacity={sec.status === 'FIT' ? 0.55 : 0.95}
              />
            </g>
          )
        })}

        {/* stations: size by tier, so the busy ones read first */}
        {net.stations.map(st => {
          const [x, y] = project(st.lat, st.lon)
          const r = st.tier === 'TIER_1' ? 5 : st.tier === 'TIER_2' ? 3.6 : 2.8
          const major = st.tier === 'TIER_1' || st.junction
          return (
            <g key={st.code}>
              <circle cx={x} cy={y} r={r} fill="#0a0e14" stroke="var(--text-dim)" strokeWidth={1.4} />
              {major && (
                <text x={x + r + 5} y={y + 3.5} fontSize={9.5} fill="var(--text-dim)"
                      fontFamily="var(--mono)">{st.code}</text>
              )}
            </g>
          )
        })}

        {/* trains: shape first, colour second, so the map stays legible */}
        {trains.map(t => {
          const [x, y] = project(t.lat, t.lon)
          if (t.cls === 'SUBURBAN_LOCAL')
            return <circle key={t.id} cx={x} cy={y} r={2.9} fill="var(--accent)" opacity={0.95} />
          if (t.cls === 'FREIGHT_MAIL')
            return <rect key={t.id} x={x - 3} y={y - 3} width={6} height={6}
                         fill="#c9d4e0" opacity={0.95} />
          return (
            <g key={t.id}>
              <circle cx={x} cy={y} r={4.6} fill="none" stroke="#e6edf3" strokeWidth={1.1} opacity={0.75} />
              <circle cx={x} cy={y} r={2.3} fill="#e6edf3" />
            </g>
          )
        })}

        <text x={PAD - 14} y={26} fontSize={12} fill="var(--text-dim)" fontFamily="var(--mono)">
          {clock}
        </text>
        <text x={W - PAD + 14} y={26} fontSize={11} fill="var(--text-mute)"
              fontFamily="var(--mono)" textAnchor="end">
          {totalActive} services running{truncated > 0 ? ` · +${truncated} not drawn` : ''}
        </text>
      </svg>

      <div className="legend">
        <span><i className="dot" style={{ background: 'var(--accent)' }} />Suburban local</span>
        <span><i className="dot" style={{ background: '#e6edf3' }} />Intercity / mail</span>
        <span><i style={{ background: 'var(--text-dim)' }} />Freight</span>
        <span style={{ marginLeft: 'auto' }}><i style={{ background: 'var(--fit)' }} />Fit</span>
        <span><i style={{ background: 'var(--sick)' }} />Sick</span>
        <span><i style={{ background: 'var(--caution)' }} />Caution order</span>
        <span><i style={{ background: 'var(--stopstart)' }} />Stop and start</span>
      </div>
    </div>
  )
}
