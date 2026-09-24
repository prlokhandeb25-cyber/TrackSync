# Demo script — five minutes

Rehearse it twice from a fresh terminal. The biggest risk on stage is a server that was already
running and is serving stale code. Numbers below are read off the screen, not memorised: every
figure in the app comes from a run that happened, and they can move between runs.

## Before you start

```powershell
# one terminal (the first start takes about a minute: it builds the timetable and solves the week)
.\.venv\Scripts\python.exe -m uvicorn backend.api.main:app --port 8000

# another
cd frontend; npm run dev
```

Open `http://127.0.0.1:5173` and wait for the map. Land on **Operations**. There are no map tiles;
the Mumbai border is cached OpenStreetMap data, so conference wifi cannot break anything.

---

## 1 · The network (30 s) — Operations

> "The Mumbai region, drawn from its real border. Every section is its real tracks — four abreast on
> the Central and Western core, two on the outer stretches. Trains run on their own track."

Point at a striped track with a crew on it.

> "That is maintenance happening right now, placed into a gap between trains."

Zoom in on it (scroll, or the + button).

> "Up close it is the work site: protected zone, cones and stop boards at each end, the crew, the
> machine for that department, and the track turns green behind it as the work progresses."

Set the speed to **5×**. Point at a cyan detour.

> "A long-distance train due through a closed section leaves it, the old path is crossed out, and it
> runs the detour. Suburban locals are never rerouted; where a section has two local tracks they run
> single-line instead, with crossovers at each end."

## 2 · A sudden task (75 s) — Operations, right column

> "Something breaks that nobody planned. Pick how urgent: low, medium, high, critical."

Press **Critical**. The map flies to it.

> "It was placed in milliseconds against about half a minute to re-solve the week. It says how: an
> existing gap, a gap it opened — with the cost in train-minutes and passengers — or lower-priority
> work it moved aside, and where that went."

Press **How it decided**. Point at "trains per hour at chosen sites vs network average".

> "It chooses quiet places and times. The same jobs placed with and without the passenger term touch
> 75% fewer passengers."

## 3 · Raise your own job (60 s) — Department coordination

> "Three departments raise work independently. What, where, how long, and which other departments
> may work alongside."

Raise a **PWI** job on **Dadar – Matunga**, both other departments ticked. Submit. Open the card.

> "It scored against the jobs near it, joined a group and was scheduled into a gap, with a written
> reason for every pair."

Press **Show on Operations map**.

> "The map flies to the job and says what, where, when — and whether it has started."

Raise an **S&T** job on the same section with **PWI unticked**: the system keeps them at different
times. A declaration is a constraint, not a label.

## 4 · How it decided (45 s) — Weekly block plan

> "Step one: how the gaps were found — the gap, minus safety and a lookout margin, minus set-up; kept
> only if 15 minutes of work remain, and each carries how reliable its start is. Step two: jobs merge
> nearest first and stop at 5 km; what hangs together shares a block. Step three: the schedule."

Toggle **Month**.

## 5 · Ask RailMitra (75 s)

Open the chat button and ask:

- *I need to plan a 2 hour PWI block on Kurla to Sion by Friday. How and where should I put it?*

> "It recommends a slot in coordinator's terms — a traffic block, how long it really needs with set-up
> and hand-back — says why the slot is quiet, how likely it is to clear before the next train, and what
> else in the week has to move. The chart shows the week with the new block and anything shifted. It
> re-solved the week on a copy in about a second and changed nothing."

- *what if Dadar to Matunga is closed at 14:00 for an hour?*
- *can OHE insulator work and tamping happen together at Kurla?*

## 5b · Is it right? (30 s) — Weekly block plan, bottom

> "A referee re-checks the plan from the timetable, not from the solver: 167 checks, none failed, and
> the tests show it failing on deliberately broken plans. Then each block is simulated against late
> trains and overrunning work; the solver avoids fragile windows, so blocks clear before the next
> train far more often than when the solver plans alone."

## 5c · Network efficiency and rerouting (75 s) — Operations tab

> "Blocks finish early sometimes, and then the rest of the protected time goes to small waiting jobs on
> the same section, urgent first. On this plan the gain is small, and the panel says why: the blocks are
> short. A 10-hour block that ends in 8 frees two hours, and RailMitra shows which waiting jobs fill it."
>
> "Jobs are grouped by place and urgency, so a P1 never waits behind a P5 in the same group, and small
> jobs ride inside a big job's block."
>
> Click **Watch** on a rerouting example: "The map flies to the closure with the whole detour in view.
> Long-distance and freight trains go round; locals never do."
>
> Open RailMitra and ask *what does a 3 hour tamping job need?*: "People by role, machines, materials,
> and it says plainly that these are planning norms, not a prediction."

## 6 · Why adopt (45 s) — Before / after

> "Same timetable, same jobs. Each comparison has one headline and how it was measured behind it. The
> 'before' case is a model of today's practice; its two invented numbers are sliders at the bottom."

Point at what the page does not claim: the department-clash and re-plan baselines are marked as
assumed, and the multiplier for re-planning is against a full exact solve, which was measured.

## 7 · Watch it think (30 s) — AI dispatcher

Press **Start simulation**: the same algorithms, in plain words, replayed from the real run.

---

## If you are asked

**"Is the data real?"** — Station coordinates, the mail/express timetable and the Mumbai border are
real (public datasets and OpenStreetMap). Suburban and freight layers, and every maintenance job,
are synthetic. `ASSUMPTIONS.md` lists everything invented.

**"Why only two tracks on Harbour and Trans-Harbour?"** — Those lines are two-track railways.
Central and Western are quadrupled on the core and two-track beyond it, which is what the map shows.

**"Does creating gaps hurt trains?"** — Yes, a little, and the app says how much: every option is
priced in train-minutes, holds are capped per train, and locals are never rerouted.

**"Does it scale beyond Mumbai?"** — `tests/test_scalability.py`: a fifth corridor added as one
config file, with assertions that no corridor or station name appears in the code.

**"Your validation has failures."** — Two checks fail and are reported, not tuned away. Moving a
threshold to fit the data it polices would make every other number unreliable.

**"The RL gap?"** — Measured on 20 held-out instances the model never saw, on the placement
objective only (the integrated-block reward is a weekly-plan feature the dispatcher is not trained
for). Greedy is in the table because a gap number means nothing without a floor.

**"Isn't squeezing work between trains risky?"** — It is, and the model prices it: a job given less
time than it needs finishes degraded more often. Micro-gap scheduling is a trade-off, not free capacity.
