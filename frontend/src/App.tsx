import { useEffect, useMemo, useRef, useState } from 'react'
import NetworkMap, { type BlockInfo, type FocusReq } from './components/NetworkMap'
import SuddenPanel from './components/SuddenPanel'
import Coordination from './components/Coordination'
import WeeklyPlan from './components/WeeklyPlan'
import Chat, { MitraIcon } from './components/Chat'
import Impact from './components/Impact'
import AlgoLab from './components/AlgoLab'
import EfficiencyPanel from './components/EfficiencyPanel'
import Studio from './components/Studio'
// import Integration from './components/Integration'   // IR integration tab: commented out
import ProofStrip from './components/ProofStrip'
import YourJobs from './components/YourJobs'
import JobClusters, { type Halo } from './components/JobClusters'
import GapStrip from './components/GapStrip'
import ReroutePanel from './components/ReroutePanel'
import LineReroute from './components/LineReroute'
import {
  api, DAYS, hhmm,
  type EventItem, type GapData, type MatrixData, type NetworkData,
  type PlanData, type RerouteBlock, type RerouteProofRow, type SectionBrief, type SuddenResult, type Task, type TrainsData,
} from './api'

// 'capacity' (Corridor capacity) and 'integration' (IR integration) are commented out of the tab bar.
type Tab = 'operations' | 'coordination' | 'plan' | 'studio' | 'impact' | 'ai'

const TAB_LABEL: Record<Tab, string> = {
  operations: 'Operations',
  coordination: 'Department coordination',
  plan: 'Weekly block plan',
  studio: 'Scaling studio',
  // capacity: 'Corridor capacity',
  impact: 'Before / after',
  ai: 'AI dispatcher',
  // integration: 'IR integration',
}

const TAB_ICON: Record<Tab, string> = {
  operations: 'M12 21s-7-6.2-7-11.2A7 7 0 0 1 19 9.8C19 14.8 12 21 12 21zM12 12.2a2.4 2.4 0 1 0 0-4.8 2.4 2.4 0 0 0 0 4.8z',
  coordination: 'M16 11a3 3 0 1 0-3-3 3 3 0 0 0 3 3zM8 12a3 3 0 1 0-3-3 3 3 0 0 0 3 3zM8 14c-3 0-5 1.6-5 3.5V19h10v-1.5C13 15.6 11 14 8 14zm8 0c-.4 0-.8 0-1.2.1 1.4 1 2.2 2.3 2.2 3.9V19h4v-1.5c0-1.9-2-3.5-5-3.5z',
  plan: 'M7 3v3M17 3v3M4 9h16M5 5h14a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1zM8 13h3M8 16h6',
  studio: 'M4 7h10M18 7h2M4 17h2M10 17h10M14 5v4M8 15v4M4 12h4M12 12h8',
  impact: 'M5 20V11M11 20V5M17 20v-6M3 20h18',
  ai: 'M9 3v2M15 3v2M9 19v2M15 19v2M3 9h2M3 15h2M19 9h2M19 15h2M7 5h10a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2zM9.5 9.5h5v5h-5z',
}
function TabIcon({ t }: { t: Tab }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"
         className="tab-ic" aria-hidden="true"><path d={TAB_ICON[t]} /></svg>
  )
}

type Win = { zone_ref: string; start_s: number; end_s: number; id?: string; dept?: string; label?: string;
             urgent?: boolean; level?: string; track?: string }
const PROTECT_S = 15 * 60      // protection goes up before the work starts ...
const HANDBACK_S = 10 * 60     // ... and comes down after it ends

const CLOCK_KEY = 'rb-clock'
const WEEK_S = 7 * 86400
// Where the simulation clock starts: where it was last left, moved on by the time away if it was running.
const initialClock = (): number => {
  try {
    const v = JSON.parse(localStorage.getItem(CLOCK_KEY) ?? 'null')
    if (v && typeof v.c === 'number' && typeof v.at === 'number') {
      const away = v.playing ? Math.max(0, (Date.now() - v.at) / 1000) * 60 : 0     // running at the normal 60x pace
      return (v.c + away) % WEEK_S
    }
  } catch { /* storage can be blocked or hold something else */ }
  return 7 * 3600
}

