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
     "what": "puts every maintenance job into a quiet gap between trains for the whole week, so no two clashing jobs meet",
     "how": "CP-SAT, an exact optimiser, plus a separate checker that re-verifies every rule on the finished plan",
     "try": "how many blocks are planned this week?", "words": r"weekly|cp.?sat|optimis|optimal|solver|block plan"},
    {"id": "gaps", "name": "Gap finder and gap creation", "where": "Operations map, Weekly block plan",
     "what": "finds the quiet minutes between trains and, where none is long enough, prices small changes to trains that would open one",
     "how": "a timetable scan with set-up and hand-back time, plus three levers: hold a train, reroute a long-distance train, run single-line",
     "try": "how much gap time is really usable?", "words": r"gap|window|creat|single.?line|lever"},
    {"id": "rules", "name": "Department rules", "where": "Department coordination tab",
     "what": "says whether two kinds of work may share a place and time: yes, only with a joint permit, or never",
     "how": "a rule engine with three verdicts, each with its reason",
     "try": "can OHE insulator work and tamping happen together at Kurla?", "words": r"rule|compatib|permit|iwp|together"},
    {"id": "clusters", "name": "Job grouping", "where": "Operations tab, Job clusters",
     "what": "groups jobs that are close together AND similarly urgent, so small jobs can ride inside a big job's block",
     "how": "average-linkage clustering on place plus priority, with K-Medoids as an alternative; both scored",
     "try": "how do you group small jobs with big ones?", "words": r"cluster|group|medoid|linkage|share a block|ride|piggy"},
    {"id": "sudden", "name": "Sudden tasks", "where": "Operations tab, Sudden task panel",
     "what": "fits a job nobody planned, from low to critical, into the live schedule, moving lower-priority work only if it must",
     "how": "fit it, else create a gap, else bump lower-priority work (an ALNS-style destroy and repair), else book it late",
     "try": "what if a critical S&T fault at Kurla right now?", "words": r"sudden|inject|emergency|unplanned|urgent|alns|destroy"},
    {"id": "reclaim", "name": "Early-finish reuse", "where": "Operations tab, Network efficiency",
     "what": "when a block finishes early, the rest of it goes to small waiting jobs on the same section",
     "how": "each block is given its crew's real timing; freed time is matched to the waiting list, priority first then longest first",
     "try": "what if a 10 hour block is finished in 8 hours?", "words": r"early|finish\w* early|freed|leftover|left over|reclaim|spare time"},
    {"id": "twin", "name": "Digital twin", "where": "Operations tab, Rerouting; Sudden task panel",
     "what": "replays the next 12 hours of the real timetable with a closure in it and picks the response that delays fewest passengers",
     "how": "a timetable replay with each train's delay carried along its route, over many random days",
     "try": "what is the best response if Dadar to Matunga is closed at 9am?", "words": r"twin|ripple|cascade|best response|replay|simulat"},
    {"id": "reroute", "name": "Rerouting", "where": "Operations map, Rerouting panel",
     "what": "sends long-distance and freight trains around a closed section; locals are never rerouted, they run single-line",
     "how": "shortest path avoiding the closed section, checked against each train's delay limit, then vetted by the twin",
     "try": "how are trains rerouted around a block?", "words": r"rerout|divert|detour|alternate route|another line"},
    {"id": "resources", "name": "Crew and equipment", "where": "RailMitra",
     "what": "the people, machines and materials a job of a given kind and length usually needs",
     "how": "planning norms per kind of work, scaled by how long it runs (not a measured prediction)",
     "try": "what does a 3 hour tamping job need?", "words": r"resource|manpower|equipment|crew|people|machine|materials|gang|staff"},
    {"id": "pax", "name": "Passenger and frequency heuristics", "where": "everywhere a slot is chosen",
     "what": "prefers slots with fewer trains and fewer passengers within reach, so work lands when few people are affected",
     "how": "hour-by-hour train counts and an estimated load per train, priced into every scheduler",
     "try": "how busy is Thane at 9am?", "words": r"heuristic|passenger|frequency|footfall|crowd"},
    {"id": "robust", "name": "Robust start times", "where": "Weekly block plan",
     "what": "slides each block within its gap to the minute most likely to be handed back before the next train",
     "how": "a 400-sample simulation of late trains and overrunning work, every move re-checked by the checker",
     "try": "how often does a block clear before the next train?", "words": r"robust|overrun|clear before|on time|referee|verify"},
    {"id": "rl", "name": "AI dispatcher", "where": "AI dispatcher tab",
     "what": "a learned policy that re-plans in milliseconds when something unplanned appears",
     "how": "offline reinforcement learning from the solver's own plans; illegal moves are masked, never merely penalised",
     "try": "how good is the AI dispatcher?", "words": r"\brl\b|dispatcher|reinforcement|learned|cql|dqn"},
]
_BY_ID = {f["id"]: f for f in FEATURES}


