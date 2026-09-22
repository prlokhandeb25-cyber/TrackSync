# CLAUDE.md — working rules for RailBlock AI

**`SPEC.md` is the authoritative specification. This file is the binding process contract.**
Read the relevant `SPEC.md` section before each phase — do not work from memory of it after a long
session. If this file and `SPEC.md` disagree: this file wins on *process*, `SPEC.md` wins on
*content*, and you say so rather than guessing.

## What this is

An SIH prototype: **AI-powered automatic block planning to maximize asset availability for train
operations on Indian Railways.** CP-SAT (OR-Tools) plans maintenance blocks optimally and also
produces expert trajectories; an offline-RL dispatcher trained on those trajectories does
millisecond reactive re-planning when unplanned defects appear.

**Deadline is days, not weeks.** Bias every decision toward "demonstrable on stage" over
"architecturally pure."

---

## Execution contract

1. **One phase at a time.** `SPEC.md` §18 defines the phases, their time budgets and their exit
   checkpoints. Execute exactly one phase, stop at its checkpoint, report what passed and what
   didn't, and wait. Do not roll into the next phase because you have momentum.
2. **Take the fallback at the checkpoint.** `SPEC.md` §19 has a pre-agreed fallback ladder for every
   risky area. When a phase blows its time budget, take the next rung down *without asking* and note
   it in the phase report. Taking a fallback is the plan, not a failure.
3. **Do not debug past a checkpoint.** If something has failed twice and the budget is gone, fall
   back. The single biggest risk to this project is hours lost grinding on data sourcing or map
   rendering.
4. **Plan before P4 (CP-SAT) and P7 (RL).** Those two phases have real design branches. Produce a
   plan and get it approved before implementing. Every other phase, just build.
5. **Tier discipline.** Complete **all** of Tier A (`SPEC.md` §1) before touching any Tier B item.
   **Never implement any Tier C item** — those go in `ROADMAP.md` as prose only. In particular:
   **no genetic/evolutionary/NSGA-II code, ever.** It is explicitly deferred.
6. **Background the long jobs.** Expert-data generation (§11) and RL training (§12) run in the
   background while you build other things. Start expert-data generation as early as it is possible
   to do so — it is the longest pole on the critical path.
7. **Ask only when the answer changes the build.** Otherwise pick the sensible default, state it in
   the phase report, and keep moving.

---

## Invariants — never violate these, at any hour of any session

### Correctness

- **RL constraints are enforced by action masking, never by reward shaping.** Invalid actions get
  `-inf` before softmax/argmax. The constraint-violation rate must be exactly **0** and must be
  asserted in the evaluation harness.
- **A `SUBURBAN_LOCAL` is never assigned an alternate route.** Locals serve fixed public stations;
  their only flexibility is UP/DN track swap on the same section. Assert this in the solution
  decoder *and* in the action mask. Getting this wrong is factually wrong in front of domain judges.
- **Integrated Work Permission (IWP) is a third distinct status**, not a flavour of "compatible."
  The compatibility verdict is exactly one of `COMPATIBLE | REQUIRES_IWP | INCOMPATIBLE`.
- **`INCOMPATIBLE` pairs get disjoint time windows.** Hard constraint. Never a soft penalty.
- **Adjacent-but-distinct work zones are COMPATIBLE.** The canonical case — PWI on the
  Matunga–Dadar *section* while OWD works Matunga *station* — must have a passing test. This
  requires keeping `SECTION` and `STATION_NODE` as distinct work-zone types; never collapse them.
- **The track-status FSM is exactly**
  `FIT → SICK → (FIT | CAUTION_ORDER | STOP_AND_START)`, with follow-up tasks auto-created for the
  two degraded states. Every transition and every *illegal* transition is unit-tested.
- **Split RL data by `instance_id`, never by transition.** Leakage here silently invalidates every
  number in the report. Assert no overlap between train/val/test.
- **The validation gate blocks execution.** If `scripts/01_validate.py` FAILs, the API and
  `demo.py` refuse to run without `--force` and a loud banner. Scheduling results computed on
  inconsistent timetable data are worthless.

### Reproducibility

