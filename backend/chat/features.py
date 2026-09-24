"""RailMitra knows every feature of the system, and can run each one on a copy to answer a question.

<!-- serves: J1, J5 -->

`FEATURES` is the catalogue: what each feature is in plain words, the technique behind it, where to find it in
the app, and a question that exercises it. Asking about a feature explains it; asking a "what if" about one
RUNS it - in a sandbox. Every runner here works on copies (`_copies`, a fresh `LiveSimState`, a private
random seed), so nothing an answer tries can change the plan, the map, the sudden-task log or the forecast.
`sandbox_fingerprint()` is what the tests compare before and after to prove it.

Numbers are read from the run that just happened, never written by hand.
"""

from __future__ import annotations

import random
import re

from backend.chat.engine import DAY_ABBR, DAY_S, Answer
from backend.chat import whatif as W
from backend.config import load_config
from backend.domain.models import WorkZoneKind, s_to_hhmm
from backend.domain.task import Department, WorkZone
from backend.planner.live_sim import LiveSimState

# --------------------------------------------------------------------------------- the catalogue

FEATURES: list[dict] = [
    {"id": "plan", "name": "Weekly block plan", "where": "Weekly block plan tab",
     "what": "places every maintenance job into a gap between trains for the whole week, so no two clashing jobs meet",
     "how": "CP-SAT (constraint optimisation) with a checker that re-verifies every rule on the result",
     "try": "how many blocks are planned this week?", "words": r"weekly|cp.?sat|optimis|optimal|solver|block plan"},
    {"id": "gaps", "name": "Gap finder and gap creation", "where": "Operations map, Weekly block plan",
     "what": "finds the quiet minutes between trains, and where none is long enough, prices small changes to trains that open one",
     "how": "timetable scan with set-up and hand-back time, plus three levers: hold a train, reroute long-distance trains, run single-line",
     "try": "how much gap time is really usable?", "words": r"gap|window|creat|single.?line|lever"},
    {"id": "rules", "name": "Department rules", "where": "Department coordination tab",
     "what": "says whether two kinds of work may share a place and time: yes, only with a joint permit, or never",
     "how": "rule engine with three verdicts (compatible, needs an Integrated Work Permission, incompatible)",
     "try": "can OHE insulator work and tamping happen together at Kurla?", "words": r"rule|compatib|permit|iwp|together"},
    {"id": "clusters", "name": "Job grouping", "where": "Operations tab, Job clusters",
     "what": "groups nearby jobs from different departments so they can share one protected block instead of several",
     "how": "average-linkage hierarchical clustering, and K-Medoids (a real job as each group's centre); both scored",
     "try": "compare the two ways of grouping jobs", "words": r"cluster|group|medoid|linkage|share a block"},
    {"id": "sudden", "name": "Sudden tasks", "where": "Operations tab, Sudden task panel",
     "what": "fits a job nobody planned, from low to critical, into the live schedule, moving lower-priority work only if it must",
     "how": "fit, then create a gap, then bump (an ALNS-style destroy and repair), then a late fallback",
     "try": "what if a critical S&T fault at Kurla right now?", "words": r"sudden|inject|emergency|unplanned|urgent|alns|destroy"},
    {"id": "predictive", "name": "Predictive blocks", "where": "Operations tab, Predicted blocks",
     "what": "turns early warnings into ordinary blocks in existing gaps days ahead, so faults are not handled as emergencies",
     "how": "a risk threshold, gaps that already exist only, one visit per section per day, a daily cap",
     "try": "what if we act on early warnings at 50% risk?", "words": r"predict|early warning|forecast|watch ?list|proactive|warning"},
    {"id": "twin", "name": "Digital twin", "where": "Operations tab, Rerouting; Sudden task panel",
     "what": "replays the next 12 hours of the real timetable with a closure in it and picks the response that delays fewest passengers",
     "how": "timetable replay with delay carried along each train's route, on many random days",
     "try": "what is the best response if Dadar to Matunga is closed at 9am?", "words": r"twin|ripple|cascade|best response|replay|simulat"},
    {"id": "reroute", "name": "Rerouting", "where": "Operations map, Rerouting panel",
     "what": "sends long-distance and freight trains around a closed section; locals are never rerouted, they run single-line",
     "how": "shortest path avoiding the closed section, checked against each train's delay limit, then vetted by the twin",
     "try": "how are trains rerouted around a block?", "words": r"rerout|divert|detour|alternate route|another line"},
    {"id": "pax", "name": "Passenger and frequency heuristics", "where": "everywhere a slot is chosen",
     "what": "prefers slots with fewer trains and fewer passengers within reach, so work lands when few people are affected",
     "how": "hour-by-hour train counts and an estimated load per train, priced into every scheduler",
     "try": "how busy is Thane at 9am?", "words": r"heuristic|passenger|frequency|footfall|crowd"},
    {"id": "robust", "name": "Robust start times", "where": "Weekly block plan",
     "what": "slides each block within its gap to the minute most likely to be handed back before the next train",
     "how": "400-sample simulation of late trains and overrunning work, every move re-checked by the referee",
     "try": "how often does a block clear before the next train?", "words": r"robust|overrun|clear before|on time|referee|verify"},
    {"id": "rl", "name": "AI dispatcher", "where": "AI dispatcher tab",
     "what": "a learned policy that re-plans in milliseconds when something unplanned appears",
     "how": "offline reinforcement learning from the solver's own plans; illegal moves are masked, never merely penalised",
     "try": "how good is the AI dispatcher?", "words": r"\brl\b|dispatcher|reinforcement|learned|cql|dqn"},
    {"id": "buffers", "name": "Crew-history buffers", "where": "not in the live plan (an option)",
     "what": "adds a time buffer for crews and weather that usually overrun",
     "how": "80th-percentile overrun by department and rain, learned from past jobs (synthetic history here)",
     "try": "how much buffer does an OHE job need in rain?", "words": r"buffer|crew history|weather|rain"},
]
_BY_ID = {f["id"]: f for f in FEATURES}


