import type { ChatVisual } from '../api'

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
    return <rect key={key} x={x} y={y(s)} width={Math.max(3, w - 1)} height={h} rx={2} {...style} />
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
        <rect x={L + 200} y={H - 4} width={8} height={4} fill="var(--accent)" stroke="var(--text)" /><text x={L + 211} y={H}>your block</text>
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
            <rect x={L + h.hour * bw + 1.5} y={H - B - bh} width={bw - 3} height={Math.max(1, bh)} rx={1.5} fill="var(--accent)" opacity={0.85}>
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

export default function ChatVisualView({ v }: { v: ChatVisual }) {
  return (
    <div className="cv">
      <div className="cv-title">{v.title}</div>
      {v.type === 'schedule' ? <Schedule v={v} /> : v.type === 'profile' ? <Profile v={v} /> : <Bars v={v} />}
    </div>
  )
}
