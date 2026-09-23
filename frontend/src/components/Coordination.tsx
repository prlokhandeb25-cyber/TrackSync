import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  api, type FormOptions, type MatrixData, type ScoredTask, type ScoresData, type SubmitResult,
} from '../api'
import CompatMatrix from './CompatMatrix'

/* Department coordination: a department raises a job on the left; on the right the system scores
   how well it fits with the jobs around it, groups it with them, and gives it a time in the train
   gaps. The score is the rule engine's verdicts over the job's cross-department neighbours (see
   backend/domain/scoring.py); nothing here is decorative. */

const DEPT_COLOR: Record<string, string> = { PWI: '#4a6fa5', OWD: '#a5744a', S_AND_T: '#4aa58c' }
const DEPT_SHORT: Record<string, string> = { PWI: 'PWI', OWD: 'OWD', S_AND_T: 'S&T' }
const VERDICT_TEXT: Record<string, string> = {
  COMPATIBLE: 'can share', REQUIRES_IWP: 'needs permit', INCOMPATIBLE: 'must be apart',
}

const scoreColor = (s: number) => (s >= 80 ? 'var(--fit)' : s >= 50 ? 'var(--sick)' : 'var(--stopstart)')

function Dial({ value, size = 46 }: { value: number; size?: number }) {
  const r = size / 2 - 4
  const c = 2 * Math.PI * r
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} style={{ flex: 'none' }}>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--line)" strokeWidth={4} />
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={scoreColor(value)} strokeWidth={4}
              strokeLinecap="round" strokeDasharray={`${(value / 100) * c} ${c}`}
              transform={`rotate(-90 ${size / 2} ${size / 2})`} style={{ transition: 'stroke-dasharray .6s' }} />
      <text x="50%" y="53%" textAnchor="middle" dominantBaseline="middle" fontSize={size * 0.32}
            fontWeight={700} fill="var(--text)" fontFamily="var(--mono)">{value}</text>
    </svg>
  )
}

/* ------------------------------------------------------------------------------- the form */

