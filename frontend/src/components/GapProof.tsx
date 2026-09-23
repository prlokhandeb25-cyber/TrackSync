import { useEffect, useState } from 'react'
import { api, DAYS, hhmm, type CreationSummary, type GapTrace } from '../api'

/* What the gap engine did, shown rather than claimed: for one track and a few hours of one day,
   every gap between two trains, the arithmetic that turns it into working time, and whether it
   was kept. Near misses show the small change to the trains that would have made them long enough
   (gap creation). The bright bars are the windows the engine really produced for this track. */

const W = 640

export default function GapProof() {
  const [section, setSection] = useState('')
  const [track, setTrack] = useState('')
  const [day, setDay] = useState(1)
  const [d, setD] = useState<GapTrace | null>(null)
  const [cs, setCs] = useState<CreationSummary | null>(null)

  useEffect(() => {
    api.explainGaps(section, track, day, 5, 9).then(t => {
      setD(t)
      if (!section) setSection(t.section_id)
      if (!track) setTrack(t.track)
    }).catch(() => undefined)
  }, [section, track, day])
  useEffect(() => { api.creationSummary().then(setCs).catch(() => undefined) }, [])

  if (!d) return <div className="panel"><div className="panel-body loading"><div className="spinner" />Replaying the gap engine…</div></div>

  const t0 = d.day * 86400 + d.hour_from * 3600
  const t1 = d.day * 86400 + d.hour_to * 3600
  const x = (s: number) => 8 + ((s - t0) / (t1 - t0)) * (W - 16)
  const sec = d.choices.find(c => c.id === d.section_id)
  const rows = d.rows.slice(0, 14)

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>1 · Finding the gaps</h2>
        <span className="sub">{d.n_trains} trains on this track today</span>
      </div>

      <div className="panel-body" style={{ paddingBottom: 6 }}>
        <div className="pickers">
          <select value={d.section_id} onChange={e => { setSection(e.target.value); setTrack('') }}>
            {d.choices.map(c => <option key={c.id} value={c.id}>{c.label} ({c.id})</option>)}
          </select>
          <select value={d.track} onChange={e => setTrack(e.target.value)}>
            {(sec?.tracks ?? [d.track]).map(t => <option key={t} value={t}>{t.replace('_', ' ')}</option>)}
          </select>
          <select value={day} onChange={e => setDay(Number(e.target.value))}>
            {DAYS.map((n, i) => <option key={n} value={i}>{n}</option>)}
          </select>
        </div>

        <p className="explain">
          Gap − <b>{d.buffer_min} min</b> safety − <b>{d.overhead_min} min</b> set-up = work time. Keep if ≥{' '}
          <b>{d.min_workable_min} min</b>. Checked <b>{d.rows.length}</b> gaps
          ({hhmm(d.hour_from * 3600)}–{hhmm(d.hour_to * 3600)}): <b style={{ color: 'var(--fit)' }}>{d.kept} kept</b>,{' '}
          <b style={{ color: 'var(--sick)' }}>{d.near_misses} near misses</b>.
        </p>

        <svg viewBox={`0 0 ${W} 74`} width="100%" role="img" aria-label="Trains and gaps on the track">
          <rect x={8} y={8} width={W - 16} height={26} rx={4} fill="var(--line-soft)" />
          {d.windows.map(w => (
            <rect key={w.id} className="gap-in" x={x(Math.max(w.start_s, t0))} y={8}
                  width={Math.max(2, x(Math.min(w.end_s, t1)) - x(Math.max(w.start_s, t0)))} height={26} rx={3}
                  fill={w.gap_type === 'MICRO_GAP' ? 'var(--accent)' : w.gap_type === 'NIGHT_WINDOW' ? 'var(--block)' : 'var(--fit)'} opacity={0.9} />
          ))}
          {d.rows.filter(r => !r.keep && r.creation).map((r, i) => (
            <rect key={`c${i}`} x={x(r.creation!.start_s)} y={8}
                  width={Math.max(2, x(r.creation!.end_s) - x(r.creation!.start_s))} height={26} rx={3}
                  fill="none" stroke="var(--sick)" strokeWidth={1.4} strokeDasharray="4 3" />
          ))}
          {d.rows.map((r, i) => (
            <line key={i} x1={x(r.next.enter_s)} x2={x(r.next.enter_s)} y1={10} y2={32}
                  stroke="var(--text)" strokeOpacity={0.5} strokeWidth={0.8} />
          ))}
          {[0, 1, 2, 3, 4].map(k => {
            const s = t0 + (k * (t1 - t0)) / 4
            return <text key={k} x={x(s)} y={54} fontSize={9.5} fill="var(--text-mute)" fontFamily="var(--mono)"
                         textAnchor={k === 0 ? 'start' : k === 4 ? 'end' : 'middle'}>{hhmm(s)}</text>
          })}
          <g fontSize={10} fill="var(--text-dim)">
            <rect x={8} y={62} width={10} height={8} rx={2} fill="var(--accent)" /><text x={22} y={69.5}>usable</text>
            <rect x={70} y={62} width={10} height={8} rx={2} fill="none" stroke="var(--sick)" strokeDasharray="3 2" /><text x={84} y={69.5}>near miss (fixable)</text>
            <line x1={200} x2={200} y1={61} y2={71} stroke="var(--text)" strokeOpacity={0.6} /><text x={206} y={69.5}>train</text>
          </g>
        </svg>
      </div>

      <div className="panel-body flush scroll" style={{ maxHeight: 330 }}>
        <table>
          <thead>
            <tr><th>Between</th><th className="num">Gap</th><th className="num">− safety</th><th className="num">− set-up</th><th className="num">Work time</th><th>Verdict</th></tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} style={{ animation: `row-in .4s ${i * 35}ms both` }}>
                <td className="mono">{hhmm(r.prev.exit_s)}–{hhmm(r.next.enter_s)}</td>
                <td className="num">{r.gap_min}</td>
                <td className="num">{r.after_buffers_min}</td>
                <td className="num">{(r.after_buffers_min - d.overhead_min).toFixed(0)}</td>
                <td className="num" style={{ fontWeight: 650, color: r.keep ? 'var(--fit)' : 'var(--text-mute)' }}>{r.usable_min}</td>
                <td>
                  {r.keep ? <span style={{ color: 'var(--fit)' }}>✓ kept<span className="muted"> · {r.reliability_pct}% reliable</span></span>
                    : r.creation ? <span style={{ color: 'var(--sick)' }}>◐ {r.creation.note}</span>
                      : <span className="muted">✗ too short</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {cs && (
        <div className="panel-body">
          <div className="k muted" style={{ fontSize: 11, marginBottom: 8 }}>WHOLE WEEK · GAP CREATION</div>
          <div className="tiles mini">
            <div className="tile"><div className="v">{cs.survey.near_gaps.toLocaleString()}</div><div className="k">near-miss gaps</div>
              <div className="note">just short of {cs.min_workable_min} min</div></div>
            <div className="tile"><div className="v" style={{ color: 'var(--fit)' }}>{cs.survey.created}</div><div className="k">opened</div>
              <div className="note">{cs.survey.RETIME} held · {cs.survey.REROUTE} rerouted</div></div>
            <div className="tile"><div className="v" style={{ color: 'var(--accent)' }}>+{cs.survey.usable_hours_added}h</div><div className="k">usable hours</div></div>
            <div className="tile"><div className="v">{cs.survey.delay_train_min.toLocaleString()}</div><div className="k">train-min cost</div></div>
            <div className="tile"><div className="v">{cs.weekly.natural_placed} → {cs.weekly.final_placed}</div><div className="k">jobs placed</div>
              <div className="note">without → with</div></div>
          </div>
        </div>
      )}
    </div>
  )
}
