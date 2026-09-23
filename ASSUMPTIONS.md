# ASSUMPTIONS

Every invented number and rule in this project, with its rationale and how it would be replaced
with real data. Maintenance-task data, coordination times, block overheads and speed restrictions
have **no public real-world source** — that is fine and defensible, but only if written down.

Updated in the same commit that introduces the assumption (CLAUDE.md invariant).

| ID | Assumption | Value | Why this value | How to replace with real data |
|----|-----------|-------|----------------|-------------------------------|
| **P0 — configuration baseline** |
| A-001 | Global seed | `20260923` | Arbitrary; fixed so every run reproduces | n/a — stays synthetic by design |
| A-002 | Service date for the planning week | `2026-09-21` (a Monday) | PLANNED tasks are finalised "every Monday" (SPEC §5.4), so the week starts Monday | Align to the division's actual weekly planning cycle date |
| **P1 — data, validation and timetable structure** |
| A-003 | Minimum headway between consecutive trains on a track | 120 s | Mumbai suburban runs a ~3 min peak headway on the Central main line; 2 min is the tightest physically plausible separation and so the right *validation* floor rather than the operating target | Signalling section headway from the division's working timetable |
| A-004 | Dwell time bounds at a non-terminal stop | 20 s – 20 min | Suburban locals dwell ~20–30 s; anything beyond 20 min at an intermediate stop indicates a data error, not an operation | Actual dwell from COA running data |
| A-005 | Minimum plausible implied speed | 15 km/h | Below this, a point-to-point run time implies a data error rather than a slow section | Section-wise permanent speed restrictions from the PWI |
| A-006 | Corridor must carry ≥ 200 services/day | 200 | Below this the corridor is not the busy-corridor case the problem statement targets, and gap analysis becomes trivial | n/a — validation threshold only |
| A-007 | Synthetic timetable structure (fallback) | ~1,240 services/day; peak headway 3–5 min (07:00–11:00, 17:00–21:00); off-peak 8–15 min; last down ~00:45; first up ~03:55 | Matches the published structure of Central Railway Mumbai suburban operations; the shape is what the gap engine consumes, so structural fidelity matters more than exact train numbers | Replace wholesale with the real suburban working timetable |
| A-008 | Intercity/freight paths per day on long-distance links | 25–40 | Order-of-magnitude for a Maharashtra trunk route; enough to make rerouting meaningful without dominating the suburban picture | data.gov.in train schedule dataset |
| A-009 | Delay distributions (no punctuality source found) | suburban mean 2.5 min; intercity 12 min; freight 35 min; gamma, peak ×1.6 | Perfectly on-time synthetic schedules make the prototype look naive; these means reflect commonly reported punctuality behaviour by class, with freight heaviest-tailed | Fit per-class distributions from COA actual-vs-scheduled running data |
| A-010 | Section length and line speed where geometry is unavailable | great-circle distance × 1.15 route factor; 100 km/h suburban main, 110 km/h trunk, 60 km/h branch | Rail routes are longer than straight lines; the 1.15 factor is a standard planning approximation | OSM railway geometry, or the division's permanent way records |
| A-011 | V5 residual threshold for WARN vs FAIL | 0.5% of traversals | A real working timetable contains tight paths; demanding literally zero sub-headway events across every traversal is stricter than the railway itself. The exact residual count is always printed, so the number stays visible rather than hidden behind a pass/fail flag | n/a — validation policy. **Currently breached: see the P1 status note below** |
| A-012 | Days of operation for real long-distance services | ~66% daily; the rest 2–4 fixed days/week, assigned deterministically by train number | The public dataset has no day-of-operation field, so every train in it looks daily. Running all 247 corridor services on one date puts a whole weekly roster on a single day, over-saturating the fast lines and producing impossible 60-second following moves between expresses that never actually run together. Roughly two thirds of IR mail/express services are daily | Days-of-running from the division's working timetable |
| A-013 | Track configuration | CSMT–Kalyan: separate fast/slow pairs (UP_SLOW, DN_SLOW, UP_FAST, DN_FAST). Kalyan–Karjat: UP/DN only | This is how the corridor is actually worked, and it is why locals and expresses do not conflict on the main line. Suburban EMUs take the slow pair, mail/express the fast pair | Divisional track diagrams |
| A-014 | Freight pathing | Slow pair, night band 00:30–04:30 only | A 40 km/h freight cannot share a fast line with a 90 km/h express over 100+ km without looping, which this model does not represent. Real freight runs the slow lines overnight once the locals have stopped | Actual freight paths from the control office |
| A-015 | Line speeds are calibrated against observed real running | declared limit raised to observed p100 × 1.05, rounded to 5 km/h | Our configured limits are assumptions; the observed running of real published services is evidence. Where the two disagree the evidence wins, and every change is logged as a V4 repair rather than applied silently | Permanent speed restrictions from the PWI |

