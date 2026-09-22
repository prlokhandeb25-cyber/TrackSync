# BUILD PROMPT — "RailBlock AI": AI-Powered Automatic Block Planning for Indian Railways

> **Paste this entire document into Antigravity as the project brief.**
> It is a technical specification, not a discussion. Work through it top to bottom.

---

## 0. ROLE, MISSION, AND HOW YOU WILL BE JUDGED

You are the implementing engineer for a Smart India Hackathon (SIH) prototype under the problem
statement: **"AI-powered automatic block planning to maximize asset availability for train
operations on Indian Railways."**

**Hard constraint: this must be a working, demonstrable prototype in a few days, not weeks.**
Every decision you make should be biased toward "demonstrable in the demo" over "architecturally
pure." Where this document gives you a fallback, take the fallback the moment you are behind.

### 0.1 The five judging criteria — keep these in your head for every file you write

| # | Criterion | What the code must prove |
|---|-----------|--------------------------|
| J1 | **Innovation** | Offline RL trained on CP-SAT expert trajectories (novel for this domain) + automated department-compatibility resolution |
| J2 | **Feasibility** | It runs. End-to-end. On real-ish data. With a seed and a one-command demo |
| J3 | **Scalability** | Adding a corridor/zone = adding config + data files. **Zero code changes.** This must be literally true and demonstrated |
| J4 | **Govt. integration** | Clean adapter boundaries mapping onto BDMS, COA, TMS, SMMS, TDMS — reads as a plug-in, not a replacement |
| J5 | **Before/after impact** | A metrics harness that outputs hard numbers comparing manual/decentralized planning vs our system |

**Requirement:** every top-level module gets a `README.md` header line naming which criteria it
serves, e.g. `<!-- serves: J1, J5 -->`. The final `REPORT.md` must contain a traceability table
mapping each criterion to the artifacts that demonstrate it. Judges will ask; the repo must answer.

### 0.2 Two innovation claims you must protect

1. **Primary (J1):** CP-SAT is used *twice* — as the optimal batch planner, and as the **expert
   whose solutions are converted into trajectories to train an offline RL dispatcher**. The RL
   dispatcher then does millisecond-latency reactive re-planning when unplanned defects appear
   mid-schedule. Reference: *"Offline Reinforcement Learning for Learning to Dispatch for Job Shop
   Scheduling"* (van Remmerden, Bukhsh, Zhang, 2024, arXiv:2409.10589). The domain transfer is:
   **JSSP jobs → maintenance tasks; JSSP machines → block corridor time-slots on track sections.**
2. **Secondary (J1 + J5):** today the S&T, OWD and PWI department heads negotiate work
   compatibility **manually, by phone/meeting**. We automate that negotiation into a computed
   compatibility matrix. This is the most concrete before/after story we have — treat it as a
   first-class feature with its own visible UI, not as backend plumbing.

---

## 1. SCOPE TRIAGE — BUILD THIS, THEN THIS, NEVER THAT

**Read this section before writing any code.** Do not start Tier B until every Tier A item is
working end-to-end. Do not build Tier C at all.

### TIER A — CORE. Must be built, must be demoed. Non-negotiable.

| A# | Item | Section |
|----|------|---------|
| A1 | Network + timetable data pipeline for **one corridor**, with a hard validation gate | §3, §4 |
| A2 | Domain model: sections, trains, tasks, departments, **track status FSM** | §5 |
| A3 | **Traffic-gap engine**: night window, Sunday megablock, **and inter-train micro-gaps** | §6 |
| A4 | **Department compatibility matrix** — all 3 rule classes, computed + visible in UI | §7 |
| A5 | **Station-tier-dependent** scheduling policy, derived from real train frequency | §8 |
| A6 | Rerouting levers: intercity/freight path substitution + **local up/down track swap** | §9 |
| A7 | CP-SAT baseline scheduler producing a weekly block plan | §10 |
| A8 | Expert-trajectory generator → offline RL dataset | §11 |
| A9 | **One** offline RL agent (CQL-style DQN) + behavior-cloning baseline + greedy baseline | §12 |
| A10 | Demand-task injection → RL reactive re-plan, with measured latency | §13 |
| A11 | UI: Maharashtra map + moving train dots + natural-language status board + compatibility matrix + per-section track status | §14 |
| A12 | Before/after metrics harness → `metrics.json` + CSV + UI Impact tab | §15 |
| A13 | Government-system adapter interfaces (BDMS/COA/TMS/SMMS/TDMS) with mock implementations | §16 |

### TIER B — HIGH VALUE. Build only after all of Tier A is green.

| B# | Item | Why it matters |
|----|------|----------------|
| B1 | **Second and third RL algorithms** (masked A2C/AWAC-style actor-critic, + optionally IQL) and a head-to-head comparison table/chart | Directly demoable J1 result; the *comparison itself* is a slide |
| B2 | Smooth animated train dots along real geometry + time-scrubber + play/pause/speed | "Wow factor" for J2/J5 |
| B3 | Continuous stochastic demand-task arrivals (not just one scripted injection) | Proves reactivity, not a canned trick |
| B4 | Real delay/punctuality distributions fitted from sourced data and injected into the sim | Realism for J2 |
| B5 | Multi-corridor run (add a 2nd corridor via config only) to *prove* J3 on stage | Scalability claim becomes a demo, not a sentence |
| B6 | Integrated Work Permission quota modelling + an "IWP requests" approval panel | Domain depth |
| B7 | k-shortest-path rerouting across the wider Maharashtra graph | Deeper version of A6 |

### TIER C — ROADMAP / PPT SLIDE ONLY. **DO NOT BUILD.**

Write these into `ROADMAP.md` with 2–4 lines each so the team can lift them straight into slides.

- **Evolutionary / genetic multi-objective layer** for weekly/monthly calendar search (NSGA-II over
  the CP-SAT+RL output, Pareto front of availability vs cost vs risk). **Explicitly deferred. Do not
  implement any GA code.**
- Live integration with the real BDMS/COA/TMS/SMMS/TDMS instances (we ship adapters + mocks only).
- Field-worker mobile app for defect capture and work-completion sign-off.
- IoT/CV-based automated defect detection feeding the task pool.
- Division-wide → zone-wide → national rollout with federated model training per zone.
- Crew/gang rostering and material-logistics optimisation inside the same solver.
- Signalling-level microsimulation digital twin for block-clearance verification.

### DO NOT WASTE TIME ON (hard stop list)

- ❌ Scraping or reverse-engineering **M-Indicator** or **RailOne**. They have no public API. This
  was already investigated. Go straight to the sources in §3.
- ❌ Authentication, user accounts, roles, multi-tenancy, or any login screen.
- ❌ Microservices, Docker Compose orchestration, Kubernetes, message queues. One FastAPI process
  + one Vite dev server. That is the whole deployment.
- ❌ A real RDBMS. Use SQLite and/or Parquet/JSON files.
- ❌ Unit-test coverage targets. Write tests **only** for the validation gate (§3.4), the
  compatibility rules (§7), and the track-status FSM (§5.3). Those three, nothing more.
- ❌ Any GA/evolutionary code (Tier C).
- ❌ Perfecting the map basemap. §14 gives you a fallback that removes all tile/network risk.

---

## 2. ARCHITECTURE AND STACK

### 2.1 Layered architecture

```
┌────────────────────────────────────────────────────────────────────┐
│  UI  (React + Vite + TS)                                           │
│  Map · Status Board · Compatibility Matrix · Track Status ·        │
│  RL Comparison · Impact (Before/After)                             │
└───────────────▲────────────────────────────────────────────────────┘
                │ REST + WebSocket (JSON)
┌───────────────┴────────────────────────────────────────────────────┐
│  API / Orchestrator  (FastAPI)                                     │
└───────────────▲────────────────────────────────────────────────────┘
                │
   ┌────────────┼───────────────┬──────────────────┬────────────────┐
   │            │               │                  │                │
┌──┴────────┐┌──┴───────────┐┌──┴──────────────┐┌──┴────────────┐┌──┴─────────┐
│ Simulation││ Gap Engine   ││ CP-SAT Planner  ││ RL Dispatcher ││ Metrics    │
│ Engine    ││ (§6)         ││ (batch/weekly)  ││ (reactive)    ││ Harness    │
│ (§13)     ││              ││ (§10)           ││ (§12)         ││ (§15)      │
└──┬────────┘└──────────────┘└──────┬──────────┘└──────▲────────┘└────────────┘
   │                                │ expert trajectories│
   │                                └───────────────────►┘
┌──┴─────────────────────────────────────────────────────────────────┐
│  Domain Core: network graph · trains · tasks · departments ·       │
│  compatibility rules · track-status FSM  (pure Python, no I/O)     │
└───────────────▲────────────────────────────────────────────────────┘
                │
┌───────────────┴────────────────────────────────────────────────────┐
│  Data Layer: timetable ingest · validation gate · synthetic task    │
│  generator · IR-system adapters (BDMS/COA/TMS/SMMS/TDMS mocks)      │
└────────────────────────────────────────────────────────────────────┘
```

