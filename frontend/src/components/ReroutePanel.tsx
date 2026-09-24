import { useEffect, useState } from 'react'
import { api, DAYS, hhmm, type RerouteBlock, type RerouteProof, type RerouteProofRow } from '../api'
import { Num, TwinBars } from './Viz'

/* Rerouting, proved. Above: what the weekly plan does to through traffic, measured over every block
   in it (long-distance and freight are sent round; suburban locals never are). Below: the closures
   in force on the map right now, each vetted by the digital twin, which can overrule a detour that
   would cost the passengers more than simply waiting. */

export default function ReroutePanel({ blocks, onWatch }: {
  blocks: RerouteBlock[]
  onWatch: (row: RerouteProofRow) => void
}) {
  const [p, setP] = useState<RerouteProof | null>(null)
  useEffect(() => { api.reroutingProof().then(setP).catch(() => undefined) }, [])

  const all = blocks.filter(b => b.reroutes.length || b.no_path.length || b.track_swap || (b.held?.length ?? 0) > 0)
  const rows = [...all].sort((a, b) => (b.reroutes.length + (b.held?.length ?? 0)) - (a.reroutes.length + (a.held?.length ?? 0))).slice(0, 3)

  return (
    <div className="panel reroute">
      <div className="panel-head"><h2>Rerouting</h2><span className="sub">{all.length ? `${all.length} closed now` : 'none closed now'}</span></div>
      <div className="panel-body">
        {p && (
          <>
            <div className="tiles mini">
              <div className="tile"><div className="v"><Num v={p.diverted} /></div><div className="k">long-distance trains sent round</div>
                <div className="note">across {p.blocks} blocks; {p.no_path} more have no other route and wait</div></div>
              <div className="tile"><div className="v">+<Num v={p.mean_added_min} dp={0} /> min</div><div className="k">average detour</div>
                <div className="note">vs {Math.round(p.wait_min / Math.max(1, p.diverted))} min waiting</div></div>
              <div className="tile"><div className="v" style={{ color: 'var(--fit)' }}><Num v={p.saved_min} /></div><div className="k">train-minutes saved</div>
                <div className="note">{p.within_limit} of {p.diverted} inside their delay limit</div></div>
              <div className="tile"><div className="v" style={{ color: 'var(--fit)' }}>{p.locals_rerouted}</div><div className="k">locals rerouted</div>
                <div className="note">of {p.locals_in_blocks} that meet a block: they run single-line</div></div>
            </div>
            <div className="rr-list">
              {p.examples.slice(0, 4).map((r, i) => (
                <div key={`${r.train_id}${r.block_start_s}`} className="rr-item" style={{ animationDelay: `${i * 60}ms` }}>
                  <span className="rr-dot" />
                  <div className="rr-main">
                    <b>{r.train}</b> <span className="muted">round <span className="mono">{r.section_id}</span> · {DAYS[Math.floor(r.enter_s / 86400) % 7]} {hhmm(r.enter_s)}</span>
                    <div className="rr-cost"><span className="good">+{Math.round(r.added_min)} min</span> instead of <span className="bad">{Math.round(r.wait_min)} min</span> waiting · via {r.via} sections</div>
                  </div>
                  <button className="action" onClick={() => onWatch(r)}>Watch</button>
                </div>
              ))}
            </div>
          </>
        )}
        {!p && <div className="hint"><span className="spinner-sm" /> measuring every block in the plan…</div>}

        {rows.length > 0 && <div className="rr-now-title">On the map now</div>}
        {rows.map(b => {
          const r = b.response
          return (
            <div key={`${b.section_id}-${b.start_s}`} className="rr-block">
              <div><b className="mono">{b.section_id}</b><span className="muted"> closed {hhmm(b.start_s)}–{hhmm(b.end_s)}</span></div>
              {b.reroutes.map(x => (
                <div key={x.train_id} className="rr-line"><span style={{ color: '#0891b2' }}>●</span> {x.train_name || x.train_id}
                  <span className="muted"> via {x.sections.length} other sections · {x.added_delay_min >= 0.5 ? `+${Math.round(x.added_delay_min)} min` : 'no added time'}</span></div>
              ))}
              {(b.held ?? []).map(x => (
                <div key={x.train_id} className="rr-line"><span style={{ color: 'var(--amber)' }}>●</span> {x.train_name || x.train_id}
                  <span className="muted"> held: the twin finds waiting costs fewer passengers than the detour</span></div>
              ))}
              {b.no_path.length > 0 && <div className="rr-line muted">{b.no_path.length} through {b.no_path.length === 1 ? 'train has' : 'trains have'} no other route here</div>}
              {b.track_swap && <div className="rr-line"><span style={{ color: 'var(--sick)' }}>●</span> locals run single-line on {b.track_swap.swap_to_track}<span className="muted"> · {b.locals_in_window} affected</span></div>}
              {b.swap_declined && <div className="rr-line"><span style={{ color: 'var(--amber)' }}>●</span> locals hold rather than run single-line<span className="muted"> · the twin finds it costs more</span></div>}
              {r?.status === 'checking' && <div className="hint"><span className="spinner-sm" /> digital twin checking this closure…</div>}
              {r?.status === 'ready' && r.pax_hours && (
                <div className="twin-box">
                  <div className="tw-head">Digital twin · next {r.horizon_h} h, {r.scenarios} random days · extra passenger-hours of delay</div>
                  <TwinBars hours={r.pax_hours} best={r.best} compact />
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
