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
- Finds every window where maintenance could go: night windows **derived per section**, Sunday
  megablocks **corroborated against observed traffic**, and — the differentiating part — the
  ordinary **gaps between consecutive trains** during the working day.
- Computes what three department heads currently negotiate by phone: whether S&T, OWD and PWI
  work can share a section and a time, with a written reason for every verdict.
- Plans the week with CP-SAT, then re-plans reactively with a learned dispatcher when an
  unplanned defect appears.

## Numbers, all from runs that actually happened

| | |
|---|---|
| Network | 4 lines, 73 stations, 74 sections, 254 route-km |
| Services | 1,640/day · 11,040/week |
| Validation | 10 checks, 8 pass, 2 warn/fail — **reported honestly, not tuned to pass** |
| CP-SAT | OPTIMAL, 0% optimality gap, ~3 s |
| Expert dataset | 1,074 instances, 28,232 transitions, splits disjoint by instance |
| Best learned policy | CQL-DQN, **14.8%** of optimal, **29× faster** to re-plan |
| Constraint violations | **0**, by construction |
| Tests | **47 passing** |

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
frontend/      React + TypeScript, seven tabs
```

## Documents

| | |
|---|---|
| `SPEC.md` | the authoritative specification |
| `REPORT.md` | results, measured figures, judging traceability |
| `ASSUMPTIONS.md` | **every invented number, with its rationale** |
| `ROADMAP.md` | what was deliberately deferred |
| `DEMO_SCRIPT.md` | the four-minute walkthrough |
| `COMPARISON.md` | this build vs a parallel Antigravity run |

`ASSUMPTIONS.md` is the one worth reading first if you are evaluating this. Maintenance-task
data, coordination times and block overheads have no public source; they are invented, and
every one of them is written down with what it would be replaced by.
