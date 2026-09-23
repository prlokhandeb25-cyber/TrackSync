"""Sudden tasks: inject, dynamically re-plan, and prove it.

<!-- serves: J1, J5 -->

    POST /api/sudden/inject     a job that was never in the planned pool, priority low..critical
    GET  /api/sudden/log        what was injected, where it went, what it displaced
    GET  /api/sudden/metrics    measured response time, deadline hit-rate, quiet-site check
    POST /api/sudden/clear      forget the injected jobs (the planned week is untouched)
    GET  /api/pax/experiment    the passenger-aware scheduler against the same one with that switched off
    GET  /api/pax/hours         a section's trains and passengers hour by hour

The algorithm is `backend/planner/sudden.py`; this file is the wiring and the bookkeeping.
"""

from __future__ import annotations

import random
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.api.routes import DAY_S, DAYS
from backend.api.state import (
    STATE, ensure_interval_index, ensure_plan, ensure_world, get_pax, make_creator,
    occupancy_by_section, week_by_id,
)
from backend.config import load_config
from backend.data.synth_tasks import _candidate_zones, generate_demand_task
from backend.domain.compatibility import check_allotment
from backend.domain.models import WorkZoneKind, s_to_hhmm
from backend.domain.task import (
    TASK_TYPES, Department, Task, TaskCategory, WorkZone,
)
from backend.planner.active_reroute import plan_block_reroutes
from backend.planner.live_sim import LiveSimState, alns_lite_insert
from backend.planner.sudden import LEVEL_NAME, LEVELS, due_hours, place_sudden

router = APIRouter()


class SuddenReq(BaseModel):
    level: str = "high"              # low | medium | high | critical
    zone_ref: str | None = None      # a section or station; random when omitted
    department: str | None = None    # random when omitted
    duration_min: int | None = None
    description: str = ""
    at_s: int = 0


def _hh(s: int) -> str:
    return s_to_hhmm(s % DAY_S)


def _make_task(net, rng: random.Random, p: SuddenReq, priority: int, tid: str) -> Task:
    at = p.at_s
    dept = None
    if p.department:
        try:
            dept = Department(p.department)
        except ValueError:
            raise HTTPException(status_code=422, detail="unknown department")
    zone = None
    if p.zone_ref:
        if p.zone_ref in net.sections:
            zone = WorkZone(kind=WorkZoneKind.SECTION, ref=p.zone_ref)
        elif p.zone_ref in net.stations:
            zone = WorkZone(kind=WorkZoneKind.STATION_NODE, ref=p.zone_ref)
        else:
            raise HTTPException(status_code=422, detail="unknown section or station")

    if dept is None:
        base = generate_demand_task(net, rng, at, zone=zone, tid=tid)
        tt = next(t for t in TASK_TYPES if t.code == base.task_type)
        dur = base.duration_min
        zone = base.zone
        if zone.kind is WorkZoneKind.STATION_NODE and not p.zone_ref:
            zone = rng.choice([z for z in _candidate_zones(net, tt) if z.kind is WorkZoneKind.SECTION]
                              or [zone])
    else:
        tt = rng.choice([t for t in TASK_TYPES if t.department is dept and t.min_duration_min <= 90]
                        or [t for t in TASK_TYPES if t.department is dept])
        zone = zone or rng.choice([z for z in _candidate_zones(net, tt) if z.kind is WorkZoneKind.SECTION]
                                  or _candidate_zones(net, tt))
        dur = rng.randint(tt.min_duration_min, min(tt.max_duration_min, 90))
    if p.duration_min:
        dur = max(10, min(240, int(p.duration_min)))
    return Task(
        id=tid, task_type=tt.code, department=tt.department, zone=zone, duration_min=dur,
        priority=priority, category=TaskCategory.DEMAND,
        requires_power_block=tt.requires_power_block, requires_traffic_block=tt.requires_traffic_block,
        released_s=at, due_by_s=at + due_hours(priority) * 3600, source="SUDDEN",
        description=p.description.strip()[:200],
    )


def _committed(w) -> list[Task]:
    """Everything already booked, whatever its origin: planned, user-raised, simulated."""
    return list(w.tasks) + [x.task for x in STATE.live_sim.placed if x.placed]


