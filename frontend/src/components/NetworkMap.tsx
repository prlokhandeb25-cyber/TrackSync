import { useMemo, useState } from 'react'
import type { NetworkData, TrainDot, Station } from '../api'

/* Geographic SVG built from the station coordinates. No map tiles: nothing here can fail on
   conference wifi, and a map that always renders beats a prettier one that sometimes doesn't.

   Visual hierarchy is deliberate. The network is drawn in desaturated per-line tints because
   it is context; status is drawn bright on top because it is the message. A judge should see
   a calm network with a few hot spots, and know instantly where to look. */

const W = 980
const H = 620
const PAD = 54

const STATUS: Record<string, string> = {
  FIT: 'var(--fit)',
  SICK: 'var(--sick)',
  CAUTION_ORDER: 'var(--caution)',
  STOP_AND_START: 'var(--stopstart)',
}
const LINE_TINT: Record<string, string> = {
  CR: 'var(--l-CR)', WR: 'var(--l-WR)', HR: 'var(--l-HR)', TH: 'var(--l-TH)',
}
const LINE_NAME: Record<string, string> = {
  CR: 'Central', WR: 'Western', HR: 'Harbour', TH: 'Trans-Harbour',
}

export default function NetworkMap({
  net, trains, totalActive, truncated, clock, selected, onSelect, blocks,
}: {
  net: NetworkData
  trains: TrainDot[]
  totalActive: number
  truncated: number
  clock: string
  selected: string | null
  onSelect: (id: string | null) => void
  blocks: Set<string>
}) {
  const [hover, setHover] = useState<Station | null>(null)

  const project = useMemo(() => {
    const lats = net.stations.map(s => s.lat)
    const lons = net.stations.map(s => s.lon)
    const minLat = Math.min(...lats), maxLat = Math.max(...lats)
    const minLon = Math.min(...lons), maxLon = Math.max(...lons)
    // Latitude degrees are ~1.06x longitude at 19N. Correcting keeps the network's real
    // shape, which is what makes it recognisable as Mumbai rather than an abstract graph.
    const kLon = Math.cos((19 * Math.PI) / 180)
    const spanLon = Math.max(1e-6, (maxLon - minLon) * kLon)
    const spanLat = Math.max(1e-6, maxLat - minLat)
    const scale = Math.min((W - PAD * 2) / spanLon, (H - PAD * 2) / spanLat)
    const ox = (W - spanLon * scale) / 2
    const oy = (H - spanLat * scale) / 2
    return (lat: number, lon: number): [number, number] => [
      ox + (lon - minLon) * kLon * scale,
      oy + (maxLat - lat) * scale,
    ]
  }, [net])

  const byCode = useMemo(
    () => Object.fromEntries(net.stations.map(s => [s.code, s])) as Record<string, Station>,
    [net])

  const degraded = net.sections.filter(s => s.status !== 'FIT')
  const lines = [...new Set(net.sections.map(s => s.line_code).filter(Boolean))]

  return (
    <div className="map-wrap">
      <svg viewBox={`0 0 ${W} ${H}`} role="img"
           aria-label="Mumbai suburban network with live train positions and track status">
        <defs>
          <filter id="glow" x="-60%" y="-60%" width="220%" height="220%">
            <feGaussianBlur stdDeviation="3.2" result="b" />
            <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
        </defs>

        {/* base network — desaturated, it is context not message */}
        {net.sections.map(sec => {
          const a = byCode[sec.from], b = byCode[sec.to]
          if (!a || !b) return null
          const [x1, y1] = project(a.lat, a.lon)
          const [x2, y2] = project(b.lat, b.lon)
          return (
            <line key={`base-${sec.id}`} x1={x1} y1={y1} x2={x2} y2={y2}
                  stroke={LINE_TINT[sec.line_code] ?? '#3a4658'}
                  strokeWidth={selected === sec.id ? 6 : 3.4}
                  strokeLinecap="round" opacity={0.62} />
          )
        })}

        {/* status overlay — bright, only where something is wrong */}
        {degraded.map(sec => {
          const a = byCode[sec.from], b = byCode[sec.to]
          if (!a || !b) return null
          const [x1, y1] = project(a.lat, a.lon)
          const [x2, y2] = project(b.lat, b.lon)
          return (
            <line key={`st-${sec.id}`} x1={x1} y1={y1} x2={x2} y2={y2}
                  stroke={STATUS[sec.status]} strokeWidth={4.6} strokeLinecap="round"
                  filter="url(#glow)" opacity={0.95} />
          )
        })}

        {/* active maintenance blocks */}
        {net.sections.filter(s => blocks.has(s.id)).map(sec => {
          const a = byCode[sec.from], b = byCode[sec.to]
          if (!a || !b) return null
          const [x1, y1] = project(a.lat, a.lon)
          const [x2, y2] = project(b.lat, b.lon)
          return (
            <line key={`bl-${sec.id}`} x1={x1} y1={y1} x2={x2} y2={y2}
                  stroke="var(--block)" strokeWidth={7} strokeLinecap="round"
                  strokeDasharray="3 7" opacity={0.95}>
              <animate attributeName="stroke-dashoffset" from="20" to="0"
                       dur="1s" repeatCount="indefinite" />
            </line>
          )
        })}

        {/* clickable hit areas */}
        {net.sections.map(sec => {
          const a = byCode[sec.from], b = byCode[sec.to]
          if (!a || !b) return null
          const [x1, y1] = project(a.lat, a.lon)
          const [x2, y2] = project(b.lat, b.lon)
          return (
            <line key={`hit-${sec.id}`} x1={x1} y1={y1} x2={x2} y2={y2}
                  stroke="transparent" strokeWidth={15} style={{ cursor: 'pointer' }}
                  onClick={() => onSelect(selected === sec.id ? null : sec.id)} />
          )
        })}

        {/* stations — size by tier so the busy ones read first */}
        {net.stations.map(st => {
          const [x, y] = project(st.lat, st.lon)
          const interchange = (st.lines?.length ?? 0) > 1
          const r = interchange ? 5.4 : st.tier === 'TIER_1' ? 4.4 : st.tier === 'TIER_2' ? 3 : 2.3
          const label = interchange || st.tier === 'TIER_1'
          return (
            <g key={st.code} onMouseEnter={() => setHover(st)} onMouseLeave={() => setHover(null)}
               style={{ cursor: 'pointer' }}>
              <circle cx={x} cy={y} r={r + 5} fill="transparent" />
              <circle cx={x} cy={y} r={r} fill="#070a0f"
                      stroke={interchange ? 'var(--text)' : 'var(--text-dim)'}
                      strokeWidth={interchange ? 2 : 1.3} />
              {label && (
                <text x={x + r + 5} y={y + 3.4} fontSize={9.5}
                      fill={interchange ? 'var(--text)' : 'var(--text-dim)'}
                      fontFamily="var(--mono)"
                      fontWeight={interchange ? 600 : 400}>{st.code}</text>
              )}
            </g>
          )
        })}

        {/* trains — shape first, colour second, so density stays legible */}
        {trains.map(t => {
          const [x, y] = project(t.lat, t.lon)
          if (t.cls === 'SUBURBAN_LOCAL')
            return <circle key={t.id} cx={x} cy={y} r={2.5} fill="var(--accent)" opacity={0.92} />
          if (t.cls === 'FREIGHT_MAIL')
            return <rect key={t.id} x={x - 2.7} y={y - 2.7} width={5.4} height={5.4} rx={1}
                         fill="#cfdae6" opacity={0.92} />
          return (
            <g key={t.id}>
              <circle cx={x} cy={y} r={4.4} fill="none" stroke="#fff" strokeWidth={1} opacity={0.6} />
              <circle cx={x} cy={y} r={2.2} fill="#fff" />
            </g>
          )
        })}

        <text x={18} y={26} fontSize={12.5} fill="var(--text-dim)" fontFamily="var(--mono)">{clock}</text>
        <text x={W - 18} y={26} fontSize={11} fill="var(--text-mute)" fontFamily="var(--mono)"
              textAnchor="end">
          {totalActive} services running{truncated > 0 ? ` · +${truncated} not drawn` : ''}
        </text>

        {hover && (() => {
          const [x, y] = project(hover.lat, hover.lon)
          const right = x > W - 200
          return (
            <g transform={`translate(${right ? x - 196 : x + 12}, ${Math.min(y - 8, H - 80)})`}>
              <rect width={184} height={hover.lines && hover.lines.length > 1 ? 68 : 56} rx={7}
                    fill="#0b0f16" stroke="var(--line)" />
              <text x={11} y={19} fontSize={11.5} fill="var(--text)" fontWeight={600}>{hover.name}</text>
              <text x={11} y={35} fontSize={10} fill="var(--text-mute)" fontFamily="var(--mono)">
                {hover.code} · {hover.tier?.replace('_', ' ').toLowerCase()} · {hover.trains_per_day} trains/day
              </text>
              <text x={11} y={49} fontSize={10} fill={STATUS[hover.status]} fontFamily="var(--mono)">
                {hover.status.replace(/_/g, ' ').toLowerCase()}
              </text>
              {hover.lines && hover.lines.length > 1 && (
                <text x={11} y={62} fontSize={9.5} fill="var(--text-mute)">
                  interchange: {hover.lines.map(l => LINE_NAME[l] ?? l).join(' · ')}
                </text>
              )}
            </g>
          )
        })()}
      </svg>

      <div className="legend">
        {lines.map(l => (
          <span key={l}><i style={{ background: LINE_TINT[l] }} />{LINE_NAME[l] ?? l}</span>
        ))}
        <span className="sep" />
        <span><i className="dot" style={{ background: 'var(--accent)' }} />Local</span>
        <span><i className="dot" style={{ background: '#fff' }} />Intercity</span>
        <span><i style={{ background: '#cfdae6' }} />Freight</span>
        <span className="sep" />
        <span><i style={{ background: 'var(--sick)' }} />Sick</span>
        <span><i style={{ background: 'var(--caution)' }} />Caution order</span>
        <span><i style={{ background: 'var(--stopstart)' }} />Stop &amp; start</span>
        <span><i style={{ background: 'var(--block)' }} />Block active</span>
      </div>
    </div>
  )
}
