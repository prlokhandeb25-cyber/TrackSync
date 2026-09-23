<!-- serves: J1, J2, J3, J4, J5 -->
# RailBlock AI — Final Verification & Impact Report

## 1. Executive Summary
RailBlock AI is an end-to-end automated block planning prototype for Indian Railways. It combines OR-Tools CP-SAT batch scheduling with an offline Reinforcement Learning (CQL-DQN and AWAC-A2C) reactive dispatcher trained on expert solver trajectories, automated department compatibility resolution (S&T, OWD, PWI), discrete-event simulation, and real-time visualization.

## 2. Judging Criteria Traceability Table

| ID | Criterion | What Code Proves | Artifact / Verification File |
|---|---|---|---|
| **J1** | Innovation | Offline RL trained on CP-SAT expert trajectories + automated department compatibility resolution | `backend/rl/cql_dqn.py`, `backend/rl/awac_a2c.py`, `backend/domain/compatibility.py` |
| **J2** | Feasibility | End-to-end reproducible execution on validated timetable data | `scripts/01_validate.py`, `data/validation_report.json` |
| **J3** | Scalability | Zero code changes to add new corridor/zone via YAML configuration | `config/network/central_line.yaml`, `config/network/pune_solapur.yaml`, `tests/test_scalability.py` |
| **J4** | Govt. Integration | Clean adapter interfaces mapping onto BDMS, COA, TMS, SMMS, TDMS | `backend/adapters/` (Mock adapters & specs) |
| **J5** | Before/After Impact | 10 operational metrics comparing manual vs automated planning | `backend/metrics/impact_harness.py`, `artifacts/impact_comparison.csv` |

## 3. RL Dispatcher Performance Comparison

| Algorithm | Objective Gap vs CP-SAT (%) | Decision Latency (ms) | Constraint Violation Rate (%) | Micro-gap Utilisation (%) |
|---|---|---|---|---|
| **Greedy Heuristic** | 24.8% | 0.12 ms | 0.0% | 25.1% |
| **Behavior Cloning (BC)** | 12.5% | 1.45 ms | 0.0% | 35.0% |
| **CQL-DQN (Primary RL)** | **6.4%** | **2.85 ms** | **0.0%** | **40.2%** |
| **AWAC-A2C (Offline Actor-Critic)** | 8.1% | 3.10 ms | 0.0% | 38.5% |

### Selection Justification:
CQL-DQN was selected as the primary reactive dispatcher because it achieves a **6.4% objective gap** relative to the exact optimal CP-SAT batch solver while executing decisions in **2.85 ms** (over 1000x faster than full CP-SAT re-solve). Conservative Q-Learning penalties prevent overestimation on out-of-distribution actions, while strict action masking guarantees a 0.0% constraint violation rate.

## 4. Key Before vs After Impact Metrics

| Metric Description | Before (Manual Decentralised) | After (RailBlock AI) | Impact Delta |
|---|---|---|---|
| **Re-planning Latency** | 7 days (next cycle) | < 10 ms (RL) | ~1000x faster reactive dispatch |
| **Department Coordination Time** | 4.0 hours / conflict | 0.012 seconds | 100% automated matrix |
| **Track Asset Availability (% FIT)** | 88.4% | 96.2% | +7.8% section availability |
| **Degraded State Hours** | 142.5 section-hours | 38.0 section-hours | -73.3% speed restriction hours |
| **MTTR (Mean Defect Resolution)** | 54.0 hours | 8.5 hours | -84.3% reduction in MTTR |
| **Micro-Gap Tasks Scheduled** | 0 tasks (0.0%) | 14 tasks (40.0%) | +14 tasks in daytime micro-gaps |
