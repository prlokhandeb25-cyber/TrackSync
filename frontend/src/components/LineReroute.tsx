import type { RerouteBlock } from '../api'
import { hhmm } from '../api'
import { laneList } from './NetworkMap'

/* One closed line of a section, and what happens to the trains that were due on it. Only that line is shut: trains on
   the other lines run as normal. Each affected train changes over to the best open line at the section's ends
   (single-line working for locals, the same-direction slow line for a long-distance train when the closed line is
   a fast one) with the delay it would really wait for a gap, or takes an alternate route if that costs less. Locals
   are never sent on an alternate route. The drawing runs on the simulation clock, so it moves with the map. */

const name = (t: string) => t.replace('_', ' ').toLowerCase()
const CLS: Record<string, string> = { SUBURBAN_LOCAL: 'local', INTERCITY: 'intercity', FREIGHT_MAIL: 'freight' }
const CLS_COLOR: Record<string, string> = { SUBURBAN_LOCAL: '#111827', INTERCITY: '#f59e0b', FREIGHT_MAIL: '#92400e' }

export default function LineReroute({ block, tracks, clockS, onWatch }: {
  block: RerouteBlock; tracks: string[]; clockS: number; onWatch?: () => void
}) {
  const swap = block.track_swap
  const blocked = block.track ?? swap?.blocked_track ?? null
  if (!blocked) return null
  const lanes = laneList(tracks)
  const W = 320, X0 = 26, X1 = W - 26, LH = 22, H = 16 + lanes.length * LH
  const y = (tr: string) => 14 + lanes.indexOf(tr) * LH + LH / 2
  const trainsSw = swap?.trains ?? []
  const detours = block.reroutes.filter(r => r.track === blocked || r.track === undefined)
  const state = (t: { enter_s: number; exit_s: number; delay_min: number }) =>
    clockS < t.enter_s ? 'due' : clockS <= t.exit_s + t.delay_min * 60 ? 'now' : 'done'
  const nowN = trainsSw.filter(t => state(t) === 'now').length
  const next = trainsSw.filter(t => state(t) === 'due').sort((a, b) => a.enter_s - b.enter_s)[0]
  const dot = (t: (typeof trainsSw)[number]) => {
    const start = t.enter_s + t.delay_min * 60
    const dur = Math.max(60, t.exit_s - t.enter_s)
    if (clockS < t.enter_s || clockS > start + dur) return null
    const waiting = clockS < start
    const f = waiting ? 0 : Math.min(1, (clockS - start) / dur)
    const fwd = (t as { fwd?: boolean }).fwd !== false
    const x = X0 + (fwd ? f : 1 - f) * (X1 - X0)
    const yb = y(blocked), ys = y(t.to)
    const k = waiting ? 0 : f < 0.12 ? f / 0.12 : f > 0.88 ? (1 - f) / 0.12 : 1        // change over, run, change back
    return { x, y: yb + (ys - yb) * k, waiting }
  }
  return (
    <div className="lr-box">
      <div className="lr-head">
        <b>{name(blocked)} line closed</b>
        <span className="muted">{hhmm(block.start_s)}–{hhmm(block.end_s)} · the other {lanes.length - 1} line{lanes.length > 2 ? 's' : ''} keep running</span>
        {onWatch && <button className="action" onClick={onWatch}>Watch on map</button>}
      </div>

      <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ maxHeight: 130 }} role="img" aria-label={`${name(blocked)} closed; trains change over to ${swap ? name(swap.swap_to_track) : 'other lines'}`}>
        {lanes.map(tr => (
          <g key={tr}>
            <line x1={X0} x2={X1} y1={y(tr)} y2={y(tr)} stroke={tr === blocked ? '#f59e0b' : tr === swap?.swap_to_track ? '#22c55e' : 'var(--line)'}
                  strokeWidth={tr === blocked || tr === swap?.swap_to_track ? 4 : 2.4} strokeDasharray={tr === blocked ? '6 4' : tr === swap?.swap_to_track ? '9 5' : undefined}>
              {(tr === blocked || tr === swap?.swap_to_track) && <animate attributeName="stroke-dashoffset" from="20" to="0" dur={tr === blocked ? '0.8s' : '1.2s'} repeatCount="indefinite" />}
            </line>
            <text x={2} y={y(tr) + 3} fontSize={7.5} fill="var(--text-mute)">{tr.replace('_SLOW', ' S').replace('_FAST', ' F')}</text>
          </g>
        ))}
        {swap && [0, 1].map(e => {
          const xa = e === 0 ? X0 : X1 - 14, xb = e === 0 ? X0 + 14 : X1
          return <line key={e} x1={e === 0 ? xa : xb} y1={e === 0 ? y(blocked) : y(swap.swap_to_track)} x2={e === 0 ? xb : xa}
                       y2={e === 0 ? y(swap.swap_to_track) : y(blocked)} stroke="#22c55e" strokeWidth={2} />
        })}
        {trainsSw.map(t => {
          const d = dot(t)
          if (!d) return null
          return (
            <g key={t.train_id} transform={`translate(${d.x},${d.y})`}>
              {d.waiting && <circle r={7} fill="none" stroke="#f59e0b" strokeWidth={1.5}><animate attributeName="r" values="4;9" dur="1s" repeatCount="indefinite" /><animate attributeName="opacity" values="1;0" dur="1s" repeatCount="indefinite" /></circle>}
              <circle r={t.cls === 'SUBURBAN_LOCAL' ? 3.6 : 4.8} fill={CLS_COLOR[t.cls] ?? '#111827'} stroke="#fff" strokeWidth={1.2} />
            </g>
          )
        })}
      </svg>

      <div className="lr-chips">
        {swap && <span className="lr-chip ok"><b>{swap.n_trains}</b> train{swap.n_trains === 1 ? '' : 's'} → {name(swap.swap_to_track)} ({swap.mode === 'single_line' ? 'single-line working' : 'same direction'})</span>}
        {swap && <span className="lr-chip">mean wait <b>{swap.mean_delay_min} min</b> · worst <b>{swap.max_delay_min} min</b></span>}
        {detours.length > 0 && <span className="lr-chip alt"><b>{detours.length}</b> long-distance train{detours.length === 1 ? '' : 's'} take an alternate route</span>}
        {!swap && block.locals_in_window > 0 && <span className="lr-chip bad">{block.locals_in_window} locals hold: no line to change over to for a block this long</span>}
        {nowN > 0 ? <span className="lr-chip now">{nowN} changing over now</span>
          : next ? <span className="lr-chip">next train due at {hhmm(next.enter_s)}</span> : null}
      </div>

      {(trainsSw.length > 0 || detours.length > 0) && (
        <table className="lr-table">
          <thead><tr><th>Train</th><th>Due</th><th>What happens</th><th>Extra wait</th></tr></thead>
          <tbody>
            {trainsSw.slice(0, 8).map(t => {
              const alt = t.options.find(o => o.kind === 'detour')
              return (
                <tr key={t.train_id} className={state(t) === 'now' ? 'on' : state(t) === 'done' ? 'done' : ''}>
                  <td><i className="lr-dot" style={{ background: CLS_COLOR[t.cls] }} />{t.name.replace(/�/g, '-').replace(/ Local$/, '').slice(0, 34)}<span className="muted"> {CLS[t.cls]}</span></td>
                  <td className="mono">{hhmm(t.enter_s)}</td>
                  <td>changes to <b>{name(t.to)}</b></td>
                  <td className="mono"><b>+{t.delay_min} min</b>{alt && <span className="muted"> (route: +{alt.delay_min})</span>}</td>
                </tr>
              )
            })}
            {detours.map(r => {
              const sw = r.options?.find(o => o.kind === 'swap')
              return (
                <tr key={r.train_id} className={r.enter_s !== undefined && clockS >= r.enter_s ? 'on' : ''}>
                  <td><i className="lr-dot" style={{ background: '#0891b2' }} />{(r.train_name || r.train_id).replace(/�/g, '-').slice(0, 26)}<span className="muted"> through</span></td>
                  <td className="mono">{r.enter_s !== undefined ? hhmm(r.enter_s) : ''}</td>
                  <td>alternate route via <b>{r.sections.length}</b> sections</td>
                  <td className="mono"><b>+{Math.round(r.added_delay_min)} min</b>{sw && <span className="muted"> (line: +{sw.delay_min})</span>}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
      {trainsSw.length > 8 && <div className="hint keep">and {trainsSw.length - 8} more trains, the same way</div>}
      <div className="hint keep">Waits are measured against the open line's own trains (opposite-direction trains must clear first; same-direction trains keep 2 minutes apart). Locals are never sent on an alternate route.</div>
    </div>
  )
}
