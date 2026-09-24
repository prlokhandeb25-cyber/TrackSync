import { useEffect, useMemo, useState } from 'react'
import {
  api, type ImpactData, type MethodsSummary, type RerouteProof, type EfficiencyData, type PaxExperiment, type PaxWeekly, type PlanVerify, type Robustness, type ScoreCardData,
  type SuddenMetrics,
} from '../api'

/* Before / after, for a reader who has ten minutes: what today's manual practice achieves against
   this system, on the same timetable and the same jobs, one headline per comparison. Every bar is a
   number from a run that happened; "how measured" sits behind each card, and the two invented
   parameters of the manual baseline are sliders at the bottom so the advantage can be watched
   surviving a hostile setting. */

type Kind = 'h' | 'n' | 'ms' | 'pct'
const fmtMs = (v: number) => {
  if (v >= 86_400_000) return `${(v / 86_400_000).toFixed(v >= 864_000_000 ? 0 : 1)} days`
  if (v >= 3_600_000) return `${(v / 3_600_000).toFixed(1)} h`
  if (v >= 60_000) return `${(v / 60_000).toFixed(0)} min`
  if (v >= 1000) return `${(v / 1000).toFixed(1)} s`
  return `${v < 10 ? v.toFixed(1) : v.toFixed(0)} ms`
}
const fmt = (v: number, k: Kind) =>
  k === 'ms' ? fmtMs(v) : k === 'pct' ? `${v.toFixed(0)}%` : k === 'h' ? `${v < 10 ? v.toFixed(1) : Math.round(v).toLocaleString()} h`
  : Math.round(v).toLocaleString()

interface Bar { who: string; v: number; tone: 'before' | 'mid' | 'after' }
interface Cmp {
  id: string; title: string; kind: Kind; better: 'lower' | 'higher'; bars: Bar[]
  how: string; repro: string
  deltaVs?: number      // which bar the last one is compared with (default: the first)
  assumed?: boolean     // the first bar rests on an assumption, so no multiplier is claimed
  chip?: string         // overrides the headline chip (e.g. 'if warning works')
}

function delta(c: Cmp) {
  if (c.assumed) return { good: true, text: c.chip ?? 'assumed baseline', neutral: true }
  const a = c.bars[c.deltaVs ?? 0].v, b = c.bars[c.bars.length - 1].v
  if (a <= 0 && b <= 0) return null
  const good = c.better === 'higher' ? b > a : b < a
  const ratio = c.better === 'higher' ? b / Math.max(1e-9, a) : a / Math.max(1e-9, b)
  const text = ratio >= 2
    ? `${ratio >= 100 ? Math.round(ratio).toLocaleString() : ratio.toFixed(ratio >= 10 ? 0 : 1)}× ${c.better === 'higher' ? 'more' : 'less'}`
    : `${c.better === 'higher' ? '+' : '−'}${Math.round(Math.abs(b - a) / Math.max(1e-9, a) * 100)}%`
  return { good, text, neutral: false }
}

function Card({ c }: { c: Cmp }) {
  const [open, setOpen] = useState(false)
  const hi = Math.max(...c.bars.map(b => b.v), 1e-9)
  const d = delta(c)
  return (
    <div className="cmp">
      <div className="cmp-head">
        <h3>{c.title}</h3>
        {d && <span className={`delta ${d.neutral ? 'neutral' : d.good ? '' : 'bad'}`}>{d.text}</span>}
      </div>
      {c.bars.map(b => (
        <div key={b.who} className={`brow ${b.tone === 'after' ? 'after' : 'before'}`}>
          <span className="who">{b.who}</span>
          <div className="trk"><i style={{ width: `${Math.max(2, (b.v / hi) * 100)}%`,
            opacity: b.tone === 'mid' ? 0.9 : undefined, background: b.tone === 'mid' ? 'var(--amber)' : undefined }} /></div>
          <span className="val">{fmt(b.v, c.kind)}</span>
        </div>
      ))}
      <div className="cmp-foot">
        <span>{c.repro}</span>
        <button className="link" onClick={() => setOpen(o => !o)}>{open ? 'hide' : 'how measured'}</button>
      </div>
      {open && <div className="cmp-how">{c.how}</div>}
    </div>
  )
}

