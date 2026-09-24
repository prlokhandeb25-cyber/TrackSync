import { useEffect, useState } from 'react'
import { api, DAYS, hhmm, type EfficiencyData, type ResourceEstimate } from '../api'
import { Num } from './Viz'
import type { FocusReq } from './NetworkMap'

/* Network efficiency: three ways time and effort are given back, each measured, plus what a job needs on
   site. Headline tiles up top; the "how" lives behind the title. */

const TYPES: [string, string][] = [
  ['PWI_TAMPING', 'Track tamping'], ['PWI_RAIL_RENEWAL', 'Rail / weld renewal'], ['PWI_JOINT', 'Joint attention'],
  ['OWD_INSULATOR', 'Insulator replacement'], ['OWD_MAST', 'Mast attention'], ['SNT_POINT_MACHINE', 'Point machine servicing'],
  ['SNT_TRACK_CIRCUIT', 'Track circuit fault'], ['SNT_INTERLOCK', 'Interlocking testing'],
]

function Needs() {
  const [type, setType] = useState('PWI_TAMPING')
  const [dur, setDur] = useState(120)
  const [e, setE] = useState<ResourceEstimate | null>(null)
  useEffect(() => { const t = setTimeout(() => api.resources(type, dur).then(setE).catch(() => undefined), 200); return () => clearTimeout(t) }, [type, dur])
  return (
    <div className="needs">
      <div className="needs-pick">
        <select value={type} onChange={x => setType(x.target.value)} aria-label="Kind of work">{TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
        <label>for <input type="number" min={15} max={720} step={15} value={dur} onChange={x => setDur(Number(x.target.value) || 60)} /> min</label>
      </div>
      {e && (
        <div className="needs-body">
          <div className="needs-big"><b><Num v={e.people_per_shift} /></b> people{e.shifts > 1 ? ` per shift · ${e.shifts} shifts` : ''}</div>
          <div className="needs-roles">{e.roles.map(r => <span key={r.role} className="chip"><b>{r.n}</b> {r.role}</span>)}</div>
          <div className="needs-line"><span>Bring</span> {e.equipment.join(', ')}</div>
          {e.materials.length > 0 && <div className="needs-line"><span>Have ready</span> {e.materials.join(', ')}</div>}
          <div className="hint">Typical planning norms scaled by job length, not a measured prediction (A-052).</div>
        </div>
      )}
    </div>
  )
}

export default function EfficiencyPanel({ onWatch }: { onWatch: (section: string, startS?: number, extra?: Partial<FocusReq>) => void }) {
  const [d, setD] = useState<EfficiencyData | null>(null)
  useEffect(() => { api.efficiency().then(setD).catch(() => undefined) }, [])
  const n = d?.reclaim.neutral
  const g = d?.grouping
  return (
    <div className="panel efficiency">
      <div className="panel-head"><h2>Network efficiency</h2><span className="sub">time given back · effort saved</span></div>
      <div className="panel-body">
        {!d && <div className="hint keep"><span className="spinner-sm" /> measuring…</div>}
        {d && n && g && (
          <>
            <div className="tiles mini">
              <div className="tile"><div className="v"><Num v={n.pulled} dp={0} /></div><div className="k">extra small jobs a week</div>
                <div className="note">done in time freed by blocks finishing early ({n.freed_h.toFixed(1)} h handed back)</div></div>
              <div className="tile"><div className="v"><Num v={g.place_and_urgency.riders} /></div><div className="k">small jobs riding in big blocks</div>
                <div className="note">{g.place_and_urgency.setup_saved_min} min of set-up and hand-back saved</div></div>
              <div className="tile"><div className="v" style={{ color: 'var(--fit)' }}>{g.place_only.mixed_urgency_groups} → {g.place_and_urgency.mixed_urgency_groups}</div>
                <div className="k">groups mixing urgent and routine work</div><div className="note">place only → place and urgency</div></div>
              <div className="tile"><div className="v"><Num v={d.rerouting.saved_min} /></div><div className="k">train-minutes saved by rerouting</div>
                <div className="note">{d.rerouting.diverted} long-distance trains sent round, 0 locals</div></div>
            </div>
            <div className="reason detail">
              Early finish: each block gets the time its crew really takes; when it finishes early, the rest of the protected time goes to small waiting
              jobs on the same section, urgent first. If crews run as often early as late this hands back {n.freed_h.toFixed(1)} h a week;
              with crews that tend to overrun, {d.reclaim.freed_h.toFixed(1)} h. Longer blocks give back more.
              Grouping: jobs join a group when they are close and similarly urgent; small ones ride in the biggest job's block.
            </div>
            {d.reclaim.examples.length > 0 && (
              <div className="rr-list">
                {d.reclaim.examples.filter(x => x.pulled.length).slice(0, 3).map(x => (
                  <div className="rr-item" key={x.task_id}>
                    <span className="rr-dot" style={{ background: 'var(--fit)' }} />
                    <div className="rr-main"><b>{x.label}</b> <span className="muted mono">{x.zone_ref}</span>
                      <div className="rr-cost">planned {x.planned_min} min, done in {x.actual_min}; {x.pulled.map(p => `${p.label.toLowerCase()} (${p.duration_min} min)`).join(', ')} fitted in
                        <span className="muted"> · {DAYS[Math.floor(x.freed_from_s / 86400) % 7]} {hhmm(x.freed_from_s)}</span></div></div>
                    <button className="action" onClick={() => onWatch(x.zone_ref, x.start_s, { endS: x.start_s + x.planned_min * 60, label: x.label })}>Show</button>
                  </div>
                ))}
              </div>
            )}
            <div className="hint">{d.reclaim.caveat}</div>
          </>
        )}
        <div className="needs-title">What a job needs on site</div>
        <Needs />
      </div>
    </div>
  )
}

