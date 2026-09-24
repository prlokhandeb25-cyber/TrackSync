import { useEffect, useRef, useState } from 'react'
import { api, type ChatVisual, type CrewWhatif } from '../api'

/* The small chart RailMitra draws under an answer when the answer has a shape: the week with a new
   block dropped into it (what stays, what moves, where the new block sits), or a section's trains
   through the day with the block or closure shaded. Drawn from the same numbers the answer quotes. */

const DEPT_VAR: Record<string, string> = { PWI: 'var(--d-pwi)', OWD: 'var(--d-owd)', S_AND_T: 'var(--d-snt)' }
const DAY = 86400

function Schedule({ v }: { v: Extract<ChatVisual, { type: 'schedule' }> }) {
  const W = 452, H = 196, L = 26, T = 18, colW = (W - L - 4) / 7, innerH = H - T - 6
  const y = (s: number) => T + ((s % DAY) / DAY) * innerH
  const byDay: Record<number, typeof v.blocks> = {}
  for (const b of v.blocks) (byDay[Math.floor(b.start_s / DAY)] ??= []).push(b)
  const laneOf = new Map<string, { lane: number; lanes: number }>()
  for (const list of Object.values(byDay)) {
    const sorted = [...list].sort((a, b) => a.start_s - b.start_s)
    const ends: number[] = []
    const ln = sorted.map(b => {
      let k = ends.findIndex(e => e <= b.start_s)
      if (k < 0) { k = ends.length; ends.push(0) }
      ends[k] = b.end_s
      return k
    })
    const lanes = Math.max(1, ends.length)
    sorted.forEach((b, i) => laneOf.set(b.id + b.start_s, { lane: ln[i], lanes }))
  }
  const rect = (b: typeof v.blocks[number], s: number, e: number, style: Record<string, string | number>, key: string) => {
    const day = Math.floor(s / DAY)
    const li = laneOf.get(b.id + b.start_s) ?? { lane: 0, lanes: 1 }
    const w = (colW - 4) / li.lanes
    const x = L + (day % 7) * colW + 2 + li.lane * w
    const h = Math.max(3, Math.min(((e - s) / DAY) * innerH, T + innerH - y(s)))
    return <rect key={key} className="cv-blk" x={x} y={y(s)} width={Math.max(3, w - 1)} height={h} rx={2} {...style} />
  }
  const order = { stay: 0, dropped: 1, moved: 2, new: 3 } as Record<string, number>
  const blocks = [...v.blocks].sort((a, b) => order[a.kind] - order[b.kind])
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={v.title}>
      {[0, 6, 12, 18, 24].map(h => (
        <g key={h}>
          <line x1={L} x2={W - 4} y1={T + (h / 24) * innerH} y2={T + (h / 24) * innerH} stroke="var(--line-soft)" />
          <text x={L - 4} y={T + (h / 24) * innerH + 3} fontSize={8.5} textAnchor="end" fill="var(--text-mute)" fontFamily="var(--mono)">{String(h % 24).padStart(2, '0')}</text>
        </g>
      ))}
      {v.days.map((d, i) => (
        <text key={d} x={L + i * colW + colW / 2} y={11} fontSize={9} textAnchor="middle" fill="var(--text-dim)">{d.split(' ')[0]} {d.split(' ')[1]}</text>
      ))}
      {blocks.map((b, i) => {
        const fill = DEPT_VAR[b.dept] ?? 'var(--text-mute)'
        if (b.kind === 'stay') return rect(b, b.start_s, b.end_s, { fill, opacity: 0.32 }, `s${i}`)
        if (b.kind === 'dropped') return rect(b, b.start_s, b.end_s, { fill: 'none', stroke: 'var(--stopstart)', strokeDasharray: '2 2' }, `d${i}`)
        if (b.kind === 'moved') return (
          <g key={`m${i}`}>
            {b.from && rect(b, b.from.start_s, b.from.end_s, { fill: 'none', stroke: 'var(--amber)', strokeDasharray: '3 2', strokeWidth: 1 }, `f${i}`)}
            {rect(b, b.start_s, b.end_s, { fill: 'var(--amber)', opacity: 0.95 }, `mm${i}`)}
          </g>
        )
        return <g key={`n${i}`}>{rect(b, b.start_s, b.end_s, { fill: 'var(--accent)', stroke: 'var(--text)', strokeWidth: 1.4 }, `nn${i}`)}</g>
      })}
      <g fontSize={9} fill="var(--text-dim)">
        <rect x={L} y={H - 4} width={8} height={4} fill="var(--text-mute)" opacity={0.4} /><text x={L + 11} y={H}>unchanged</text>
        <rect x={L + 70} y={H - 4} width={8} height={4} fill="var(--amber)" /><text x={L + 81} y={H}>moved</text>
        <rect x={L + 120} y={H - 4} width={8} height={4} fill="none" stroke="var(--amber)" strokeDasharray="2 1" /><text x={L + 131} y={H}>where it was</text>
        <rect x={L + 200} y={H - 4} width={8} height={4} fill="var(--accent)" stroke="var(--text)" /><text x={L + 211} y={H}>{v.legend?.new ?? 'your block'}</text>
      </g>
    </svg>
  )
}

