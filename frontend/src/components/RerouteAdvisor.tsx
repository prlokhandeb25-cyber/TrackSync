import { useEffect, useState } from 'react'
import { api, type ReroutingData } from '../api'

/* SPEC §9: for the tasks CP-SAT genuinely could not fit anywhere, what lever could create a
   window. Kept as a standalone advisor rather than wired into the solver's own objective - the
   solver already reaches OPTIMAL at a 0% gap, and this is real analysis on top of it, not a
   guess. The guardrail (a SUBURBAN_LOCAL is never rerouted) lives in the backend and is tested
   there; this only ever renders what that backend actually returned. */

export default function RerouteAdvisor() {
  const [d, setD] = useState<ReroutingData | null>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => { api.reroutingOpportunities().then(setD).catch(e => setErr(String(e))) }, [])

  if (err) return null
  if (!d) return (
    <div className="panel" style={{ marginTop: 16 }}>
      <div className="panel-body muted">Checking for rerouting opportunities…</div>
    </div>
  )
  if (d.unscheduled_total === 0) return null

  return (
    <div className="panel" style={{ marginTop: 16 }}>
      <div className="panel-head">
        <h2>Could a window be created for the unplaced work?</h2>
        <span className="sub">{d.unscheduled_total} jobs have no window long enough</span>
      </div>
      <div className="lede">
        Intercity and freight trains have a fixed origin and destination but not a fixed route,
        so they can be <b>rerouted</b> to free a corridor. Suburban locals serve fixed stations
        and are never rerouted — their only lever is running <b>single-line working</b> on their
        own track pair. Every figure below came from a real path search or track check just now.
      </div>
      <div className="panel-body flush scroll" style={{ maxHeight: 320 }}>
        {d.opportunities.length === 0 && (
          <div className="panel-body muted">
            No lever found for the remaining work — it needs a window longer than either
            rerouting or a track swap can create here.
          </div>
        )}
        {d.opportunities.map(o => (
          <div key={o.task_id} style={{ padding: '12px 16px', borderBottom: '1px solid var(--line-soft)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12.5 }}>
              <span>
                <span className={`badge dept ${o.department ?? ''}`}>{o.department}</span>{' '}
                {o.task_label} on <span className="mono">{o.zone_ref}</span>
              </span>
              <span className="mono muted">needs {o.shortfall_min} more min</span>
            </div>
            <div className="chips" style={{ marginTop: 8 }}>
              {o.reroute_paths.slice(0, 3).map((p, i) => (
                <span key={i} className="chip" title={p.sections.join(' → ')}>
                  reroute <b>{p.train_id}</b> ({p.train_class.toLowerCase()}) +{p.added_delay_min}min
                  {p.within_limit ? '' : ' (over limit)'}
                </span>
              ))}
              {o.track_swap && (
                <span className="chip">
                  single-line <b>{o.track_swap.blocked_track}</b> ↔ {o.track_swap.swap_to_track}
                  , up to {o.track_swap.max_single_line_min}min, {o.track_swap.locals_affected_per_hour}/hr locals affected
                </span>
              )}
              {o.reroute_paths.length === 0 && !o.track_swap && (
                <span className="chip muted">no lever found on this section</span>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
