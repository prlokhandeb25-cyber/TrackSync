import { useEffect, useMemo, useRef, useState } from 'react'
import { DAYS, hhmm, type NetworkData, type RerouteBlock, type Station, type TrainDot } from '../api'
import type { Halo } from './JobClusters'
import { MMR_BORDER, MUMBAI_CITY_BORDER } from '../data/mumbaiBorder'

/* The Mumbai Metropolitan Region drawn from its real OpenStreetMap boundary (cached locally, see
   scripts/07_build_mumbai_border.py), white inside, with the railway network on top through the
   SAME projection so every station sits where it really is. Each section is drawn as its real
   tracks - slow lines outside, fast inside, as on the division's system map - and trains run on
   their own track.

   Maintenance is drawn at two levels. Zoomed out, a closed track shows hazard stripes and a gear.
   Zoomed in, the work site itself appears: the protected zone, cones and stop boards at each end,
   a crew, the machine for that department, and the track turning green behind it as the work
   progresses in step with the simulation clock. A long-distance train diverted around a closed
   section leaves the closed track (a ghost of its old path stays behind, crossed out), and travels
   the detour on the same clock.

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
const DEPT_COLOR: Record<string, string> = { PWI: '#3b82f6', OWD: '#f97316', S_AND_T: '#14b8a6' }
const DEPT_NAME: Record<string, string> = { PWI: 'P.Way', OWD: 'Overhead', S_AND_T: 'S&T' }
const TRAIN = { local: '#111827', intercity: '#f59e0b', freight: '#92400e', reroute: '#0891b2' }

// Physical track order across a section, outside to inside: slow lines outside, fast lines in the
// middle. Two-track sections are DN | UP.
const LANE_RANK: Record<string, number> = {
  DN_SLOW: 0, DN_FAST: 1, UP_FAST: 2, UP_SLOW: 3, DN: 1, UP: 2,
}
const LANE_GAP = 3.7          // screen px between adjacent tracks when zoomed out
const laneList = (tracks: string[]) =>
  [...tracks].sort((a, b) => (LANE_RANK[a] ?? 9) - (LANE_RANK[b] ?? 9))

const MIN_SCALE_FACTOR = 0.35
const MAX_SCALE_FACTOR = 18
const PROTECT_S = 15 * 60     // protection is set before work starts and lifted after it ends
const HANDBACK_S = 10 * 60

type View = { scale: number; tx: number; ty: number }
type Geom = { x1: number; y1: number; x2: number; y2: number; nx: number; ny: number }

/** A job under way (or about to be) on a section, for the work-site drawing and its caption. */
export interface BlockInfo {
  section: string
  startS: number
  endS: number
  dept?: string
  label?: string
  id?: string
  urgent?: boolean
  level?: string
}
/** "Take me to this job": the map flies there and captions where and when. */
export interface FocusReq {
  key: number
  section: string
  startS: number
  endS?: number
  label?: string
  dept?: string
  track?: string
  id?: string
}

const fmtWhen = (s: number) => `${DAYS[Math.floor(s / 86400) % 7]} ${hhmm(s)}`