function Profile({ v }: { v: Extract<ChatVisual, { type: 'profile' }> }) {
  const W = 452, H = 130, L = 8, T = 16, B = 22
  const max = Math.max(1, ...v.hours.map(h => h.value))
  const bw = (W - L * 2) / 24
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={v.title}>
      {v.highlight && (
        <rect x={L + v.highlight[0] * bw} y={T - 4} width={Math.max(bw * 0.6, (v.highlight[1] - v.highlight[0]) * bw)}
              height={H - T - B + 4} fill="var(--amber)" opacity={0.28} rx={2} />
      )}
      {v.hours.map(h => {
        const bh = (h.value / max) * (H - T - B)
        return (
          <g key={h.hour}>
            <rect className="cv-col" x={L + h.hour * bw + 1.5} y={H - B - bh} width={bw - 3} height={Math.max(1, bh)} rx={1.5} fill="var(--accent)" opacity={0.85} style={{ animationDelay: `${h.hour * 18}ms` }}>
              <title>{`${String(h.hour).padStart(2, '0')}:00 · ${h.value} trains · ~${h.passengers.toLocaleString()} passengers`}</title>
            </rect>
          </g>
        )
      })}
      {[0, 6, 12, 18].map(h => (
        <text key={h} x={L + h * bw + bw / 2} y={H - 8} fontSize={9} textAnchor="middle" fill="var(--text-mute)" fontFamily="var(--mono)">{String(h).padStart(2, '0')}:00</text>
      ))}
      <text x={W - L} y={10} fontSize={9} textAnchor="end" fill="var(--text-mute)">{v.day} · peak {max} trains/h</text>
    </svg>
  )
}

function Bars({ v }: { v: Extract<ChatVisual, { type: 'bars' }> }) {
  const max = Math.max(1, ...v.items.map(i => i.value))
  return (
    <div className="cv-bars">
      {v.items.map(i => (
        <div key={i.label} className="cvb-row">
          <span className="cvb-l">{i.label}</span>
          <div className="cvb-t"><i style={{ width: `${Math.max(2, (i.value / max) * 100)}%`, background: i.best ? 'var(--fit)' : 'var(--text-mute)' }} /></div>
          <span className="cvb-v" style={{ color: i.best ? 'var(--fit)' : undefined }}>{i.value.toLocaleString()}</span>
        </div>
      ))}
    </div>
  )
}

const PALETTE = ['#0284c7', '#65a30d', '#d97706', '#dc2626', '#c026d3', '#4f46e5', '#0d9488', '#ea580c', '#7c3aed', '#16a34a']

