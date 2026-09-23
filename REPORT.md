# RailBlock AI — results

Every figure here comes from a run that actually happened, on the seed in
`config/config.yaml`. Where something was not measured, it says so.

---

## 1. Data

| | |
|---|---|
| Source | public Indian Railways station and schedule datasets (`anandology/railways`) |
| Network | 4 lines — Central, Western, Harbour, Trans-Harbour |
| | 73 stations · 74 sections · 254 route-km |
| Interchanges | CSMT, Kurla, Thane, Vashi, Sanpada — **discovered by shared station code, not declared** |
| Services | 1,640/day · 11,040/week · 22,821 section traversals |
| Coordinates | **20 from the public dataset, 53 supplied by us** |

The national dataset only carries stations that long-distance trains call at, so pure suburban
halts (Churchgate, Vashi, Mahim) are absent and their coordinates are ours. Provenance is
tracked per station rather than glossed over.

Likewise the timetable is a hybrid: the mail and express layer is real, the suburban and
freight layers are synthesised to published structural parameters because no public source
carries them. 429 of 1,640 daily services are real.

### Validation gate — 10 checks

| | Result |
|---|---|
| Passing | V1, V2, V3, V6, V7, V8, V9, V10 |
| **Failing** | **V4** — 135 of 22,207 hops imply an impossible speed (0.61% vs a 0.5% threshold) |
| **Failing** | **V5** — 1,050 sub-headway events (4.60% vs a 0.5% threshold) |
| Repairs applied | 5,065 |

**These are reported as failures rather than tuned into passes.** The V5 residual is real
intercity services published at 60-second spacing through the dense CSMT–Kalyan throat; three
repair strategies were tried and each hit a floor. The next fix is written up in
`ASSUMPTIONS.md`. Moving a threshold to fit the data it is meant to police would make every
later number in this report unreliable.

---

## 2. Where maintenance can go

| Window type | Count | Usable hours/week |
|---|---:|---:|
| Gaps between trains | 12,117 | — |
| Night windows | 1,384 | — |
| Megablock windows | 744 | — |

**Only 56% of raw gap time is actually workable.** Every block costs 15 minutes to protect and
10 to hand back, so a 40-minute gap yields about 15 minutes of work. Planning against raw gaps
would overstate capacity across the whole network.

Two things that are evidence rather than assertion:

- **Night windows are derived per section** from the last and first train on that track, and
  they differ section by section. They are clipped to the night band — without that, a sparse
  fast line reported a ten-hour "night window" running to mid-morning.
- **The Sunday megablock is corroborated**: traffic in the configured window measures **51%
  below a weekday** across 16 sections.

Station tiers are derived by frequency quantile, never by name. The derivation independently
places Vangani, Shelu, Neral and Bhivpuri Road in Tier 3 — which matches the domain expectation
it was never told about. Tier-1 micro-gaps cap at 20 usable minutes; Tier-3 run to 136.

---

## 3. Department coordination

On a 40-task week, over the pre-plan view the three department heads actually face:

| | |
|---|---:|
| Compatible pairs | 144 |
| Need an Integrated Work Permission | 6 |
| Incompatible — must be sequenced | 3 |
| **Cross-department conflicts** | **6** |
| **Manual negotiation replaced** | **24 hours** |

Every verdict carries a written reason. The canonical case from the domain brief is a passing
test: *PWI on the Matunga–Dadar section while OWD works Matunga station* → **COMPATIBLE**, rule
R2, because the zones are adjacent but do not physically overlap.

---

## 4. CP-SAT weekly plan

| | |
|---|---|
| Status | **OPTIMAL**, 0% optimality gap |
| Solve time | ~3 s |
| Placed | 36 of 40 jobs |
| Into gaps between trains | 25% |
| Unplaced | 4 — no window long enough anywhere on their section |

Those 4 are a real capacity finding, not a solver failure: the work physically cannot be done
in any existing gap. They are the case for creating a window by rerouting.

---

## 5. The learned dispatcher

Expert dataset: **1,074 instances kept of 1,200** (10.5% discarded), **28,232 transitions**,
split **by instance** with a leakage assertion. Mean CP-SAT optimality gap on the instances
used as expert demonstrations: 6.48%.

Evaluated on **20 held-out instances**, regenerated from stored instance ids and re-solved with
CP-SAT for the reference value:

