import { useEffect, useMemo, useRef, useState } from 'react'
import { api, hhmm, type ClusterTrace, type GapTrace, type ScheduleDemo } from '../api'
import RlPanel from './RlPanel'

/* The algorithms, watched. Everything on this page is replayed from a real run - the gap engine on
   one real track, the clustering on the real job pool, the scheduler on real jobs - so what the
   narration says is what the code actually computed. Press start and it walks through:

     1  find the gaps            2  open the near misses      3  group the jobs
     4  check who may share      5  give the groups a time
*/

const PALETTE = ['#0284c7', '#65a30d', '#d97706', '#dc2626', '#c026d3',
                 '#4f46e5', '#0d9488', '#ea580c', '#7c3aed', '#16a34a']
const DEPT_COLOR: Record<string, string> = { PWI: 'var(--d-pwi)', OWD: 'var(--d-owd)', S_AND_T: 'var(--d-snt)' }
const DEPT_SHORT: Record<string, string> = { PWI: 'PWI', OWD: 'OWD', S_AND_T: 'S&T' }
const STAGES = ['Find the gaps', 'Open near misses', 'Group the jobs', 'Check the rules', 'Give it a time']

type Frame = { stage: number; i: number }

/* ---- a gap, taken apart: safety, set-up and hand-back, and what is left to work in ---- */
function Anatomy({ gapMin, buffer, overhead, need }: { gapMin: number; buffer: number; overhead: number; need: number }) {
  const total = Math.max(gapMin, 2 * buffer + overhead + need, 30)
  const W = 560
  const seg = (min: number) => (min / total) * W
  const safety = Math.min(gapMin, 2 * buffer)
  const setup = Math.min(Math.max(0, gapMin - safety), overhead)
  const work = Math.max(0, gapMin - safety - setup)
  let x = 0
  const bars: { w: number; c: string; label: string }[] = []
  bars.push({ w: seg(safety), c: '#64748b', label: `${safety.toFixed(0)} safety` })
  bars.push({ w: seg(setup), c: 'var(--block)', label: `${setup.toFixed(0)} set-up + hand-back` })
  bars.push({ w: seg(work), c: work >= need ? 'var(--fit)' : 'var(--sick)', label: `${work.toFixed(0)} to work` })
  return (
    <svg viewBox={`0 0 ${W} 44`} width="100%" role="img" aria-label="A gap divided into safety, set-up and work time">
      <rect x={0} y={6} width={seg(gapMin)} height={22} rx={4} fill="none" stroke="var(--text-mute)" strokeDasharray="3 3" />
      {bars.map((b, i) => {
        const r = <g key={i}><rect x={x} y={6} width={Math.max(0, b.w)} height={22} rx={3} fill={b.c} className="gap-in" />
          {b.w > 46 && <text x={x + b.w / 2} y={21} fontSize={10} fill="#05080e" textAnchor="middle" fontWeight={650}>{b.label}</text>}</g>
        x += b.w
        return r
      })}
      <rect x={seg(2 * buffer + overhead + need)} y={2} width={1.5} height={30} fill="var(--fit)" />
      <text x={seg(2 * buffer + overhead + need) + 4} y={41} fontSize={9.5} fill="var(--fit)">{need} min of work needed</text>
      <text x={Math.min(seg(gapMin), W - 4)} y={41} fontSize={9.5} fill="var(--text-dim)" textAnchor="end">gap {gapMin.toFixed(0)} min</text>
    </svg>
  )
}