def sandbox_fingerprint() -> tuple:
    """What an answer must leave untouched: sizes and ids of every live booking, log and override."""
    st = W._live().STATE
    return (len(st.live_sim.placed), len(st.sudden_state.placed), len(st.forecast_state.placed), len(st.daily_state.placed), len(st.sudden_log),
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


# ------------------------------------------------------------------------------------- the twin


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
    a.text = ("Let me use the digital twin for this. It replays the next 12 hours of the real timetable with the closure in it, lets each "
              "train's delay spread to the trains behind it, and does that on many random days for each possible response"
              + pick + ".\n\n" + a.text + "\n\nWant me to show where the diverted trains would go? Ask *how are trains rerouted around a block?*")
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
                text = (f"If {sec.id} ({net.stations[sec.from_station].name} to {net.stations[sec.to_station].name}) is closed "
                        f"{W._now_label(start)} to {s_to_hhmm(end % DAY_S)}, {len(b.reroutes)} long-distance or freight train"
                        f"{'s' if len(b.reroutes) != 1 else ''} would be sent round it. The longest detour is {r['train_name'] or r['train_id']}, "
                        f"going through {len(r['sections'])} other sections and losing about {r['added_delay_min']:.0f} minutes. If it just waited for the block to lift, it would lose about {wait:.0f}.\n\n"
                        f"{b.locals_in_window} suburban locals are due through as well. Those never get rerouted, because they serve fixed stations"
                        + (f", so they'd run one at a time on {b.track_swap['swap_to_track']} instead." if b.track_swap else " and would simply hold."))
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
    text = (f"Here's how it works. Over this week's {proof['blocks']} blocks, {proof['diverted']} long-distance and freight trains have to go round a closed section. "
            f"Each detour costs about {proof['mean_added_min']:.0f} minutes, whereas waiting for the block to lift would cost about "
            f"{proof['wait_min'] / max(1, proof['diverted']):.0f} each. That's roughly {proof['saved_min']:,.0f} train-minutes saved.\n\n"
            f"Another {proof['no_path']} trains have no other route, so they wait either way. And none of the {proof['locals_in_blocks']} local train movements "
            f"that meet a block is ever rerouted, since locals serve fixed stations; they run one at a time on the other track of their pair. "
            f"Before any detour is taken, the digital twin checks it isn't worse than waiting.")
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
        text = (f"That one is tough: a {lvl} {tt.label.lower()} fault at {_zn(net, s.zone)} can't be placed before its deadline "
                f"({due_hours(prio)} hours), even after opening a gap or moving lower-priority work. " + " ".join(res.steps[-2:]))
        return Answer(text, facts, ["ALNS-lite scheduler", "nothing was changed"], "sudden")
    how = {"gap": "in a gap that already exists", "created": "in a gap made by a small change to the trains",
           "bumped": "by moving lower-priority planned work aside", "late": "late: it's the earliest slot there is, but it's after the deadline"}[res.method]
    text = (f"I'd put a {lvl} {tt.label.lower()} at {_zn(net, s.zone)} on {W._date_label(pl.start_s)} to "
            f"{s_to_hhmm(pl.end_s % DAY_S)}, {how}. That took {res.response_ms:.0f} milliseconds on a copy of the schedule.")
    if res.method == "late":
        text += " " + " ".join(x for x in res.steps if x.startswith(("No slot", "Nothing fits")))[:240]
    if pl.created is not None:
        text += f" It costs about {pl.created.delay_min:.0f} train-minutes ({pl.created.note})."
    if res.moves:
        lines = [f"**{m.task.id}** {m.task.label.lower()} to " + (f"**{W._date_label(m.new.start_s)}**" if m.new else "**deferred**")
                 for m in res.moves]
        text += f"\n\nTo make room, " + "; ".join(lines) + f". The other {len(booked) - len(res.moves)} jobs stay exactly where they are."
    else:
        text += "\n\nNothing else has to move."
    text += "\n\nWant to see what crew it needs? Ask *what does a job like that need?*"
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
    from backend.api.routes import _cluster_pool
    from backend.planner.clustering import _feat, _position, _to_km, cluster_tasks, compare_methods, priority_effect

    pool = W._copies(_cluster_pool())
    net = world.net
    cmp_ = compare_methods(net, pool)
    if len(cmp_.get("methods", [])) < 2:
        return Answer("There are too few open jobs to group right now.", [], ["job pool"], "clusters")
    pe = priority_effect(net, pool)
    h, k = cmp_["methods"]
    cl_h = cluster_tasks(net, pool, method="average")
    cl_k = cluster_tasks(net, pool, method="kmedoids")
    pts = {t.id: _to_km(*_position(net, t)) for t in pool}
    x0 = min(p[0] for p in pts.values()); y0 = min(p[1] for p in pts.values())
    po, pu = pe["place_only"], pe["place_and_urgency"]
    big = max((c for c in cl_h if c.riders), key=lambda c: len(c.riders), default=None)
    pl = lambda n, w: f"{n} {w}" + ("" if n == 1 else "s")            # noqa: E731

    def vis(cls, title):
        rows = []
        for c in cls:
            for tid in c.task_ids:
                x, y = pts[tid]
                rows.append({"x": round(x - x0, 2), "y": round(y - y0, 2), "g": c.id, "medoid": tid == c.medoid_id or tid == c.anchor_id})
        return {"type": "scatter", "title": title, "points": rows}

    text = (f"I group jobs by two things at once: how close they are and how urgent they are. A P1 shouldn't sit waiting because a P5 is next to it.\n\n"
            f"On today's {len(pool)} open jobs that makes {pu['groups']} groups. Grouping by place alone would put a very urgent job and a very routine one "
            f"together in {po['mixed_urgency_groups']} groups; with urgency counted, that's {pu['mixed_urgency_groups']}.\n\n"
            f"Small jobs (up to {pe['small_job_min']} minutes) can ride inside a bigger job's block when the rules allow it and their priority is close: "
            f"{pu['riders']} jobs qualify today, which saves about {pu['setup_saved_min']} minutes of set-up and hand-back because they don't need a block of their own.")
    if big:
        text += f"\n\nThe best example is around {big.label}: {pl(len(big.riders), 'small job')} can ride with the big {next((t.label for t in pool if t.id == big.anchor_id), 'one').lower()}."
    text += (f"\n\nI also tried a second method, K-Medoids, which picks a real job as each group's centre. Scored the same way (1 is tight and clearly separated) it gets {k['silhouette']} "
             f"against {h['silhouette']} for the standard method, "
             + ("so on today's jobs it's slightly tighter; you can switch to it on the Job clusters panel." if k['silhouette'] > h['silhouette']
                else "so the standard method stays as the default."))
    a = Answer(text, [{"k": "groups", "v": str(pu["groups"])}, {"k": "small jobs riding", "v": str(pu["riders"])},
                      {"k": "set-up saved", "v": f"{pu['setup_saved_min']} min"}],
               ["job pool", "clustering (place + urgency)", "rule engine", "nothing was changed"], "clusters",
               suggestions=["what does a 3 hour tamping job need?", "what can you do?"])
    a.visual = vis(cl_h, f"Grouped by place and urgency: {h['groups']} groups")
    a.visuals = [vis(cl_k, f"K-Medoids: {k['groups']} groups")]
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



# ---------------------------------------------------------------------------------- predictions


def h_prediction_note(q: str, s: W.Slots, world, now_s: int) -> Answer:
    text = ("Good thing to ask about. I used to have an early-warning feature that booked repair blocks before things broke, "
            "but I took it out. The warnings were made up by the program (there is no camera or sensor feed here), and the "
            "'accuracy' was just the odds I had set myself, so it proved nothing. I'd rather not show you a number I can't stand behind.\n\n"
            "If you connect real inspection data later, the booking part could come back, because it already puts work only into "
            "gaps that exist. Meanwhile, I can help with things I can actually measure. Shall we look at what happens when a block finishes early?")
    return Answer(text, [], ["decision log"], "prediction", suggestions=["what if a 10 hour block is finished in 8 hours?",
                                                                       "what can you do?"])


def _resource_visual(est: dict) -> dict:
    items = [{"label": r["role"], "value": r["n"], "best": False} for r in est["roles"]]
    return {"type": "bars", "title": f"People on site per shift ({est['people_per_shift']} in all)", "items": items}


def h_resources(q: str, s: W.Slots, world, now_s: int) -> Answer:
    from backend.planner.resources import estimate

    tt = W._default_type(s.depts[0] if s.depts else None, s.types, s.zone)
    dur = s.duration_min or max(tt.min_duration_min, min(90, tt.max_duration_min))
    e = estimate(tt, dur)
    crew = ", ".join(f"{r['n']} {r['role'].lower()}" for r in e["roles"])
    text = (f"For a {dur}-minute {tt.label.lower()} job you'd normally line up about {e['people_per_shift']} people: {crew}.")
    if e["shifts"] > 1:
        text += f" It runs past one shift, so plan {e['shifts']} relief crews, about {e['people_total']} people over the job."
    text += f"\n\nBring: {', '.join(e['equipment']).lower()}."
    if e["materials"]:
        text += f" Have {', '.join(e['materials']).lower()} ready."
    text += ("\n\nOne honest note: these are typical planning norms for this kind of work, scaled by how long it runs. "
             "I don't have real gang records, so treat it as a starting checklist rather than a forecast.")
    if e["power_block"]:
        text += " Because it needs a power block, a traction power controller and an earthing party are included."
    if s.zone is not None:
        text += f"\n\nWant me to find the best slot for it at {_zn(world.net, s.zone)}?"
    a = Answer(text, [{"k": "people", "v": str(e["people_per_shift"])}, {"k": "shifts", "v": str(e["shifts"])},
                      {"k": "machines", "v": str(len(e["equipment"]))}], ["planning norms (assumed)", "nothing was changed"], "resources",
               suggestions=[f"best time for a {dur} minute {tt.department.value} job?", "what can you do?"])
    a.visual = _resource_visual(e)
    return a


def _durations(low: str) -> list[int]:
    out = []
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(hours?|hrs?|h|minutes?|mins?)\b", low):
        v = float(m.group(1))
        out.append(int(v * 60) if m.group(2).startswith("h") else int(v))
    return out


def h_reclaim(q: str, s: W.Slots, world, now_s: int) -> Answer:
    from backend.api.routes_efficiency import reclaim_summary
    from backend.planner import reclaim as R

    d = reclaim_summary()
    ds = _durations(q.lower())
    if len(ds) >= 2 and ds[0] > ds[1]:
        planned, actual = ds[0], ds[1]
        freed = planned - actual
        zone = s.zone.ref if (s.zone is not None and s.zone.kind is WorkZoneKind.SECTION) else None
        take = []
        if zone:
            bk = R.make_backlog(world.net, 4242, d["backlog"], d["max_job_min"])
            take = R.fill(world.net, zone, freed, bk, set())
        used = sum(j.duration_min for j in take)
        text = (f"Nice case. A {planned // 60}-hour block that finishes in {actual // 60 if actual % 60 == 0 else actual / 60:g} hours leaves "
                f"{freed} minutes with the track already protected and the crew on site, so a small job waiting on that stretch can start straight away, "
                f"with no new block and no second set-up.")
        if take:
            text += (f"\n\nOn {zone} I'd pull in {len(take)} waiting job{'s' if len(take) != 1 else ''}: "
                     + "; ".join(f"{j.label.lower()} ({j.duration_min} min, P{j.priority})" for j in take)
                     + f". That uses {used} of the {freed} minutes and saves about {len(take) * 25} minutes of set-up and hand-back.")
        elif zone:
            text += f"\n\nNothing on the waiting list fits {zone} in those {freed} minutes, so the time would simply be handed back to the trains."
        else:
            text += "\n\nName the section (for example *on Kurla to Sion*) and I'll show which waiting jobs would fill it."
        text += ("\n\nFor scale: across this week's real plan (mostly short blocks), early finishes hand back about "
                 f"{d['neutral']['freed_h']:.1f} hours if crews take the planned time on average. The bigger the block, the more there is to give back.")
        a = Answer(text, [{"k": "freed", "v": f"{freed} min"}, {"k": "jobs pulled in", "v": str(len(take))}],
                   ["crew timing model", "waiting list (assumed)", "rule engine", "nothing was changed"], "reclaim",
                   suggestions=["how much time does early finishing give back over a week?", "what can you do?"])
        a.visual = {"type": "blockbar", "title": "One block, finished early", "planned_min": planned, "actual_min": actual,
                    "jobs": [{"label": j.label, "min": j.duration_min} for j in take]}
        return a

    n = d["neutral"]
    text = (f"Good question. Crews don't take exactly the planned time, so some blocks finish early. With the crew behaviour I assume (crews tend to run a bit over), "
            f"only about {d['early_blocks']:.0f} of the week's {d['blocks']} blocks finish early, handing back about {d['freed_h']:.1f} hours, and small jobs use about {d['pulled_h']:.1f} of it. "
            "That's honestly small.\n\n"
            f"If crews instead took the planned time on average (as often early as late), about {n['early_blocks']:.0f} blocks finish early and hand back about {n['freed_h']:.1f} hours; "
            f"the waiting small jobs on the same stretch (urgent first, then longest that fits) use about {n['pulled_h']:.1f} hours, which completes around {n['pulled']:.0f} extra jobs a week "
            f"and skips about {n['saved_setup_h']:.1f} hours of set-up and hand-back.\n\n"
            "The gain grows with block length: a 10-hour block that finishes 2 hours early frees far more than a 1-hour job that finishes 5 minutes early. "
            f"The waiting list ({d['backlog']} small jobs) and the crew timing are assumptions, so read this as how the mechanism behaves, not a forecast. "
            "Try *what if a 10 hour block on Kurla to Sion finishes in 8 hours?*")
    a = Answer(text, [{"k": "blocks early", "v": f"{n['early_blocks']:.0f}/{d['blocks']}"}, {"k": "hours freed", "v": f"{n['freed_h']:.1f}"},
                      {"k": "extra jobs", "v": f"{n['pulled']:.0f}"}], ["weekly plan", "crew timing model", "waiting list (assumed)", "nothing was changed"],
               "reclaim", suggestions=["what if a 10 hour block on Kurla to Sion finishes in 8 hours?", "what does a 3 hour tamping job need?"])
    a.visual = {"type": "bars", "title": "Hours in a week if crews take the planned time on average",
                "items": [{"label": "Handed back by early finishes", "value": round(n["freed_h"], 1), "best": False},
                          {"label": "Used by small waiting jobs", "value": round(n["pulled_h"], 1), "best": True},
                          {"label": "Set-up time not spent", "value": round(n["saved_setup_h"], 1), "best": True}]}
    return a


def h_greeting(q: str, s: W.Slots, world, now_s: int) -> Answer:
    low = q.lower()
    if re.search(r"\b(thanks|thank you|great|cool|nice)\b", low):
        text = "Glad that helped! Ask me anything else about the network, or tell me a job and I'll work out where it fits."
    else:
        text = ("Hello! I'm RailMitra. I can plan a block for you, try out a closure or a sudden fault on a copy of the schedule, "
                "tell you who and what a job needs on site, and explain how any part of the system works. What would you like to look at?")
    return Answer(text, [], [], "greeting", suggestions=["what can you do?", "what does a 3 hour tamping job need?",
                                                        "what if a 10 hour block is finished in 8 hours?"])


def warm(a: Answer) -> Answer:
    """A friendly lead-in and a follow-up for answers from the analysis handlers; the figures are untouched."""
    lead = {"whatif": "Sure, I tried that on a copy of the schedule, so nothing real changed.\n\n",
            "planblock": "Happy to help plan that. I re-worked the week on a copy to see what would move.\n\n",
            "traffic": "", "whos_working": "", "together": "Let me check the rules for you.\n\n",
            "sudden": "", "status": "", "why_not": "Let me look at the rules.\n\n"}.get(a.intent, "")
    if lead and not a.text.startswith(lead):
        a.text = lead + a.text
    if a.suggestions and "Want me to" not in a.text and a.intent in ("whatif", "planblock", "sudden", "together", "traffic"):
        a.text += f"\n\nWant me to try something else, like *{a.suggestions[0].rstrip('?')}*?"
    return a


# ------------------------------------------------------------------------------------- routing

_CAT = re.compile(r"\b(what can you do|what do you do|features?|capabilit\w+|everything (you|the system)|what (all )?can (i|we) (ask|do)|"
                  r"list (of )?(the )?(features|tools|functions)|tour|overview)\b")
_EXPLAIN = re.compile(r"\b(explain|what is|what are|what's|how does|how do|how is|tell me about|describe)\b")


def h_aging(q: str, s: W.Slots, world, now_s: int) -> Answer:
    """How low-priority work is kept from starving: priority aging (planner/aging.py). Read-only."""
    from backend.planner import aging as AG
    hps, floor, enabled = AG._cfg()
    booked = [t for t in W.booked_tasks(world) if not t.completed]
    rows = [AG.explain(t, now_s) for t in booked]
    moved = [r for r in rows if r["steps"] > 0]
    pushed = [r for r in rows if r["pushed_aside"] > 0]
    ladder = [(int(hps * k), max(floor, 5 - k)) for k in range(0, 5 - floor + 1)]
    text = (f"Yes: routine work does not wait forever, because a job **moves up one priority level for every {int(hps)} hours it waits**"
            f", or each time a more urgent job pushes it aside, and it **never rises above P{floor}**, so it can't outrank a P1 emergency.\n\n"
            f"- **Where it applies:** a sudden task may push aside only jobs whose *current* priority is lower than its own, so a job that has waited or been moved before is protected.\n"
            f"- **Carried over:** a job left unplaced at the end of a week is planned one level more urgent for each week it has waited (see the Month view).\n"
            f"- **Early-finish reuse:** the waiting list is ranked by current priority, so aged jobs get the freed time first.\n"
            f"- **Right now:** **{len(moved)}** of {len(booked)} booked jobs have aged at least one level and **{len(pushed)}** have been pushed aside before.\n\n"
            f"*The {int(hps)}-hour step and the P{floor} ceiling are assumed values (A-059); with `aging.enabled: false` priorities are strict.*")
    a = Answer(text, [{"k": "hours per step", "v": str(int(hps))}, {"k": "highest reachable", "v": f"P{floor}"},
                      {"k": "aged now", "v": str(len(moved))}],
               ["priority aging rule (assumed)", "booked jobs", "nothing was changed"], "aging",
               suggestions=["what if a critical S&T fault at Kurla right now?", "what can you do?"])
    a.visual = {"type": "bars", "title": "A P5 routine job's priority as it waits (lower P = more urgent)",
                "items": [{"label": f"after {h} h: P{p}", "value": 6 - p, "best": p == floor} for h, p in ladder]}
    return a


def route(q: str, world, now_s: int) -> Answer | None:
    low = q.lower()
    s = W.parse(q, world, now_s)
    if _CAT.search(low):
        return h_catalogue(q, s, world, now_s)
    if re.search(r"\bk.?medoids?\b|\bcompare\b.*\bgroup|\bcluster\w*\b.*\b(compare|versus|vs|two ways)|\b(compare|versus|vs)\b.*\bcluster", low):
        return h_clusters_run(q, s, world, now_s)
    if re.search(r"\b(alns|algorithms?|techniques?|really optimi[sz]|is it optimal|are you (sure|confident))\b", low):
        return h_algorithms(q, s, world, now_s)
    if re.search(r"\b(aging|ageing|starv\w*|low.priority (job|task|work)s?|routine (job|task|work)s?.{0,25}(wait|never|ignored)|never (get|gets|got) (done|planned|placed)|keep (getting )?(bumped|pushed))\b", low):
        return h_aging(q, s, world, now_s)
    from backend.chat import ops as _ops
    if re.search(r"\b(buffer|crew history|overrun)\w*\b", low) and not re.search(r"\bhow often\b", low) \
            and not (s.zone is not None and (s.tod_s is not None or _ops.time_range(low))):
        return h_buffers(q, s, world, now_s)
    if re.search(r"\b(predict\w*|early warning\w*|forecast\w*|watch ?list|proactive|warnings?)\b", low) \
            and not re.search(r"\b(resource|manpower|people|crew|equipment)\b", low):
        return h_prediction_note(q, s, world, now_s)
    from backend.chat import ops
    tr_ = ops.time_range(low)
    slot_words = re.search(r"\b(gap|slot|window|free|available|availability|open)\b", low)
    last_slot = getattr(ops, "LAST_SLOT_Q", None)
    if s.zone is None and last_slot and re.search(r"\b(that|this|the same) (slot|gap|window)\b", low):
        merged = last_slot + " " + q                     # "can OWD work in that slot?" means the slot just asked about
        return ops.h_slot_check(merged, W.parse(merged, world, now_s), world, now_s)
    if slot_words and s.zone is None and (tr_ or s.tod_s is not None) and re.search(r"\b(is|are) there\b|\bfree\b|\bavailable\b|\bopen\b", low)             and not re.search(r"\b(best|earliest|quietest|fit a|find (me )?a)\b", low):
        if W._CTX.get("zone"):                           # no place named: the one being talked about
            s.zone = W._CTX["zone"]
        return ops.h_slot_check(q, s, world, now_s)
    if (slot_words and s.zone is not None and (tr_ or s.tod_s is not None) and not re.search(r"\b(best|earliest|quietest|fit a|find (me )?a)\b", low)) \
            or re.search(r"\b(can|could) (my|another|other|any) (dept|department)\b|\bwhat (should|would) (the )?buffer\b|\bdynamic buffer\b|\bbuffer (for|in|on)\b", low) and s.zone is not None:
        return ops.h_slot_check(q, s, world, now_s)
    if re.search(r"\b(\d+\s*(more |extra |additional )?(workers?|people|men|staff|technicians?|maintainers?|machines?|tampers?)|more (workers|people|machines?)|fewer (workers|people)|extra (workers|people|machines?)|"
                 r"how (long|much longer|much faster|quickly)\b.*\b(take|with|if)|how (long|much time) (will|would|does) .*(take|need))", low) \
            and (s.depts or s.types or re.search(r"\b(job|task|block|work)\b", low)):
        return ops.h_crew_whatif(q, s, world, now_s)
    if re.search(r"\b(resources?|manpower|equipment|crew|machines?|materials|gang|costs?|price|budget|expense|rupees|how much (will|would|does) it|who (is|are) needed|what (does|do) .* need)\b"
                 r"|how many (workers?|people|men|staff|technicians?|maintainers?|persons?|machines?)\b"
                 r"|\b(workers?|people|staff|manpower|men) (are |is )?(needed|required|necessary)\b|what (tools|equipment|machines?|materials) ", low) \
            and not re.search(r"\b(buffer|overrun)\b", low):
        return ops.h_resources(q, s, world, now_s)
    if re.search(r"\bhow many (tasks?|jobs?|works?) (are |is |do we have |have we got )?(planned|scheduled|booked|on|there|happening)\b", low) \
            and not re.search(r"\b(placed|unplaced|of 40|weekly plan)\b", low):
        return ops.h_tasks(q, s, world, now_s)
    if (re.match(r"^\s*(show|list|display|view|see|give me)\b", low) and re.search(r"\b(tasks?|jobs?|work|maintenance|planned|scheduled|schedule|plan)\b", low)) \
            or re.search(r"\bwhat (tasks|jobs|work|maintenance) (is|are)\b", low):
        return ops.h_tasks(q, s, world, now_s)
    if re.search(r"\b(finish\w* early|finished early|ends? early|over early|early finish\w*|finishing early|leftover|left over|freed|spare time|reclaim)\b", low) \
            or (re.search(r"\bblock\b", low) and len(_durations(low)) >= 2 and re.search(r"\b(finish\w*|done|over|complete\w*)\b", low)):
        return h_reclaim(q, s, world, now_s)
    if re.search(r"^\s*(hi|hello|hey|namaste|thanks|thank you|good (morning|afternoon|evening))\b", low):
        return h_greeting(q, s, world, now_s)
    if re.search(r"\bpriorit\w*\b.*\b(cluster|group)\w*|\b(cluster|group)\w*\b.*\b(small|big|priority|urgen\w*)", low):
        return h_clusters_run(q, s, world, now_s)
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
