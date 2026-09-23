import { useEffect, useState } from 'react'
import { api, type NetworkData, type SuddenMetrics, type SuddenResult } from '../api'

/* A job nobody planned. Pick how urgent it is and inject it; the system fits it into the live
   schedule and shows, with measured numbers, how: a gap that already existed, a gap it opened by a
   small change to the trains, or lower-priority work it moved aside (and where that went). */

const LEVELS: { id: 'low' | 'medium' | 'high' | 'critical'; label: string; due: string }[] = [
  { id: 'low', label: 'Low', due: 'due in 3 days' },
  { id: 'medium', label: 'Medium', due: 'due in 24 h' },
  { id: 'high', label: 'High', due: 'due in 6 h' },
  { id: 'critical', label: 'Critical', due: 'due in 2 h' },
]
const METHOD: Record<string, string> = {
  gap: 'Existing gap', created: 'Gap opened', bumped: 'Lower-priority work moved', late: 'Booked late', none: 'Not placed',
}
const DEPTS = [['', 'Any department'], ['PWI', 'P.Way'], ['OWD', 'Overhead'], ['S_AND_T', 'S&T']]
const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
const hh = (s: number) => `${String(Math.floor((s % 86400) / 3600)).padStart(2, '0')}:${String(Math.floor((s % 3600) / 60)).padStart(2, '0')}`

