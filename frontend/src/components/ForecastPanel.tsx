import { useEffect, useMemo, useState } from 'react'
import { api, DAYS, hhmm, type ForecastData, type ForecastRow, type PolicyRow } from '../api'
import { Num } from './Viz'
import type { FocusReq } from './NetworkMap'

/* Predicted blocks. A monitoring feed (simulated here) warns that assets may fail; the ones above the
   action threshold are booked days ahead as ordinary blocks in gaps that already exist. The guard
   table shows why it stops there: what each way of acting costs the trains, on the same warnings. */

export interface PredWin { zone_ref: string; start_s: number; end_s: number; id: string; dept: string; label: string }

const DAY = 86400
const DEPT_VAR: Record<string, string> = { PWI: 'var(--d-pwi)', OWD: 'var(--d-owd)', S_AND_T: 'var(--d-snt)' }
const SHORT: Record<string, string> = {
  'React only (no forecast)': 'Wait for the failure',
  'Plan every warning, changing trains if needed': 'Plan all, change trains',
  'Plan every warning, existing gaps only': 'Plan all, existing gaps',
  'Act at risk 30% and above, existing gaps': 'Act at 30% and above',
  'Act at risk 50% and above, existing gaps': 'Act at 50% and above',
  'Act at risk 70% and above, existing gaps': 'Act at 70% and above',
}

function WeekStrip({ rows, clock, onPick }: { rows: ForecastRow[]; clock: number; onPick: (r: ForecastRow) => void }) {
  const W = 440, H = 164, L = 26, T = 18, colW = (W - L - 4) / 7, innerH = H - T - 20
  const y = (s: number) => T + ((s % DAY) / DAY) * innerH
  const x = (s: number) => L + Math.min(6, Math.floor(s / DAY)) * colW
  const planned = rows.filter(r => r.decision === 'planned' && r.start_s !== null)
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="Predicted failures and the blocks planned ahead of them" className="pb-strip">
      {[0, 6, 12, 18, 24].map(h => (
        <g key={h}>
          <line x1={L} x2={W - 4} y1={T + (h / 24) * innerH} y2={T + (h / 24) * innerH} stroke="var(--line-soft)" />
          <text x={L - 4} y={T + (h / 24) * innerH + 3} fontSize={8.5} textAnchor="end" fill="var(--text-mute)" fontFamily="var(--mono)">{String(h % 24).padStart(2, '0')}</text>
        </g>
      ))}
      {DAYS.map((d, i) => <text key={d} x={L + i * colW + colW / 2} y={11} fontSize={9} textAnchor="middle" fill="var(--text-dim)">{d}</text>)}
      {rows.filter(r => r.decision !== 'covered').map(r => (
        <g key={`f${r.id}`} opacity={r.decision === 'watch' ? 0.45 : 0.9}>
          <path d={`M${x(r.fail_s) + colW / 2 - 3},${y(r.fail_s) - 3}l6,6m0,-6l-6,6`} stroke="var(--stopstart)" strokeWidth={1.3} strokeLinecap="round" />
        </g>
      ))}
      {planned.map((r, i) => (
        <rect key={r.id} className="pb-bar" x={x(r.start_s!) + 3} y={y(r.start_s!)} width={colW - 6}
              height={Math.max(4, ((r.end_s! - r.start_s!) / DAY) * innerH)} rx={2}
              fill={DEPT_VAR[r.department] ?? 'var(--accent)'} style={{ animationDelay: `${i * 45}ms`, cursor: 'pointer' }}
              onClick={() => onPick(r)}>
          <title>{`${r.label} on ${r.section}, ${DAYS[Math.floor(r.start_s! / DAY) % 7]} ${hhmm(r.start_s!)}`}</title>
        </rect>
      ))}
      {clock >= 0 && (
        <line x1={x(clock)} x2={x(clock) + colW} y1={y(clock)} y2={y(clock)} stroke="var(--accent)" strokeWidth={1.4} strokeDasharray="3 2">
          <animate attributeName="opacity" values="1;.35;1" dur="1.8s" repeatCount="indefinite" />
        </line>
      )}
      <g fontSize={9} fill="var(--text-dim)">
        <rect x={L} y={H - 5} width={8} height={4} fill="var(--accent)" /><text x={L + 11} y={H - 1}>planned ahead</text>
        <path d={`M${L + 92},${H - 6}l5,5m0,-5l-5,5`} stroke="var(--stopstart)" strokeWidth={1.3} /><text x={L + 102} y={H - 1}>where the warning says it fails</text>
      </g>
    </svg>
  )
}

