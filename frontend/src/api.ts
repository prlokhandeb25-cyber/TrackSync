export type Status = 'FIT' | 'SICK' | 'CAUTION_ORDER' | 'STOP_AND_START'
export type Verdict = 'COMPATIBLE' | 'REQUIRES_IWP' | 'INCOMPATIBLE'

export interface Station {
  code: string; name: string; lat: number; lon: number
  tier: string | null; junction: boolean; platforms: number
  trains_per_day: number; peak_tph: number; status: Status
  lines?: string[]; line_code?: string; coord_src?: string
}
export interface Section {
  id: string; from: string; to: string; length_km: number
  line_speed_kmph: number; tracks: string[]; tier: string | null
  geometry: [number, number][]; trains_per_day: number; status: Status
  line_code: string
}
export interface NetworkData { corridor: string; name: string; stations: Station[]; sections: Section[]; order: string[] }

export interface Task {
  id: string; department: string; dept_label: string; source_system: string
  label: string; zone: string; zone_kind: string; duration_min: number
  priority: number; category: string; power_block: boolean; completed: boolean
  outcome: Status | null; describe: string; scheduled: boolean
  day: string | null; start_hhmm: string | null; gap_type: string | null
}

export interface MatrixCell { a: string; b: string; value: Verdict; reason: string; rule_id: string; zone_relation: string }
export interface MatrixData {
  tasks: { id: string; department: string; label: string; zone: string }[]
  cells: MatrixCell[]
  summary: Record<Verdict, number>
  coordination_conflicts: number
  manual_coordination_hours: number
  view: string
  iwp_quota_per_day: number
}

export interface GapData {
  counts: Record<string, number>
  usable_hours: Record<string, number>
  raw_hours: number; total_usable_hours: number; usable_pct_of_raw: number
  night_windows: Record<string, [string, string]>
  megablock_observed_reduction: number
  block_setup_min: number; block_release_min: number
}

export interface PlanData {
  status: string; objective: number; gap_pct: number; wall_s: number
  n_tasks: number; n_scheduled: number; n_unscheduled: number
  micro_gap_count: number; iwp_used: number; relaxations: string[]
  by_day: Record<string, number>; by_gap_type: Record<string, number>
  assignments: { task_id: string; zone_ref: string; start_s: number; gap_type: string; day: number }[]
}

export interface TrainDot { id: string; cls: string; section: string; track?: string; lat: number; lon: number }
export interface TrainsData { at_s: number; trains: TrainDot[]; total_active: number; truncated: number }

export interface EventItem { at_s: number; text: string; kind: string }

export interface ChatAction { label: string; section: string | null; start_s: number }
export type ChatVisual =
  | { type: 'schedule'; title: string; days: string[]
      blocks: { id: string; dept: string; start_s: number; end_s: number; kind: 'stay' | 'moved' | 'new' | 'dropped'
                label: string; from?: { start_s: number; end_s: number } }[] }
  | { type: 'profile'; title: string; unit: string; day: string; highlight: [number, number] | null
      hours: { hour: number; value: number; passengers: number }[] }
  | { type: 'bars'; title: string; items: { label: string; value: number; best: boolean }[] }
export interface ChatAnswer {
  text: string
  facts: { k: string; v: string }[]
  trace: string[]
  intent: string
  suggestions: string[]
  action?: ChatAction | null
  visual?: ChatVisual | null
  visuals?: ChatVisual[]
}

export interface ImpactMetric {
  id: string; name: string; before: number; after: number; unit: string
  better: 'lower' | 'higher'; note: string; delta_pct: number; improvement_pct: number
}
export interface ImpactData {
  instances: number
  assumptions: Record<string, unknown>
  metrics: ImpactMetric[]
}