| **P2 — domain core, tasks and compatibility** |
| A-016 | Task durations per task type | 20 min – 6 h, per type | Spread reflects the nature of each job: a fish-plate attention is short, ballast screening and interlocking testing are long. The *types* are real categories of departmental work; the durations are ours | Historical job durations from TMS / SMMS / TDMS |
| A-017 | Completion outcome distribution per task type | e.g. tamping 55% FIT / 40% CAUTION_ORDER / 5% STOP_AND_START; joint attention 85% FIT | Some work reliably restores the section, some routinely leaves a speed restriction pending consolidation. Tamping typically leaves a temporary restriction; a joint repair usually does not | Post-work status records from TMS |
| A-018 | Squeezed jobs degrade more often | probability mass moves out of FIT in proportion to the shortfall, ×1.5, capped at 90% | This is what stops micro-gap scheduling from looking like free lunch. Fitting work into a short gap is a real option carrying a real risk, and the optimiser should price that risk rather than ignore it. Without this, the model would always prefer short gaps | Observed rework rates against block duration |
| A-019 | Follow-up after a degraded outcome | STOP_AND_START lifts to CAUTION_ORDER 65% / FIT 35%; CAUTION_ORDER lifts to FIT | A restriction is usually relaxed in stages rather than cleared at once | Speed restriction registers |
| A-020 | Department allotments differ per department | PWI 16 sections, OWD 15, S&T 14 | Identical full-corridor allotments would make rule R0 unenforceable — the constraint has to be able to bite for the rule to mean anything. The control office allots specific segments per week | The divisional control office roster |
| A-021 | Department-pair base matrix (R4) | all three pairs geometry-decided | We have no evidence for a blanket prohibition between any two departments, and inventing one would be fiction. The hook exists so a real rule can be added when we learn one | Divisional working rules |
| A-025 | Pune–Solapur corridor, used as the scalability fixture | 16 stations, all coordinates from the public dataset | Deliberately unlike the Mumbai lines: long-distance, two-track, sparse, no suburban layer. A Mumbai-shaped assumption hiding in the code fails there rather than passing quietly | n/a — the coordinates are real |
| A-023 | A section is SICK only where a defect was found | priority 1-2, or a fault-named task type | SICK means a defect needs attention. Routine preventive work - tamping on a cycle, a scheduled lamp change - happens on healthy track, so marking those sections sick both overstates corridor degradation and washes the map amber, hiding the sections that genuinely are degraded | Defect registers from TMS / SMMS / TDMS |
| A-022 | Same department, same zone, same time | INCOMPATIBLE — must be sequenced | One gang cannot be in two places; two gangs in one zone under one block is not how the work is organised | Gang rosters |

