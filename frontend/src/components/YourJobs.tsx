import { useEffect, useState } from 'react'
import { api, type ScoredTask } from '../api'

/* Jobs raised on the coordination page, with where the system put them. "Watch it" jumps the
   simulation clock to just before the job starts, so the hazard stripes, the working crew and any
   rerouted trains appear on the map straight away instead of hours of simulated time later. */

export default function YourJobs({ tick, onWatch, onWindows }: {
  tick: number; onWatch: (t: ScoredTask) => void
  onWindows: (w: { zone_ref: string; start_s: number; end_s: number; id: string; dept: string; label: string; track?: string }[]) => void
}) {
  const [rows, setRows] = useState<ScoredTask[]>([])
  useEffect(() => {
    api.taskScores(false).then(d => {
      const mine = d.tasks.filter(t => t.source === 'USER')
      setRows(mine)
      onWindows(mine.filter(t => t.schedule).map(t => ({
        zone_ref: t.schedule!.section_id, start_s: t.schedule!.start_s, end_s: t.schedule!.end_s,
        id: t.id, dept: t.department, label: t.description || t.label, track: t.schedule!.track })))
    }).catch(() => undefined)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick])
  if (!rows.length) return null

  return (
    <div className="panel">
      <div className="panel-head"><h2>Your jobs</h2><span className="sub">raised on Department coordination</span></div>
      <div className="panel-body flush">
        {rows.map(t => (
          <div key={t.id} style={{ padding: '11px 16px', borderBottom: '1px solid var(--line-soft)', fontSize: 12.5 }}>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              <span className={`badge dept ${t.department}`}>{t.department === 'S_AND_T' ? 'S&T' : t.department}</span>
              <b>{t.description || t.label}</b>
              {t.score && <span className="chip">score {t.score.score}</span>}
            </div>
            {t.schedule ? (
              <div style={{ marginTop: 5, color: 'var(--text-dim)' }}>
                {t.schedule.day} {t.schedule.hhmm} on <span className="mono">{t.schedule.section_id}</span> ({t.schedule.track})
                {t.schedule.integrated_with.length > 0 && <span className="tag good"> shares a block</span>}
                {t.schedule.created && <span className="tag warn"> gap created</span>}
                <div><button className="action" style={{ marginTop: 7 }}
                             onClick={() => onWatch(t)}>
                  ▶ Watch it on the map
                </button></div>
              </div>
            ) : <div className="muted" style={{ marginTop: 4 }}>{t.unplaced_reason ?? 'not placed'}</div>}
          </div>
        ))}
      </div>
    </div>
  )
}
