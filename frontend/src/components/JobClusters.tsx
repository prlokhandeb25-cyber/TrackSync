import { useEffect, useState } from 'react'
import { api, type ClustersData } from '../api'

/* How jobs are grouped: nearby work from different departments can share one protected block.
   Each group is a colour on the map; click a chip to spotlight it. */

export interface Halo { zone: string; color: string; active: boolean }

const PALETTE = ['#22d3ee', '#a3e635', '#facc15', '#fb7185', '#f472b6',
                 '#818cf8', '#2dd4bf', '#fdba74', '#c4b5fd', '#86efac']

export default function JobClusters({ tick, onHalos }: { tick: number; onHalos: (h: Halo[]) => void }) {
  const [d, setD] = useState<ClustersData | null>(null)
  const [sel, setSel] = useState<number | null>(null)
  const [show, setShow] = useState(true)

  useEffect(() => { api.clusters().then(setD).catch(() => { /* next tick retries */ }) }, [tick])

  useEffect(() => {
    if (!d || !show) { onHalos([]); return }
    onHalos(d.clusters.filter(c => c.size > 1).flatMap(c =>
      c.zones.map(z => ({ zone: z, color: PALETTE[(c.id - 1) % PALETTE.length], active: sel === c.id }))))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [d, sel, show])

  if (!d) return null
  const chosen = d.clusters.find(c => c.id === sel)
  const groups = d.clusters.filter(c => c.size > 1)
  const singles = d.clusters.length - groups.length

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Job clusters</h2>
        <span className="sub">{d.n_tasks} jobs → {groups.length} shared groups</span>
        <button className="action" style={{ padding: '3px 10px', fontSize: 11 }}
                onClick={() => setShow(s => !s)}>{show ? 'Hide on map' : 'Show on map'}</button>
      </div>
      <div className="panel-body">
        <div className="chips" style={{ marginTop: 0 }}>
          {groups.map(c => {
            const color = PALETTE[(c.id - 1) % PALETTE.length]
            return (
              <button key={c.id} className="chip"
                      style={{ cursor: 'pointer', borderColor: sel === c.id ? color : undefined,
                               background: sel === c.id ? `${color}22` : undefined }}
                      onClick={() => setSel(sel === c.id ? null : c.id)}>
                <i style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%',
                            background: color, marginRight: 6 }} />
                <b>{c.size}</b> · {c.label}
              </button>
            )
          })}
          {singles > 0 && <span className="chip muted">+{singles} single {singles === 1 ? 'job' : 'jobs'}</span>}
        </div>
        {chosen && (
          <div className="reason" style={{ margin: '12px 0 0', borderLeftColor: PALETTE[(chosen.id - 1) % PALETTE.length] }}>
            {chosen.departments.map(x => (
              <span key={x} className={`badge dept ${x}`} style={{ marginRight: 5 }}>{x}</span>
            ))}
            {chosen.total_min} min of work around {chosen.label}
            {chosen.cross_pairs > 0 && (
              <div className="muted" style={{ marginTop: 5, fontSize: 11.5 }}>
                {chosen.compatible} of {chosen.cross_pairs} cross-department pairs can share a block
                {chosen.requires_iwp > 0 && ` · ${chosen.requires_iwp} need a work permit`}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