const initialTheme = (): 'light' | 'dark' => {
  try {
    const t = localStorage.getItem('rb-theme')
    if (t === 'light' || t === 'dark') return t
  } catch { /* storage can be blocked */ }
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
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
  const [brief, setBrief] = useState<SectionBrief | null>(null)
  const [userWindows, setUserWindows] = useState<Win[]>([])
  const [simWindows, setSimWindows] = useState<Win[]>([])
  const [suddenWins, setSuddenWins] = useState<Win[]>([])
  const [movedIds, setMovedIds] = useState<Set<string>>(new Set())
  const [movedWins, setMovedWins] = useState<Win[]>([])
  const [focus, setFocus] = useState<FocusReq | null>(null)
  const [theme, setTheme] = useState<'light' | 'dark'>(initialTheme)
  const [clock, setClock] = useState(initialClock)
  const [speed, setSpeed] = useState(1)
  const [tick, setTick] = useState(0)
  const [halos, setHalos] = useState<Halo[]>([])
  const [rerouteBlocks, setRerouteBlocks] = useState<RerouteBlock[]>([])
  const [chatOpen, setChatOpen] = useState(false)
  const [playing, setPlaying] = useState(true)
  const [err, setErr] = useState<string | null>(null)
  const raf = useRef<number>(0)

  // Every panel that carries explanatory text folds it away behind its title: click the title to open it.
  useEffect(() => {
    const DETAIL = '.hint:not(.warn):not(.keep), .tile .note, .cmp-how, .steps, .limits, .detail'
    let raf = 0
    const mark = () => {
      document.querySelectorAll('.main .panel:not(.foldable):not(.chat)').forEach(p => {
        if (p.querySelector(DETAIL)) p.classList.add('foldable')
      })
    }
    const obs = new MutationObserver(() => { cancelAnimationFrame(raf); raf = requestAnimationFrame(mark) })
    obs.observe(document.body, { childList: true, subtree: true })
    mark()
    const click = (e: MouseEvent) => {
      const head = (e.target as HTMLElement).closest('.panel.foldable > .panel-head')
      if (!head || (e.target as HTMLElement).closest('button, select, input, a')) return
      head.parentElement!.classList.toggle('open')
    }
    document.addEventListener('click', click)
    return () => { obs.disconnect(); document.removeEventListener('click', click); cancelAnimationFrame(raf) }
  }, [])

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    try { localStorage.setItem('rb-theme', theme) } catch { /* storage can be blocked */ }
  }, [theme])

  useEffect(() => {
    Promise.all([api.network(), api.tasks(), api.matrix(20), api.gaps(), api.plan(), api.events()])
      .then(([n, t, m, g, p, e]) => {
        setNet(n); setTasks(t.tasks); setMat(m); setGaps(g); setPlan(p); setEvents(e.events)
      })
      .catch(e => setErr(String(e)))
  }, [])

  // The Scaling studio test takes minutes: start it in the background shortly after the app opens if there is no
  // saved result, so the page has real numbers by the time it is visited (a saved run is shown at once).
  useEffect(() => {
    const t = setTimeout(() => {
      api.studioScale().then(j => { if (j.status === 'idle') void api.studioScaleRun() }).catch(() => undefined)
    }, 20000)
    return () => clearTimeout(t)
  }, [])

  const speedRef = useRef(speed)
  speedRef.current = speed
  useEffect(() => {
    if (!playing) return
    let last = performance.now()
    const frame = (now: number) => {
      // a background tab or a stalled frame must not make the clock leap past the job being watched
      const dt = Math.min(0.25, (now - last) / 1000); last = now
      setClock(c => (c + dt * 60 * speedRef.current) % (7 * 86400))
      raf.current = requestAnimationFrame(frame)
    }
    raf.current = requestAnimationFrame(frame)
    return () => cancelAnimationFrame(raf.current)
  }, [playing])

  // One long-lived poll reading the clock from a ref. Making the effect depend on the clock
  // re-subscribes several times a second, and each cleanup kills the in-flight request before
  // it resolves, so train positions never land.
  const clockRef = useRef(clock)
  clockRef.current = clock
  // Remember the clock so a reload or a return to the page carries on from where it was, not from 07:00.
  const playingRef = useRef(playing)
  playingRef.current = playing
  useEffect(() => {
    const save = () => {
      try { localStorage.setItem(CLOCK_KEY, JSON.stringify({ c: clockRef.current, at: Date.now(), playing: playingRef.current })) } catch { /* storage can be blocked */ }
    }
    const id = setInterval(save, 1000)
    window.addEventListener('beforeunload', save)
    return () => { clearInterval(id); window.removeEventListener('beforeunload', save) }
  }, [])
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

  // Which sections are closed right now and where through traffic is being sent instead.
  useEffect(() => {
    if (tab !== 'operations') return
    let alive = true
    const pull = async () => {
      try {
        const d = await api.reroutingActive(clockRef.current)
        if (alive) setRerouteBlocks(d.blocks)
      } catch { /* transient - the next poll retries */ }
    }
    void pull()
    const id = setInterval(pull, 2000)
    return () => { alive = false; clearInterval(id) }
  }, [tab])

  useEffect(() => {
    if (!selected) { setBrief(null); return }
    let alive = true
    api.sectionBrief(selected, clockRef.current).then(b => { if (alive) setBrief(b) })
      .catch(() => { if (alive) setBrief(null) })
    return () => { alive = false }
  }, [selected, tick])

  // The live Operations-page simulation: while that tab is open, a small batch of unplanned
  // tasks is generated and gap-scheduled every few seconds (backend/planner/live_sim.py) and
  // folded straight into the status board and the map's block overlay.
  useEffect(() => {
    if (tab !== 'operations') return
    let alive = true
    const run = async () => {
      try {
        const d = await api.simTick(clockRef.current)
        if (!alive) return
        const lines: EventItem[] = d.results.map(r => ({
          at_s: d.at_s,
          text: `Simulated arrival: ${r.task.describe} — ${r.reason}.`,
          kind: r.placed ? 'plan' : 'info',
        }))
        setEvents(ev => [...ev, ...lines].slice(-400))
        const wins = d.results
          .filter(r => r.placed && r.window)
          .map(r => ({ zone_ref: r.window!.zone_ref, start_s: r.window!.start_s, end_s: r.window!.end_s,
                       id: r.task.id, dept: r.task.department, label: r.task.label ?? r.task.describe, track: r.window!.track }))
        if (wins.length) setSimWindows(sw => [...sw, ...wins].slice(-200))
        setTick(t => t + 1)
      } catch { /* transient - the next tick retries */ }
    }
    const id = setInterval(run, 7000)
    return () => { alive = false; clearInterval(id) }
  }, [tab])

  const degraded = useMemo(
    () => (net?.sections ?? []).filter(s => s.status !== 'FIT'), [net])

  const tasksById = useMemo(() => Object.fromEntries(tasks.map(t => [t.id, t])) as Record<string, Task>, [tasks])

  // Every job whose work site is on the map right now (including the protection set-up and the
  // hand-back around it), from every source: the weekly plan, the live simulation, the jobs you
  // raised, sudden tasks, and planned jobs a sudden task pushed to a new time.
  const blockInfo = useMemo(() => {
    const out: Record<string, BlockInfo> = {}
    const put = (w: Win) => {
      if (clock < w.start_s - PROTECT_S || clock >= w.end_s + HANDBACK_S) return
      const prev = out[w.zone_ref]
      // the exact lines closed in this section right now (a job with no line named closes the whole section)
      const lines = new Set(prev?.tracks ?? [])
      if (w.track) lines.add(w.track)
      const whole = (prev && !prev.track && !prev.tracks?.length) || !w.track
      if (prev && (prev.urgent || !w.urgent)) { prev.tracks = whole ? [] : [...lines]; if (whole) prev.track = undefined; return }
      out[w.zone_ref] = { section: w.zone_ref, startS: w.start_s, endS: w.end_s, dept: w.dept, label: w.label,
                          id: w.id, urgent: w.urgent, level: w.level, track: w.track, tracks: whole ? [] : [...lines] }
    }
    for (const w of suddenWins) put(w)
    for (const w of movedWins) put(w)
    if (plan) for (const a of plan.assignments) {
      if (movedIds.has(a.task_id)) continue
      const t = tasksById[a.task_id]
      put({ zone_ref: a.zone_ref, start_s: a.start_s, end_s: a.end_s ?? a.start_s + 3600,
            id: a.task_id, dept: t?.department, label: t?.label, track: a.track })
    }
    for (const w of [...simWindows, ...userWindows]) put(w)
    return out
  }, [plan, clock, simWindows, userWindows, suddenWins, movedWins, movedIds, tasksById])
  const activeBlocks = useMemo(() => new Set(Object.keys(blockInfo)), [blockInfo])

  // Fly the map to a job and say where and when it happens; start the clock a little before it.
  const showJob = (section: string, startS?: number, extra: Partial<FocusReq> = {}) => {
    setSelected(section); setTab('operations')
    window.scrollTo({ top: 0, behavior: 'smooth' })
    if (startS !== undefined) {
      // a little before the protection goes up, at real-time-ish pace so the work can be watched
      setClock(Math.max(0, startS - PROTECT_S - 90)); setSpeed(1); setPlaying(true)
    }
    setFocus({ key: Date.now(), section, startS: startS ?? clockRef.current, ...extra })
  }

  // Take the map to a diversion: the closed section and the whole detour in view, clock just before the
  // train reaches the closure so the hand-off can be watched.
  const watchDiversion = (r: RerouteProofRow) => {
    showJob(r.section_id, r.block_start_s, { endS: r.block_end_s, label: `${r.train} goes round`, fit: r.sections, id: r.train_id })
    setClock(Math.max(0, r.enter_s - 4 * 60))
  }

  const onSudden = (r: SuddenResult) => {
    if (r.placed && r.window) {
      const w = r.window
      setSuddenWins(ws => [...ws.filter(x => x.id !== r.id), {
        zone_ref: w.zone_ref, start_s: w.start_s, end_s: w.end_s, id: r.id, dept: r.task.department, track: w.track,
        label: r.task.label, urgent: r.priority <= 2, level: r.level }])
    }
    if (r.bumped.length) {
      setMovedIds(ids => new Set([...ids, ...r.bumped.map(b => b.task_id)]))
      setSimWindows(ws => ws.filter(x => !r.bumped.some(b => b.task_id === x.id)))
      setMovedWins(ws => [
        ...ws.filter(x => !r.bumped.some(b => b.task_id === x.id)),
        ...r.bumped.filter(b => b.to).map(b => ({
          zone_ref: b.zone, start_s: b.to!.start_s, end_s: b.to!.end_s, id: b.task_id, dept: b.department, label: b.label })),
      ])
    }
    setEvents(ev => [...ev, {
      at_s: r.at_s, kind: 'demand',
      text: `Sudden ${r.level.toLowerCase()}: ${r.task.describe} — ${r.window ? `${r.window.hhmm} on ${r.window.section_id}` : 'no slot yet'}`
        + (r.bumped.length ? `; moved ${r.bumped.length} lower-priority job(s)` : '') + ` (${Math.round(r.response_ms)} ms).`,
    }].slice(-400))
    setTick(t => t + 1)
    if (r.placed && r.window) watchSudden(r)
  }
  // The AI dispatcher page's "inject defect" button: put a sudden task into the live plan and show it on Operations.
  const [howKey, setHowKey] = useState(0)
  const injectFromDispatcher = async () => {
    try {
      const r = await api.suddenInject({ level: 'high', zone_ref: null, department: null, at_s: Math.round(clockRef.current) })
      onSudden(r)
      setHowKey(k => k + 1)
    } catch { /* the dispatcher page still shows its own timing */ }
    setTab('operations')
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }
  const injectRef = useRef(injectFromDispatcher)
  injectRef.current = injectFromDispatcher
  useEffect(() => {
    const h = () => { void injectRef.current() }
    window.addEventListener('railblock:sudden-defect', h)
    return () => window.removeEventListener('railblock:sudden-defect', h)
  }, [])
  const onSuddenClear = () => { setSuddenWins([]); setMovedIds(new Set()); setMovedWins([]); setTick(t => t + 1) }
  const watchSudden = (r: SuddenResult) => {
    if (!r.window) return
    showJob(r.window.zone_ref, r.window.start_s, {
      endS: r.window.end_s, label: r.task.label, dept: r.task.department, track: r.window.track, id: r.id })
  }

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
        <div className="logo-mark" role="img" aria-label="TrackSync">
          <img className="lm-dark" src="/logo-emblem-dark.png" alt="" />
          <img className="lm-light" src="/logo-emblem-light.png" alt="" />
        </div>
        <div className="brand">
          <b>TrackSync</b>
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
        <button className="theme-toggle" onClick={() => {
                  // a short-lived class turns on colour transitions for the switch only, so hovers and animations stay as they were
                  const el = document.documentElement
                  el.classList.add('theme-anim')
                  window.setTimeout(() => el.classList.remove('theme-anim'), 650)
                  setTheme(t => (t === 'dark' ? 'light' : 'dark'))
                }}
                title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
                aria-label="Toggle light and dark mode">
          {theme === 'dark' ? (
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
            </svg>
          ) : (
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
            </svg>
          )}
        </button>
      </header>

      <nav className="tabs">
        {(Object.keys(TAB_LABEL) as Tab[]).map(t => (
          <button key={t} className={`tab ${tab === t ? 'on' : ''}`} onClick={() => setTab(t)}>
            <TabIcon t={t} />{TAB_LABEL[t]}
          </button>
        ))}
        <button className="tab" style={{ marginLeft: 'auto' }} onClick={() => setPlaying(p => !p)}>
          {playing ? '❙❙ Pause' : '▶ Play'}
        </button>
      </nav>

      <main className="main">
        {tab === 'operations' && (
          <div className="grid ops">
            <div style={{ display: 'grid', gap: 16, alignContent: 'start', minWidth: 0 }}>
            <div className="panel">
              <div className="panel-head">
                <h2>Mumbai suburban network</h2>
                <div className="speed" style={{ marginLeft: 'auto' }}>
                  {[0.25, 1, 5, 10, 20].map(x => (
                    <button key={x} className={speed === x ? 'on' : ''} onClick={() => setSpeed(x)}
                            title={`${x}x simulation speed`}>{x}×</button>
                  ))}
                </div>
                <span className="sub" style={{ marginLeft: 8 }}>
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
                  clockS={clock}
                  selected={selected}
                  onSelect={setSelected}
                  blocks={activeBlocks}
                  blockInfo={blockInfo}
                  halos={halos}
                  reroutes={rerouteBlocks}
                  focus={focus}
                  onClearFocus={() => setFocus(null)}
                />
              </div>
            </div>
            <ProofStrip tick={tick} />
            <JobClusters tick={tick} onHalos={setHalos} />
            <ReroutePanel blocks={rerouteBlocks} onWatch={watchDiversion} />
            {selectedSection && (
                <div className="panel">
                  <div className="panel-head">
                    <h2>{selectedSection.id}</h2>
                    <span className="sub">{selectedSection.line_code}</span>
                  </div>
                  <div className="panel-body">
                    {rerouteBlocks.filter(b => b.section_id === selectedSection.id && (b.track || b.track_swap)).map(b => (
                      <LineReroute key={`${b.start_s}-${b.track}`} block={b} tracks={selectedSection.tracks} clockS={clock}
                                   onWatch={() => showJob(b.section_id, b.start_s, { endS: b.end_s, track: b.track ?? undefined, label: `${(b.track ?? '').replace('_', ' ').toLowerCase()} closed` })} />
                    ))}
                    {brief && (
                      <div className="reason" style={{ margin: '0 0 14px', borderLeftColor: 'var(--accent)' }}>
                        {brief.summary}
                        {brief.next_gap && (
                          <div className="muted" style={{ marginTop: 7, fontSize: 11.5 }}>
                            Next available gap: {brief.next_gap.start_hhmm}–{brief.next_gap.end_hhmm}
                            {' '}({brief.next_gap.usable_min} min usable,{' '}
                            {brief.next_gap.gap_type.replace(/_/g, ' ').toLowerCase()})
                          </div>
                        )}
                      </div>
                    )}
                    {brief && brief.timeline.length > 0 && (
                      <div style={{ margin: '0 0 14px' }}>
                        <div className="k muted" style={{ fontSize: 11, marginBottom: 6 }}>
                          TODAY · TRAINS AND GAPS
                        </div>
                        <GapStrip key={brief.section_id} tracks={brief.timeline} nowS={brief.now_s} />
                      </div>
                    )}
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

            </div>

            <div style={{ display: 'grid', gap: 16, alignContent: 'start' }}>
              <SuddenPanel net={net} clock={clock} tick={tick} onResult={onSudden} onWatch={watchSudden}
                           onClear={onSuddenClear} expandKey={howKey} />
              <YourJobs tick={tick} onWindows={setUserWindows}
                        onWatch={t => t.schedule && showJob(t.schedule.section_id, t.schedule.start_s, {
                          endS: t.schedule.end_s, label: t.description || t.label, dept: t.department,
                          track: t.schedule.track, id: t.id })} />
              <EfficiencyPanel onWatch={showJob} />
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

        {tab === 'coordination' && (
          <Coordination mat={mat} clock={clock} onShow={showJob} />
        )}

        {tab === 'plan' && <WeeklyPlan />}

        {/* Corridor capacity tab: commented out
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
        */}

        {tab === 'studio' && <Studio />}
        {tab === 'impact' && <Impact />}
        {tab === 'ai' && <AlgoLab />}
        {/* {tab === 'integration' && <Integration />}   IR integration tab: commented out */}
      </main>

      <div className={`chat-drawer ${chatOpen ? '' : 'closed'}`}><Chat atS={clock} onShow={showJob} /></div>
      <div className="mitra-dock">
        {!chatOpen && <span className="mitra-label">Ask <b>RailMitra</b></span>}
        <button className="chat-fab" onClick={() => setChatOpen(o => !o)}
                title={chatOpen ? 'Close RailMitra' : 'Ask RailMitra'} aria-label="Ask RailMitra">
          {chatOpen ? (
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round">
              <path d="M6 6l12 12M18 6L6 18" /></svg>
          ) : <MitraIcon />}
          {!chatOpen && <i className="ring" />}
        </button>
      </div>
    </div>
  )
}