function TaskForm({ opts, clock, onDone }: {
  opts: FormOptions; clock: number; onDone: (r: SubmitResult) => void
}) {
  const [dept, setDept] = useState('PWI')
  const [typeCode, setTypeCode] = useState('')
  const [desc, setDesc] = useState('')
  const [zone, setZone] = useState('')
  const [dur, setDur] = useState(60)
  const [prio, setPrio] = useState(3)
  const [allows, setAllows] = useState<string[]>(['PWI', 'OWD', 'S_AND_T'])
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const types = useMemo(() => opts.task_types.filter(t => t.department === dept), [opts, dept])
  useEffect(() => {
    const t = types[0]
    if (t) { setTypeCode(t.code); setDur(Math.round((t.min + t.max) / 2 / 5) * 5) }
  }, [types])
  useEffect(() => { if (!zone && opts.sections.length) setZone(opts.sections[0].id) }, [opts, zone])

  const others = opts.departments.filter(d => d.code !== dept)
  const allotted = new Set(opts.allotments[dept] ?? [])
  const zoneOk = allotted.size === 0 || allotted.has(zone) || [...allotted].some(a => a.split('-').includes(zone))

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true); setErr(null)
    try {
      const r = await api.submitTask({
        description: desc, department: dept, zone_ref: zone, task_type: typeCode,
        duration_min: dur, priority: prio, allows_with: allows.filter(a => a !== dept), at_s: Math.round(clock),
      })
      onDone(r)
      setDesc('')
    } catch (ex) { setErr(String(ex)) } finally { setBusy(false) }
  }

  const bylines: Record<string, typeof opts.sections> = {}
  for (const s of opts.sections) (bylines[s.line] ??= []).push(s)
  const LINE = { CR: 'Central', WR: 'Western', HR: 'Harbour', TH: 'Trans-Harbour' } as Record<string, string>

  return (
    <form className="panel" onSubmit={submit}>
      <div className="panel-head"><h2>Raise a job</h2><span className="sub">any department</span></div>
      <div className="panel-body" style={{ display: 'grid', gap: 14 }}>
        <div>
          <label className="flabel">Which department is raising it?</label>
          <div className="seg">
            {opts.departments.map(d => (
              <button type="button" key={d.code} className={dept === d.code ? 'on' : ''}
                      style={dept === d.code ? { borderColor: DEPT_COLOR[d.code], background: `${DEPT_COLOR[d.code]}33` } : undefined}
                      onClick={() => { setDept(d.code); setAllows(a => a.filter(x => x !== d.code)) }}>
                <b>{DEPT_SHORT[d.code]}</b><span>{d.label.split('(')[0]}</span>
              </button>
            ))}
          </div>
        </div>

        <div>
          <label className="flabel">Kind of work</label>
          <select value={typeCode} onChange={e => {
            setTypeCode(e.target.value)
            const t = types.find(x => x.code === e.target.value)
            if (t) setDur(Math.round((t.min + t.max) / 2 / 5) * 5)
          }}>
            {types.map(t => <option key={t.code} value={t.code}>{t.label}</option>)}
          </select>
        </div>

        <div>
          <label className="flabel">Describe the job</label>
          <textarea rows={2} value={desc} onChange={e => setDesc(e.target.value)}
                    placeholder="e.g. rail crack found near the platform end" />
        </div>

        <div>
          <label className="flabel">Where — the section to be allotted</label>
          <select value={zone} onChange={e => setZone(e.target.value)}>
            {Object.entries(bylines).map(([line, list]) => (
              <optgroup key={line} label={`${LINE[line] ?? line} line`}>
                {list.map(s => <option key={s.id} value={s.id}>{s.label} ({s.id})</option>)}
              </optgroup>
            ))}
            <optgroup label="Stations">
              {opts.stations.map(s => <option key={s.code} value={s.code}>{s.name} station</option>)}
            </optgroup>
          </select>
          {!zoneOk && (
            <div className="hint warn">
              {DEPT_SHORT[dept]} is not allotted this stretch this week, so the system will refuse it (rule R0).
            </div>
          )}
        </div>

        <div className="two">
          <div>
            <label className="flabel">How long (min)</label>
            <input type="number" min={10} max={720} step={5} value={dur}
                   onChange={e => setDur(Number(e.target.value))} />
          </div>
          <div>
            <label className="flabel">Priority</label>
            <select value={prio} onChange={e => setPrio(Number(e.target.value))}>
              {[1, 2, 3, 4, 5].map(p => <option key={p} value={p}>{p}{p === 1 ? ' — most urgent' : p === 5 ? ' — routine' : ''}</option>)}
            </select>
          </div>
        </div>

        <div>
          <label className="flabel">Can work alongside</label>
          <div className="checks">
            {others.map(d => (
              <label key={d.code} className={allows.includes(d.code) ? 'on' : ''}>
                <input type="checkbox" checked={allows.includes(d.code)}
                       onChange={e => setAllows(a => e.target.checked ? [...a, d.code] : a.filter(x => x !== d.code))} />
                <i style={{ background: DEPT_COLOR[d.code] }} />{d.label.split('(')[0].trim()}
              </label>
            ))}
          </div>
          <div className="hint">Untick a department and the system will keep its work at a different time.</div>
        </div>

        {err && <div className="hint warn">{err}</div>}
        <button className="action primary" type="submit" disabled={busy || !zone}>
          {busy ? 'Checking…' : 'Check compatibility & schedule'}
        </button>
      </div>
    </form>
  )
}

/* ---------------------------------------------------------------------------- the score card */