export default function AlgoLab() {
  const [gap, setGap] = useState<GapTrace | null>(null)
  const [cl, setCl] = useState<ClusterTrace | null>(null)
  const [sch, setSch] = useState<ScheduleDemo | null>(null)
  const [f, setF] = useState(-1)                 // -1 = not started
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(1600)

  useEffect(() => {
    api.explainGaps().then(setGap).catch(() => undefined)
    api.explainClusters().then(setCl).catch(() => undefined)
    api.explainSchedule().then(setSch).catch(() => undefined)
  }, [])

  const rows = useMemo(() => (gap?.rows ?? []).slice(0, 12), [gap])
  const nears = useMemo(() => (gap?.rows ?? []).filter(r => !r.keep && r.creation).slice(0, 3), [gap])
  const merges = useMemo(() => {
    if (!cl) return []
    const below = cl.merges.filter(m => m.distance_km <= cl.cut_km)
    const step = Math.max(1, Math.ceil(below.length / 18))
    const picked = below.filter((_, i) => i % step === 0 || i === below.length - 1)
    return picked.map(m => ({ ...m, idx: below.indexOf(m) + 1 }))
  }, [cl])

  const frames: Frame[] = useMemo(() => {
    const out: Frame[] = []
    rows.forEach((_, i) => out.push({ stage: 0, i }))
    ;(nears.length ? nears : [null]).forEach((_, i) => out.push({ stage: 1, i }))
    merges.forEach((_, i) => out.push({ stage: 2, i }))
    out.push({ stage: 2, i: merges.length })                       // the "stop at the cut" frame
    out.push({ stage: 3, i: 0 })
    ;(sch?.results ?? []).forEach((_, i) => out.push({ stage: 4, i }))
    return out
  }, [rows, nears, merges, sch])

  const timer = useRef<number | null>(null)
  useEffect(() => {
    if (!playing) return
    timer.current = window.setInterval(() => {
      setF(x => { if (x + 1 >= frames.length) { setPlaying(false); return x } return x + 1 })
    }, speed)
    return () => { if (timer.current) window.clearInterval(timer.current) }
  }, [playing, speed, frames.length])

  const start = () => { setF(0); setPlaying(true) }
  const cur = f >= 0 ? frames[Math.min(f, frames.length - 1)] : null
  const ready = gap && cl && sch

  /* ---------------------------------------------------------------- stage 1 and 2 stage */
  const t0 = gap ? gap.day * 86400 + gap.hour_from * 3600 : 0
  const t1 = gap ? gap.day * 86400 + gap.hour_to * 3600 : 1
  const TW = 640
  const tx = (s: number) => 8 + ((s - t0) / (t1 - t0)) * (TW - 16)

  const gapStage = () => {
    if (!gap || !cur) return null
    const shown = cur.stage === 0 ? cur.i : rows.length - 1
    const row = cur.stage === 0 ? rows[cur.i] : nears[cur.i]
    if (!row) return <div className="muted">No near misses in this window — every short gap was simply too short.</div>
    const near = cur.stage === 1
    const c = near ? row.creation : null
    const gapMin = row.gap_min
    return (
      <>
        <svg viewBox={`0 0 ${TW} 64`} width="100%" role="img" aria-label="Trains passing on one track">
          <rect x={8} y={10} width={TW - 16} height={26} rx={4} fill="var(--line-soft)" />
          {rows.slice(0, shown + 1).map((r, i) => {
            const cur1 = cur.stage === 0 && i === cur.i
            return (
              <g key={i}>
                <rect x={tx(r.prev.exit_s)} y={10} width={Math.max(1.5, tx(r.next.enter_s) - tx(r.prev.exit_s))} height={26} rx={3}
                      fill={r.keep ? 'var(--fit)' : r.creation ? 'var(--sick)' : '#64748b'}
                      opacity={cur1 ? 1 : 0.38} className={cur1 ? 'gap-in' : ''} />
                <line x1={tx(r.next.enter_s)} x2={tx(r.next.enter_s)} y1={8} y2={38} stroke="var(--text)" strokeOpacity={0.75} strokeWidth={1} />
              </g>
            )
          })}
          {c && (
            <rect x={tx(c.start_s)} y={8} width={Math.max(2, tx(c.end_s) - tx(c.start_s))} height={30} rx={4}
                  fill="none" stroke="var(--fit)" strokeWidth={2} strokeDasharray="5 3" className="gap-in" />
          )}
          {[0, 1, 2, 3, 4].map(k => {
            const s = t0 + (k * (t1 - t0)) / 4
            return <text key={k} x={tx(s)} y={56} fontSize={9.5} fill="var(--text-mute)" fontFamily="var(--mono)"
                         textAnchor={k === 0 ? 'start' : k === 4 ? 'end' : 'middle'}>{hhmm(s)}</text>
          })}
        </svg>
        <div className="k muted" style={{ fontSize: 11, margin: '12px 0 4px' }}>
          THE GAP BETWEEN {row.prev.train_id.split('+')[0]} AND {row.next.train_id.split('+')[0]}, TAKEN APART
        </div>
        <Anatomy gapMin={gapMin} buffer={gap.buffer_min} overhead={gap.overhead_min} need={gap.min_workable_min} />
        {c && (
          <>
            <div className="k muted" style={{ fontSize: 11, margin: '12px 0 4px' }}>AFTER: {c.lever_label.toUpperCase()}</div>
            <Anatomy gapMin={c.raw_min + 2 * gap.buffer_min} buffer={gap.buffer_min} overhead={gap.overhead_min} need={gap.min_workable_min} />
          </>
        )}
      </>
    )
  }

  /* -------------------------------------------------------------------- stage 3 scatter */
  const scatter = () => {
    if (!cl || !cur) return null
    const pts = cl.points
    const xs = pts.map(p => p.x_km), ys = pts.map(p => p.y_km)
    const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)]
    const SW = 640, SH = 300, P = 24
    const sx = (v: number) => P + ((v - x0) / Math.max(1e-6, x1 - x0)) * (SW - 2 * P)
    const sy = (v: number) => SH - P - ((v - y0) / Math.max(1e-6, y1 - y0)) * (SH - 2 * P)
    const upto = cur.stage > 2 ? merges.length : cur.stage === 2 ? cur.i + 1 : 0
    const doneMerges = cl.merges.filter(m => m.distance_km <= cl.cut_km)
      .slice(0, cur.stage > 2 ? 9999 : (merges[Math.min(upto, merges.length) - 1]?.idx ?? 0))
    // union-find over the merges shown so far
    const parent = pts.map((_, i) => i)
    const find = (a: number): number => (parent[a] === a ? a : (parent[a] = find(parent[a])))
    const node = new Map<number, number>()      // merge id -> a representative point
    const rep = (id: number): number => (id < pts.length ? id : node.get(id)!)
    doneMerges.forEach(m => { const a = rep(m.a), b = rep(m.b); node.set(m.id, a); parent[find(b)] = find(a) })
    const groups = new Map<number, number[]>()
    pts.forEach((_, i) => { const r = find(i); groups.set(r, [...(groups.get(r) ?? []), i]) })
    const last = doneMerges[doneMerges.length - 1]
    const lastA = last ? rep(last.a) : -1, lastB = last ? rep(last.b) : -1
    return (
      <svg viewBox={`0 0 ${SW} ${SH}`} width="100%" role="img" aria-label="Jobs by position, merging into groups">
        {[...groups.values()].filter(g => g.length > 1).map((g, i) => {
          const cx = g.reduce((s, k) => s + sx(pts[k].x_km), 0) / g.length
          const cy = g.reduce((s, k) => s + sy(pts[k].y_km), 0) / g.length
          const r = Math.max(...g.map(k => Math.hypot(sx(pts[k].x_km) - cx, sy(pts[k].y_km) - cy))) + 12
          const col = PALETTE[(pts[g[0]].cluster - 1) % PALETTE.length]
          return <circle key={i} cx={cx} cy={cy} r={r} fill={col} fillOpacity={0.13} stroke={col} strokeOpacity={0.7} className="gap-in" />
        })}
        {last && lastA >= 0 && (
          <line x1={sx(pts[lastA].x_km)} y1={sy(pts[lastA].y_km)} x2={sx(pts[lastB].x_km)} y2={sy(pts[lastB].y_km)}
                stroke="var(--text)" strokeWidth={2} strokeDasharray="4 3" />
        )}
        {pts.map((p, i) => {
          const g = groups.get(find(i))!
          return <circle key={p.id} cx={sx(p.x_km)} cy={sy(p.y_km)} r={4.6}
                         fill={g.length > 1 ? PALETTE[(p.cluster - 1) % PALETTE.length] : '#64748b'}
                         stroke={DEPT_COLOR[p.department]} strokeWidth={1.8} />
        })}
        <text x={SW - 8} y={SH - 6} fontSize={9.5} fill="var(--text-mute)" textAnchor="end">
          each dot is a job at its real position · ring colour = department
        </text>
      </svg>
    )
  }

  /* ---------------------------------------------------------------------- stage 5 view */
  const schedView = () => {
    if (!sch || !cur) return null
    const shown = sch.results.slice(0, cur.i + 1)
    const placed = sch.results.filter(r => r.start_s !== null)
    const lo = Math.min(...placed.map(r => r.start_s!)) - 1800
    const hi = Math.max(...placed.map(r => r.end_s!)) + 1800
    const SW = 640, RH = 26
    const px = (s: number) => 92 + ((s - lo) / (hi - lo)) * (SW - 100)
    return (
      <svg viewBox={`0 0 ${SW} ${sch.results.length * RH + 24}`} width="100%" role="img" aria-label="Jobs placed on a timeline">
        {sch.results.map((r, i) => {
          const y = i * RH
          const on = i <= cur.i
          return (
            <g key={r.id} opacity={on ? 1 : 0.18}>
              <text x={0} y={y + 16} fontSize={10.5} fill="var(--text-dim)" fontFamily="var(--mono)">
                {DEPT_SHORT[r.department]} {r.zone.length > 9 ? r.zone.slice(0, 9) : r.zone}
              </text>
              <rect x={92} y={y + 3} width={SW - 100} height={18} rx={4} fill="var(--line-soft)" />
              {on && r.placed && (
                <rect className="gap-in" x={px(r.start_s!)} y={y + 3} width={Math.max(3, px(r.end_s!) - px(r.start_s!))} height={18} rx={4}
                      fill={DEPT_COLOR[r.department]} stroke={r.created ? 'var(--sick)' : 'var(--panel)'}
                      strokeWidth={r.created ? 2 : r.integrated_with.length ? 1.6 : 0} strokeDasharray={r.created ? '4 3' : undefined} />
              )}
              {on && !r.placed && <text x={100} y={y + 16} fontSize={10} fill="var(--stopstart)">no gap available in time</text>}
            </g>
          )
        })}
        {[0, 1, 2, 3].map(k => {
          const s = lo + (k * (hi - lo)) / 3
          return <text key={k} x={px(s)} y={sch.results.length * RH + 16} fontSize={9.5} fill="var(--text-mute)"
                       fontFamily="var(--mono)" textAnchor="middle">{hhmm(s)}</text>
        })}
        <rect x={0} y={0} width={0} height={0} />
        {shown.length === 0 && null}
      </svg>
    )
  }

  /* ------------------------------------------------------------------------ narration */
  const narration = (): { title: string; text: React.ReactNode } => {
    if (!cur || !gap || !cl || !sch) return { title: 'Ready', text: 'Press “Start simulation”. The page will replay the real algorithms step by step, in plain words.' }
    if (cur.stage === 0) {
      const r = rows[cur.i]
      const work = r.after_buffers_min - gap.overhead_min
      return {
        title: `Looking at the gap after train ${r.prev.train_id.split('+')[0]}`,
        text: <>
          The next train arrives {r.gap_min} minutes later. Take off <b>{gap.buffer_min * 2} min</b> of safety →{' '}
          <b>{r.after_buffers_min}</b>. Take off <b>{gap.overhead_min} min</b> to set up and hand back the line →{' '}
          <b>{work >= 0 ? work.toFixed(0) : `nothing (short by ${(-work).toFixed(0)})`}</b>. {r.keep
            ? <b style={{ color: 'var(--fit)' }}>{r.usable_min} minutes of real work fit, so this gap is kept.</b>
            : <b style={{ color: r.creation ? 'var(--sick)' : 'var(--text-mute)' }}>{r.reason}</b>}
        </>,
      }
    }
    if (cur.stage === 1) {
      const r = nears[cur.i]
      if (!r?.creation) return { title: 'No near misses here', text: 'Every short gap in this window was too short to save with a small change — the engine simply leaves them.' }
      const c = r.creation
      return {
        title: 'A near miss — can a small change save it?',
        text: <>This gap was almost long enough. <b>{c.note}</b> and it becomes <b>{c.raw_min} minutes</b> — enough to work in.
          It costs <b>{c.delay_min} train-minutes</b> of delay, so it is only used when a job would otherwise wait.
          {c.lever === 'REROUTE' && <> Only long-distance and freight trains are ever rerouted — never a suburban local.</>}</>,
      }
    }
    if (cur.stage === 2) {
      if (cur.i >= merges.length) {
        const big = cl.clusters.filter(c => c.size > 1).length
        return { title: 'Stop at the limit', text: <>The next closest groups are more than <b>{cl.cut_km} km</b> apart — too far to share a block — so joining stops. <b>{cl.points.length} jobs became {big} shared groups.</b></> }
      }
      const m = merges[cur.i]
      return { title: `Joining the closest jobs (${m.idx} of ${cl.merges.filter(x => x.distance_km <= cl.cut_km).length})`,
        text: <>The two closest groups are {m.distance_km < 0.1 ? <b>at the same spot</b> : <>just <b>{m.distance_km} km</b> apart</>}, so they join into one group of <b>{m.size}</b>.
          Repeating this — always joining the closest pair — is called <b>hierarchical clustering</b>.</> }
    }
    if (cur.stage === 3) {
      const c = [...cl.clusters].sort((a, b) => b.cross_pairs - a.cross_pairs)[0]
      return { title: 'Can these jobs really share a block?', text: <>
        Being close is not enough, so the rules check every pair from different departments. In the biggest group ({c?.label}):{' '}
        <b style={{ color: 'var(--fit)' }}>{c?.compatible} pairs can share</b>, <b style={{ color: 'var(--iwp)' }}>{c?.requires_iwp} need a work permit</b>,{' '}
        <b style={{ color: 'var(--stopstart)' }}>{c?.incompatible} must be kept apart</b>. Different places = fine; same place = permit; same department = one after the other.</> }
    }
    const r = sch.results[cur.i]
    return { title: `Giving ${DEPT_SHORT[r.department]} “${r.label}” a time`, text: (
      <ol className="steps" style={{ margin: 0 }}>
        <li>A demo copy of <b>{r.from_task}</b>{r.shortened_from ? ` (shortened from ${r.shortened_from} to ${r.duration_min} min to fit the screen)` : ''}, due within 6 hours.</li>
        {r.steps.map((s, i) => <li key={i}>{s}</li>)}
        {r.placed && <li><b>{r.hhmm}</b> on {r.section_id} ({r.track}).</li>}
      </ol>) }
  }
  const nar = narration()
  const pct = f < 0 ? 0 : Math.round(((f + 1) / frames.length) * 100)

  return (
    <div style={{ display: 'grid', gap: 16 }}>
      <div className="panel">
        <div className="panel-head">
          <h2>Watch the algorithms work</h2>
          <span className="sub">replayed from real runs · a normal slow track, a few hours of one morning</span>
        </div>
        <div className="panel-body">
          <div className="lab-controls">
            <button className="action primary" disabled={!ready} onClick={start}>
              {f < 0 ? '▶ Start simulation' : '↻ Restart'}
            </button>
            {f >= 0 && (
              <>
                <button className="action" onClick={() => setPlaying(p => !p)}>{playing ? '❙❙ Pause' : '▶ Resume'}</button>
                <button className="action" onClick={() => { setPlaying(false); setF(x => Math.min(frames.length - 1, x + 1)) }}>Step ▸</button>
              </>
            )}
            <div className="speed" style={{ marginLeft: 'auto' }}>
              {([['Slow', 3200], ['Normal', 1600], ['Fast', 700]] as const).map(([n, v]) => (
                <button key={n} className={speed === v ? 'on' : ''} onClick={() => setSpeed(v)}>{n}</button>
              ))}
            </div>
          </div>

          <div className="stages">
            {STAGES.map((n, i) => (
              <div key={n} className={`stage ${cur?.stage === i ? 'on' : cur && cur.stage > i ? 'done' : ''}`}>
                <span>{cur && cur.stage > i ? '✓' : i + 1}</span>{n}
              </div>
            ))}
          </div>
          <div className="bar" style={{ marginTop: 10 }}><i style={{ width: `${pct}%`, transition: 'width .4s' }} /></div>
        </div>

        <div className="lab-grid">
          <div className="lab-stage">
            {!ready && <div className="loading"><div className="spinner" />Preparing the real run…</div>}
            {ready && !cur && (
              <div className="lab-idle">
                <div className="big">Gap finding · Job grouping · Scheduling</div>
                <p>Press start to see how the system finds the gaps between trains, groups nearby jobs, checks the rules, and gives each group a time.</p>
                <p className="muted">Track: {gap!.section_id} {gap!.track.replace('_', ' ')} · {gap!.n_trains} trains that day · {rows.length} gaps shown</p>
              </div>
            )}
            {cur && (cur.stage <= 1) && gapStage()}
            {cur && cur.stage === 2 && scatter()}
            {cur && cur.stage === 3 && scatter()}
            {cur && cur.stage === 4 && schedView()}
          </div>
          <div className="lab-say">
            <div className="k muted" style={{ fontSize: 11, marginBottom: 6 }}>IN SIMPLE WORDS</div>
            <div className="say-title">{nar.title}</div>
            <div className="say-text">{nar.text}</div>
          </div>
        </div>
      </div>

      <div>
        <div className="k muted" style={{ fontSize: 11, margin: '0 0 8px 2px' }}>
          AND WHEN A NEW DEFECT APPEARS MID-WEEK — THE LEARNED DISPATCHER
        </div>
        <RlPanel />
      </div>
    </div>
  )
}
