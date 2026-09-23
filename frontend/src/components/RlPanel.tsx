import { useEffect, useState } from 'react'
import { api, type RlData } from '../api'
import DemandDemo from './DemandDemo'

/* The innovation claim, with its evidence. Showing greedy and random alongside the learned
   policies is deliberate: a gap figure means nothing without the floor it is measured from. */

export default function RlPanel() {
  const [d, setD] = useState<RlData | null>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => { api.rl().then(setD).catch(e => setErr(String(e))) }, [])

  if (err) return (
    <div className="panel"><div className="panel-body muted">
      No comparison yet — run <span className="mono">scripts/06_evaluate_rl.py</span>.
    </div></div>
  )
  if (!d) return <div className="loading"><div className="spinner" />Loading policy comparison…</div>

  const best = d.table.reduce((a, b) =>
    b.mean_gap_vs_cpsat_pct < a.mean_gap_vs_cpsat_pct ? b : a)
  const worst = Math.max(...d.table.map(r => r.mean_gap_vs_cpsat_pct))
  const speedup = d.cpsat_mean_ms / Math.max(1, best.mean_full_replan_ms)
  const totalViolations = d.table.reduce((n, r) => n + r.constraint_violations, 0)

  return (
    <div style={{ display: 'grid', gap: 16 }}>
      <DemandDemo />

      <div className="panel">
        <div className="panel-head">
          <h2>Learned dispatcher vs the solver</h2>
          <span className="sub">{d.instances} held-out instances, never seen in training</span>
        </div>

        <div className="lede">
          CP-SAT solves the weekly plan optimally but takes seconds. Its solutions were replayed
          as <b>decision trajectories</b> and used to train an offline policy, so the solver
          teaches the dispatcher how to dispatch. The policy then re-plans in{' '}
          <b>milliseconds</b> — which is what makes reacting to a defect mid-week possible at all.
        </div>

        <div className="panel-body" style={{ paddingTop: 0 }}>
          <div className="tiles">
            <div className="tile">
              <div className="v" style={{ color: 'var(--fit)' }}>{best.mean_gap_vs_cpsat_pct}%</div>
              <div className="k">Best policy's gap from optimal</div>
              <div className="note">{best.policy}, on the same placement objective as CP-SAT.</div>
            </div>
            <div className="tile">
              <div className="v" style={{ color: 'var(--accent)' }}>{speedup.toFixed(0)}×</div>
              <div className="k">Faster to re-plan</div>
              <div className="note">
                {best.mean_full_replan_ms.toFixed(0)} ms against the solver's{' '}
                {(d.cpsat_mean_ms / 1000).toFixed(1)} s.
              </div>
            </div>
            <div className="tile">
              <div className="v">{best.mean_decision_ms.toFixed(2)}<small> ms</small></div>
              <div className="k">Per dispatch decision</div>
            </div>
            <div className="tile">
              <div className="v" style={{ color: totalViolations === 0 ? 'var(--fit)' : 'var(--stopstart)' }}>
                {totalViolations}
              </div>
              <div className="k">Constraint violations</div>
              <div className="note">
                Zero by construction: every action passes through a legality mask, so an
                illegal schedule is unrepresentable rather than merely discouraged.
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="grid two">
        <div className="panel">
          <div className="panel-head"><h2>Every policy compared</h2></div>
          <div className="panel-body flush">
            <table>
              <thead>
                <tr>
                  <th>Policy</th>
                  <th className="num">Gap</th>
                  <th className="num">Placed</th>
                  <th className="num">Micro-gaps</th>
                  <th className="num">Decision</th>
                </tr>
              </thead>
              <tbody>
                {d.table.map(r => (
                  <tr key={r.policy} style={r.policy === best.policy
                    ? { background: 'var(--accent-soft)' } : undefined}>
                    <td style={{ fontWeight: r.policy === best.policy ? 650 : 400 }}>
                      {r.policy}
                      {r.policy === best.policy &&
                        <span className="badge micro" style={{ marginLeft: 7 }}>selected</span>}
                    </td>
                    <td className="num">{r.mean_gap_vs_cpsat_pct}%</td>
                    <td className="num">{r.mean_scheduled_pct}%</td>
                    <td className="num">{r.mean_micro_gap}</td>
                    <td className="num">{r.mean_decision_ms.toFixed(2)} ms</td>
                  </tr>
                ))}
                <tr>
                  <td className="muted">CP-SAT (reference)</td>
                  <td className="num muted">0%</td>
                  <td className="num muted">—</td>
                  <td className="num muted">—</td>
                  <td className="num muted">{(d.cpsat_mean_ms / 1000).toFixed(1)} s</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div className="panel">
          <div className="panel-head"><h2>Gap from optimal</h2><span className="sub">lower is better</span></div>
          <div className="panel-body">
            {d.table.map(r => (
              <div key={r.policy} style={{ marginBottom: 14 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12.5 }}>
                  <span>{r.policy}</span>
                  <span className="mono">{r.mean_gap_vs_cpsat_pct}%</span>
                </div>
                <div className="bar">
                  <i style={{
                    width: `${(r.mean_gap_vs_cpsat_pct / worst) * 100}%`,
                    background: r.policy === best.policy
                      ? 'var(--fit)'
                      : 'var(--text-mute)',
                  }} />
                </div>
              </div>
            ))}
            <div className="reason" style={{ margin: '16px 0 0', borderLeftColor: 'var(--fit)' }}>
              The learned policies place <b>{best.mean_micro_gap} jobs into gaps between
              trains</b> against greedy's{' '}
              {d.table.find(r => r.policy === 'greedy')?.mean_micro_gap ?? '—'}. That behaviour
              was not hand-written — it transferred from the solver's own solutions, which is
              the clearest evidence the expert-to-policy bridge carried something real.
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