/* A closed section with the long way round drawn beside it; a marker travels the detour. */
function Route({ v }: { v: Extract<ChatVisual, { type: 'route' }> }) {
  const W = 452, H = 170, P = 26
  const pts = [v.closed.from, v.closed.to, ...v.detour]
  const lat0 = Math.min(...pts.map(p => p[0])), lat1 = Math.max(...pts.map(p => p[0]))
  const lon0 = Math.min(...pts.map(p => p[1])), lon1 = Math.max(...pts.map(p => p[1]))
  const k = Math.cos(((lat0 + lat1) / 2) * Math.PI / 180)
  const dx = Math.max(1e-4, (lon1 - lon0) * k), dy = Math.max(1e-4, lat1 - lat0)
  const sc = Math.min((W - 2 * P) / dx, (H - 2 * P) / dy)
  const ox = (W - dx * sc) / 2, oy = (H - dy * sc) / 2
  const pj = (p: [number, number]): [number, number] => [ox + (p[1] - lon0) * k * sc, H - oy - (p[0] - lat0) * sc]
  const a = pj(v.closed.from), b = pj(v.closed.to)
  const path = 'M ' + v.detour.map(pj).map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' L ')
  const mid: [number, number] = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={v.title} className="cv-route">
      <rect x={0} y={0} width={W} height={H} rx={6} fill="var(--panel-2)" />
      <line x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} stroke="var(--text-mute)" strokeWidth={5} strokeDasharray="2 6" strokeLinecap="round" />
      <g transform={`translate(${mid[0]},${mid[1]})`}>
        <circle r={8} fill="var(--panel)" stroke="var(--stopstart)" strokeWidth={1.4} />
        <path d="M-3.4 -3.4L3.4 3.4M3.4 -3.4L-3.4 3.4" stroke="var(--stopstart)" strokeWidth={1.8} strokeLinecap="round" />
      </g>
      <path d={path} fill="none" stroke="#0891b2" strokeWidth={9} strokeOpacity={0.16} strokeLinecap="round" strokeLinejoin="round" />
      <path className="cv-detour" d={path} fill="none" stroke="#0891b2" strokeWidth={2.6} strokeDasharray="7 5" strokeLinecap="round" strokeLinejoin="round" />
      <g>
        <animateMotion path={path} dur="4.5s" repeatCount="indefinite" rotate="auto" />
        <circle r={9} fill="#0891b2" fillOpacity={0.25} />
        <circle r={5} fill="#0891b2" stroke="#fff" strokeWidth={1.5} />
      </g>
      {[v.closed.from, v.closed.to].map((p, i) => {
        const [x, y] = pj(p)
        return (
          <g key={i}>
            <circle cx={x} cy={y} r={4.5} fill="var(--panel)" stroke="var(--text)" strokeWidth={1.6} />
            <text x={x + (i === 0 ? -9 : 9)} y={y + 3.5} fontSize={9.5} textAnchor={i === 0 ? 'end' : 'start'} fill="var(--text)" fontWeight={600}>{v.closed.names[i]}</text>
          </g>
        )
      })}
      <g fontSize={9} fill="var(--text-dim)">
        <line x1={P} x2={P + 16} y1={H - 10} y2={H - 10} stroke="var(--text-mute)" strokeWidth={3} strokeDasharray="2 4" /><text x={P + 21} y={H - 7}>closed section</text>
        <line x1={P + 110} x2={P + 126} y1={H - 10} y2={H - 10} stroke="#0891b2" strokeWidth={2.4} strokeDasharray="5 3" /><text x={P + 131} y={H - 7}>the long way round</text>
      </g>
    </svg>
  )
}

const CLS_COL: Record<string, string> = { SUBURBAN_LOCAL: '#64748b', INTERCITY: '#f59e0b', FREIGHT_MAIL: '#92400e' }

