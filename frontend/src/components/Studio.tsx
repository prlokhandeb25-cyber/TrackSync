import { useEffect, useMemo, useRef, useState } from 'react'
import {
  api, DAYS, hhmm, type ApprovalsData, type LearningData, type MachinesData, type ParetoData, type ParetoPoint, type ScaleData,
  type StudioJob,
} from '../api'
import { Num } from './Viz'

/* The planning studio: what a coordinator needs to trust the system. Timing at scale, the trade-offs behind one plan,
   machines that can only be in one place, propose / approve / reject with a trail, and learning from what really happened.
   Everything long runs once on copies; only Apply and Revert (on an approved proposal) touch the plan in force. */

const COLORS = ['#0284c7', '#65a30d', '#d97706', '#c026d3']
const SCALE_LABEL = (n: number) => `${n} jobs`
const pct = (v: number) => `${(v * 100).toFixed(1)}%`
const secs = (v: number | null) => (v === null ? 'not reached' : v < 10 ? `${v.toFixed(1)} s` : `${Math.round(v)} s`)

function usePoll<T>(fetcher: () => Promise<StudioJob<T>>, deps: unknown[] = []) {
  const [job, setJob] = useState<StudioJob<T> | null>(null)
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
  }, deps)
  return [job, load] as const
}

// ------------------------------------------------------------------------------------------ scale

function ScaleChart({ d }: { d: ScaleData }) {
  const W = 520, H = 210, L = 44, T = 14, B = 30
  const maxT = Math.max(10, ...d.rows.map(r => r.budget_s))
  const x = (t: number) => L + (t / maxT) * (W - L - 10)
  const y = (g: number) => T + (1 - Math.min(100, Math.max(0, g)) / 100) * (H - T - B)
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ maxWidth: 760, display: "block" }} role="img" aria-label="Optimality gap over time by workload size">
      {[0, 25, 50, 75, 100].map(g => (
        <g key={g}><line x1={L} x2={W - 10} y1={y(g)} y2={y(g)} stroke="var(--line-soft)" />
          <text x={L - 5} y={y(g) + 3} fontSize={9} textAnchor="end" fill="var(--text-mute)">{g}%</text></g>
      ))}
      {[0, 0.25, 0.5, 0.75, 1].map(f => (
        <text key={f} x={x(f * maxT)} y={H - 14} fontSize={9} textAnchor="middle" fill="var(--text-mute)">{Math.round(f * maxT)} s</text>
      ))}
      <line x1={L} x2={W - 10} y1={y(1)} y2={y(1)} stroke="var(--fit)" strokeDasharray="4 3" opacity={0.7} />
      <text x={W - 12} y={y(1) - 4} fontSize={9} textAnchor="end" fill="var(--fit)">within 1% of optimal</text>
      {d.rows.map((r, i) => {
        const pts = r.curve.length ? r.curve : []
        if (!pts.length) return null
        const last = pts[pts.length - 1]
        const path = 'M ' + pts.map(([t, g], k) => `${k ? 'L' : ''}${x(t).toFixed(1)},${y(g).toFixed(1)}`).join(' ') + ` L ${x(r.wall_s).toFixed(1)},${y(last[1]).toFixed(1)}`
        return (
          <g key={r.n}>
            <path d={path} fill="none" stroke={COLORS[i % 4]} strokeWidth={2.2} strokeLinejoin="round" className="sc-line" pathLength={1} />
            <circle cx={x(r.wall_s)} cy={y(last[1])} r={4.2} fill={COLORS[i % 4]} stroke="var(--panel)" strokeWidth={1.5} />
            <text x={x(r.wall_s) - 6} y={y(last[1]) - 7} fontSize={9.5} textAnchor="end" fill={COLORS[i % 4]} fontWeight={700}>
              {SCALE_LABEL(r.n)}{r.proven_optimal ? ' ✓' : ` · ${r.final_gap_pct}%`}
            </text>
          </g>
        )
      })}
      <text x={12} y={H / 2} fontSize={9} fill="var(--text-mute)" transform={`rotate(-90 12 ${H / 2})`} textAnchor="middle">distance from the best possible plan</text>
    </svg>
  )
}

