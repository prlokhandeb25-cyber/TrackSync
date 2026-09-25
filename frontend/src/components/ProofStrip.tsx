import { useEffect, useState } from 'react'
import { api, type AvailabilityData, type ProofData } from '../api'

/* Measured evidence, one tile per algorithm. Every figure is read from a run that happened -
   the interval-tree timing is a real benchmark against a full scan, the solver figures are the
   last real solve, the live counts move as the simulation ticks. Hover a tile for the detail. */

const k = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n))

export default function ProofStrip({ tick }: { tick: number }) {
  const [p, setP] = useState<ProofData | null>(null)
  const [av, setAv] = useState<AvailabilityData | null>(null)
  useEffect(() => {
    const pull = () => {
      api.proof().then(setP).catch(() => { /* next pull retries */ })
      api.availability().then(setAv).catch(() => { /* next pull retries */ })
    }
    void pull()
    const id = setInterval(pull, 4000)
    return () => clearInterval(id)
  }, [tick])
  if (!p) return null

  const tiles: { v: string; label: string; sub: string; tip: string; color?: string }[] = [
    ...(av ? [{ v: `${av.service_pct.toFixed(2)}%`, label: 'asset availability, service hours', color: 'var(--fit)', sub: '',
      tip: `Track open to traffic in service hours (04:00-24:00): ${av.service_pct}%. Train movements this week that were not due on a line while it was closed: ${av.train_pct}% (${av.trains_meeting_a_closed_line} of ${av.train_movements} met a closed line). `
        + `Track open to traffic: ${av.line_pct}% of line-km-hours over the week, ${av.service_pct}% in service hours (04:00-24:00). `
        + `Had each block closed every line of its section: ${av.if_whole_section.train_pct}% of movements, ${av.if_whole_section.service_pct}% in service hours. ${av.how}` }] : []),
    { v: k(p.gaps.total), label: 'gaps found', color: 'var(--accent)',
      sub: '',
      tip: `${p.gaps.micro} gaps between trains, ${p.gaps.night} night windows, ${p.gaps.megablock} megablock windows` },
    { v: `${p.cpsat.placed}/${p.cpsat.n_tasks}`, label: 'jobs in the weekly plan', color: 'var(--fit)',
      sub: '',
      tip: `CP-SAT solve, ${p.cpsat.status.toLowerCase()}, ${Math.round(p.cpsat.gap_pct * 10) / 10}% gap, ${p.cpsat.wall_s}s wall time` },
    ...(p.rl ? [{ v: `${p.rl.speedup_x}×`, label: 'faster re-plan', color: 'var(--accent)',
      sub: '',
      tip: `Held-out benchmark over ${p.rl.instances} instances` }] : []),
    { v: `${p.rerouting.executed}`, label: 'trains rerouted', color: '#0891b2',
      sub: '',
      tip: 'Long-distance and freight trains due through a section while it was closed. Locals are never rerouted.' },
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
              {t.sub && <div className="note">{t.sub}</div>}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
