import { useEffect, useMemo, useRef, useState } from 'react'
import type { NetworkData, TrainDot, Station } from '../api'

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

const MIN_SCALE_FACTOR = 0.3   // relative to the network-fit view — lets you zoom out to the whole state
const MAX_SCALE_FACTOR = 9     // relative to the network-fit view — enough to read every station name

type View = { scale: number; tx: number; ty: number }

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

          {/* base network — vivid per-line colour, it is meant to be seen */}
          {net.sections.map(sec => {
            const a = byCode[sec.from], b = byCode[sec.to]
            if (!a || !b) return null
            const [x1, y1] = project(a.lat, a.lon)
            const [x2, y2] = project(b.lat, b.lon)
            return (
              <line key={`base-${sec.id}`} x1={x1} y1={y1} x2={x2} y2={y2}
                    stroke={LINE_TINT[sec.line_code] ?? '#3a4658'}
                    strokeWidth={selected === sec.id ? 6 : 3.4}
                    strokeLinecap="round" opacity={0.88} vectorEffect="non-scaling-stroke" />
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
                    stroke={STATUS[sec.status]} strokeWidth={4.6} strokeLinecap="round"
                    filter="url(#glow)" opacity={0.95} vectorEffect="non-scaling-stroke" />
            )
          })}

          {/* active maintenance blocks — CP-SAT/RL plan AND live-sim placements alike */}
          {net.sections.filter(s => blocks.has(s.id)).map(sec => {
            const a = byCode[sec.from], b = byCode[sec.to]
            if (!a || !b) return null
            const [x1, y1] = project(a.lat, a.lon)
            const [x2, y2] = project(b.lat, b.lon)
            return (
              <line key={`bl-${sec.id}`} x1={x1} y1={y1} x2={x2} y2={y2}
                    stroke="var(--block)" strokeWidth={7} strokeLinecap="round"
                    strokeDasharray="3 7" opacity={0.95} vectorEffect="non-scaling-stroke">
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
            const [x, y] = project(t.lat, t.lon)
            const g = `translate(${x},${y}) scale(${1 / view.scale})`
            if (t.cls === 'SUBURBAN_LOCAL')
              return <g key={t.id} transform={g}><circle r={2.5} fill="var(--accent)" opacity={0.92} /></g>
            if (t.cls === 'FREIGHT_MAIL')
              return <g key={t.id} transform={g}>
                <rect x={-2.7} y={-2.7} width={5.4} height={5.4} rx={1} fill="#cfdae6" opacity={0.92} />
              </g>
            return (
              <g key={t.id} transform={g}>
                <circle r={4.4} fill="none" stroke="#fff" strokeWidth={1} opacity={0.6} />
                <circle r={2.2} fill="#fff" />
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
        <span><i style={{ background: 'var(--block)' }} />Block active</span>
        <span className="sep" />
        <span className="muted" style={{ fontStyle: 'italic' }}>
          scroll/drag to zoom &amp; pan · state outline is stylized, not survey data
        </span>
      </div>
    </div>
  )
}