export interface RlRow {
  policy: string; instances: number; mean_gap_vs_cpsat_pct: number
  mean_scheduled_pct: number; mean_micro_gap: number; mean_decision_ms: number
  mean_full_replan_ms: number; constraint_violations: number
}
export interface RlData { table: RlRow[]; cpsat_mean_ms: number; instances: number }

export interface AdapterInfo {
  system: string; full_name: string; role: string; direction: string
  department: string | null; methods: string[]; mode: string; schema_status: string
}
export interface AdapterData {
  mode: string; adapters: AdapterInfo[]
  sample_block_demands: Record<string, unknown>[]
  sample_task_records: Record<string, Record<string, unknown>[]>
}

export interface DemandReplanResult {
  task: { id: string; describe: string; zone: string; department: string; duration_min: number; priority: number }
  cpsat: { status: string; latency_ms: number; scheduled: number; n_tasks: number; demand_task_placed: boolean }
  rl: { status: string; dispatcher: string; latency_ms: number; scheduled: number; n_tasks: number; violations: number; demand_task_placed: boolean }
  speedup_x: number
}

export interface ReroutePath { train_id: string; train_class: string; sections: string[]; added_delay_min: number; within_limit: boolean }
export interface TrackSwap { section_id: string; blocked_track: string; swap_to_track: string; locals_affected_per_hour: number; max_single_line_min: number }
export interface ReroutingOpportunity {
  task_id: string; zone_ref: string; shortfall_min: number
  reroute_paths: ReroutePath[]; track_swap: TrackSwap | null
  task_label?: string; department?: string; duration_min?: number
}
export interface ReroutingData { unscheduled_total: number; opportunities: ReroutingOpportunity[] }

export interface SimTickTask {
  id: string; describe: string; label?: string; zone: string; department: string
  duration_min: number; priority: number
}
export interface SimTickWindow {
  id: string; section_id: string; zone_ref: string
  start_s: number; end_s: number; gap_type: string
}
export interface SimTickPlacement {
  task: SimTickTask; placed: boolean; window: SimTickWindow | null; reason: string
}
export interface SimTickData { at_s: number; results: SimTickPlacement[]; algorithm: string }

export interface NextGap { start_hhmm: string; end_hhmm: string; gap_type: string; usable_min: number }
export interface TimelineTrack { track: string; trains: number[]; gaps: [number, number, string, number][] }
export interface SectionBrief {
  section_id: string; status: Status; summary: string
  open_task_count: number; next_gap: NextGap | null
  timeline: TimelineTrack[]; day_start_s: number; now_s: number
}

export interface RerouteView {
  train_id: string; train_name: string; train_class: string
  sections: string[]; added_delay_min: number; within_limit: boolean
  enter_s?: number; exit_s?: number; track?: string
}
export interface RerouteBlock {
  section_id: string; start_s: number; end_s: number
  reroutes: RerouteView[]; no_path: string[]
  track_swap: { blocked_track: string; swap_to_track: string; max_single_line_min: number } | null
  locals_in_window: number
}
export interface ReroutingActive { at_s: number; blocks: RerouteBlock[]; executed: number }

export interface JobCluster {
  id: number; size: number; task_ids: string[]; zones: string[]; departments: string[]
  total_min: number; label: string; lat: number; lon: number
  compatible: number; requires_iwp: number; incompatible: number; cross_pairs: number
}
export interface ClustersData {
  n_tasks: number; n_clusters: number; cut_km: number; method: string; clusters: JobCluster[]
}

export interface ProofData {
  interval_tree: { queries: number; scan_ms: number; tree_ms: number; speedup_x: number; identical: boolean }
  gaps: { total: number; micro: number; night: number; megablock: number; usable_hours: number }
  cpsat: { status: string; gap_pct: number; placed: number; n_tasks: number; wall_s: number }
  rl: { policy: string; gap_pct: number; speedup_x: number; instances: number } | null
  clusters: { tasks: number; clusters: number; cross_pairs: number; compatible: number }
  live_sim: { arrived: number; placed: number; moved_aside: number }
  rerouting: { unplaced: number; with_lever: number; reroute_paths: number; track_swaps: number; executed: number }
}

