import { useEffect, useState } from 'react'
import { api, type ImpactData, type ImpactMetric, type ScoreCardData, type ScoreCardItem } from '../api'

/* The before/after story, built so a sceptic can test it. Every figure is measured over the same
   instances for the manual baseline and this system; each algorithm's card says how the number was
   taken and how to reproduce it; the two invented parameters behind the "before" case are sliders,
   so the advantage can be watched surviving a hostile setting rather than taken on trust. */

const fmtMs = (v: number) => {
  if (v >= 86_400_000) return `${(v / 86_400_000).toFixed(v >= 864_000_000 ? 0 : 1)} days`
  if (v >= 3_600_000) return `${(v / 3_600_000).toFixed(1)} h`
  if (v >= 1000) return `${(v / 1000).toFixed(1)} s`
  return `${v.toFixed(0)} ms`
}
const fmt = (v: number, unit: string) => {
  if (unit === 'ms') return fmtMs(v)
  if (unit === '%') return `${v.toFixed(1)}%`
  if (unit === 'hours') return v >= 100 ? `${v.toFixed(0)} h` : `${v.toFixed(1)} h`
  return `${v.toFixed(0)}`
}

function Row({ m }: { m: ImpactMetric }) {
  const good = m.improvement_pct > 0.5
  const bad = m.improvement_pct < -0.5
  return (
    <div className="ba-row">
      <div className="ba-name">{m.name}</div>
      <div className="ba" style={{ padding: 0, border: 'none' }}>
        <div className="side before"><div className="v">{fmt(m.before, m.unit)}</div><div className="k">before · manual</div></div>
        <div className="arrow">→</div>
        <div className="side after">
          <div className="v" style={{ color: good ? 'var(--fit)' : bad ? 'var(--stopstart)' : 'var(--text)' }}>{fmt(m.after, m.unit)}</div>
          <div className="k">after · RailBlock AI</div>
        </div>
      </div>
      {m.note && <div className="ba-note">{m.note}</div>}
    </div>
  )
}

function Card({ c }: { c: ScoreCardItem }) {
  const [open, setOpen] = useState(false)
  const hi = Math.max(c.before.value, c.after.value, 1e-9)
  const lowerBetter = c.after.value < c.before.value
  return (
    <div className="proof-card">
      <div className="pc-head"><b>{c.algorithm}</b></div>
      <div className="pc-what">{c.what}</div>
      {[c.before, c.after].map((s, i) => (
        <div key={i} className="pc-row">
          <div className="pc-label">{s.label}</div>
          <div className="pc-bar"><i style={{ width: `${Math.max(3, (s.value / hi) * 100)}%`,
            background: i === 0 ? '#47566b' : 'linear-gradient(90deg, var(--fit), #2a9d6a)' }} /></div>
          <div className="pc-val"><b>{s.value.toLocaleString()}</b> <span>{s.unit}</span></div>
        </div>
      ))}
      <div className="pc-detail">
        {lowerBetter && c.before.value > 0 && <b style={{ color: 'var(--fit)' }}>{(c.before.value / Math.max(c.after.value, 1e-9)).toFixed(c.before.value / Math.max(c.after.value, 1e-9) >= 10 ? 0 : 1)}× lower. </b>}
        {!lowerBetter && c.before.value > 0 && c.after.value > c.before.value && <b style={{ color: 'var(--fit)' }}>{(c.after.value / c.before.value).toFixed(1)}× higher. </b>}
        {c.detail}
      </div>
      <button className="pc-more" onClick={() => setOpen(o => !o)}>{open ? 'Hide' : 'How was this measured?'}</button>
      {open && (
        <div className="pc-how">
          <div>{c.how}</div>
          <div className="mono" style={{ marginTop: 6, color: 'var(--text-mute)' }}>reproduce: {c.repro}</div>
        </div>
      )}
    </div>
  )
}