def sandbox_fingerprint() -> tuple:
    """What an answer must leave untouched: sizes and ids of every live booking, log and override."""
    st = W._live().STATE
    return (len(st.live_sim.placed), len(st.sudden_state.placed), len(st.forecast_state.placed), len(st.sudden_log),
            len(st.overrides), len(st.user_placements), len(st.forecast_rows),
            tuple(sorted((a.task_id, a.start_s) for a in (st.plan.assignments if st.plan else []))),
            tuple(sorted((t.id, t.scheduled_start_s) for t in (st.world.tasks if st.world else []))))


def _zn(net, zone: WorkZone) -> str:
    """A place as a person says it: 'Kurla station', or 'DR-MTN (Dadar–Matunga)'."""
    if zone.kind is WorkZoneKind.STATION_NODE:
        return f"{net.stations[zone.ref].name} station"
    sec = net.sections[zone.ref]
    return f"{zone.ref} ({net.stations[sec.from_station].name}–{net.stations[sec.to_station].name})"


# ------------------------------------------------------------------------- what is where (explain)


def h_catalogue(q: str, s: W.Slots, world, now_s: int) -> Answer:
    lines = [f"**{f['name']}** ({f['where']}): {f['what']}." for f in FEATURES]
    text = ("Here is everything the system does, and where to find it. Ask me to *explain* any of them, or ask a "
            "what-if and I will run it on a copy of the schedule without touching the real one.\n\n" + "\n".join(f"- {l}" for l in lines))
    return Answer(text, [{"k": "features", "v": str(len(FEATURES))}], ["feature catalogue"], "features",
                  suggestions=[f["try"] for f in FEATURES[3:9]])


def h_explain(f: dict) -> Answer:
    text = (f"**{f['name']}** — {f['what']}.\n\n**How:** {f['how']}.\n\n**Where:** {f['where']}.")
    return Answer(text, [{"k": "feature", "v": f["name"]}], ["feature catalogue"], "features",
                  suggestions=[f["try"], "what can you do?"])


def _match_feature(low: str) -> dict | None:
    best, best_hits = None, 0
    for f in FEATURES:
        hits = len(re.findall(f["words"], low))
        if hits > best_hits:
            best, best_hits = f, hits
    return best


# ----------------------------------------------------------------------------------- predictive