**The domain core must be pure and I/O-free.** Everything above it (solver, RL, sim, API, UI) reads
the same in-memory objects. This is what makes J3 (scalability) defensible.

### 2.2 Stack (do not substitute without a reason you write down)

- **Backend:** Python 3.11, FastAPI, Uvicorn, Pydantic v2
- **Optimisation:** `ortools` (CP-SAT)
- **RL:** PyTorch. Hand-roll the agents (they are small); do **not** pull in a heavy offline-RL
  framework — the masking requirement (§12.3) makes custom code faster than fighting a library.
- **Data:** pandas, pyarrow, numpy, SQLite (stdlib), NetworkX (graph + shortest paths)
- **Frontend:** React 18 + TypeScript + Vite + TailwindCSS. Map via **MapLibre GL JS** *or*
  plain **SVG/Canvas** (see §14.2 fallback). Charts via Recharts.
- **Reproducibility:** one `SEED` in `config/config.yaml`, threaded into numpy, random, torch, and
  the CP-SAT `random_seed` parameter. Every run must be reproducible.

### 2.3 Repository layout

```
railblock-ai/
├── README.md                  # what it is, how to run, judging traceability
├── ROADMAP.md                 # Tier C items only
├── ASSUMPTIONS.md             # EVERY invented number/rule, with rationale  (see §2.4)
├── REPORT.md                  # generated: results, metrics, before/after, RL comparison
├── config/
│   ├── config.yaml            # seed, time budgets, weights, thresholds
│   └── network/
│       ├── central_line.yaml  # corridor definition — ADD A FILE = ADD A CORRIDOR
│       └── stations.geojson   # station coordinates
├── data/
│   ├── raw/                   # whatever you sourced, untouched
│   ├── processed/             # validated timetable parquet
│   └── validation_report.json
├── backend/
│   ├── domain/                # network, train, section, task, department, fsm, compatibility
│   ├── data/                  # ingest, validate, synth_tasks, delay_model
│   ├── gaps/                  # traffic-gap engine
│   ├── planner/               # cp_sat model, objective, solution decoding
│   ├── rl/                    # env, mdp, trajectory_gen, agents/, train.py, evaluate.py
│   ├── sim/                   # discrete-event simulation + demand injection
│   ├── metrics/               # before/after harness, baseline "manual" planner
│   ├── adapters/              # bdms.py coa.py tms.py smms.py tdms.py (mock impls)
│   └── api/                   # FastAPI routes + websocket
├── frontend/
├── scripts/
│   ├── 00_fetch_data.py
│   ├── 01_validate.py
│   ├── 02_generate_expert_data.py
│   ├── 03_train_rl.py
│   ├── 04_evaluate_rl.py
│   ├── 05_run_impact_study.py
│   └── demo.py                # one command → seeds everything for the live demo
└── artifacts/                 # metrics.json, comparison.csv, charts/*.png, screenshots/
```

### 2.4 `ASSUMPTIONS.md` is mandatory

Maintenance-task data, coordination times, setup/release durations, speed restrictions and
department allotments have **no public real-world source**. Every time you invent a number or a
rule, append a row: `| ID | Assumption | Value | Why this value | How to replace with real data |`.
The team will be asked "where did this come from?" on stage — the repo must have the answer, and
"we invented it, here is exactly which parts" is a strong answer. Silent invention is a weak one.

---

## 3. DATA: SOURCING, SCHEMA, AND THE VALIDATION GATE

### 3.1 Target scope for the prototype

**Primary corridor (build this first):** Mumbai Central Railway main line —
**CSMT → Byculla → Dadar → Kurla → Ghatkopar → Thane → Dombivli → Kalyan**, then the Karjat branch
(**Ambernath → Badlapur → Vangani → Shelu → Neral → Bhivpuri Road → Karjat**).

This corridor is chosen deliberately: it contains both very-high-frequency stations (CSMT, Dadar,
Thane, Kalyan) and genuinely low-frequency outer stations (**Neral, Bhivpuri Road**), which is
exactly what §8's station-tier logic needs to demonstrate.

**Secondary (for the Maharashtra map + intercity/freight):** long-distance links
Mumbai–Pune, Mumbai–Nashik–Bhusawal, Bhusawal–Nagpur, Pune–Solapur. These carry the
intercity/freight trains that make rerouting (§9) meaningful.

### 3.2 Data sourcing — timeboxed to 90 minutes, then stop

Attempt in this order:

1. **`data.gov.in`** — Indian Railways train time-table / train schedule datasets (CSV). Best
   licensed source for intercity trains.
2. **Open GitHub datasets** — e.g. `anandology/railways` and similar public repos containing
   station lists, train schedules, and station coordinates.
3. **Mumbai suburban timetable** — needed specifically for the suburban dot density on the map.
   Look for open CSV/JSON dumps of Central/Western/Harbour line local timetables in public repos
   or open-data portals.
4. **OpenStreetMap** (Overpass or a pre-extracted GeoJSON) for **railway line geometry and station
   coordinates** in Maharashtra.

> **DO NOT** attempt M-Indicator or RailOne. No public API. Already ruled out.

**FALLBACK (take it at the 90-minute mark, no guilt):** generate a synthetic timetable that
*matches real published structure* — ~1,100–1,300 suburban services/day on the Central main line,
3–5 min peak headway (07:00–11:00, 17:00–21:00), 8–15 min off-peak, last down service ~00:45,
first up service ~03:55, plus ~25–40 intercity/freight paths/day on the long-distance links. Write
the source of each structural number into `ASSUMPTIONS.md`. A structurally faithful synthetic
timetable beats a half-scraped real one — say so in the README and move on.

### 3.3 Canonical schemas (Pydantic models + parquet columns)

```python
Station:  id, name, code, lat, lon, corridor_id, is_junction, platforms
Section:  id, from_station, to_station, corridor_id, length_km, line_speed_kmph,
          tracks: ["UP","DN"] (or more), geometry: [[lat,lon],...],
          status: TrackStatus, alternate_section_ids: [id]   # for rerouting
Train:    id, number, name, train_class, origin, destination, days_of_week,
          stops: [ {station_id, arr, dep, section_id_next} ],
          priority (int), max_acceptable_delay_min, reroutable: bool
TrainClass: SUBURBAN_LOCAL | INTERCITY (Rajdhani/Deccan Queen/…) | FREIGHT_MAIL
Task:     id, department, task_type, section_id, work_zone (SECTION|STATION_NODE),
          duration_min, priority (1..5), category: PLANNED|DEMAND,
          requires_power_block: bool, requires_traffic_block: bool,
          released_at (datetime), due_by (datetime), resulting_status_on_completion
Department: S_AND_T | OWD | PWI
Allotment: department, section_ids[], valid_from, valid_to    # issued by control office
```

### 3.4 THE VALIDATION GATE — this is a blocking requirement

Write `scripts/01_validate.py`. It emits `data/validation_report.json` + a human-readable
`data/validation_report.md`, with **PASS/FAIL per check**. `scripts/demo.py` and the API **must
refuse to run** on any FAIL unless `--force` is passed and a loud banner is printed.

Checks (all must be implemented):

| ID | Check | Fail condition |
|----|-------|----------------|
| V1 | Monotonic times | Any train whose stop times are not strictly non-decreasing (after midnight-wrap normalisation) |
| V2 | Midnight wrap | Any service crossing 00:00 not correctly day-indexed |
| V3 | Dwell sanity | Dwell < 20 s or > 20 min at a non-terminal stop |
| V4 | Run-time sanity | Implied point-to-point speed > line speed, or < 15 km/h, for any section hop |
| V5 | **No impossible overlaps** | Two trains occupying the same `(section, track, direction)` with a separation < `min_headway_s` (default 120 s) |
| V6 | Referential integrity | Any stop/section referencing an unknown station or section |
| V7 | Coverage | Corridor has < 200 services/day, or any section has zero traffic |
| V8 | Geometry | Any section lacking coordinates for both endpoints |
| V9 | Conservation | Every train has a valid origin, destination and ≥ 2 stops |
| V10 | Gap consistency | Recomputed section occupancy sums + idle time ≠ 24 h (± 1 min) |

