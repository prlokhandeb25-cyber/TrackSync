import { useEffect, useMemo, useRef, useState } from 'react'
import type { NetworkData, TrainDot, Station } from '../api'
import type { Halo } from './JobClusters'
import type { RerouteBlock } from '../api'

/* Geographic SVG built from the station coordinates, with a stylized Maharashtra state
   outline behind it for context — both drawn through the SAME projection, so the network sits
   in its true position relative to the state (the Konkan coast, near Mumbai, on the west
   edge). The outline is hand-traced from general knowledge of the state's shape, not survey
   boundary data — see ASSUMPTIONS.md. No map tiles: nothing here can fail on conference wifi.

   Visual hierarchy: the network is drawn in vivid per-line colour (distinct at a glance, by
   request — see SPEC.md §14.1 for the deliberate exception this page takes); status is drawn
   even brighter on top, with a glow, because it is the message that matters most. A judge
   should see a calm-enough network with a few hot spots and know instantly where to look.

   Zoom/pan: the whole scene sits in one transformed <g>. Station markers, labels and train
   dots are nested in their own inverse-scaled group so they stay a constant, legible screen
   size at any zoom level; line strokes use vector-effect="non-scaling-stroke" for the same
   reason. */

const W = 980
const H = 620
const PAD = 46

// A stylized trace of Maharashtra's outer boundary — decorative context, not survey data.
const MAHARASHTRA_OUTLINE: [number, number][] = [
  [20.15, 72.75], [21.05, 73.55], [21.65, 74.30], [21.75, 75.60], [21.50, 76.60],
  [21.65, 77.50], [21.85, 78.40], [21.95, 79.20], [21.40, 79.85], [20.70, 80.20],
  [19.90, 80.10], [19.30, 79.95], [19.05, 79.30], [18.85, 78.10], [18.30, 77.40],
  [17.85, 76.60], [17.55, 76.10], [17.10, 75.60], [16.65, 75.10], [16.30, 74.50],
  [16.00, 74.10], [15.80, 73.85], [16.05, 73.55], [16.55, 73.35], [17.35, 73.20],
  [18.00, 73.05], [18.55, 72.90], [18.95, 72.80], [19.30, 72.75],
]

const STATUS: Record<string, string> = {
  FIT: 'var(--fit)',
  SICK: 'var(--sick)',
  CAUTION_ORDER: 'var(--caution)',
  STOP_AND_START: 'var(--stopstart)',
}
const LINE_TINT: Record<string, string> = {
  CR: 'var(--l-CR-vivid)', WR: 'var(--l-WR-vivid)', HR: 'var(--l-HR-vivid)', TH: 'var(--l-TH-vivid)',
}
const LINE_NAME: Record<string, string> = {
  CR: 'Central', WR: 'Western', HR: 'Harbour', TH: 'Trans-Harbour',
}

// Physical track order across a section, outside to inside: slow lines on the outside, fast lines
// in the middle - the layout in the division's own system map (four abreast at the core, two on
// the outer sections). Two-track sections are just DN | UP.
const LANE_RANK: Record<string, number> = {
  DN_SLOW: 0, DN_FAST: 1, UP_FAST: 2, UP_SLOW: 3, DN: 1, UP: 2,
}
const LANE_GAP = 3.7          // screen px between adjacent tracks
const laneList = (tracks: string[]) =>
  [...tracks].sort((a, b) => (LANE_RANK[a] ?? 9) - (LANE_RANK[b] ?? 9))

const MIN_SCALE_FACTOR = 0.3   // relative to the network-fit view — lets you zoom out to the whole state
const MAX_SCALE_FACTOR = 9     // relative to the network-fit view — enough to read every station name