export default function NetworkMap({
  net, trains, totalActive, truncated, clock, clockS, selected, onSelect, blocks, blockInfo = {},
  halos = [], reroutes = [], focus = null, onClearFocus,
}: {
  net: NetworkData
  trains: TrainDot[]
  totalActive: number
  truncated: number
  clock: string
  clockS: number
  selected: string | null
  onSelect: (id: string | null) => void
  blocks: Set<string>
  blockInfo?: Record<string, BlockInfo>
  halos?: Halo[]
  reroutes?: RerouteBlock[]
  focus?: FocusReq | null
  onClearFocus?: () => void
}) {
  const [hover, setHover] = useState<Station | null>(null)
  const [isDragging, setIsDragging] = useState(false)
  const svgRef = useRef<SVGSVGElement>(null)
  const justDragged = useRef(false)
  const animRef = useRef(0)

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
  const viewRef = useRef(view)
  viewRef.current = view
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

  const stopAnim = () => cancelAnimationFrame(animRef.current)

  const zoomBy = (factor: number, center?: { x: number; y: number }) => {
    stopAnim()
    setView(v => {
      const next = Math.min(maxScale, Math.max(minScale, v.scale * factor))
      const k = next / v.scale
      const c = center ?? { x: W / 2, y: H / 2 }
      return { scale: next, tx: c.x - (c.x - v.tx) * k, ty: c.y - (c.y - v.ty) * k }
    })
  }

  // Glide to a view: the centre moves linearly and the scale geometrically, so the fly-in reads as
  // one smooth swoop instead of a jump.
  const flyTo = (target: View, ms = 900) => {
    stopAnim()
    const from = viewRef.current
    const c0 = { x: (W / 2 - from.tx) / from.scale, y: (H / 2 - from.ty) / from.scale }
    const c1 = { x: (W / 2 - target.tx) / target.scale, y: (H / 2 - target.ty) / target.scale }
    const t0 = performance.now()
    const step = (now: number) => {
      const k = Math.min(1, (now - t0) / ms)
      const e = k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2
      const s = from.scale * Math.pow(target.scale / from.scale, e)
      const cx = c0.x + (c1.x - c0.x) * e, cy = c0.y + (c1.y - c0.y) * e
      setView({ scale: s, tx: W / 2 - cx * s, ty: H / 2 - cy * s })
      if (k < 1) animRef.current = requestAnimationFrame(step)
    }
    animRef.current = requestAnimationFrame(step)
  }

  // Fit one section on screen, a little above centre so the caption card never covers it.
  const viewForSection = (id: string): View | null => {
    const g = secGeom[id]
    if (!g) return null
    const bw = Math.max(14, Math.abs(g.x2 - g.x1)), bh = Math.max(14, Math.abs(g.y2 - g.y1))
    const s = Math.min(maxScale, Math.min((W - 300) / bw, (H - 260) / bh))
    const cx = (g.x1 + g.x2) / 2, cy = (g.y1 + g.y2) / 2
    return { scale: s, tx: W / 2 - cx * s, ty: H * 0.44 - cy * s }
  }

  const focusKey = focus?.key
  useEffect(() => {
    if (!focus) return
    const v = viewForSection(focus.section)
    if (v) flyTo(v)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusKey])
  useEffect(() => () => stopAnim(), [])

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
    stopAnim()
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
  const zoomRatio = view.scale / initialView.scale
  const zoomedIn = zoomRatio > 1.55
  const detail = zoomRatio > 3           // close enough to draw the work site itself
  // Tracks spread apart as you zoom, so a crew has room to be drawn between them.
  const laneGap = LANE_GAP * (1 + Math.min(2.4, Math.max(0, zoomRatio - 1) * 0.3))
  const laneOffset = (n: number, k: number) => ((k - (n - 1) / 2) * laneGap) / view.scale
  const inv = 1 / view.scale

  // Detours in force right now, and which timetable dots they replace.
  const detours = useMemo(() => reroutes.flatMap(b => b.reroutes.map(r => {
    const secs = r.sections.map(id => secById[id]).filter(Boolean)
    if (!secs.length) return null
    let cur = secs.length === 1 ? secs[0].from
      : ([secs[1].from, secs[1].to].includes(secs[0].from) ? secs[0].to : secs[0].from)
    const nodes = [cur]
    for (const sc of secs) { cur = sc.from === cur ? sc.to : sc.from; nodes.push(cur) }
    const pts = nodes.map(c => byCode[c]).filter(Boolean).map(st => project(st.lat, st.lon))
    if (pts.length < 2) return null
    const cum = [0]
    for (let i = 1; i < pts.length; i++) cum.push(cum[i - 1] + Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]))
    return { block: b, r, pts, cum, total: cum[cum.length - 1] }
  }).filter(Boolean) as { block: RerouteBlock; r: RerouteBlock['reroutes'][number]; pts: [number, number][]; cum: number[]; total: number }[]),
  [reroutes, secById, byCode, project])

  const detourPos = (d: (typeof detours)[number], f: number): [number, number] => {
    const target = d.total * Math.min(1, Math.max(0, f))
    for (let i = 1; i < d.pts.length; i++) {
      if (target <= d.cum[i]) {
        const k = (target - d.cum[i - 1]) / Math.max(1e-6, d.cum[i] - d.cum[i - 1])
        return [d.pts[i - 1][0] + (d.pts[i][0] - d.pts[i - 1][0]) * k, d.pts[i - 1][1] + (d.pts[i][1] - d.pts[i - 1][1]) * k]
      }
    }
    return d.pts[d.pts.length - 1]
  }
  const detourProgress = (r: RerouteBlock['reroutes'][number]) => {
    if (r.enter_s === undefined || r.exit_s === undefined) return null
    const span = r.exit_s + r.added_delay_min * 60 - r.enter_s
    return (clockS - r.enter_s) / Math.max(60, span)
  }
  // a diverted train is not on the closed section: hide the timetable dot while it would be
  const hiddenTrains = useMemo(() => {
    const s = new Set<string>()
    for (const d of detours) {
      const f = detourProgress(d.r)
      if (f !== null && f >= -0.02 && f <= 1.02) s.add(d.r.train_id)
    }
    return s
  }, [detours, clockS])   // eslint-disable-line

  // ---------------------------------------------------------------- the work site
  const workSite = (sec: NetworkData['sections'][number]) => {
    const g = secGeom[sec.id]
    if (!g) return null
    const info = blockInfo[sec.id]
    const lanes = laneList(sec.tracks)
    const swap = reroutes.find(r => r.section_id === sec.id)?.track_swap ?? null
    const mx = (g.x1 + g.x2) / 2, my = (g.y1 + g.y2) / 2
    const dx = g.x2 - g.x1, dy = g.y2 - g.y1
    const start = info?.startS ?? clockS, end = info?.endS ?? clockS + 3600
    const phase = clockS < start ? 'protect' : clockS < end ? 'work' : 'handback'
    const pct = Math.min(1, Math.max(0, (clockS - start) / Math.max(60, end - start)))
    const col = DEPT_COLOR[info?.dept ?? ''] ?? '#f59e0b'
    const urgent = !!info?.urgent
    const closedLanes = lanes.map((tr, k) => ({ tr, k })).filter(l => !swap || l.tr === swap.blocked_track)
    const bundle = closedLanes.length * laneGap
    const at = (t: number, o: number) => [g.x1 + dx * t + g.nx * o, g.y1 + dy * t + g.ny * o] as const
    const mainLane = closedLanes[Math.floor(closedLanes.length / 2)] ?? { tr: lanes[0], k: 0 }
    const mo = laneOffset(lanes.length, mainLane.k)
    const [px, py] = at(pct, mo)

    return (
      <g key={`bl-${sec.id}`} pointerEvents="none">
        {lanes.map((tr, k) => {
          const o = laneOffset(lanes.length, k)
          const closed = !swap || tr === swap.blocked_track
          const takingOver = !!swap && tr === swap.swap_to_track
          if (!closed && !takingOver) return null
          const p = { x1: g.x1 + g.nx * o, y1: g.y1 + g.ny * o, x2: g.x2 + g.nx * o, y2: g.y2 + g.ny * o }
          const w = Math.max(4.4, laneGap * 0.85)
          return closed ? (
            <g key={tr}>
              <line {...p} stroke={urgent ? '#ef4444' : '#f59e0b'} strokeWidth={w} vectorEffect="non-scaling-stroke" />
              <line {...p} stroke="#111827" strokeWidth={w} strokeDasharray="5 5" vectorEffect="non-scaling-stroke">
                <animate attributeName="stroke-dashoffset" from="20" to="0" dur="0.7s" repeatCount="indefinite" />
              </line>
              {/* work done so far: the hazard stripes give way to green behind the machine */}
              {pct > 0 && (
                <line x1={p.x1} y1={p.y1} x2={p.x1 + (p.x2 - p.x1) * pct} y2={p.y1 + (p.y2 - p.y1) * pct}
                      stroke="#22c55e" strokeWidth={w} strokeLinecap="butt" vectorEffect="non-scaling-stroke" />
              )}
            </g>
          ) : (
            <g key={tr}>
              <line {...p} stroke="#22c55e" strokeWidth={Math.max(3, laneGap * 0.7)} strokeDasharray="9 5"
                    vectorEffect="non-scaling-stroke">
                <animate attributeName="stroke-dashoffset" from="28" to="0" dur="1.1s" repeatCount="indefinite" />
              </line>
            </g>
          )
        })}

        {/* single-line working: crossovers at each end let trains change over to the open track */}
        {swap && detail && (() => {
          const a = laneOffset(lanes.length, lanes.indexOf(swap.blocked_track))
          const b = laneOffset(lanes.length, lanes.indexOf(swap.swap_to_track))
          return [0.05, 0.95].map(t => {
            const [x1, y1] = at(t - 0.03, a), [x2, y2] = at(t + 0.03, b)
            const [q1x, q1y] = at(t + 0.03, a), [q2x, q2y] = at(t - 0.03, b)
            return (
              <g key={t}>
                <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="#22c55e" strokeWidth={2} vectorEffect="non-scaling-stroke" />
                <line x1={q1x} y1={q1y} x2={q2x} y2={q2y} stroke="#22c55e" strokeWidth={2} vectorEffect="non-scaling-stroke" />
              </g>
            )
          })
        })()}

        {/* zoomed out: a beacon and a gear at the middle is all the detail there is room for */}
        {!detail && (
          <g transform={`translate(${mx},${my}) scale(${inv})`}>
            {[0, 0.9].map(delay => (
              <circle key={delay} r={6} fill="none" stroke={urgent ? '#ef4444' : col} strokeWidth={1.8}>
                <animate attributeName="r" values="6;26" dur="1.8s" begin={`${delay}s`} repeatCount="indefinite" />
                <animate attributeName="opacity" values="0.9;0" dur="1.8s" begin={`${delay}s`} repeatCount="indefinite" />
              </circle>
            ))}
            <circle r={7.5} fill="#111827" stroke={urgent ? '#ef4444' : '#f59e0b'} strokeWidth={1.4} />
            <circle r={5} fill="none" stroke={urgent ? '#ef4444' : '#f59e0b'} strokeWidth={2.6} strokeDasharray="2.6 2.6">
              <animateTransform attributeName="transform" type="rotate" from="0" to="360" dur="3.5s" repeatCount="indefinite" />
            </circle>
          </g>
        )}

        {/* zoomed in: the work site */}
        {detail && (
          <g>
            {/* the protected zone */}
            <line x1={g.x1} y1={g.y1} x2={g.x2} y2={g.y2} stroke={col} strokeOpacity={0.14}
                  strokeWidth={bundle + 16} strokeLinecap="round" vectorEffect="non-scaling-stroke" />
            {[-1, 1].map(sd => {
              const off = (sd * (bundle / 2 + 6)) / view.scale
              return <line key={sd} x1={g.x1 + g.nx * off} y1={g.y1 + g.ny * off} x2={g.x2 + g.nx * off}
                           y2={g.y2 + g.ny * off} stroke={col} strokeWidth={1.4} strokeDasharray="6 4"
                           strokeOpacity={0.8} vectorEffect="non-scaling-stroke" />
            })}

            {/* cones and stop boards at both ends: they go up before work and come down after */}
            {[0.02, 0.98].map((t, i) => (
              <g key={t} opacity={phase === 'handback' && pct >= 1 ? 0.5 : 1}>
                {closedLanes.map(({ tr, k }) => {
                  const [cx, cy] = at(t, laneOffset(lanes.length, k))
                  return (
                    <g key={tr} transform={`translate(${cx},${cy}) scale(${inv})`}>
                      <polygon points="0,-4.2 -3.2,3 3.2,3" fill="#f97316" stroke="#fff" strokeWidth={0.7} />
                      <rect x={-1.7} y={-0.6} width={3.4} height={1.2} fill="#fff" />
                    </g>
                  )
                })}
                {(() => {
                  const [cx, cy] = at(i === 0 ? -0.012 : 1.012, laneOffset(lanes.length, mainLane.k))
                  return (
                    <g transform={`translate(${cx},${cy}) scale(${inv})`}>
                      <line x1={0} y1={0} x2={0} y2={-11} stroke="#e5e7eb" strokeWidth={1.2} />
                      <circle cy={-13} r={4.2} fill="#dc2626" stroke="#fff" strokeWidth={1}>
                        {phase === 'protect' && <animate attributeName="opacity" values="1;0.25;1" dur="0.9s" repeatCount="indefinite" />}
                      </circle>
                      <rect x={-2.6} y={-13.7} width={5.2} height={1.4} fill="#fff" />
                    </g>
                  )
                })()}
              </g>
            ))}

            {/* the crew walk the closed track around the machine */}
            {phase === 'work' && [0, 1, 2, 3].map(i => {
              const lane = closedLanes[i % Math.max(1, closedLanes.length)] ?? mainLane
              const o = laneOffset(lanes.length, lane.k) + ((i % 2 ? 1 : -1) * 3.2) / view.scale
              const t0 = Math.max(0, pct - 0.09), t1 = Math.min(1, pct + 0.09)
              const [ax, ay] = at(t0, o), [bx, by] = at(t1, o)
              return (
                <g key={i} transform={`scale(${inv})`}>
                  <circle r={2.1} fill="#facc15" stroke="#111827" strokeWidth={0.8}>
                    <animate attributeName="cx" values={`${ax * view.scale};${bx * view.scale};${ax * view.scale}`}
                             dur={`${5 + i * 1.7}s`} begin={`${i * 0.6}s`} repeatCount="indefinite" />
                    <animate attributeName="cy" values={`${ay * view.scale};${by * view.scale};${ay * view.scale}`}
                             dur={`${5 + i * 1.7}s`} begin={`${i * 0.6}s`} repeatCount="indefinite" />
                  </circle>
                </g>
              )
            })}

            {/* the machine, at the point the work has reached */}
            <g transform={`translate(${px},${py}) rotate(${(Math.atan2(dy, dx) * 180) / Math.PI}) scale(${inv})`}>
              {info?.dept === 'OWD' ? (
                <g>
                  <rect x={-9} y={-3.4} width={18} height={6.8} rx={1.4} fill="#f97316" stroke="#111827" strokeWidth={0.9} />
                  <line x1={0} y1={-3.4} x2={0} y2={-10} stroke="#111827" strokeWidth={1.6} />
                  <ellipse cx={0} cy={-11} rx={4.4} ry={1.7} fill="#fde68a" stroke="#111827" strokeWidth={0.8}>
                    <animate attributeName="cy" values="-11;-13;-11" dur="1.8s" repeatCount="indefinite" />
                  </ellipse>
                </g>
              ) : info?.dept === 'S_AND_T' ? (
                <g>
                  <rect x={-8} y={-3.4} width={16} height={6.8} rx={1.4} fill="#e5e7eb" stroke="#111827" strokeWidth={0.9} />
                  <circle cx={5} cy={-1} r={1.7} fill="#22c55e"><animate attributeName="opacity" values="1;0.2;1" dur="0.8s" repeatCount="indefinite" /></circle>
                  <rect x={-6} y={-1.6} width={6} height={3.2} fill="#93c5fd" />
                </g>
              ) : (
                <g>
                  <rect x={-10} y={-3.4} width={20} height={6.8} rx={1.4} fill="#facc15" stroke="#111827" strokeWidth={0.9} />
                  {[-5, 0, 5].map(x => (
                    <line key={x} x1={x} y1={3.4} x2={x} y2={7.2} stroke="#111827" strokeWidth={1.6}>
                      <animate attributeName="y2" values="7.2;4.6;7.2" dur="0.5s" begin={`${(x + 5) * 0.05}s`} repeatCount="indefinite" />
                    </line>
                  ))}
                  <circle cx={-6} cy={-3.4} r={1.1} fill="#111827" /><circle cx={6} cy={-3.4} r={1.1} fill="#111827" />
                </g>
              )}
              {(phase === 'work' || urgent) && (
                <circle cx={0} cy={-15} r={2.6} fill={urgent ? '#ef4444' : '#f59e0b'}>
                  <animate attributeName="opacity" values="1;0.1;1" dur={urgent ? '0.45s' : '0.9s'} repeatCount="indefinite" />
                </circle>
              )}
            </g>

            {/* caption over the site */}
            <g transform={`translate(${mx},${my}) scale(${inv})`}>
              <g transform="translate(0,-34)">
                <rect x={-96} y={-24} width={192} height={38} rx={6} fill="#0b1017" fillOpacity={0.94} stroke={col} strokeWidth={1.2} />
                <text x={-88} y={-10} fontSize={10.5} fill="#f8fafc" fontWeight={650}>
                  {(urgent ? `URGENT ${info?.level ?? ''} · ` : '') + (DEPT_NAME[info?.dept ?? ''] ?? 'Work')}
                  {info?.label ? ` · ${info.label.length > 22 ? info.label.slice(0, 21) + '…' : info.label}` : ''}
                </text>
                <text x={-88} y={3} fontSize={9.5} fill="#cbd5e1" fontFamily="var(--mono)">
                  {phase === 'protect' ? `protecting the line · starts ${hhmm(start)}`
                    : phase === 'work' ? `${hhmm(start)}–${hhmm(end)} · ${Math.round(pct * 100)}% done`
                    : 'work complete · handing back'}
                </text>
                <rect x={-88} y={7} width={176} height={3} rx={1.5} fill="#334155" />
                <rect x={-88} y={7} width={176 * pct} height={3} rx={1.5} fill="#22c55e" />
              </g>
            </g>
          </g>
        )}
      </g>
    )
  }

  // ---------------------------------------------------------------- the focus pin and caption
  const fSec = focus ? secById[focus.section] : null
  const fGeom = focus ? secGeom[focus.section] : undefined
  const fEnd = focus ? (focus.endS ?? focus.startS + 3600) : 0
  const fState = !focus ? '' : clockS < focus.startS - PROTECT_S
    ? `starts in ${Math.max(1, Math.round((focus.startS - clockS) / 60))} min`
    : clockS < focus.startS ? 'protecting the line'
    : clockS < fEnd ? `in progress · ${Math.round(((clockS - focus.startS) / Math.max(60, fEnd - focus.startS)) * 100)}%`
    : 'finished'

  return (
    <div className="map-wrap">
      <div className="map-live"><i />LIVE SIMULATION</div>
      <div className="map-controls">
        <button onClick={() => zoomBy(1.4)} title="Zoom in">+</button>
        <button onClick={() => zoomBy(1 / 1.4)} title="Zoom out">−</button>
        <button onClick={() => { flyTo(initialView, 700) }} title="Reset view" style={{ fontSize: 11 }}>⤾</button>
      </div>

      {focus && fSec && (
        <div className="focus-card">
          <button className="fc-x" onClick={onClearFocus} aria-label="Close">×</button>
          <div className="fc-top">
            {focus.dept && <span className={`badge dept ${focus.dept}`}>{DEPT_NAME[focus.dept] ?? focus.dept}</span>}
            <b>{focus.label ?? 'Maintenance job'}</b>
          </div>
          <div className="fc-row"><span>Where</span>
            <b>{byCode[fSec.from]?.name} → {byCode[fSec.to]?.name}</b></div>
          <div className="fc-row"><span>Track</span><b className="mono">{focus.track ?? fSec.tracks.join(' ')}</b></div>
          <div className="fc-row"><span>When</span><b>{fmtWhen(focus.startS)} – {hhmm(fEnd)}</b></div>
          <div className="fc-row"><span>Status</span><b className="fc-state">{fState}</b></div>
          <div className="fc-bar"><i style={{ width: `${Math.min(100, Math.max(0, ((clockS - focus.startS) / Math.max(60, fEnd - focus.startS)) * 100))}%` }} /></div>
          <button className="action" style={{ marginTop: 8, padding: '4px 10px', fontSize: 11.5 }}
                  onClick={() => { const v = viewForSection(focus.section); if (v) flyTo(v) }}>Zoom to job</button>
        </div>
      )}

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
              <g key={`halo-${i}`} transform={`translate(${x},${y}) scale(${inv})`} pointerEvents="none">
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
                    stroke={STATUS[sec.status]} strokeWidth={laneGap * sec.tracks.length + 8}
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
                        strokeWidth={laneGap * lanes.length + 10} strokeLinecap="round"
                        vectorEffect="non-scaling-stroke" />
                )}
                {lanes.map((tr, k) => {
                  const o = laneOffset(lanes.length, k)
                  const fast = tr.endsWith('_FAST')
                  return (
                    <line key={tr} x1={g.x1 + g.nx * o} y1={g.y1 + g.ny * o}
                          x2={g.x2 + g.nx * o} y2={g.y2 + g.ny * o}
                          stroke={tint} strokeWidth={sel ? 2.2 : detail ? 2.4 : 1.8} strokeLinecap="butt"
                          strokeOpacity={fast ? 1 : 0.7} vectorEffect="non-scaling-stroke" />
                  )
                })}
                {/* zoomed in, name the tracks so "UP_SLOW closed" can be read off the map */}
                {detail && (sel || blocks.has(sec.id) || focus?.section === sec.id) && lanes.map((tr, k) => {
                  const o = laneOffset(lanes.length, k)
                  return (
                    <text key={`lbl-${tr}`} transform={`translate(${g.x1 + (g.x2 - g.x1) * 0.14 + g.nx * o},${g.y1 + (g.y2 - g.y1) * 0.14 + g.ny * o}) scale(${inv})`}
                          fontSize={7.5} fill="#475569" fontFamily="var(--mono)" textAnchor="middle" dy={-2.6}
                          stroke="#fff" strokeWidth={2.4} paintOrder="stroke" pointerEvents="none">{tr.replace('_', ' ')}</text>
                  )
                })}
              </g>
            )
          })}

          {/* maintenance: everything about a closed track and the crew on it */}
          {net.sections.filter(sec => blocks.has(sec.id)).map(sec => workSite(sec))}

          {/* the reroute: the closed path ghosted and crossed out, the detour lit, the train on it */}
          {detours.map(d => {
            const { block: b, r, pts } = d
            const g = secGeom[b.section_id]
            const path = 'M ' + pts.map(([x, y]) => `${x.toFixed(2)},${y.toFixed(2)}`).join(' L ')
            const f = detourProgress(r)
            const onDetour = f !== null && f > 0 && f < 1
            const [tx, ty] = detourPos(d, f ?? 0.5)
            const mid = detourPos(d, 0.5)
            return (
              <g key={`rr-${b.section_id}-${r.train_id}`} pointerEvents="none">
                {g && (
                  <g>
                    <line x1={g.x1} y1={g.y1} x2={g.x2} y2={g.y2} stroke="#64748b" strokeWidth={5} strokeDasharray="2 5"
                          strokeLinecap="round" strokeOpacity={0.9} vectorEffect="non-scaling-stroke" />
                    <g transform={`translate(${(g.x1 + g.x2) / 2},${(g.y1 + g.y2) / 2}) scale(${inv})`}>
                      <circle r={6.5} fill="#fff" stroke="#64748b" strokeWidth={1.2} />
                      <path d="M-3 -3L3 3M3 -3L-3 3" stroke="#dc2626" strokeWidth={1.8} strokeLinecap="round" />
                    </g>
                  </g>
                )}
                <path d={path} fill="none" stroke={TRAIN.reroute} strokeWidth={9} strokeOpacity={0.18}
                      strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
                <path d={path} fill="none" stroke={TRAIN.reroute} strokeWidth={2.6} strokeDasharray="7 5"
                      strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke">
                  <animate attributeName="stroke-dashoffset" from="24" to="0" dur="0.9s" repeatCount="indefinite" />
                </path>
                {/* chevrons streaming along the detour */}
                {[0, 1, 2].map(i => (
                  <g key={i}>
                    <animateMotion path={path} dur="6s" begin={`${i * 2}s`} repeatCount="indefinite" rotate="auto" />
                    <g transform={`scale(${inv})`}>
                      <path d="M-3.4 -3L2.6 0L-3.4 3" fill="none" stroke={TRAIN.reroute} strokeWidth={2} strokeLinecap="round" />
                    </g>
                  </g>
                ))}
                {onDetour && (
                  <g transform={`translate(${tx},${ty}) scale(${inv})`}>
                    <circle r={9} fill={TRAIN.reroute} fillOpacity={0.25}>
                      <animate attributeName="r" values="7;12;7" dur="1.4s" repeatCount="indefinite" />
                    </circle>
                    <circle r={5.4} fill={TRAIN.reroute} stroke="#fff" strokeWidth={1.6} />
                    <circle r={1.6} fill="#fff" />
                  </g>
                )}
                <g transform={`translate(${mid[0]},${mid[1]}) scale(${inv})`}>
                  <g transform="translate(0,-16)">
                    <rect x={-58} y={-9} width={116} height={17} rx={8.5} fill="#0e7490" stroke="#fff" strokeWidth={1} />
                    <text y={3} fontSize={9.5} fill="#fff" textAnchor="middle" fontWeight={650}>
                      {(r.train_name || r.train_id).slice(0, 16)} · +{Math.round(r.added_delay_min)} min
                    </text>
                  </g>
                </g>
              </g>
            )
          })}

          {/* clickable hit areas */}
          {net.sections.map(sec => {
            const g = secGeom[sec.id]
            if (!g) return null
            return (
              <line key={`hit-${sec.id}`} x1={g.x1} y1={g.y1} x2={g.x2} y2={g.y2}
                    stroke="transparent" strokeWidth={laneGap * sec.tracks.length + 8}
                    vectorEffect="non-scaling-stroke" style={{ cursor: 'pointer' }}
                    onClick={pick(sec.id)} />
            )
          })}

          {/* stations, inverse-scaled so markers and labels keep a constant, legible size */}
          {net.stations.map(st => {
            const [x, y] = project(st.lat, st.lon)
            const interchange = (st.lines?.length ?? 0) > 1
            const r = interchange ? 5.4 : st.tier === 'TIER_1' ? 4.4 : st.tier === 'TIER_2' ? 3.2 : 2.6
            const near = !!fSec && (st.code === fSec.from || st.code === fSec.to)
            const label = interchange || st.tier === 'TIER_1' || (zoomedIn && st.tier === 'TIER_2')
                        || (zoomRatio > 3.2) || near
            return (
              <g key={st.code} transform={`translate(${x},${y}) scale(${inv})`}
                 onMouseEnter={() => setHover(st)} onMouseLeave={() => setHover(null)}
                 style={{ cursor: 'default' }}>
                <circle r={r + 5} fill="transparent" />
                <circle r={r} fill="#fff" stroke="#111827" strokeWidth={interchange ? 2.2 : 1.4} />
                {label && (
                  <text x={r + 5} y={3.6} fontSize={near ? 11 : 9.5} fill="#111827" fontFamily="var(--mono)"
                        fontWeight={interchange || near ? 700 : 500} stroke="#fff" strokeWidth={3}
                        paintOrder="stroke">{zoomRatio > 3.2 || near ? st.name : st.code}</text>
                )}
              </g>
            )
          })}

          {/* trains: black dot = local, orange ringed = intercity, brown square = freight */}
          {trains.filter(t => !hiddenTrains.has(t.id)).map(t => {
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
            const gt = `translate(${x},${y}) scale(${inv})`
            const grow = detail ? 1.5 : 1
            if (t.cls === 'SUBURBAN_LOCAL')
              return <g key={t.id} transform={gt}>
                <circle r={2.4 * grow} fill={TRAIN.local} stroke="#fff" strokeWidth={0.9} />
              </g>
            if (t.cls === 'FREIGHT_MAIL')
              return <g key={t.id} transform={gt}>
                <rect x={-2.9 * grow} y={-2.9 * grow} width={5.8 * grow} height={5.8 * grow} rx={1} fill={TRAIN.freight}
                      stroke="#fff" strokeWidth={0.9} />
              </g>
            return (
              <g key={t.id} transform={gt}>
                <circle r={4.6 * grow} fill={TRAIN.intercity} stroke="#111827" strokeWidth={1.3} />
                <circle r={1.5 * grow} fill="#111827" />
              </g>
            )
          })}

          {/* the focus pin: where the job is, even before it starts */}
          {focus && fGeom && (() => {
            const mx = (fGeom.x1 + fGeom.x2) / 2, my = (fGeom.y1 + fGeom.y2) / 2
            const active = clockS >= focus.startS - PROTECT_S && clockS < fEnd + HANDBACK_S
            return (
              <g transform={`translate(${mx},${my}) scale(${inv})`} pointerEvents="none">
                {[0, 0.8, 1.6].map(d => (
                  <circle key={d} r={10} fill="none" stroke="#f59e0b" strokeWidth={2.2}>
                    <animate attributeName="r" values="10;48" dur="2.4s" begin={`${d}s`} repeatCount="indefinite" />
                    <animate attributeName="opacity" values="0.9;0" dur="2.4s" begin={`${d}s`} repeatCount="indefinite" />
                  </circle>
                ))}
                {!active && (
                  <g transform="translate(0,-46)">
                    <path d="M0 40 L-7 24 A14 14 0 1 1 7 24 Z" fill="#f59e0b" stroke="#111827" strokeWidth={1.4} />
                    <circle cy={14} r={5} fill="#111827" />
                  </g>
                )}
              </g>
            )
          })()}
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
                    fill="#0b0f16" stroke="#334155" />
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
        <span><i className="dot" style={{ background: TRAIN.reroute }} />Diverted train</span>
        <span className="sep" />
        <span><i style={{ background: 'repeating-linear-gradient(45deg,#f59e0b 0 3px,#111827 3px 6px)' }} />Track closed for work</span>
        <span><i style={{ background: '#22c55e' }} />Work done / single-line</span>
        <span><i style={{ background: 'repeating-linear-gradient(90deg,#64748b 0 2px,transparent 2px 5px)' }} />Old path (closed)</span>
        <span className="sep" />
        <span className="muted" style={{ fontStyle: 'italic' }}>zoom in to see the crew and machine at work</span>
      </div>
    </div>
  )
}
