import { useEffect, useRef, useState } from 'react'
import { api, type ScaleData, type StudioJob } from '../api'
import { Num } from './Viz'

/* Scaling studio: the one job of this page is to show that the algorithm holds up on big batches. The same weekly
   model is run on random 40, 100, 200 and 400 jobs by the exact solver, and on 800 and 1,600 by the fast path; each
   result shows how long it took, how close to the best possible plan it got, and whether an independent checker
   still finds every rule satisfied. Nothing here is rounded up: where the solver could not prove optimality, the gap
   it reached is shown. */

const COLORS = ['#0284c7', '#65a30d', '#d97706', '#c026d3']
const secs = (v: number | null | undefined) => (v === null || v === undefined ? 'not reached' : v < 10 ? `${v.toFixed(1)} s` : `${Math.round(v)} s`)

function usePoll(fetcher: () => Promise<StudioJob<ScaleData>>) {
  const [job, setJob] = useState<StudioJob<ScaleData> | null>(null)
  const alive = useRef(true)
  const load = () => fetcher().then(j => { if (alive.current) setJob(j); return j }).catch(() => null)
  useEffect(() => {
    alive.current = true
    let t: ReturnType<typeof setTimeout>
    const tick = async () => {
      const j = await load()
      if (alive.current && j && j.status === 'running') t = setTimeout(tick, 2500)
    }
    void tick()
    return () => { alive.current = false; clearTimeout(t) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  return [job, load] as const
}

function GapChart({ d }: { d: ScaleData }) {
  const W = 560, H = 230, L = 46, T = 14, B = 32
  const maxT = Math.max(10, ...d.rows.map(r => r.budget_s))
  const x = (t: number) => L + (t / maxT) * (W - L - 10)
  // closeness to the best possible plan: 100% = proven optimal, so a rising line means improving
  const y = (c: number) => T + (1 - Math.min(100, Math.max(0, c)) / 100) * (H - T - B)
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ maxWidth: 780, display: 'block' }} role="img" aria-label="Closeness to the best possible plan over time, by batch size">
      {[0, 25, 50, 75, 100].map(g => (
        <g key={g}><line x1={L} x2={W - 10} y1={y(g)} y2={y(g)} stroke="var(--line-soft)" />
          <text x={L - 5} y={y(g) + 3} fontSize={9} textAnchor="end" fill="var(--text-mute)">{g}%</text></g>
      ))}
      {[0, 0.25, 0.5, 0.75, 1].map(f => (
        <text key={f} x={x(f * maxT)} y={H - 16} fontSize={9} textAnchor="middle" fill="var(--text-mute)">{Math.round(f * maxT)} s</text>
      ))}
      <line x1={L} x2={W - 10} y1={y(99)} y2={y(99)} stroke="var(--fit)" strokeDasharray="4 3" opacity={0.7} />
      <text x={W - 12} y={y(99) + 11} fontSize={9} textAnchor="end" fill="var(--fit)">99%: within 1% of the best possible</text>
      {d.rows.map((r, i) => {
        const pts = r.curve.map(([t, g]) => [t, 100 - g] as [number, number])
        if (!pts.length) return null
        const last = pts[pts.length - 1]
        const path = 'M ' + pts.map(([t, g], k) => `${k ? 'L' : ''}${x(t).toFixed(1)},${y(g).toFixed(1)}`).join(' ') + ` L ${x(r.wall_s).toFixed(1)},${y(last[1]).toFixed(1)}`
        return (
          <g key={r.n}>
            <path d={path} fill="none" stroke={COLORS[i % 4]} strokeWidth={2.4} strokeLinejoin="round" className="sc-line" pathLength={1} />
            <circle cx={x(r.wall_s)} cy={y(last[1])} r={4.4} fill={COLORS[i % 4]} stroke="var(--panel)" strokeWidth={1.5} />
            <text x={x(r.wall_s) - 6} y={y(last[1]) - 8} fontSize={10} textAnchor="end" fill={COLORS[i % 4]} fontWeight={700}>
              {r.n} jobs{r.proven_optimal ? ' ✓ proven optimal' : ` · ${(100 - r.final_gap_pct).toFixed(0)}%`}
            </text>
          </g>
        )
      })}
      <text x={12} y={H / 2} fontSize={9} fill="var(--text-mute)" transform={`rotate(-90 12 ${H / 2})`} textAnchor="middle">closeness to the best possible plan</text>
    </svg>
  )
}

