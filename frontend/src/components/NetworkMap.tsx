import { useEffect, useMemo, useRef, useState } from 'react'
import type { NetworkData, RerouteBlock, Station, TrainDot } from '../api'
import type { Halo } from './JobClusters'
import { MMR_BORDER, MUMBAI_CITY_BORDER } from '../data/mumbaiBorder'

/* The Mumbai Metropolitan Region drawn from its real OpenStreetMap boundary (cached locally, see
   scripts/07_build_mumbai_border.py), white inside, with the railway network on top through the
   SAME projection so every station sits where it really is. Each section is drawn as its real
   tracks - slow lines outside, fast inside, as on the division's system map - and trains run on
   their own track.

   Colour is chosen to read on white: one strong hue per line, black/orange/brown trains by class,
   hazard stripes for a closed track. Status (sick, caution, stop-and-start) is a wide translucent
   band underneath.

   Panning happens only while the button is held: the move and release listeners live on the
   window for the length of one drag, so a missed pointer-up can never leave the map following the
   cursor. */

const W = 980
const H = 620
const PAD = 40

const STATUS: Record<string, string> = {
  FIT: 'var(--fit)',
  SICK: 'var(--sick)',
  CAUTION_ORDER: 'var(--caution)',
  STOP_AND_START: 'var(--stopstart)',
}
export const LINE_COLOR: Record<string, string> = {
  CR: '#2563eb', WR: '#db2777', HR: '#15803d', TH: '#7c3aed',
}
const LINE_NAME: Record<string, string> = {
  CR: 'Central', WR: 'Western', HR: 'Harbour', TH: 'Trans-Harbour',
}
const TRAIN = { local: '#111827', intercity: '#f59e0b', freight: '#92400e', reroute: '#0891b2' }

// Physical track order across a section, outside to inside: slow lines outside, fast lines in the
// middle. Two-track sections are DN | UP.
const LANE_RANK: Record<string, number> = {
  DN_SLOW: 0, DN_FAST: 1, UP_FAST: 2, UP_SLOW: 3, DN: 1, UP: 2,
}
const LANE_GAP = 3.7          // screen px between adjacent tracks
const laneList = (tracks: string[]) =>
  [...tracks].sort((a, b) => (LANE_RANK[a] ?? 9) - (LANE_RANK[b] ?? 9))

const MIN_SCALE_FACTOR = 0.35
const MAX_SCALE_FACTOR = 9

type View = { scale: number; tx: number; ty: number }
type Geom = { x1: number; y1: number; x2: number; y2: number; nx: number; ny: number }