**Auto-repair where safe** (clip absurd dwells to bounds, resolve sub-headway conflicts by nudging
the lower-priority train) and **log every repair** into the report. The report's repair count is
itself a slide-worthy number: "we ingested X services, auto-repaired Y inconsistencies,
and ran the simulation on validated data."

### 3.5 Simulation-fidelity check (also blocking)

Replay the validated timetable through the simulation engine **with zero maintenance tasks**.
Assert: every train completes, zero section conflicts, and mean arrival deviation ≈ 0 (or matches
the injected delay distribution within tolerance). If this fails, the scheduling results on top of
it are meaningless. Fix before proceeding.

### 3.6 Delay / punctuality realism (Tier B4, implement cheaply in Tier A)

If real punctuality data is found, fit per-`train_class` delay distributions and sample from them.
**FALLBACK (do this first, it takes 20 minutes):** documented synthetic distributions —
suburban: `Gamma` with mean ≈ 2.5 min, P(delay > 10 min) ≈ 4 %; intercity: mean ≈ 12 min, heavy
right tail; freight: mean ≈ 35 min, very heavy tail. Add peak-hour multipliers. Log in
`ASSUMPTIONS.md`. Perfectly on-time synthetic schedules make the prototype look naive — do not
ship those.

---

## 4. NETWORK CONFIG — THE SCALABILITY PROOF (J3)

`config/network/*.yaml` fully defines a corridor: stations, sections, track counts, line speeds,
alternate routes, megablock windows, department allotments. **The code must contain zero
corridor-specific names, IDs or special cases.** Adding `pune_solapur.yaml` + its timetable rows
must make the system plan that corridor with no code edit.

Acceptance test (write it): `tests/test_scalability.py` loads a second, tiny synthetic corridor
config and asserts the full pipeline (gaps → CP-SAT → RL inference → metrics) runs on it unchanged.
**This single test is your J3 evidence.** In the PPT, screenshot the test passing.

---

## 5. DOMAIN MODEL

### 5.1 Network graph

Undirected multigraph. Nodes = stations. Edges = sections, each with ≥ 1 track
(`UP`, `DN`, sometimes `UP_SLOW/DN_SLOW/UP_FAST/DN_FAST` on the Mumbai main line — model the
fast/slow pair if the data supports it; otherwise UP/DN and note the simplification).

A **work zone** is either a `SECTION` (between two stations, e.g. Matunga–Dadar) or a
`STATION_NODE` (the station yard itself, e.g. Matunga). This distinction is **required** by the
compatibility rules in §7 — do not collapse it.

### 5.2 Track status states — literal spec

Every section (and station node) carries one status:

| Status | Meaning | Effect on simulation |
|--------|---------|----------------------|
| `FIT` | Normal operation | Trains run at line speed |
| `SICK` | Defect identified; maintenance required | Line speed reduced to `sick_speed_kmph` (default 30) until attended; task exists in pool |
| `CAUTION_ORDER` | Work done, operate at reduced/careful speed | Speed capped at `caution_speed_kmph` (default 30); follow-up task auto-created |
| `STOP_AND_START` | Work done, restricted operation: trains must stop and then start | Fixed time penalty per train (`stop_and_start_penalty_s`, default 240 s) + speed cap; follow-up task auto-created |

### 5.3 Track status FSM — implement exactly this, with tests

```
FIT ──defect_reported──────────────► SICK
SICK ──task_scheduled──────────────► SICK  (task.scheduled_window set; status unchanged)
SICK ──block_granted / work_start──► SICK  (section closed to traffic for the block window)
SICK ──work_completed(outcome)─────► FIT | CAUTION_ORDER | STOP_AND_START
CAUTION_ORDER ──followup_completed─► FIT
STOP_AND_START ──followup_completed► CAUTION_ORDER | FIT
ANY ──demand_defect_found_during_work──► SICK + emit new Task(category=DEMAND)
```

Rules:
- `work_completed` **must** remove the task from the active pool, update section status, and push
  the change over the WebSocket so the map and status board update live.
- The outcome (`FIT` / `CAUTION_ORDER` / `STOP_AND_START`) is sampled from a per-`task_type`
  distribution — e.g. a full track-renewal task completes to `FIT` with high probability, a partial
  or time-curtailed job is more likely to complete to `CAUTION_ORDER`. **Key modelling hook:** if a
  task is squeezed into a gap shorter than its required duration, raise the probability of a
  degraded outcome. This is what makes micro-gap scheduling a *trade-off* rather than free lunch,
  and it is a strong answer to the obvious judge question "isn't squeezing work into small gaps
  risky?" — the model prices that risk. Log the distributions in `ASSUMPTIONS.md`.
- `CAUTION_ORDER` and `STOP_AND_START` section-hours are a **direct availability loss** and feed
  the impact metrics (§15). Clearing them faster is the point of the whole system.
- Unit-test every transition and every illegal transition.

### 5.4 Tasks: PLANNED vs DEMAND

- **PLANNED** tasks are decided on a **weekly cycle** — in our scenario, finalised **every Monday**
  for the coming week. These go through the **CP-SAT batch path** (§10).
- **DEMAND** tasks are discovered *during* maintenance execution and were not planned. They must be
  **properly fitted into the existing schedule**, not appended ad hoc at the end. These are the live
  case for the **RL dispatcher** (§12, §13) — fast, reactive, constraint-respecting re-planning.

This split is the architectural justification for having both a solver and a learned policy. Make
it explicit in the README and in the UI (a badge on each task: `PLANNED` / `DEMAND`).

### 5.5 Synthetic task generator

Real maintenance-task data does not exist publicly. Generate it, structured to match reality:

- Per department, realistic task types:
  - **PWI** (Permanent Way Inspector — track & gearing): rail/weld renewal, tamping, ballast
    screening, fish-plate/joint attention, points & crossings attention, gauge correction.
  - **OWD** (Overhead Wire Department — traction/electrical): OHE wire tension adjustment, insulator
    replacement, dropper/jumper repair, mast/cantilever attention, **power block required**.
  - **S&T** (Signalling & Telecom): point-machine servicing, track-circuit fault, signal lamp/LED,
    axle counter, cable and relay-room work, interlocking testing.
- Duration distributions per task type (20 min to 6 h). Priority 1–5. Release times: PLANNED tasks
  released Monday 00:00; DEMAND tasks released stochastically during work execution.
- Weight task locations toward sections that are SICK or under CAUTION_ORDER.
- Flags: `requires_power_block` (OWD work and any work under live OHE), `requires_traffic_block`.
- Emit the generator's parameters into `ASSUMPTIONS.md` and note: *"in deployment these arrive from
  TMS (PWI), SMMS (S&T) and TDMS (OWD) — see §16."*

---

## 6. TRAFFIC-GAP ENGINE (Tier A3) — core scheduling logic, not a UI feature

This is where a large share of our differentiation lives. Build it carefully.

### 6.1 Occupancy timeline

For each `(section, track, direction)` build a 24 h × 7 d occupancy timeline from the validated
timetable: each train hop occupies `[entry_time − headway_buffer, exit_time + headway_buffer]`
where `headway_buffer` defaults to 120 s. Store as an interval tree / sorted interval list.

### 6.2 Gap classification — three types, all required

