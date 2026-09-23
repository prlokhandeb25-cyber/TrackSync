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

> "The Mumbai region, drawn from its real border. Every section is drawn as its real tracks — four
> abreast on the Central and Western core, two on the outer stretches, slow lines outside and fast
> inside. Trains run on their own track."

Point at the yellow-and-black striped track with the crew moving along it.

> "That is maintenance happening right now. Jobs are arriving and being placed continuously."

Set the speed to **5×** or **10×**. Point at the cyan train.

> "A long-distance train due through a closed section is rerouted around it. Suburban locals never
> are — they serve fixed stations — so where a section has two tracks they run single-line instead,
> the green dashed track."

## 2 · The proof strip (20 s) — Operations, below the map

> "Everything under 'Proof it works' is measured, not asserted. Gap lookup with an interval tree
> against a full scan, with identical answers; the weekly plan solved to optimality; jobs
> clustered; jobs placed live; trains rerouted."

## 3 · Raise your own job (75 s) — Department coordination

> "Three departments raise work independently. Here's the form a department fills in: what, where,
> for how long, and which other departments may work alongside."

Raise a **PWI** job on **Dadar – Matunga**, both other departments ticked. Submit.

> "It scored 100 against the jobs near it, joined a group, and was scheduled into a gap — sharing a
> block with a nearby job where the rules allow. Open the card: every pair has a written reason."

Now raise an **S&T** job on the same section with **PWI unticked**.

> "PWI did not allow it, so the system keeps them at different times. The declaration is a
> constraint, not a label."

Click **See it on the Operations map →** (or **Watch it** on Operations) and speed to 20×.

> "The job we just raised, happening on the map."

## 4 · How it decided (60 s) — Weekly block plan

> "Three steps, each shown from a real run. One: how the gaps were found — every gap between two
> trains, minus safety and set-up time, kept only if 15 minutes of real work remain. Near misses
> that a small change would save are marked. Two: the dendrogram — jobs merge nearest first and
> stop at 5 km; what hangs together shares a block. Three: the schedule."

Toggle **Month**.

> "Four rolling weeks, each solved exactly, with the last week's leftovers carried in."

## 5 · Watch it think (60 s) — AI dispatcher

Press **Start simulation**.

> "Same algorithms, in plain words: taking a gap apart, opening a near miss, merging the closest
> jobs, checking the rules, giving each job a time. It is replayed from the real run, so it says
> exactly what the code did."

Scroll to the learned dispatcher.

> "And when an unplanned defect appears mid-week, the learned dispatcher re-plans in milliseconds
> where the exact solver takes seconds. Zero constraint violations, by construction."

## 6 · Why adopt it (45 s) — Before / after

> "Each algorithm, before and after, on the same instances — with how it was measured and how to
> reproduce it. The 'before' case is a model of today's practice, and its two invented numbers are
> sliders: drag the negotiation time down and watch whether we still win."

Point at the cost: gap creation delays trains, and that cost is stated in train-minutes.

## 7 · Ask RailMitra (15 s)

Open the chat button: **"how are jobs grouped?"** / **"what did gap creation open?"**

> "Answers come out of the same objects the planner uses. No language model."

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
