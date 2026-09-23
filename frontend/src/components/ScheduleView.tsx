import { useEffect, useState } from 'react'
import { api, DAYS, hhmm, type MonthSchedule, type PlanEntry, type WeekSchedule } from '../api'

/* The plan itself. Week: every day as a 24-hour column, each job a block at the time the planner
   gave it. Month: four rolling weekly cycles - each week is re-planned with the previous week's
   leftover jobs carried in, on the same repeating timetable. */

const DEPT_COLOR: Record<string, string> = { PWI: '#4a8fe7', OWD: '#e0894a', S_AND_T: '#3fc8a4' }
const DEPT_SHORT: Record<string, string> = { PWI: 'PWI', OWD: 'OWD', S_AND_T: 'S&T' }
const DAY = 86400

function tip(e: PlanEntry) {
  return `${DEPT_SHORT[e.department]} · ${e.description || e.label}\n${e.section_id} (${e.track})\n` +
    `${hhmm(e.start_s)}–${hhmm(e.end_s)} · ${e.gap_type.replace('_', ' ').toLowerCase()}` +
    (e.created ? '\nin a gap opened by a small change to the trains' : '') +
    (e.source === 'USER' ? '\nraised by you' : '')
}

function WeekGrid({ entries, dayOffset = 0 }: { entries: PlanEntry[]; dayOffset?: number }) {
  const H = 250
  return (
    <div className="weekgrid">
      <div className="hours">{[0, 6, 12, 18, 24].map(h => <span key={h} style={{ top: (h / 24) * H }}>{String(h % 24).padStart(2, '0')}</span>)}</div>
      {DAYS.map((name, di) => {
        const day = entries.filter(e => Math.floor(e.start_s / DAY) === di + dayOffset)
          .sort((a, b) => a.start_s - b.start_s)
        // side-by-side lanes: a block goes in the first lane that is free at its start time
        const laneEnd: number[] = []
        const laneOf = day.map(e => {
          let k = laneEnd.findIndex(end => end <= e.start_s)
          if (k < 0) { k = laneEnd.length; laneEnd.push(0) }
          laneEnd[k] = e.end_s
          return k
        })
        const lanes = Math.max(1, laneEnd.length)
        return (
          <div key={name} className="daycol">
            <div className="dayname">{name}<b>{day.length || ''}</b></div>
            <div className="strip" style={{ height: H }}>
              {[6, 12, 18].map(h => <i key={h} style={{ top: (h / 24) * H }} />)}
              {day.map((e, i) => (
                <div key={e.task_id + e.start_s} title={tip(e)}
                     className={`blk ${e.created ? 'created' : ''} ${e.source === 'USER' ? 'user' : ''}`}
                     style={{ top: ((e.start_s % DAY) / DAY) * H, height: Math.max(5, ((e.end_s - e.start_s) / DAY) * H),
                              left: `calc(${(laneOf[i] / lanes) * 100}% + 2px)`, right: 'auto',
                              width: `calc(${100 / lanes}% - 3px)`, background: DEPT_COLOR[e.department] }} />
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}

function Legend() {
  return (
    <div className="legend" style={{ border: 'none', padding: '10px 0 0' }}>
      {Object.entries(DEPT_COLOR).map(([k, c]) => <span key={k}><i style={{ background: c }} />{DEPT_SHORT[k]}</span>)}
      <span className="sep" />
      <span><i style={{ background: 'transparent', border: '1.5px dashed var(--sick)' }} />gap opened by a small change</span>
      <span><i style={{ background: 'transparent', border: '1.5px solid #fff' }} />raised by you</span>
    </div>
  )
}

export default function ScheduleView() {
  const [mode, setMode] = useState<'week' | 'month'>('week')
  const [wk, setWk] = useState<WeekSchedule | null>(null)
  const [mo, setMo] = useState<MonthSchedule | null>(null)
  const [pickDay, setPickDay] = useState<number | null>(null)

  useEffect(() => { api.scheduleWeek().then(setWk).catch(() => undefined) }, [])

  useEffect(() => {
    if (mode !== 'month') return
    let alive = true
    api.buildMonth().catch(() => undefined)
    const pull = () => api.scheduleMonth().then(m => { if (alive) setMo(m) }).catch(() => undefined)
    void pull()
    const id = setInterval(pull, 2500)
    return () => { alive = false; clearInterval(id) }
  }, [mode])

  const s = wk?.summary
  const allMonth = (mo?.weeks ?? []).flatMap(w => w.entries)

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Step 3 — the schedule</h2>
        <div className="seg2" style={{ marginLeft: 'auto' }}>
          <button className={mode === 'week' ? 'on' : ''} onClick={() => setMode('week')}>Week</button>
          <button className={mode === 'month' ? 'on' : ''} onClick={() => setMode('month')}>Month</button>
        </div>
      </div>

      {mode === 'week' && (!wk ? <div className="panel-body loading"><div className="spinner" />Loading the week…</div> : (
        <div className="panel-body">
          <div className="tiles mini">
            <div className="tile"><div className="v">{s!.placed}<small>/{s!.n_tasks}</small></div><div className="k">jobs placed</div>
              <div className="note">{s!.solver.toLowerCase()} · {s!.gap_pct}% gap · {s!.wall_s}s</div></div>
            <div className="tile"><div className="v" style={{ color: 'var(--accent)' }}>{s!.micro_gap}</div><div className="k">in gaps between trains</div></div>
            <div className="tile"><div className="v">{s!.night}</div><div className="k">in night windows</div></div>
            <div className="tile"><div className="v">{s!.megablock}</div><div className="k">in the Sunday megablock</div></div>
            <div className="tile"><div className="v" style={{ color: 'var(--sick)' }}>+{Math.max(0, s!.plan_placed - s!.natural_only_placed)}</div>
              <div className="k">extra jobs from gap creation</div><div className="note">{s!.from_created_gaps} used a created gap</div></div>
          </div>
          <div style={{ marginTop: 16 }}><WeekGrid entries={wk.entries} /></div>
          <Legend />
          {wk.unplaced.length > 0 && (
            <div className="reason" style={{ margin: '12px 0 0', borderLeftColor: 'var(--sick)' }}>
              <b>{wk.unplaced.length} job(s) still unplaced:</b>{' '}
              {wk.unplaced.slice(0, 4).map(u => `${DEPT_SHORT[u.department]} ${u.label} on ${u.zone}`).join(' · ')}
              <div className="muted" style={{ fontSize: 11.5, marginTop: 4 }}>No window long enough even after gap creation; see the rerouting advisor below.</div>
            </div>
          )}
        </div>
      ))}

      {mode === 'month' && (
        <div className="panel-body">
          {(!mo || mo.status === 'running' || mo.status === 'idle') && (
            <div className="reason" style={{ margin: '0 0 14px', borderLeftColor: 'var(--accent)' }}>
              Planning four rolling weeks… <b>{mo?.progress ?? 0} of 4</b> done. Each week is solved exactly, with last week's leftover jobs carried in.
              <div className="bar"><i style={{ width: `${((mo?.progress ?? 0) / 4) * 100}%` }} /></div>
            </div>
          )}
          {mo?.status === 'error' && <div className="hint warn">Month planning failed: {mo.error}</div>}
          {mo && mo.weeks.length > 0 && (
            <>
              {mo.status === 'done' && <div className="tiles mini">
                <div className="tile"><div className="v">{mo.summary.placed}<small>/{mo.summary.n_tasks}</small></div><div className="k">jobs placed in the month</div></div>
                <div className="tile"><div className="v" style={{ color: 'var(--accent)' }}>{mo.summary.micro_gap}</div><div className="k">in gaps between trains</div></div>
                <div className="tile"><div className="v" style={{ color: 'var(--sick)' }}>{mo.summary.created}</div><div className="k">used a created gap</div></div>
                <div className="tile"><div className="v">{mo.summary.backlog_end}</div><div className="k">backlog left at month end</div></div>
              </div>}
              <div className="monthgrid">
                {mo.weeks.map(w => (
                  <div key={w.week} className="mweek">
                    <div className="mhead">
                      <b>Week {w.week}</b>
                      <span className="muted">{w.placed}/{w.n_tasks} placed{w.carried_in > 0 && ` · ${w.carried_in} carried in`}{w.carried_out > 0 && ` · ${w.carried_out} carried out`}</span>
                    </div>
                    <div className="mdays">
                      {DAYS.map((name, di) => {
                        const abs = (w.week - 1) * 7 + di
                        const list = w.entries.filter(e => Math.floor(e.start_s / DAY) === abs)
                        const on = pickDay === abs
                        return (
                          <button key={name} className={`mday ${on ? 'on' : ''}`} onClick={() => setPickDay(on ? null : abs)}>
                            <span>{name}</span>
                            <b>{list.length || '·'}</b>
                            <div className="dots">
                              {['PWI', 'OWD', 'S_AND_T'].map(dep => {
                                const n = list.filter(e => e.department === dep).length
                                return n ? <i key={dep} style={{ background: DEPT_COLOR[dep], flex: n }} /> : null
                              })}
                            </div>
                          </button>
                        )
                      })}
                    </div>
                  </div>
                ))}
              </div>
              {pickDay !== null && (
                <div style={{ marginTop: 14 }}>
                  <div className="k muted" style={{ fontSize: 11, marginBottom: 6 }}>
                    WEEK {Math.floor(pickDay / 7) + 1} · {DAYS[pickDay % 7].toUpperCase()}
                  </div>
                  <table>
                    <tbody>
                      {allMonth.filter(e => Math.floor(e.start_s / DAY) === pickDay).map(e => (
                        <tr key={e.task_id + e.start_s}>
                          <td className="mono">{hhmm(e.start_s)}–{hhmm(e.end_s)}</td>
                          <td><span className={`badge dept ${e.department}`}>{DEPT_SHORT[e.department]}</span></td>
                          <td>{e.description || e.label}</td>
                          <td className="mono">{e.section_id}</td>
                          <td className="muted">{e.gap_type.replace('_', ' ').toLowerCase()}{e.created && ' · created gap'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <Legend />
            </>
          )}
        </div>
      )}
    </div>
  )
}