function ScalePanel() {
  const [job, reload] = usePoll<ScaleData>(api.studioScale)
  const [msg, setMsg] = useState('')
  const run = async () => {
    const r = await api.studioScaleRun()
    setMsg(r.started ? '' : `Busy with the ${r.busy_with} run; try again when it finishes.`)
    void reload()
    const again = () => api.studioScale().then(j => { if (j.status === 'running') setTimeout(again, 2500); void reload() })
    setTimeout(again, 1500)
  }
  const d = job?.data
  const running = job?.status === 'running'
  return (
    <div className="panel">
      <div className="panel-head"><h2>Does it scale? Random jobs, timed</h2>
        <button className="action primary" style={{ marginLeft: 'auto' }} disabled={running} onClick={run}>{running ? `Running… ${job!.progress[0]}/${job!.progress[1]}` : d ? 'Run again' : 'Run the scale test'}</button>
      </div>
      <div className="panel-body">
        {msg && <div className="hint warn">{msg}</div>}
        {job?.status === 'error' && <div className="hint warn">Could not finish: {job.error}</div>}
        {!d && !running && <div className="hint keep">Solves 40, 100, 200 and 400 random jobs on the live network with the exact solver and records how close to the best possible plan it gets, and when. Takes about 3 minutes.</div>}
        {running && !d && <div className="hint keep"><span className="spinner-sm" /> solving the first size…</div>}
        {d && (
          <>
            <ScaleChart d={d} />
            <table className="sc-table">
              <thead><tr><th>Jobs</th><th>Placed</th><th>First plan</th><th>Within 5%</th><th>Within 1%</th><th>Stopped at</th><th>Fast heuristic</th></tr></thead>
              <tbody>
                {d.rows.map((r, i) => (
                  <tr key={r.n}>
                    <td><i className="sc-dot" style={{ background: COLORS[i % 4] }} /><b>{r.n}</b></td>
                    <td>{r.placed}</td><td>{secs(r.first_plan_s)}</td><td>{secs(r.within_5_s)}</td><td>{secs(r.within_1_s)}</td>
                    <td>{r.proven_optimal ? <span className="good">proven optimal, {r.wall_s} s</span> : <span className="warn">{r.final_gap_pct}% from best possible after {Math.round(r.wall_s)} s</span>}</td>
                    <td>{r.heuristic.placed} placed in {r.heuristic.wall_s < 1 ? `${Math.round(r.heuristic.wall_s * 1000)} ms` : `${r.heuristic.wall_s.toFixed(1)} s`}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {d.partial && <div className="hint keep"><span className="spinner-sm" /> more sizes running…</div>}
            {d.how && <div className="hint">{d.how}</div>}
            {d.caveat && <div className="hint">{d.caveat}</div>}
          </>
        )}
      </div>
    </div>
  )
}

// ------------------------------------------------------------------------------------------ pareto

function ParetoPanel({ by, onProposed }: { by: string; onProposed: () => void }) {
  const [job, reload] = usePoll<ParetoData>(api.studioPareto)
  const [pick, setPick] = useState(0)
  const [msg, setMsg] = useState('')
  const d = job?.data
  const pts = useMemo(() => (d ? [...d.points].sort((a, b) => a.passengers - b.passengers) : []), [d])
  useEffect(() => { if (pts.length) setPick(Math.max(0, pts.findIndex(p => p.id === 'balanced'))) }, [pts.length])   // eslint-disable-line
  const run = async () => {
    const r = await api.studioParetoRun()
    setMsg(r.started ? '' : `Busy with the ${r.busy_with} run; try again when it finishes.`)
    const again = () => api.studioPareto().then(j => { if (j.status === 'running') setTimeout(again, 2500); void reload() })
    setTimeout(again, 1500)
  }
  const cur: ParetoPoint | undefined = pts[Math.min(pick, pts.length - 1)]
  const ref = d?.reference
  const running = job?.status === 'running'
  const span = (k: 'passengers' | 'robust' | 'placed') => { const v = pts.map(p => p[k]); return [Math.min(...v), Math.max(...v)] }
  return (
    <div className="panel">
      <div className="panel-head"><h2>Trade-offs: choose between plans</h2>
        <button className="action primary" style={{ marginLeft: 'auto' }} disabled={running} onClick={run}>{running ? `Solving… ${job!.progress[0]}/${job!.progress[1]}` : d ? 'Solve again' : 'Solve the trade-offs'}</button>
      </div>
      <div className="panel-body">
        {msg && <div className="hint warn">{msg}</div>}
        {job?.status === 'error' && <div className="hint warn">Could not finish: {job.error}</div>}
        {!d && !running && <div className="hint keep">One plan hides a choice. This solves five plans on the same rules and jobs, each favouring something different: jobs done, passengers affected, how safely blocks clear. Takes about a minute.</div>}
        {running && !d && <div className="hint keep"><span className="spinner-sm" /> solving five plans with the exact solver…</div>}
        {d && cur && ref && (
          <>
            <div className="par-slider">
              <span>Fewest passengers</span>
              <input type="range" min={0} max={pts.length - 1} step={1} value={pick} onChange={e => setPick(Number(e.target.value))} aria-label="Choose a trade-off plan" />
              <span>Most passengers, most flexible</span>
            </div>
            <div className="par-dots">
              {pts.map((p, i) => (
                <button key={p.id} className={`par-dot ${i === pick ? 'on' : ''} ${p.dominated ? 'dom' : ''}`} onClick={() => setPick(i)} title={p.why}>
                  {p.title}{p.dominated ? ' ·beaten' : ''}
                </button>
              ))}
            </div>
            <div className="tiles mini">
              <div className="tile"><div className="v"><Num v={cur.placed} /><small> / {ref.placed}</small></div><div className="k">jobs placed</div>
                <div className="note">{cur.placed - ref.placed === 0 ? 'same as the plan in force' : `${cur.placed - ref.placed > 0 ? '+' : ''}${cur.placed - ref.placed} against the plan in force`}</div></div>
              <div className="tile"><div className="v" style={{ color: cur.passengers <= ref.passengers ? 'var(--fit)' : 'var(--stopstart)' }}>
                {cur.passengers === ref.passengers ? '' : cur.passengers < ref.passengers ? '−' : '+'}<Num v={Math.abs(Math.round((1 - cur.passengers / Math.max(1, ref.passengers)) * 100))} suffix="%" /></div>
                <div className="k">passengers within reach</div><div className="note">{cur.passengers.toLocaleString()} passenger-hours, plan in force {ref.passengers.toLocaleString()}</div></div>
              <div className="tile"><div className="v">{pct(cur.robust)}</div><div className="k">blocks clear before the next train</div>
                <div className="note">plan in force {pct(ref.robust)}</div></div>
              <div className="tile"><div className="v">{cur.status === 'OPTIMAL' ? <span style={{ color: 'var(--fit)' }}>optimal</span> : `${cur.gap_pct}% gap`}</div><div className="k">solver result</div>
                <div className="note">{cur.status === 'OPTIMAL' ? 'proven best for this weighting' : 'best found in the time allowed'}</div></div>
            </div>
            <div className="par-bars">
              {([['placed', 'Jobs', false], ['passengers', 'Passengers', true], ['robust', 'Robust', false]] as const).map(([k, label, lowerBetter]) => {
                const [lo, hi] = span(k)
                const f = hi === lo ? 1 : ((cur[k] as number) - lo) / (hi - lo)
                return (
                  <div key={k} className="par-bar"><span>{label}</span>
                    <div className="par-t"><i style={{ width: `${Math.max(4, (lowerBetter ? 1 - f : f) * 100)}%` }} /></div>
                    <em>{lowerBetter ? 'less is better' : 'more is better'}</em></div>
                )
              })}
            </div>
            <div className="par-moves">
              <b>Against the plan in force: {cur.diff.moved.length} job{cur.diff.moved.length === 1 ? '' : 's'} move{cur.diff.moved.length === 1 ? 's' : ''}, {cur.diff.unchanged} stay put
                {cur.diff.dropped.length ? `, ${cur.diff.dropped.length} dropped` : ''}{cur.diff.added.length ? `, ${cur.diff.added.length} added` : ''}</b>
              {[...cur.diff.moved.slice(0, 6).map(m => ({ ...m, kind: 'moved' })), ...cur.diff.dropped.slice(0, 3).map(m => ({ ...m, kind: 'dropped' }))].map(m => (
                <div key={m.task_id + m.kind} className="par-move"><span className="mono">{m.task_id}</span> {m.label.toLowerCase()}
                  {m.from && <span className="muted"> {DAYS[Math.floor(m.from[0] / 86400) % 7]} {hhmm(m.from[0])}</span>}
                  {m.to ? <> → <b>{DAYS[Math.floor(m.to[0] / 86400) % 7]} {hhmm(m.to[0])}</b></> : <b className="bad"> could not be kept</b>}</div>
              ))}
            </div>
            <div className="sd-actions">
              <button className="action primary" onClick={async () => { try { await api.studioPropose('pareto', cur.id, by); setMsg('Proposed. Approve or reject it under Approvals below.'); onProposed() } catch (e) { setMsg(String(e)) } }}>Propose this plan</button>
            </div>
            <div className="hint">{d.how} {d.caveat}</div>
          </>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------------------- machines

function MachinesPanel({ by, onProposed }: { by: string; onProposed: () => void }) {
  const [pools, setPools] = useState({ t: 1, b: 1, w: 2 })
  const [d, setD] = useState<MachinesData | null>(null)
  const [msg, setMsg] = useState('')
  const load = () => api.studioResources(pools.t, pools.b, pools.w).then(setD).catch(() => undefined)
  useEffect(() => { const id = setTimeout(load, 250); return () => clearTimeout(id) }, [pools.t, pools.b, pools.w])   // eslint-disable-line
  useEffect(() => {
    if (d?.solve.status !== 'running') return
    const id = setInterval(load, 2500)
    return () => clearInterval(id)
  }, [d?.solve.status])                                                                                               // eslint-disable-line
  const run = async () => {
    const r = await api.studioResourcesRun(pools.t, pools.b, pools.w)
    setMsg(r.started ? '' : `Busy with the ${r.busy_with} run; try again when it finishes.`)
    setTimeout(load, 1200)
  }
  const s = d?.solve
  const r = s?.data
  const num = (label: string, k: 't' | 'b' | 'w') => (
    <label className="mach-in">{label}<input type="number" min={1} max={6} value={pools[k]} onChange={e => setPools(p => ({ ...p, [k]: Math.max(1, Math.min(6, Number(e.target.value) || 1)) }))} /></label>
  )
  return (
    <div className="panel">
      <div className="panel-head"><h2>Machines can only be in one place</h2>
        <button className="action primary" style={{ marginLeft: 'auto' }} disabled={s?.status === 'running'} onClick={run}>{s?.status === 'running' ? `Solving… ${s.progress[0]}/${s.progress[1]}` : 'Solve with machine limits'}</button>
      </div>
      <div className="panel-body">
        <div className="mach-row">{num('Tamping machines', 't')}{num('Ballast cleaners', 'b')}{num('Tower wagons', 'w')}</div>
        {msg && <div className="hint warn">{msg}</div>}
        {d && (
          <div className="tiles mini">
            <div className="tile"><div className="v">{d.machine_jobs}</div><div className="k">jobs need a machine</div><div className="note">of the week's jobs</div></div>
            <div className="tile"><div className="v" style={{ color: d.live_conflicts.length ? 'var(--stopstart)' : 'var(--fit)' }}>{d.live_conflicts.length}</div>
              <div className="k">the plan in force cannot serve</div><div className="note">machine double-booked or no time to travel</div></div>
            {r && <div className="tile"><div className="v" style={{ color: r.with.conflicts.length ? 'var(--stopstart)' : 'var(--fit)' }}>{r.with.conflicts.length}</div>
              <div className="k">after solving with the limits</div><div className="note">{r.with.placed} placed against {r.without.placed}; {r.moved_vs_live} jobs move</div></div>}
          </div>
        )}
        {d?.live_conflicts.map(c => (
          <div key={c.task_id} className="par-move"><b>{c.machine}</b> cannot reach <span className="mono">{c.zone}</span> for {c.label.toLowerCase()} at {DAYS[Math.floor(c.start_s / 86400) % 7]} {hhmm(c.start_s)}: {c.kind}, short by {c.short_by_min} min</div>
        ))}
        {s?.status === 'error' && <div className="hint warn">Could not finish: {s.error}</div>}
        {r && (
          <div className="sd-actions">
            <button className="action" onClick={async () => { try { await api.studioPropose('resources', '', by); setMsg('Proposed. Approve or reject it under Approvals below.'); onProposed() } catch (e) { setMsg(String(e)) } }}>Propose the machine-aware plan</button>
          </div>
        )}
        <div className="hint">Each machine is in one place at a time and needs travel time between sections; the pools, speed and shunt time are assumptions (A-057). Solving runs the exact solver twice on copies.</div>
        {r && <div className="hint">{r.how} {r.caveat}</div>}
      </div>
    </div>
  )
}

// --------------------------------------------------------------------------------------- approvals

function ApprovalsPanel({ by, setBy, tick, onChanged }: { by: string; setBy: (s: string) => void; tick: number; onChanged: () => void }) {
  const [d, setD] = useState<ApprovalsData | null>(null)
  const [reasons, setReasons] = useState<Record<string, string>>({})
  const [err, setErr] = useState('')
  const load = () => api.approvals().then(setD).catch(() => undefined)
  useEffect(() => { void load() }, [tick])                                     // eslint-disable-line
  const act = async (fn: () => Promise<unknown>, changesPlan = false) => {
    setErr('')
    try { await fn(); await load(); if (changesPlan) onChanged() } catch (e) { setErr(String(e).replace(/^Error: /, '')) }
  }
  const STATUS: Record<string, string> = { proposed: 'waiting for a decision', approved: 'approved, not yet applied', rejected: 'rejected', applied: 'in force now', reverted: 'reverted' }
  return (
    <div className="panel">
      <div className="panel-head"><h2>Approvals and audit trail</h2>
        <label className="mach-in" style={{ marginLeft: 'auto' }}>You are <input type="text" value={by} onChange={e => setBy(e.target.value)} maxLength={30} style={{ width: 120 }} /></label>
      </div>
      <div className="panel-body">
        {err && <div className="hint warn">{err}</div>}
        {d && <div className="hint keep">Plan in force: {d.plan_in_force.placed} jobs placed ({d.plan_in_force.status.toLowerCase()}).
          {d.can_revert && <> <button className="link" onClick={() => act(() => api.revertPlan(by), true)}>Revert {d.can_revert}</button></>}</div>}
        {d && d.proposals.length === 0 && <div className="hint keep">No proposals yet. Propose a plan from the trade-offs or the machine panel above; nothing changes until someone approves and applies it.</div>}
        {d?.proposals.map(p => (
          <div key={p.id} className={`prop st-${p.status}`}>
            <div className="prop-head"><b>{p.id}</b> {p.title}<span className={`prop-st st-${p.status}`}>{STATUS[p.status]}</span></div>
            <div className="prop-sum">{p.summary.placed} jobs · {p.summary.passengers.toLocaleString()} passenger-hours · {pct(p.summary.robust)} clear in time · {p.diff.n_moved} job(s) move, {p.diff.unchanged} stay · proposed by {p.created_by}</div>
            {p.status === 'proposed' && (
              <div className="prop-act">
                <input type="text" placeholder="Reason (required)" value={reasons[p.id] ?? ''} onChange={e => setReasons(r => ({ ...r, [p.id]: e.target.value }))} />
                <button className="action primary" onClick={() => act(() => api.decide(p.id, true, reasons[p.id] ?? '', by))}>Approve</button>
                <button className="action" onClick={() => act(() => api.decide(p.id, false, reasons[p.id] ?? '', by))}>Reject</button>
              </div>
            )}
            {p.status !== 'proposed' && p.reason && <div className="prop-sum">{p.decided_by}: “{p.reason}”</div>}
            {p.status === 'approved' && <div className="prop-act"><button className="action primary" onClick={() => act(() => api.applyProposal(p.id, by), true)}>Apply to the plan in force</button></div>}
          </div>
        ))}
        {d && d.audit.length > 0 && (
          <div className="audit">
            <div className="needs-title">Audit trail</div>
            {d.audit.slice(0, 12).map(a => (
              <div key={a.seq} className="audit-row"><span className="mono muted">{a.at.replace('T', ' ')}</span> <b>{a.event}</b> {a.proposal} <span className="muted">by {a.by}</span>
                {typeof a.detail === 'object' && 'reason' in a.detail ? <span className="muted"> — “{String(a.detail.reason)}”</span> : null}</div>
            ))}
          </div>
        )}
        <div className="hint">Every step is written, with who and when, to an append-only file. Applying is refused while sudden tasks are booked against the current plan; a revert restores the previous plan exactly.</div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------------------- learning

function LearningPanel() {
  const [source, setSource] = useState<'real' | 'simulated'>('real')
  const [d, setD] = useState<LearningData | null>(null)
  const [tasks, setTasks] = useState<{ id: string; label: string; department: string; planned_min: number }[]>([])
  const [tid, setTid] = useState('')
  const [actual, setActual] = useState(60)
  const [rain, setRain] = useState(false)
  const [msg, setMsg] = useState('')
  const load = (s = source) => api.learning(s).then(setD).catch(() => undefined)
  useEffect(() => { void load() }, [source])                                   // eslint-disable-line
  useEffect(() => { api.learningTasks().then(r => { setTasks(r.tasks); if (r.tasks[0]) { setTid(r.tasks[0].id); setActual(r.tasks[0].planned_min) } }).catch(() => undefined) }, [])
  const t = tasks.find(x => x.id === tid)
  return (
    <div className="panel">
      <div className="panel-head"><h2>Learning from what really happened</h2>
        <div className="segc" style={{ marginLeft: 'auto' }}>
          <button className={source === 'real' ? 'on' : ''} onClick={() => setSource('real')}>Logged jobs{d ? ` (${d.n_real})` : ''}</button>
          <button className={source === 'simulated' ? 'on' : ''} onClick={() => setSource('simulated')}>Simulated{d ? ` (${d.n_simulated})` : ''}</button>
        </div>
      </div>
      <div className="panel-body">
        {source === 'real' && (
          <div className="learn-form">
            <select value={tid} onChange={e => { setTid(e.target.value); const x = tasks.find(y => y.id === e.target.value); if (x) setActual(x.planned_min) }} aria-label="Finished job">
              {tasks.map(x => <option key={x.id} value={x.id}>{x.id} · {x.label} · planned {x.planned_min} min</option>)}
            </select>
            <label>took <input type="number" min={5} max={1440} value={actual} onChange={e => setActual(Number(e.target.value) || 5)} /> min</label>
            <label><input type="checkbox" checked={rain} onChange={e => setRain(e.target.checked)} /> rain</label>
            <button className="action primary" onClick={async () => { try { await api.learningLog(tid, actual, rain); setMsg(`Logged. ${t ? `${t.label}: planned ${t.planned_min}, took ${actual}.` : ''}`); void load() } catch (e) { setMsg(String(e)) } }}>Log completion</button>
          </div>
        )}
        {source === 'simulated' && (
          <div className="learn-form">
            <button className="action primary" onClick={async () => { await api.learningSimulate(60); void load() }}>Add 60 simulated completions</button>
            <button className="action" onClick={async () => { await api.learningResetSim(); void load() }}>Clear</button>
            <span className="hint keep">Drawn from a hidden crew table, only to watch the estimate converge. Never mixed with real logs.</span>
          </div>
        )}
        {msg && <div className="hint keep">{msg}</div>}
        {d && (
          <table className="sc-table">
            <thead><tr><th>Crew</th><th>Weather</th><th>Jobs logged</th><th>Takes vs plan</th><th>Buffer for 2 h</th>{source === 'simulated' && <th>Hidden truth</th>}</tr></thead>
            <tbody>
              {d.estimate.map(r => (
                <tr key={r.department + r.rain}>
                  <td>{r.department.replace('S_AND_T', 'S&T')}</td><td>{r.rain ? 'rain' : 'dry'}</td><td>{r.n}</td>
                  <td>×{r.mean.toFixed(2)}{r.n === 0 && <span className="muted"> (prior)</span>}</td>
                  <td><b>{r.buffer_min_120} min</b></td>{source === 'simulated' && <td>×{r.hidden_true_mean?.toFixed(2)}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {source === 'simulated' && d && d.convergence.length > 1 && (
          <div className="hint keep">Average error against the hidden truth: {d.convergence[0].mean_abs_error.toFixed(3)} after {d.convergence[0].n} jobs → <b>{d.convergence[d.convergence.length - 1].mean_abs_error.toFixed(3)}</b> after {d.convergence[d.convergence.length - 1].n}.</div>
        )}
        <div className="hint">{d?.note} Each finished job moves its group's estimate toward what it really took; the buffer is the 80th-percentile overrun (capped at half the job), so with no data it is zero and with data it is the crews' own. Real logs are stored in artifacts/execution_log.jsonl.</div>
      </div>
    </div>
  )
}

// -------------------------------------------------------------------------------------------- page

export default function Studio({ onPlanChanged }: { onPlanChanged: () => void }) {
  const [by, setByState] = useState(() => { try { return localStorage.getItem('rb-user') || 'coordinator' } catch { return 'coordinator' } })
  const setBy = (s: string) => { setByState(s); try { localStorage.setItem('rb-user', s) } catch { /* storage can be blocked */ } }
  const [tick, setTick] = useState(0)
  return (
    <div style={{ display: 'grid', gap: 16 }}>
      <div className="ba-hero">
        <h1>Planning studio</h1>
        <div className="sub">Trust it, steer it, overrule it: timing at scale, trade-offs, machine limits, approvals, learning.</div>
      </div>
      <div className="grid two">
        <div style={{ display: 'grid', gap: 16, alignContent: 'start' }}>
          <ParetoPanel by={by} onProposed={() => setTick(t => t + 1)} />
          <MachinesPanel by={by} onProposed={() => setTick(t => t + 1)} />
        </div>
        <div style={{ display: 'grid', gap: 16, alignContent: 'start' }}>
          <ApprovalsPanel by={by} setBy={setBy} tick={tick} onChanged={() => { setTick(t => t + 1); onPlanChanged() }} />
          <LearningPanel />
        </div>
      </div>
      <ScalePanel />
    </div>
  )
}
