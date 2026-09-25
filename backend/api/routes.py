"""API routes (SPEC §17).

<!-- serves: J2, J4, J5 -->
"""

from __future__ import annotations

import random
import time
from collections import Counter

from fastapi import APIRouter, HTTPException

from backend.api.state import (
    STATE, ensure_interval_index, ensure_plan, ensure_world, make_creator, new_demand_task,
    occupancy_by_section, reset,
)
from backend.config import load_config
from backend.domain.compatibility import coordination_conflicts, matrix
from backend.domain.models import TrackStatus, WorkZoneKind, s_to_hhmm
from backend.gaps.engine import GapType
from backend.adapters import all_adapters, registry
from backend.chat.engine import answer as chat_answer
from backend.metrics.impact import compute as compute_impact
from backend.planner.cpsat import solve_with_relaxation

router = APIRouter()
from backend.config import REPO_ROOT as _RR
REPO_ROOT_MODELS = _RR / 'artifacts' / 'models'
REPO_ROOT_ART = _RR / 'artifacts'
DAY_S = 86400
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


@router.get("/api/network")
def network() -> dict:
    w = ensure_world()
    return {
        "corridor": w.net.corridor_id,
        "name": w.net.name,
        "stations": [
            {
                "code": s.code, "name": s.name, "lat": s.lat, "lon": s.lon,
                "tier": s.tier.value if s.tier else None, "junction": s.is_junction,
                "platforms": s.platforms, "trains_per_day": s.trains_per_day,
                "peak_tph": s.peak_trains_per_hour,
                "line_code": s.line_code, "lines": s.lines, "coord_src": s.coord_src,
                "status": w.registry.get(s.code).value,
            }
            for s in w.net.stations.values()
        ],
        "sections": [
            {
                "id": s.id, "from": s.from_station, "to": s.to_station,
                "length_km": s.length_km, "line_speed_kmph": s.line_speed_kmph,
                "tracks": s.tracks, "tier": s.tier.value if s.tier else None,
                "geometry": s.geometry, "trains_per_day": s.trains_per_day,
                "line_code": s.line_code,
                "status": w.registry.get(s.id).value,
            }
            for s in w.net.sections.values()
        ],
        "order": w.net.order,
    }