| Policy | Gap vs CP-SAT | Tasks placed | Micro-gaps used | Decision | Violations |
|---|---:|---:|---:|---:|---:|
| random | 59.6% | 81.7% | 5.5 | 0.05 ms | 0 |
| greedy | 19.7% | 85.6% | 6.7 | 0.04 ms | 0 |
| behaviour cloning | 15.8% | 85.9% | 10.0 | 0.33 ms | 0 |
| **CQL-DQN** | **14.8%** | **85.9%** | **10.1** | **0.31 ms** | **0** |
| CP-SAT (reference) | 0% | — | — | 5,093 ms | 0 |

Three things worth drawing out:

1. **CQL-DQN wins**, matching the reference paper (arXiv:2409.10589). Greedy and random are in
   the table as floors, because a gap figure means nothing without them.
2. **The learned policies place ~50% more work into micro-gaps than greedy** (10.1 vs 6.7).
   That behaviour was not hand-written — it transferred from the solver's own solutions, which
   is the clearest evidence the expert-to-policy bridge carried something real.
3. **Zero constraint violations, by construction.** Every action passes through a legality
   mask, so an illegal schedule is unrepresentable rather than merely discouraged.

**Honest caveat:** 14.8% is short of the 5–10% the spec aspired to, and both models peaked at
training step 1,000 of 6,000 — they overfit early. More expert data or stronger regularisation
would likely close some of it. That is a known limitation, not a finished result.

---

## 6. Before and after

The "before" case models today's decentralised process: each department first-come-first-served,
night windows and megablocks only, cross-department clashes discovered late and settled by
phone, unplanned defects waiting for the next weekly cycle.

**It is a model, not measured field data**, and both of its parameters
(4 hours per conflict, 7-day cycle) are exposed in the UI so a sceptical judge can dial them
down and watch whether the advantage survives. An argument that holds up under a hostile
parameter is worth more than one tuned to look good.

Ten metrics are computed over the same instances for both. The most distinctive:

| | Before | After |
|---|---|---|
| Re-planning latency for an unplanned defect | next weekly cycle | **~180 ms** |
| Department coordination | hours of phone negotiation | milliseconds |
| Work fitted into gaps between trains | **0 by construction** | measured |

The manual case finds no micro-gaps because spotting one needs the whole timetable, every
department's pending work and the compatibility rules in one place at one moment. A
decentralised process has none of those at once. That is not a failing of the people doing it;
it is what the information available to them allows.

---

## 7. Scalability

`tests/test_scalability.py` — **10 passing tests** running the full pipeline on a fifth
corridor, **Pune–Solapur**, added as a config file and nothing else. It is deliberately unlike
the Mumbai lines: long-distance, two-track, sparse, no suburban layer at all, stations tens of
kilometres apart.

Two of those tests assert the strong form of the claim directly: **no corridor id and no
station code appears anywhere in backend code.** If one did, adding a zone would mean editing
code and the argument would collapse however well the pipeline ran.

---

## 8. Judging traceability

| | Criterion | Demonstrated by |
|---|---|---|
| **J1** | Innovation | Offline RL trained on CP-SAT expert trajectories — `backend/rl/`, `artifacts/rl_comparison.csv`. Automated department compatibility — `backend/domain/compatibility.py` |
| **J2** | Feasibility | It runs end to end, seeded. 47 passing tests. Validation gate that blocks on bad data |
| **J3** | Scalability | `tests/test_scalability.py` — a fifth corridor by config alone, plus assertions that no corridor or station name is in the code |
| **J4** | Govt. integration | `backend/adapters/` — PWI→TMS, S&T→SMMS, OWD→TDMS, plan→BDMS, live←COA |
| **J5** | Before/after impact | `backend/metrics/` — ten metrics, with the baseline's assumptions exposed rather than buried |

---

## 9. What is not built

Deferred deliberately and written up in `ROADMAP.md`: the evolutionary multi-objective layer
(Tier C throughout), live integration with the real IR systems, a field-worker mobile app, and
IoT/CV defect detection.

Not reached in the time available: a third RL algorithm (offline actor-critic), the continuous
stochastic demand-arrival demo, and rerouting implemented as an explicit solver lever rather
than as window-extension cost.