const j = async <T,>(url: string, init?: RequestInit): Promise<T> => {
  const r = await fetch(url, init)
  if (!r.ok) throw new Error(`${url} -> ${r.status}`)
  return r.json() as Promise<T>
}

export const api = {
  network: () => j<NetworkData>('/api/network'),
  tasks: () => j<{ tasks: Task[]; total: number; by_department: Record<string, number> }>('/api/tasks'),
  matrix: (limit = 18) => j<MatrixData>(`/api/compatibility/matrix?limit=${limit}`),
  gaps: () => j<GapData>('/api/gaps'),
  plan: () => j<PlanData>('/api/plan'),
  trains: (at: number) => j<TrainsData>(`/api/trains?at_s=${Math.round(at)}`),
  events: () => j<{ events: EventItem[] }>('/api/events'),
  injectDemand: () => j<DemandReplanResult>('/api/tasks/demand', { method: 'POST' }),
  chat: (q: string, atS = 0) => j<ChatAnswer>('/api/chat', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ q, at_s: Math.round(atS) }),
  }),
  impact: (hoursPerConflict?: number, waitDays?: number) => j<ImpactData>(
    `/api/metrics/impact${hoursPerConflict !== undefined ? `?hours_per_conflict=${hoursPerConflict}&wait_days=${waitDays}` : ''}`),
  scorecard: () => j<ScoreCardData>('/api/metrics/scorecard'),
  rl: () => j<RlData>('/api/rl/comparison'),
  adapters: () => j<AdapterData>('/api/adapters'),
  reroutingOpportunities: () => j<ReroutingData>('/api/rerouting/opportunities'),
  simTick: (atS: number) => j<SimTickData>(`/api/sim/tick?at_s=${Math.round(atS)}`, { method: 'POST' }),
  sectionBrief: (id: string, atS: number) =>
    j<SectionBrief>(`/api/sections/${encodeURIComponent(id)}/brief?at_s=${Math.round(atS)}`),
  clusters: () => j<ClustersData>('/api/tasks/clusters'),
  reroutingActive: (atS: number) => j<ReroutingActive>(`/api/rerouting/active?at_s=${Math.round(atS)}`),
  proof: () => j<ProofData>('/api/algorithms/proof'),
  formOptions: () => j<FormOptions>('/api/form/options'),
  submitTask: (b: SubmitBody) => j<SubmitResult>('/api/tasks/submit', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b),
  }),
  clearUserTasks: () => j<{ removed: number }>('/api/tasks/user/clear', { method: 'POST' }),
  taskScores: (includeSim = false) => j<ScoresData>(`/api/tasks/scores?include_sim=${includeSim}`),
  explainGaps: (section = '', track = '', day = 1, from = 5, to = 9) =>
    j<GapTrace>(`/api/explain/gaps?section=${section}&track=${track}&day=${day}&hour_from=${from}&hour_to=${to}`),
  explainClusters: () => j<ClusterTrace>('/api/explain/clusters'),
  explainSchedule: () => j<ScheduleDemo>('/api/explain/schedule'),
  creationSummary: () => j<CreationSummary>('/api/creation/summary'),
  scheduleWeek: () => j<WeekSchedule>('/api/schedule/week'),
  scheduleMonth: () => j<MonthSchedule>('/api/schedule/month'),
  suddenInject: (b: SuddenBody) => j<SuddenResult>('/api/sudden/inject', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b),
  }),
  suddenLog: () => j<{ log: SuddenResult[]; n: number }>('/api/sudden/log'),
  suddenMetrics: () => j<SuddenMetrics>('/api/sudden/metrics'),
  suddenClear: () => j<{ cleared: number }>('/api/sudden/clear', { method: 'POST' }),
  paxExperiment: () => j<PaxExperiment>('/api/pax/experiment'),
  paxWeekly: () => j<PaxWeekly>('/api/pax/weekly'),
  planVerify: () => j<PlanVerify>('/api/plan/verify'),
  methodsSummary: () => j<MethodsSummary>('/api/methods/summary'),
  planRobustness: () => j<Robustness>('/api/plan/robustness'),
  buildMonth: (force = false) => j<{ status: string }>(`/api/schedule/month/build?force=${force}`, { method: 'POST' }),
}