/* A day on one section: each track as a line, trains as bars, the free gaps between them, the asked-about slot outlined. */
function DayStrip({ v }: { v: Extract<ChatVisual, { type: 'daystrip' }> }) {
  const W = 452, L = 46, T = 18, rowH = 22, H = T + v.tracks.length * rowH + 24
  const x = (s: number) => L + (s / DAY) * (W - L - 6)
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={v.title}>
      {[0, 6, 12, 18, 24].map(h => (
        <g key={h}><line x1={x(h * 3600)} x2={x(h * 3600)} y1={T - 4} y2={H - 16} stroke="var(--line-soft)" />
          <text x={x(h * 3600)} y={H - 4} fontSize={9} textAnchor="middle" fill="var(--text-mute)" fontFamily="var(--mono)">{String(h % 24).padStart(2, '0')}:00</text></g>
      ))}
      {v.tracks.map((t, i) => (
        <g key={t.track}>
          <text x={L - 6} y={T + i * rowH + 13} fontSize={8.5} textAnchor="end" fill="var(--text-dim)">{t.track.replace('_', ' ')}</text>
          <rect x={L} y={T + i * rowH + 3} width={W - L - 6} height={rowH - 8} rx={3} fill="var(--fit)" opacity={0.16} />
          {t.trains.map(([a, b, c], k) => (
            <rect key={k} className="cv-blk" x={x(a)} y={T + i * rowH + 3} width={Math.max(1.6, x(b) - x(a))} height={rowH - 8} rx={1}
                  fill={CLS_COL[c] ?? '#64748b'} style={{ animationDelay: `${Math.min(500, k * 6)}ms` }} />
          ))}
        </g>
      ))}
      <rect className="cv-grow" x={x(v.range[0])} y={T - 3} width={Math.max(3, x(v.range[1]) - x(v.range[0]))} height={v.tracks.length * rowH + 2}
            fill="var(--accent)" fillOpacity={0.14} stroke="var(--accent)" strokeWidth={1.4} rx={3} />
      <g fontSize={9} fill="var(--text-dim)"><rect x={L} y={4} width={8} height={5} fill="var(--fit)" opacity={0.5} /><text x={L + 11} y={10}>free</text>
        <rect x={L + 44} y={4} width={8} height={5} fill="#64748b" /><text x={L + 55} y={10}>train</text>
        <rect x={L + 92} y={4} width={8} height={5} fill="none" stroke="var(--accent)" /><text x={L + 103} y={10}>your slot</text></g>
    </svg>
  )
}

/* Two jobs and the rule engine's verdict between them. */
function Verdict({ v }: { v: Extract<ChatVisual, { type: 'verdict' }> }) {
  const col = v.verdict === 'COMPATIBLE' ? 'var(--fit)' : v.verdict === 'REQUIRES_IWP' ? 'var(--amber)' : 'var(--stopstart)'
  const word = v.verdict === 'COMPATIBLE' ? 'can share' : v.verdict === 'REQUIRES_IWP' ? 'only with a joint permit' : 'must be apart'
  const dc: Record<string, string> = { PWI: 'var(--d-pwi)', OWD: 'var(--d-owd)', S_AND_T: 'var(--d-snt)' }
  return (
    <div className="cv-verdict">
      <div className="cvv-box" style={{ borderColor: dc[v.a.dept] }}><b>{v.a.label}</b><span>{v.a.dept.replace('S_AND_T', 'S&T')}</span></div>
      <div className="cvv-link" style={{ color: col }}>
        <svg viewBox="0 0 90 22" width="90" height="22"><line className="cv-grow" x1={2} y1={11} x2={88} y2={11} stroke={col} strokeWidth={3}
             strokeDasharray={v.verdict === 'INCOMPATIBLE' ? '6 5' : v.verdict === 'REQUIRES_IWP' ? '2 4' : '0'} strokeLinecap="round" />
          {v.verdict === 'INCOMPATIBLE' && <path d="M40 5l10 12M50 5l-10 12" stroke={col} strokeWidth={2.4} strokeLinecap="round" />}</svg>
        <em>{word}</em>
      </div>
      <div className="cvv-box" style={{ borderColor: dc[v.b.dept] }}><b>{v.b.label}</b><span>{v.b.dept.replace('S_AND_T', 'S&T')}</span></div>
    </div>
  )
}

