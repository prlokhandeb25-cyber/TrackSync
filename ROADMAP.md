# Roadmap — deliberately not built

Everything here was scoped out on purpose. The prototype had days, not weeks, and the
discipline that made it finish was refusing to start these. They are written up so the
direction is clear without anything being half-implemented.

---

## Deferred by design (Tier C throughout)

### Evolutionary multi-objective calendar search

An NSGA-II layer over the CP-SAT and RL output, searching the weekly and monthly calendar for a
Pareto front across asset availability, cost and risk rather than a single weighted optimum.
The planner would hand a controller three or four genuinely different weeks to choose between
instead of one answer.

**Why not now:** the weighted objective already produces defensible plans, and a Pareto layer
adds a tuning surface without adding a demonstrable result. Deferred from the first day and
never started.

### Live integration with the IR systems

The adapters exist as interfaces with mock implementations; `adapters.mode: live` is the only
switch on this side. What is missing is the other side: real endpoints, authentication, and
the actual payload schemas for BDMS, COA, TMS, SMMS and TDMS.

**Why not now:** these are internal systems with no public API. The payload shapes in the code
are our best-effort assumptions, clearly labelled as such. Inventing plausible API documentation
and presenting it as real would be the fastest way to lose a domain evaluator's trust.

### Field-worker mobile app

Defect capture and work-completion sign-off from the trackside, feeding the task pool directly
instead of through a department head. This is what would make the demand-task path real rather
than simulated.

### IoT and computer-vision defect detection

Track-recording-car output, axle-counter telemetry and OHE imagery feeding defects
automatically. The track-status FSM already models `FIT → SICK` on a reported defect; this
changes only who reports it.

### Division → zone → national rollout, with per-zone models

The corridor config proves a new line is a config file. A national rollout adds two things this
prototype does not have: federated training so each zone's dispatcher learns from local traffic
without centralising data, and partitioned solving so a zone-sized CP-SAT model stays tractable.

### Crew rostering and material logistics in the same model

Gang capacity is currently a flat cumulative constraint. Real planning must also place the
right gang with the right competence and the right material at the right site, which turns the
scheduling problem into a joint one.

### Signalling-level digital twin

Microsimulation at signal-section granularity, to verify block clearance rather than assume it.
The current model treats an inter-station section as the unit of occupancy with a headway rule,
which is right for planning and too coarse for safety verification.

---

## Wanted, and not reached in the time available

These are not deferred on principle — they ran out of clock.

| | |
|---|---|
| **Third RL algorithm** | An offline advantage-weighted actor-critic alongside BC and CQL-DQN. Vanilla A2C is on-policy and not valid trained purely offline; the adaptation is the interesting part. The evaluation harness already supports a fourth row |
| **Continuous demand arrivals** | Today the reactive path is exercised by one scripted injection. Stochastic arrivals through a simulated week would show it is reactive rather than staged |
| **Rerouting as an explicit solver lever** | Currently modelled as window-extension cost. The domain distinction is implemented and asserted — intercity and freight may take an alternate path, suburban locals may only swap UP/DN on the same section — but the solver does not yet choose paths |
| **Closing the V5 residual** | 1,050 sub-headway events remain, all real intercity services published at 60-second spacing. Three repair strategies hit a floor; the next is absorbing the hold into the follower's dwell with a per-station cap, or modelling more than one fast path through the CSMT–Kalyan throat |
| **More expert data** | Both learned models peaked at training step 1,000 of 6,000. The 14.8% gap would likely narrow with a larger dataset or stronger regularisation |
