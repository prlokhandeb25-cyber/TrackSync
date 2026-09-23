"""API routes (SPEC §17).

<!-- serves: J2, J4, J5 -->
"""

from __future__ import annotations

import random
import time
from collections import Counter

from fastapi import APIRouter, HTTPException

from backend.api.state import (
    STATE, ensure_interval_index, ensure_plan, ensure_world, new_demand_task, reset,
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
            "scheduled": bool(a),
            "start_s": a.start_s if a else None,
            "day": DAYS[a.day] if a else None,
            "start_hhmm": s_to_hhmm(a.start_s % DAY_S) if a else None,
            "gap_type": a.gap_type if a else None,
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
    res = solve_with_relaxation(w.net, w.tasks, w.windows,
                                time_limit_s=load_config()["planner"]["solve_time_s_demo"])
    STATE.plan = res
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

    results = []
    for t in ordered:
        placement = alns_lite_insert(w.net, t, index, w.tasks, STATE.live_sim)
        STATE.log(
            at_s,
            f"Simulated arrival: {t.describe()} — {placement.reason}.",
            "plan" if placement.placed else "info",
        )
        results.append({
            "task": {"id": t.id, "describe": t.describe(), "zone": t.zone.ref,
                     "department": t.department.value, "duration_min": t.duration_min,
                     "priority": t.priority},
            "placed": placement.placed,
            "window": (None if placement.window is None else {
                "id": placement.window.id, "section_id": placement.window.section_id,
                "zone_ref": placement.window.zone_ref,
                "start_s": placement.window.start_s,
                "end_s": placement.window.start_s + t.duration_min * 60,
                "gap_type": placement.window.gap_type.value,
            }),
            "reason": placement.reason,
        })
    return {"at_s": at_s, "results": results,
            "algorithm": "Max-to-Min greedy ordering + ALNS-lite destroy/repair insertion"}


@router.get("/api/sections/{section_id}/brief")
def section_brief(section_id: str) -> dict:
    """Plain-language summary + next available gap, for the Operations map's click panel.

    Uses the interval tree's range query (backend/planner/interval_index.py) to answer "what's
    free here in the next day" — a question the plain per-zone dict index cannot answer without
    scanning every window.
    """
    w = ensure_world()
    sec = w.net.sections.get(section_id)
    if sec is None:
        raise HTTPException(status_code=404, detail="unknown section")
    index = ensure_interval_index()
    status = w.registry.get(section_id)
    at_s = STATE.sim_time_s

    open_tasks = [t for t in w.tasks if t.zone.ref == section_id and not t.completed]
    upcoming = index.free_in(section_id, WorkZoneKind.SECTION, at_s, at_s + 24 * 3600)
    next_gap = upcoming[0] if upcoming else None

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
        "open_task_count": len(open_tasks),
        "next_gap": (None if next_gap is None else {
            "start_hhmm": s_to_hhmm(next_gap.start_s % DAY_S),
            "end_hhmm": s_to_hhmm(next_gap.end_s % DAY_S),
            "gap_type": next_gap.gap_type.value,
            "usable_min": next_gap.usable_min(),
        }),
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
        out.append((o.train_id, o.train_class.value, o.enter_s, o.exit_s, a, b, o.section_id))
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
    for tid, cls, enter, exit_, a, b, sid in segs:
        if enter <= at_s < exit_:
            f = (at_s - enter) / max(1, exit_ - enter)
            active.append({
                "id": tid, "cls": cls, "section": sid,
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
    a = chat_answer(str(payload.get("q", "")), w, STATE.plan)
    return a.to_dict()


@router.get("/api/metrics/impact")
def impact() -> dict:
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

    policy, note = load_best_policy()
    rep = compute_impact(w.net, w.tasks, w.windows, plan, policy)
    d = rep.to_dict()
    # Which dispatcher produced the latency figure is part of the claim, not a footnote.
    d["dispatcher"] = note
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