def h_predictive(q: str, s: W.Slots, world, now_s: int) -> Answer:
    from backend.planner import forecast as F

    st = W._live()
    net = world.net
    cfg = F._cfg()
    m = re.search(r"(\d{1,3})\s*%", q)
    thr = min(0.95, max(0.0, int(m.group(1)) / 100)) if m else cfg["threshold"]
    warns = F.watchlist(net)
    committed = W._copies(W.booked_tasks(world, include_forecast=False))
    index, pax, creator = st.ensure_interval_index(), st.get_pax(), st.make_creator()

    def run(pol):
        return F.run_policy(net, index, committed, creator, pax, warns, pol, with_rows=True)

    react = run(F.Policy("Wait for the failure", 2.0, False))
    act = run(F.Policy(f"Act at {int(thr * 100)}% risk", thr, False))
    force = run(F.Policy("Plan all, changing trains", 0.0, True))

    text = (f"I replayed a **simulated** early-warning feed on a copy of the schedule: **{act['warnings']} warnings** over the week, "
            f"of which **{act['failures']}** would really have failed (which ones is hidden from the planner, as it would be in life).")
    text += (f"\n\n**Acting at {int(thr * 100)}% risk and above** books **{act['blocks_added']} proactive blocks**, all in gaps that already "
             f"exist — **{act['gaps_made_proactive']} trains held, retimed or rerouted** for them. That gets ahead of "
             f"**{act['prevented']} of {act['failures']} failures**; **{act['emergencies']}** still arrive as emergencies.")
    text += (f"\n\n**Trains:** waiting for failures costs **{react['train_min']:,.0f} train-minutes** (each emergency needs a gap made "
             f"by changing trains); acting early costs **{act['train_min']:,.0f}**.")
    text += (f"\n\n**The guard against over-planning:** {act['false_alarm_blocks']} of the {act['blocks_added']} blocks "
             f"(**{act['wasted_hours']:.1f} h** of crew time) turned out unnecessary. No more than {cfg['max_per_day']} proactive blocks "
             f"a day and one visit per section per day are allowed, so the count cannot run away. ")
    if force["blocks_added"] > act["blocks_added"]:
        text += (f"Planning every warning, however weak, adds {force['blocks_added'] - act['blocks_added']} more blocks and "
                 f"{force['wasted_hours'] - act['wasted_hours']:.1f} more wasted hours for a further "
                 f"{max(0.0, act['train_min'] - force['train_min']):,.0f} train-minutes saved.")
    text += "\n\n*The warnings themselves are simulated: there is no camera or sensor feed here. Everything after a warning is the real scheduler.*"

    tasks = {t.id: t for t in world.tasks}
    blocks = [{"id": a.task_id, "dept": (tasks[a.task_id].department.value if a.task_id in tasks else ""), "start_s": a.start_s,
               "end_s": a.end_s, "kind": "stay", "label": tasks[a.task_id].label if a.task_id in tasks else a.task_id}
              for a in W._effective_plan(st)]
    for d in act["rows"]:
        if d["decision"] == "planned":
            blocks.append({"id": d["id"], "dept": d["department"], "start_s": d["start_s"], "end_s": d["end_s"],
                           "kind": "new", "label": d["label"]})
    sched = {"type": "schedule", "title": "Routine plan (faint) with the proactive blocks added", "days": [W._day_label(d) for d in range(7)],
             "blocks": blocks, "legend": {"new": "proactive block"}}
    bars = {"type": "bars", "title": "Train-minutes lost by policy",
            "items": [{"label": "Wait for failure", "value": round(react["train_min"])},
                      {"label": f"Act at {int(thr * 100)}%", "value": round(act["train_min"]), "best": True},
                      {"label": "Plan all + change trains", "value": round(force["train_min"])}]}
    a = Answer(text, [{"k": "blocks", "v": str(act["blocks_added"])}, {"k": "prevented", "v": f"{act['prevented']}/{act['failures']}"},
                      {"k": "trains held", "v": str(act["gaps_made_proactive"])}, {"k": "wasted", "v": f"{act['wasted_hours']:.1f} h"}],
               ["simulated warning feed", "gap finder", "ALNS-lite scheduler", "emergency levers", "nothing was changed"], "predictive",
               suggestions=["what if we act at 70% risk?", "what if we act at 30% risk?", "what can you do?"])
    a.visual, a.visuals = bars, [sched]
    return a


# -------------------------------------------------------------------------------------- the twin


