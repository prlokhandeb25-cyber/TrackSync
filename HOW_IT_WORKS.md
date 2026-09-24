# How each feature works, and what can honestly be called optimal

Plain descriptions of the mechanism behind every feature, so each claim can be defended. Numbers come from
runs on this repository's data; where an input is assumed, `ASSUMPTIONS.md` says so.

## The one-paragraph answer on "is it optimal?"

- **The weekly plan is provably optimal for its stated objective.** CP-SAT (an exact solver) ends `OPTIMAL`
  on the 40-job week in about 27-47 s: it proves no plan scores better on the model. "Best" means best on the
  objective and weights we wrote down (`config/config.yaml`), which are our choices, not a law of nature.
- **Every rule is checked twice.** A separate referee re-checks the finished plan straight from the timetable
  (167 checks, 0 violations), and the tests show it failing on deliberately broken plans.
- **The live, fast parts are heuristics, and we say so.** Sudden tasks, early-finish reuse and grouping use
  fast rules, not proofs. They are compared with the exact answer where that can be measured (the learned
  dispatcher lands within about 11-13% of the exact solver's objective and re-plans about 25x faster).

## 1. Gap finder
For every track, the timetable is scanned for the space between one train leaving and the next arriving.
A gap's **usable** time is what is left after a lookout margin (5 min before the next train), protection
set-up (15 min) and hand-back (10 min); a job needs at least 15 minutes of real work, on a 5-minute grid.
Each gap gets a **reliability**: the chance the train before it runs late enough to eat into it. Night
windows are read from the last and first train on each track (not assumed), and the Sunday megablock is
checked against measured traffic. An interval tree finds candidate gaps in microseconds (a measured
speed-up over scanning every window, with identical answers).

## 2. Gap creation
When no gap is long enough, three levers are priced and the cheapest wins: **hold** a train a few minutes,
**reroute** a long-distance or freight train, or run a section **single-line**. Cost = train-minutes +
passenger-minutes. Suburban locals are never rerouted (asserted in the code and the tests).

## 3. Department rules
A rule engine gives every pair of jobs one of three verdicts: compatible, needs an Integrated Work Permission,
or incompatible, with the rule that decided it. Incompatible pairs get disjoint times (a hard constraint).
Adjacent-but-distinct places (a section and the station at its end) are compatible.

## 4. Weekly block plan (CP-SAT)
Each job is an interval that must sit inside a candidate gap after set-up and before hand-back. Hard
constraints: department allotment, incompatible pairs disjoint, permit quota, two gangs per department,
station concurrency, daily block limit. Objective: place as many jobs as possible, prefer gaps between trains
to night windows, reward jobs that share a block, penalise passengers within reach, penalise fragile windows.
The solver proves optimality on this model. If time runs out it reports the gap to the best bound.

## 5. Robust start times
Each block is simulated 400 times: the train ahead is late by a random draw, the work takes a random multiple
of its plan (15% spread). The start is then slid within its gap to where the block is most likely handed back
in time, and the referee re-checks every move. Measured: about 88% of simulated days clear on time without
this, about 97% with it.

## 6. Passenger and frequency heuristics
An hour-by-hour train count per section and an estimated load per train (3,000 people on a suburban train
at peak) give "passengers within reach" of any slot (services within 30 min either side). Every scheduler
prices it, so work lands where fewer trains and people are affected: about 75% fewer passengers within reach
than timing that ignores them (estimated loads, A-040).

## 7. Sudden tasks
Fit it into an existing gap; if none, create a gap (section 2); if none, **bump**: move at most two strictly
lower-priority jobs, never work already under way, and re-place them; else book the earliest slot and flag it
late. This is the destroy-and-repair idea of ALNS with one destroy move and no learned operator weights; it
is a heuristic (answers in milliseconds), not a proof of optimality.

## 8. Early-finish reuse
Each block is given the time its crew really takes. If it finishes early, the rest is already protected with
the crew on site, so waiting small jobs on the same section fill it: urgent first, then longest first, only
if they fit. Each saves a set-up and a hand-back. The amount depends on two assumptions (the waiting list and
crew timing, A-053) and grows with block length; on this plan it is small, and the page says so.

## 9. Grouping by place and urgency; small jobs riding in big blocks
Each job becomes a point: its position in km plus its priority (one step = 2 km). Average-linkage clustering
groups points closer than 5 km, so a P1 is not grouped with a P5. K-Medoids (picks a real job as each group's
centre, group count chosen by silhouette) is offered as an alternative and both are scored. In each group the
biggest job is the anchor; a job of 45 minutes or less, within one priority step, and allowed by the rules
rides in the anchor's block. Distance only proposes groups; the rule engine decides what may share a block.

## 10. Digital twin
The real timetable for the next 12 hours is replayed with the closure in it. A train's delay carries along its
route (winning back 30 s per section) and pushes the trains behind it on every track (no overtaking, 120 s
headway). Three responses are compared on the same 20-30 random days: hold everything, divert long-distance
and freight, divert plus run locals single-line. Only delay the closure adds is counted. The best response
changes with the time of day, which is why it is replayed rather than assumed. Recovery and single-line
capacity are assumed (A-046).

## 11. Rerouting
Shortest path around the closed section (as several candidates), accepted only if it stays inside that train
class's delay limit. Compared with simply waiting for the block to lift. The twin can overrule a detour that
costs passengers more than waiting. Locals are excluded before the search runs.

## 12. What a job needs on site
Typical crew by role, machines and materials per kind of work, scaled by length (a relief crew per extra 4 h;
flagmen when the track is closed; a power controller and earthing party for a power block). These are planning
norms, not a prediction (A-052).

## 13. AI dispatcher
An offline-RL policy trained on the exact solver's own plans. Illegal actions are masked before the choice, so
rule violations are zero by construction, and this is asserted in evaluation. It re-plans in milliseconds.

## 14. Scale test
The same weekly model is built for 40, 100, 200 and 400 random jobs (the per-day block cap grows with the
workload) and solved with a fixed time budget while the solver's own progress is logged: when it first had a
plan, when its plan was provably within 10%, 5% and 1% of the best possible, and where it stopped. "Proven
optimal" appears only if the gap closed to zero; otherwise the gap reached is shown. A fast heuristic runs on
the same jobs for comparison (quick, no proof).

## 15. Trade-off plans
Five plans, each the exact solver's answer to a different weighting of the same model, starting from the plan in
force and paying a small cost per job moved, so a difference between plans is a real trade-off, not noise. Each
is scored on jobs placed, passengers within reach and how often blocks clear before the next train; a plan another
beats on all three is marked beaten. Choosing one only proposes it.

## 16. Machines and travel
Each machine kind has a small pool. In the solver, every machine job takes one machine while it runs and any two
jobs on the same machine are separated by the travel time between their sections. A checker applies the same rule
to any plan, so the live plan can be scored (it has a conflict today) and the machine-aware plan shown to have none.

## 17. Approvals and audit
A proposal is a whole alternative plan with what it changes. It needs a stated reason to approve or reject, only
an approved one can be applied, applying keeps a snapshot, and a revert restores the previous plan exactly. Apply
is refused while sudden tasks are booked against the current plan. Every step is appended, with who and when, to
`artifacts/audit_log.jsonl`.

## 18. Learning from execution
Each logged completion (planned versus actual minutes, dry or rain) moves that group's estimate from a neutral
prior toward the data, and the buffer follows. No data means no buffer. Real logs and a labelled simulated stream
are kept apart.

## What is not claimed
- Early-warning prediction was removed: the feed was simulated, so accuracy could not be measured.
- The assumed inputs (crew timing, waiting list, passenger loads, recovery per hop, task data) are listed in
  `ASSUMPTIONS.md` with how to replace each with real data.
- Track geometry is still straight lines between stations.