| **P-Ops — Operations map, live simulation** |
| A-026 | ~~Maharashtra state outline behind the network~~ | superseded by A-038 | The stylised state outline was replaced by a real Mumbai Metropolitan Region border | n/a |
| A-027 | Live-simulation tasks (Operations tab, ticking every ~7s) | same synthetic generation as the existing task pool (`backend/data/synth_tasks.py::generate_demand_task`) | Same precedent already used for demand-injection tasks; there is no real-time defect-reporting feed to draw from | A live feed from TMS/SMMS/TDMS (SPEC §16) |
| A-028 | ALNS-lite destroy/repair (`backend/planner/live_sim.py`) | one repair pass plus at most one bounded destroy-and-retry, not run to convergence | Scoped for a live, sub-second response on every tick rather than solution quality; it reuses the real compatibility rule engine so it can never place work the rules would reject, but it does not search as hard as CP-SAT's exact solve, and the UI names it "ALNS-lite" rather than "optimal" for exactly this reason | Run more destroy/repair rounds, or a real ALNS with an acceptance criterion, if this ever needs to beat greedy on solution quality rather than just be live |
| A-029 | Job-clustering cut distance | 5 km (average-linkage), `clustering.cut_km` | Jobs within a few stations of each other can plausibly share one protected block; far enough apart and they cannot. Only a grouping signal - whether grouped jobs may actually overlap is still decided by the compatibility rule engine | Tune against how far apart real integrated blocks are granted, from divisional block registers |
| A-030 | Live reroute overlay (`backend/planner/active_reroute.py`) | up to 3 long-distance/freight trains per closed section, delay = nominal run-time difference against the shortest route | Enough to show the mechanism without drawing every train; the overlay never rewrites the timetable or cached occupancy. Locals are never rerouted (guardrail inherited from `reroute_candidates`) | Real diversion rules and traffic-controller decisions from the control office |
| A-031 | Parallel-track drawing | one lane per entry in `section.tracks`, slow lines outside and fast lines inside, fixed 3.7 px spacing | The track counts are the configured ones (four on the Central/Western core, two elsewhere, matching the division system map); spacing and ordering are purely visual | Real track layout and geometry from OSM / divisional track diagrams (not yet sourced) |
| A-032 | Gap-creation limits (`gap_creation.*`) | one train held at most 4 min; a created gap may cost at most 30 train-minutes; near-miss = up to 12 min short; single-line waits at most 8 min per train and 60 train-minutes in total; at most 4 long-distance trains diverted per gap | Small enough that a controller could plausibly accept them as a routine concession, large enough to convert a real share of near-miss gaps. Every option is priced in train-minutes and shown, so the limits are visible rather than hidden | Divisional operating rules for holding, diverting and single-line working |
| A-033 | Minimum workable time in any gap | 15 min (`gaps.min_workable_min`), so a window needs at least 40 raw minutes | Requested requirement: no window shorter than 15 minutes of real work. 15 + the 25 min of set-up and hand-back (A-006 block overheads) gives the raw minimum | Field data on the shortest block that is worth protecting |
| A-034 | Deadlines for jobs raised through the form | priority 1: 6 h, 2: 24 h, 3: 72 h, 4-5: 7 days | Gives urgency a meaning, which is what makes gap creation matter: an urgent job cannot wait for the next night window. Simulated arrivals keep the existing 24 h | Defect-severity classes and repair-by times from TMS / SMMS / TDMS |
| A-035 | Integrated-block reward and the creation repair pass | `w8_integrated_block` = 6 per compatible cross-department pair sharing a block; after CP-SAT, unplaced jobs are placed into created gaps by a repair pass that checks compatibility but not the daily block cap or station concurrency caps | 12 made CP-SAT slow to prove optimal (about 60 s against about 20 s at 6). The repair pass is a fast pass instead of a second full solve; its two omissions are named here rather than hidden | Fold both caps into the repair pass, or a second solve with warm start |
| A-036 | Declared compatibility (`allows_with`) | a department ticks which OTHER departments may share a block with its job; if either side has not allowed the other, and they could overlap, the pair is INCOMPATIBLE by declaration (rule id DECL) | The form asks for exactly this; honouring it in the planner, scheduler and score means a declaration is a constraint, not a label. The rule engine's three verdicts are unchanged | The department heads' real standing agreements about who may work alongside whom |
| A-037 | Compatibility score | 100 x (compatible + 0.5 x needing a permit) / cross-department pairs, over the other departments' jobs in the same cluster; a job with none scores 100 and is flagged standalone | Simple enough to explain in one sentence and derived only from the rule engine's verdicts. The 0.5 for a permit is a judgement: usable, but administratively costly | Calibrate against how often each verdict actually delays real work |
| A-038 | Mumbai border | OpenStreetMap administrative boundaries (Mumbai Metropolitan Region, Mumbai City and Mumbai Suburban districts) via Nominatim, simplified to about 65 m, cached in `data/raw/osm_mumbai_borders.json` | Real boundary data, fetched once so the demo has no network dependency; all 73 stations fall inside it | Refresh with scripts/07_build_mumbai_border.py |
| A-039 | Month view | four rolling weekly cycles on the repeating weekly timetable; week 1 is the current plan, weeks 2-4 use freshly generated synthetic jobs plus the previous week's unplaced jobs | A single week's timetable repeats, so re-solving the same windows with a new backlog is a fair rolling programme; the job pools are synthetic like the rest (A-016) | A real 26-week Rolling Block Programme from the division |

---

## P1 status note — open issue, recorded rather than hidden

**V5 (no impossible train overlaps) does not pass.** After repair, 337 sub-headway events remain,
7.16% of 4,705 traversals, against the 0.5% threshold in A-011. The gate therefore reports **FAIL**
and the API and demo will refuse to serve this data, which is the intended behaviour.

The residual is understood and localised: every offender is a pair of **real** intercity services on
the fast lines, published in the source dataset at 60-second spacing through the dense CSMT–Kalyan
section. The source rounds long-distance times to whole minutes in this area, so genuine 2-minute
headways can appear as 1-minute ones.

Three repair strategies were tried and each hit a floor (2,772 → 567 → 376 → 337 conflicts):
whole-train nudging oscillates, because shifting a service also moves the stops it has already
made; holding in rear and propagating forward converges better but still leaves the bunched pairs.

**The next fix, not yet implemented:** absorb the hold into the follower's *dwell* at the station in
rear rather than translating its whole downstream schedule, and cap the per-station hold so a
regulated train cannot cascade into the service behind it. Failing that, the honest alternative is
to model the fast lines as they really are — more than one fast path per direction through the
CSMT–Kalyan throat — which removes the contention at its source.

The threshold in A-011 was deliberately **not** relaxed to make the gate green. Moving a threshold
to fit the data it is meant to police would make every later number in this project unreliable.

---

## Pending — to be filled in later phases

These are already specified in `SPEC.md` and will get rows as their phases land:

- **P2** — track-status outcome distributions per task type (SPEC §5.3), department base
  compatibility matrix (§7.2 R4), the power-block interaction rule, department allotments.
- **P3** — block setup/release overhead (15 / 10 / +10 min, SPEC §6.3), `min_usable_gap_min`,
  Sunday megablock window (Central main default 10:30–15:30).
- **P4** — objective weights (SPEC §10.3), gangs per department, IWP daily quota, station-tier
  window caps.
- **P9** — `manual_coordination_hours_per_conflict` (4 h) and `manual_replan_wait_days` (7), the
  two parameters that define the "before" baseline in SPEC §15.1. Both are exposed as UI sliders
  so a sceptical judge can dial them down and see whether the advantage survives.