/* Try a scenario from any department: pick the kind of work, its length, and slide the number of workers or machines.
   The numbers come from the same model as the written answer. */
function Crew({ v }: { v: Extract<ChatVisual, { type: 'crew' }> }) {
  const first = v.scenarios.find(x => x.task_type === v.task_type)
  const [dept, setDept] = useState(first?.department ?? 'PWI')
  const [type, setType] = useState(v.task_type)
  const [dur, setDur] = useState(v.duration_min)
  const [n, setN] = useState<number | null>(v.workers)
  const [m, setM] = useState<number | null>(v.machines || null)
  const [d, setD] = useState<CrewWhatif | null>(null)
  const seq = useRef(0)
  useEffect(() => {
    const id = ++seq.current
    const t = setTimeout(() => api.resourcesWhatif(type, dur, n, m)
      .then(r => { if (seq.current === id) setD(r) }).catch(() => undefined), 120)
    return () => clearTimeout(t)
  }, [n, m, type, dur])
  const list = v.scenarios.filter(x => x.department === dept)
  const depts = [...new Map(v.scenarios.map(x => [x.department, x.dept_title])).entries()]
  const b = d?.base, x = d?.new
  const normN = b?.norm_workers ?? v.norm_workers, normM = b?.norm_machines ?? 0
  const curN = n ?? normN
  const dt = b && x ? x.work_min - b.work_min : 0
  const dc = b && x ? x.cost.total - b.cost.total : 0
  const W = 452, H = 84, L = 6
  const curve = d?.curve ?? []
  const maxW = 3 * normN
  const mx = Math.max(1, ...curve.map(c => c.work_min))
  const px = (w: number) => L + ((w - 1) / Math.max(1, maxW - 1)) * (W - 2 * L)
  const py = (mm: number) => 8 + (1 - mm / mx) * (H - 20)
  const path = curve.map((c, i) => `${i ? 'L' : 'M'}${px(c.workers).toFixed(1)},${py(c.work_min).toFixed(1)}`).join(' ')
  const money = (r: number) => `₹${Math.round(r).toLocaleString()}`
  const sc = v.scenarios.find(y => y.task_type === type)
  const pick = (t: string) => {
    const s2 = v.scenarios.find(y => y.task_type === t)
    setType(t); setN(null); setM(null); if (s2) setDur(s2.default_min)
  }
  return (
    <div className="cv-crew">
      <div className="cvc-tabs">
        {depts.map(([k, label]) => (
          <button key={k} className={dept === k ? 'on' : ''} onClick={() => { setDept(k); const f = v.scenarios.find(y => y.department === k); if (f) pick(f.task_type) }}>{label}</button>
        ))}
      </div>
      <div className="cvc-chips">
        {list.map(y => <button key={y.task_type} className={type === y.task_type ? 'on' : ''} onClick={() => pick(y.task_type)}>{y.label}</button>)}
      </div>
      <div className="cvc-sliders">
        <label><span>Length of the job <b>{dur} min</b></span>
          <input type="range" min={15} max={480} step={15} value={dur} onChange={e => { setDur(Number(e.target.value)); setN(null); setM(null) }} aria-label="Length of the job in minutes" /></label>
        <label><span>Workers <b>{curN}</b><i className="muted"> (usual {normN})</i></span>
          <input type="range" min={1} max={maxW} value={curN} onChange={e => setN(Number(e.target.value))} aria-label="Number of workers" /></label>
        {normM > 0 && (
          <label><span>{b?.machine_names[0] ?? 'Machines'} <b>{m ?? normM}</b><i className="muted"> (usual {normM})</i></span>
            <input type="range" min={1} max={4} value={m ?? normM} onChange={e => setM(Number(e.target.value))} aria-label="Number of machines" /></label>
        )}
        <button className="link" onClick={() => { setN(null); setM(null) }}>back to the usual crew</button>
      </div>
      {x && b && (
        <div className="cvc-out">
          <div className="cvc-t"><b>{x.work_min}</b> min of work<em className={dt < 0 ? 'good' : dt > 0 ? 'bad' : ''}>{dt === 0 ? 'as usual' : `${dt < 0 ? '' : '+'}${dt} min`}</em></div>
          <div className="cvc-t"><b>{x.block_min}</b> min on the track<em>{x.overhead_min} min set-up and hand-back</em></div>
          <div className="cvc-t"><b>{money(x.cost.total)}</b> cost<em className={dc < 0 ? 'good' : dc > 0 ? 'bad' : ''}>{dc === 0 ? 'as usual' : `${dc < 0 ? '−' : '+'}${money(Math.abs(dc))}`}</em></div>
          <div className="cvc-t"><b>{x.people}</b> people on site<em>{x.person_hours} person-hours</em></div>
        </div>
      )}
      {d && (
        <div className="cvc-bill">
          <b>{sc?.label ?? d.estimate.label}</b>: {d.estimate.roles.map(r => `${r.n} ${r.role.toLowerCase()}`).join(', ')}.
          <span> Bring {d.estimate.equipment.join(', ').toLowerCase()}.</span>
          {d.estimate.power_block && <span> Needs a power block.</span>}
        </div>
      )}
      {curve.length > 1 && (
        <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="Work time against crew size">
          <path d={path} fill="none" stroke="var(--accent)" strokeWidth={2.2} strokeLinejoin="round" opacity={0.85} />
          {d && <line x1={px(d.cap_workers)} x2={px(d.cap_workers)} y1={6} y2={H - 12} stroke="var(--line)" strokeDasharray="3 3" />}
          {d && <text x={px(d.cap_workers) + 4} y={16} fontSize={8.5} fill="var(--text-mute)">no faster beyond here</text>}
          <circle cx={px(curN)} cy={py(curve.find(c => c.workers === curN)?.work_min ?? 0)} r={5} fill="var(--accent)" stroke="var(--panel)" strokeWidth={1.6} />
          <text x={L} y={H - 2} fontSize={9} fill="var(--text-mute)">1 worker</text>
          <text x={W - L} y={H - 2} fontSize={9} textAnchor="end" fill="var(--text-mute)">{maxW} workers</text>
        </svg>
      )}
    </div>
  )
}

