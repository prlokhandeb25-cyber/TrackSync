import { useEffect, useState } from 'react'
import { api, type ClustersData } from '../api'

/* How jobs are grouped: nearby work from different departments can share one protected block.
   Each group is a colour on the map; click a chip to spotlight it. */

export interface Halo { zone: string; color: string; active: boolean }

const PALETTE = ['#0284c7', '#65a30d', '#d97706', '#dc2626', '#c026d3',
                 '#4f46e5', '#0d9488', '#ea580c', '#7c3aed', '#16a34a']

export default function JobClusters({ tick, onHalos }: { tick: number; onHalos: (h: Halo[]) => void }) {
  const [d, setD] = useState<ClustersData | null>(null)
  const [sel, setSel] = useState<number | null>(null)
  const [show, setShow] = useState(true)
  const [method, setMethod] = useState<'average' | 'kmedoids'>('average')

  useEffect(() => { api.clusters(method).then(setD).catch(() => { /* next tick retries */ }) }, [tick, method])

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
        <div className="segc" style={{ marginBottom: 10 }}>
          <button className={method === 'average' ? 'on' : ''} onClick={() => { setSel(null); setMethod('average') }}>Average-linkage</button>
          <button className={method === 'kmedoids' ? 'on' : ''} onClick={() => { setSel(null); setMethod('kmedoids') }}>K-Medoids</button>
        </div>
        {d.compare && d.compare.methods.length === 2 && (
          <div className="cl-cmp">
            {d.compare.methods.map(m => (
              <div key={m.method} className={m.method.startsWith(method === 'average' ? 'Average' : 'K-Medoids') ? 'on' : ''}>
                <b>{m.silhouette.toFixed(2)}</b><span>{m.method.split(' (')[0]} · {m.groups} groups · {m.mean_km_to_centre} km to centre</span>
              </div>
            ))}
          </div>
        )}
        <div className="hint" style={{ margin: '0 0 8px' }}>Jobs group when they are close AND similarly urgent. Small jobs (up to 45 min) can ride in the biggest job's block if the rules allow.</div>
        {method === 'kmedoids' && <div className="hint" style={{ margin: '0 0 8px' }}>Silhouette: 1 is tight and well separated. ◎ marks each group's centre job, an actual place a shared block could go.</div>}
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
                <b>{c.size}</b> · {c.label}{c.medoid_id ? <em className="mono muted"> ◎{c.medoid_id}</em> : null}
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
            {chosen.riders && chosen.riders.length > 0 && (
              <div style={{ marginTop: 5, fontSize: 11.5 }}>{chosen.riders.length} small job{chosen.riders.length === 1 ? '' : 's'} can ride in the big job's block, saving {chosen.setup_saved_min} min of set-up and hand-back</div>
            )}
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
