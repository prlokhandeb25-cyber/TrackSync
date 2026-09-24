# RailBlock AI

**AI-powered automatic block planning to maximise asset availability for train operations on
Indian Railways.** Smart India Hackathon prototype.

CP-SAT plans maintenance blocks optimally across the Mumbai suburban network and, in the same
step, produces the expert trajectories an offline-RL dispatcher is trained on. The solver is
exact but takes seconds; the learned dispatcher re-plans in milliseconds, which is what makes
reacting to an unplanned defect mid-week possible at all.

```
                 ┌──────────────┐
  TMS  (PWI)  ──►│              │
  SMMS (S&T)  ──►│  RailBlock   │──► BDMS   (plan submitted as block demands)
  TDMS (OWD)  ──►│      AI      │◄── COA    (actual running closes the loop)
                 └──────────────┘
```

---

## What it does

- Reads the real Indian Railways timetable, filters it to the Mumbai network, and **refuses to
  run on data it cannot validate** (ten checks, blocking).
- Finds every window where maintenance could go — night windows **derived per section**, Sunday
  megablocks **corroborated against observed traffic**, and the ordinary **gaps between trains** —
  and keeps a gap only if **15 minutes of real work** remain after safety, a lookout margin before
  the next train, set-up and hand-back. Blocks sit on a 5-minute grid and each gap carries the
  chance its start runs late.
- **Prefers quiet places and times**: a train-frequency and passenger model prices every slot by how
  many services and people are within reach, in the weekly plan and in the live scheduler.
- **Opens near-miss gaps** with small, priced changes to the trains: hold one a few minutes,
  reroute a long-distance train, run one track for both directions, or (critical faults only) take
  an emergency block. Suburban locals are never rerouted.
- Lets a department **raise a job** with the departments it may work alongside; the system scores
  it, **clusters** it with nearby jobs (hierarchical clustering), and schedules it into a gap,
  sharing a block with a compatible neighbour where the rules allow.
- **Checks itself.** An independent referee re-checks every rule of the finished plan straight from
  the timetable (window, release and deadline, allotment, no train on the track during the work,
  incompatible pairs, permits, gangs, station concurrency, daily limit): 167 checks, 0 violations on
  the live plan, and the tests show it failing on deliberately broken plans.
- **Plans for a bad day.** Each block is simulated against late trains and overrunning work; the
  solver avoids fragile windows and each start time is centred where the line is most likely to be
  handed back before the next train.
- **Gives time back.** When a block finishes early, the rest of its protected time goes to small waiting
  jobs on the same section, urgent first. On the current plan (36 mostly short blocks) the measured gain is small: about 1.4 hours
  a week handed back and 0.5 extra jobs with crews that tend to overrun, 2.9 hours and 1.2 jobs if crews
  take the planned time on average. The waiting list and crew timing are assumed (A-053); the gain grows
  with block length, and it is not a headline result.
- **Groups jobs by place and urgency**, and lets small jobs ride in a big job's block: no group mixes very
  urgent with very routine work any more (2 groups did before), and 2 small jobs ride today, saving 50
  minutes of set-up and hand-back (A-054).
- **Fills the day, not just the small hours.** Planned jobs sit mostly in the quiet 00:00-04:00 gaps; a daily list
  of small routine jobs is placed from 04:00 to midnight into gaps that already exist (A-055).
- **RailMitra answers slot questions** (is a gap free, who may use it, what buffer to leave), **crew and cost
  what-ifs** (how long and how much with different workers or machines, assumed rates A-056), and shows jobs
  on screen, as short bullet lists.
- **Planning studio tab.** (1) A timing curve: the exact solver on random 40, 100, 200 and 400 jobs, with the
  point where it stops proving optimality shown as the gap it reached. (2) Trade-off plans: five exact
  solutions favouring jobs done, passengers affected or robustness, a slider between them, and exactly which
  jobs move against the plan in force. (3) Machines that can be in only one place at a time, with travel time
  (A-057). (4) Propose, approve or reject with a reason, apply, revert, and an append-only audit trail. (5) A
  learning loop: log planned versus actual duration and the crew buffers follow the data (A-058).
- **Says what a job needs on site** (people by role, machines, materials) from planning norms, not a
  prediction (A-052).
- **Early-warning predictions were removed.** The feed was simulated, so its accuracy could not be
  measured; RailMitra says so if asked (A-048).
- **A digital twin picks the response to a closure.** Each closure in force is replayed through the
  next 12 hours of the real timetable; the twin can overrule a detour that would cost passengers more
  than waiting, and shows the three responses side by side on the map page, in the sudden-task
  result and in RailMitra.
- **Proves the rerouting.** Across the week's 28 blocks, 10 long-distance and freight trains are sent
  round (+4 min on average against about 41 min waiting), 39 more have no other route, and 0 of 93
  local movements are rerouted (locals serve fixed stations; they run single-line on their own pair).
  Each example has a Watch button that flies the map to the closure with the whole detour in view.
- **Groups jobs two ways** (average-linkage, and K-Medoids with the group count chosen by silhouette),
  scored side by side; on today's jobs average-linkage scores higher (0.62 against 0.58), so it
  stays the default.
- Takes **sudden tasks** (low to critical) that were never in the plan: fits them into an existing
  gap, or opens one, or moves lower-priority work aside and re-places it, in milliseconds, with the
  cost in train-minutes and passengers shown.
- Plans the week with CP-SAT (and a rolling four-week month), then re-plans reactively with a
  learned dispatcher when an unplanned defect appears.
