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

### Early-warning feed and full ALNS

The predictive-blocks panel runs on a simulated watch list (A-048); connecting a real condition-monitoring feed
(image analysis on inspection-vehicle or drone video, track-recording cars, telemetry) is the one missing input.
The scheduler for live arrivals is ALNS-lite: repair, one bounded destroy step, no learned operator weights and no
run to convergence; a full ALNS with several destroy operators and adaptive weights would be the next step.


### Assessed and left out: rolling-stock assignment, short-turning and skip-stop (arXiv 2404.04233)

Salode and Ramamoorthy design the timetable of a bidirectional metro line: which services run, when, and how the
trains are assigned to them, to cut passenger waiting time and operating cost. Assessed against this project's problem
(placing maintenance blocks into the gaps of a given timetable):

- **Rolling-stock assignment** decides which physical train runs which service. The timetable is an input here and
  rake circulation and depots are outside block planning, so it does not help.
- **Skip-stop** redesigns which stations a service serves to cut waiting time. It needs origin-destination demand, which
  this project does not have (passenger loads are an assumed per-train figure, A-040), and it changes the timetable that
  block planning takes as given. Mumbai's fast and slow lines already are a form of it. It does not help.
- **Short-turning** is the one idea with a place here: when a section is fully closed, locals could turn back at the
  last open station on each side instead of queueing (the paper cites Ghaemi et al. 2018 for this). Not integrated,
  because it cannot be done honestly yet: the network config has no data on which stations can turn a train back, the
  timetable does not link a terminating train to the service it forms next, and the digital twin has no back-pressure
  on the approach side, so it would count a short-turned train's passengers once but a held train's at every section
  and show a benefit that is an artefact of counting. The timetable already includes the turn-back patterns locals run
  every day (`suburban.patterns`, e.g. CSTM to TNA, DI, ABH, BUD).
- **Scale:** the paper's exact models reach the 4-hour time limit on instances of 30-60 trains and some find nothing;
  this system plans a week for hundreds of trains, which is why it plans against a fixed timetable.

Would need before revisiting: turn-back capable stations and turn-back times per station, the train-to-service linking
for terminating trains, and queue spill-back on the approach side in the twin.

### Signalling-level digital twin

Microsimulation at signal-section granularity, to verify block clearance rather than assume it.
The current model treats an inter-station section as the unit of occupancy with a headway rule,
which is right for planning and too coarse for safety verification.

### Simulated Annealing over the train timetable

Nudging real departure times (a couple of minutes here and there) around planned maintenance
blocks, cooling toward a network-wide schedule that minimises total commuter delay, was
requested alongside the Operations-page rework.

**Why not now:** every other part of this project is built around a promise the demo repeatedly
makes to judges — that trains are not the thing being moved, only maintenance work is. Touching
real departure times is a materially different, much larger problem (it has to re-derive
occupancy and re-run gap-finding for whatever it changes) and risks quietly contradicting that
promise days before a demo. If this is ever built, it belongs as its own reviewed phase, not a
same-day addition to the Operations map.

### Capacitated Arc Routing (CARP) for maintenance-vehicle logistics

Routing tamping rakes and OHE tower wagons from depot to work site as a capacitated
arc-routing problem over the track network.

**Why not now:** there is no depot, vehicle or capacity data model anywhere in this project —
building one from scratch, honestly labelled as invented (per CLAUDE.md's honesty invariant),
is a lot of net-new scope for a capability nothing currently asks for beyond the map looking
busier. Worth doing once real depot/fleet data exists to model against.

### Clustering on the Department-coordination tab

Job clustering itself now exists (`backend/planner/clustering.py`, shown on the Operations tab as
"Job clusters"). What is still not built is surfacing the same grouping inside the
compatibility matrix on the Department-coordination tab (the matrix itself is now hidden there). K-Medoids
now exists as an alternative to the average-linkage method, with both scored on the same jobs (A-050);
average-linkage stays the default because it scored higher on the live pool. Not yet done: using the medoid
job's zone as the proposed site for a shared block.

---

## Wanted, and not reached in the time available

These are not deferred on principle — they ran out of clock.

| | |
|---|---|
| **Third RL algorithm** | An offline advantage-weighted actor-critic alongside BC and CQL-DQN. Vanilla A2C is on-policy and not valid trained purely offline; the adaptation is the interesting part. The evaluation harness already supports a fourth row |
| **Continuous demand arrivals** | *Partly closed*: the Operations tab now generates a small batch of unplanned tasks every ~7 seconds and gap-schedules them live with Max-to-Min ordering + an ALNS-lite destroy/repair (`backend/planner/live_sim.py`, ASSUMPTIONS A-027/A-028). What is still missing is arrivals following a realistic stochastic process across a full simulated week, rather than a fixed tick interval |
| **Rerouting as an explicit solver lever** | *Partly closed*: rerouting is now a lever inside gap creation (`backend/gaps/creation.py`) and is executed live on the Operations map, priced in train-minutes. What is still missing is path choice inside CP-SAT's own model, so the solver could trade a detour against a window jointly |
| **Real track geometry** | Sections are still straight lines between stations. Curved alignment from OpenStreetMap (or divisional track diagrams), and a genuinely separate fast/slow track layout for the Harbour and Trans-Harbour lines if they turn out to need one |
| **Closing the V5 residual** | 1,050 sub-headway events remain, all real intercity services published at 60-second spacing. Three repair strategies hit a floor; the next is absorbing the hold into the follower's dwell with a per-station cap, or modelling more than one fast path through the CSMT–Kalyan throat |
| **More expert data** | Both learned models peaked at training step 1,000 of 6,000. The 14.8% gap would likely narrow with a larger dataset or stronger regularisation |


### Real passenger loads and real track geometry

The passenger model uses invented per-train loads and one hour-of-day profile (ASSUMPTIONS A-040);
real footfall per station-hour and directional peaks would replace them. Tracks are still drawn as
straight lines between stations; OpenStreetMap centre-line geometry is the planned replacement
(A-010, A-031). Neither changes an algorithm, only the data it reads.