/* Time to a first plan (exact solver) and to plan the whole batch (fast path), as the batch grows. */
function TimeBars({ d }: { d: ScaleData }) {
  const items: { n: number; first: number | null; fast: number }[] = [
    ...d.rows.map(r => ({ n: r.n, first: r.first_plan_s, fast: r.heuristic.wall_s })),
    ...d.fast.map(f => ({ n: f.n, first: null, fast: f.wall_s })),
  ]
  const mx = Math.max(1, ...items.flatMap(i => [i.first ?? 0, i.fast]))
  const w = (v: number) => `${Math.max(1.5, (Math.log10(1 + v) / Math.log10(1 + mx)) * 100)}%`
  return (
    <div className="tb-scale">
      {items.map((it, i) => (
        <div key={it.n} className="tbs-row" style={{ animationDelay: `${i * 70}ms` }}>
          <b>{it.n.toLocaleString()} jobs</b>
          <div className="tbs-lines">
            <div className="tbs-l"><span>exact solver: first legal plan</span><div className="tbs-t"><i style={{ width: it.first === null ? '0%' : w(it.first), background: 'var(--accent)' }} /></div><em>{it.first === null ? 'not run' : secs(it.first)}</em></div>
            <div className="tbs-l"><span>fast path: whole batch</span><div className="tbs-t"><i style={{ width: w(it.fast), background: 'var(--fit)' }} /></div><em>{it.fast < 1 ? `${Math.round(it.fast * 1000)} ms` : secs(it.fast)}</em></div>
          </div>
        </div>
      ))}
      <div className="hint keep">Bar lengths are on a log scale.</div>
    </div>
  )
}

