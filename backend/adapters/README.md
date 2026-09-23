<!-- serves: J4 -->
# Government System Adapter Interfaces & Integration Boundary

RailBlock AI is designed as an intelligent planning plug-in that interfaces cleanly with existing Indian Railways software systems rather than replacing them.

## System Mapping & Data Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Existing Indian Railways System Infrastructure            │
│                                                                             │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐                 │
│  │     TMS      │     │     SMMS     │     │     TDMS     │                 │
│  │ (PWI Track)  │     │(S&T Signal)  │     │(OWD Traction)│                 │
│  └──────┬───────┘     └──────┬───────┘     └──────┬───────┘                 │
└─────────┼────────────────────┼────────────────────┼─────────────────────────┘
          │ defects & tasks    │ signalling tasks   │ OHE & power constraints
          ▼                    ▼                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            RailBlock AI Core                                │
│        Department Compatibility Engine & Hybrid CP-SAT / RL Planner         │
└─────────┬─────────────────────────────────────────┬─────────────────────────┘
          │ Sanctioned Block Demands                │ Live TSR / Speed Caps
          ▼                                         ▼
┌───────────────────────────────────┐     ┌───────────────────────────────────┐
│               BDMS                │     │                COA                │
│  (Block Demand Management System) │     │    (Control Office Application)   │
└───────────────────────────────────┘     └───────────────────────────────────┘
```

## Adapter Interface Specifications

| System | Role in Indian Railways | Method Signatures | Payload Structure |
|---|---|---|---|
| **BDMS** | Block Demand Management System | `fetch_pending_block_demands()`, `submit_block_plan(plan)`, `fetch_sanction_status(block_id)` | `{ demand_id, department, section_id, duration_min, status }` |
| **COA** | Control Office Application | `fetch_live_train_positions()`, `fetch_actual_running(date)`, `notify_block_impact(sec, speed)` | `{ train_id, lat, lon, delay_min, speed_cap_kmph }` |
| **TMS** | Track Management System (P-Way) | `fetch_track_defects()`, `post_work_completion(task_id, status)` | `{ defect_id, section_id, severity, recommended_speed }` |
| **SMMS** | Signalling Maintenance Management System | `fetch_signalling_tasks()`, `post_work_completion(task_id, status)` | `{ task_id, section_id, equipment }` |
| **TDMS** | Traction Distribution Management System | `fetch_ohe_tasks()`, `fetch_power_block_constraints()`, `post_work_completion(task_id, status)` | `{ task_id, section_id, feeder, isolation_time_min }` |

*Note: These interfaces represent internal Indian Railways software systems that do not expose public APIs. Schemas are best-effort assumptions pending official CRIS API integration.*