export default function SuddenPanel({ net, clock, onResult, onWatch, onClear, tick }: {
  net: NetworkData
  clock: number
  onResult: (r: SuddenResult) => void
  onWatch: (r: SuddenResult) => void
  onClear: () => void
  tick: number
}) {
  const [zone, setZone] = useState('')
  const [dept, setDept] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [last, setLast] = useState<SuddenResult | null>(null)
  const [m, setM] = useState<SuddenMetrics | null>(null)
  const [how, setHow] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const refresh = () => api.suddenMetrics().then(setM).catch(() => undefined)
  useEffect(() => { void refresh() }, [tick])                       // eslint-disable-line
  useEffect(() => {
    api.suddenLog().then(d => { if (d.log.length) setLast(d.log[0]) }).catch(() => undefined)
  }, [])

  const inject = async (level: 'low' | 'medium' | 'high' | 'critical') => {
    setBusy(level); setErr(null)
    try {
      const r = await api.suddenInject({
        level, zone_ref: zone || null, department: dept || null, at_s: Math.round(clock),
      })
      setLast(r); setHow(false); onResult(r); void refresh()
    } catch (e) { setErr(String(e)) } finally { setBusy(null) }
  }

  const clear = async () => { await api.suddenClear(); setLast(null); setM({ n: 0 }); onClear() }

  return (
    <div className="panel sudden">
      <div className="panel-head">
        <h2>Sudden task</h2>
        <span className="sub">not in the weekly plan</span>
      </div>
      <div className="panel-body">
        <div className="sd-pick">
          <select value={zone} onChange={e => setZone(e.target.value)} aria-label="Where">
            <option value="">Anywhere on the network</option>
            {net.sections.map(s => <option key={s.id} value={s.id}>{s.id}</option>)}
          </select>
          <select value={dept} onChange={e => setDept(e.target.value)} aria-label="Department">
            {DEPTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </div>
        <div className="sd-levels">
          {LEVELS.map(l => (
            <button key={l.id} className={`lv lv-${l.id}`} disabled={busy !== null} onClick={() => inject(l.id)}>
              <b>{busy === l.id ? '…' : l.label}</b><span>{l.due}</span>
            </button>
          ))}
        </div>
        {err && <div className="hint warn">{err}</div>}

        {last && (
          <div className={`sd-result ${last.placed ? 'ok' : 'no'} lv-${last.level.toLowerCase()}`}>
            <div className="sd-head">
              <span className={`sd-tag lv-${last.level.toLowerCase()}`}>{last.level}</span>
              <b>{last.task.describe}</b>
            </div>
            <div className="sd-line">
              {last.window ? (
                <><b>{last.window.hhmm}</b> on <span className="mono">{last.window.section_id}</span> ({last.window.track})</>
              ) : <span>No slot before {last.deadline_hhmm}</span>}
              <span className={`sd-method m-${last.method}`}>{METHOD[last.method]}</span>
            </div>

            <div className="sd-tiles">
              <div><b>{last.response_ms < 10 ? last.response_ms.toFixed(1) : Math.round(last.response_ms)} ms</b>
                <span>{last.plan_resolve_s ? `vs ${last.plan_resolve_s.toFixed(0)} s to re-plan the week` : 'to place'}</span></div>
              {last.exposure && (
                <div><b>{last.exposure.passengers.toLocaleString()}</b>
                  <span>passengers within reach · {last.exposure.trains_per_hour.toFixed(0)} trains/h (avg {last.network_tph.toFixed(0)})</span></div>
              )}
              {last.margin_min !== null && (
                <div className={last.margin_min < 0 ? 'bad' : ''}><b>{last.margin_min >= 0 ? `${Math.round(last.margin_min / 60 * 10) / 10} h` : `${Math.abs(Math.round(last.margin_min / 60 * 10) / 10)} h late`}</b>
                  <span>{last.margin_min >= 0 ? 'to spare before deadline' : 'past the deadline'}</span></div>
              )}
              {last.created && (
                <div><b>{last.created.delay_min.toFixed(0)} train-min</b>
                  <span>{last.created.lever_label} · {last.created.pax_delay.toLocaleString()} passenger-min</span></div>
              )}
              {last.reroutes && (last.reroutes.diverted > 0 || last.reroutes.locals > 0) && (
                <div><b>{last.reroutes.diverted} diverted</b>
                  <span>{last.reroutes.locals} locals stay on their track pair</span></div>
              )}
            </div>

            {last.bumped.length > 0 && (
              <div className="sd-moved">
                {last.bumped.map(b => (
                  <div key={b.task_id}>
                    <b className="mono">{b.task_id}</b> P{b.priority} · {b.from.hhmm}
                    {' '}<span className="arrow">→</span>{' '}
                    {b.to ? <b>{b.to.hhmm}</b> : <b className="bad">deferred</b>}
                  </div>
                ))}
              </div>
            )}

            <div className="sd-actions">
              {last.window && <button className="action primary" onClick={() => onWatch(last)}>Watch on map</button>}
              <button className="action" onClick={() => setHow(h => !h)}>{how ? 'Hide steps' : 'How it decided'}</button>
            </div>
            {how && <ol className="steps">{last.steps.map((s, i) => <li key={i}>{s}</li>)}</ol>}
          </div>
        )}

        {m && m.n > 0 && (
          <div className="sd-proof">
            <div className="sd-proof-head">
              <b>Measured over {m.n} sudden task{m.n === 1 ? '' : 's'}</b>
              <button className="link" onClick={clear}>clear</button>
            </div>
            <div className="sd-tiles">
              <div><b>{m.placed}/{m.n}</b><span>placed · {m.in_time} in time</span></div>
              <div><b>{m.median_ms} ms</b><span>median{m.speedup_x ? ` · ${m.speedup_x.toLocaleString()}× faster than a full re-plan` : ''}</span></div>
              {m.site_tph !== null && m.site_tph !== undefined && (
                <div><b>{m.site_tph} vs {m.network_tph}</b><span>trains/h at chosen sites vs network average</span></div>
              )}
              {(m.bumped_total ?? 0) > 0 && (
                <div><b>{m.replaced_total}/{m.bumped_total}</b><span>moved jobs re-placed{(m.deferred_total ?? 0) > 0 ? `, ${m.deferred_total} deferred` : ''}</span></div>
              )}
            </div>
          </div>
        )}
        <div className="hint" style={{ marginTop: 10 }}>
          Now: {DAYS[Math.floor(clock / 86400) % 7]} {hh(clock)}
        </div>
      </div>
    </div>
  )
}