def _busiest_paired(world, st) -> str:
    from backend.planner.rerouting import track_swap_opportunity
    counts: dict[str, int] = {}
    for o in world.occupancy:
        counts[o.section_id] = counts.get(o.section_id, 0) + 1
    paired = [sid for sid, sec in world.net.sections.items() if track_swap_opportunity(world.net, sec, 10.0) is not None]
    return max(paired or list(world.net.sections), key=lambda x: counts.get(x, 0))


def h_twin(q: str, s: W.Slots, world, now_s: int) -> Answer:
    st = W._live()
    if s.zone is None:
        sid = _busiest_paired(world, st)
        s.zone = WorkZone(kind=WorkZoneKind.SECTION, ref=sid)
        s.zones = [s.zone]
        pick = f" (I picked **{sid}**, the busiest section with a track pair)"
    else:
        pick = ""
    if s.duration_min is None:
        s.duration_min = 90
    if s.tod_s is None and s.day is None:
        s.tod_s = 9 * 3600
    a = W.h_whatif_close(q, s, world, now_s)
    a.text = ("The **digital twin** replays the next 12 hours of the real timetable with the closure in it, carries each train's "
              "delay along its route and onto the trains behind, and does it on many random days for each possible response"
              + pick + ".\n\n" + a.text)
    a.intent = "twin"
    return a


# ----------------------------------------------------------------------------------- rerouting


def _path_nodes(net, sections: list[str]) -> list[str]:
    secs = [net.sections[i] for i in sections if i in net.sections]
    if not secs:
        return []
    if len(secs) == 1:
        cur = secs[0].from_station
    else:
        cur = secs[0].to_station if secs[0].from_station in (secs[1].from_station, secs[1].to_station) else secs[0].from_station
    nodes = [cur]
    for sc in secs:
        cur = sc.to_station if sc.from_station == cur else sc.from_station
        nodes.append(cur)
    return nodes


def route_visual(net, closed: str, detour_sections: list[str], title: str) -> dict:
    sec = net.sections[closed]
    nodes = _path_nodes(net, detour_sections)
    ll = lambda c: [net.stations[c].lat, net.stations[c].lon]          # noqa: E731
    return {"type": "route", "title": title,
            "closed": {"from": ll(sec.from_station), "to": ll(sec.to_station), "id": closed,
                       "names": [net.stations[sec.from_station].name, net.stations[sec.to_station].name]},
            "detour": [ll(c) for c in nodes],
            "stops": [{"name": net.stations[c].name, "at": ll(c)} for c in (nodes[0], nodes[-1])] if nodes else []}