| Type | Definition | Notes |
|------|------------|-------|
| `NIGHT_WINDOW` | The natural low-traffic window between the **last train** and the **first train** on that section | **Derive it from the data per section — do not hardcode 01:00–04:00.** It will come out around 01:00–04:00 on the main line and be *longer* on outer sections. Deriving it, and showing the derived value differing per section, is a better story than a constant |
| `MEGABLOCK` | Sunday extended maintenance window (Indian Railways' standard practice) | Configurable per corridor in the network YAML. Default for Central main line: **Sunday ~10:30–15:30**. Mark as an assumption and verify against the timetable — real megablocks show as an actual thinning of services |
| `MICRO_GAP` | Any gap between **consecutive trains during normal daytime operation** that is ≥ `min_usable_gap_min` | **This is the differentiating idea.** Most planning only uses night + megablock. We evaluate whether tasks fit into ordinary daytime inter-train gaps too |

### 6.3 Usable duration — model the overhead honestly

A raw gap is **not** working time. Compute:

```
usable_min = raw_gap_min − block_setup_min − block_release_min
```

Defaults (assumptions, configurable): `block_setup_min = 15` (protection, detonators/banner flags,
caution orders issued, men and material on site), `block_release_min = 10` (site clearance, joint
inspection, line clear certificate, speed restriction imposition if any). OWD power blocks add
`power_block_extra_min = 10` for isolation + earthing and again for de-earthing.

So a 40-minute raw gap yields ~15 minutes of real work. **Say this in the UI.** It is exactly the
kind of detail that signals to judges that the team understands railway operations rather than
abstract scheduling.

### 6.4 Gap output

The engine emits `CandidateWindow` records:

```python
CandidateWindow: id, section_id, work_zone, track/direction, start, end,
                 raw_min, usable_min, gap_type, station_tier,
                 trains_affected_if_extended: [train_id],
                 extension_cost_min: float   # cost of stealing time from adjacent trains
```

`extension_cost_min` lets the planner *create* a slightly larger window by delaying/rerouting a
train rather than only consuming existing gaps. This connects §6 to §9.

### 6.5 Fallback ladder

1. **First**: night window only. Prove the whole pipeline end-to-end with one gap type.
2. **Then**: add Sunday megablock (config-driven — cheap).
3. **Then**: add micro-gaps. ← *Do not stop before this; it is a core differentiator.*
4. **Then (Tier B)**: window extension via rerouting cost.

---

## 7. DEPARTMENT COMPATIBILITY (Tier A4) — the "before/after" centrepiece

### 7.1 The real-world process we are replacing

Today: individual workers identify needed work → report to their **department head** → the three
heads (S&T, OWD, PWI) **manually coordinate among themselves** to decide who can work where and
when without conflicting. This is phone calls, meetings, and institutional memory.

**Our system automates that coordination step.** Frame it that way in code comments, the README, the
UI, and the metrics. This is our clearest "before vs after."

### 7.2 Rules — implement literally, in this order

Let `t1`, `t2` be two tasks with departments `d1`, `d2`, work zones `z1`, `z2`, and overlapping
proposed time windows.

**R0 — Allotment constraint (hard precondition).**
Each department is allotted a specific section/segment by the **control office** and may **only**
work within that allotted section. Any task whose `section_id` ∉ `Allotment(dept, date)` is
**infeasible** — reject it at model-build time with a clear reason string.

**R1 — Same work zone, overlapping time, different departments → `REQUIRES_IWP`.**
Two departments that want to work **together in the same section/time** need a special
**"Integrated Work Permission" (IWP)**. This is a *distinct status* from ordinary independent
compatibility — it is not "compatible" and not "incompatible." Model it as a third value. An
IWP-flagged pair may be co-scheduled **only if** an IWP is granted; model IWP as a limited daily
resource (`iwp_quota_per_day`, default 2 per corridor) consumed by each granted co-schedule.

**R2 — Physically distinct but adjacent zones, overlapping time → `COMPATIBLE`.**
Two departments working in physically distinct but adjacent zones at the same time **are
compatible** — they do not physically conflict.
**Canonical example to encode as a test case:** *PWI working the **Matunga–Dadar section** while OWD
works **Matunga station** itself → COMPATIBLE.*
"Adjacent" = the two zones share an endpoint node but do not geometrically overlap. A `SECTION` zone
and a `STATION_NODE` zone at one of its endpoints are adjacent, **not** overlapping. This is
precisely why §5.1 requires the section/station-node distinction.

**R3 — Incompatible → different time slots entirely.**
Any pair determined incompatible **must** be assigned disjoint time windows. This is a hard
`NoOverlap` in CP-SAT and a hard action mask in the RL environment. No soft penalty. No exceptions.

**R4 — Base department-pair matrix (3×3), then geometry modifier.**
Maintain a base compatibility table over `{S&T, OWD, PWI} × {S&T, OWD, PWI}` in config, then apply
the geometric relation (SAME_ZONE / ADJACENT / DISJOINT) to arrive at the final verdict. Additional
encoded rule (**flag as our assumption in `ASSUMPTIONS.md`**): work requiring a **power block** by
OWD over a stretch, and other departments' work physically under that same energised stretch,
interacts — either it must be co-scheduled under the power block (IWP) or separated. State it as an
assumption, do not present it as established IR rule.

### 7.3 Output — a visible matrix, not just backend logic

```python
compatibility(t1, t2) -> Verdict{
    value: COMPATIBLE | REQUIRES_IWP | INCOMPATIBLE,
    reason: str,            # human-readable, shown in the UI tooltip
    rule_id: "R0".."R4",
    zone_relation: SAME_ZONE | ADJACENT | DISJOINT
}
```

Every verdict carries a **human-readable reason string** — e.g.
*"Compatible: PWI is on the Matunga–Dadar section while OWD is at Matunga station; adjacent zones,
no physical conflict (R2)."* These strings are what get shown in the UI and screenshotted for the
PPT. Write them well.

Expose `GET /api/compatibility/matrix?date=...` returning the full pairwise matrix for all active
tasks. The UI renders it as a colour-coded grid (§14.5).

### 7.4 Fallback ladder

1. **First**: one department pair (PWI × OWD) with R1/R2/R3 only, and the Matunga–Dadar/Matunga test
   case passing.
2. **Then**: generalise to all three departments and the full 3×3 base matrix.
3. **Then**: R0 allotment constraints.
4. **Then (Tier B6)**: IWP as a quota resource with an approval panel.

---

## 8. STATION-TIER-DEPENDENT SCHEDULING (Tier A5)

**Train frequency must be an explicit scheduling factor — not a fixed "always work at night" rule.**

### 8.1 Derive tiers from the data

Compute `trains_per_hour` per station and per section from the validated timetable (peak and daily
mean). Assign tiers by **quantile**, not by hardcoded station names:

| Tier | Derivation | Expected members (sanity-check only) | Scheduling policy |
|------|-----------|--------------------------------------|-------------------|
| `TIER_1` | Top quantile of frequency | CSMT, Dadar, Kurla, Thane, Kalyan | **Frequent small daily windows** (20–45 min, `max_window_min_tier1`). Low-traffic windows are rare here, so work must **not** pile up waiting for a megablock. Cap concurrent blocks. Prefer high task-turnover over long single blocks |
| `TIER_2` | Middle | Dombivli, Ambernath, Badlapur | Mixed: night window + selective micro-gaps |
| `TIER_3` | Bottom quantile | **Neral, Bhivpuri Road**, Vangani, Shelu | **Daytime maintenance permitted.** Frequency is low enough that real gaps exist outside the night window. Allow longer daytime blocks (`max_window_min_tier3`) |

Validate that the derived tiers actually place CSMT/Dadar in TIER_1 and Neral/Bhivpuri in TIER_3. If
they do not, your frequency computation is wrong — fix it. (Sanity check only; do not hardcode.)

### 8.2 How tiers enter the optimiser

- Tier caps maximum block duration and maximum concurrent blocks per station.
- Tier 1 gets a **backlog-aging penalty**: a task waiting at a Tier-1 station accrues cost faster,
  forcing the solver to drip-feed it into small windows instead of hoarding it for a megablock.
- Tier 3 unlocks `MICRO_GAP` and daytime windows with relaxed duration limits.

### 8.3 Demo value

Explicitly surface this in the UI and the report: *"On this corridor the system scheduled N tasks at
Tier-1 stations across M short daily windows, while consolidating K tasks at Tier-3 stations into
longer daytime blocks — a policy difference derived automatically from train frequency."*

---

## 9. REROUTING AND TRACK-SWAP LEVERS (Tier A6)

Maintenance does not only fit into gaps — **it can create gaps by moving trains.** Two distinct
levers with different rules. Implement the distinction exactly; it is a domain-accuracy differentiator.

### 9.1 INTERCITY (Rajdhani/Deccan Queen/…) and FREIGHT_MAIL — reroutable

These trains have a **fixed origin and destination that must be honoured, but not a fixed physical
route.** The system may reroute them onto an alternate line/track to free the original corridor for
maintenance, **provided final arrival is not badly delayed.**

Implementation:
- Precompute, per train, a small set of alternate paths (origin → destination) over the network
  graph with NetworkX `shortest_simple_paths`. **Cap at `k = 3`** — more is wasted compute.
- CP-SAT gets a path-selection boolean per (train, path). Exactly one path selected.
- Constraint: `added_delay_min ≤ train.max_acceptable_delay_min`
  (defaults: intercity 30 min, freight 90 min — assumptions, configurable).
- Constraint: the alternate path's sections must have capacity (occupancy check) and must be `FIT`
  or at worst `CAUTION_ORDER` (never route onto a section under an active block).
- Objective penalty proportional to added delay × train priority.

### 9.2 SUBURBAN_LOCAL — **not reroutable**

Suburban locals serve **fixed stations for the travelling public and cannot be moved onto a
different line.** The only flexibility available is **switching between the UP track and the DOWN
track of the same section** — standard railway single-line working during a block.

Implementation:
- Boolean per (local service, section hop): `use_opposite_track`.
- When a section is on single-line working, **throughput halves**: enforce doubled effective headway
  on the shared track and a crossing/precedence constraint between opposing movements.
- Cap the continuous duration of single-line working (`max_single_line_min`, default 180) and the
  number of concurrently single-line sections per corridor (default 1–2).
- Penalty proportional to the number of local services affected × delay.

### 9.3 Guardrail — encode as an assertion

**A `SUBURBAN_LOCAL` must never be assigned an alternate path. Assert this in the solution decoder
and in the RL action mask.** If it ever happens, the demo is factually wrong in front of domain
judges. Write a test.

### 9.4 Fallback ladder

1. **First**: no rerouting — gap-fitting only. Get the pipeline green.
2. **Then**: local UP/DN track swap (simpler, and it is the more domain-specific detail).
3. **Then**: intercity/freight alternate-path selection with k = 2.
4. **Then (Tier B7)**: k = 3 over the wider Maharashtra graph.

---

## 10. CP-SAT BATCH PLANNER (Tier A7)

Plans the **weekly PLANNED task set**, finalised "every Monday," and serves as the **expert** whose
solutions become RL training trajectories (§11). Quality here directly caps RL quality — invest in it.

### 10.1 Decision variables

- Per task: `start` (int, minutes from week start), fixed `duration`, `IntervalVar`, and an
  `is_scheduled` boolean (tasks may be deferred to next week at a cost).
- Per task: assignment to a `CandidateWindow` (optional-interval / presence literals).
- Per task pair requiring IWP: a `co_scheduled` boolean consuming IWP quota.
- Per reroutable train: path-selection booleans (§9.1).
- Per local service hop on a blocked section: `use_opposite_track` boolean (§9.2).

### 10.2 Constraints

1. Task interval ⊆ chosen candidate window (or a window created via §6.4 extension).
2. `NoOverlap` per `(section, track)` across work intervals **and** train occupancy.
3. **Compatibility (§7):** `INCOMPATIBLE` pairs → hard disjunction (different time slots entirely).
   `REQUIRES_IWP` pairs → either disjoint, or overlapping **with** `co_scheduled = 1` consuming quota.
   `COMPATIBLE` pairs → free to overlap.
4. **R0 allotment:** task section ∈ department allotment.
5. Department **gang capacity**: `Cumulative` per department per shift (default 2 concurrent gangs
   per department per corridor — assumption).
6. Station-tier caps (§8.2): max block duration, max concurrent blocks per station.
7. Task release ≤ start; priority-1 tasks must finish before `due_by` (hard); others soft.
8. Rerouting/track-swap constraints (§9).
9. Power-block tasks require the OHE isolation window (setup/release overhead per §6.3).

### 10.3 Objective (weighted sum; expose weights in `config.yaml`)

```
minimize
    w1 * train_minutes_lost                 # delay + cancellations, weighted by train priority
  + w2 * unscheduled_task_penalty           # weighted by task priority and age
  + w3 * degraded_status_section_hours      # time spent in CAUTION_ORDER / STOP_AND_START
  + w4 * rerouted_train_delay
  + w5 * single_line_working_minutes
  + w6 * iwp_usage                          # IWP is administratively expensive; use sparingly
  - w7 * micro_gap_utilisation_bonus        # actively reward using non-obvious gaps
```

`w7` is deliberate: we *want* the solver to prefer micro-gaps, because that behaviour is our
headline claim. Default weights go in config with a one-line rationale each.

### 10.4 Solver hygiene

- `max_time_in_seconds` from config (default 60 s for a demo solve, 10 s per instance when mass-
  generating expert data). `num_search_workers = 8`. Fixed `random_seed`.
- Log: status (OPTIMAL/FEASIBLE/INFEASIBLE), objective, best bound, **gap %**, wall time. Persist to
  `artifacts/`. Reporting "CP-SAT reached a 2.1 % optimality gap in 47 s" is credibility.
- **On INFEASIBLE:** run a relaxation ladder (drop soft due-dates → drop tier caps → allow task
  deferral) and report *which* relaxation restored feasibility. Never return a bare "infeasible" to
  the UI — that is a dead demo.

---

## 11. EXPERT TRAJECTORY GENERATION (Tier A8) — the bridge to RL

This converts CP-SAT solutions into the offline RL dataset. Follow arXiv:2409.10589's approach.

### 11.1 The MDP — specify it before writing any agent code

**Decision point:** a moment in simulated time when a dispatch decision is required — a gap window
opening, a task becoming released, a block completing, or a DEMAND task arriving.

**State `s`** (fixed-length float vector; document every element in `rl/mdp.py`):
- Global: normalised sim time-of-day, day-of-week, minutes to next night window.
- Per-section (for the K sections in the current planning horizon): status one-hot
  (FIT/SICK/CAUTION/STOP_START), station tier one-hot, current traffic density, minutes until next
  train, current gap usable-minutes.
- Task pool (top-N pending tasks by priority × age): department one-hot, duration, priority,
  age-since-release, slack to `due_by`, `requires_power_block`, target section index,
  PLANNED/DEMAND flag.
- Resources: per-department free gangs, IWP quota remaining today.
- Conflict summary: for each candidate task, counts of INCOMPATIBLE / REQUIRES_IWP relations against
  currently-scheduled work.

**Action `a`:** select one `(task, candidate_window)` pair from a fixed-size masked action space
(`N_tasks × M_windows`, plus a `NO_OP / DEFER` action). Fixed dimensions across instances — pad and
mask. `NO_OP` is always legal; this guarantees the agent can never deadlock.

**Reward `r`** (dense, aligned with the CP-SAT objective so the learned policy and the solver
optimise the same thing):
```
r = + completion_bonus(task.priority)
    + micro_gap_bonus         if window.gap_type == MICRO_GAP
    − train_minutes_lost_delta
    − degraded_status_hours_delta
    − reroute_penalty_delta
    − waiting_penalty         for each pending task, each step (drives urgency)
```
NO_OP yields only the waiting penalty. Terminal: end of the planning horizon.

**Action mask:** every constraint from §7, §8, §9, §10.2 that can be evaluated point-wise becomes a
mask. **Constraint satisfaction is enforced by masking, never by reward shaping.** Consequence: the
policy's constraint-violation rate is 0 by construction, which is a claim you can make on stage.

### 11.2 Generating the dataset

1. Sample **N instances** (target **500**; absolute minimum **200**) by varying: task mix and count
   (15–60 tasks), department balance, traffic density (weekday/weekend/festival multipliers),
   defect distribution, corridor sub-span, IWP quota, gang availability.
2. Solve each with CP-SAT (10 s cap each; run instances in parallel with `multiprocessing`).
3. **Replay each solution chronologically through the environment**, emitting the action the expert
   solution implies at each decision point. Record
   `(state, action, reward, next_state, action_mask, next_action_mask, done, instance_id)`.
4. Discard instances that are INFEASIBLE or hit the time cap with a gap > 25 %. Log the discard rate.
5. Store as sharded Parquet/NPZ in `data/expert/`. Emit `data/expert/schema.md` and a stats summary:
   #instances, #transitions (target **50k–200k**), action distribution, mean episode return,
   micro-gap usage share.
6. **Split by instance, not by transition** — 70 % train / 15 % val / 15 % held-out test. Leakage
   here silently invalidates every RL number you report. Assert no `instance_id` overlap.

### 11.3 Fallback

If CP-SAT generation is too slow, reduce instance size (fewer sections, fewer tasks), drop the cap
to 5 s, and cut to 200 instances. **Do not** reduce below 200 — the offline RL result becomes noise
and the whole innovation claim collapses. Generating expert data is on the critical path; start it
early and let it run in the background while you build the UI.

---

## 12. OFFLINE RL DISPATCHER + ALGORITHM COMPARISON (Tier A9 / Tier B1)

**Do not commit to one algorithm up front.** The comparison is itself a demo-able result and a slide.
But build them in the order below — one working agent beats three broken ones.

### 12.1 Build order (strict)

| Order | Model | Purpose | Tier |
|-------|-------|---------|------|
| 1 | **Greedy heuristic** — earliest-usable-gap × highest-priority, mask-respecting | The "what a simple script does" floor. Also a sanity check on the env | A |
| 2 | **Behavior Cloning (BC)** — masked cross-entropy on expert actions | Validates that the state encoding is learnable at all. If BC can't beat greedy, your features are broken — fix them before touching Q-learning | A |
| 3 | **Offline DQN + CQL regulariser** | The paper's approach. Primary agent | A |
| 4 | **Masked actor-critic (A2C-style, offline-adapted)** | Second algorithm for the comparison | B |
| 5 | *(optional)* **IQL** | Third point on the comparison chart | B |

### 12.2 Technical note on A2C — read this, it prevents a wrong result

Vanilla A2C is **on-policy** and is not valid trained purely offline on someone else's trajectories;
run naively, it will produce numbers that look fine in training and collapse in evaluation. Implement
the A2C-style agent as an **offline-adapted advantage-weighted actor-critic (AWAC-style)**: learn a
critic on the offline data, and update the actor with advantage-weighted likelihood on *dataset
actions only*, with a behaviour-constraint term. Keep the A2C actor-critic architecture and label it
"A2C (offline-adapted / advantage-weighted)" in the report, **with a one-line footnote explaining the
adaptation.** Presenting an honest, correctly-adapted A2C is stronger than presenting a naive one —
and a judge who knows RL will ask exactly this question.

### 12.3 Requirements common to all agents

- **Maskable action space is mandatory.** Invalid actions get `-inf` on logits / Q-values before
  softmax or argmax. Many actions are infeasible at any given state; an unmasked agent will produce
  constraint-violating schedules and the demo will be wrong.
- Conservatism: DQN uses a **CQL** penalty term (weight `alpha` in config, default 5.0) to stop
  Q-values extrapolating on out-of-distribution actions — the exact failure mode the reference paper
  addresses. Do not skip it.
- Architecture: 2–3 layer MLP, hidden 256, ReLU, LayerNorm. These are small problems; do not build a
  transformer. If you have spare time and want a Tier-B upgrade, an attention pooling layer over the
  task list is the right next step (it also makes the model size-invariant, which supports J3).
- Training: Adam, lr 3e-4, batch 256, ~50–100k gradient steps, target-network updates for DQN,
  validation every 2k steps, early stop on validation return, checkpoint best. Should train in
  **minutes, not hours,** on CPU. If it doesn't, your network or dataset is too big — shrink it.

### 12.4 Evaluation protocol — same protocol for every agent, no exceptions

Run every model on the **held-out instance set** (never seen in training). Report:

| Metric | Definition |
|--------|-----------|
| **Objective gap vs CP-SAT (%)** | `(agent_obj − cpsat_obj) / cpsat_obj`. **The headline number.** |
| **Decision latency (ms)** | Mean + p95 wall time per dispatch decision |
| **Full re-plan latency (ms)** | Time to produce a complete revised schedule after a demand-task injection |
| **Constraint-violation rate** | Must be exactly 0 (masking guarantees it). Assert it |
| **Tasks scheduled** | Count + priority-weighted |
| **Micro-gap utilisation (%)** | Share of tasks placed in `MICRO_GAP` windows |
| **Train-minutes lost** | Total delay induced |
| **Deadline misses** | Priority-1 tasks past `due_by` |

Output `artifacts/rl_comparison.csv` + a grouped bar chart PNG + a rendered table in the UI (§14.6).

**Then write the selection justification** in `REPORT.md`: which algorithm wins, on which metric,
and *why* it suits this problem (e.g. "CQL-DQN attains a 6 % objective gap at 3 ms/decision, while
the advantage-weighted actor-critic trades 2 % objective quality for smoother behaviour under
distribution shift"). **Judges reward the reasoning more than the winner.** Do not write "we chose
DQN because it is popular."

### 12.5 The killer comparison — put this on a slide

```
Full re-plan after an unplanned defect:
   CP-SAT (optimal, batch):        ~30–60 s
   RL dispatcher (learned):        ~5–50 ms      →  ~1000× faster
   Objective quality retained:     within ~5–10 % of optimal
   Manual/decentralised (today):   hours to next planning cycle
```
Measure these for real. Do not write estimates into the report — measure and cite the measurement.

### 12.6 Fallback ladder

1. Greedy + BC only, evaluated and charted. **This alone is a presentable result** ("learned
   dispatcher matches expert behaviour at 1000× the speed").
2. Add CQL-DQN. ← *Minimum bar for the innovation claim. Get here.*
3. Add the offline-adapted A2C for the head-to-head comparison.
4. Add IQL for a third data point.

If RL training does not converge by your deadline: **ship BC as the dispatcher**, label it honestly
as behavior cloning on CP-SAT expert data, and put the full offline-RL comparison in the roadmap.
BC on expert trajectories is still a legitimate, defensible learned dispatcher. A broken CQL is not.

---

## 13. SIMULATION ENGINE AND THE DEMAND-TASK LOOP (Tier A10)

### 13.1 Simulation

Discrete-event / fixed-tick hybrid. One simulated day per ~30–60 real seconds, adjustable
(`0.5× / 1× / 4× / 16×`). Per tick, advance every active train along its path, applying:
- Section status speed effects (§5.2): SICK / CAUTION_ORDER speed caps, STOP_AND_START time penalty.
- Active blocks: sections closed → trains held, rerouted, or on single-line working per §9.
- Sampled delays per §3.6, propagating downstream (a delayed train delays its follower).

Broadcast state over WebSocket at ~4 Hz: train positions, section statuses, active blocks, task
pool, and the natural-language event log.

### 13.2 The demand-task loop — this is the money demo

```
1. Run the simulated week with the CP-SAT weekly plan executing normally.
2. At a scripted moment (a "Inject Demand Task" button in the UI), a gang working a
   section discovers an unplanned defect → a DEMAND task is created.
3. Show side by side, on screen, both responses:
      (a) CP-SAT full re-solve      → spinner → completes in ~30–60 s
      (b) RL dispatcher             → completes in milliseconds
   Display both revised schedules and both objective values.
4. Apply the RL schedule live. Map, status board and task pool update.
5. When the work completes, the FSM transitions the section to
   FIT / CAUTION_ORDER / STOP_AND_START, the task leaves the active pool,
   and both the backend state and the map reflect it.
```

Step 3 is the single most persuasive twenty seconds of the demo. Make it visually obvious that both
paths ran on the same problem and produced comparable schedules at wildly different latencies.

### 13.3 Fallback

If live simulation is unstable: pre-compute the whole day's state into a timeline JSON and let the
UI scrub through it. **A deterministic replay that always works beats a live sim that might crash on
stage.** Build the replay export regardless, as the demo-safety net.

---

## 14. UI / SIMULATION REQUIREMENTS (Tier A11)

### 14.1 Design discipline — read this carefully; it is not a contradiction

**Outputs and data must be clear, calm and uncluttered — not overly colourful or busy. The overall
UI polish and "wow factor" must still be high.** These are compatible: high polish comes from
disciplined typography, spacing, hierarchy and motion — *not* from more colour.

Concretely:
- **One** neutral base (slate/zinc). **One** accent for interaction. Colour is reserved for
  **semantic status only**: track status and compatibility verdicts. Nothing else gets colour.
- Status palette, used consistently everywhere (map, matrix, board, tables):
  `FIT` = calm green · `SICK` = amber · `CAUTION_ORDER` = orange · `STOP_AND_START` = red ·
  `BLOCK_ACTIVE` = blue/violet.
- Train types differentiated by **shape and size first, colour second**: suburban = small dot;
  intercity = larger dot with a ring; freight = square/diamond. This keeps a dense map legible and
  works for colour-blind viewers.
- At default zoom, **do not render every one of 1,200 services**. Render trains active in the
  current time window, decluster on zoom, cap simultaneous dots (`max_rendered_trains`, default 120)
  and show "+N more" — deliberate visual hierarchy is an explicit requirement.
- Dark theme default (reads well on projectors), high contrast, generous whitespace, one heading
  scale. Subtle transitions on state change — motion is what makes it feel expensive.

### 14.2 The map (core)

- **Geography:** Maharashtra, with interconnected railway lines. Mumbai suburban network shown at
  detail; intercity links (Mumbai–Pune, Mumbai–Nashik–Bhusawal–Nagpur, Pune–Solapur) shown as the
  long-distance layer.
- **Lines:** rendered from section geometry. Each section is **coloured by its current track
  status** (§5.2) — this is how track status is "visible per section" as required.
- **Trains as moving dots**, differentiated by type per §14.1, animated along section geometry
  according to simulated time.
- **Active maintenance blocks:** a distinct overlay on the affected section (hatched/pulsing
  segment) with the owning department badge.
- Click a section → side panel: status, active/pending tasks, allotted department, next available
  gap, frequency and station tier.

**FALLBACK ladder — take it early if the map is eating time:**
1. **Static schematic SVG** of the corridor (straight lines, stations as nodes) with sections
   coloured by status. **No tiles, no network dependency, zero risk, and honestly quite readable.**
2. Add train dots at discrete positions updated per tick (no interpolation).
3. Add a real geographic basemap (MapLibre + a muted style) with real geometry.
4. Add smooth interpolated animation, zoom declustering and the time scrubber (Tier B2).

A crisp schematic that always renders beats a half-finished geographic map. Decide by your
mid-project checkpoint and do not revisit.

### 14.3 Status board — natural language, not a data dump

Alongside/below the map. **Plain readable English sentences**, newest first:

> **02:14** · Block granted to **PWI** on **Vangani–Shelu (DN)** for 95 min — rail joint attention.
> Fitted into the night window; no services affected.
>
> **02:20** · **OWD** working **Neral station** OHE in parallel — *compatible* with PWI on the
> adjacent Vangani–Shelu section, so both proceed together. (Under manual coordination this pair
> would have been serialised across two nights.)
>
> **06:40** · **Bhivpuri Road–Karjat** returned to service as **CAUTION ORDER** (30 km/h). Follow-up
> task queued for Thursday.
>
> **11:05** · Unplanned defect reported at **Kurla (UP)** — track circuit. Re-planned in **7 ms**;
> slotted into the 11:47–12:09 gap between services. No train delayed.

The parenthetical before/after asides — *"under manual coordination this would have taken two
nights"* — are deliberate. Generate them from the baseline comparison (§15) so they are true, not
decorative. Also show a compact current-state header: sim clock, active blocks, tasks pending by
department, sections by status.

### 14.4 Task pool panel

Table of active tasks: department (badged), type, section, duration, priority,
`PLANNED`/`DEMAND` badge, status (`pending` / `scheduled @ time` / `in progress` / `done`), and
which gap type it was placed in. Completed tasks leave the pool visibly (fade out).

### 14.5 Compatibility matrix view (required, visible)

A colour-coded grid of active tasks × active tasks:
- **green** = COMPATIBLE · **amber** = REQUIRES INTEGRATED WORK PERMISSION · **red** = INCOMPATIBLE.
- Hover a cell → the human-readable `reason` string and `rule_id` from §7.3.
- A toggle: **"Manual coordination (today)"** vs **"Automated (RailBlock AI)"**, showing the
  estimated coordination time and the resulting schedule under each. This single control is our
  before/after story in one screen — build it.
- Also show the 3×3 department-level base matrix as a small legend panel.

### 14.6 RL comparison panel

Table + grouped bar chart from `artifacts/rl_comparison.csv`: Greedy / BC / CQL-DQN / A2C-offline
across objective gap, latency, tasks scheduled, micro-gap utilisation. Highlight the selected
algorithm and show the one-paragraph justification inline.

### 14.7 Impact (before/after) tab

Renders §15. Big-number tiles for the headline deltas, a grouped bar chart, and a downloadable CSV.
Design these tiles to be **screenshot-ready for the PPT** — they will be lifted directly into slides.

---

## 15. BEFORE/AFTER IMPACT HARNESS (Tier A12) — J5, the thing judges remember

### 15.1 Define the "before" baseline explicitly and defensibly

Implement `metrics/manual_baseline.py` simulating today's decentralised process:
- Each department plans **independently**, first-come-first-served.
- Only **night windows and Sunday megablocks** are used. **No micro-gap usage.** No rerouting.
- Cross-department conflicts are discovered **late** and resolved by **deferring** the later request
  to the next available window (no compatibility reasoning, no adjacency exploitation, no IWP).
- Each cross-department conflict incurs a **manual coordination delay**
  (`manual_coordination_hours_per_conflict`, default **4 h** — an assumption; log it and expose it
  as a slider in the UI so a sceptical judge can dial it down and see our advantage survive).
- Unplanned demand tasks wait for the **next weekly planning cycle** (up to 7 days) rather than
  being re-planned intra-week.

**Be honest about this being a model, not measured field data** — say so in the report. A clearly
stated, parameterised baseline is far more credible than an unsourced "70 % improvement" claim.

### 15.2 Metrics to compute (all of them)

| # | Metric | Before (manual) | After (ours) |
|---|--------|-----------------|--------------|
| M1 | **Re-planning latency** for an unplanned defect | Hours → next cycle | CP-SAT seconds / **RL milliseconds** |
| M2 | **Department coordination time** | #conflicts × manual hours/conflict | Compatibility-matrix compute time (ms) |
| M3 | **Asset availability** — % section-hours in FIT | | |
| M4 | **Degraded-state hours** — CAUTION_ORDER + STOP_AND_START section-hours | | |
| M5 | **MTTR** — mean defect-reported → work-completed | | |
| M6 | **Tasks fitted into non-obvious gaps** — count and % in `MICRO_GAP` (not night/megablock) | ~0 by construction | measured |
| M7 | **Task throughput** — tasks completed per week, priority-weighted | | |
| M8 | **Backlog** — pending task queue length over the week | | |
| M9 | **Train impact** — train-minutes delayed, trains rerouted, locals on single-line working | | |
| M10 | **Megablock dependence** — % of work that *needed* a megablock | | |

M6 and M2 are the two most distinctive; make them prominent.

### 15.3 Output

`scripts/05_run_impact_study.py` runs both planners over the **same** seeded instances and emits:
- `artifacts/metrics.json` (machine-readable)
- `artifacts/impact_comparison.csv` (**straight into the PPT** — required)
- `artifacts/charts/*.png`
- A `REPORT.md` section with a before/after table and 3–5 plain-English takeaway sentences.

Report **deltas and percentages**, and state the instance count and seed alongside every number.

---

## 16. GOVERNMENT SYSTEM INTEGRATION (Tier A13) — J4

The problem statement names **BDMS, COA, TMS, SMMS, TDMS**. Our system must read as something that
**plugs into** these, not a green-field replacement. Build `backend/adapters/` with a thin, clearly
documented interface per system and a **mock implementation** reading/writing our local data.

| System | Our reading of it | Adapter role | Interface (implement these method signatures) |
|--------|-------------------|--------------|-----------------------------------------------|
| **BDMS** — Block Demand Management System | Where block demands are raised and sanctioned | **Primary integration point.** Our plan is submitted as block demands; sanctions flow back | `fetch_pending_block_demands()`, `submit_block_plan(plan)`, `fetch_sanction_status(block_id)` |
| **COA** — Control Office Application | Live train running / control charts | Source of live train positions and actual running times; consumer of our block impact | `fetch_live_train_positions()`, `fetch_actual_running(date)`, `notify_block_impact(...)` |
| **TMS** — Track Management System | P-Way / track asset condition and inspection records | Source of **PWI** tasks and track asset condition | `fetch_track_defects()`, `post_work_completion(task, outcome_status)` |
| **SMMS** — Signalling Maintenance Management System | S&T maintenance records | Source of **S&T** tasks | `fetch_signalling_tasks()`, `post_work_completion(...)` |
| **TDMS** — Traction Distribution Management System | OHE / traction distribution | Source of **OWD** tasks and power-block requirements | `fetch_ohe_tasks()`, `fetch_power_block_constraints()`, `post_work_completion(...)` |

**This mapping is a genuinely strong integration story — make it a slide:** the three departments
whose coordination we automate map one-to-one onto three existing IR systems
(**PWI → TMS, S&T → SMMS, OWD → TDMS**), the plan we produce is consumed by **BDMS** as block
demands, and **COA** closes the loop with live running data. We are the **planning brain between
systems that already exist.**

Requirements:
- Each adapter is an ABC + a `Mock*Adapter` implementation reading our synthetic/real data.
- Config switch `adapters.mode: mock | live` so the live path is visibly a config change.
- `adapters/README.md` documents each payload we would send/receive and **explicitly states** that
  these are internal IR systems without public APIs, so schemas are our best-effort assumptions
  pending access. **Say this out loud** — inventing fake API docs and presenting them as real is the
  fastest way to lose a domain judge's trust.
- Draw the integration boundary in the architecture diagram: our system is a box between the three
  source systems and BDMS/COA.

---

## 17. API SURFACE (minimum)

```
GET  /api/network                      → stations, sections, geometry, statuses, tiers
GET  /api/trains?at=<ts>               → positions at a sim time
GET  /api/gaps?date=&section=          → candidate windows incl. gap_type, raw vs usable minutes
GET  /api/tasks                        → active pool (PLANNED + DEMAND)
POST /api/tasks/demand                 → inject a demand task (demo button)
POST /api/plan/cpsat                   → run batch planner, return schedule + solver stats
POST /api/plan/rl                      → run RL dispatcher, return schedule + latency_ms
GET  /api/compatibility/matrix?date=   → pairwise verdicts + reason strings + rule ids
POST /api/sim/control                  → play | pause | speed | reset | jump_to
POST /api/work/complete                → {task_id, outcome} → FSM transition + broadcast
GET  /api/metrics/impact               → before/after metrics.json
GET  /api/rl/comparison                → algorithm comparison table
WS   /ws/state                         → live sim state, status changes, event log lines
```

Every planning response must include `latency_ms` and the objective value. Those two fields power
most of the demo's numbers.

---

## 18. BUILD ORDER WITH TIME BUDGETS AND CHECKPOINTS

Assume ~4 working days. Adjust proportionally. **At every checkpoint: if red, take the fallback and
move on. Do not debug past a checkpoint.**

| Phase | Budget | Deliverable | Checkpoint (must be true to proceed) |
|-------|--------|-------------|--------------------------------------|
| **P0 — Skeleton** | 2 h | Repo, config, FastAPI hello, Vite app, `ASSUMPTIONS.md` | `uvicorn` + `vite` both run |
| **P1 — Data** | 4 h | Sourcing (90 min hard cap) → ingest → **validation gate** → fidelity replay | `01_validate.py` PASSes; timetable replay is conflict-free |
| **P2 — Domain core** | 3 h | Network graph, FSM, tasks, departments, **compatibility rules + tests** | Matunga–Dadar / Matunga adjacency test passes; FSM tests pass |
| **P3 — Gap engine** | 3 h | Night → megablock → **micro-gaps**, with setup/release overhead | Gap counts per type printed; night window *derived*, not hardcoded |
| **P4 — CP-SAT** | 6 h | Full model, objective, decoder, relaxation ladder | Weekly plan solved for the corridor, gap < 10 %, no constraint violations |
| **P5 — UI v1** | 5 h | Schematic/geo map + status board + task pool + compatibility matrix | You can watch a planned day run and read it in English |
| **P6 — Expert data** | 3 h *(start generation early, run in background)* | 200–500 instances → trajectories → splits | ≥ 50k transitions, no instance leakage across splits |
| **P7 — RL** | 6 h | Greedy → BC → CQL-DQN, evaluation harness | CQL-DQN within ~15 % of CP-SAT objective, 0 violations, ms latency |
| **P8 — Demand loop** | 3 h | Injection button, CP-SAT vs RL side-by-side, FSM completion | The §13.2 sequence runs start to finish without a crash |
| **P9 — Impact** | 3 h | Manual baseline + all 10 metrics + charts + CSV | `metrics.json` + `impact_comparison.csv` exist and are non-trivial |
| **P10 — Adapters + docs** | 2 h | 5 adapters + README + ROADMAP + REPORT | `REPORT.md` complete with the J1–J5 traceability table |
| **P11 — Polish / Tier B** | remainder | A2C comparison (B1) → animation (B2) → second corridor (B5) → the rest | — |
| **P12 — Demo lock** | 2 h | `scripts/demo.py`, deterministic replay export, screenshots, rehearsal | Full demo runs twice, clean, from a fresh terminal |

**Reserve P12. Do not let it be eaten.** A prototype that works once on your machine and fails on
stage scores zero on feasibility.

---

## 19. CONSOLIDATED FALLBACK LADDERS (quick reference)

| Area | 1. Cheapest working thing | 2. Upgrade | 3. Upgrade | 4. Stretch |
|------|---------------------------|-----------|-----------|-----------|
| **Data** | Structurally faithful synthetic timetable | + real intercity data from data.gov.in | + real Mumbai suburban timetable | + fitted real delay distributions |
| **Gaps** | Night window only | + Sunday megablock | **+ micro-gaps** *(don't stop before here)* | + window extension via reroute cost |
| **Compatibility** | PWI × OWD, rules R1–R3 | + all three departments, 3×3 base matrix | + R0 allotment constraints | + IWP quota & approval panel |
| **Rerouting** | None (gap-fitting only) | + local UP/DN track swap | + intercity/freight alt path, k=2 | + k=3 over the wider graph |
| **RL** | Greedy heuristic | + Behavior Cloning | **+ CQL-DQN** *(min bar for the innovation claim)* | + offline A2C / IQL comparison |
| **Map** | Static schematic SVG, sections coloured by status | + discrete-tick train dots | + geographic basemap & real geometry | + smooth animation, declustering, scrubber |
| **Demand loop** | One scripted injection | + CP-SAT vs RL side-by-side timing | + live FSM completion on the map | + continuous stochastic arrivals |
| **Sim** | Pre-computed replay timeline JSON | + live tick simulation | + delay propagation | + multi-corridor concurrent sim |

---

## 20. ACCEPTANCE CRITERIA — the prototype is "done" when all of these are true

1. `python scripts/demo.py` runs the full pipeline from a clean clone with a fixed seed.
2. `01_validate.py` reports **PASS** on every check, with the repair log published.
3. The gap engine reports counts for all three gap types, with the night window **derived** per
   section, and raw-vs-usable minutes shown.
4. CP-SAT produces a weekly plan with solver status, objective and **optimality gap** logged.
5. The compatibility matrix is visible in the UI, colour-coded, with human-readable reasons, and the
   **Matunga–Dadar (PWI) / Matunga station (OWD) → COMPATIBLE** case is demonstrable.
6. At least **two** learned models (BC + one offline RL agent) are evaluated on held-out instances
   with a published comparison table and a written selection justification.
7. The demand-task injection shows **CP-SAT seconds vs RL milliseconds** side by side on screen.
8. The track-status FSM visibly transitions a section on the map to FIT / CAUTION_ORDER /
   STOP_AND_START and removes the task from the pool.
9. `artifacts/impact_comparison.csv` contains all ten before/after metrics with stated assumptions.
10. `tests/test_scalability.py` passes on a second corridor added **by config only**.
11. `ASSUMPTIONS.md`, `ROADMAP.md` (Tier C) and `REPORT.md` (with the J1–J5 traceability table) are
    complete.
12. A `SUBURBAN_LOCAL` is never assigned an alternate route anywhere in any output (asserted).

---

## 21. THE DEMO SCRIPT — build toward this, exactly

Target: **4 minutes.** Write it into `DEMO_SCRIPT.md` and rehearse it.

1. **(20 s)** Map of Maharashtra, trains moving. "1,200 services a day on this corridor. Every one of
   them is in the way of maintenance."
2. **(30 s)** Task pool: S&T, OWD, PWI tasks. "Today, three department heads coordinate this by
   phone. Here is that coordination, computed." → Compatibility matrix, toggle **manual vs
   automated**, show the coordination-time delta.
3. **(40 s)** Gap engine. "Everyone schedules at night and on Sunday megablocks. We also find the
   gaps *between trains during the day*." → show micro-gaps, raw vs usable minutes, and a task
   fitted at Neral in daylight because its station tier allows it.
4. **(40 s)** CP-SAT weekly plan executing. Section goes SICK → block → back to **CAUTION ORDER**,
   follow-up auto-queued. Status board reads it out in English.
5. **(50 s)** **Inject a demand task.** CP-SAT re-solve spinner vs RL dispatcher — side by side.
   "Seconds versus milliseconds, within ~7 % of optimal. The RL policy was trained on 500 CP-SAT
   solutions — the solver taught the policy how to dispatch."
6. **(30 s)** RL comparison table: greedy vs BC vs CQL-DQN vs A2C, and *why* we chose what we chose.
7. **(30 s)** Impact tab: the ten before/after metrics.
8. **(20 s)** Integration slide: PWI→TMS, S&T→SMMS, OWD→TDMS, plan→BDMS, live running←COA. "This sits
   between systems Indian Railways already runs." Then the second corridor added by config → J3.

---

## 22. FINAL INSTRUCTIONS TO YOU, THE BUILDER

1. **Work Tier A top to bottom before touching Tier B.** A complete Tier A is a winning prototype.
   A half-built Tier B on top of a broken Tier A is a loss.
2. **Take the fallback at the checkpoint.** They are pre-agreed. Taking one is not a failure; it is
   the plan.
3. **Log every assumption.** `ASSUMPTIONS.md` is a deliverable, not overhead.
4. **Never fabricate numbers.** Every figure in `REPORT.md` and the UI must come from a run that
   actually happened. If something wasn't measured, say it wasn't measured.
5. **Preserve the domain rules exactly** — adjacency compatibility, Integrated Work Permission as a
   third distinct status, incompatible-pairs-get-different-slots, the four track statuses, locals
   restricted to UP/DN swap while intercity and freight can be rerouted, and station-tier-driven
   window sizing. These specifics are what make this submission look researched rather than
   generic. Do not generalise them away.
6. **Start expert-data generation early** and let it run in the background while you build the UI.
   It is the longest pole on the critical path.
7. **Commit often, with a working `main`.** Tag `demo-ready` as soon as Tier A is green, and keep
   that tag deployable no matter what you do afterwards.