- Shows all of it: a live map of the Mumbai region with each section drawn as its real tracks; zoom
  in to see the work site (protected zone, cones, crew, the machine, the track turning green as the
  work progresses) and diverted long-distance trains travelling their detour; a step-by-step replay
  of the algorithms in plain words; and a before/after page where every figure says how it was
  measured.
- **RailMitra** answers in block-coordinator terms (traffic block, power block, hand-back), in plain
  words: "plan a 2 hour PWI block on Kurla to Sion by Friday" gets a recommended slot and what else in
  the week would move (an exact re-solve on a copy that keeps the plan unless moving a job pays), with
  a small chart. Also closures, pairs of work, who is working where. No language model.
- Light and dark themes.

## Numbers, all from runs that actually happened

| | |
|---|---|
| Network | 4 lines, 73 stations, 74 sections |
| Windows | 6,922 (5,074 between trains, 1,303 night, 545 megablock), every one with at least 15 min of work |
| Usable maintenance time | 6,625 h/week against 4,106 h from night + Sunday block alone (**+61%**) |
| Weekly plan | CP-SAT OPTIMAL in 27 s (0% gap), 36 of 40 jobs, 6 compatible cross-department pairs sharing a block. On some runs the solver stops at its 60 s limit within 0.3% |
| Gap creation | 60 urgent jobs due in 6 h: **11** fit existing gaps, **59** fit with creation |
| Passengers | the same 60 jobs placed with and without the passenger term: **75% fewer** passengers within reach (127,950 vs 517,070, estimated); chosen sites average 4.5 trains/h against 12.4 across the network |
| Interval tree | about 160x faster range lookups than a full scan, identical answers (varies with machine load) |
| Best learned policy | behaviour cloning within **10.9%** of optimal on 20 held-out instances (CQL-DQN 11.1%, greedy 13.4%), **25x** faster to re-plan (161 ms vs 4,100 ms), 0 constraint violations |
| Plan check | referee: 167 checks, 0 violations. Blocks clear before the next train on 97% of simulated days against 88% when the solver plans alone (3 vs 10 fragile blocks of 28); both plans place 36 of 40 and solve to optimal. Varies between runs |
| Predictive blocks | 40 failures on the real timetable: emergencies 40 → 12 and train-minutes lost 1,262 → 119 if 80% are warned (assumed) |
| Digital twin | the best response to a closure depends on the moment: on the busiest section with a local track pair, diverting long-distance trains wins at night (679 → 0 passenger-hours of extra delay against holding), while by day holding beats single-line working (1.6-1.7x) |
| Bundling | no real gain: 190 → 189 protected blocks over 6 instances (1 extra merge); the solver already captures nearly all of it, so it is not in the live pipeline |
| Adaptive buffers | blocks clear on time 87% → 97% under the (synthetic) crew table, at the cost of 2 fewer jobs placed of 36; optional, not in the live plan |
| Tests | see the last line of `pytest -q` |

The RL figures are on the placement objective only (the integrated-block reward is a weekly-plan
feature the dispatcher is not trained for) and were re-measured after the gap definition changed.

## Quick start

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cpu

.\.venv\Scripts\python.exe scripts\00_fetch_data.py      # public IR datasets
.\.venv\Scripts\python.exe scripts\01_validate.py        # validation gate
.\.venv\Scripts\python.exe scripts\02_gaps.py            # traffic-gap engine
.\.venv\Scripts\python.exe scripts\03_plan.py            # CP-SAT weekly plan
```

Run the app:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.api.main:app --port 8000
cd frontend; npm install; npm run dev
```

Retrain the dispatcher (optional — trained weights are in `artifacts/models/`):

```powershell
.\.venv\Scripts\python.exe scripts\04_generate_expert_data.py 1200 6   # ~40 min
.\.venv\Scripts\python.exe scripts\05_train_rl.py
.\.venv\Scripts\python.exe scripts\06_evaluate_rl.py 20
```

> **Note on torch:** it is needed only to train and run the learned policies. The map, the
> planner, the metrics and the assistant all work without it, and the pipeline never imports
> it. On a memory-constrained machine torch's DLL initialisation can crash at the native
> level, so keeping it off the shared path is deliberate.

## Layout

```
backend/
  domain/      network, tasks, departments, track-status FSM, compatibility rules
  data/        ingest, validation gate, week expansion, synthetic tasks
  gaps/        traffic-gap engine
  planner/     CP-SAT model and the shared world builder
  rl/          MDP, expert trajectories, policies, agents, rollout environment
  metrics/     manual baseline and the before/after harness
  adapters/    TMS · SMMS · TDMS · BDMS · COA
  chat/        grounded question answering (no language model)
  api/         FastAPI routes
config/network/ one YAML per corridor — adding a line is adding a file
frontend/      React + TypeScript, five tabs and the RailMitra assistant
```

## Documents

| | |
|---|---|
| `SPEC.md` | the authoritative specification |
| `REPORT.md` | results, measured figures, judging traceability |
| `ASSUMPTIONS.md` | **every invented number, with its rationale** |
| `ROADMAP.md` | what was deliberately deferred |
| `DEMO_SCRIPT.md` | the five-minute walkthrough |
| `COMPARISON.md` | this build vs a parallel Antigravity run |

`ASSUMPTIONS.md` is the one worth reading first if you are evaluating this. Maintenance-task
data, coordination times and block overheads have no public source; they are invented, and
every one of them is written down with what it would be replaced by.
