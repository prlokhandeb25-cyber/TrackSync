import { useEffect, useState } from 'react'
import { api, type ProofData } from '../api'

/* Measured evidence, one tile per algorithm. Every figure is read from a run that happened -
   the interval-tree timing is a real benchmark against a full scan, the solver figures are the
   last real solve, the live counts move as the simulation ticks. Hover a tile for the detail. */

const k = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n))

export default function ProofStrip({ tick }: { tick: number }) {
  const [p, setP] = useState<ProofData | null>(null)
  useEffect(() => {
    const pull = () => api.proof().then(setP).catch(() => { /* next pull retries */ })
    void pull()
    const id = setInterval(pull, 4000)
    return () => clearInterval(id)
  }, [tick])
  if (!p) return null

  const tiles: { v: string; label: string; sub: string; tip: string; color?: string }[] = [
    { v: k(p.gaps.total), label: 'gaps found', color: 'var(--accent)',
      sub: `${k(p.gaps.micro)} between trains · ${p.gaps.usable_hours.toLocaleString()} h usable`,
      tip: `${p.gaps.micro} gaps between trains, ${p.gaps.night} night windows, ${p.gaps.megablock} megablock windows` },
    { v: `${p.interval_tree.speedup_x}×`, label: 'faster gap lookup', color: 'var(--fit)',
      sub: p.interval_tree.identical ? 'same answers as full scan ✓' : 'MISMATCH',
      tip: `${p.interval_tree.queries} range queries: full scan ${p.interval_tree.scan_ms} ms, interval tree ${p.interval_tree.tree_ms} ms` },
    { v: `${p.clusters.clusters}`, label: 'job clusters',
      sub: `from ${p.clusters.tasks} jobs · ${p.clusters.compatible}/${p.clusters.cross_pairs} pairs compatible`,
      tip: 'Average-linkage hierarchical clustering by location; compatibility from the rule engine' },
    { v: p.cpsat.status === 'OPTIMAL' ? 'Optimal' : p.cpsat.status.replace('_', ' ').toLowerCase(),
      label: 'weekly plan', color: 'var(--fit)',
      sub: `${Math.round(p.cpsat.gap_pct * 10) / 10}% gap · ${p.cpsat.placed}/${p.cpsat.n_tasks} placed`,
      tip: `CP-SAT solve, ${p.cpsat.wall_s}s wall time` },
    ...(p.rl ? [{ v: `${p.rl.speedup_x}×`, label: 'faster re-plan', color: 'var(--accent)',
      sub: `${p.rl.policy} · ${Math.round(p.rl.gap_pct * 10) / 10}% from optimal`,
      tip: `Held-out benchmark over ${p.rl.instances} instances` }] : []),
    { v: `${p.live_sim.placed}/${p.live_sim.arrived}`, label: 'placed live',
      sub: p.live_sim.moved_aside ? `${p.live_sim.moved_aside} moved aside` : 'longest job first',
      tip: 'Max-to-Min ordering + ALNS-lite insertion on simulated arrivals' },
    { v: `${p.rerouting.executed}`, label: 'trains rerouted', color: '#0891b2',
      sub: 'sent around live blocks',
      tip: 'Long-distance and freight trains due through a section while it was closed. Locals are never rerouted.' },
    { v: `${p.rerouting.with_lever}/${p.rerouting.unplaced}`, label: 'unplaced with a fix',
      sub: `${p.rerouting.reroute_paths} reroutes · ${p.rerouting.track_swaps} track swaps`,
      tip: 'Unplaced jobs for which a reroute or single-line working could open a window' },
  ]

  return (
    <div className="panel">
      <div className="panel-head"><h2>Proof it works</h2><span className="sub">measured, live</span></div>
      <div className="panel-body">
        <div className="tiles mini">
          {tiles.map(t => (
            <div className="tile" key={t.label} title={t.tip}>
              <div className="v" style={{ color: t.color }}>{t.v}</div>
              <div className="k">{t.label}</div>
              <div className="note">{t.sub}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
