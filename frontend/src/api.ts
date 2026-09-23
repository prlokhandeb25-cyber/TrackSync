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

export interface ChatAnswer {
  text: string
  facts: { k: string; v: string }[]
  trace: string[]
  intent: string
  suggestions: string[]
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
  id: string; describe: string; zone: string; department: string
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
  chat: (q: string) => j<ChatAnswer>('/api/chat', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ q }),
  }),
  impact: () => j<ImpactData>('/api/metrics/impact'),
  rl: () => j<RlData>('/api/rl/comparison'),
  adapters: () => j<AdapterData>('/api/adapters'),
  reroutingOpportunities: () => j<ReroutingData>('/api/rerouting/opportunities'),
  simTick: (atS: number) => j<SimTickData>(`/api/sim/tick?at_s=${Math.round(atS)}`, { method: 'POST' }),
  sectionBrief: (id: string, atS: number) =>
    j<SectionBrief>(`/api/sections/${encodeURIComponent(id)}/brief?at_s=${Math.round(atS)}`),
  clusters: () => j<ClustersData>('/api/tasks/clusters'),
  reroutingActive: (atS: number) => j<ReroutingActive>(`/api/rerouting/active?at_s=${Math.round(atS)}`),
  proof: () => j<ProofData>('/api/algorithms/proof'),
}

export const hhmm = (s: number) => {
  const t = ((s % 86400) + 86400) % 86400
  return `${String(Math.floor(t / 3600)).padStart(2, '0')}:${String(Math.floor((t % 3600) / 60)).padStart(2, '0')}`
}
export const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