export const hhmm = (s: number) => {
  const t = ((s % 86400) + 86400) % 86400
  return `${String(Math.floor(t / 3600)).padStart(2, '0')}:${String(Math.floor((t % 3600) / 60)).padStart(2, '0')}`
}
export const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

// ---------------------------------------------------------------- task pipeline (form -> score -> plan)

export interface FormOptions {
  departments: { code: string; label: string }[]
  task_types: { code: string; label: string; department: string; min: number; max: number; power_block: boolean }[]
  sections: { id: string; label: string; line: string; tracks: number }[]
  stations: { code: string; name: string }[]
  allotments: Record<string, string[]>
}

export interface SubmitBody {
  description: string; department: string; zone_ref: string; task_type: string
  duration_min: number; priority: number; allows_with: string[]; at_s: number
}

export interface CreationOptionView {
  lever: string; lever_label: string; section_id: string; track: string; day: number
  start_s: number; end_s: number; raw_min: number; delay_min: number
  trains: { train_id: string; class: string; action: string }[]; note: string
}

export interface PairView { other: string; department: string; verdict: Verdict; reason: string; rule: string }
export interface ScoreView {
  task_id: string; score: number; cluster_id: number | null; mates: number
  compatible: number; requires_iwp: number; incompatible: number; standalone: boolean
  pairs: PairView[]
}
export interface ScheduleView {
  start_s: number; end_s: number; section_id: string; track: string; gap_type: string
  integrated_with: string[]; created: CreationOptionView | null; reason: string; steps: string[]
  day: string; hhmm: string
}
export interface ScoredTask {
  id: string; source: string; department: string; label: string; description: string
  zone: string; zone_kind: string; duration_min: number; priority: number
  allows_with: string[] | null
  score: ScoreView | null
  cluster: { id: number; label: string; size: number } | null
  schedule: ScheduleView | null
  unplaced_reason: string | null
}
export interface ScoresData {
  tasks: ScoredTask[]; clusters: JobCluster[]
  summary: { n_tasks: number; n_clusters: number; mean_score: number; n_user: number; n_shared: number }
}
export interface SubmitResult {
  task: ScoredTask; cluster: JobCluster | null; scheduling_ms: number
  rejected_by_allotment: boolean; pool: { n_tasks: number; n_clusters: number }
}

// ---------------------------------------------------------------- explainers

