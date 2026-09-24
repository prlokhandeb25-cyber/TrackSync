import { useEffect, useState } from 'react'
import { api, DAYS, hhmm, type PlanVerify, type Robustness } from '../api'

/* Two questions a sceptic asks of any optimiser: is the plan actually legal, and will it hold on a
   bad day? The first is answered by a referee that re-checks every rule from the timetable (not from
   the solver); the second by simulating each block against late trains and overrunning work. */

export default function PlanCheck() {
  const [v, setV] = useState<PlanVerify | null>(null)
  const [r, setR] = useState<Robustness | null>(null)

  useEffect(() => {
    api.planVerify().then(setV).catch(() => undefined)
    let alive = true
    const poll = () => api.planRobustness().then(x => {
      if (!alive) return
      setR(x)
      if (x.ablation_status === 'running') setTimeout(poll, 4000)
    }).catch(() => undefined)
    void poll()
    return () => { alive = false }
  }, [])

  const pct = (x: number) => `${Math.round(x * 100)}%`
  return (
    <div className="panel">
      <div className="panel-head"><h2>Is the plan right, and will it hold?</h2><span className="sub">independent checks</span></div>
      <div className="panel-body">
        <div className="tiles mini">
          <div className="tile">
            <div className="v" style={{ color: v ? (v.ok ? 'var(--fit)' : 'var(--stopstart)') : undefined }}>
              {v ? (v.ok ? '0 violations' : `${v.n_violations} violations`) : '…'}
            </div>
            <div className="k">rules re-checked by a referee</div>
            <div className="note">{v ? `${v.total_checks} checks from the timetable itself` : 'checking'}</div>
          </div>
          <div className="tile">
            <div className="v" style={{ color: 'var(--fit)' }}>{r ? pct(r.plan.mean) : '…'}</div>
            <div className="k">blocks clear before the next train</div>
            <div className="note">{r ? `average over ${r.samples} simulated days each` : 'simulating'}</div>
          </div>
          <div className="tile">
            <div className="v" style={{ color: r && r.plan.risky ? 'var(--sick)' : 'var(--fit)' }}>{r ? `${r.plan.risky}/${r.plan.blocks}` : '…'}</div>
            <div className="k">fragile blocks (under 90%)</div>
            <div className="note">{r ? `${r.plan.expected_overruns} expected overruns a week` : ''}</div>
          </div>
          <div className="tile">
            <div className="v" style={{ color: 'var(--accent)' }}>
              {r?.ablation ? `${pct(r.ablation.raw.mean)} → ${pct(r.plan.mean)}` : r?.ablation_status === 'error' ? 'n/a' : '…'}
            </div>
            <div className="k">effect of planning for late trains</div>
            <div className="note">{r?.ablation ? `solver alone chose ${pct(r.ablation.raw.mean)} (${r.ablation.raw.risky} fragile blocks); ${r.centred_moves} start times then centred` : 'solving the week without it'}</div>
          </div>
        </div>

        {r && r.weakest.some(b => b.p_clear < 0.95) && (
          <div style={{ marginTop: 14 }}>
            <div className="k muted" style={{ fontSize: 11, marginBottom: 6 }}>THE FRAGILE ONES</div>
            <table>
              <tbody>
                {r.weakest.filter(b => b.p_clear < 0.95).map(b => (
                  <tr key={b.task_id}>
                    <td className="mono">{b.task_id}</td>
                    <td className="mono">{b.section_id} {b.track.replace('_', ' ')}</td>
                    <td className="mono">{DAYS[Math.floor(b.start_s / 86400) % 7]} {hhmm(b.start_s)}</td>
                    <td className="num">{b.slack_after_min > 900 ? '—' : `${b.slack_after_min.toFixed(0)} min spare`}</td>
                    <td className="num" style={{ fontWeight: 650, color: b.p_clear < 0.9 ? 'var(--sick)' : 'var(--text)' }}>{pct(b.p_clear)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