type View = { scale: number; tx: number; ty: number }

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
  const dragState = useRef<{ x: number; y: number; tx: number; ty: number; moved: boolean } | null>(null)

  // Fixed projection: the whole state maps into the viewBox once. The network — a small
  // cluster on the coast — is framed afterwards by the separate zoom/pan transform below, so
  // both share one true geographic coordinate system.
  const project = useMemo(() => {
    const lats = MAHARASHTRA_OUTLINE.map(([la]) => la)
    const lons = MAHARASHTRA_OUTLINE.map(([, lo]) => lo)
    const minLat = Math.min(...lats), maxLat = Math.max(...lats)
    const minLon = Math.min(...lons), maxLon = Math.max(...lons)
    const kLon = Math.cos((18.7 * Math.PI) / 180)
    const spanLon = Math.max(1e-6, (maxLon - minLon) * kLon)
    const spanLat = Math.max(1e-6, maxLat - minLat)
    const scale = Math.min((W - PAD * 2) / spanLon, (H - PAD * 2) / spanLat)
    const ox = (W - spanLon * scale) / 2
    const oy = (H - spanLat * scale) / 2
    return (lat: number, lon: number): [number, number] => [
      ox + (lon - minLon) * kLon * scale,
      oy + (maxLat - lat) * scale,
    ]
  }, [])

  const outlinePath = useMemo(() => {
    const pts = MAHARASHTRA_OUTLINE.map(([la, lo]) => project(la, lo))
    return 'M ' + pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' L ') + ' Z'
  }, [project])

  const byCode = useMemo(
    () => Object.fromEntries(net.stations.map(s => [s.code, s])) as Record<string, Station>,
    [net])

  const secById = useMemo(
    () => Object.fromEntries(net.sections.map(s => [s.id, s])) as Record<string, NetworkData['sections'][number]>,
    [net])

  // Each section's centreline and its unit normal, so parallel tracks can be offset from it.
  const secGeom = useMemo(() => {
    const out: Record<string, { x1: number; y1: number; x2: number; y2: number; nx: number; ny: number }> = {}
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

  // The network's own footprint in projected space — the initial zoom fits exactly this.
  const netBBox = useMemo(() => {
    const pts = net.stations.map(s => project(s.lat, s.lon))
    const xs = pts.map(p => p[0]), ys = pts.map(p => p[1])
    return {
      minX: Math.min(...xs), maxX: Math.max(...xs),
      minY: Math.min(...ys), maxY: Math.max(...ys),
    }
  }, [net, project])

  const initialView = useMemo((): View => {
    const bw = Math.max(1, netBBox.maxX - netBBox.minX)
    const bh = Math.max(1, netBBox.maxY - netBBox.minY)
    const pad = 60
    const s = Math.min((W - pad * 2) / bw, (H - pad * 2) / bh)
    const cx = (netBBox.minX + netBBox.maxX) / 2, cy = (netBBox.minY + netBBox.maxY) / 2
    return { scale: s, tx: W / 2 - cx * s, ty: H / 2 - cy * s }
  }, [netBBox])

  const [view, setView] = useState<View>(initialView)
  const minScale = initialView.scale * MIN_SCALE_FACTOR
  const maxScale = initialView.scale * MAX_SCALE_FACTOR

  const toUserSpace = (clientX: number, clientY: number): { x: number; y: number } | null => {
    const svg = svgRef.current
    if (!svg) return null
    const ctm = svg.getScreenCTM()
    if (!ctm) return null
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
      return {
        scale: next,
        tx: c.x - (c.x - v.tx) * k,
        ty: c.y - (c.y - v.ty) * k,
      }
    })
  }

  // React attaches JSX onWheel as a passive listener, so e.preventDefault() inside it silently
  // fails and the page scrolls under the map instead of zooming it. A native listener attached
  // with { passive: false } is the only way to actually claim the wheel event.
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

  const onPointerDown = (e: React.PointerEvent<SVGSVGElement>) => {
    (e.target as Element).setPointerCapture?.(e.pointerId)
    dragState.current = { x: e.clientX, y: e.clientY, tx: view.tx, ty: view.ty, moved: false }
  }
  const onPointerMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const d = dragState.current
    const svg = svgRef.current
    if (!d || !svg) return
    const ctm = svg.getScreenCTM()
    if (!ctm) return
    const dx = (e.clientX - d.x) / ctm.a
    const dy = (e.clientY - d.y) / ctm.d
    if (Math.abs(dx) + Math.abs(dy) > 2 && !d.moved) { d.moved = true; setIsDragging(true) }
    setView(v => ({ ...v, tx: d.tx + dx, ty: d.ty + dy }))
  }
  const onPointerUp = () => { setIsDragging(false) }

  const suppressClickIfDragged = (fn: () => void) => () => {
    if (dragState.current?.moved) return
    fn()
  }

  const resetView = () => setView(initialView)

  const degraded = net.sections.filter(s => s.status !== 'FIT')
  const lines = [...new Set(net.sections.map(s => s.line_code).filter(Boolean))]
  const zoomedIn = view.scale > initialView.scale * 1.55

  return (
    <div className="map-wrap">
      <div className="map-live"><i />LIVE SIMULATION</div>
      <div className="map-controls">
        <button onClick={() => zoomBy(1.35)} title="Zoom in">+</button>
        <button onClick={() => zoomBy(1 / 1.35)} title="Zoom out">−</button>
        <button onClick={resetView} title="Reset view" style={{ fontSize: 11 }}>⤾</button>
      </div>
      <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} role="img"
           className={isDragging ? 'dragging' : ''}
           aria-label="Maharashtra with the Mumbai suburban network, live train positions and track status"
           onPointerDown={onPointerDown}
           onPointerMove={onPointerMove}
           onPointerUp={onPointerUp}
           onPointerLeave={() => { dragState.current = null; setIsDragging(false) }}>
        <defs>
          <filter id="glow" x="-60%" y="-60%" width="220%" height="220%">
            <feGaussianBlur stdDeviation="3.2" result="b" />
            <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
        </defs>

        <g transform={`translate(${view.tx},${view.ty}) scale(${view.scale})`}>
          {/* Maharashtra outline — decorative context, honestly stylized (see legend note) */}
          <path d={outlinePath} fill="#ffffff08" stroke="#ffffff" strokeOpacity={0.55}
                strokeWidth={1.4} vectorEffect="non-scaling-stroke" />

          {/* job-cluster halos — each colour is one group of nearby jobs */}
          {halos.map((h, i) => {
            const sec = secById[h.zone]
            if (sec) {
              const a = byCode[sec.from], b = byCode[sec.to]
              if (!a || !b) return null
              const [x1, y1] = project(a.lat, a.lon)
              const [x2, y2] = project(b.lat, b.lon)
              return (
                <line key={`halo-${i}`} x1={x1} y1={y1} x2={x2} y2={y2} stroke={h.color}
                      strokeWidth={h.active ? 16 : 11} strokeLinecap="round"
                      opacity={h.active ? 0.6 : 0.3} vectorEffect="non-scaling-stroke"
                      filter={h.active ? 'url(#glow)' : undefined} pointerEvents="none" />
              )
            }
            const st = byCode[h.zone]
            if (!st) return null
            const [x, y] = project(st.lat, st.lon)
            return (
              <g key={`halo-${i}`} transform={`translate(${x},${y}) scale(${1 / view.scale})`}
                 pointerEvents="none">
                <circle r={h.active ? 15 : 11} fill={h.color} fillOpacity={h.active ? 0.35 : 0.2}
                        stroke={h.color} strokeWidth={1.4} />
              </g>
            )
          })}

          {/* base network: one line per physical track, slow outside, fast inside */}
          {net.sections.map(sec => {
            const g = secGeom[sec.id]
            if (!g) return null
            const lanes = laneList(sec.tracks)
            const tint = LINE_TINT[sec.line_code] ?? '#3a4658'
            const sel = selected === sec.id
            return (
              <g key={`base-${sec.id}`}>
                {sel && (
                  <line x1={g.x1} y1={g.y1} x2={g.x2} y2={g.y2} stroke={tint} strokeOpacity={0.28}
                        strokeWidth={LANE_GAP * lanes.length + 8} strokeLinecap="round"
                        vectorEffect="non-scaling-stroke" />
                )}
                {lanes.map((tr, k) => {
                  const o = ((k - (lanes.length - 1) / 2) * LANE_GAP) / view.scale
                  const fast = tr.endsWith('_FAST')
                  return (
                    <line key={tr} x1={g.x1 + g.nx * o} y1={g.y1 + g.ny * o}
                          x2={g.x2 + g.nx * o} y2={g.y2 + g.ny * o}
                          stroke={tint} strokeWidth={sel ? 2.1 : 1.7} strokeLinecap="butt"
                          strokeOpacity={fast ? 1 : 0.72} vectorEffect="non-scaling-stroke" />
                  )
                })}
              </g>
            )
          })}

          {/* status overlay — brightest layer, only where something is wrong */}
          {degraded.map(sec => {
            const a = byCode[sec.from], b = byCode[sec.to]
            if (!a || !b) return null
            const [x1, y1] = project(a.lat, a.lon)
            const [x2, y2] = project(b.lat, b.lon)
            return (
              <line key={`st-${sec.id}`} x1={x1} y1={y1} x2={x2} y2={y2}
                    stroke={STATUS[sec.status]} strokeWidth={LANE_GAP * sec.tracks.length + 3} strokeLinecap="round"
                    filter="url(#glow)" opacity={0.95} vectorEffect="non-scaling-stroke" />
            )
          })}

          {/* active maintenance: the closed tracks get a hazard animation, a crew moves along
              them and a gear turns at the middle. Where a single-line swap is possible only the
              blocked track is closed and the track it swaps onto pulses amber. */}
          {net.sections.filter(sec => blocks.has(sec.id)).map(sec => {
            const g = secGeom[sec.id]
            if (!g) return null
            const lanes = laneList(sec.tracks)
            const swap = reroutes.find(r => r.section_id === sec.id)?.track_swap ?? null
            const mx = (g.x1 + g.x2) / 2, my = (g.y1 + g.y2) / 2
            return (
              <g key={`bl-${sec.id}`} pointerEvents="none">
                {lanes.map((tr, k) => {
                  const o = ((k - (lanes.length - 1) / 2) * LANE_GAP) / view.scale
                  const closed = !swap || tr === swap.blocked_track
                  const takingOver = !!swap && tr === swap.swap_to_track
                  if (!closed && !takingOver) return null
                  return (
                    <line key={tr} x1={g.x1 + g.nx * o} y1={g.y1 + g.ny * o}
                          x2={g.x2 + g.nx * o} y2={g.y2 + g.ny * o}
                          stroke={closed ? 'var(--block)' : 'var(--sick)'}
                          strokeWidth={closed ? 3.4 : 2.6} strokeLinecap="butt"
                          strokeDasharray={closed ? '4 4' : '9 5'} vectorEffect="non-scaling-stroke">
                      <animate attributeName="stroke-dashoffset" from={closed ? '16' : '0'}
                               to={closed ? '0' : '28'} dur={closed ? '0.8s' : '1.4s'} repeatCount="indefinite" />
                    </line>
                  )
                })}
                <circle r={3 / view.scale} fill="#ffd166">
                  <animate attributeName="cx" values={`${g.x1};${g.x2};${g.x1}`} dur="3.4s" repeatCount="indefinite" />
                  <animate attributeName="cy" values={`${g.y1};${g.y2};${g.y1}`} dur="3.4s" repeatCount="indefinite" />
                </circle>
                <g transform={`translate(${mx},${my}) scale(${1 / view.scale})`}>
                  {[0, 0.9].map(delay => (
                    <circle key={delay} r={6} fill="none" stroke="var(--block)" strokeWidth={1.6}>
                      <animate attributeName="r" values="6;24" dur="1.8s" begin={`${delay}s`} repeatCount="indefinite" />
                      <animate attributeName="opacity" values="0.9;0" dur="1.8s" begin={`${delay}s`} repeatCount="indefinite" />
                    </circle>
                  ))}
                  <circle r={7} fill="#150f2b" stroke="var(--block)" strokeWidth={1.2} />
                  <circle r={5} fill="none" stroke="#ffd166" strokeWidth={2.6} strokeDasharray="2.6 2.6">
                    <animateTransform attributeName="transform" type="rotate" from="0" to="360"
                                      dur="3.5s" repeatCount="indefinite" />
                  </circle>
                </g>
              </g>
            )
          })}

          {/* rerouted long-distance and freight trains: the detour is drawn along the alternate
              sections, with the train travelling it. Locals never appear here. */}
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
                <path d={d} fill="none" stroke="#22e5ff" strokeWidth={7} strokeOpacity={0.18}
                      strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
                <path d={d} fill="none" stroke="#22e5ff" strokeWidth={2.4} strokeDasharray="7 5"
                      strokeLinecap="round" strokeLinejoin="round" opacity={0.95}
                      vectorEffect="non-scaling-stroke">
                  <animate attributeName="stroke-dashoffset" from="24" to="0" dur="0.9s" repeatCount="indefinite" />
                </path>
                <g>
                  <animateMotion path={d} dur={`${Math.max(6, pts.length * 2.2)}s`} repeatCount="indefinite" />
                  <g transform={`scale(${1 / view.scale})`}>
                    <circle r={5.5} fill="#22e5ff" stroke="#fff" strokeWidth={1.4} />
                    <text x={9} y={3.5} fontSize={9.5} fill="#22e5ff" fontFamily="var(--mono)"
                          fontWeight={600}>{r.train_name || r.train_id}</text>
                  </g>
                </g>
              </g>
            )
          }))}

          {/* clickable hit areas */}
          {net.sections.map(sec => {
            const a = byCode[sec.from], b = byCode[sec.to]
            if (!a || !b) return null
            const [x1, y1] = project(a.lat, a.lon)
            const [x2, y2] = project(b.lat, b.lon)
            return (
              <line key={`hit-${sec.id}`} x1={x1} y1={y1} x2={x2} y2={y2}
                    stroke="transparent" strokeWidth={16} vectorEffect="non-scaling-stroke"
                    style={{ cursor: 'pointer' }}
                    onClick={suppressClickIfDragged(() => onSelect(selected === sec.id ? null : sec.id))} />
            )
          })}

          {/* stations — inverse-scaled so markers and labels stay a constant, legible size */}
          {net.stations.map(st => {
            const [x, y] = project(st.lat, st.lon)
            const interchange = (st.lines?.length ?? 0) > 1
            const r = interchange ? 5.4 : st.tier === 'TIER_1' ? 4.4 : st.tier === 'TIER_2' ? 3 : 2.3
            const label = interchange || st.tier === 'TIER_1' || (zoomedIn && st.tier === 'TIER_2')
                        || (view.scale > initialView.scale * 3.2)
            return (
              <g key={st.code} transform={`translate(${x},${y}) scale(${1 / view.scale})`}
                 onMouseEnter={() => setHover(st)} onMouseLeave={() => setHover(null)}
                 style={{ cursor: 'pointer' }}>
                <circle r={r + 5} fill="transparent" />
                <circle r={r} fill="#070a0f"
                        stroke={interchange ? 'var(--text)' : 'var(--text-dim)'}
                        strokeWidth={interchange ? 2 : 1.3} />
                {label && (
                  <text x={r + 5} y={3.4} fontSize={9.5}
                        fill={interchange ? 'var(--text)' : 'var(--text-dim)'}
                        fontFamily="var(--mono)"
                        fontWeight={interchange ? 600 : 400}>{st.code}</text>
                )}
              </g>
            )
          })}

          {/* trains — shape first, colour second; inverse-scaled to stay small dots */}
          {trains.map(t => {
            const [px, py] = project(t.lat, t.lon)
            const sec = secById[t.section]
            const g = sec ? secGeom[t.section] : undefined
            let x = px, y = py
            if (sec && g && t.track) {
              const lanes = laneList(sec.tracks)
              const k = lanes.indexOf(t.track)
              if (k >= 0) {
                const o = ((k - (lanes.length - 1) / 2) * LANE_GAP) / view.scale
                x += g.nx * o; y += g.ny * o
              }
            }
            const gt = `translate(${x},${y}) scale(${1 / view.scale})`
            if (t.cls === 'SUBURBAN_LOCAL')
              return <g key={t.id} transform={gt}><circle r={2.1} fill="var(--accent)" opacity={0.95} /></g>
            if (t.cls === 'FREIGHT_MAIL')
              return <g key={t.id} transform={gt}>
                <rect x={-2.4} y={-2.4} width={4.8} height={4.8} rx={1} fill="#cfdae6" opacity={0.95} />
              </g>
            return (
              <g key={t.id} transform={gt}>
                <circle r={4.2} fill="none" stroke="#fff" strokeWidth={1} opacity={0.6} />
                <circle r={2} fill="#fff" />
              </g>
            )
          })}
        </g>

        <text x={18} y={26} fontSize={12.5} fill="var(--text-dim)" fontFamily="var(--mono)">{clock}</text>
        <text x={W - 18} y={26} fontSize={11} fill="var(--text-mute)" fontFamily="var(--mono)"
              textAnchor="end">
          {totalActive} services running{truncated > 0 ? ` · +${truncated} not drawn` : ''}
        </text>

        {hover && (() => {
          const [px, py] = project(hover.lat, hover.lon)
          const x = view.tx + px * view.scale, y = view.ty + py * view.scale
          const right = x > W - 200
          return (
            <g transform={`translate(${right ? x - 196 : x + 12}, ${Math.min(Math.max(y - 8, 8), H - 80)})`}>
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
        <span><i style={{ background: '#fff' }} />Intercity</span>
        <span><i style={{ background: '#cfdae6' }} />Freight</span>
        <span className="sep" />
        <span><i style={{ background: 'var(--sick)' }} />Sick</span>
        <span><i style={{ background: 'var(--caution)' }} />Caution order</span>
        <span><i style={{ background: 'var(--stopstart)' }} />Stop &amp; start</span>
        <span><i style={{ background: 'var(--block)' }} />Track closed for work</span>
        <span><i style={{ background: 'var(--sick)' }} />Single-line working</span>
        <span><i style={{ background: '#22e5ff' }} />Rerouted train</span>
        <span className="sep" />
        <span className="muted" style={{ fontStyle: 'italic' }}>
          each line = its real tracks (slow outside, fast inside) · scroll/drag to zoom · state outline is stylized
        </span>
      </div>
    </div>
  )
}