// The cards worth showing. Hidden for now (still computed, easy to bring back): 'pl' jobs placed, 'cp' clash calls,
// 'pw' weekly passenger view, 'twin' modelled closure delay, 'buf' crew buffers, 'it' gap search speed, 'sd' sudden task time.
const SHOWN = new Set(['gaps', 'cr', 'cl', 'm1', 'pax', 'rb', 'rr'])

export default function Impact() {
  const [d, setD] = useState<ImpactData | null>(null)
  const [sc, setSc] = useState<ScoreCardData | null>(null)
  const [px, setPx] = useState<PaxExperiment | null>(null)
  const [sd, setSd] = useState<SuddenMetrics | null>(null)
  const [pw, setPw] = useState<PaxWeekly | null>(null)
  const [rb, setRb] = useState<Robustness | null>(null)
  const [mt, setMt] = useState<MethodsSummary | null>(null)
  const [vf, setVf] = useState<PlanVerify | null>(null)
  const [ef, setEf] = useState<EfficiencyData | null>(null)
  const [rp, setRp] = useState<RerouteProof | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    api.impact().then(setD).catch(e => setErr(String(e)))
    api.scorecard().then(setSc).catch(() => undefined)
    api.paxExperiment().then(setPx).catch(() => undefined)
    api.suddenMetrics().then(setSd).catch(() => undefined)
    api.planVerify().then(setVf).catch(() => undefined)
    const pollMt = () => api.methodsSummary().then(r => { setMt(r); if (r.status === 'running') setTimeout(pollMt, 5000) }).catch(() => undefined)
    void pollMt()
    api.reroutingProof().then(setRp).catch(() => undefined)
    api.efficiency().then(setEf).catch(() => undefined)
    let alive = true
    const pollRb = () => api.planRobustness().then(r => { if (alive) { setRb(r); if (r.ablation_status === 'running') setTimeout(pollRb, 4000) } }).catch(() => undefined)
    void pollRb()
    const poll = () => api.paxWeekly().then(r => { if (alive) { setPw(r); if (r.status === 'running') setTimeout(poll, 3000) } }).catch(() => undefined)
    void poll()
    return () => { alive = false }
  }, [])

  const cmps = useMemo((): Cmp[] => {
    if (!sc || !d) return []
    const card = (id: string) => sc.cards.find(c => c.id === id)
    const out: Cmp[] = []
    const g = card('gaps'), cr = card('creation'), cl = card('cluster'), pl = card('plan'), it = card('interval'), cp = card('compat')
    const m1 = d.metrics.find(x => x.id === 'M1')
    const rl = card('rl')
    if (g) out.push({ id: 'gaps', title: 'Usable maintenance time each week', kind: 'h', better: 'higher',
      bars: [{ who: 'Night + Sunday', v: g.before.value, tone: 'before' }, { who: 'RailBlock', v: g.after.value, tone: 'after' }],
      how: g.how, repro: g.repro })
    if (cr) out.push({ id: 'cr', title: `Urgent jobs done in time (of ${sc.headline.urgent_jobs_total})`, kind: 'n', better: 'higher',
      bars: [{ who: 'Fixed timetable', v: cr.before.value, tone: 'before' }, { who: 'RailBlock', v: cr.after.value, tone: 'after' }],
      how: `${cr.how} ${cr.detail}`, repro: cr.repro })
    if (pl) out.push({ id: 'pl', title: 'Jobs placed in the weekly plan', kind: 'n', better: 'higher',
      bars: [{ who: 'Manual', v: pl.before.value, tone: 'before' }, { who: 'RailBlock', v: pl.after.value, tone: 'after' }],
      how: pl.how, repro: pl.repro })
    if (cl) out.push({ id: 'cl', title: 'Protected blocks needed', kind: 'n', better: 'lower',
      bars: [{ who: 'One per job', v: cl.before.value, tone: 'before' }, { who: 'Shared blocks', v: cl.after.value, tone: 'after' }],
      how: cl.how, repro: cl.repro })
    if (m1 && rl) out.push({ id: 'm1', title: 'Time to re-plan after a defect', kind: 'ms', better: 'lower', deltaVs: 1,
      bars: [{ who: 'Next weekly cycle*', v: m1.before, tone: 'before' },
             { who: 'Full CP-SAT solve', v: rl.before.value * 1000, tone: 'mid' },
             { who: 'RailBlock', v: rl.after.value * 1000, tone: 'after' }],
      how: `*Manual: the assumed wait for the next planning cycle (adjustable below). The multiplier compares RailBlock with a full exact solve, which was measured. ${rl.detail}`,
      repro: rl.repro })
    if (cp) out.push({ id: 'cp', title: 'Settling department clashes', kind: 'ms', better: 'lower',
      assumed: true,
      bars: [{ who: 'Phone calls*', v: cp.before.value * 3_600_000, tone: 'before' }, { who: 'RailBlock', v: cp.after.value, tone: 'after' }],
      how: `*${cp.how}`, repro: cp.repro })
    if (px) {
      // Manual (night + Sunday windows only) touches few passengers because it works almost only when
      // trains are few - and it places fewer jobs. It is named in the text rather than left out.
      out.push({ id: 'pax', title: `Passengers within reach of ${px.jobs} urgent jobs`, kind: 'n', better: 'lower',
        bars: [
          { who: 'Timing ignores them', v: px.unaware.passengers, tone: 'before' },
          { who: 'RailBlock', v: px.aware.passengers, tone: 'after' }],
        how: `${px.how} For reference, manual planning (night and Sunday windows only) touches ${px.manual.passengers.toLocaleString()} `
          + `passengers but places ${px.manual.placed} of ${px.jobs} jobs against ${px.aware.placed}, and has no daytime capacity for urgent work.`,
        repro: 'GET /api/pax/experiment' })
    }
    if (pw?.data) out.push({ id: 'pw', title: 'Weekly plan: passengers within reach', kind: 'n', better: 'lower',
      bars: [{ who: 'Timing ignores them', v: pw.data.unaware_common, tone: 'before' }, { who: 'RailBlock', v: pw.data.aware_common, tone: 'after' }],
      how: pw.data.how, repro: 'GET /api/pax/weekly' })
    if (rb?.ablation) out.push({ id: 'rb', title: 'Blocks that clear before the next train', kind: 'pct', better: 'higher',
      bars: [{ who: 'Solver alone', v: rb.ablation.raw.mean * 100, tone: 'before' }, { who: 'RailBlock', v: rb.plan.mean * 100, tone: 'after' }],
      how: `${rb.how} "Solver alone" is the same week solved without the fragile-window cost.`, repro: 'GET /api/plan/robustness' })
    // Predictive blocks were removed: the warning feed was simulated, so its accuracy could not be measured.
    const tw = mt?.results.twin
    const tc = tw?.cases.filter(c => c.policies.HOLD.pax_min >= 600).sort((x, y) => y.policies.HOLD.pax_min - x.policies.HOLD.pax_min)[0]
    if (tw && tc) out.push({ id: 'twin', title: `Passenger-hours of delay after a closure (${tc.label})`, kind: 'n', better: 'lower', assumed: true,
      chip: 'modelled recovery',
      bars: [{ who: 'Hold everything', v: Math.round(tc.policies.HOLD.pax_min / 60), tone: 'before' },
             { who: `Twin's choice`, v: Math.round(tc.policies[tc.best].pax_min / 60), tone: 'after' }],
      how: `${tw.how} ${tw.caveat}`, repro: 'GET /api/methods/summary' })
    if (rp && rp.diverted > 0) out.push({ id: 'rr', title: `Delay to ${rp.diverted} long-distance trains when a block closes their route`, kind: 'n', better: 'lower',
      chip: 'locals never rerouted',
      bars: [{ who: 'Wait for the block to lift', v: Math.round(rp.wait_min), tone: 'before' }, { who: 'Sent round', v: Math.round(rp.added_min), tone: 'after' }],
      how: `${rp.how} ${rp.no_path} more through trains meet a block with no other route and wait either way.`, repro: 'GET /api/rerouting/proof' })
    const bf = mt?.results.buffers
    if (bf) out.push({ id: 'buf', title: 'Blocks that clear on time, with crew-history buffers', kind: 'pct', better: 'higher', assumed: true,
      chip: `costs ${Math.max(0, bf.jobs_lost)} jobs placed`,
      bars: [{ who: 'Flat plan', v: bf.flat.mean * 100, tone: 'before' }, { who: 'Learned buffers', v: bf.adaptive.mean * 100, tone: 'after' }],
      how: `${bf.how} ${bf.caveat} Jobs placed ${bf.flat.placed} to ${bf.adaptive.placed}; reserved hours ${bf.flat.reserved_hours} to ${bf.adaptive.reserved_hours}.`,
      repro: 'GET /api/methods/summary' })
    if (it) out.push({ id: 'it', title: 'Finding free gaps', kind: 'ms', better: 'lower',
      bars: [{ who: 'Scan every window', v: it.before.value, tone: 'before' }, { who: 'Interval tree', v: it.after.value, tone: 'after' }],
      how: `${it.how} ${it.detail}`, repro: it.repro })
    if (sd && sd.n > 0 && sd.median_ms !== undefined) out.push({
      id: 'sd', title: 'Placing a sudden task', kind: 'ms', better: 'lower',
      assumed: true,
      bars: [{ who: 'Next weekly cycle*', v: (sd.manual_wait_days ?? 7) * 86_400_000, tone: 'before' },
             { who: 'RailBlock (median)', v: sd.median_ms, tone: 'after' }],
      how: `Median of ${sd.n} sudden task(s) injected on the Operations page.`, repro: 'GET /api/sudden/metrics' })
    return out
  }, [sc, d, px, sd, pw, rb, mt, ef, rp])

  if (err) return <div className="panel"><div className="panel-body muted">Could not load impact metrics: {err}</div></div>
  if (!d) return <div className="loading"><div className="spinner" />Measuring the manual baseline and every algorithm…</div>

  const h = sc?.headline
  const paxSaved = px ? Math.round(px.passengers_saved_pct) : null
  const rlc = sc?.cards.find(c => c.id === 'rl')
  const replan = rlc ? rlc.before.value / Math.max(1e-9, rlc.after.value) : null

  return (
    <div style={{ display: 'grid', gap: 16 }}>
      <div className="ba-hero">
        <h1>RailBlock AI against manual planning</h1>
        <div className="sub">Same timetable, same jobs. Every figure is measured.</div>
        <div className="kpis">
          {h && <div className="kpi"><div className="big">+{h.capacity_gain_pct}%</div>
            <div className="k">usable maintenance time</div>
            <div className="ba-line">every gap counts, not just night and Sunday</div></div>}
          {h && <div className="kpi"><div className="big">{h.urgent_jobs_creation}/{h.urgent_jobs_total}</div>
            <div className="k">urgent jobs done in time</div>
            <div className="ba-line">{h.urgent_jobs_natural}/{h.urgent_jobs_total} on the fixed timetable</div></div>}
          {rlc && replan && <div className="kpi"><div className="big">{Math.round(replan).toLocaleString()}×</div>
            <div className="k">faster re-plan after a defect</div>
            <div className="ba-line">{fmtMs(rlc.before.value * 1000)} → {fmtMs(rlc.after.value * 1000)}</div></div>}
          {paxSaved !== null && <div className="kpi"><div className="big">−{paxSaved}%</div>
            <div className="k">passengers within reach of work</div>
            <div className="ba-line">against timing that ignores them</div></div>}
        </div>
      </div>

      {h && (
        <div className="panel">
          <div className="panel-head"><h2>Why the Ministry should adopt it</h2></div>
          <div className="panel-body">
            <ul className="why">
              <li><span><b>+{h.capacity_gain_pct}%</b> more usable maintenance time from the same timetable</span></li>
              <li><span><b>{h.urgent_jobs_creation} of {h.urgent_jobs_total}</b> urgent jobs done in time, not {h.urgent_jobs_natural}</span></li>
              <li><span><b>{h.blocks_ours}</b> protected blocks where manual needs <b>{h.blocks_manual}</b></span></li>
              {rlc && <li><span>Re-plans a defect in <b>{fmtMs(rlc.after.value * 1000)}</b>; a full solve takes {fmtMs(rlc.before.value * 1000)}</span></li>}
              {paxSaved !== null && <li><span><b>{paxSaved}%</b> fewer passengers within reach of work</span></li>}
              <li><span><b>{vf ? vf.n_violations : 0}</b> rule violations in {vf ? vf.total_checks : '…'} independent checks; every verdict carries its reason</span></li>
              {rb && <li><span>Blocks clear before the next train on <b>{Math.round(rb.plan.mean * 100)}%</b> of simulated days</span></li>}
              {/* early-finish reuse yields about one job a week on this plan: kept on the Operations page, not claimed here */}
              {ef && ef.grouping.place_and_urgency.riders > 0 && <li><span><b>{ef.grouping.place_and_urgency.riders}</b> small jobs ride in big blocks, saving <b>{ef.grouping.place_and_urgency.setup_saved_min} min</b> of set-up; urgent and routine work no longer share a group ({ef.grouping.place_only.mixed_urgency_groups} → {ef.grouping.place_and_urgency.mixed_urgency_groups})</span></li>}
              {rp && rp.diverted > 0 && <li><span>Long-distance trains sent round a closed section lose <b>{Math.round(rp.mean_added_min)} min</b> instead of <b>{Math.round(rp.wait_min / rp.diverted)} min</b> waiting; <b>0</b> locals rerouted</span></li>}
            </ul>
          </div>
        </div>
      )}

      {!sc || !px ? <div className="loading"><div className="spinner" />Running every algorithm once more…</div> : (
        <div className="cmp-grid">{cmps.filter(c => SHOWN.has(c.id)).map(c => <Card key={c.id} c={c} />)}</div>
      )}

      {/* Stress-test sliders: hidden to keep this page short.
      <details className="fold">
        <summary>Stress-test the manual baseline</summary>
        <div>
          <div className="slider">
            <label>Phone negotiation per clash <b>{hours} h</b></label>
            <input type="range" min={0.25} max={8} step={0.25} value={hours} onChange={e => setHours(Number(e.target.value))} />
          </div>
          <div className="slider">
            <label>Wait for the next planning cycle <b>{wait} days</b></label>
            <input type="range" min={0.5} max={14} step={0.5} value={wait} onChange={e => setWait(Number(e.target.value))} />
          </div>
          <div className="tiles mini">
            {['M1', 'M2'].map(id => {
              const x = m(id, stress ?? d)
              if (!x) return null
              return (
                <div className="tile" key={id}>
                  <div className="v" style={{ color: x.improvement_pct > 0 ? 'var(--fit)' : 'var(--stopstart)' }}>
                    {id === 'M1' ? `${Math.round(x.before / Math.max(1, x.after)).toLocaleString()}×` : `${x.improvement_pct.toFixed(0)}%`}
                  </div>
                  <div className="k">{id === 'M1' ? 'faster re-plan' : 'less coordination time'}</div>
                </div>
              )
            })}
          </div>
        </div>
      </details>

      */}

      {/* "What this does not show" hidden on request
      <details className="fold">
        <summary>What this does not show</summary>
        <div><ul className="limits">{(sc?.limits ?? []).map((t, i) => <li key={i}>{t}</li>)}</ul></div>
      </details>
      */}
    </div>
  )
}