function Guard({ d, cap }: { d: NonNullable<ForecastData['sweep']>; cap: number }) {
  const [scale, setScale] = useState(0)
  const sc = d.scales[Math.min(scale, d.scales.length - 1)]
  const react = sc.table[0]
  const max = Math.max(1, ...sc.table.map(r => r.train_min))
  const chosen = (r: PolicyRow) => !r.allow_create && Math.abs(r.threshold - d.in_use_threshold) < 1e-9 && r.threshold > 0
  return (
    <div className="pb-guard">
      <div className="pb-guard-head">
        <b>What acting on warnings costs the trains</b>
        <div className="segc">
          {d.scales.map((s, i) => (
            <button key={s.scale} className={i === scale ? 'on' : ''} onClick={() => setScale(i)}>
              {s.scale === 1 ? `${s.warnings} warnings` : `${s.warnings} (noisy feed)`}
            </button>
          ))}
        </div>
      </div>
      <div className="pb-rows">
        {sc.table.map((r, i) => (
          <div key={r.policy} className={`pb-row ${chosen(r) ? 'pick' : ''} ${r.gaps_made_proactive > 0 ? 'warnrow' : ''}`} style={{ animationDelay: `${i * 60}ms` }}>
            <span className="pb-l">{SHORT[r.policy] ?? r.policy}{chosen(r) && <em>in use</em>}</span>
            <div className="pb-t"><i style={{ width: `${Math.max(1.5, (r.train_min / max) * 100)}%`, animationDelay: `${i * 60}ms` }} /></div>
            <span className="pb-v">{Math.round(r.train_min).toLocaleString()}<small> train-min</small></span>
            <span className="pb-x">{r.blocks_added} blocks · {r.emergencies} emergencies · {r.gaps_made_proactive} trains held for blocks · {r.wasted_hours.toFixed(1)} h unneeded</span>
          </div>
        ))}
      </div>
      <div className="hint">
        Train-minutes lost, all emergencies included. Waiting for failures costs {Math.round(react.train_min).toLocaleString()}.
        No proactive block ever needed a train held or rerouted: each went into a gap that already existed. Acting on weaker
        warnings saves more train-minutes but books more blocks that turn out unneeded (crew hours), so the count is capped at
        {' '}{cap} a day and one visit per section per day.
      </div>
    </div>
  )
}

