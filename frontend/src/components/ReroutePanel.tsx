import type { RerouteBlock } from '../api'

/* What the closed sections are doing to through traffic, right now: who was sent around, at what
   cost, and where there simply is no other way. Silent when nothing is closed. */

export default function ReroutePanel({ blocks }: { blocks: RerouteBlock[] }) {
  const all = blocks.filter(b => b.reroutes.length || b.no_path.length || b.track_swap)
  // Sections with an actual detour first: those are the ones worth reading.
  const sorted = [...all].sort((a, b) => b.reroutes.length - a.reroutes.length)
  const rows = sorted.slice(0, 4)
  if (!rows.length) return null

  return (
    <div className="panel">
      <div className="panel-head"><h2>Rerouting now</h2><span className="sub">{all.length} closed now</span></div>
      <div className="panel-body flush">
        {rows.map(b => (
          <div key={`${b.section_id}-${b.start_s}`} style={{ padding: '10px 16px', borderBottom: '1px solid var(--line-soft)', fontSize: 12.5 }}>
            <b className="mono">{b.section_id}</b>
            <span className="muted"> closed</span>
            {b.reroutes.map(r => (
              <div key={r.train_id} style={{ marginTop: 4 }}>
                <span style={{ color: '#0891b2' }}>●</span> {r.train_name || r.train_id}
                <span className="muted"> via {r.sections.length} other sections · {r.added_delay_min >= 0.5 ? `+${r.added_delay_min} min` : 'no added time'}
                  {r.within_limit ? '' : ' (over limit)'}</span>
              </div>
            ))}
            {b.no_path.length > 0 && (
              <div className="muted" style={{ marginTop: 4 }}>
                {b.no_path.length} through {b.no_path.length === 1 ? 'train has' : 'trains have'} no other route here
              </div>
            )}
            {b.track_swap && (
              <div style={{ marginTop: 4 }}>
                <span style={{ color: 'var(--sick)' }}>●</span> locals run single-line on {b.track_swap.swap_to_track}
                <span className="muted"> · {b.locals_in_window} affected</span>
              </div>
            )}
          </div>
        ))}
        {all.length > rows.length && (
          <div className="muted" style={{ padding: '8px 16px', fontSize: 11.5 }}>
            +{all.length - rows.length} more closed sections
          </div>
        )}
      </div>
    </div>
  )
}