export default function Impact() {
  const [d, setD] = useState<ImpactData | null>(null)
  const [sc, setSc] = useState<ScoreCardData | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [hours, setHours] = useState(4)
  const [wait, setWait] = useState(7)
  const [stress, setStress] = useState<ImpactData | null>(null)

  useEffect(() => {
    api.impact().then(setD).catch(e => setErr(String(e)))
    api.scorecard().then(setSc).catch(() => undefined)
  }, [])
  useEffect(() => {
    if (hours === 4 && wait === 7) { setStress(null); return }   // the defaults are the main run
    const t = setTimeout(() => api.impact(hours, wait).then(setStress).catch(() => undefined), 350)
    return () => clearTimeout(t)
  }, [hours, wait])

  if (err) return <div className="panel"><div className="panel-body muted">Could not load impact metrics: {err}</div></div>
  if (!d) return <div className="loading"><div className="spinner" />Measuring the manual baseline and every algorithm…</div>

  const m = (id: string, src: ImpactData | null = d) => src?.metrics.find(x => x.id === id)
  const m1 = m('M1'), m2 = m('M2')
  const h = sc?.headline

  return (
    <div style={{ display: 'grid', gap: 16 }}>
      <div className="panel hero">
        <div className="panel-head"><h2>Why this should be used</h2><span className="sub">every figure measured in this run</span></div>
        <div className="panel-body">
          <div className="tiles">
            {h && (
              <>
                <div className="tile"><div className="v" style={{ color: 'var(--fit)' }}>+{h.capacity_gain_pct}%</div>
                  <div className="k">usable maintenance time</div><div className="note">by using every gap, not just the night and Sunday block</div></div>
                <div className="tile"><div className="v" style={{ color: 'var(--fit)' }}>{h.urgent_jobs_natural} → {h.urgent_jobs_creation}</div>
                  <div className="k">urgent jobs placed in time</div><div className="note">of {h.urgent_jobs_total}, with gap creation</div></div>
                <div className="tile"><div className="v" style={{ color: 'var(--fit)' }}>{h.blocks_manual} → {h.blocks_ours}</div>
                  <div className="k">protected blocks needed</div><div className="note">compatible departments share one block</div></div>
              </>
            )}
            {m1 && <div className="tile"><div className="v" style={{ color: 'var(--fit)' }}>{fmtMs(m1.before)} → {fmtMs(m1.after)}</div>
              <div className="k">to re-plan after a defect</div><div className="note">instead of waiting for the next weekly cycle</div></div>}
            {m2 && <div className="tile"><div className="v" style={{ color: 'var(--fit)' }}>{m2.before.toFixed(0)} h → {(m2.after * 3600).toFixed(0)} s</div>
              <div className="k">department coordination</div><div className="note">phone negotiation replaced by rules with written reasons</div></div>}
          </div>
          {h && (
            <p className="explain" style={{ margin: '16px 0 0', fontSize: 13.5 }}>
              On the same timetable and the same jobs, the system finds <b>{h.capacity_gain_pct}% more usable maintenance time</b>,
              places <b>{h.jobs_placed_ours} of the week's jobs against {h.jobs_placed_manual}</b> for department-by-department planning,
              gets <b>{h.urgent_jobs_creation} of {h.urgent_jobs_total} urgent jobs</b> done inside six hours where existing gaps allow only {h.urgent_jobs_natural},
              and needs <b>{h.blocks_ours} protected blocks instead of {h.blocks_manual}</b>. It also answers in milliseconds where today's process waits days.
              The cost is stated too: opening gaps delays trains, counted in train-minutes on each card below.
            </p>
          )}
        </div>
      </div>

      <div>
        <div className="k muted" style={{ fontSize: 11, margin: '0 0 8px 2px' }}>PROOF, ALGORITHM BY ALGORITHM</div>
        {!sc ? <div className="loading"><div className="spinner" />Running every algorithm once more for its proof…</div> : (
          <div className="proof-grid">{sc.cards.map(c => <Card key={c.id} c={c} />)}</div>
        )}
      </div>

      <div className="grid two">
        <div className="panel">
          <div className="panel-head"><h2>All ten metrics</h2><span className="sub">before · manual → after · RailBlock AI</span></div>
          <div className="panel-body">{d.metrics.map(x => <Row key={x.id} m={x} />)}</div>
        </div>

        <div style={{ display: 'grid', gap: 16, alignContent: 'start' }}>
          <div className="panel">
            <div className="panel-head"><h2>Try to break the comparison</h2><span className="sub">the two invented numbers behind “before”</span></div>
            <div className="panel-body">
              <div className="slider">
                <label>Phone negotiation per conflict <b>{hours} h</b></label>
                <input type="range" min={0.25} max={8} step={0.25} value={hours} onChange={e => setHours(Number(e.target.value))} />
              </div>
              <div className="slider">
                <label>Wait for the next planning cycle <b>{wait} days</b></label>
                <input type="range" min={0.5} max={14} step={0.5} value={wait} onChange={e => setWait(Number(e.target.value))} />
              </div>
              {(stress ?? d) && (
                <div className="tiles mini" style={{ marginTop: 12 }}>
                  {['M1', 'M2'].map(id => {
                    const x = m(id, stress ?? d)!
                    return (
                      <div className="tile" key={id}>
                        <div className="v" style={{ color: x.improvement_pct > 0 ? 'var(--fit)' : 'var(--stopstart)' }}>
                          {id === 'M1' ? `${(x.before / Math.max(1, x.after)).toExponential(1).replace('e+', '×10^')}×` : `${x.improvement_pct.toFixed(0)}%`}
                        </div>
                        <div className="k">{id === 'M1' ? 're-plan speed-up' : 'coordination time saved'}</div>
                        <div className="note">{fmt(x.before, x.unit)} → {fmt(x.after, x.unit)}</div>
                      </div>
                    )
                  })}
                </div>
              )}
              <div className="reason" style={{ margin: '14px 0 0', borderLeftColor: 'var(--sick)' }}>{String(d.assumptions.note)}</div>
            </div>
          </div>

          <div className="panel">
            <div className="panel-head"><h2>What this does not show</h2></div>
            <div className="panel-body">
              <ul className="limits">{(sc?.limits ?? []).map((t, i) => <li key={i}>{t}</li>)}</ul>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