function ScoreCard({ t, open, onToggle, onShow }: {
  t: ScoredTask; open: boolean; onToggle: () => void; onShow: (section: string, startS?: number) => void
}) {
  const sc = t.score
  const s = t.schedule
  return (
    <div className={`score-card ${t.source === 'USER' ? 'mine' : ''}`}>
      <div className="score-main" onClick={onToggle}>
        <Dial value={sc?.score ?? 0} />
        <div style={{ minWidth: 0, flex: 1 }}>
          <div className="score-top">
            <span className={`badge dept ${t.department}`}>{DEPT_SHORT[t.department]}</span>
            <b>{t.description || t.label}</b>
            {t.source === 'USER' && <span className="badge micro">yours</span>}
            {t.source === 'SIM' && <span className="badge">simulated</span>}
          </div>
          <div className="score-meta">
            <span className="mono">{t.zone}</span> · {t.duration_min} min
            {t.cluster && <> · <span className="chip">group {t.cluster.id} · {t.cluster.label} ({t.cluster.size})</span></>}
            {sc && !sc.standalone && (
              <> · <span style={{ color: 'var(--fit)' }}>{sc.compatible} ok</span>
                {sc.requires_iwp > 0 && <> · <span style={{ color: 'var(--iwp)' }}>{sc.requires_iwp} permit</span></>}
                {sc.incompatible > 0 && <> · <span style={{ color: 'var(--stopstart)' }}>{sc.incompatible} apart</span></>}</>
            )}
            {sc?.standalone && <> · <span className="muted">nothing nearby to conflict with</span></>}
          </div>
          <div className="score-sched">
            {s ? (
              <>
                <b>{s.day} {s.hhmm}</b> · {s.section_id} ({s.track}) · {s.gap_type.replace('_', ' ').toLowerCase()}
                {s.integrated_with.length > 0 && <span className="tag good"> one block with {s.integrated_with.slice(0, 3).join(', ')}{s.integrated_with.length > 3 && ` +${s.integrated_with.length - 3} more`}</span>}
                {s.created && <span className="tag warn"> gap created</span>}
              </>
            ) : (
              <span className="muted">{t.unplaced_reason ?? 'not yet placed by the weekly plan'}</span>
            )}
          </div>
        </div>
      </div>

      {open && (
        <div className="score-detail">
          {s && s.steps.length > 0 && (
            <ol className="steps">{s.steps.map((x, i) => <li key={i}>{x}</li>)}</ol>
          )}
          {s?.created && (
            <div className="reason" style={{ margin: '8px 0', borderLeftColor: 'var(--sick)' }}>
              No natural gap was long enough, so the system opened one: <b>{s.created.note}</b>
              <div className="muted" style={{ fontSize: 11.5, marginTop: 4 }}>
                cost {s.created.delay_min} train-minutes · {s.created.lever_label}
              </div>
            </div>
          )}
          {sc && sc.pairs.length > 0 ? sc.pairs.map(p => (
            <div key={p.other} className="pairline">
              <span className={`vdot v-${p.verdict}`} />
              <span className="mono">{p.other}</span>
              <b style={{ margin: '0 6px' }}>{VERDICT_TEXT[p.verdict]}</b>
              <span className="muted">{p.reason}</span>
            </div>
          )) : <div className="muted" style={{ fontSize: 12 }}>No other department has a job near this one.</div>}
          {s && <button className="action" style={{ marginTop: 8 }} onClick={() => onShow(s.section_id, s.start_s)}>Show on Operations map →</button>}
        </div>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------------------------- page */

export default function Coordination({ mat, clock, onShow }: {
  mat: MatrixData | null; clock: number; onShow: (section: string, startS?: number) => void
}) {
  const [opts, setOpts] = useState<FormOptions | null>(null)
  const [data, setData] = useState<ScoresData | null>(null)
  const [last, setLast] = useState<SubmitResult | null>(null)
  const [open, setOpen] = useState<string | null>(null)
  const [mine, setMine] = useState(false)
  const [sim, setSim] = useState(false)
  const [showMatrix, setShowMatrix] = useState(false)

  const load = useCallback(() => {
    api.taskScores(sim).then(setData).catch(() => { /* next refresh retries */ })
  }, [sim])
  useEffect(() => { api.formOptions().then(setOpts).catch(() => undefined) }, [])
  useEffect(() => { load(); const id = setInterval(load, 8000); return () => clearInterval(id) }, [load])

  const onDone = (r: SubmitResult) => { setLast(r); setOpen(r.task.id); load() }
  const rows = (data?.tasks ?? []).filter(t => !mine || t.source === 'USER')

  return (
    <div className="grid coord">
      <div style={{ display: 'grid', gap: 16, alignContent: 'start' }}>
        {opts ? <TaskForm opts={opts} clock={clock} onDone={onDone} />
          : <div className="loading"><div className="spinner" />Loading the form…</div>}
        {last && (
          <div className="panel result-flash">
            <div className="panel-head"><h2>{last.task.id} — what the system did</h2>
              <span className="sub">{last.scheduling_ms} ms</span></div>
            <div className="panel-body" style={{ fontSize: 13 }}>
              {last.rejected_by_allotment ? (
                <div className="reason" style={{ margin: 0, borderLeftColor: 'var(--stopstart)' }}>
                  {last.task.unplaced_reason}
                </div>
              ) : (
                <>
                  <div className="flow">
                    <div><span>1</span> Scored <b style={{ color: scoreColor(last.task.score?.score ?? 0) }}>{last.task.score?.score}</b>/100
                      against {last.task.score?.mates ?? 0} nearby job(s)</div>
                    <div><span>2</span> {last.task.cluster && last.task.cluster.size > 1
                      ? <>Grouped with {last.task.cluster.size - 1} job(s) around <b>{last.task.cluster.label}</b></>
                      : <>Stands alone around <b>{last.task.cluster?.label}</b></>}</div>
                    <div><span>3</span> {last.task.schedule
                      ? <>Scheduled <b>{last.task.schedule.day} {last.task.schedule.hhmm}</b> on {last.task.schedule.section_id}
                          {last.task.schedule.integrated_with.length > 0 && <>, sharing a block with {last.task.schedule.integrated_with.slice(0, 3).join(', ')}{last.task.schedule.integrated_with.length > 3 && ` and ${last.task.schedule.integrated_with.length - 3} more`}</>}</>
                      : <>Could not be placed: {last.task.unplaced_reason}</>}</div>
                  </div>
                  <button className="action" style={{ marginTop: 10 }}
                          onClick={() => last.task.schedule && onShow(last.task.schedule.section_id, last.task.schedule.start_s)}>
                    See it on the Operations map →
                  </button>
                </>
              )}
            </div>
          </div>
        )}
      </div>

      <div style={{ display: 'grid', gap: 16, alignContent: 'start', minWidth: 0 }}>
        <div className="panel">
          <div className="panel-head">
            <h2>Compatibility score</h2>
            <span className="sub">how well each job fits the ones around it</span>
          </div>
          <div className="panel-body">
            <div className="tiles mini">
              <div className="tile"><div className="v">{data?.summary.n_tasks ?? '—'}</div><div className="k">jobs</div></div>
              <div className="tile"><div className="v" style={{ color: scoreColor(data?.summary.mean_score ?? 0) }}>
                {data?.summary.mean_score ?? '—'}</div><div className="k">average score</div></div>
              <div className="tile"><div className="v">{data?.summary.n_shared ?? '—'}</div>
                <div className="k">shared groups</div><div className="note">nearby jobs that can share a block</div></div>
              <div className="tile"><div className="v" style={{ color: 'var(--accent)' }}>{data?.summary.n_user ?? 0}</div>
                <div className="k">raised by you</div></div>
            </div>
            <div className="filters">
              <button className={!mine ? 'on' : ''} onClick={() => setMine(false)}>All jobs</button>
              <button className={mine ? 'on' : ''} onClick={() => setMine(true)}>Only mine</button>
              <label><input type="checkbox" checked={sim} onChange={e => setSim(e.target.checked)} /> include simulated arrivals</label>
              {(data?.summary.n_user ?? 0) > 0 && (
                <button style={{ marginLeft: 'auto' }} onClick={() => api.clearUserTasks().then(() => { setLast(null); load() })}>
                  Clear my jobs
                </button>
              )}
            </div>
          </div>
          <div className="panel-body flush scroll" style={{ maxHeight: 640 }}>
            {!data && <div className="loading"><div className="spinner" />Scoring every job…</div>}
            {rows.map(t => (
              <ScoreCard key={t.id} t={t} open={open === t.id}
                         onToggle={() => setOpen(open === t.id ? null : t.id)} onShow={onShow} />
            ))}
            {data && rows.length === 0 && <div className="panel-body muted">Nothing raised yet — use the form.</div>}
          </div>
        </div>

        {mat && (
          <div>
            <button className="action" onClick={() => setShowMatrix(s => !s)}>
              {showMatrix ? 'Hide' : 'Show'} the pair-by-pair matrix behind the scores
            </button>
            {showMatrix && <div style={{ marginTop: 12 }}><CompatMatrix data={mat} /></div>}
          </div>
        )}
      </div>
    </div>
  )
}
