import type { TimelineTrack } from '../api'

/* How gaps are found, drawn instead of described: each row is one physical track for the day,
   every tick is a train passing, and the bright bars are the usable gaps the engine found
   between them (after protection set-up and release time are taken off). */

const W = 320
const LABEL = 54
const ROW = 13
const GAP = 5
const DAY = 86400

const GAP_COLOR: Record<string, string> = {
  MICRO_GAP: 'var(--accent)',
  NIGHT_WINDOW: '#8b7cf6',
  MEGABLOCK: 'var(--fit)',
}

export default function GapStrip({ tracks, nowS }: { tracks: TimelineTrack[]; nowS: number }) {
  const x = (s: number) => LABEL + (s / DAY) * (W - LABEL - 4)
  const H = tracks.length * (ROW + GAP) + 16

  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img"
           aria-label="Trains and usable gaps on each track today">
        {tracks.map((t, i) => {
          const y = i * (ROW + GAP)
          return (
            <g key={t.track}>
              <text x={0} y={y + 9.5} fontSize={8.5} fill="var(--text-mute)" fontFamily="var(--mono)">
                {t.track.replace('_', ' ')}
              </text>
              <rect x={LABEL} y={y} width={W - LABEL - 4} height={ROW} rx={3} fill="var(--line-soft)" />
              {t.gaps.map(([a, b, type], k) => (
                <rect key={k} className="gap-in" x={x(a)} y={y} width={Math.max(1.5, x(b) - x(a))}
                      height={ROW} rx={2.5} fill={GAP_COLOR[type] ?? 'var(--accent)'}
                      style={{ animationDelay: `${(k % 24) * 25}ms` }} opacity={0.9} />
              ))}
              {t.trains.map((s, k) => (
                <line key={k} x1={x(s)} x2={x(s)} y1={y + 1.5} y2={y + ROW - 1.5}
                      stroke="#fff" strokeOpacity={0.4} strokeWidth={0.6} />
              ))}
            </g>
          )
        })}
        <line x1={x(nowS)} x2={x(nowS)} y1={-2} y2={H - 14} stroke="var(--sick)" strokeWidth={1.2} />
        {[0, 6, 12, 18, 24].map(h => (
          <text key={h} x={x(h * 3600)} y={H - 3} fontSize={8} fill="var(--text-mute)"
                fontFamily="var(--mono)" textAnchor={h === 24 ? 'end' : h === 0 ? 'start' : 'middle'}>
            {String(h % 24).padStart(2, '0')}
          </text>
        ))}
      </svg>
      <div className="legend" style={{ padding: '6px 0 0', border: 'none', gap: '4px 12px' }}>
        <span><i style={{ background: 'var(--accent)' }} />gap between trains</span>
        <span><i style={{ background: '#8b7cf6' }} />night</span>
        <span><i style={{ background: 'var(--fit)' }} />megablock</span>
        <span><i style={{ background: '#fff', opacity: 0.5, width: 2 }} />train</span>
      </div>
    </div>
  )
}