export interface GapRow {
  prev: { train_id: string; class: string; enter_s: number; exit_s: number }
  next: { train_id: string; class: string; enter_s: number; exit_s: number }
  gap_min: number; after_buffers_min: number; usable_min: number; keep: boolean; reliability_pct: number
  reason: string; creation: CreationOptionView | null
}
export interface GapTrace {
  section_id: string; track: string; day: number; hour_from: number; hour_to: number
  buffer_min: number; overhead_min: number; min_workable_min: number; min_raw_min: number
  n_trains: number; rows: GapRow[]; kept: number; dropped: number; near_misses: number
  windows: { id: string; start_s: number; end_s: number; gap_type: string; usable_min: number }[]
  choices: { id: string; tracks: string[]; label: string }[]
}
export interface ClusterTrace {
  cut_km: number; method: string
  points: { index: number; id: string; x_km: number; y_km: number; lat: number; lon: number
            department: string; zone: string; label: string; cluster: number }[]
  merges: { a: number; b: number; distance_km: number; size: number; id: number }[]
  clusters: JobCluster[]; scores: Record<string, number>; cluster_labels: Record<string, string>
}
export interface ScheduleDemo {
  order: string[]
  results: {
    id: string; from_task: string; shortened_from: number | null; department: string; label: string; zone: string
    duration_min: number; placed: boolean; start_s: number | null; end_s: number | null
    hhmm: string | null; section_id: string | null; track: string | null; gap_type: string | null
    integrated_with: string[]; created: CreationOptionView | null; reason: string; steps: string[]
  }[]
  clusters_used: number[]
}
export interface CreationSummary {
  survey: {
    track_days: number; natural_gaps: number; near_gaps: number; created: number
    RETIME: number; REROUTE: number; usable_hours_added: number; delay_train_min: number
    trains_held: number; trains_rerouted: number
  }
  min_workable_min: number
  weekly: {
    natural_placed: number; final_placed: number; n_tasks: number
    used: { window_id: string; task_id: string; task: string; department: string; section_id: string
            track: string; lever: string; delay_min: number; note: string; start_s: number; end_s: number }[]
  }
}

// ---------------------------------------------------------------- schedules

export interface PlanEntry {
  task_id: string; label: string; description: string; department: string; zone: string
  section_id: string; track: string; start_s: number; end_s: number; gap_type: string
  source: string; priority: number; cluster: number | null; created: boolean; tag: string
}
export interface WeekSchedule {
  entries: PlanEntry[]
  unplaced: { task_id: string; label: string; department: string; zone: string; duration_min: number; reason: string }[]
  by_day: Record<string, number>
  summary: {
    n_tasks: number; placed: number; unplaced: number; micro_gap: number; night: number
    megablock: number; from_created_gaps: number; natural_only_placed: number; plan_placed: number
    solver: string; gap_pct: number; wall_s: number
  }
}
export interface MonthSchedule {
  status: 'idle' | 'running' | 'done' | 'error'; progress: number; total_weeks: number
  error: string | null
  weeks: { week: number; entries: PlanEntry[]; n_tasks: number; placed: number
           carried_in: number; carried_out: number; micro_gap: number; created: number }[]
  summary: { n_tasks: number; placed: number; micro_gap: number; created: number; backlog_end: number }
}

export interface ScoreCardItem {
  id: string; algorithm: string; what: string
  before: { label: string; value: number; unit: string }
  after: { label: string; value: number; unit: string }
  detail: string; how: string; repro: string
}
export interface ScoreCardData {
  cards: ScoreCardItem[]
  headline: {
    capacity_gain_pct: number; urgent_jobs_natural: number; urgent_jobs_creation: number
    urgent_jobs_total: number; blocks_manual: number; blocks_ours: number
    jobs_placed_manual: number; jobs_placed_ours: number
  }
  limits: string[]
}


// ---------------------------------------------------------------- sudden tasks and passengers

