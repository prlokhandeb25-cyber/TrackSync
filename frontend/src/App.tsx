import { useEffect, useMemo, useRef, useState } from 'react'
import MapView from './components/MapView'
import CompatMatrix from './components/CompatMatrix'
import {
  api, DAYS, hhmm,
  type EventItem, type GapData, type MatrixData, type NetworkData,
  type PlanData, type Task, type TrainsData,
} from './api'

type Tab = 'operations' | 'compatibility' | 'plan' | 'capacity'

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
  const [clock, setClock] = useState(6 * 3600)
  const [playing, setPlaying] = useState(true)
  const [err, setErr] = useState<string | null>(null)
  const raf = useRef<number>(0)

  useEffect(() => {
    Promise.all([api.network(), api.tasks(), api.matrix(18), api.gaps(), api.plan(), api.events()])
      .then(([n, t, m, g, p, e]) => {
        setNet(n); setTasks(t.tasks); setMat(m); setGaps(g); setPlan(p); setEvents(e.events)
      })
      .catch(e => setErr(String(e)))
  }, [])

  // Simulated clock. 1 real second = 6 simulated minutes.
  useEffect(() => {
    if (!playing) return
    let last = performance.now()
    const tick = (now: number) => {
      const dt = (now - last) / 1000; last = now
      setClock(c => (c + dt * 360) % (7 * 86400))
      raf.current = requestAnimationFrame(tick)
    }
    raf.current = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf.current)
  }, [playing])

  // Train positions are polled on ONE long-lived interval that reads the clock from a ref.
  // Making the effect depend on the clock instead re-subscribes several times a second, and
  // each cleanup invalidates the in-flight request before it resolves - so nothing ever lands.
  const clockRef = useRef(clock)
  clockRef.current = clock
  useEffect(() => {
    if (!net) return
    let alive = true
    let busy = false
    const pull = async () => {
      if (busy) return            // don't stack requests if one is slow
      busy = true
      try {
        const d = await api.trains(clockRef.current)
        if (alive) setTrains(d)
      } catch { /* transient - the next tick retries */ } finally { busy = false }
    }
    void pull()
    const id = setInterval(pull, 1000)
    return () => { alive = false; clearInterval(id) }
  }, [net])

  const sick = useMemo(
    () => (net?.sections ?? []).filter(s => s.status !== 'FIT'), [net])

  if (err) return <div className="loading">Could not reach the API: {err}</div>
  if (!net || !gaps || !plan) return <div className="loading">Loading corridor…</div>

  const day = Math.floor(clock / 86400)

  return (
    <div className="app">
      <header className="header">
        <div className="brand">
          RailBlock AI
          <span>{net.name}</span>
        </div>
        <div className="header-stats">
          <div className="hstat">
            <div className="v">{trains?.total_active ?? '—'}</div>
            <div className="k">Trains running</div>
          </div>
          <div className="hstat">
            <div className="v">{sick.length}</div>
            <div className="k">Sections not fit</div>
          </div>
          <div className="hstat">
            <div className="v">{tasks.filter(t => !t.completed).length}</div>
            <div className="k">Open jobs</div>
          </div>
          <div className="hstat">
            <div className="v">{DAYS[day]} {hhmm(clock)}</div>
            <div className="k">Simulated clock</div>
          </div>
        </div>
      </header>

      <nav className="tabs">
        {(['operations', 'compatibility', 'plan', 'capacity'] as Tab[]).map(t => (
          <button key={t} className={`tab ${tab === t ? 'on' : ''}`} onClick={() => setTab(t)}>
            {t === 'operations' ? 'Operations'
              : t === 'compatibility' ? 'Department coordination'
                : t === 'plan' ? 'Weekly block plan' : 'Corridor capacity'}
          </button>
        ))}
        <button className="tab" style={{ marginLeft: 'auto' }} onClick={() => setPlaying(p => !p)}>
          {playing ? 'Pause' : 'Play'}
        </button>
      </nav>

      <main className="main">
        {tab === 'operations' && (
          <div className="grid map-layout">
            <div className="panel">
              <div className="panel-head">
                <h2>Corridor</h2>
                <span className="sub">
                  {selected ? selected : `${net.stations.length} stations · ${net.sections.length} sections`}
                </span>
              </div>
              <div className="panel-body flush">
                <MapView
                  net={net}
                  trains={trains?.trains ?? []}
                  totalActive={trains?.total_active ?? 0}
                  truncated={trains?.truncated ?? 0}
                  clock={`${DAYS[day]} ${hhmm(clock)}`}
                  selected={selected}
                  onSelect={setSelected}
                />
              </div>
            </div>

            <div className="panel">
              <div className="panel-head">
                <h2>Status board</h2>
                <span className="sub">plain language</span>
              </div>
              <div className="panel-body flush board">
                {events.length === 0 && (
                  <div className="ev muted">Nothing has happened yet this week.</div>
                )}
                {[...events].reverse().map((e, i) => (
                  <div key={i} className={`ev ${e.kind}`}>
                    <span className="t">{DAYS[Math.floor(e.at_s / 86400)]} {hhmm(e.at_s)}</span>
                    {e.text}
                  </div>
                ))}
                {sick.slice(0, 6).map(s => (
                  <div key={s.id} className="ev">
                    <span className="t">now</span>
                    <b>{s.id}</b> is <span className={`status s-${s.status}`}>
                      {s.status.replace(/_/g, ' ').toLowerCase()}</span>.
                    {s.status === 'CAUTION_ORDER' && (
                      <span className="aside">
                        Trains pass at reduced speed until a follow-up job clears it.
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {tab === 'compatibility' && mat && <CompatMatrix data={mat} />}

        {tab === 'plan' && (
          <div className="grid two">
            <div className="panel">
              <div className="panel-head">
                <h2>CP-SAT weekly plan</h2>
                <span className="sub">{plan.status.toLowerCase()} · {plan.gap_pct}% gap · {plan.wall_s}s</span>
              </div>
              <div className="panel-body">
                <div className="tiles">
                  <div className="tile">
                    <div className="v">{plan.n_scheduled}<span className="muted" style={{ fontSize: 15 }}>/{plan.n_tasks}</span></div>
                    <div className="k">Jobs placed</div>
                  </div>
                  <div className="tile">
                    <div className="v" style={{ color: 'var(--accent)' }}>{plan.micro_gap_count}</div>
                    <div className="k">Into gaps between trains</div>
                    <div className="note">Work that would otherwise wait for a night block or a megablock.</div>
                  </div>
                  <div className="tile">
                    <div className="v">{plan.n_unscheduled}</div>
                    <div className="k">No window long enough</div>
                    <div className="note">These need a window to be created by rerouting.</div>
                  </div>
                </div>
                <div style={{ marginTop: 18 }}>
                  <div className="k muted" style={{ fontSize: 11.5 }}>BLOCKS PER DAY</div>
                  <div className="week">
                    {DAYS.map(d => {
                      const n = plan.by_day[d] ?? 0
                      const max = Math.max(1, ...Object.values(plan.by_day))
                      return (
                        <div key={d}>
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
                        <td><span className="badge dept">{t.department}</span></td>
                        <td>
                          {t.label}
                          {t.category === 'DEMAND' && <span className="badge demand" style={{ marginLeft: 6 }}>unplanned</span>}
                        </td>
                        <td className="mono">{t.zone}</td>
                        <td className="num">{t.duration_min}</td>
                        <td>
                          {t.scheduled
                            ? <>{t.day} {t.start_hhmm}{t.gap_type === 'MICRO_GAP' &&
                                <span className="badge micro" style={{ marginLeft: 6 }}>micro-gap</span>}</>
                            : <span className="muted">unplanned</span>}
                        </td>
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
              <div className="panel-head"><h2>Where maintenance can go</h2><span className="sub">one week</span></div>
              <div className="panel-body">
                <div className="tiles">
                  {(['NIGHT_WINDOW', 'MEGABLOCK', 'MICRO_GAP'] as const).map(k => (
                    <div className="tile" key={k}>
                      <div className="v">{gaps.counts[k] ?? 0}</div>
                      <div className="k">{k === 'NIGHT_WINDOW' ? 'Night windows'
                        : k === 'MEGABLOCK' ? 'Megablock windows' : 'Gaps between trains'}</div>
                      <div className="note">{gaps.usable_hours[k] ?? 0} usable hours</div>
                    </div>
                  ))}
                </div>
                <div className="tile" style={{ marginTop: 14 }}>
                  <div className="v">{gaps.usable_pct_of_raw}%</div>
                  <div className="k">of raw gap time is actually workable</div>
                  <div className="bar"><i style={{ width: `${gaps.usable_pct_of_raw}%` }} /></div>
                  <div className="note">
                    A gap is not working time. Every block costs {gaps.block_setup_min} min to
                    protect and {gaps.block_release_min} min to hand back, so a 40-minute gap
                    yields about 15 minutes of work. Planning against raw gaps would overstate
                    capacity across the whole corridor.
                  </div>
                </div>
              </div>
            </div>

            <div className="panel">
              <div className="panel-head"><h2>Night windows, derived per section</h2>
                <span className="sub">not hardcoded</span></div>
              <div className="panel-body flush scroll">
                <table>
                  <thead><tr><th>Section / track</th><th>Low-traffic window</th></tr></thead>
                  <tbody>
                    {Object.entries(gaps.night_windows).map(([k, [a, b]]) => (
                      <tr key={k}><td className="mono">{k}</td><td className="mono">{a} – {b}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="reason" style={{ borderLeftColor: 'var(--accent)' }}>
                Each window is read from the last and first train on that track, so it differs
                section by section rather than assuming a single corridor-wide night. The Sunday
                megablock is corroborated too: traffic in the configured window measures{' '}
                <b>{gaps.megablock_observed_reduction}% below a weekday</b>.
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  )
}