export default function Studio() {
  const [job, reload] = usePoll(api.studioScale)
  const [msg, setMsg] = useState('')
  const run = async () => {
    const r = await api.studioScaleRun()
    setMsg(r.started ? '' : `Busy with the ${r.busy_with} run; try again when it finishes.`)
    const again = () => api.studioScale().then(j => { if (j.status === 'running') setTimeout(again, 2500); void reload() })
    setTimeout(again, 1200)
  }
  const d = job?.data
  const running = job?.status === 'running'
  const big = d?.rows[d.rows.length - 1]
  const fastTop = d && d.fast.length ? d.fast[d.fast.length - 1] : null
  const checks = d ? d.rows.reduce((a, r) => a + (r.referee?.checks ?? 0), 0) : 0
  const viol = d ? d.rows.reduce((a, r) => a + (r.referee?.violations ?? 0), 0) : 0
  const proven = d?.rows.filter(r => r.proven_optimal).pop()
  return (
    <div style={{ display: 'grid', gap: 16 }}>
      <div className="ba-hero">
        <h1>Scaling studio</h1>
        <div className="sub">The same algorithm on 40 to 1,600 random jobs: how fast, how close to the best possible plan, and whether every rule still holds.</div>
        <div style={{ marginTop: 14 }}>
          <button className="action primary" disabled={running} onClick={run}>
            {running ? `Running… step ${job!.progress[0]} of ${job!.progress[1]}` : d ? 'Run the scale test again' : 'Run the scale test'}
          </button>
          {running && <span className="mc-run" style={{ display: 'inline-flex', marginLeft: 12 }}><span className="spinner-sm" />the exact solver is given up to 2 minutes at the largest size</span>}
        </div>
      </div>

      <div className="panel"><div className="panel-head"><h2>How the algorithm works</h2></div>
        <div className="panel-body"><ul className="how-list">
          <li><b>Find the gaps.</b> Every quiet stretch between trains on every track becomes a possible slot for a maintenance block.</li>
          <li><b>Choose slots for all jobs at once.</b> The exact solver (CP-SAT) decides which job goes in which slot, respecting every rule: no clashing departments, crew limits, blocks per day.</li>
          <li><b>Improve and prove.</b> It keeps improving the plan and tightens a proof of how close it is to the best possible. 100% means proven optimal.</li>
          <li><b>Check independently.</b> A separate checker re-tests every rule on the finished plan; those are the checks passed below.</li>
          <li><b>Fast path.</b> For live changes a quick insert-one-job method places jobs in milliseconds, longest first.</li>
        </ul></div></div>

      {msg && <div className="hint warn">{msg}</div>}
      {job?.status === 'error' && <div className="hint warn">Could not finish: {job.error}</div>}
      {!d && !running && (
        <div className="panel"><div className="panel-body"><div className="hint keep">Press <b>Run the scale test</b>. It solves random batches of 40, 100, 200 and 400 jobs with the exact solver (about 5 minutes in all), then runs the fast path on 800 and 1,600, and checks every plan with the independent rule checker.</div></div></div>
      )}

      {d && big && (
        <>
          <div className="tiles">
            <div className="tile"><div className="v"><Num v={big.n} /> jobs</div><div className="k">largest batch the exact solver planned</div>
              <div className="note">{big.placed} placed, first legal plan after {secs(big.first_plan_s)}</div></div>
            <div className="tile"><div className="v" style={{ color: 'var(--fit)' }}><Num v={checks - viol} /></div>
              <div className="k">rule checks passed on the solver's plans</div><div className="note">{viol === 0 ? `all ${checks.toLocaleString()} passed, at every batch size` : `${checks - viol} of ${checks.toLocaleString()} passed`}</div></div>
            {fastTop && <div className="tile"><div className="v"><Num v={fastTop.n} /> jobs</div><div className="k">planned by the fast path in {fastTop.wall_s < 10 ? fastTop.wall_s.toFixed(1) : Math.round(fastTop.wall_s)} s</div>
              <div className="note">{fastTop.jobs_per_s.toLocaleString()} jobs per second</div></div>}
            <div className="tile"><div className="v">{proven ? `${proven.n} jobs` : `${(100 - d.rows[0].final_gap_pct).toFixed(0)}%`}</div>
              <div className="k">{proven ? 'largest batch proven optimal' : `closeness to best possible, at ${d.rows[0].n} jobs`}</div>
              <div className="note">beyond this the solver still returns legal plans, with a weaker proof</div></div>
          </div>

          <div className="grid two">
            <div className="panel"><div className="panel-head"><h2>How close to the best possible plan, over time</h2></div>
              <div className="panel-body"><GapChart d={d} />
                <div className="hint">Each line is one batch size. It climbs as the solver improves its plan and tightens its proof; a line that reaches 100% is proven optimal.</div></div></div>
            <div className="panel"><div className="panel-head"><h2>Time to plan, as the batch grows</h2></div>
              <div className="panel-body"><TimeBars d={d} />
                <div className="hint">The exact solver had a legal plan after {secs(Math.max(...d.rows.map(r => r.first_plan_s ?? 0)))} at worst. The fast path plans 400 jobs in about {d.rows[d.rows.length - 1].heuristic.wall_s.toFixed(1)} s, but its time grows faster than the batch (1,600 jobs took {d.fast.length ? secs(d.fast[d.fast.length - 1].wall_s) : 'longer'}).</div></div></div>
          </div>

          <div className="panel">
            <div className="panel-head"><h2>Every result</h2></div>
            <div className="panel-body">
              <table className="sc-table">
                <thead><tr><th>Jobs</th><th>Placed</th><th>First plan</th><th>Within 5%</th><th>Within 1%</th><th>Solver reached</th><th>Solver checks passed</th><th>Fast path</th><th>Fast path checks passed</th></tr></thead>
                <tbody>
                  {d.rows.map((r, i) => (
                    <tr key={r.n}>
                      <td><i className="sc-dot" style={{ background: COLORS[i % 4] }} /><b>{r.n}</b></td>
                      <td>{r.placed}</td><td>{secs(r.first_plan_s)}</td><td>{secs(r.within_5_s)}</td><td>{secs(r.within_1_s)}</td>
                      <td>{r.proven_optimal ? <span className="good">proven optimal, {r.wall_s} s</span> : <span className="warn">{(100 - r.final_gap_pct).toFixed(0)}% of the best possible, after {Math.round(r.wall_s)} s</span>}</td>
                      <td>{r.referee ? <span className={r.referee.violations ? 'warn' : 'good'}>{r.referee.checks - r.referee.violations} of {r.referee.checks}</span> : '—'}</td>
                      <td>{r.heuristic.placed} placed, {r.heuristic.wall_s < 1 ? `${Math.round(r.heuristic.wall_s * 1000)} ms` : `${r.heuristic.wall_s.toFixed(1)} s`}</td>
                      <td>{r.heuristic.referee ? <span className={r.heuristic.referee.violations ? 'warn' : 'good'}>{r.heuristic.referee.checks - r.heuristic.referee.violations} of {r.heuristic.referee.checks}</span> : '—'}</td>
                    </tr>
                  ))}
                  {d.fast.map(f => (
                    <tr key={`f${f.n}`}>
                      <td><b>{f.n.toLocaleString()}</b></td><td>—</td><td>—</td><td>—</td><td>—</td><td className="muted">exact solver not run</td><td>—</td>
                      <td>{f.placed} placed, {f.wall_s.toFixed(1)} s</td>
                      <td><span className={f.referee.violations ? 'warn' : 'good'}>{f.referee.checks - f.referee.violations} of {f.referee.checks}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {d.partial && <div className="hint keep"><span className="spinner-sm" /> more sizes running…</div>}
              <div className="hint">What this shows: the exact solver passes every rule check at every size and always found a legal plan; it proves optimality on small batches and stays close to it on larger ones. The fast path is quicker per job and passes most checks, but it does not enforce the gang and daily-block limits, so it misses the rest. That is why the system uses the exact solver for the weekly plan and the fast path for live single-job placement.</div>
              {d.how && <div className="hint">{d.how}</div>}
              {d.caveat && <div className="hint">{d.caveat}</div>}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