export interface SuddenBody {
  level: 'low' | 'medium' | 'high' | 'critical'
  zone_ref?: string | null; department?: string | null; duration_min?: number | null
  description?: string; at_s: number
}
export interface SuddenMoved {
  task_id: string; label: string; department: string; priority: number; zone: string
  from: { start_s: number; end_s: number; hhmm: string }
  to: { start_s: number; end_s: number; hhmm: string } | null
}
export interface SuddenResult {
  id: string; priority: number; level: string
  task: { label: string; department: string; zone: string; duration_min: number; describe: string }
  at_s: number; placed: boolean; method: 'gap' | 'created' | 'bumped' | 'late' | 'none'
  window: { section_id: string; zone_ref: string; track: string; start_s: number; end_s: number
            gap_type: string; hhmm: string; created_by: string | null } | null
  response_ms: number; deadline_s: number | null; deadline_hhmm: string | null; margin_min: number | null
  exposure: { passengers: number; trains: number; trains_per_hour: number; span_min: number } | null
  created: { lever: string; lever_label: string; note: string; delay_min: number; pax_delay: number } | null
  bumped: SuddenMoved[]
  reroutes: { diverted: number; added_delay_min: number; trains: { id: string; delay: number }[]
              locals: number; track_swap: { blocked_track: string; swap_to_track: string } | null } | null
  steps: string[]; reason: string; plan_resolve_s: number | null; network_tph: number
}
export interface SuddenMetrics {
  n: number; placed?: number; in_time?: number
  by_method?: Record<string, number>; by_level?: Record<string, { n: number; placed: number }>
  median_ms?: number; max_ms?: number; plan_resolve_ms?: number | null; speedup_x?: number | null
  bumped_total?: number; replaced_total?: number; deferred_total?: number; trains_diverted?: number
  pax_within_reach?: number; site_tph?: number | null; network_tph?: number
  created_delay_train_min?: number; manual_wait_days?: number
}
export interface PaxRun { placed: number; passengers: number; mean_tph: number; mean_wait_h: number; in_peak: number }
export interface PaxExperiment {
  manual: PaxRun
  jobs: number; network_tph: number; passengers_saved_pct: number; how: string
  aware: { placed: number; passengers: number; mean_tph: number; mean_wait_h: number; in_peak: number }
  unaware: { placed: number; passengers: number; mean_tph: number; mean_wait_h: number; in_peak: number }
}

export interface PaxWeekly {
  status: 'idle' | 'running' | 'done' | 'error'
  error: string | null
  data: {
    aware: { placed: number; pax: number; status: string }
    unaware: { placed: number; pax: number; status: string }
    common_jobs: number; aware_common: number; unaware_common: number; saved_pct: number; how: string
  } | null
}

export interface PlanVerify {
  ok: boolean; n_violations: number; violations: string[]; total_checks: number
  checks: Record<string, number>; n_jobs: number; status: string
}
interface RobStats { mean: number; risky: number; expected_overruns: number; blocks: number }
export interface Robustness {
  samples: number; plan: RobStats; before_centring: RobStats | null; centred_moves: number
  weakest: { task_id: string; section_id: string; track: string; start_s: number; p_clear: number; slack_after_min: number }[]
  ablation_status: 'idle' | 'running' | 'done' | 'error'
  ablation: { placed: number; solver: string; raw: RobStats; centred: RobStats; moved: number } | null
  error: string | null; how: string
}

interface Pol { pax_min: number; train_min: number; late5: number; sections: number; label: string }
interface FlatBuf { placed: number; status: string; referee_ok: boolean; mean: number; fragile: number; expected_overruns: number
                    blocks: number; reserved_hours: number; work_hours: number; topped_up: number }
export interface MethodsSummary {
  status: 'idle' | 'running' | 'done' | 'error'
  error: string | null
  results: {
    predictive?: {
      failures: number; verdict: string; how: string; caveat: string
      reactive: PredRow
      predictive: (PredRow & { p_detect: number })[]
    }
    twin?: {
      verdict: string; how: string; caveat: string
      cases: { label: string; best: 'HOLD' | 'DIVERT' | 'DIVERT_SINGLE'; spread_x: number | null
               policies: Record<'HOLD' | 'DIVERT' | 'DIVERT_SINGLE', Pol> }[]
    }
    bundling?: {
      verdict: string; how: string; caveat: string; instances: number; blocks_before: number; blocks_after: number
      held_before: number; held_after: number; merges: number; all_legal: boolean
    }
    buffers?: {
      verdict: string; how: string; caveat: string; jobs_lost: number; flat: FlatBuf; adaptive: FlatBuf
      learned: { department: string; rain: boolean; n: number; learned_mean: number; true_mean: number }[]
    }
  }
}
interface PredRow {
  events: number; emergencies: number; prevented: number; train_min: number; pax_delay_min: number
  pax_reach: number; peak_jobs: number; placed: number; late: number
}