@router.get("/api/tasks")
def tasks() -> dict:
    w = ensure_world()
    plan = STATE.plan
    placed = {a.task_id: a for a in plan.assignments} if plan else {}
    out = []
    for t in w.tasks:
        a = placed.get(t.id)
        out.append({
            "id": t.id, "department": t.department.value, "dept_label": t.department.label,
            "source_system": t.department.source_system,
            "type": t.task_type, "label": t.label, "zone": t.zone.ref,
            "zone_kind": t.zone.kind.value, "duration_min": t.duration_min,
            "priority": t.priority, "category": t.category.value,
            "power_block": t.requires_power_block, "completed": t.completed,
            "outcome": t.outcome.value if t.outcome else None,
            "describe": t.describe(),
            "scheduled": bool(a) or t.id in STATE.user_placements,
            "start_s": (a.start_s if a else (STATE.user_placements[t.id].start_s
                                              if t.id in STATE.user_placements else None)),
            "day": (DAYS[a.day] if a else (DAYS[STATE.user_placements[t.id].start_s // DAY_S % 7]
                                            if t.id in STATE.user_placements else None)),
            "start_hhmm": (s_to_hhmm(a.start_s % DAY_S) if a else (
                s_to_hhmm(STATE.user_placements[t.id].start_s % DAY_S)
                if t.id in STATE.user_placements else None)),
            "gap_type": a.gap_type if a else (STATE.user_placements[t.id].window.gap_type.value
                                              if t.id in STATE.user_placements
                                              and STATE.user_placements[t.id].window else None),
            "source": t.source, "description": t.description,
        })
    return {"tasks": out, "total": len(out),
            "by_department": dict(Counter(t["department"] for t in out))}


@router.get("/api/compatibility/matrix")
def compatibility_matrix(limit: int = 24, scheduled: bool = False) -> dict:
    """The compatibility question the three department heads face.

    By default this is the PRE-scheduling view: tasks are treated as unscheduled, so the
    matrix shows which jobs genuinely cannot share a zone and time. Once the planner has
    separated them in time, rule R3 makes almost every pair compatible - true, but it is the
    answer, not the question, and the question is what the manual process has to work through.

    Pass scheduled=true to see the post-plan matrix instead.
    """
    w = ensure_world()
    # Prefer tasks that actually interact, so the matrix shows something worth reading.
    interacting = [
        t for t in w.tasks
        if any(o is not t and (o.zone.endpoints & t.zone.endpoints) for o in w.tasks)
    ]
    chosen = (interacting or w.tasks)[:limit]
    subset = chosen if scheduled else [
        t.model_copy(update={"scheduled_start_s": None, "scheduled_end_s": None})
        for t in chosen
    ]
    m = matrix(w.net, subset)
    m["view"] = "post-plan" if scheduled else "pre-plan (the manual negotiation)"
    m["coordination_conflicts"] = coordination_conflicts(w.net, subset)
    cfg = load_config()
    hours = float(cfg.get_path("metrics.manual_coordination_hours_per_conflict", 4.0))
    m["manual_coordination_hours"] = round(m["coordination_conflicts"] * hours, 1)
    return m


@router.get("/api/gaps")
def gaps() -> dict:
    w = ensure_world()
    by_type = Counter(x.gap_type.value for x in w.gaps.windows)
    usable = Counter()
    for x in w.gaps.windows:
        usable[x.gap_type.value] += x.usable_min()
    raw = sum(x.raw_min for x in w.gaps.windows)
    use = sum(x.usable_min() for x in w.gaps.windows)
    return {
        "counts": dict(by_type),
        "usable_hours": {k: round(v / 60, 1) for k, v in usable.items()},
        "raw_hours": round(raw / 60, 1),
        "total_usable_hours": round(use / 60, 1),
        "usable_pct_of_raw": round(100 * use / max(1, raw)),
        "night_windows": {k: [s_to_hhmm(a), s_to_hhmm(b)]
                          for k, (a, b) in list(w.gaps.night_windows_by_section.items())[:20]},
        "megablock_observed_reduction": round(
            100 * sum(w.gaps.megablock_observed.values())
            / max(1, len(w.gaps.megablock_observed))),
        "block_setup_min": load_config().get_path("gaps.block_setup_min"),
        "block_release_min": load_config().get_path("gaps.block_release_min"),
    }


@router.post("/api/plan/cpsat")
def plan_cpsat() -> dict:
    w = ensure_world()
    t0 = time.time()
    from backend.api.state import get_pax, reroute_cache
    from backend.planner.creation_plan import solve_with_creation

    natural, res, created = solve_with_creation(
        w.net, w.tasks, w.windows, occupancy_by_section(), reroute_cache(),
        time_limit_s=load_config()["planner"]["solve_time_s_demo"], pax=get_pax())
    STATE.plan_natural = natural
    STATE.plan = res
    from backend.api.state import creation_summary
    STATE.creation_used = creation_summary(w, res, created)
    STATE.log(0, (f"CP-SAT re-planned the week in {res.wall_s:.1f}s: "
                  f"{len(res.assignments)} jobs placed."), "plan")
    d = res.to_dict()
    d["latency_ms"] = round((time.time() - t0) * 1000)
    return d


@router.post("/api/plan/rl")
def plan_rl() -> dict:
    """Re-plan the current task pool with the learned dispatcher alone.

    Same task pool and windows CP-SAT sees, scored with CP-SAT's own objective, so the
    two numbers mean the same thing when compared - see backend/rl/env.py.
    """
    from backend.rl.env import rollout

    from backend.rl.policies import load_best_policy

    w = ensure_world()
    policy, dispatcher_note = load_best_policy()
    t0 = time.time()
    r = rollout(policy, w.net, w.tasks, w.windows)
    latency_ms = (time.time() - t0) * 1000
    res = _rollout_to_plan_result(w.net, w.tasks, r)
    STATE.plan = res
    STATE.log(0, (f"RL dispatcher ({dispatcher_note}) re-planned the week in "
                  f"{latency_ms:.0f} ms: {len(res.assignments)} jobs placed."), "plan")
    d = res.to_dict()
    d["latency_ms"] = round(latency_ms, 1)
    d["dispatcher"] = dispatcher_note
    d["violations"] = r.violations
    return d


@router.get("/api/plan")
def plan() -> dict:
    res = ensure_plan()
    d = res.to_dict()
    d["by_day"] = {DAYS[i]: sum(1 for a in res.assignments if a.day == i) for i in range(7)}
    d["by_gap_type"] = dict(Counter(a.gap_type for a in res.assignments))
    return d


@router.get("/api/rerouting/opportunities")
def rerouting_opportunities() -> dict:
    """For each task CP-SAT could not place, what lever could create a window (SPEC §9).

    A standalone advisor, deliberately not wired into the solver's own objective - the solver
    already reaches OPTIMAL at a 0% gap, and path selection inside CP-SAT is the highest-risk
    change left in the project. This analyses the same unplaced tasks after the fact.
    """
    from backend.planner.rerouting import find_opportunities

    w = ensure_world()
    res = ensure_plan()
    opps = find_opportunities(w.net, w.tasks, w.windows, res.unscheduled, w.week)
    tasks_by_id = {t.id: t for t in w.tasks}
    out = []
    for o in opps:
        d = o.to_dict()
        t = tasks_by_id.get(o.task_id)
        if t is not None:
            d["task_label"] = t.label
            d["department"] = t.department.value
            d["duration_min"] = t.duration_min
        out.append(d)
    return {"unscheduled_total": len(res.unscheduled), "opportunities": out}


@router.post("/api/sim/tick")
def sim_tick(at_s: int = 0) -> dict:
    """One tick of the live Operations-map simulation (SPEC's map, ROADMAP's "continuous
    demand arrivals" gap): a small batch of new, unplanned tasks is generated and gap-scheduled
    right now with Max-to-Min greedy ordering and an ALNS-lite destroy/repair insertion
    (backend/planner/live_sim.py) — kept fully separate from the CP-SAT weekly plan and the
    trained RL dispatcher, neither of which this reads from or writes to.
    """
    from backend.planner.live_sim import alns_lite_insert, order_max_to_min, random_task

    w = ensure_world()
    index = ensure_interval_index()
    rng = random.Random(load_config()["seed"] + 97 * (STATE.sim_seq + 1))
    n = rng.choices([1, 2], weights=[70, 30], k=1)[0]

    batch = []
    for i in range(n):
        STATE.sim_seq += 1
        batch.append(random_task(w.net, rng, at_s, STATE.sim_seq))
    ordered = order_max_to_min(batch)
    creator = make_creator()

    results = []
    for t in ordered:
        placement = alns_lite_insert(w.net, t, index, w.tasks, STATE.live_sim,
                                     creator=creator, at_s=at_s)
        STATE.log(
            at_s,
            f"Simulated arrival: {t.describe()} — {placement.reason}.",
            "plan" if placement.placed else "info",
        )
        results.append({
            "task": {"id": t.id, "describe": t.describe(), "zone": t.zone.ref, "label": t.label,
                     "department": t.department.value, "duration_min": t.duration_min,
                     "priority": t.priority},
            "placed": placement.placed,
            "window": (None if placement.window is None else {
                "id": placement.window.id, "section_id": placement.window.section_id,
                "zone_ref": placement.window.zone_ref, "track": placement.window.track,
                "start_s": placement.start_s,
                "end_s": placement.end_s,
                "gap_type": placement.window.gap_type.value,
                "created_by": placement.window.created_by,
            }),
            "reason": placement.reason,
            "integrated_with": placement.integrated_with,
            "created": None if placement.created is None else placement.created.to_dict(),
        })
    return {"at_s": at_s, "results": results,
            "algorithm": "Max-to-Min greedy ordering + ALNS-lite destroy/repair insertion"}


def _occupancy_by_section() -> dict:
    return occupancy_by_section()


@router.get("/api/sections/{section_id}/brief")
def section_brief(section_id: str, at_s: int = 0) -> dict:
    """Plain-language summary + next available gap, for the Operations map's click panel.

    Uses the interval tree's range query (backend/planner/interval_index.py) to answer "what's
    free here in the next day" — a question the plain per-zone dict index cannot answer without
    scanning every window. Also returns, per track, the day's train passes and the gaps found
    between them, so the UI can show HOW the gaps were identified rather than just their count.
    """
    w = ensure_world()
    sec = w.net.sections.get(section_id)
    if sec is None:
        raise HTTPException(status_code=404, detail="unknown section")
    index = ensure_interval_index()
    status = w.registry.get(section_id)
    at_s = at_s or STATE.sim_time_s

    open_tasks = [t for t in w.tasks if t.zone.ref == section_id and not t.completed]
    upcoming = index.free_in(section_id, WorkZoneKind.SECTION, at_s, at_s + 24 * 3600)
    next_gap = upcoming[0] if upcoming else None

    day_lo = (at_s // DAY_S) * DAY_S
    day_hi = day_lo + DAY_S
    day_gaps = index.free_in(section_id, WorkZoneKind.SECTION, day_lo, day_hi)
    timeline = []
    for track in sec.tracks:
        passes = sorted(o.enter_s - day_lo for o in _occupancy_by_section().get(section_id, [])
                        if o.track == track and day_lo <= o.enter_s < day_hi)
        gaps = [[max(g.start_s, day_lo) - day_lo, min(g.end_s, day_hi) - day_lo,
                 g.gap_type.value, g.usable_min()]
                for g in day_gaps if g.track == track]
        timeline.append({"track": track, "trains": passes, "gaps": gaps})

    if open_tasks:
        lead = open_tasks[0]
        summary = f"{lead.department.label} is doing {lead.label.lower()} here, {lead.duration_min} min."
        if len(open_tasks) > 1:
            summary += f" {len(open_tasks) - 1} more job(s) are waiting on this section."
    elif status is not TrackStatus.FIT:
        summary = f"No work booked yet, but this section is {status.value.replace('_', ' ').lower()}."
    else:
        summary = "Nothing outstanding here right now — the section is fit and clear."

    return {
        "section_id": section_id, "status": status.value, "summary": summary,
        "timeline": timeline, "day_start_s": day_lo, "now_s": at_s - day_lo,
        "open_task_count": len(open_tasks),
        "next_gap": (None if next_gap is None else {
            "start_hhmm": s_to_hhmm(next_gap.start_s % DAY_S),
            "end_hhmm": s_to_hhmm(next_gap.end_s % DAY_S),
            "gap_type": next_gap.gap_type.value,
            "usable_min": next_gap.usable_min(),
        }),
    }


def _cluster_pool() -> list:
    """Open planned/demand jobs plus whatever the live simulation has placed so far."""
    w = ensure_world()
    live = [p.task for p in STATE.live_sim.placed if p.placed][-24:]   # recent arrivals only
    return [t for t in w.tasks if not t.completed] + live


_CLUSTER_CACHE: dict = {}
_CLUSTER_LOCK = __import__("threading").Lock()


@router.get("/api/tasks/clusters")
def task_clusters(method: str = "average") -> dict:
    """Jobs grouped by position: average-linkage (default) or K-Medoids, with both scored side by side."""
    from backend.planner.clustering import cluster_tasks, compare_methods

    w = ensure_world()
    pool = _cluster_pool()
    cut = float(load_config().get_path("clustering.cut_km", 5.0))
    m = "kmedoids" if method == "kmedoids" else "average"
    # The grouping only depends on the jobs (where, how urgent, which department), and this is polled every
    # tick, so an unchanged pool is answered from memory instead of being re-clustered and re-scored (~1 s).
    key = (m, cut, tuple((t.id, t.zone.ref, t.priority, t.department.value, t.completed) for t in pool))
    with _CLUSTER_LOCK:                 # two identical requests at once: the second waits for the first, then reads it
        hit = _CLUSTER_CACHE.get(key)
        if hit is not None:
            return hit
        out = _cluster_answer(w, pool, cut, m, cluster_tasks, compare_methods)
        if len(_CLUSTER_CACHE) > 8:
            _CLUSTER_CACHE.clear()
        _CLUSTER_CACHE[key] = out
        return out


def _cluster_answer(w, pool, cut, m, cluster_tasks, compare_methods) -> dict:
    clusters = cluster_tasks(w.net, pool, cut_km=cut, method=m)
    out = {"n_tasks": len(pool), "n_clusters": len(clusters), "cut_km": cut,
           "method": "K-Medoids (k by silhouette)" if m == "kmedoids" else "average-linkage agglomerative (scipy)",
           "compare": compare_methods(w.net, pool, cut),
           "clusters": [c.to_dict() for c in clusters]}
    return out


_PROOF_STATIC: dict | None = None
_REROUTE_PROOF: tuple | None = None


def _proof_interval_tree() -> dict:
    """Measured, not asserted: the same range queries answered by a full scan and by the tree."""
    w = ensure_world()
    index = ensure_interval_index()
    sections = list(w.net.sections)
    queries = [(sections[i % len(sections)], (i * 7919) % (6 * DAY_S)) for i in range(60)]

    t0 = time.perf_counter()
    scan_results = []
    for zone, lo in queries:
        hi = lo + 3 * 3600
        scan_results.append({x.id for x in w.windows
                             if x.zone_ref == zone and x.zone_kind == WorkZoneKind.SECTION
                             and x.start_s < hi and lo < x.end_s})
    scan_ms = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    tree_results = [{x.id for x in index.free_in(zone, WorkZoneKind.SECTION, lo, lo + 3 * 3600)}
                    for zone, lo in queries]
    tree_ms = (time.perf_counter() - t0) * 1000

    return {"queries": len(queries), "scan_ms": round(scan_ms, 1), "tree_ms": round(tree_ms, 2),
            "speedup_x": round(scan_ms / max(1e-6, tree_ms), 1),
            "identical": scan_results == tree_results}


_REROUTE_CACHE: dict = {}
_REROUTE_SEEN: set = set()
_WEEK_BY_ID: dict | None = None


def _active_blocks(at_s: int) -> list[tuple[str, int, int, str | None]]:
    """Section blocks in force at this instant: the weekly plan's and the live simulation's, each with its exact line."""
    w = ensure_world()
    out: list[tuple[str, int, int, str | None]] = []
    if STATE.plan:
        for a in STATE.plan.assignments:
            if a.task_id in STATE.overrides:
                continue   # pushed aside by a sudden task: its new slot is added below
            if a.zone_ref in w.net.sections and a.start_s <= at_s < a.end_s:
                out.append((a.zone_ref, a.start_s, a.end_s, a.track))
    for o in STATE.overrides.values():
        if o and o["zone_ref"] in w.net.sections and o["start_s"] <= at_s < o["end_s"]:
            out.append((o["zone_ref"], o["start_s"], o["end_s"], o.get("track")))
    for p in (list(STATE.live_sim.placed) + list(STATE.user_placements.values())
              + list(STATE.sudden_state.placed) + list(STATE.forecast_state.placed)
              + list(STATE.daily_state.placed)):
        if p.placed and p.window is not None and p.window.zone_ref in w.net.sections:
            if p.start_s is not None and p.start_s <= at_s < p.end_s:
                out.append((p.window.zone_ref, p.start_s, p.end_s, p.window.track))
    return list(dict.fromkeys(out))


@router.get("/api/rerouting/active")
def rerouting_active(at_s: int = 0) -> dict:
    """Trains due through a section that is blocked right now, and where they go instead.

    Each closure is also sent to the digital twin (in the background). Its answer decides whether diverting
    long-distance trains, and running locals single-line, is really better than waiting: a detour the twin
    finds costlier than holding is not shown as taken."""
    from backend.api.state import reroute_cache
    from backend.planner.advisor import response_for
    from backend.planner.active_reroute import plan_block_reroutes

    global _WEEK_BY_ID
    w = ensure_world()
    if _WEEK_BY_ID is None:
        _WEEK_BY_ID = {t.id: t for t in w.week}
    blocks = []
    for section_id, start, end, track in _active_blocks(at_s):
        key = (section_id, start, end, track)
        if key not in _REROUTE_CACHE:
            _REROUTE_CACHE[key] = plan_block_reroutes(
                w.net, _WEEK_BY_ID, _occupancy_by_section().get(section_id, []),
                w.net.sections[section_id], start, end, track).to_dict()
            _REROUTE_CACHE[key]["track"] = track
        b = dict(_REROUTE_CACHE[key])
        resp = response_for(w, reroute_cache(), section_id, start, end)
        b["response"] = resp
        if b["reroutes"] and not resp["divert"]:
            b["held"], b["reroutes"] = b["reroutes"], []           # the twin says waiting costs fewer passengers
        if b["track_swap"] and not resp["single_line"]:
            b["swap_declined"], b["track_swap"] = b["track_swap"], None
        for r in b["reroutes"]:
            _REROUTE_SEEN.add((section_id, start, r["train_id"]))
        blocks.append(b)
    return {"at_s": at_s, "blocks": blocks, "executed": len(_REROUTE_SEEN)}


_REROUTE_PROOF_WEEK: dict | None = None


@router.get("/api/rerouting/proof")
def rerouting_proof() -> dict:
    """Every block in the weekly plan, and what happens to the through trains due in it.

    Measured from the plan and the timetable, not staged: how many long-distance and freight trains would be
    sent round, what each detour adds, and what the same train would have lost waiting for the block to lift.
    Suburban locals are counted separately and are never rerouted."""
    from backend.planner.active_reroute import plan_block_reroutes

    global _REROUTE_PROOF_WEEK, _WEEK_BY_ID
    if _REROUTE_PROOF_WEEK is not None:
        return _REROUTE_PROOF_WEEK
    w = ensure_world()
    plan = ensure_plan()
    if _WEEK_BY_ID is None:
        _WEEK_BY_ID = {t.id: t for t in w.week}
    occ = _occupancy_by_section()
    seen_blocks, rows = set(), []
    n_blocks = with_through = no_path = locals_hit = locals_rerouted = 0
    for a in plan.assignments:
        if a.zone_ref not in w.net.sections or (a.zone_ref, a.start_s, a.end_s) in seen_blocks:
            continue
        seen_blocks.add((a.zone_ref, a.start_s, a.end_s))
        key = (a.zone_ref, a.start_s, a.end_s, a.track)        # the same key the live map uses: only the closed line is affected
        if key not in _REROUTE_CACHE:
            _REROUTE_CACHE[key] = plan_block_reroutes(w.net, _WEEK_BY_ID, occ.get(a.zone_ref, []),
                                                      w.net.sections[a.zone_ref], a.start_s, a.end_s, a.track).to_dict()
            _REROUTE_CACHE[key]["track"] = a.track
        b = _REROUTE_CACHE[key]
        n_blocks += 1
        locals_hit += b["locals_in_window"]
        no_path += len(b["no_path"])
        locals_rerouted += sum(1 for r in b["reroutes"] if r["train_class"] == "SUBURBAN_LOCAL")
        if b["reroutes"] or b["no_path"]:
            with_through += 1
        for r in b["reroutes"]:
            wait = max(0.0, (a.end_s - r["enter_s"]) / 60.0)          # it would wait until the block lifts
            rows.append({"section_id": a.zone_ref, "block_start_s": a.start_s, "block_end_s": a.end_s,
                         "train_id": r["train_id"], "train": r["train_name"] or r["train_id"], "class": r["train_class"],
                         "enter_s": r["enter_s"], "via": len(r["sections"]), "sections": r["sections"],
                         "added_min": r["added_delay_min"], "wait_min": round(wait, 1), "within_limit": r["within_limit"]})
    n = len(rows)
    added = sum(r["added_min"] for r in rows)
    wait = sum(r["wait_min"] for r in rows)
    ok = sum(1 for r in rows if r["within_limit"])
    rows.sort(key=lambda r: -(r["wait_min"] - r["added_min"]))
    _REROUTE_PROOF_WEEK = {
        "blocks": n_blocks, "blocks_with_through_trains": with_through, "diverted": n,
        "within_limit": ok, "added_min": round(added, 1), "wait_min": round(wait, 1),
        "saved_min": round(wait - added, 1), "mean_added_min": round(added / n, 1) if n else 0.0,
        "no_path": no_path, "locals_in_blocks": locals_hit, "locals_rerouted": locals_rerouted,
        "examples": rows[:8],
        "how": "Every block in the weekly plan; each long-distance or freight train due through it is sent by the reroute "
               "search (shortest path avoiding the closed section, checked against that train's delay limit). "
               "Waiting is the train held until the block lifts; it ignores knock-on delay, which the digital twin adds.",
    }
    return _REROUTE_PROOF_WEEK


@router.get("/api/algorithms/proof")
def algorithms_proof() -> dict:
    """Measured evidence that each algorithm ran, from the same objects the app uses.

    The interval-tree benchmark is computed once (the world is static) and cached; everything
    else is read live so the numbers move as the simulation runs.
    """
    import json

    global _PROOF_STATIC, _REROUTE_PROOF
    w = ensure_world()
    plan = ensure_plan()
    if _PROOF_STATIC is None:
        _PROOF_STATIC = _proof_interval_tree()

    by_type = Counter(x.gap_type.value for x in w.gaps.windows)
    usable = sum(x.usable_min() for x in w.gaps.windows)

    from backend.planner.clustering import cluster_tasks
    pool = _cluster_pool()
    clusters = cluster_tasks(w.net, pool)
    cross = sum(c.cross_pairs for c in clusters)

    if _REROUTE_PROOF is None or _REROUTE_PROOF[0] != id(plan):
        from backend.planner.rerouting import find_opportunities
        opps = find_opportunities(w.net, w.tasks, w.windows, plan.unscheduled, w.week)
        _REROUTE_PROOF = (id(plan), {
            "unplaced": len(plan.unscheduled),
            "with_lever": sum(1 for o in opps if o.reroute_paths or o.track_swap),
            "reroute_paths": sum(len(o.reroute_paths) for o in opps),
            "track_swaps": sum(1 for o in opps if o.track_swap),
        })

    rl = None
    path = REPO_ROOT_ART / "rl_comparison.json"
    if path.exists():
        d = json.loads(path.read_text(encoding="utf-8"))
        best = min(d["table"], key=lambda r: r["mean_gap_vs_cpsat_pct"])
        rl = {"policy": best["policy"], "gap_pct": best["mean_gap_vs_cpsat_pct"],
              "speedup_x": round(d["cpsat_mean_ms"] / max(1.0, best["mean_full_replan_ms"]), 1),
              "instances": d["instances"]}

    placed_live = [p for p in STATE.live_sim.placed if p.placed]
    return {
        "interval_tree": _PROOF_STATIC,
        "gaps": {"total": len(w.gaps.windows), "micro": by_type.get("MICRO_GAP", 0),
                 "night": by_type.get("NIGHT_WINDOW", 0), "megablock": by_type.get("MEGABLOCK", 0),
                 "usable_hours": round(usable / 60)},
        "cpsat": {"status": plan.status, "gap_pct": plan.gap_pct, "placed": len(plan.assignments),
                  "n_tasks": plan.n_tasks, "wall_s": round(plan.wall_s, 2)},
        "rl": rl,
        "clusters": {"tasks": len(pool), "clusters": len(clusters), "cross_pairs": cross,
                     "compatible": sum(c.compatible for c in clusters)},
        "live_sim": {"arrived": len(STATE.live_sim.placed), "placed": len(placed_live),
                     "moved_aside": sum(1 for p in placed_live if "moving aside" in p.reason)},
        "rerouting": {**_REROUTE_PROOF[1], "executed": len(_REROUTE_SEEN)},
    }


def _rollout_to_plan_result(net, tasks, rollout_result) -> "PlanResult":
    """Express an RL rollout in the same shape CP-SAT results are rendered in.

    So the UI's plan rendering, the map's active-block overlay and the task pool all work
    identically whichever dispatcher produced the schedule - the map should not need to know
    which one it is looking at.
    """
    from backend.planner.cpsat import Assignment, PlanResult
    from backend.rl.env import objective_of

    assignments = [
        Assignment(
            task_id=task.id, window_id=window.id, section_id=window.section_id,
            zone_ref=window.zone_ref, track=window.track,
            start_s=window.start_s, end_s=window.start_s + task.duration_min * 60,
            gap_type=window.gap_type.value, day=window.start_s // DAY_S,
        )
        for task, window in rollout_result.placements
    ]
    return PlanResult(
        status="RL_DISPATCH", objective=objective_of(rollout_result.placements, tasks,
                                                      rollout_result.iwp_used),
        best_bound=0.0, gap_pct=0.0, wall_s=0.0,
        assignments=assignments, unscheduled=rollout_result.unscheduled,
        n_tasks=len(tasks), n_windows_considered=0, iwp_used=rollout_result.iwp_used,
    )


@router.post("/api/tasks/demand")
def inject_demand(zone_ref: str | None = None, at_s: int = 0) -> dict:
    """Inject an unplanned defect and re-plan both ways, side by side (SPEC §13.2).

    This is the demo's centrepiece: the same problem, solved twice. CP-SAT re-solves the
    whole week exactly, which takes seconds; the learned dispatcher reacts in milliseconds.
    The RL schedule is the one actually applied live, because that is the point of having it -
    a controller cannot wait seconds every time a defect is reported.
    """
    import time as _time

    w = ensure_world()
    t = new_demand_task(at_s or STATE.sim_time_s, zone_ref)
    STATE.log(at_s or STATE.sim_time_s,
              f"Unplanned defect reported: {t.describe()}.", "demand")

    t0 = _time.perf_counter()
    cpsat_res = solve_with_relaxation(
        w.net, w.tasks, w.windows,
        time_limit_s=load_config()["planner"]["solve_time_s_demo"])
    cpsat_ms = (_time.perf_counter() - t0) * 1000

    from backend.rl.env import rollout
    from backend.rl.policies import load_best_policy

    policy, dispatcher_note = load_best_policy()
    t0 = _time.perf_counter()
    rl_rollout = rollout(policy, w.net, w.tasks, w.windows)
    rl_ms = (_time.perf_counter() - t0) * 1000
    rl_res = _rollout_to_plan_result(w.net, w.tasks, rl_rollout)

    # Apply the reactive schedule live: this is the plan the map and task pool now show.
    STATE.plan = rl_res
    demand_placed = any(a.task_id == t.id for a in rl_res.assignments)
    speedup = cpsat_ms / max(1e-6, rl_ms)
    STATE.log(
        at_s or STATE.sim_time_s,
        (f"Re-planned in {rl_ms:.0f} ms with {dispatcher_note} "
         f"({speedup:.0f}x faster than CP-SAT's {cpsat_ms / 1000:.1f}s full re-solve). "
         f"{'The new job was fitted in.' if demand_placed else 'No window was found for it yet.'}"),
        "plan",
    )

    return {
        "task": {"id": t.id, "describe": t.describe(), "zone": t.zone.ref,
                 "department": t.department.value, "duration_min": t.duration_min,
                 "priority": t.priority},
        "cpsat": {"status": cpsat_res.status, "latency_ms": round(cpsat_ms, 1),
                  "scheduled": len(cpsat_res.assignments), "n_tasks": cpsat_res.n_tasks,
                  "demand_task_placed": any(a.task_id == t.id for a in cpsat_res.assignments)},
        "rl": {"status": "OK", "dispatcher": dispatcher_note, "latency_ms": round(rl_ms, 1),
               "scheduled": len(rl_res.assignments), "n_tasks": rl_res.n_tasks,
               "violations": rl_rollout.violations,
               "demand_task_placed": demand_placed},
        "speedup_x": round(speedup, 1),
    }


_SEGMENTS: list | None = None


def _segments() -> list:
    """Flatten the week into (train, section, enter, exit) segments once, for interpolation."""
    global _SEGMENTS
    if _SEGMENTS is not None:
        return _SEGMENTS
    w = ensure_world()
    coords = {c: (st.lat, st.lon) for c, st in w.net.stations.items()}
    out = []
    for o in w.occupancy:
        sec = w.net.sections.get(o.section_id)
        if sec is None:
            continue
        a, b = coords.get(sec.from_station), coords.get(sec.to_station)
        if not a or not b:
            continue
        # Direction determines which end the train starts from.
        if o.direction == "UP":
            a, b = b, a
        out.append((o.train_id, o.train_class.value, o.enter_s, o.exit_s, a, b, o.section_id, o.track))
    out.sort(key=lambda r: r[2])
    _SEGMENTS = out
    return out


@router.get("/api/trains")
def trains(at_s: int = 0, limit: int = 120) -> dict:
    """Train positions at a simulated instant.

    Capped at `limit`: rendering every one of the corridor's services at once produces an
    unreadable smear of dots, and a map nobody can read is worse than no map.
    """
    segs = _segments()
    active = []
    for tid, cls, enter, exit_, a, b, sid, track in segs:
        if enter <= at_s < exit_:
            f = (at_s - enter) / max(1, exit_ - enter)
            active.append({
                "id": tid, "cls": cls, "section": sid, "track": track,
                "lat": a[0] + (b[0] - a[0]) * f,
                "lon": a[1] + (b[1] - a[1]) * f,
            })
    total = len(active)
    # Keep long-distance and freight visible when trimming: they are the reroutable ones.
    active.sort(key=lambda t: 0 if t["cls"] != "SUBURBAN_LOCAL" else 1)
    return {"at_s": at_s, "trains": active[:limit], "total_active": total,
            "truncated": max(0, total - limit)}


@router.get("/api/status/sections")
def section_status() -> dict:
    w = ensure_world()
    counts = Counter()
    rows = []
    for sec in w.net.sections.values():
        st = w.registry.get(sec.id)
        counts[st.value] += 1
        rows.append({"id": sec.id, "status": st.value, "tier": sec.tier.value if sec.tier else None})
    for code in w.net.order:
        st = w.registry.get(code)
        if st is not TrackStatus.FIT:
            counts[st.value] += 1
    return {"sections": rows, "counts": dict(counts)}


@router.get("/api/events")
def events(limit: int = 60) -> dict:
    ensure_world()
    return {"events": STATE.event_log[-limit:]}


@router.post("/api/reset")
def do_reset() -> dict:
    reset()
    ensure_world()
    return {"ok": True}


# ------------------------------------------------------------------ chat, impact, adapters


@router.post("/api/chat")
def chat(payload: dict) -> dict:
    """Grounded question answering over live state. No language model is involved."""
    w = ensure_world()
    # Answers about what is booked read the solved plan and the daily routine jobs; make sure they exist (a no-op once built).
    ensure_plan()
    try:
        from backend.api.routes_tasks import ensure_dayfill
        ensure_dayfill()
    except Exception:
        pass
    a = chat_answer(str(payload.get("q", "")), w, STATE.plan, int(payload.get("at_s", 0) or 0))
    return a.to_dict()


_IMPACT_CACHE: dict = {}


@router.get("/api/metrics/impact")
def impact(hours_per_conflict: float | None = None, wait_days: float | None = None) -> dict:
    """Before/after metrics.

    The dispatcher comes from load_best_policy, which lives in the torch-free policies module.
    Importing it from backend.rl.agents instead would pull torch into the request path, and on
    a memory-constrained machine torch's DLL init takes an access violation that no try/except
    can catch - which is exactly how this endpoint was returning 500 while the same computation
    ran fine from a script.
    """
    w = ensure_world()
    plan = ensure_plan()
    from backend.rl.policies import load_best_policy

    # The measurement re-runs several solves; for one plan and one setting it cannot change, so it is
    # done once. A new plan (or a different slider position) is a different key.
    key = (id(plan), len(w.tasks), hours_per_conflict, wait_days)
    if key in _IMPACT_CACHE:
        return _IMPACT_CACHE[key]
    policy, note = load_best_policy()
    rep = compute_impact(w.net, w.tasks, w.windows, plan, policy,
                         hours_per_conflict=hours_per_conflict, wait_days=wait_days)
    d = rep.to_dict()
    # Which dispatcher produced the latency figure is part of the claim, not a footnote.
    d["dispatcher"] = note
    _IMPACT_CACHE.clear() if len(_IMPACT_CACHE) > 12 else None
    _IMPACT_CACHE[key] = d
    return d


@router.get("/api/rl/comparison")
def rl_comparison() -> dict:
    import json
    path = REPO_ROOT_ART / "rl_comparison.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Run scripts/06_evaluate_rl.py first.")
    return json.loads(path.read_text(encoding="utf-8"))


@router.get("/api/adapters")
def adapters() -> dict:
    w = ensure_world()
    plan = STATE.plan
    reg = registry()
    tasks_by_id = {t.id: t for t in w.tasks}
    sample_demands = (reg["BDMS"].submit_block_plan(plan.assignments[:3], tasks_by_id)
                      if plan else [])
    return {
        "mode": load_config().get_path("adapters.mode"),
        "adapters": all_adapters(),
        "sample_block_demands": sample_demands,
        "sample_task_records": {
            "TMS": reg["TMS"].fetch_tasks(w.tasks)[:2],
            "SMMS": reg["SMMS"].fetch_tasks(w.tasks)[:2],
            "TDMS": reg["TDMS"].fetch_tasks(w.tasks)[:2],
        },
    }
