import { useState } from 'react'
import { api, type DemandReplanResult } from '../api'

/* SPEC §13.2's "money demo": inject a defect nobody planned for, and watch CP-SAT's exact
   full re-solve and the learned dispatcher's reactive re-plan run on the SAME problem, timed
   for real. This is not a canned number - every click calls the live API and shows what
   actually happened, including which dispatcher answered if the trained model is unavailable
   on this machine and it fell back to the greedy heuristic. */

// kept across tab changes: the page is left as soon as the defect is injected, and the timing is here when you come back
let lastResult: DemandReplanResult | null = null

export default function DemandDemo() {
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<DemandReplanResult | null>(lastResult)
  const [err, setErr] = useState<string | null>(null)

  const run = async () => {
    setBusy(true); setErr(null)
    try {
      // the live system gets the same kind of defect and the app moves to Operations to show where and how it was placed
      window.dispatchEvent(new CustomEvent('railblock:sudden-defect'))
      const r = await api.injectDemand()
      lastResult = r
      setResult(r)
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusy(false)
    }
  }

  const cpsatSeconds = result ? result.cpsat.latency_ms / 1000 : 0
  const rlMs = result ? result.rl.latency_ms : 0
  // Scale both bars against the CP-SAT time, which is always the slower one, so the RL bar
  // reads as a sliver against it - that contrast is the whole point of the demo.
  const maxMs = result ? Math.max(result.cpsat.latency_ms, 40) : 1

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Try it live: an unplanned defect appears mid-week</h2>
        <span className="sub">calls the real API, on the current task pool</span>
      </div>

      <div className="panel-body">
        <button className="action primary" onClick={run} disabled={busy}>
          {busy ? 'Re-planning both ways…' : 'Inject an unplanned defect'}
        </button>

        {err && <div className="reason" style={{ marginTop: 14, borderLeftColor: 'var(--stopstart)' }}>
          Could not reach the planner: {err}
        </div>}

        {result && (
          <>
            <div className="reason" style={{ margin: '16px 0', borderLeftColor: 'var(--accent)' }}>
              <b>{result.task.describe}</b>
              <div className="rule">
                {result.task.department} · {result.task.zone} · {result.task.duration_min} min ·
                priority {result.task.priority}
              </div>
            </div>

            <div style={{ display: 'grid', gap: 14 }}>
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12.5, marginBottom: 5 }}>
                  <span>CP-SAT — full exact re-solve</span>
                  <span className="mono">{cpsatSeconds.toFixed(2)} s</span>
                </div>
                <div className="bar" style={{ height: 10 }}>
                  <i style={{
                    width: `${Math.min(100, (result.cpsat.latency_ms / maxMs) * 100)}%`,
                    background: 'var(--text-mute)',
                  }} />
                </div>
              </div>
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12.5, marginBottom: 5 }}>
                  <span>RL dispatcher — reactive re-plan</span>
                  <span className="mono">{rlMs.toFixed(0)} ms</span>
                </div>
                <div className="bar" style={{ height: 10 }}>
                  <i style={{
                    width: `${Math.max(1.5, (result.rl.latency_ms / maxMs) * 100)}%`,
                    background: 'var(--fit)',
                  }} />
                </div>
              </div>
            </div>

            <div className="tiles" style={{ marginTop: 16 }}>
              <div className="tile">
                <div className="v" style={{ color: 'var(--accent)' }}>{result.speedup_x}×</div>
                <div className="k">Faster, measured just now</div>
              </div>
              <div className="tile">
                <div className="v">{result.cpsat.scheduled}<small>/{result.cpsat.n_tasks}</small></div>
                <div className="k">CP-SAT placed</div>
              </div>
              <div className="tile">
                <div className="v">{result.rl.scheduled}<small>/{result.rl.n_tasks}</small></div>
                <div className="k">RL placed</div>
              </div>
              <div className="tile">
                <div className="v" style={{ color: result.rl.demand_task_placed ? 'var(--fit)' : 'var(--sick)' }}>
                  {result.rl.demand_task_placed ? 'yes' : 'not yet'}
                </div>
                <div className="k">New defect fitted in by RL</div>
              </div>
            </div>

            <div className="reason" style={{ marginTop: 16, borderLeftColor: 'var(--iwp)' }}>
              Dispatcher used: <b>{result.rl.dispatcher}</b>.{' '}
              {result.rl.dispatcher.includes('torch unavailable')
                ? 'The trained CQL-DQN model could not load on this machine right now, so this ran the greedy heuristic instead - the speedup shown is real but smaller than the trained model achieves on the held-out benchmark below.'
                : 'This is the trained policy, evaluated live.'}
              {' '}Constraint violations: <b>{result.rl.violations}</b>.
            </div>
          </>
        )}
      </div>
    </div>
  )
}