export default function ForecastPanel({ clock, tick, onWatch, onWindows }: {
  clock: number; tick: number
  onWatch: (section: string, startS?: number, extra?: Partial<FocusReq>) => void
  onWindows: (w: PredWin[]) => void
}) {
  const [d, setD] = useState<ForecastData | null>(null)
  const [open, setOpen] = useState(false)
  useEffect(() => {
    let alive = true
    const poll = () => api.forecast().then(r => {
      if (!alive) return
      setD(r)
      if (r.sweep_status === 'running' || r.sweep_status === 'idle') setTimeout(poll, 3000)
    }).catch(() => { if (alive) setTimeout(poll, 5000) })
    void poll()
    return () => { alive = false }
  }, [tick])                                                        // eslint-disable-line

  const planned = useMemo(() => (d?.rows ?? []).filter(r => r.decision === 'planned' && r.start_s !== null), [d])
  useEffect(() => {
    onWindows(planned.map(r => ({ zone_ref: r.zone_ref ?? r.section, start_s: r.start_s!, end_s: r.end_s!, id: r.id,
                                  dept: r.department, label: `Predicted: ${r.label}` })))
  }, [planned])                                                     // eslint-disable-line

  if (!d) return <div className="panel"><div className="panel-head"><h2>Predicted blocks</h2></div><div className="panel-body"><div className="loading"><div className="spinner" />Reading the watch list…</div></div></div>
  const s = d.summary
  const top = [...d.rows].sort((a, b) => b.risk - a.risk).slice(0, open ? 12 : 5)
  const sc1 = d.sweep?.scales[0]
  const rec = sc1?.table.find(r => !r.allow_create && r.threshold > 0 && Math.abs(r.threshold - (d.sweep?.in_use_threshold ?? -1)) < 1e-9)
  const react = sc1?.table[0]

  const watch = (r: ForecastRow) => r.start_s !== null && onWatch(r.zone_ref ?? r.section, r.start_s, {
    endS: r.end_s ?? undefined, label: `Predicted: ${r.label}`, dept: r.department, track: r.track ?? undefined, id: r.id })

  return (
    <div className="panel forecast">
      <div className="panel-head">
        <h2>Predicted blocks</h2>
        <span className="sub">{s.warnings} warnings · {s.planned} planned ahead</span>
      </div>
      <div className="panel-body">
        <div className="tiles mini">
          <div className="tile"><div className="v"><Num v={s.planned} /></div><div className="k">blocks planned ahead</div>
            <div className="note">of {s.warnings} warnings, risk {Math.round(s.threshold * 100)}% or more</div></div>
          <div className="tile"><div className="v" style={{ color: s.gaps_made === 0 ? 'var(--fit)' : 'var(--stopstart)' }}><Num v={s.gaps_made} /></div>
            <div className="k">trains held or rerouted</div><div className="note">all in gaps that already exist</div></div>
          {rec && react && (
            <div className="tile"><div className="v"><Num v={Math.round(react.train_min)} /> → <Num v={Math.round(rec.train_min)} /></div>
              <div className="k">train-minutes lost</div><div className="note">wait for failures → act on warnings</div></div>
          )}
          {rec && react && (
            <div className="tile"><div className="v"><Num v={react.emergencies} /> → <Num v={rec.emergencies} /></div>
              <div className="k">emergencies</div><div className="note">{rec.prevented} of {rec.failures} failures met early</div></div>
          )}
        </div>

        <WeekStrip rows={d.rows} clock={clock} onPick={watch} />

        <div className="pb-list">
          {top.map((r, i) => (
            <div key={r.id} className={`pb-item d-${r.decision.replace(' ', '')}`} style={{ animationDelay: `${i * 50}ms` }}>
              <div className="pb-meter" title={`risk ${Math.round(r.risk * 100)}%`}><i style={{ height: `${r.risk * 100}%` }} /></div>
              <div className="pb-main">
                <div><b>{r.label}</b> <span className="mono muted">{r.section}</span></div>
                <div className="muted">{r.cue} · {Math.round(r.risk * 100)}% risk</div>
                <div className={`pb-why ${r.decision}`}>
                  {r.decision === 'planned' && r.start_s !== null
                    ? <>Planned {DAYS[Math.floor(r.start_s / DAY) % 7]} {hhmm(r.start_s)}–{hhmm(r.end_s!)}</>
                    : r.why}
                </div>
              </div>
              {r.decision === 'planned' && <button className="action" onClick={() => watch(r)}>Show</button>}
            </div>
          ))}
          <button className="link" onClick={() => setOpen(o => !o)}>{open ? 'fewer' : `all ${d.rows.length} warnings`}</button>
        </div>

        {d.sweep && <Guard d={d.sweep} cap={s.max_per_day} />}
        {!d.sweep && d.sweep_status !== 'error' && <div className="hint"><span className="spinner-sm" /> measuring what each policy costs…</div>}
        {d.sweep_status === 'error' && <div className="hint warn">Could not finish the comparison: {d.sweep_error}</div>}
        <div className="hint">The warnings are simulated: there is no camera or sensor feed here. Booking them is the real scheduler.</div>
      </div>
    </div>
  )
}
