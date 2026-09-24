import { useEffect, useMemo, useState } from 'react'
import { api, type ClusterTrace } from '../api'

/* How jobs were grouped: a dendrogram of the real merge history. Every job starts alone; the two
   closest groups join, again and again, and the height of each join is the distance in km. Joins
   stop at the cut line (config clustering.cut_km): what hangs below it together is one group -
   jobs close enough to share a protected block. */

const PALETTE = ['#0284c7', '#65a30d', '#d97706', '#dc2626', '#c026d3',
                 '#4f46e5', '#0d9488', '#ea580c', '#7c3aed', '#16a34a']
const W = 640, H = 230, PADL = 34, PADB = 34

export default function ClusterProof() {
  const [d, setD] = useState<ClusterTrace | null>(null)
  useEffect(() => { api.explainClusters().then(setD).catch(() => undefined) }, [])

  const layout = useMemo(() => {
    if (!d || d.points.length < 2) return null
    const n = d.points.length
    const kids = new Map<number, [number, number]>()
    d.merges.forEach(m => kids.set(m.id, [m.a, m.b]))
    const dist = new Map<number, number>(d.merges.map(m => [m.id, m.distance_km]))
    const order: number[] = []
    const walk = (id: number) => { const k = kids.get(id); if (!k) { order.push(id); return } walk(k[0]); walk(k[1]) }
    const root = d.merges[d.merges.length - 1].id
    walk(root)
    const pos = new Map<number, { x: number; y: number }>()
    order.forEach((id, i) => pos.set(id, { x: PADL + ((i + 0.5) / n) * (W - PADL - 8), y: 0 }))
    const maxD = Math.max(...d.merges.map(m => m.distance_km), d.cut_km * 1.3)
    const yOf = (km: number) => H - PADB - (km / maxD) * (H - PADB - 10)
    d.merges.forEach(m => {
      const a = pos.get(m.a)!, b = pos.get(m.b)!
      pos.set(m.id, { x: (a.x + b.x) / 2, y: yOf(m.distance_km) })
    })
    for (const id of order) pos.get(id)!.y = yOf(0)
    return { order, pos, dist, maxD, yOf, kids }
  }, [d])

  if (!d) return <div className="panel"><div className="panel-body loading"><div className="spinner" />Replaying the clustering…</div></div>
  if (!layout) return <div className="panel"><div className="panel-body muted">Not enough jobs to cluster yet.</div></div>

  const color = (leaf: number) => PALETTE[(d.points[leaf].cluster - 1) % PALETTE.length]
  const leavesOf = (id: number): number[] => {
    const k = layout.kids.get(id)
    return k ? [...leavesOf(k[0]), ...leavesOf(k[1])] : [id]
  }
  const big = d.clusters.filter(c => c.size > 1)

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>2 · Grouping the jobs</h2>
        <span className="sub">{d.points.length} jobs → {big.length} shared groups</span>
      </div>
      <div className="panel-body">
        <p className="explain">
          Jobs that are close and similarly urgent join first (each priority step counts as 2 km). Joins stop at <b>{d.cut_km}</b> (dashed): jobs still together can share one block.
        </p>
        <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="Dendrogram of job groups">
          {[0, 0.25, 0.5, 0.75, 1].map(f => {
            const km = f * layout.maxD
            return (
              <g key={f}>
                <line x1={PADL} x2={W - 8} y1={layout.yOf(km)} y2={layout.yOf(km)} stroke="var(--line-soft)" />
                <text x={PADL - 5} y={layout.yOf(km) + 3} fontSize={9} textAnchor="end" fill="var(--text-mute)"
                      fontFamily="var(--mono)">{km.toFixed(0)}</text>
              </g>
            )
          })}
          <text x={4} y={12} fontSize={9} fill="var(--text-mute)">distance (km + urgency)</text>
          {d.merges.map((m, i) => {
            const a = layout.pos.get(m.a)!, b = layout.pos.get(m.b)!, p = layout.pos.get(m.id)!
            const below = m.distance_km <= d.cut_km
            const col = below ? color(leavesOf(m.id)[0]) : '#64748b'
            const path = `M ${a.x} ${a.y} V ${p.y} H ${b.x} V ${b.y}`
            return (
              <path key={m.id} d={path} fill="none" stroke={col} strokeWidth={below ? 1.6 : 1}
                    strokeOpacity={below ? 0.95 : 0.55} pathLength={1} strokeDasharray={1} strokeDashoffset={1}
                    style={{ animation: `draw-line .5s ${Math.min(i * 22, 900)}ms forwards` }} />
            )
          })}
          <line x1={PADL} x2={W - 8} y1={layout.yOf(d.cut_km)} y2={layout.yOf(d.cut_km)} stroke="var(--sick)"
                strokeDasharray="5 4" strokeWidth={1.3} />
          <text x={W - 10} y={layout.yOf(d.cut_km) - 4} fontSize={10} textAnchor="end" fill="var(--sick)">cut at {d.cut_km} km</text>
          {layout.order.map(id => {
            const p = layout.pos.get(id)!
            return (
              <g key={id}>
                <circle cx={p.x} cy={p.y} r={3.2} fill={color(id)} />
                <text x={p.x} y={p.y + 12} fontSize={7} fill="var(--text-mute)" textAnchor="end"
                      transform={`rotate(-60 ${p.x} ${p.y + 12})`} fontFamily="var(--mono)">{d.points[id].zone}</text>
              </g>
            )
          })}
        </svg>
        <div className="chips">
          {big.map(c => (
            <span key={c.id} className="chip">
              <i style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%', marginRight: 6,
                          background: PALETTE[(c.id - 1) % PALETTE.length] }} />
              <b>{c.size}</b> jobs · {c.label} · {c.departments.map(x => x === 'S_AND_T' ? 'S&T' : x).join('+')}
            </span>
          ))}
        </div>
      </div>
    </div>
  )
}
