<!-- serves: J1, J2, J3, J4, J5 -->
# RailBlock AI: AI-Powered Automatic Block Planning for Indian Railways

RailBlock AI is a Smart India Hackathon (SIH) prototype demonstrating automated maintenance block planning for Indian Railways. It integrates OR-Tools CP-SAT batch scheduling with an offline Reinforcement Learning (CQL-DQN and AWAC-A2C) reactive dispatcher trained on expert solver trajectories, automated department compatibility resolution (S&T, OWD, PWI), station-tier gap engine analysis, discrete-event simulation, and real-time visualization.

## Judging Criteria Traceability Table

| ID | Criterion | Key Artifacts & Demonstration |
|---|---|---|
| **J1** | Innovation | `backend/rl/cql_dqn.py`, `backend/rl/awac_a2c.py`, `backend/rl/trajectory_gen.py`, `backend/domain/compatibility.py` |
| **J2** | Feasibility | `scripts/demo.py`, `backend/data/validate.py`, `data/validation_report.json` |
| **J3** | Scalability | `config/network/central_line.yaml`, `config/network/pune_solapur.yaml`, `tests/test_scalability.py` |
| **J4** | Govt. Integration | `backend/adapters/` (BDMS, COA, TMS, SMMS, TDMS mock adapters & specs) |
| **J5** | Before/After Impact | `backend/metrics/impact_harness.py`, `artifacts/impact_comparison.csv`, UI Impact Tab |

## Quick Start (One Command Demo)

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run the full validation, expert generation, RL evaluation, and launch backend/frontend
python scripts/demo.py
```

## Architecture

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

## Key Innovation Summary
1. **Offline RL Trained on CP-SAT Expert Trajectories**: CP-SAT generates optimal weekly batch schedules. State-action trajectories are logged to train an offline RL agent (CQL-DQN / AWAC-A2C). The RL agent provides millisecond-latency reactive re-planning when unplanned demand defects appear during operations.
2. **Automated Department Compatibility**: Replaces manual phone negotiations between Signalling & Telecom (S&T), Overhead Wire Department (OWD), and Permanent Way Inspector (PWI) with a computed geometric compatibility matrix (Rules R0–R4), including Integrated Work Permission (IWP) quota handling.