def _apply_moves(res, at_s: int, sudden_id: str) -> list[dict]:
    """Write the displaced jobs' new slots back into the live schedule, and describe them."""
    out = []
    for mv in res.moves:
        b, tid = mv.task, mv.task.id
        new = mv.new
        if tid.startswith("SIM-"):
            STATE.live_sim.placed = [x for x in STATE.live_sim.placed if x.task.id != tid]
            if new is not None:
                STATE.live_sim.add(new)
        elif tid.startswith("U-"):
            if new is not None:
                STATE.user_placements[tid] = new
            else:
                STATE.user_placements.pop(tid, None)
                STATE.user_unplaced[tid] = f"deferred by sudden task {sudden_id}"
        elif tid.startswith("SUD-"):
            STATE.sudden_state.placed = [x for x in STATE.sudden_state.placed if x.task.id != tid]
            if new is not None:
                STATE.sudden_state.add(new)
        else:
            STATE.overrides[tid] = None if new is None else {
                "start_s": new.start_s, "end_s": new.end_s, "zone_ref": new.window.zone_ref,
                "section_id": new.window.section_id, "track": new.window.track,
                "gap_type": new.window.gap_type.value, "by": sudden_id}
        out.append({
            "task_id": tid, "label": b.label, "department": b.department.value, "priority": b.priority,
            "zone": b.zone.ref,
            "from": {"start_s": mv.old["start_s"], "end_s": mv.old["end_s"],
                     "hhmm": f"{DAYS[(mv.old['start_s'] // DAY_S) % 7]} {_hh(mv.old['start_s'])}"},
            "to": None if new is None else {
                "start_s": new.start_s, "end_s": new.end_s,
                "hhmm": f"{DAYS[(new.start_s // DAY_S) % 7]} {_hh(new.start_s)}"},
        })
    return out


@router.post("/api/sudden/inject")
def inject(p: SuddenReq) -> dict:
    """A job nobody planned. Place it now, adjusting the live schedule if it has to."""
    w = ensure_world()
    ensure_plan()
    net = w.net
    pax = get_pax()
    priority = LEVELS.get(p.level.lower())
    if priority is None:
        raise HTTPException(status_code=422, detail="level must be low, medium, high or critical")

    STATE.sudden_seq += 1
    tid = f"SUD-{STATE.sudden_seq:04d}"
    rng = random.Random(int(load_config()["seed"]) + 7919 * STATE.sudden_seq)
    task = _make_task(net, rng, p, priority, tid)

    rejection = check_allotment(net, task)
    if rejection is not None:
        entry = _entry(task, p, None, "none", [], 0.0, [], rejection.reason, pax)
        entry["steps"] = [rejection.reason]
        STATE.sudden_log.append(entry)
        return entry

    def movable(b: Task) -> bool:
        # work already under way cannot be pushed aside
        return not (b.scheduled_start_s is not None and b.scheduled_start_s <= p.at_s < (b.scheduled_end_s or 0))

    res = place_sudden(net, task, ensure_interval_index(), _committed(w), STATE.sudden_state,
                       make_creator(), p.at_s, pax, movable)
    moves = _apply_moves(res, p.at_s, tid)
    entry = _entry(task, p, res.placement, res.method, moves, res.response_ms, res.steps,
                   "" if res.placement else "no window before the deadline, even after "
                   "opening gaps or moving lower-priority work", pax)
    STATE.sudden_log.append(entry)
    del STATE.sudden_log[:-200]
    where = f"{entry['window']['section_id']} at {entry['window']['hhmm']}" if entry["window"] else "nowhere yet"
    STATE.log(p.at_s, (f"SUDDEN {entry['level'].upper()}: {task.describe()} - {where}"
                       + (f"; pushed {len(moves)} lower-priority job(s) aside" if moves else "")
                       + f" ({entry['response_ms']:.0f} ms)."), "demand")
    return entry


def _entry(task: Task, p: SuddenReq, place, method: str, moves: list[dict], ms: float,
           steps: list[str], reason: str, pax) -> dict:
    net = ensure_world().net
    win = None
    reroutes = None
    margin = None
    if place is not None and place.window is not None:
        w = place.window
        win = {"section_id": w.section_id, "zone_ref": w.zone_ref, "track": w.track,
               "start_s": place.start_s, "end_s": place.end_s, "gap_type": w.gap_type.value,
               "hhmm": f"{DAYS[(place.start_s // DAY_S) % 7]} {_hh(place.start_s)}-{_hh(place.end_s)}",
               "created_by": w.created_by}
        margin = round(((task.due_by_s or 0) - place.end_s) / 60)
        sec = net.sections.get(w.zone_ref)
        if sec is not None:
            b = plan_block_reroutes(net, week_by_id(), occupancy_by_section().get(sec.id, []), sec,
                                    place.start_s, place.end_s)
            reroutes = {"diverted": len(b.reroutes),
                        "added_delay_min": round(sum(r["added_delay_min"] for r in b.reroutes), 1),
                        "trains": [{"id": r["train_name"] or r["train_id"], "delay": r["added_delay_min"]}
                                   for r in b.reroutes],
                        "locals": b.locals_in_window,
                        "track_swap": b.track_swap}
    moves_out = moves
    return {
        "id": task.id, "priority": task.priority, "level": LEVEL_NAME.get(task.priority, "Medium"),
        "task": {"label": task.label, "department": task.department.value, "zone": task.zone.ref,
                 "duration_min": task.duration_min, "describe": task.describe()},
        "at_s": p.at_s, "placed": place is not None and place.placed, "method": method,
        "window": win, "response_ms": round(ms, 1),
        "deadline_s": task.due_by_s, "deadline_hhmm": (f"{DAYS[(task.due_by_s // DAY_S) % 7]} {_hh(task.due_by_s)}"
                                                        if task.due_by_s else None),
        "margin_min": margin, "exposure": None if place is None else place.exposure,
        "created": None if place is None or place.created is None else place.created.to_dict(),
        "bumped": moves_out, "reroutes": reroutes, "steps": steps, "reason": reason,
        "plan_resolve_s": round(STATE.plan.wall_s, 1) if STATE.plan else None,
        "network_tph": round(pax.network_mean_tph(), 1),
    }