const DEPT_C: Record<string, string> = { PWI: 'var(--d-pwi)', OWD: 'var(--d-owd)', S_AND_T: 'var(--d-snt)' }

/* The jobs themselves: who, what, where, when, and how urgent, each on its own 24-hour line. */
function Tasks({ v }: { v: Extract<ChatVisual, { type: 'tasks' }> }) {
  const hh = (s: number) => `${String(Math.floor((s % DAY) / 3600)).padStart(2, '0')}:${String(Math.floor((s % 3600) / 60)).padStart(2, '0')}`
  const DN = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
  return (
    <div className="cv-tasks">
      {v.rows.map((r, i) => (
        <div key={r.id + i} className="cvt-row" style={{ animationDelay: `${i * 40}ms` }}>
          <i className="cvt-dot" style={{ background: DEPT_C[r.dept] ?? 'var(--text-mute)' }} />
          <div className="cvt-main">
            <b>{r.label}</b> <span className="mono muted">{r.zone}</span>
            <div className="cvt-track"><i style={{ left: `${((r.start_s % DAY) / DAY) * 100}%`, width: `${Math.max(1.5, ((r.end_s - r.start_s) / DAY) * 100)}%`, background: DEPT_C[r.dept] }} /></div>
          </div>
          <div className="cvt-when">{DN[Math.floor(r.start_s / DAY) % 7]} {hh(r.start_s)}–{hh(r.end_s)}<span className={`cvt-p p${r.priority}`}>P{r.priority}</span></div>
        </div>
      ))}
    </div>
  )
}

