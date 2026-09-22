import { useState } from 'react'
import type { MatrixData, MatrixCell } from '../api'

/* The matrix is the automated replacement for three department heads negotiating by phone.
   Every cell carries the reason string the backend produced, because the reason is the
   argument - the colour alone only says that a decision was made, not why. */

export default function CompatMatrix({ data }: { data: MatrixData }) {
  const [hover, setHover] = useState<MatrixCell | null>(null)

  const ids = data.tasks.map(t => t.id)
  const lookup = new Map<string, MatrixCell>()
  for (const c of data.cells) {
    lookup.set(`${c.a}|${c.b}`, c)
    lookup.set(`${c.b}|${c.a}`, c)
  }
  const label = (id: string) => {
    const t = data.tasks.find(x => x.id === id)
    return t ? `${t.department} ${t.zone}` : id
  }
  const borderFor = (v?: string) =>
    v === 'INCOMPATIBLE' ? 'var(--incompatible)'
      : v === 'REQUIRES_IWP' ? 'var(--iwp)'
        : v === 'COMPATIBLE' ? 'var(--compatible)' : 'var(--line)'

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Department compatibility</h2>
        <span className="sub">{data.view}</span>
      </div>

      <div className="panel-body" style={{ paddingBottom: 4 }}>
        <div className="tiles">
          <div className="tile">
            <div className="v" style={{ color: 'var(--compatible)' }}>{data.summary.COMPATIBLE ?? 0}</div>
            <div className="k">Compatible</div>
          </div>
          <div className="tile">
            <div className="v" style={{ color: 'var(--iwp)' }}>{data.summary.REQUIRES_IWP ?? 0}</div>
            <div className="k">Need Integrated Work Permission</div>
          </div>
          <div className="tile">
            <div className="v" style={{ color: 'var(--incompatible)' }}>{data.summary.INCOMPATIBLE ?? 0}</div>
            <div className="k">Incompatible — must be sequenced</div>
          </div>
          <div className="tile">
            <div className="v">{data.manual_coordination_hours}h</div>
            <div className="k">Manual negotiation replaced</div>
            <div className="note">
              {data.coordination_conflicts} cross-department conflicts that three
              department heads would resolve by phone. Computed here in milliseconds.
            </div>
          </div>
        </div>
      </div>

      <div className="matrix-scroll">
        <table className="matrix">
          <thead>
            <tr>
              <th />
              {ids.map(id => <th key={id} className="collab">{label(id)}</th>)}
            </tr>
          </thead>
          <tbody>
            {ids.map(a => (
              <tr key={a}>
                <th className="rowlab">{label(a)}</th>
                {ids.map(b => {
                  if (a === b) return <td key={b} className="cell self" />
                  const c = lookup.get(`${a}|${b}`)
                  return (
                    <td
                      key={b}
                      className={`cell c-${c?.value ?? ''}`}
                      onMouseEnter={() => c && setHover(c)}
                      title={c?.reason ?? ''}
                    />
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="reason" style={{ borderLeftColor: borderFor(hover?.value) }}>
        {hover ? (
          <>
            <div>{hover.reason}</div>
            <div className="rule" style={{ marginTop: 6 }}>
              rule {hover.rule_id} · zones {hover.zone_relation.toLowerCase().replace('_', ' ')}
            </div>
          </>
        ) : (
          <span className="muted">
            Hover any cell to see why those two jobs can or cannot share a slot.
          </span>
        )}
      </div>
    </div>
  )
}