- **One `SEED` in `config/config.yaml`**, threaded into `random`, `numpy`, `torch`, and CP-SAT's
  `random_seed`. Every run reproducible.
- **No corridor-specific names, IDs or special cases in code.** Corridors are defined entirely by
  `config/network/*.yaml`. `tests/test_scalability.py` proves it by running the full pipeline on a
  second corridor added by config only. This test is the project's scalability evidence — keep it
  passing.

### Honesty

- **`ASSUMPTIONS.md` is updated in the same commit that introduces the assumption**, not at the end.
  Every invented number or rule gets a row: what, value, why that value, how to replace it with real
  data. Maintenance-task data, coordination times, setup/release durations and speed restrictions
  are all invented — that is fine and defensible, but only if it is written down.
- **Never write a number into `REPORT.md` or the UI that did not come from a run that actually
  happened.** No estimates presented as measurements. If it wasn't measured, say it wasn't measured.
- **Never invent API schemas for BDMS/COA/TMS/SMMS/TDMS and present them as real.** They are
  internal IR systems without public APIs. `adapters/README.md` must state plainly that the payloads
  are our best-effort assumptions pending access.
- **Do not attempt to scrape M-Indicator or RailOne.** No public API; already ruled out. Sources are
  listed in `SPEC.md` §3.2, with a 90-minute hard cap and a synthetic fallback.

---

## Environment

Windows 11 + PowerShell. Venv at `.venv`; if `Activate.ps1` is blocked, call
`.\.venv\Scripts\python.exe` directly rather than changing the machine's execution policy.
**Install `torch` from the CPU wheel index** — the CUDA payload is a long download and useless
here. Use `pathlib.Path` everywhere, never hardcode separators, always write UTF-8. Verify
`ortools` imports and Node/npm exist as part of the P0 checkpoint.

## Commands

```powershell
# backend
.\.venv\Scripts\python.exe -m uvicorn backend.api.main:app --reload --port 8000

# frontend
cd frontend; npm run dev

# pipeline
.\.venv\Scripts\python.exe scripts\01_validate.py
.\.venv\Scripts\python.exe scripts\02_generate_expert_data.py   # background this
.\.venv\Scripts\python.exe scripts\03_train_rl.py               # background this
.\.venv\Scripts\python.exe scripts\04_evaluate_rl.py
.\.venv\Scripts\python.exe scripts\05_run_impact_study.py

# the demo
.\.venv\Scripts\python.exe scripts\demo.py
```

## Git

`git init` at P0. Commit at the end of every phase with a message naming the phase
(`P3: traffic-gap engine — night/megablock/micro-gaps`). **`main` must always run.** Tag
`demo-ready` the moment Tier A is green, and keep that tag deployable regardless of what happens
afterwards. Never force-push over `demo-ready`.

## Tests — write these three only

1. The validation gate (`SPEC.md` §3.4)
2. The compatibility rules (`SPEC.md` §7.2), including the Matunga–Dadar / Matunga adjacency case
3. The track-status FSM (`SPEC.md` §5.3), including illegal transitions

Plus `tests/test_scalability.py`. **No coverage targets. No other tests.** Time spent on test
breadth is time not spent on the demo.

## Definition of done for a phase

The checkpoint in `SPEC.md` §18 is true, the code is committed, `ASSUMPTIONS.md` reflects anything
invented during the phase, and you have reported: what passed, what fell back and why, and what the
next phase needs.

## What judges are scoring — keep this in view

| | Criterion | Proven by |
|---|---|---|
| J1 | Innovation | Offline RL on CP-SAT expert trajectories; automated department compatibility |
| J2 | Feasibility | It runs, end-to-end, seeded, from one command |
| J3 | Scalability | `tests/test_scalability.py` — a new corridor is config only |
| J4 | Govt. integration | Adapters mapping PWI→TMS, S&T→SMMS, OWD→TDMS, plan→BDMS, live←COA |
| J5 | Before/after impact | `artifacts/impact_comparison.csv` — ten measured metrics |

Every top-level module's `README.md` opens with `<!-- serves: J… -->`. `REPORT.md` ends with the
traceability table mapping each criterion to the artifact that demonstrates it.
