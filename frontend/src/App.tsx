import { useEffect, useMemo, useRef, useState } from 'react'
import NetworkMap from './components/NetworkMap'
import CompatMatrix from './components/CompatMatrix'
import Chat from './components/Chat'
import Impact from './components/Impact'
import RlPanel from './components/RlPanel'
import Integration from './components/Integration'
import {
  api, DAYS, hhmm,
  type EventItem, type GapData, type MatrixData, type NetworkData,
  type PlanData, type Task, type TrainsData,
} from './api'

type Tab = 'operations' | 'coordination' | 'plan' | 'capacity' | 'impact' | 'ai' | 'integration'

const TAB_LABEL: Record<Tab, string> = {
  operations: 'Operations',
  coordination: 'Department coordination',
  plan: 'Weekly block plan',
  capacity: 'Corridor capacity',
  impact: 'Before / after',
  ai: 'AI dispatcher',
  integration: 'IR integration',
}

export default function App() {
  const [net, setNet] = useState<NetworkData | null>(null)
  const [tasks, setTasks] = useState<Task[]>([])
  const [mat, setMat] = useState<MatrixData | null>(null)
  const [gaps, setGaps] = useState<GapData | null>(null)
  const [plan, setPlan] = useState<PlanData | null>(null)
  const [trains, setTrains] = useState<TrainsData | null>(null)
  const [events, setEvents] = useState<EventItem[]>([])
  const [tab, setTab] = useState<Tab>('operations')
  const [selected, setSelected] = useState<string | null>(null)
  const [clock, setClock] = useState(7 * 3600)
  const [playing, setPlaying] = useState(true)
  const [err, setErr] = useState<string | null>(null)
  const raf = useRef<number>(0)

  useEffect(() => {
    Promise.all([api.network(), api.tasks(), api.matrix(20), api.gaps(), api.plan(), api.events()])
      .then(([n, t, m, g, p, e]) => {
        setNet(n); setTasks(t.tasks); setMat(m); setGaps(g); setPlan(p); setEvents(e.events)
      })
      .catch(e => setErr(String(e)))
  }, [])

  useEffect(() => {
    if (!playing) return
    let last = performance.now()
    const tick = (now: number) => {
      const dt = (now - last) / 1000; last = now
      setClock(c => (c + dt * 420) % (7 * 86400))
      raf.current = requestAnimationFrame(tick)
    }
    raf.current = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf.current)
  }, [playing])

  // One long-lived poll reading the clock from a ref. Making the effect depend on the clock
  // re-subscribes several times a second, and each cleanup kills the in-flight request before
  // it resolves, so train positions never land.
  const clockRef = useRef(clock)
  clockRef.current = clock
  useEffect(() => {
    if (!net) return
    let alive = true
    let busy = false
    const pull = async () => {
      if (busy) return
      busy = true
      try {
        const d = await api.trains(clockRef.current)
        if (alive) setTrains(d)
      } catch { /* transient - the next tick retries */ } finally { busy = false }
    }
    void pull()
    const id = setInterval(pull, 1100)
    return () => { alive = false; clearInterval(id) }
  }, [net])

  const degraded = useMemo(
    () => (net?.sections ?? []).filter(s => s.status !== 'FIT'), [net])

  const activeBlocks = useMemo(() => {
    const s = new Set<string>()
    if (!plan) return s
    for (const a of plan.assignments) {
      if (a.start_s <= clock && clock < a.start_s + 3600) s.add(a.zone_ref)
    }
    return s
  }, [plan, clock])

  const selectedSection = net?.sections.find(s => s.id === selected) ?? null
  const selectedTasks = tasks.filter(t => t.zone === selected)

  if (err) return (
    <div className="loading">
      <div className="spinner" />
      Could not reach the planner API.<br />
      <span className="mono" style={{ fontSize: 11 }}>{err}</span>
    </div>
  )
  if (!net || !gaps || !plan) return (
    <div className="loading"><div className="spinner" />Building the Mumbai network…</div>
  )

  const day = Math.floor(clock / 86400)
  const lines = [...new Set(net.sections.map(s => s.line_code).filter(Boolean))]

  return (
    <div className="app">
      <header className="header">
        <div className="logo">
          <svg viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2.2"
               strokeLinecap="round" strokeLinejoin="round">
            <rect x="4" y="3" width="16" height="13" rx="2.5" />
            <path d="M4 11h16M8 20l-2 2M16 20l2 2M9 16h.01M15 16h.01" />
          </svg>
        </div>
        <div className="brand">
          <b>RailBlock AI</b>
          <span>{net.name} · {lines.length} lines · {net.stations.length} stations</span>
        </div>
        <div className="header-stats">
          <div className="hstat">
            <div className="v">{trains?.total_active ?? '—'}</div>
            <div className="k">Running</div>
          </div>
          <div className="hstat">
            <div className="v" style={{ color: degraded.length ? 'var(--sick)' : 'var(--fit)' }}>
              {degraded.length}
            </div>
            <div className="k">Not fit</div>
          </div>
          <div className="hstat">
            <div className="v">{tasks.filter(t => !t.completed).length}</div>
            <div className="k">Open jobs</div>
          </div>
          <div className="hstat">
            <div className="v">{DAYS[day]} {hhmm(clock)}</div>
            <div className="k">Sim clock</div>
          </div>
        </div>
      </header>

      <nav className="tabs">
        {(Object.keys(TAB_LABEL) as Tab[]).map(t => (
          <button key={t} className={`tab ${tab === t ? 'on' : ''}`} onClick={() => setTab(t)}>
            {TAB_LABEL[t]}
          </button>
        ))}
        <button className="tab" style={{ marginLeft: 'auto' }} onClick={() => setPlaying(p => !p)}>
          {playing ? '❙❙ Pause' : '▶ Play'}
        </button>
      </nav>

      <main className="main">
        {tab === 'operations' && (
          <div className="grid ops">
            <div className="panel">
              <div className="panel-head">
                <h2>Mumbai suburban network</h2>
                <span className="sub">
                  {selectedSection
                    ? `${selectedSection.id} · ${selectedSection.length_km.toFixed(1)} km · ${selectedSection.trains_per_day} trains/day`
                    : 'click a section · hover a station'}
                </span>
              </div>
              <div className="panel-body flush">
                <NetworkMap
                  net={net}
                  trains={trains?.trains ?? []}
                  totalActive={trains?.total_active ?? 0}
                  truncated={trains?.truncated ?? 0}
                  clock={`${DAYS[day]} ${hhmm(clock)}`}
                  selected={selected}
                  onSelect={setSelected}
                  blocks={activeBlocks}
                />
              </div>
            </div>

            <div style={{ display: 'grid', gap: 16, alignContent: 'start' }}>
              {selectedSection && (
                <div className="panel">
                  <div className="panel-head">
                    <h2>{selectedSection.id}</h2>
                    <span className="sub">{selectedSection.line_code}</span>
                  </div>
                  <div className="panel-body">
                    <div className="kv"><span className="k">Status</span>
                      <span className={`status s-${selectedSection.status}`}>
                        {selectedSection.status.replace(/_/g, ' ').toLowerCase()}</span></div>
                    <div className="kv"><span className="k">Length</span>
                      <span className="v">{selectedSection.length_km.toFixed(2)} km</span></div>
                    <div className="kv"><span className="k">Line speed</span>
                      <span className="v">{selectedSection.line_speed_kmph} km/h</span></div>
                    <div className="kv"><span className="k">Tracks</span>
                      <span className="v mono">{selectedSection.tracks.join(' ')}</span></div>
                    <div className="kv"><span className="k">Station tier</span>
                      <span className="v">{selectedSection.tier?.replace('_', ' ').toLowerCase()}</span></div>
                    <div className="kv"><span className="k">Traffic</span>
                      <span className="v">{selectedSection.trains_per_day} trains/day</span></div>
                    {selectedTasks.length > 0 && (
                      <div style={{ marginTop: 12 }}>
                        <div className="k muted" style={{ fontSize: 11, marginBottom: 6 }}>
                          OUTSTANDING WORK
                        </div>
                        {selectedTasks.map(t => (
                          <div key={t.id} className="kv">
                            <span className="k">
                              <span className={`badge dept ${t.department}`}>{t.department}</span>{' '}
                              {t.label}
                            </span>
                            <span className="v mono">
                              {t.scheduled ? `${t.day} ${t.start_hhmm}` : 'unplanned'}
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              )}

              <div className="panel">
                <div className="panel-head">
                  <h2>Status board</h2><span className="sub">plain language</span>
                </div>
                <div className="panel-body flush board">
                  {[...events].reverse().map((e, i) => (
                    <div key={i} className={`ev ${e.kind}`}>
                      <span className="t">{DAYS[Math.floor(e.at_s / 86400)]} {hhmm(e.at_s)}</span>
                      {e.text}
                    </div>
                  ))}
                  {degraded.slice(0, 8).map(s => (
                    <div key={s.id} className="ev">
                      <span className="t">now</span>
                      <b>{s.id}</b> is <span className={`status s-${s.status}`}>
                        {s.status.replace(/_/g, ' ').toLowerCase()}</span>
                      {s.status === 'CAUTION_ORDER' && (
                        <span className="aside">
                          Trains pass at reduced speed until a follow-up job clears it.
                        </span>
                      )}
                      {s.status === 'SICK' && (
                        <span className="aside">
                          A defect has been identified and work is outstanding.
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}

        {tab === 'coordination' && mat && (
          <div className="grid side">
            <CompatMatrix data={mat} />
            <Chat />
          </div>
        )}

        {tab === 'plan' && (
          <div className="grid two">
            <div className="panel">
              <div className="panel-head">
                <h2>CP-SAT weekly plan</h2>
                <span className="sub">
                  {plan.status.toLowerCase()} · {plan.gap_pct}% optimality gap · {plan.wall_s}s
                </span>
              </div>
              <div className="panel-body">
                <div className="tiles">
                  <div className="tile">
                    <div className="v">{plan.n_scheduled}<small>/{plan.n_tasks}</small></div>
                    <div className="k">Jobs placed this week</div>
                  </div>
                  <div className="tile">
                    <div className="v" style={{ color: 'var(--accent)' }}>{plan.micro_gap_count}</div>
                    <div className="k">Into gaps between trains</div>
                    <div className="note">
                      Work that conventional planning would leave waiting for a night block.
                    </div>
                  </div>
                  <div className="tile">
                    <div className="v">{plan.n_unscheduled}</div>
                    <div className="k">No window long enough</div>
                    <div className="note">
                      These need a window created by rerouting, not merely finding.
                    </div>
                  </div>
                </div>
                <div style={{ marginTop: 18 }}>
                  <div className="k muted" style={{ fontSize: 11 }}>BLOCKS GRANTED PER DAY</div>
                  <div className="week">
                    {DAYS.map(d => {
                      const n = plan.by_day[d] ?? 0
                      const max = Math.max(1, ...Object.values(plan.by_day))
                      return (
                        <div key={d}>
                          <b>{n || ''}</b>
                          <i style={{ height: `${(n / max) * 52}px` }} />
                          <span>{d}</span>
                        </div>
                      )
                    })}
                  </div>
                </div>
              </div>
            </div>

            <div className="panel">
              <div className="panel-head"><h2>Task pool</h2><span className="sub">{tasks.length} jobs</span></div>
              <div className="panel-body flush scroll">
                <table>
                  <thead>
                    <tr><th>Dept</th><th>Job</th><th>Where</th><th className="num">Min</th><th>When</th></tr>
                  </thead>
                  <tbody>
                    {tasks.map(t => (
                      <tr key={t.id}>
                        <td><span className={`badge dept ${t.department}`}>{t.department}</span></td>
                        <td>{t.label}
                          {t.category === 'DEMAND' &&
                            <span className="badge demand" style={{ marginLeft: 6 }}>unplanned</span>}
                        </td>
                        <td className="mono">{t.zone}</td>
                        <td className="num">{t.duration_min}</td>
                        <td>{t.scheduled
                          ? <>{t.day} {t.start_hhmm}{t.gap_type === 'MICRO_GAP' &&
                              <span className="badge micro" style={{ marginLeft: 6 }}>micro-gap</span>}</>
                          : <span className="muted">unplanned</span>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}

        {tab === 'capacity' && (
          <div className="grid two">
            <div className="panel">
              <div className="panel-head"><h2>Where maintenance can go</h2><span className="sub">one week, whole network</span></div>
              <div className="panel-body">
                <div className="tiles">
                  {(['MICRO_GAP', 'NIGHT_WINDOW', 'MEGABLOCK'] as const).map(k => (
                    <div className="tile" key={k}>
                      <div className="v" style={{ color: k === 'MICRO_GAP' ? 'var(--accent)' : undefined }}>
                        {(gaps.counts[k] ?? 0).toLocaleString()}
                      </div>
                      <div className="k">{k === 'NIGHT_WINDOW' ? 'Night windows'
                        : k === 'MEGABLOCK' ? 'Megablock windows' : 'Gaps between trains'}</div>
                      <div className="note">{(gaps.usable_hours[k] ?? 0).toLocaleString()} usable hours</div>
                    </div>
                  ))}
                </div>
                <div className="tile" style={{ marginTop: 13 }}>
                  <div className="v">{gaps.usable_pct_of_raw}%</div>
                  <div className="k">of raw gap time is actually workable</div>
                  <div className="bar"><i style={{ width: `${gaps.usable_pct_of_raw}%` }} /></div>
                  <div className="note">
                    A gap is not working time. Every block costs {gaps.block_setup_min} minutes
                    to protect and {gaps.block_release_min} to hand back, so a 40-minute gap
                    yields about 15 minutes of work. Planning against raw gaps would overstate
                    capacity across the entire network.
                  </div>
                </div>
              </div>
            </div>

            <div className="panel">
              <div className="panel-head">
                <h2>Night windows, derived per section</h2><span className="sub">not hardcoded</span>
              </div>
              <div className="panel-body flush scroll" style={{ maxHeight: 360 }}>
                <table>
                  <thead><tr><th>Section / track</th><th>Low-traffic window</th></tr></thead>
                  <tbody>
                    {Object.entries(gaps.night_windows).map(([k, [a, b]]) => (
                      <tr key={k}><td className="mono">{k}</td><td className="mono">{a} – {b}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="reason" style={{ borderLeftColor: 'var(--accent)', marginTop: 14 }}>
                Each window is read from the last and first train on that track, so it differs
                section by section rather than assuming one corridor-wide night. The Sunday
                megablock is corroborated too: traffic in the configured window measures{' '}
                <b>{gaps.megablock_observed_reduction}% below a weekday</b>, so it is evidence
                rather than an assertion.
              </div>
            </div>
          </div>
        )}

        {tab === 'impact' && <Impact />}
        {tab === 'ai' && <RlPanel />}
        {tab === 'integration' && <Integration />}
      </main>
    </div>
  )
}