export default function NetworkMap({
  net, trains, totalActive, truncated, clock, selected, onSelect, blocks, halos = [], reroutes = [],
}: {
  net: NetworkData
  trains: TrainDot[]
  totalActive: number
  truncated: number
  clock: string
  selected: string | null
  onSelect: (id: string | null) => void
  blocks: Set<string>
  halos?: Halo[]
  reroutes?: RerouteBlock[]
}) {
  const [hover, setHover] = useState<Station | null>(null)
  const [isDragging, setIsDragging] = useState(false)
  const svgRef = useRef<SVGSVGElement>(null)
  const justDragged = useRef(false)

  // One fixed projection: the whole Mumbai region maps into the viewBox; the network is framed
  // afterwards by the zoom/pan transform.
  const project = useMemo(() => {
    const pts = MMR_BORDER.flat()
    const lats = pts.map(p => p[0]), lons = pts.map(p => p[1])
    const minLat = Math.min(...lats), maxLat = Math.max(...lats)
    const minLon = Math.min(...lons), maxLon = Math.max(...lons)
    const kLon = Math.cos((19.05 * Math.PI) / 180)
    const spanLon = (maxLon - minLon) * kLon
    const spanLat = maxLat - minLat
    const scale = Math.min((W - PAD * 2) / spanLon, (H - PAD * 2) / spanLat)
    const ox = (W - spanLon * scale) / 2
    const oy = (H - spanLat * scale) / 2
    return (lat: number, lon: number): [number, number] => [
      ox + (lon - minLon) * kLon * scale,
      oy + (maxLat - lat) * scale,
    ]
  }, [])

  const ringPath = (rings: [number, number][][]) =>
    rings.map(r => 'M ' + r.map(([la, lo]) => {
      const [x, y] = project(la, lo)
      return `${x.toFixed(1)},${y.toFixed(1)}`
    }).join(' L ') + ' Z').join(' ')
  const mmrPath = useMemo(() => ringPath(MMR_BORDER), [project])          // eslint-disable-line
  const cityPath = useMemo(() => ringPath(MUMBAI_CITY_BORDER), [project]) // eslint-disable-line

  const byCode = useMemo(
    () => Object.fromEntries(net.stations.map(s => [s.code, s])) as Record<string, Station>, [net])
  const secById = useMemo(
    () => Object.fromEntries(net.sections.map(s => [s.id, s])) as Record<string, NetworkData['sections'][number]>,
    [net])

  const secGeom = useMemo(() => {
    const out: Record<string, Geom> = {}
    for (const sec of net.sections) {
      const a = byCode[sec.from], b = byCode[sec.to]
      if (!a || !b) continue
      const [x1, y1] = project(a.lat, a.lon)
      const [x2, y2] = project(b.lat, b.lon)
      const len = Math.hypot(x2 - x1, y2 - y1) || 1
      out[sec.id] = { x1, y1, x2, y2, nx: -(y2 - y1) / len, ny: (x2 - x1) / len }
    }
    return out
  }, [net, byCode, project])

  const initialView = useMemo((): View => {
    const pts = net.stations.map(s => project(s.lat, s.lon))
    const xs = pts.map(p => p[0]), ys = pts.map(p => p[1])
    const bw = Math.max(1, Math.max(...xs) - Math.min(...xs))
    const bh = Math.max(1, Math.max(...ys) - Math.min(...ys))
    const s = Math.min((W - 90) / bw, (H - 90) / bh)
    const cx = (Math.min(...xs) + Math.max(...xs)) / 2, cy = (Math.min(...ys) + Math.max(...ys)) / 2
    return { scale: s, tx: W / 2 - cx * s, ty: H / 2 - cy * s }
  }, [net, project])

  const [view, setView] = useState<View>(initialView)
  const minScale = initialView.scale * MIN_SCALE_FACTOR
  const maxScale = initialView.scale * MAX_SCALE_FACTOR

  const toUserSpace = (clientX: number, clientY: number) => {
    const svg = svgRef.current
    const ctm = svg?.getScreenCTM()
    if (!svg || !ctm) return null
    const pt = svg.createSVGPoint()
    pt.x = clientX; pt.y = clientY
    const loc = pt.matrixTransform(ctm.inverse())
    return { x: loc.x, y: loc.y }
  }

  const zoomBy = (factor: number, center?: { x: number; y: number }) => {
    setView(v => {
      const next = Math.min(maxScale, Math.max(minScale, v.scale * factor))
      const k = next / v.scale
      const c = center ?? { x: W / 2, y: H / 2 }
      return { scale: next, tx: c.x - (c.x - v.tx) * k, ty: c.y - (c.y - v.ty) * k }
    })
  }

  // React attaches JSX onWheel as passive, so preventDefault would silently fail: use a native
  // non-passive listener.
  const zoomByRef = useRef(zoomBy)
  zoomByRef.current = zoomBy
  useEffect(() => {
    const svg = svgRef.current
    if (!svg) return
    const handler = (e: WheelEvent) => {
      e.preventDefault()
      const loc = toUserSpace(e.clientX, e.clientY)
      zoomByRef.current(Math.exp(-e.deltaY * 0.0016), loc ?? undefined)
    }
    svg.addEventListener('wheel', handler, { passive: false })
    return () => svg.removeEventListener('wheel', handler)
  }, [])

  // A drag exists only between a primary-button press and its release; both listeners are on the
  // window and removed the moment it ends (or if the button is no longer down).
  const onPointerDown = (e: React.PointerEvent<SVGSVGElement>) => {
    if (e.button !== 0) return
    const svg = svgRef.current
    const ctm = svg?.getScreenCTM()
    if (!svg || !ctm) return
    const start = { x: e.clientX, y: e.clientY, tx: view.tx, ty: view.ty }
    let moved = false
    justDragged.current = false

    const move = (ev: PointerEvent) => {
      if (!(ev.buttons & 1)) { end(); return }
      const dx = (ev.clientX - start.x) / ctm.a
      const dy = (ev.clientY - start.y) / ctm.d
      if (!moved && Math.abs(dx) + Math.abs(dy) > 3) { moved = true; setIsDragging(true) }
      if (moved) setView(v => ({ ...v, tx: start.tx + dx, ty: start.ty + dy }))
    }
    const end = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', end)
      window.removeEventListener('pointercancel', end)
      window.removeEventListener('blur', end)
      setIsDragging(false)
      justDragged.current = moved
      if (moved) setTimeout(() => { justDragged.current = false }, 0)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', end)
    window.addEventListener('pointercancel', end)
    window.addEventListener('blur', end)
  }

  const pick = (id: string) => () => {
    if (justDragged.current) return
    onSelect(selected === id ? null : id)
  }

  const degraded = net.sections.filter(s => s.status !== 'FIT')
  const lines = [...new Set(net.sections.map(s => s.line_code).filter(Boolean))]
  const zoomedIn = view.scale > initialView.scale * 1.55
  const laneOffset = (n: number, k: number) => ((k - (n - 1) / 2) * LANE_GAP) / view.scale

  return (
    <div className="map-wrap">
      <div className="map-live"><i />LIVE SIMULATION</div>
      <div className="map-controls">
        <button onClick={() => zoomBy(1.35)} title="Zoom in">+</button>
        <button onClick={() => zoomBy(1 / 1.35)} title="Zoom out">−</button>
        <button onClick={() => setView(initialView)} title="Reset view" style={{ fontSize: 11 }}>⤾</button>
      </div>
      <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} role="img"
           className={isDragging ? 'dragging' : ''}
           aria-label="Mumbai region with the suburban network, live train positions and track status"
           onPointerDown={onPointerDown}>
        <g transform={`translate(${view.tx},${view.ty}) scale(${view.scale})`}>
          {/* the region: white inside, real border; Mumbai city proper outlined harder */}
          <path d={mmrPath} fill="#f5f7fa" stroke="#94a3b8" strokeWidth={1.6}
                strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
          <path d={cityPath} fill="#ffffff" stroke="#475569" strokeWidth={1.3}
                strokeLinejoin="round" vectorEffect="non-scaling-stroke" />

          {/* job-cluster halos */}
          {halos.map((h, i) => {
            const sec = secById[h.zone]
            if (sec) {
              const g = secGeom[sec.id]
              if (!g) return null
              return (
                <line key={`halo-${i}`} x1={g.x1} y1={g.y1} x2={g.x2} y2={g.y2} stroke={h.color}
                      strokeWidth={h.active ? 18 : 12} strokeLinecap="round"
                      opacity={h.active ? 0.6 : 0.32} vectorEffect="non-scaling-stroke"
                      pointerEvents="none" />
              )
            }
            const st = byCode[h.zone]
            if (!st) return null
            const [x, y] = project(st.lat, st.lon)
            return (
              <g key={`halo-${i}`} transform={`translate(${x},${y}) scale(${1 / view.scale})`} pointerEvents="none">
                <circle r={h.active ? 15 : 11} fill={h.color} fillOpacity={h.active ? 0.4 : 0.22}
                        stroke={h.color} strokeWidth={1.4} />
              </g>
            )
          })}

          {/* track status: a wide translucent band under the lines, only where something is wrong */}
          {degraded.map(sec => {
            const g = secGeom[sec.id]
            if (!g) return null
            return (
              <line key={`st-${sec.id}`} x1={g.x1} y1={g.y1} x2={g.x2} y2={g.y2}
                    stroke={STATUS[sec.status]} strokeWidth={LANE_GAP * sec.tracks.length + 8}
                    strokeLinecap="round" opacity={0.5} vectorEffect="non-scaling-stroke" />
            )
          })}

          {/* the network: one line per physical track */}
          {net.sections.map(sec => {
            const g = secGeom[sec.id]
            if (!g) return null
            const lanes = laneList(sec.tracks)
            const tint = LINE_COLOR[sec.line_code] ?? '#475569'
            const sel = selected === sec.id
            return (
              <g key={`base-${sec.id}`}>
                {sel && (
                  <line x1={g.x1} y1={g.y1} x2={g.x2} y2={g.y2} stroke={tint} strokeOpacity={0.22}
                        strokeWidth={LANE_GAP * lanes.length + 10} strokeLinecap="round"
                        vectorEffect="non-scaling-stroke" />
                )}
                {lanes.map((tr, k) => {
                  const o = laneOffset(lanes.length, k)
                  const fast = tr.endsWith('_FAST')
                  return (
                    <line key={tr} x1={g.x1 + g.nx * o} y1={g.y1 + g.ny * o}
                          x2={g.x2 + g.nx * o} y2={g.y2 + g.ny * o}
                          stroke={tint} strokeWidth={sel ? 2.2 : 1.8} strokeLinecap="butt"
                          strokeOpacity={fast ? 1 : 0.7} vectorEffect="non-scaling-stroke" />
                  )
                })}
              </g>
            )
          })}

          {/* maintenance: hazard stripes on the closed tracks, a crew moving along them and a gear
              turning at the middle. With single-line working only the blocked track is closed and
              the track taking the traffic runs a moving green dash. */}
          {net.sections.filter(sec => blocks.has(sec.id)).map(sec => {
            const g = secGeom[sec.id]
            if (!g) return null
            const lanes = laneList(sec.tracks)
            const swap = reroutes.find(r => r.section_id === sec.id)?.track_swap ?? null
            const mx = (g.x1 + g.x2) / 2, my = (g.y1 + g.y2) / 2
            return (
              <g key={`bl-${sec.id}`} pointerEvents="none">
                {lanes.map((tr, k) => {
                  const o = laneOffset(lanes.length, k)
                  const closed = !swap || tr === swap.blocked_track
                  const takingOver = !!swap && tr === swap.swap_to_track
                  if (!closed && !takingOver) return null
                  const p = { x1: g.x1 + g.nx * o, y1: g.y1 + g.ny * o, x2: g.x2 + g.nx * o, y2: g.y2 + g.ny * o }
                  return closed ? (
                    <g key={tr}>
                      <line {...p} stroke="#f59e0b" strokeWidth={4.4} vectorEffect="non-scaling-stroke" />
                      <line {...p} stroke="#111827" strokeWidth={4.4} strokeDasharray="5 5"
                            vectorEffect="non-scaling-stroke">
                        <animate attributeName="stroke-dashoffset" from="20" to="0" dur="0.7s" repeatCount="indefinite" />
                      </line>
                    </g>
                  ) : (
                    <line key={tr} {...p} stroke="#22c55e" strokeWidth={3} strokeDasharray="9 5"
                          vectorEffect="non-scaling-stroke">
                      <animate attributeName="stroke-dashoffset" from="28" to="0" dur="1.1s" repeatCount="indefinite" />
                    </line>
                  )
                })}
                <circle r={3.4 / view.scale} fill="#ef4444" stroke="#fff" strokeWidth={0.9 / view.scale}>
                  <animate attributeName="cx" values={`${g.x1};${g.x2};${g.x1}`} dur="3.4s" repeatCount="indefinite" />
                  <animate attributeName="cy" values={`${g.y1};${g.y2};${g.y1}`} dur="3.4s" repeatCount="indefinite" />
                </circle>
                <g transform={`translate(${mx},${my}) scale(${1 / view.scale})`}>
                  {[0, 0.9].map(delay => (
                    <circle key={delay} r={6} fill="none" stroke="#ef4444" strokeWidth={1.8}>
                      <animate attributeName="r" values="6;26" dur="1.8s" begin={`${delay}s`} repeatCount="indefinite" />
                      <animate attributeName="opacity" values="0.9;0" dur="1.8s" begin={`${delay}s`} repeatCount="indefinite" />
                    </circle>
                  ))}
                  <circle r={7.5} fill="#111827" stroke="#f59e0b" strokeWidth={1.4} />
                  <circle r={5} fill="none" stroke="#f59e0b" strokeWidth={2.6} strokeDasharray="2.6 2.6">
                    <animateTransform attributeName="transform" type="rotate" from="0" to="360"
                                      dur="3.5s" repeatCount="indefinite" />
                  </circle>
                </g>
              </g>
            )
          })}

          {/* rerouted long-distance and freight trains travel their detour. Locals never appear. */}
          {reroutes.flatMap(b => b.reroutes.map(r => {
            const secs = r.sections.map(id => secById[id]).filter(Boolean)
            if (!secs.length) return null
            let cur = secs.length === 1 ? secs[0].from
              : ([secs[1].from, secs[1].to].includes(secs[0].from) ? secs[0].to : secs[0].from)
            const nodes = [cur]
            for (const sc of secs) { cur = sc.from === cur ? sc.to : sc.from; nodes.push(cur) }
            const pts = nodes.map(c => byCode[c]).filter(Boolean).map(st => project(st.lat, st.lon))
            if (pts.length < 2) return null
            const d = 'M ' + pts.map(([x, y]) => `${x.toFixed(2)},${y.toFixed(2)}`).join(' L ')
            return (
              <g key={`rr-${b.section_id}-${r.train_id}`} pointerEvents="none">
                <path d={d} fill="none" stroke={TRAIN.reroute} strokeWidth={8} strokeOpacity={0.2}
                      strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
                <path d={d} fill="none" stroke={TRAIN.reroute} strokeWidth={2.6} strokeDasharray="7 5"
                      strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke">
                  <animate attributeName="stroke-dashoffset" from="24" to="0" dur="0.9s" repeatCount="indefinite" />
                </path>
                <g>
                  <animateMotion path={d} dur={`${Math.max(6, pts.length * 2.2)}s`} repeatCount="indefinite" />
                  <g transform={`scale(${1 / view.scale})`}>
                    <circle r={6} fill={TRAIN.reroute} stroke="#fff" strokeWidth={1.6} />
                    <text x={10} y={3.5} fontSize={9.5} fill="#0e7490" fontFamily="var(--mono)" fontWeight={700}
                          stroke="#fff" strokeWidth={3} paintOrder="stroke">{r.train_name || r.train_id}</text>
                  </g>
                </g>
              </g>
            )
          }))}

          {/* clickable hit areas */}
          {net.sections.map(sec => {
            const g = secGeom[sec.id]
            if (!g) return null
            return (
              <line key={`hit-${sec.id}`} x1={g.x1} y1={g.y1} x2={g.x2} y2={g.y2}
                    stroke="transparent" strokeWidth={LANE_GAP * sec.tracks.length + 8}
                    vectorEffect="non-scaling-stroke" style={{ cursor: 'pointer' }}
                    onClick={pick(sec.id)} />
            )
          })}

          {/* stations, inverse-scaled so markers and labels keep a constant, legible size */}
          {net.stations.map(st => {
            const [x, y] = project(st.lat, st.lon)
            const interchange = (st.lines?.length ?? 0) > 1
            const r = interchange ? 5.4 : st.tier === 'TIER_1' ? 4.4 : st.tier === 'TIER_2' ? 3.2 : 2.6
            const label = interchange || st.tier === 'TIER_1' || (zoomedIn && st.tier === 'TIER_2')
                        || (view.scale > initialView.scale * 3.2)
            return (
              <g key={st.code} transform={`translate(${x},${y}) scale(${1 / view.scale})`}
                 onMouseEnter={() => setHover(st)} onMouseLeave={() => setHover(null)}
                 style={{ cursor: 'default' }}>
                <circle r={r + 5} fill="transparent" />
                <circle r={r} fill="#fff" stroke="#111827" strokeWidth={interchange ? 2.2 : 1.4} />
                {label && (
                  <text x={r + 5} y={3.6} fontSize={9.5} fill="#111827" fontFamily="var(--mono)"
                        fontWeight={interchange ? 700 : 500} stroke="#fff" strokeWidth={3}
                        paintOrder="stroke">{st.code}</text>
                )}
              </g>
            )
          })}

          {/* trains: black dot = local, orange ringed = intercity, brown square = freight */}
          {trains.map(t => {
            const [px, py] = project(t.lat, t.lon)
            const sec = secById[t.section]
            const g = sec ? secGeom[t.section] : undefined
            let x = px, y = py
            if (sec && g && t.track) {
              const lanes = laneList(sec.tracks)
              const k = lanes.indexOf(t.track)
              if (k >= 0) {
                const o = laneOffset(lanes.length, k)
                x += g.nx * o; y += g.ny * o
              }
            }
            const gt = `translate(${x},${y}) scale(${1 / view.scale})`
            if (t.cls === 'SUBURBAN_LOCAL')
              return <g key={t.id} transform={gt}>
                <circle r={2.4} fill={TRAIN.local} stroke="#fff" strokeWidth={0.9} />
              </g>
            if (t.cls === 'FREIGHT_MAIL')
              return <g key={t.id} transform={gt}>
                <rect x={-2.9} y={-2.9} width={5.8} height={5.8} rx={1} fill={TRAIN.freight}
                      stroke="#fff" strokeWidth={0.9} />
              </g>
            return (
              <g key={t.id} transform={gt}>
                <circle r={4.6} fill={TRAIN.intercity} stroke="#111827" strokeWidth={1.3} />
                <circle r={1.5} fill="#111827" />
              </g>
            )
          })}
        </g>

        <text x={18} y={26} fontSize={12.5} fill="#cbd5e1" fontFamily="var(--mono)">{clock}</text>
        <text x={W - 18} y={26} fontSize={11} fill="#94a3b8" fontFamily="var(--mono)" textAnchor="end">
          {totalActive} services running{truncated > 0 ? ` · +${truncated} not drawn` : ''}
        </text>

        {hover && (() => {
          const [px, py] = project(hover.lat, hover.lon)
          const x = view.tx + px * view.scale, y = view.ty + py * view.scale
          const right = x > W - 200
          return (
            <g transform={`translate(${right ? x - 196 : x + 12}, ${Math.min(Math.max(y - 8, 8), H - 80)})`}
               pointerEvents="none">
              <rect width={184} height={hover.lines && hover.lines.length > 1 ? 68 : 56} rx={7}
                    fill="#0b0f16" stroke="var(--line)" />
              <text x={11} y={19} fontSize={11.5} fill="#eef3f8" fontWeight={600}>{hover.name}</text>
              <text x={11} y={35} fontSize={10} fill="#94a3b8" fontFamily="var(--mono)">
                {hover.code} · {hover.tier?.replace('_', ' ').toLowerCase()} · {hover.trains_per_day} trains/day
              </text>
              <text x={11} y={49} fontSize={10} fill={STATUS[hover.status]} fontFamily="var(--mono)">
                {hover.status.replace(/_/g, ' ').toLowerCase()}
              </text>
              {hover.lines && hover.lines.length > 1 && (
                <text x={11} y={62} fontSize={9.5} fill="#94a3b8">
                  interchange: {hover.lines.map(l => LINE_NAME[l] ?? l).join(' · ')}
                </text>
              )}
            </g>
          )
        })()}
      </svg>

      <div className="legend">
        {lines.map(l => (
          <span key={l}><i style={{ background: LINE_COLOR[l] }} />{LINE_NAME[l] ?? l}</span>
        ))}
        <span className="sep" />
        <span><i className="dot" style={{ background: TRAIN.local }} />Local</span>
        <span><i className="dot" style={{ background: TRAIN.intercity }} />Intercity</span>
        <span><i style={{ background: TRAIN.freight }} />Freight</span>
        <span><i style={{ background: TRAIN.reroute }} />Rerouted</span>
        <span className="sep" />
        <span><i style={{ background: 'repeating-linear-gradient(45deg,#f59e0b 0 3px,#111827 3px 6px)' }} />Track closed for work</span>
        <span><i style={{ background: '#22c55e' }} />Single-line working</span>
        <span><i style={{ background: 'var(--sick)' }} />Sick</span>
        <span><i style={{ background: 'var(--caution)' }} />Caution</span>
        <span><i style={{ background: 'var(--stopstart)' }} />Stop &amp; start</span>
        <span className="sep" />
        <span className="muted" style={{ fontStyle: 'italic' }}>
          slow tracks outside, fast inside · border: OpenStreetMap
        </span>
      </div>
    </div>
  )
}