@router.get("/api/sudden/log")
def sudden_log() -> dict:
    return {"log": STATE.sudden_log[-30:][::-1], "n": len(STATE.sudden_log)}


@router.get("/api/sudden/metrics")
def sudden_metrics() -> dict:
    log = STATE.sudden_log
    plan = STATE.plan
    n = len(log)
    if not n:
        return {"n": 0}
    placed = [e for e in log if e["placed"]]
    by_level: dict[str, dict] = {}
    for e in log:
        d = by_level.setdefault(e["level"], {"n": 0, "placed": 0})
        d["n"] += 1
        d["placed"] += 1 if e["placed"] else 0
    ms = sorted(e["response_ms"] for e in log)
    tph = [e["exposure"]["trains_per_hour"] for e in placed if e.get("exposure")]
    net_tph = log[-1]["network_tph"]
    resolve_ms = (plan.wall_s * 1000) if plan else None
    return {
        "n": n, "placed": len(placed),
        "in_time": sum(1 for e in placed if (e["margin_min"] or 0) >= 0),
        "by_method": {m: sum(1 for e in log if e["method"] == m)
                      for m in ("gap", "created", "bumped", "late", "none")},
        "by_level": by_level,
        "median_ms": round(ms[len(ms) // 2], 1), "max_ms": round(ms[-1], 1),
        "plan_resolve_ms": None if resolve_ms is None else round(resolve_ms),
        "speedup_x": None if not resolve_ms else round(resolve_ms / max(0.01, ms[len(ms) // 2])),
        "bumped_total": sum(len(e["bumped"]) for e in log),
        "replaced_total": sum(1 for e in log for b in e["bumped"] if b["to"]),
        "deferred_total": sum(1 for e in log for b in e["bumped"] if not b["to"]),
        "trains_diverted": sum((e["reroutes"] or {}).get("diverted", 0) for e in placed),
        "pax_within_reach": sum(e["exposure"]["passengers"] for e in placed if e.get("exposure")),
        "site_tph": round(sum(tph) / len(tph), 1) if tph else None,
        "network_tph": net_tph,
        "created_delay_train_min": round(sum((e["created"] or {}).get("delay_min", 0) for e in placed), 1),
        "manual_wait_days": float(load_config().get_path("metrics.manual_replan_wait_days", 7)),
    }


@router.post("/api/sudden/clear")
def sudden_clear() -> dict:
    n = len(STATE.sudden_log)
    STATE.sudden_state = LiveSimState()
    STATE.sudden_log = []
    STATE.overrides = {}
    return {"cleared": n}


# ------------------------------------------------------------------ the passenger-aware scheduler

_PAX_EXP: dict | None = None


@router.get("/api/pax/experiment")
def pax_experiment() -> dict:
    """The same jobs placed twice on the same schedule: once counting passengers, once not.

    60 unplanned jobs are released at random moments of the week, each due within a day. Each is
    placed independently (nothing is kept) with the passenger term on and then off. Both runs are
    then scored the same way, by the trains and passengers within reach of the slot they chose.
    """
    global _PAX_EXP
    if _PAX_EXP is not None:
        return _PAX_EXP
    w = ensure_world()
    ensure_plan()
    pax, index, committed = get_pax(), ensure_interval_index(), _committed(w)
    rng = random.Random(int(load_config()["seed"]) + 31)
    jobs = []
    for i in range(60):
        at = rng.randint(0, 6 * DAY_S)
        jobs.append(generate_demand_task(w.net, rng, at, tid=f"PX-{i:03d}"))

    from backend.gaps.engine import GapType
    from backend.planner.interval_index import build_interval_index
    night_only = build_interval_index([x for x in w.windows
                                       if x.gap_type in (GapType.NIGHT_WINDOW, GapType.MEGABLOCK)])

    def run(use_pax: bool, idx=index) -> dict:
        placed = passengers = 0
        tph, wait_h, peak = [], [], 0
        for j in jobs:
            t = j.model_copy(deep=True)
            p = alns_lite_insert(w.net, t, idx, committed, LiveSimState(), creator=None,
                                 at_s=t.released_s, pax=pax if use_pax else None, commit=False)
            if not p.placed or p.window is None:
                continue
            e = pax.exposure(p.window.section_id, p.start_s, p.end_s)
            placed += 1
            passengers += e.passengers
            tph.append(e.trains_per_hour)
            wait_h.append((p.start_s - t.released_s) / 3600)
            hour = (p.start_s % DAY_S) // 3600
            peak += 1 if hour in (7, 8, 9, 10, 17, 18, 19, 20) else 0
        return {"placed": placed, "passengers": passengers,
                "mean_tph": round(sum(tph) / max(1, len(tph)), 1),
                "mean_wait_h": round(sum(wait_h) / max(1, len(wait_h)), 1), "in_peak": peak}

    aware, unaware = run(True), run(False)
    manual = run(False, night_only)      # today's practice: night and Sunday windows only
    red = 100.0 * (unaware["passengers"] - aware["passengers"]) / max(1, unaware["passengers"])
    _PAX_EXP = {"jobs": len(jobs), "aware": aware, "unaware": unaware, "manual": manual,
                "passengers_saved_pct": round(red, 1),
                "network_tph": round(pax.network_mean_tph(), 1),
                "how": "Same 60 jobs, same schedule, same rules. Aware vs unaware differ only in the passenger term; manual uses night and Sunday windows only. "
                       "Scored by passengers on services within 30 min of the chosen slot (estimated, A-040)."}
    return _PAX_EXP


@router.get("/api/pax/hours")
def pax_hours(section: str, day: int = 1) -> dict:
    w = ensure_world()
    if section not in w.net.sections:
        raise HTTPException(status_code=404, detail="unknown section")
    return {"section": section, "day": day, "hours": get_pax().hour_profile(section, day)}


# ------------------------------------------------- the weekly plan, with and without the passenger term

_WEEKLY: dict = {"status": "idle", "data": None, "error": None}
_WEEKLY_LOCK = __import__("threading").Lock()


def _weekly_worker() -> None:
    from backend.planner.cpsat import solve_with_relaxation
    try:
        w = ensure_world()
        plan = ensure_plan()
        pax = get_pax()
        tasks = [t.model_copy(deep=True) for t in w.tasks]          # the solver writes times onto its tasks
        for t in tasks:
            t.scheduled_start_s = t.scheduled_end_s = None
        res = solve_with_relaxation(w.net, tasks, w.windows,
                                    time_limit_s=load_config()["planner"]["solve_time_s_demo"], pax=None)
        unaware = sum(pax.job_exposure(a.section_id, a.start_s, a.end_s) for a in res.assignments)
        aware = sum(pax.job_exposure(a.section_id, a.start_s, a.end_s)
                    for a in plan.assignments if a.window_id and not a.window_id.startswith("CW-"))
        # like for like: only the jobs the natural (uncreated) part of each plan placed
        nat_ids = {a.task_id for a in plan.assignments if a.window_id and not a.window_id.startswith("CW-")}
        common = nat_ids & {a.task_id for a in res.assignments}
        aw_c = sum(pax.job_exposure(a.section_id, a.start_s, a.end_s) for a in plan.assignments if a.task_id in common)
        un_c = sum(pax.job_exposure(a.section_id, a.start_s, a.end_s) for a in res.assignments if a.task_id in common)
        with _WEEKLY_LOCK:
            _WEEKLY.update(status="done", data={
                "aware": {"placed": len(plan.assignments), "pax": aware, "status": plan.status},
                "unaware": {"placed": len(res.assignments), "pax": unaware, "status": res.status},
                "common_jobs": len(common), "aware_common": aw_c, "unaware_common": un_c,
                "saved_pct": round(100.0 * (un_c - aw_c) / max(1, un_c), 1),
                "how": "The same week solved twice by CP-SAT, once with the passenger term and once without. "
                       "Compared on the jobs both plans placed, by passenger-hours within reach (estimated, A-040)."})
    except Exception as e:                                        # surfaced to the page, not swallowed
        with _WEEKLY_LOCK:
            _WEEKLY.update(status="error", error=repr(e))


@router.get("/api/pax/weekly")
def pax_weekly() -> dict:
    """Start (once) and report the with/without passenger-term comparison of the weekly plan."""
    with _WEEKLY_LOCK:
        if _WEEKLY["status"] == "idle":
            _WEEKLY["status"] = "running"
            __import__("threading").Thread(target=_weekly_worker, daemon=True).start()
        return dict(_WEEKLY)
