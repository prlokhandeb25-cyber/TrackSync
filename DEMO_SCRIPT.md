# Demo script — four minutes

Rehearse it twice from a fresh terminal before presenting. The single biggest risk on stage is
a server that was already running and is serving stale code.

## Before you start

```powershell
# one terminal
.\.venv\Scripts\python.exe -m uvicorn backend.api.main:app --port 8000

# another
cd frontend; npm run dev
```

Open `http://127.0.0.1:5173`. Wait for the map to draw before you begin — the first request
builds the network and takes a few seconds. Land on **Operations**.

There are no map tiles anywhere in this app, so conference wifi cannot break it.

---

## 1 · The problem (25 s) — Operations tab

> "This is the Mumbai suburban network — four lines, 73 stations, eleven thousand services a
> week. Every one of them is in the way of maintenance."

Let the trains move for a beat. Point at the amber sections.

> "These four sections have defects outstanding. The network is drawn calm and the problems are
> drawn bright, so you know where to look without reading anything."

Hover an interchange (Thane or Kurla).

> "We didn't declare the interchanges. They fall out of the data — the same station code
> appearing on two lines."

## 2 · What we replace (45 s) — Department coordination tab

> "Three departments raise maintenance work: track, overhead wire, signalling. Today their
> three heads decide by phone who can work where without conflicting. That negotiation is what
> this replaces."

Point at the tiles: 6 needing an Integrated Work Permission, 3 incompatible, **24 hours of
manual negotiation**.

Hover a green cell that is adjacent rather than disjoint.

> "Read the reason. PWI on the Matunga–Dadar section while OWD works Matunga station — they
> meet at Matunga but don't physically overlap, so both proceed. That's rule R2, and it's the
> capacity a phone call usually gives away."

Hover an amber cell.

> "Same section, same time, different departments. That needs an Integrated Work Permission —
> which is a third status, not a flavour of compatible."

Ask the assistant on the right: **"why can't S&T work on NRL-BVS?"**

> "It answers from the live plan. There's no language model here — every number it gives you is
> read out of the same objects the solver uses, so it can't invent one. The line underneath
> shows what it read."

## 3 · The capacity nobody uses (40 s) — Corridor capacity tab

> "Everyone schedules at night and on Sunday megablocks. We also find the gaps *between*
> trains during the working day — twelve thousand of them across the week."

Point at the 56% bar.

> "And a gap isn't working time. Fifteen minutes to protect the block, ten to hand it back. A
> forty-minute gap gives you about fifteen minutes of work. Planning against raw gaps would
> overstate capacity everywhere."

Point at the night-window table.

> "These aren't hardcoded. Each one is read from the last and first train on that track, so
> they differ section by section. And the Sunday megablock is corroborated — traffic in that
> window measures 51% below a weekday."

## 4 · The plan (30 s) — Weekly block plan tab

> "CP-SAT solves the week to optimality — zero optimality gap, three seconds. Thirty-six of
> forty jobs placed, a quarter of them into gaps between trains."

Point at the four unplaced.

> "These four have no window long enough anywhere on their section. That's not a solver
> failure, it's a real finding: that work can't be done without *creating* a window by moving
> trains."

## 5 · The innovation (50 s) — AI dispatcher tab

> "Here's the part that's ours. CP-SAT is exact but takes seconds, which is useless when a
> defect appears mid-week. So we ran it a thousand times, replayed every solution as a sequence
> of dispatch decisions, and trained a policy on those. The solver teaches the dispatcher."

Point at the table.

> "Twenty held-out instances it never saw. CQL-DQN lands within 14.8% of optimal and re-plans
> twenty-nine times faster. Greedy and random are in the table because a gap number means
> nothing without a floor."

Point at the micro-gap column.

> "And this is the one I'd look at. The learned policies put fifty percent more work into gaps
> between trains than greedy does. Nobody wrote that rule — it transferred from the solver's
> own solutions."

Point at violations.

> "Zero constraint violations, and that's by construction, not by luck. Every action goes
> through a legality mask, so an illegal schedule literally can't be represented."

## 6 · The impact (30 s) — Before / after tab

> "Ten metrics, same instances both sides."

Point at the assumptions panel.

> "And the 'before' case is a model, not field data — we say so. Both its parameters are
> adjustable. Turn the negotiation time down and see whether we still win. We'd rather you
> tested it than believed it."

## 7 · Where it plugs in (20 s) — IR integration tab

> "This isn't a replacement for anything. The three departments map one-to-one onto three
> systems Indian Railways already runs — track to TMS, signalling to SMMS, overhead to TDMS.
> Our plan goes to BDMS as block demands, and COA closes the loop with live running. We're the
> planning brain between systems that already exist."

---

## If you are asked

**"Is the data real?"** — Station coordinates and the mail/express timetable are real, from the
public IR datasets. Suburban and freight layers are synthesised, because no public source
carries them. 429 of 1,640 daily services are real, and provenance is tracked per train.
`ASSUMPTIONS.md` lists everything invented.

**"Does it scale beyond Mumbai?"** — `tests/test_scalability.py`, ten passing tests on a fifth
corridor added as a config file. Two of them assert no corridor or station name appears
anywhere in the code.

**"Your validation has failures."** — Yes, and we report them rather than tune the thresholds.
Two checks fail, both understood and written up. Moving a threshold to fit the data it polices
would make every other number unreliable.

**"14.8% isn't that close to optimal."** — Agreed, and the spec aimed at 5–10%. Both models
overfit early — they peaked at step 1,000 of 6,000. More data or stronger regularisation would
likely narrow it. We'd rather tell you that than present it as a ceiling.

**"Isn't squeezing work between trains risky?"** — It is, and the model prices it. A job given
less time than it needs has a higher probability of finishing in a degraded state, which costs
train time every day until a follow-up clears it. Micro-gap scheduling is a trade-off here, not
free capacity.