def h_reroute(q: str, s: W.Slots, world, now_s: int) -> Answer:
    from backend.api.routes import rerouting_proof
    from backend.planner.active_reroute import plan_block_reroutes

    st = W._live()
    net = world.net
    proof = rerouting_proof()
    if s.zone is not None:
        sec = (net.sections.get(s.zone.ref) if s.zone.kind is WorkZoneKind.SECTION else None)
        if sec is None:
            secs = [x for x in net.sections.values() if s.zone.ref in (x.from_station, x.to_station)]
            sec = max(secs, key=lambda x: len(st.occupancy_by_section().get(x.id, []))) if secs else None
        if sec is not None:
            start = (s.day * DAY_S + (s.tod_s or 9 * 3600)) if s.day is not None else ((now_s // DAY_S) * DAY_S + (s.tod_s or 9 * 3600))
            end = start + (s.duration_min or 120) * 60
            b = plan_block_reroutes(net, st.week_by_id(), st.occupancy_by_section().get(sec.id, []), sec, start, end)
            if b.reroutes:
                r = max(b.reroutes, key=lambda x: x["added_delay_min"])
                wait = max(0.0, (end - r["enter_s"]) / 60.0)
                text = (f"If **{sec.id}** ({net.stations[sec.from_station].name}–{net.stations[sec.to_station].name}) is closed "
                        f"{W._now_label(start)}–{s_to_hhmm(end % DAY_S)}, **{len(b.reroutes)} long-distance/freight train(s)** would be "
                        f"sent round it. The longest detour is **{r['train_name'] or r['train_id']}** via {len(r['sections'])} other "
                        f"sections, **+{r['added_delay_min']:.0f} min**; waiting for the block to lift would cost it about **{wait:.0f} min**. "
                        f"**{b.locals_in_window} suburban locals** are due through too: they are never rerouted (they serve fixed stations)"
                        + (f", so they run single-line on **{b.track_swap['swap_to_track']}**." if b.track_swap else " and would hold."))
                a = Answer(text, [{"k": "diverted", "v": str(len(b.reroutes))}, {"k": "detour", "v": f"+{r['added_delay_min']:.0f} min"},
                                  {"k": "vs waiting", "v": f"{wait:.0f} min"}, {"k": "locals rerouted", "v": "0"}],
                           ["reroute search (locals excluded)", "timetable occupancy", "nothing was changed"], "reroute",
                           suggestions=[f"what is the best response if {sec.id} is closed at 9am?", "what can you do?"])
                a.visual = route_visual(net, sec.id, r["sections"], f"{r['train_name'] or r['train_id']} goes round {sec.id}")
                a.action = {"label": "Show on map", "section": sec.id, "start_s": start}
                return a
            text = (f"No long-distance or freight train is due through **{sec.id}** in that window, so there is nothing to reroute. "
                    f"{b.locals_in_window} suburban locals are; they are never rerouted"
                    + (f" and would run single-line on {b.track_swap['swap_to_track']}." if b.track_swap else " and would hold."))
            return Answer(text, [{"k": "diverted", "v": "0"}, {"k": "locals", "v": str(b.locals_in_window)}],
                          ["reroute search", "nothing was changed"], "reroute", suggestions=["how are trains rerouted around a block?"])

    ex = proof["examples"][0] if proof["examples"] else None
    text = (f"Across the **{proof['blocks']} blocks** in this week's plan, **{proof['diverted']} long-distance and freight trains** "
            f"are sent round a closed section (**{proof['within_limit']}** inside their delay limit). Each detour adds **{proof['mean_added_min']:.0f} min** on average; "
            f"waiting for the block to lift would cost them **{proof['wait_min'] / max(1, proof['diverted']):.0f} min** each — "
            f"**{proof['saved_min']:,.0f} train-minutes saved** in all. **{proof['locals_in_blocks']} local movements** meet a block and **"
            f"{proof['locals_rerouted']}** of them are rerouted: locals serve fixed stations, so they only run single-line on their own track pair. "
            f"Before a detour is taken the digital twin checks it is not worse than waiting.")
    a = Answer(text, [{"k": "diverted", "v": str(proof["diverted"])}, {"k": "saved", "v": f"{proof['saved_min']:,.0f} min"},
                      {"k": "locals rerouted", "v": str(proof["locals_rerouted"])}],
               ["weekly plan blocks", "reroute search", "nothing was changed"], "reroute",
               suggestions=["what happens to trains if Kurla to Thane is closed at 10am?", "what can you do?"])
    if ex:
        a.visual = route_visual(net, ex["section_id"], ex["sections"], f"{ex['train']} goes round {ex['section_id']}")
        a.action = {"label": "Show on map", "section": ex["section_id"], "start_s": ex["block_start_s"]}
    return a


# --------------------------------------------------------------------------- a sudden task, tried


def h_sudden_run(q: str, s: W.Slots, world, now_s: int) -> Answer:
    from backend.planner.sudden import LEVEL_NAME, due_hours, place_sudden
    from backend.domain.task import Task, TaskCategory

    st = W._live()
    net = world.net
    if s.zone is None:
        return W._need((s.note + " " if s.note else "") + "Where is the fault? For example **what if a critical S&T fault at Kurla right now?**",
                       "what if a critical S&T fault at Kurla right now?")
    prio = s.priority or 2
    tt = W._default_type(s.depts[0] if s.depts else None, s.types, s.zone)
    task = W._probe(world, s, "SUD-TRY", tt, now_s, priority=prio)
    task.source = "SUDDEN"
    task.due_by_s = now_s + due_hours(prio) * 3600
    booked = W._copies(W.booked_tasks(world))
    idx, pax = st.ensure_interval_index(), st.get_pax()
    before = {t.id: (t.scheduled_start_s, t.scheduled_end_s) for t in booked}
    res = place_sudden(net, task, idx, booked, LiveSimState(), st.make_creator(), now_s, pax,
                       lambda b: not (b.scheduled_start_s is not None and b.scheduled_start_s <= now_s < (b.scheduled_end_s or 0)))
    lvl = LEVEL_NAME.get(prio, "Medium").lower()
    pl = res.placement
    facts = [{"k": "level", "v": lvl}, {"k": "method", "v": res.method}, {"k": "answered in", "v": f"{res.response_ms:.0f} ms"}]
    if pl is None or not pl.placed:
        text = (f"A **{lvl}** {tt.label.lower()} fault at **{_zn(net, s.zone)}** could **not** be placed before its deadline "
                f"({due_hours(prio)} h), even after opening a gap or moving lower-priority work. " + " ".join(res.steps[-2:]))
        return Answer(text, facts, ["ALNS-lite scheduler", "nothing was changed"], "sudden")
    how = {"gap": "in a gap that already exists", "created": "in a gap made by a small change to the trains",
           "bumped": "by moving lower-priority planned work aside", "late": "**late** — the earliest slot there is, after its deadline"}[res.method]
    text = (f"A **{lvl}** {tt.label.lower()} at **{_zn(net, s.zone)}** would go **{W._date_label(pl.start_s)}–"
            f"{s_to_hhmm(pl.end_s % DAY_S)}** {how}, worked out in **{res.response_ms:.0f} ms** on a copy of the schedule.")
    if res.method == "late":
        text += " " + " ".join(x for x in res.steps if x.startswith(("No slot", "Nothing fits")))[:240]
    if pl.created is not None:
        text += f" That costs **{pl.created.delay_min:.0f} train-minutes** ({pl.created.note})."
    if res.moves:
        lines = [f"**{m.task.id}** {m.task.label.lower()} to " + (f"**{W._date_label(m.new.start_s)}**" if m.new else "**deferred**")
                 for m in res.moves]
        text += f"\n\n**What moves:** " + "; ".join(lines) + f". {len(booked) - len(res.moves)} other jobs stay exactly as they are."
    else:
        text += "\n\n**What moves:** nothing; no planned job is disturbed."
    tasks = {t.id: t for t in world.tasks}
    moved = {m.task.id for m in res.moves}
    blocks = [{"id": t.id, "dept": t.department.value, "start_s": before[t.id][0], "end_s": before[t.id][1], "kind": "stay",
               "label": t.label} for t in booked if before.get(t.id, (None,))[0] is not None and t.id not in moved]
    for m in res.moves:
        if m.new:
            blocks.append({"id": m.task.id, "dept": m.task.department.value, "start_s": m.new.start_s, "end_s": m.new.end_s, "kind": "moved",
                           "label": m.task.label, "from": {"start_s": m.old["start_s"], "end_s": m.old["end_s"]}})
        else:
            blocks.append({"id": m.task.id, "dept": m.task.department.value, "start_s": m.old["start_s"], "end_s": m.old["end_s"],
                           "kind": "dropped", "label": m.task.label})
    blocks.append({"id": "NEW", "dept": tt.department.value, "start_s": pl.start_s, "end_s": pl.end_s, "kind": "new", "label": "the fault"})
    a = Answer(text, facts, ["ALNS-lite scheduler", "gap creation", "passenger model", "nothing was changed"], "sudden",
               suggestions=["what if it is low priority?", "how many sudden tasks were handled?"])
    a.visual = {"type": "schedule", "title": f"The week with a {lvl} fault dropped in", "days": [W._day_label(d) for d in range(7)],
                "blocks": blocks, "legend": {"new": "the fault"}}
    a.action = {"label": "Show on map", "section": pl.window.section_id if pl.window else None, "start_s": pl.start_s}
    return a


# ---------------------------------------------------------------------------------- clustering


def h_clusters_run(q: str, s: W.Slots, world, now_s: int) -> Answer:
    import numpy as np
    from backend.api.routes import _cluster_pool
    from backend.planner.clustering import _position, _to_km, cluster_tasks, compare_methods

    pool = W._copies(_cluster_pool())
    net = world.net
    cmp_ = compare_methods(net, pool)
    if len(cmp_.get("methods", [])) < 2:
        return Answer("There are too few jobs to group.", [], ["job pool"], "clusters")
    h, k = cmp_["methods"]
    cl_h = cluster_tasks(net, pool, method="average")
    cl_k = cluster_tasks(net, pool, method="kmedoids")
    pts = {t.id: _to_km(*_position(net, t)) for t in pool}
    x0 = min(p[0] for p in pts.values()); y0 = min(p[1] for p in pts.values())

    def vis(cls, title):
        rows = []
        for c in cls:
            for tid in c.task_ids:
                x, y = pts[tid]
                rows.append({"x": round(x - x0, 2), "y": round(y - y0, 2), "g": c.id, "medoid": tid == c.medoid_id})
        return {"type": "scatter", "title": title, "points": rows}

    better = k if k["silhouette"] > h["silhouette"] else h
    text = (f"I grouped the **{len(pool)} open jobs** two ways on a copy, then scored both the same way (silhouette: 1 is tight and "
            f"well separated, 0 is borderline).\n\n"
            f"- **Average-linkage** (merge the closest jobs until they are more than {cmp_['cut_km']:.0f} km apart): "
            f"**{h['groups']} groups**, silhouette **{h['silhouette']}**, jobs sit on average {h['mean_km_to_centre']} km from their group's centre, widest group {h['widest_group_km']} km.\n"
            f"- **K-Medoids** (pick k real jobs as centres; k chosen by silhouette): **{k['groups']} groups**, silhouette **{k['silhouette']}**, "
            f"{k['mean_km_to_centre']} km from the centre, widest {k['widest_group_km']} km.\n\n"
            f"On these jobs **{better['method'].split(' (')[0].lower()}** scores better. A K-Medoids centre is an actual job, so it also names "
            f"a real place where a shared block could go; average-linkage needs no group count in advance and caps how far apart grouped jobs can be. "
            f"Whether grouped jobs may share a block is still decided by the rule engine, never by distance.")
    a = Answer(text, [{"k": "average-linkage", "v": f"{h['groups']} groups, s={h['silhouette']}"},
                      {"k": "K-Medoids", "v": f"{k['groups']} groups, s={k['silhouette']}"}],
               ["job pool", "clustering (both methods)", "nothing was changed"], "clusters",
               suggestions=["how are jobs grouped?", "what can you do?"])
    a.visual = vis(cl_h, f"Average-linkage: {h['groups']} groups")
    a.visuals = [vis(cl_k, f"K-Medoids: {k['groups']} groups (ringed = centre job)")]
    return a


# ---------------------------------------------------------------------------------- algorithms


def h_algorithms(q: str, s: W.Slots, world, now_s: int) -> Answer:
    from backend.planner.clustering import compare_methods
    from backend.api.routes import _cluster_pool

    st = W._live()
    plan = st.ensure_plan()
    ver = None
    try:
        from backend.planner.verify import verify_plan
        ver = verify_plan(world.net, world.tasks, plan.assignments, world.windows, st.occupancy_by_section()).ok
    except Exception:
        ver = None
    cm = compare_methods(world.net, W._copies(_cluster_pool()))
    sil = {m["method"].split(" (")[0]: m["silhouette"] for m in cm.get("methods", [])}
    text = ("These are the techniques in the system, and what I can vouch for from this run:\n\n"
            f"- **CP-SAT** plans the week. It ended **{plan.status.lower()}** in **{plan.wall_s:.0f} s** on {plan.n_tasks} jobs"
            + (" — the solver proves no better plan exists, and an independent checker confirms every rule holds." if plan.status == "OPTIMAL" and ver else
               f" — a good plan within its time limit" + ("; the independent checker confirms every rule holds." if ver else "."))
            + "\n- **ALNS-lite** places jobs that arrive one at a time: repair into the best gap, then if needed open a gap, then one bounded destroy step. "
              "It is the destroy-and-repair idea of ALNS with a single destroy move and no learned operator weights, and it is not run to convergence.\n"
            + (f"- **Job grouping** uses average-linkage and **K-Medoids**; silhouettes on today's jobs: " + ", ".join(f"{k} {v}" for k, v in sil.items()) + ".\n"
               if sil else "")
            + "- **Digital twin** replays 12 hours of the timetable to pick the response to a closure.\n"
              "- **Predictive blocks** act on early warnings in existing gaps only, under a daily cap.\n"
              "- **The AI dispatcher** is offline RL trained on CP-SAT's plans; illegal actions are masked, so constraint violations are zero by construction.\n\n"
              "Not claimed: that ALNS-lite is optimal (it is a fast heuristic for live arrivals), or that the warning feed is real (it is simulated).")
    return Answer(text, [{"k": "weekly plan", "v": plan.status.lower()}, {"k": "checker", "v": "passes" if ver else "n/a"}],
                  ["weekly plan status", "verify_plan", "clustering (both methods)", "nothing was changed"], "algorithms",
                  suggestions=["compare the two ways of grouping jobs", "what if we act on early warnings at 50% risk?"])


# ----------------------------------------------------------------------------------- buffers


def h_buffers(q: str, s: W.Slots, world, now_s: int) -> Answer:
    from backend.planner.crew_profile import CrewModel, synthetic_history

    m = CrewModel(synthetic_history())
    dur = s.duration_min or 120
    depts = [d.value for d in (s.depts or [Department.OWD])][:1]
    items, rows = [], []
    for dep in ("PWI", "OWD", "S_AND_T"):
        dry, wet = m.buffer_min(dep, False, dur), m.buffer_min(dep, True, dur)
        rows.append((dep, dry, wet))
        items.append({"label": f"{dep.replace('S_AND_T', 'S&T')} dry", "value": dry})
        items.append({"label": f"{dep.replace('S_AND_T', 'S&T')} rain", "value": wet, "best": False})
    dep = depts[0]
    dry, wet = m.buffer_min(dep, False, dur), m.buffer_min(dep, True, dur)
    text = (f"For a **{dur}-minute {dep.replace('S_AND_T', 'S&T')} job**, crews like that usually overrun enough that the plan should reserve "
            f"**{dry} min** of buffer in dry weather and **{wet} min** in rain (the 80th-percentile overrun, so about 4 jobs in 5 finish inside it).\n\n"
            "This is an option, not in the live plan: reserving buffers made blocks clear before the next train more often but placed fewer jobs. "
            "*The crew history here is synthetic, so this shows the mechanism, not how real crews behave.*")
    a = Answer(text, [{"k": "dry", "v": f"{dry} min"}, {"k": "rain", "v": f"{wet} min"}], ["crew-history model (synthetic)", "nothing was changed"],
               "buffers", suggestions=["how good is the AI dispatcher?", "what can you do?"])
    a.visual = {"type": "bars", "title": f"Buffer to reserve for a {dur}-minute job (minutes)", "items": items}
    return a


# ------------------------------------------------------------------------------------- routing

_CAT = re.compile(r"\b(what can you do|what do you do|features?|capabilit\w+|everything (you|the system)|what (all )?can (i|we) (ask|do)|"
                  r"list (of )?(the )?(features|tools|functions)|tour|overview)\b")
_EXPLAIN = re.compile(r"\b(explain|what is|what are|what's|how does|how do|how is|tell me about|describe)\b")


def route(q: str, world, now_s: int) -> Answer | None:
    low = q.lower()
    s = W.parse(q, world, now_s)
    if _CAT.search(low):
        return h_catalogue(q, s, world, now_s)
    if re.search(r"\bk.?medoids?\b|\bcompare\b.*\bgroup|\bcluster\w*\b.*\b(compare|versus|vs|two ways)|\b(compare|versus|vs)\b.*\bcluster", low):
        return h_clusters_run(q, s, world, now_s)
    if re.search(r"\b(alns|algorithms?|techniques?|really optimi[sz]|is it optimal|are you (sure|confident))\b", low):
        return h_algorithms(q, s, world, now_s)
    if re.search(r"\b(buffer|crew history|overrun)\w*\b", low) and not re.search(r"\bhow often\b", low):
        return h_buffers(q, s, world, now_s)
    if re.search(r"\b(predict\w*|early warning\w*|forecast\w*|watch ?list|proactive|warnings?)\b", low):
        return h_predictive(q, s, world, now_s)
    if re.search(r"\b(digital twin|the twin|ripple|cascad\w*|best response|replay)\b", low):
        return h_twin(q, s, world, now_s)
    if re.search(r"\b(rerout\w*|divert\w*|detour\w*|alternate route|another line|sent round)\b", low) \
            and not re.search(r"\b(clos(e|ed)|blocked)\b.*\b(if|what)\b|\b(if|what)\b.*\b(clos(e|ed)|blocked)\b", low):
        return h_reroute(q, s, world, now_s)
    if re.search(r"\b(sudden|inject\w*|unplanned|emergency|fault|defect)\b", low) and s.zone is not None \
            and re.search(r"\b(what if|what happens|suppose|if|would|how would|try|test|simulate)\b", low):
        return h_sudden_run(q, s, world, now_s)
    if _EXPLAIN.search(low) and not s.zones:
        f = _match_feature(low)
        if f is not None:
            return h_explain(f)
    return None