/* One block: planned length, the time it really took, and the small jobs that fill what was left. */
function BlockBar({ v }: { v: Extract<ChatVisual, { type: 'blockbar' }> }) {
  const W = 452, H = 84, L = 8, bw = W - 2 * L
  const px = (m: number) => (m / v.planned_min) * bw
  let x = L + px(v.actual_min)
  const palette = ['#0284c7', '#65a30d', '#d97706', '#c026d3']
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={v.title}>
      <rect x={L} y={16} width={bw} height={26} rx={5} fill="var(--panel-3)" stroke="var(--line)" strokeDasharray="4 3" />
      <rect className="cv-grow" x={L} y={16} width={px(v.actual_min)} height={26} rx={5} fill="var(--accent)" />
      <text x={L + 8} y={33} fontSize={10.5} fill="var(--on-accent)" fontWeight={600}>the planned work, done in {Math.round(v.actual_min / 6) / 10} h</text>
      {v.jobs.map((j, i) => {
        const w = Math.max(6, px(j.min)); const x0 = x; x += w
        return (
          <g key={i} className="cv-blk" style={{ animationDelay: `${300 + i * 200}ms` }}>
            <rect x={x0} y={16} width={w - 1.5} height={26} rx={4} fill={palette[i % palette.length]} />
            <text x={x0 + 4} y={33} fontSize={9} fill="#fff" fontWeight={600}>{j.min}m</text>
          </g>
        )
      })}
      <text x={L} y={62} fontSize={9.5} fill="var(--text-dim)">planned {Math.round(v.planned_min / 6) / 10} h</text>
      <text x={W - L} y={62} fontSize={9.5} textAnchor="end" fill="var(--text-dim)">
        {v.jobs.length ? v.jobs.map(j => j.label.toLowerCase()).join(' · ').slice(0, 70) : 'nothing waiting fits: handed back to the trains'}
      </text>
    </svg>
  )
}

/* Jobs by position (km), coloured by group; a ring marks a K-Medoids centre job. */
function Scatter({ v }: { v: Extract<ChatVisual, { type: 'scatter' }> }) {
  const W = 220, H = 150, P = 12
  const mx = Math.max(1, ...v.points.map(p => p.x)), my = Math.max(1, ...v.points.map(p => p.y))
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={v.title}>
      <rect x={0} y={0} width={W} height={H} rx={5} fill="var(--panel-2)" />
      {v.points.map((p, i) => {
        const x = P + (p.x / mx) * (W - 2 * P), y = H - P - (p.y / my) * (H - 2 * P)
        const c = PALETTE[(p.g - 1) % PALETTE.length]
        return (
          <g key={i} className="cv-pt" style={{ animationDelay: `${Math.min(600, i * 12)}ms` }}>
            {p.medoid && <circle cx={x} cy={y} r={7} fill="none" stroke={c} strokeWidth={1.6} />}
            <circle cx={x} cy={y} r={3.2} fill={c} />
          </g>
        )
      })}
    </svg>
  )
}

export default function ChatVisualView({ v }: { v: ChatVisual }) {
  return (
    <div className="cv">
      <div className="cv-title">{v.title}</div>
      {v.type === 'schedule' ? <Schedule v={v} /> : v.type === 'profile' ? <Profile v={v} />
        : v.type === 'route' ? <Route v={v} /> : v.type === 'scatter' ? <Scatter v={v} /> : v.type === 'crew' ? <Crew v={v} /> : v.type === 'verdict' ? <Verdict v={v} /> : v.type === 'daystrip' ? <DayStrip v={v} /> : v.type === 'tasks' ? <Tasks v={v} /> : v.type === 'blockbar' ? <BlockBar v={v} /> : <Bars v={v} />}
    </div>
  )
}
