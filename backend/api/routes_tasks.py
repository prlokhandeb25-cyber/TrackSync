"""Routes for the task pipeline, the explainers and the schedules.

<!-- serves: J1, J2, J5 -->

    form -> submit -> compatibility score + cluster -> integrated scheduling into gaps
    explain/*  : the gap engine, the clustering and the scheduler, replayed step by step
    schedule/* : the week and month plans
    creation/* : what gap creation opened, and what it cost
"""

from __future__ import annotations

import random
import threading
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.planner.aging import age_carried
from backend.api.routes import DAY_S, DAYS, _cluster_pool
from backend.api.state import (
    STATE, creation_summary, ensure_interval_index, ensure_plan, ensure_world, make_creator,
    get_pax, occupancy_by_section, reroute_cache, week_by_id,
)
from backend.config import load_config
from backend.domain.compatibility import check_allotment
from backend.domain.models import WorkZoneKind, s_to_hhmm
from backend.domain.scoring import score_tasks
from backend.domain.task import (
    TASK_TYPES, TASK_TYPES_BY_CODE, Department, Task, TaskCategory, WorkZone,
)
from backend.gaps.creation import survey
from backend.gaps.explain import trace_track_day
from backend.planner.clustering import cluster_tasks, cluster_trace
from backend.planner.live_sim import LiveSimState, alns_lite_insert, order_max_to_min

router = APIRouter()


# ------------------------------------------------------------------------------------ the form


@router.get("/api/form/options")
def form_options() -> dict:
    w = ensure_world()
    net = w.net
    return {
        "departments": [{"code": d.value, "label": d.label} for d in Department],
        "task_types": [
            {"code": t.code, "label": t.label, "department": t.department.value,
             "min": t.min_duration_min, "max": t.max_duration_min,
             "power_block": t.requires_power_block}
            for t in TASK_TYPES
        ],
        "sections": [
            {"id": s.id, "label": f"{net.stations[s.from_station].name} - {net.stations[s.to_station].name}",
             "line": s.line_code, "tracks": len(s.tracks), "track_names": list(s.tracks)}
            for s in net.sections.values()
        ],
        "stations": [{"code": st.code, "name": st.name} for st in net.stations.values()],
        "allotments": {d: sorted(v) for d, v in net.allotments.items()},
    }


class SubmitTask(BaseModel):
    description: str = ""
    department: str
    zone_ref: str
    task_type: str | None = None
    duration_min: int = 60
    priority: int = 3
    allows_with: list[str] = []
    at_s: int = 0
    track: str | None = None          # the exact line of the section, or None for any line


def _hhmm_range(a: int, b: int) -> str:
    return f"{s_to_hhmm(a % DAY_S)}-{s_to_hhmm(b % DAY_S)}"


def _pool(include_sim: bool = False) -> list[Task]:
    """Planned and user-raised jobs; simulated arrivals only when asked for."""
    if include_sim:
        return _cluster_pool()
    return [t for t in ensure_world().tasks if not t.completed]


def _task_row(t: Task, scores: dict, cluster_of: dict) -> dict:
    sc = scores.get(t.id)
    place = STATE.user_placements.get(t.id)
    a = next((x for x in STATE.plan.assignments if x.task_id == t.id), None) if STATE.plan else None
    sched = None
    if place is not None and place.placed:
        sched = {"start_s": place.start_s, "end_s": place.end_s, "section_id": place.window.section_id,
                 "track": place.window.track, "gap_type": place.window.gap_type.value,
                 "integrated_with": place.integrated_with,
                 "created": None if place.created is None else place.created.to_dict(),
                 "reason": place.reason, "steps": place.steps}
    elif a is not None:
        sched = {"start_s": a.start_s, "end_s": a.end_s, "section_id": a.section_id,
                 "track": a.track, "gap_type": a.gap_type, "integrated_with": [], "created": None,
                 "reason": "", "steps": []}
    if sched:
        sched["day"] = DAYS[(sched["start_s"] // DAY_S) % 7]
        sched["hhmm"] = _hhmm_range(sched["start_s"], sched["end_s"])
    return {
        "id": t.id, "source": t.source, "department": t.department.value, "label": t.label,
        "description": t.description, "zone": t.zone.ref, "zone_kind": t.zone.kind.value,
        "duration_min": t.duration_min, "priority": t.priority, "track": t.track,
        "allows_with": None if t.allows_with is None else [d.value for d in t.allows_with],
        "score": None if sc is None else sc.to_dict(),
        "cluster": cluster_of.get(t.id),
        "schedule": sched,
        "unplaced_reason": STATE.user_unplaced.get(t.id),
    }


def _scored_pool(include_sim: bool = False) -> tuple[list[Task], list, dict, dict]:
    w = ensure_world()
    pool = _pool(include_sim)
    clusters = cluster_tasks(w.net, pool)
    scores = score_tasks(w.net, pool, clusters)
    cluster_of = {}
    for c in clusters:
        for tid in c.task_ids:
            cluster_of[tid] = {"id": c.id, "label": c.label, "size": len(c.task_ids)}
    return pool, clusters, scores, cluster_of


@router.post("/api/tasks/submit")
def submit_task(p: SubmitTask) -> dict:
    """A department raises a job: score it, group it, and give it a time in the gaps."""
    w = ensure_world()
    net = w.net
    try:
        dept = Department(p.department)
    except ValueError:
        raise HTTPException(status_code=422, detail="unknown department")
    if p.zone_ref in net.sections:
        zone = WorkZone(kind=WorkZoneKind.SECTION, ref=p.zone_ref)
    elif p.zone_ref in net.stations:
        zone = WorkZone(kind=WorkZoneKind.STATION_NODE, ref=p.zone_ref)
    else:
        raise HTTPException(status_code=422, detail="unknown section or station")

    track = (p.track or "").strip() or None
    if track is not None:
        if zone.kind is not WorkZoneKind.SECTION:
            raise HTTPException(status_code=422, detail="a line can only be chosen for work on a section")
        if track not in net.sections[zone.ref].tracks:
            raise HTTPException(status_code=422, detail=f"{zone.ref} has no {track} line (it has {', '.join(net.sections[zone.ref].tracks)})")
    tt = TASK_TYPES_BY_CODE.get(p.task_type or "")
    if tt is None or tt.department is not dept:
        tt = next(t for t in TASK_TYPES if t.department is dept)
    others = {d.value for d in Department} - {dept.value}
    allows = [Department(x) for x in p.allows_with if x in others]

    STATE.user_counter += 1
    tid = f"U-{STATE.user_counter:04d}"
    task = Task(
        id=tid, task_type=tt.code, department=dept, zone=zone,
        duration_min=max(10, min(720, int(p.duration_min))), priority=max(1, min(5, int(p.priority))),
        category=TaskCategory.DEMAND, requires_power_block=tt.requires_power_block,
        requires_traffic_block=tt.requires_traffic_block, released_s=p.at_s,
        due_by_s=p.at_s + {1: 6, 2: 24, 3: 72}.get(max(1, min(5, int(p.priority))), 168) * 3600,
        source="USER", description=p.description.strip()[:200],
        allows_with=allows, track=track,
    )
    w.tasks.append(task)

    t0 = time.perf_counter()
    rejection = check_allotment(net, task)
    placement = None
    if rejection is not None:
        STATE.user_unplaced[tid] = rejection.reason
    else:
        committed = [t for t in w.tasks if t.id != tid] + [
            x.task for x in STATE.live_sim.placed if x.placed]
        placement = alns_lite_insert(net, task, ensure_interval_index(), committed,
                                     LiveSimState(), creator=make_creator(), at_s=p.at_s)
        if placement.placed:
            STATE.user_placements[tid] = placement
        else:
            STATE.user_unplaced[tid] = placement.reason
    sched_ms = (time.perf_counter() - t0) * 1000

    pool, clusters, scores, cluster_of = _scored_pool()
    row = _task_row(task, scores, cluster_of)
    sc = scores.get(tid)
    cl = next((c for c in clusters if tid in c.task_ids), None)

    where = cluster_of[tid]["label"] if tid in cluster_of else "its area"
    if placement is not None and placement.placed:
        msg = (f"You added: {task.describe()}. Score {sc.score if sc else '-'}, grouped with "
               f"{(cl and len(cl.task_ids) - 1) or 0} nearby job(s) around {where}; {placement.reason}.")
    else:
        msg = f"You added: {task.describe()}. Could not schedule it: {STATE.user_unplaced.get(tid)}."
    STATE.log(p.at_s, msg, "demand")

    return {
        "task": row,
        "cluster": None if cl is None else cl.to_dict(),
        "scheduling_ms": round(sched_ms, 1),
        "rejected_by_allotment": rejection is not None,
        "pool": {"n_tasks": len(pool), "n_clusters": len(clusters)},
    }


@router.post("/api/tasks/user/clear")
def clear_user_tasks() -> dict:
    w = ensure_world()
    ids = {t.id for t in w.tasks if t.source == "USER"}
    w.tasks[:] = [t for t in w.tasks if t.id not in ids]
    for i in ids:
        STATE.user_placements.pop(i, None)
        STATE.user_unplaced.pop(i, None)
    return {"removed": len(ids)}


@router.get("/api/tasks/scores")
def task_scores(include_sim: bool = False) -> dict:
    """Every job with its compatibility score, cluster and schedule."""
    pool, clusters, scores, cluster_of = _scored_pool(include_sim)
    rows = [_task_row(t, scores, cluster_of) for t in pool]
    # newest user jobs first, then lowest score first: the ones needing attention lead
    rows.sort(key=lambda r: (r["source"] != "USER", -int(r["id"].split("-")[-1]) if r["source"] == "USER"
                             else (r["score"]["score"] if r["score"] else 100)))
    real = [r for r in rows if r["score"]]
    return {
        "tasks": rows,
        "clusters": [c.to_dict() for c in clusters],
        "summary": {
            "n_tasks": len(rows), "n_clusters": len(clusters),
            "mean_score": round(sum(r["score"]["score"] for r in real) / max(1, len(real))),
            "n_user": sum(1 for r in rows if r["source"] == "USER"),
            "n_shared": sum(1 for c in clusters if len(c.task_ids) > 1),
        },
    }


# ------------------------------------------------------------------------------- the explainers


def _default_track(section) -> str:
    slow = [t for t in section.tracks if t.endswith("_SLOW")]
    return (slow or section.tracks)[0]


_BEST_VIEW: dict[int, tuple[str, str, float]] = {}


def _best_view(day: int) -> tuple[str, str, float]:
    """A section, track and 4-hour window that shows kept gaps AND near misses (an instructive
    view), found by scanning candidates with the same trace the explainer uses."""
    if day in _BEST_VIEW:
        return _BEST_VIEW[day]
    w = ensure_world()
    occ_by, rc = occupancy_by_section(), reroute_cache()
    first = next(iter(w.net.sections.values()))
    best, best_score = (first.id, _default_track(first), 5.0), -1     # fallback: the first section, not a named one
    for sec in list(w.net.sections.values())[:40]:
        track = _default_track(sec)
        occ = occ_by.get(sec.id, [])
        for start in range(0, 22, 3):
            t = trace_track_day(sec, track, day, occ, [], rc, start, start + 4)
            if len(t["rows"]) < 6:
                continue
            score = min(t["kept"], 4) * 3 + min(t["near_misses"], 4) * 2 + min(len(t["rows"]), 10)
            if t["kept"] and t["near_misses"] and score > best_score:
                best, best_score = (sec.id, track, float(start)), score
    _BEST_VIEW[day] = best
    return best


@router.get("/api/explain/gaps")
def explain_gaps(section: str = "", track: str = "", day: int = 1,
                 hour_from: float | None = None, hour_to: float | None = None) -> dict:
    """The gap engine on one track for a few hours: every train, every gap, keep or drop and why."""
    w = ensure_world()
    day = max(0, min(6, day))
    if not section:
        section, track, start = _best_view(day)
        hour_from, hour_to = start, start + 4
    sec = w.net.sections.get(section)
    if sec is None:
        raise HTTPException(status_code=404, detail="unknown section")
    track = track if track in sec.tracks else _default_track(sec)
    if hour_from is None:
        hour_from, hour_to = 5.0, 9.0
    out = trace_track_day(sec, track, day, occupancy_by_section().get(section, []), w.windows,
                          reroute_cache(), hour_from, hour_to if hour_to is not None else hour_from + 4)
    out["choices"] = [{"id": s.id, "tracks": s.tracks,
                       "label": f"{w.net.stations[s.from_station].name} - {w.net.stations[s.to_station].name}"}
                      for s in w.net.sections.values()]
    return out


@router.get("/api/explain/clusters")
def explain_clusters(include_sim: bool = False) -> dict:
    """The clustering run: every job's position, the merge history and where the cut falls."""
    w = ensure_world()
    pool, clusters, scores, cluster_of = _scored_pool(include_sim)
    trace = cluster_trace(w.net, pool)
    label_of = {c.id: c.label for c in clusters}
    return {
        **trace,
        "clusters": [c.to_dict() for c in clusters],
        "scores": {tid: s.score for tid, s in scores.items()},
        "cluster_labels": label_of,
        "stations": [{"code": st.code, "name": st.name, "lat": st.lat, "lon": st.lon}
                     for st in w.net.stations.values()],
    }


@router.get("/api/explain/schedule")
def explain_schedule() -> dict:
    """A dry run of the scheduler on a few clustered jobs, with its reasoning in plain words.

    Copies of real jobs are placed on an empty scratch state, so what is shown is exactly what the
    live scheduler does - longest job first, into the best gap, alongside a neighbour where the
    rules allow, opening a gap when none fits - without disturbing the real plan.
    """
    w = ensure_world()
    pool, clusters, _, _ = _scored_pool(include_sim=True)   # enough short jobs to make a story
    big = [c for c in clusters if len(c.task_ids) >= 2][:3]
    by_id = {t.id: t for t in pool}
    ok = lambda t: t.zone.kind is WorkZoneKind.SECTION   # noqa: E731
    ids = [tid for c in big for tid in c.task_ids if ok(by_id[tid])][:7]
    ids = ids or [t.id for t in pool if ok(t)][:6]
    base = DAY_S + 8 * 3600     # the morning peak: gaps are scarce, so urgent jobs need help
    demo = []
    for k, tid in enumerate(ids):
        t = by_id[tid].model_copy(update={
            "id": f"DEMO-{k + 1}", "scheduled_start_s": None, "scheduled_end_s": None,
            "window_id": None, "gap_type": None, "released_s": base, "source": "SIM",
            "priority": 1, "due_by_s": base + 6 * 3600,
            "duration_min": min(by_id[tid].duration_min, 120)})
        demo.append((tid, t))
    ordered = order_max_to_min([t for _, t in demo])
    origin = {t.id: tid for tid, t in demo}

    state = LiveSimState()
    creator = make_creator()
    index = ensure_interval_index()
    out = []
    for t in ordered:
        p = alns_lite_insert(w.net, t, index, [], state, creator=creator, at_s=base)
        out.append({
            "id": t.id, "from_task": origin[t.id],
            "shortened_from": (by_id[origin[t.id]].duration_min
                               if by_id[origin[t.id]].duration_min > t.duration_min else None),
            "department": t.department.value,
            "label": t.label, "zone": t.zone.ref, "duration_min": t.duration_min,
            "placed": p.placed, "start_s": p.start_s, "end_s": p.end_s,
            "hhmm": _hhmm_range(p.start_s, p.end_s) if p.placed else None,
            "section_id": p.window.section_id if p.window else None,
            "track": p.window.track if p.window else None,
            "gap_type": p.window.gap_type.value if p.window else None,
            "integrated_with": p.integrated_with,
            "created": None if p.created is None else p.created.to_dict(),
            "reason": p.reason, "steps": p.steps,
        })
    return {"order": [t.id for t in ordered], "results": out,
            "clusters_used": [c.id for c in big]}


# ------------------------------------------------------------------------------ gap creation


_SURVEY: dict | None = None
_EXPERIMENT: dict | None = None


@router.get("/api/creation/experiment")
def creation_experiment() -> dict:
    """Measured, not asserted: sixty urgent jobs, each due within six hours, scheduled once using
    only the gaps the timetable has and once with gap creation allowed. Same jobs, same order."""
    global _EXPERIMENT
    if _EXPERIMENT is not None:
        return _EXPERIMENT
    from backend.data.synth_tasks import generate_tasks
    from backend.domain.fsm import StatusRegistry

    w = ensure_world()
    seed = int(load_config()["seed"]) + 7
    rng = random.Random(seed)
    base = generate_tasks(w.net, 90, rng, registry=StatusRegistry(), id_prefix="EX")
    jobs = []
    for t in base:
        if t.zone.kind is not WorkZoneKind.SECTION:
            continue
        start = DAY_S + rng.randint(6, 20) * 3600
        jobs.append(t.model_copy(update={
            "duration_min": rng.randint(40, 100), "priority": 1, "released_s": start,
            "due_by_s": start + 6 * 3600, "source": "SIM"}))
        if len(jobs) == 60:
            break

    def run(creator):
        st = LiveSimState()
        idx = ensure_interval_index()
        out = []
        for t in order_max_to_min([j.model_copy(deep=True) for j in jobs]):
            out.append(alns_lite_insert(w.net, t, idx, [], st, creator=creator, at_s=t.released_s))
        return out

    a = run(None)
    b = run(make_creator())
    made = [p for p in b if p.placed and p.created is not None]
    _EXPERIMENT = {
        "jobs": len(jobs), "due_within_h": 6,
        "natural_placed": sum(1 for p in a if p.placed),
        "with_creation_placed": sum(1 for p in b if p.placed),
        "created_gaps_used": len(made),
        "by_lever": {k: sum(1 for p in made if p.created.lever == k)
                     for k in ("RETIME", "REROUTE", "SINGLE_LINE")},
        "delay_train_min": round(sum(p.created.delay_min for p in made), 1),
        "trains_held_or_rerouted": sum(len(p.created.trains) for p in made),
    }
    return _EXPERIMENT


@router.get("/api/creation/summary")
def creation_summary_route() -> dict:
    """What gap creation could open across the whole timetable, and what the weekly plan used."""
    global _SURVEY
    w = ensure_world()
    plan = ensure_plan()
    if _SURVEY is None:
        _SURVEY = survey(w.net, occupancy_by_section(), reroute_cache())
    nat = STATE.plan_natural
    return {
        "survey": _SURVEY,
        "min_workable_min": int(load_config()["gaps"]["min_workable_min"]),
        "weekly": {
            "natural_placed": len(nat.assignments) if nat else len(plan.assignments),
            "final_placed": len(plan.assignments),
            "n_tasks": plan.n_tasks,
            "used": STATE.creation_used,
        },
    }


# --------------------------------------------------------------------------- week and month


def _entries(res, by_id: dict, cluster_of: dict, offset_s: int = 0, tag: str = "") -> list[dict]:
    out = []
    for a in res.assignments:
        t = by_id.get(a.task_id)
        if t is None:
            continue
        out.append({
            "task_id": a.task_id, "label": t.label, "description": t.description,
            "department": t.department.value, "zone": a.zone_ref, "section_id": a.section_id,
            "track": a.track, "start_s": a.start_s + offset_s, "end_s": a.end_s + offset_s,
            "gap_type": a.gap_type, "source": t.source, "priority": t.priority,
            "cluster": (cluster_of.get(a.task_id) or {}).get("id"),
            "created": bool(a.window_id and a.window_id.startswith("CW-")), "tag": tag,
        })
    return sorted(out, key=lambda e: e["start_s"])


_DAILY_LOCK = threading.Lock()


def ensure_dayfill() -> dict:
    """Book each day's routine jobs from 04:00 on, once, against everything already booked."""
    from backend.planner.dayfill import fill_days
    w = ensure_world()
    plan = ensure_plan()
    with _DAILY_LOCK:
        if STATE.daily_summary:
            return STATE.daily_summary
        committed = list(w.tasks) + [x.task for x in STATE.live_sim.placed if x.placed]
        STATE.daily_state = LiveSimState()
        STATE.daily_summary = fill_days(w.net, ensure_interval_index(), committed, get_pax(), STATE.daily_state,
                                        int(load_config()["seed"]))
        return STATE.daily_summary


@router.get("/api/schedule/week")
def schedule_week() -> dict:
    """This week's plan: what was placed where, and what gap creation contributed."""
    w = ensure_world()
    plan = ensure_plan()
    daily = ensure_dayfill()
    pool, clusters, scores, cluster_of = _scored_pool()
    by_id = {t.id: t for t in w.tasks}
    entries = _entries(plan, by_id, cluster_of)
    # jobs a sudden task pushed aside: show their NEW slot (or none, if deferred)
    moved = []
    for e in entries:
        if e["task_id"] in STATE.overrides:
            o = STATE.overrides[e["task_id"]]
            if o:
                moved.append({**e, "start_s": o["start_s"], "end_s": o["end_s"], "section_id": o["section_id"],
                              "zone": o["zone_ref"], "track": o["track"], "gap_type": o["gap_type"],
                              "tag": "moved"})
    entries = [e for e in entries if e["task_id"] not in STATE.overrides] + moved
    placed_ids = {e["task_id"] for e in entries}

    # jobs raised by a user are scheduled live, not by the weekly solve: show them in the week too
    for tid, p in STATE.user_placements.items():
        if tid not in placed_ids and p.placed:
            t = by_id.get(tid)
            if t is None:
                continue
            entries.append({
                "task_id": tid, "label": t.label, "description": t.description,
                "department": t.department.value, "zone": t.zone.ref, "section_id": p.window.section_id,
                "track": p.window.track, "start_s": p.start_s, "end_s": p.end_s,
                "gap_type": p.window.gap_type.value, "source": "USER", "priority": t.priority,
                "cluster": (cluster_of.get(tid) or {}).get("id"),
                "created": bool(p.created), "tag": "",
            })
            placed_ids.add(tid)
    # sudden tasks were never in the planned pool; they are booked live, and belong in the week too
    for sp in STATE.sudden_state.placed:
        if sp.placed and sp.task.id not in placed_ids:
            t = sp.task
            entries.append({
                "task_id": t.id, "label": t.label, "description": t.description,
                "department": t.department.value, "zone": t.zone.ref, "section_id": sp.window.section_id,
                "track": sp.window.track, "start_s": sp.start_s, "end_s": sp.end_s,
                "gap_type": sp.window.gap_type.value, "source": "SUDDEN", "priority": t.priority,
                "cluster": None, "created": bool(sp.created), "tag": "sudden",
            })
            placed_ids.add(t.id)
    # routine daily jobs (04:00 onward) are booked live alongside the planned ones
    for dp in STATE.daily_state.placed:
        if dp.placed and dp.task.id not in placed_ids:
            t = dp.task
            entries.append({
                "task_id": t.id, "label": t.label, "description": t.description,
                "department": t.department.value, "zone": t.zone.ref, "section_id": dp.window.section_id,
                "track": dp.window.track, "start_s": dp.start_s, "end_s": dp.end_s,
                "gap_type": dp.window.gap_type.value, "source": "DAILY", "priority": t.priority,
                "cluster": None, "created": False, "tag": "daily",
            })
            placed_ids.add(t.id)
    entries.sort(key=lambda e: e["start_s"])

    unplaced = [{"task_id": t.id, "label": t.label, "department": t.department.value,
                 "zone": t.zone.ref, "duration_min": t.duration_min,
                 "reason": STATE.user_unplaced.get(t.id, "pushed aside by a sudden task, no slot left"
                                  if t.id in STATE.overrides else "no window long enough this week")}
                for t in w.tasks if t.id not in placed_ids]
    nat = STATE.plan_natural
    planned_e = [e for e in entries if e["source"] not in ("DAILY", "SUDDEN", "USER")]
    hour = lambda e: (e["start_s"] % DAY_S) // 3600   # noqa: E731
    by_day = {DAYS[i]: sum(1 for e in entries if (e["start_s"] // DAY_S) % 7 == i) for i in range(7)}
    return {
        "entries": entries, "unplaced": unplaced, "by_day": by_day,
        "summary": {
            "n_tasks": len(w.tasks), "placed": len(entries), "unplaced": len(unplaced),
            "micro_gap": sum(1 for e in entries if e["gap_type"] == "MICRO_GAP"),
            "night": sum(1 for e in entries if e["gap_type"] == "NIGHT_WINDOW"),
            "megablock": sum(1 for e in entries if e["gap_type"] == "MEGABLOCK"),
            "from_created_gaps": sum(1 for e in entries if e["created"]),
            "natural_only_placed": len(nat.assignments) if nat else len(plan.assignments),
            "plan_placed": len(plan.assignments),
            "solver": plan.status, "gap_pct": plan.gap_pct, "wall_s": round(plan.wall_s, 1),
            "planned_in_small_hours": sum(1 for e in planned_e if hour(e) < 4), "planned_total": len(planned_e),
            "daily_placed": daily["placed"], "daily_unplaced": daily["unplaced"], "daily_from_hour": daily["from_hour"],
            "daily_per_day": daily["per_day"],
        },
    }


_MONTH: dict = {"status": "idle", "progress": 0, "weeks": [], "error": None, "started": None}
_MONTH_LOCK = threading.Lock()


def _build_month() -> None:
    from backend.data.synth_tasks import generate_tasks
    from backend.domain.fsm import StatusRegistry
    from backend.planner.creation_plan import solve_with_creation

    try:
        w = ensure_world()
        plan = ensure_plan()
        pool, clusters, scores, cluster_of = _scored_pool()
        by_id = {t.id: t for t in w.tasks}
        weeks: list[dict] = []
        waited: dict[str, int] = {}          # weeks each job has been carried over, for priority aging
        aged_from: dict[str, int] = {}

        e0 = _entries(plan, by_id, cluster_of, 0, "W1")
        carried = [t.model_copy(deep=True) for t in w.tasks if t.id not in {e["task_id"] for e in e0}]
        weeks.append({"week": 1, "entries": e0, "n_tasks": len(w.tasks), "placed": len(e0),
                      "carried_in": 0, "carried_out": len(carried),
                      "micro_gap": sum(1 for e in e0 if e["gap_type"] == "MICRO_GAP"),
                      "created": sum(1 for e in e0 if e["created"])})
        with _MONTH_LOCK:
            _MONTH.update(weeks=list(weeks), progress=1)

        seed = int(load_config()["seed"])
        occ, rc = occupancy_by_section(), reroute_cache()
        limit = float(load_config()["planner"]["solve_time_s_instance"])
        for k in range(2, 5):
            new = generate_tasks(w.net, 40, random.Random(seed + 1000 * k), registry=StatusRegistry(),
                                 id_prefix=f"W{k}")
            for t in carried:
                t.scheduled_start_s = t.scheduled_end_s = None
                waited[t.id] = waited.get(t.id, 0) + 1
            # A job left over from earlier weeks is planned one level more urgent for each week it has waited,
            # so routine work is not outranked forever (backend/planner/aging.py, A-059).
            aged_from.update({k: v for k, v in age_carried(carried, {t.id: 1 for t in carried}).items() if k not in aged_from})
            tasks = new + carried
            natural, res, created = solve_with_creation(w.net, tasks, w.windows, occ, rc, limit,
                                                        pax=get_pax())
            tby = {t.id: t for t in tasks}
            off = (k - 1) * 7 * DAY_S
            ek = _entries(res, tby, {}, off, f"W{k}")
            for e in ek:
                if e["task_id"] in aged_from:
                    e["aged_from"] = aged_from[e["task_id"]]
                    e["waited_weeks"] = waited.get(e["task_id"], 0)
            placed_ids = {e["task_id"] for e in ek}
            weeks.append({"week": k, "entries": ek, "n_tasks": len(tasks), "placed": len(ek),
                          "carried_in": len(carried),
                          "carried_out": len([t for t in tasks if t.id not in placed_ids]),
                          "micro_gap": sum(1 for e in ek if e["gap_type"] == "MICRO_GAP"),
                          "created": sum(1 for e in ek if e["created"])})
            carried = [t.model_copy(deep=True) for t in tasks if t.id not in placed_ids]
            with _MONTH_LOCK:
                _MONTH.update(weeks=list(weeks), progress=k)
        with _MONTH_LOCK:
            _MONTH.update(status="done")
    except Exception as e:  # surfaced to the UI rather than dying silently in a thread
        with _MONTH_LOCK:
            _MONTH.update(status="error", error=repr(e))


@router.post("/api/schedule/month/build")
def month_build(force: bool = False) -> dict:
    with _MONTH_LOCK:
        if _MONTH["status"] == "running":
            return {"status": "running"}
        if _MONTH["status"] == "done" and not force:
            return {"status": "done"}
        _MONTH.update(status="running", progress=0, weeks=[], error=None, started=time.time())
    threading.Thread(target=_build_month, daemon=True).start()
    return {"status": "running"}


@router.get("/api/schedule/month")
def schedule_month() -> dict:
    """Four rolling weekly cycles: each week re-plans with the last week's backlog carried in."""
    with _MONTH_LOCK:
        m = dict(_MONTH)
    weeks = m["weeks"]
    return {
        "status": m["status"], "progress": m["progress"], "total_weeks": 4, "error": m["error"],
        "weeks": weeks,
        "summary": {
            "n_tasks": sum(x["n_tasks"] - x["carried_in"] for x in weeks),
            "placed": sum(x["placed"] for x in weeks),
            "micro_gap": sum(x["micro_gap"] for x in weeks),
            "created": sum(x["created"] for x in weeks),
            "backlog_end": weeks[-1]["carried_out"] if weeks else 0,
        },
    }


# ------------------------------------------------------------------------------- scorecard


def _blocks(entries: list[dict]) -> int:
    """Protected blocks the plan needs: jobs that overlap in time with a nearby job from another
    department, and are in the same cluster, share one block. Counted by union-find."""
    parent = list(range(len(entries)))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for i, a in enumerate(entries):
        for j in range(i + 1, len(entries)):
            b = entries[j]
            if (a["cluster"] is not None and a["cluster"] == b["cluster"]
                    and a["department"] != b["department"]
                    and a["start_s"] < b["end_s"] and b["start_s"] < a["end_s"]):
                parent[find(i)] = find(j)
    return len({find(i) for i in range(len(entries))})


@router.get("/api/metrics/scorecard")
def scorecard() -> dict:
    """Every algorithm's measured effect, each with how it was measured and how to reproduce it."""
    import json
    from backend.api.routes import REPO_ROOT_ART, algorithms_proof
    from backend.domain.scoring import score_tasks as _score
    from backend.metrics.manual_baseline import plan_manually

    w = ensure_world()
    plan = ensure_plan()
    proof = algorithms_proof()
    exp = creation_experiment()
    cs = creation_summary_route()
    pool, clusters, scores, cluster_of = _scored_pool()

    usable = {"NIGHT_WINDOW": 0, "MEGABLOCK": 0, "MICRO_GAP": 0}
    for x in w.gaps.windows:
        usable[x.gap_type.value] += x.usable_min()
    manual_h = (usable["NIGHT_WINDOW"] + usable["MEGABLOCK"]) / 60
    ours_h = sum(usable.values()) / 60

    by_id = {t.id: t for t in w.tasks}
    entries = _entries(plan, by_id, cluster_of)
    manual = plan_manually(w.net, w.tasks, w.windows)
    blocks_ours = _blocks(entries)

    t0 = time.perf_counter()
    scored = score_tasks(w.net, pool, clusters)
    score_ms = (time.perf_counter() - t0) * 1000
    pairs = sum(s.mates for s in scored.values()) // 2
    hours = float(load_config().get_path("metrics.manual_coordination_hours_per_conflict", 4.0))

    rl = None
    path = REPO_ROOT_ART / "rl_comparison.json"
    if path.exists():
        d = json.loads(path.read_text(encoding="utf-8"))
        best = min(d["table"], key=lambda r: r["mean_gap_vs_cpsat_pct"])
        rl = {"policy": best["policy"], "gap": best["mean_gap_vs_cpsat_pct"],
              "cpsat_ms": d["cpsat_mean_ms"], "rl_ms": best["mean_full_replan_ms"],
              "instances": d["instances"], "violations": best["constraint_violations"]}

    it = proof["interval_tree"]
    cards = [
        {"id": "gaps", "algorithm": "Gap finding (interval engine)",
         "what": "Finds every workable gap between trains, after safety and set-up time.",
         "before": {"label": "Night + Sunday block only", "value": round(manual_h), "unit": "usable hours / week"},
         "after": {"label": "Every gap, min 15 min of work", "value": round(ours_h), "unit": "usable hours / week"},
         "detail": f"{proof['gaps']['micro']:,} of the windows are gaps between trains that manual planning never looks at.",
         "how": "Sum of usable minutes over every window the engine produced, by type. Manual planning uses night and megablock windows only (SPEC section 6).",
         "repro": "GET /api/gaps"},
        {"id": "creation", "algorithm": "Gap creation (retime, reroute, single-line)",
         "what": "Opens a window with a small, priced change to the trains when none exists in time.",
         "before": {"label": "Only gaps that already exist", "value": exp["natural_placed"], "unit": f"of {exp['jobs']} urgent jobs placed"},
         "after": {"label": "With gap creation", "value": exp["with_creation_placed"], "unit": f"of {exp['jobs']} urgent jobs placed"},
         "detail": (f"{exp['created_gaps_used']} gaps opened ({exp['by_lever']['SINGLE_LINE']} single-line, "
                    f"{exp['by_lever']['REROUTE']} reroute, {exp['by_lever']['RETIME']} retime) at a cost of "
                    f"{exp['delay_train_min']} train-minutes. Timetable-wide, {cs['survey']['near_gaps']:,} near-miss gaps exist and "
                    f"{cs['survey']['created']} can be opened (+{cs['survey']['usable_hours_added']} usable hours)."),
         "how": "Sixty urgent jobs (due within 6 h) scheduled twice on the same timetable, same order: without and with creation. Each job is scheduled independently on an empty plan.",
         "repro": "GET /api/creation/experiment"},
        {"id": "cluster", "algorithm": "Job clustering + integrated blocks",
         "what": "Groups nearby jobs so compatible departments share one protected block.",
         "before": {"label": "One block per job", "value": len(manual.placements), "unit": "protected blocks"},
         "after": {"label": "Jobs sharing blocks", "value": blocks_ours, "unit": f"protected blocks for {len(entries)} jobs"},
         "detail": f"{plan.integrated_pairs} compatible cross-department pairs were placed into shared blocks by the weekly solver.",
         "how": "Blocks in the weekly plan = jobs minus merges of same-cluster, different-department jobs that overlap in time. The manual baseline cannot overlap departments (each clash is negotiated and deferred).",
         "repro": "GET /api/schedule/week"},
        {"id": "compat", "algorithm": "Compatibility engine (rules R0-R4 + declarations)",
         "what": "Decides whether two jobs may share a place and time, with a written reason per pair.",
         "before": {"label": "Phone negotiation", "value": round(pairs * hours), "unit": f"hours ({pairs} pairs x {hours:g} h, assumed)"},
         "after": {"label": "Computed", "value": round(score_ms), "unit": "ms for the whole pool"},
         "detail": "Every verdict is one of COMPATIBLE / REQUIRES_IWP / INCOMPATIBLE and carries its reason.",
         "how": f"Wall-clock time of score_tasks over {len(pool)} jobs. The manual figure uses the adjustable baseline parameter, not field data.",
         "repro": "GET /api/tasks/scores"},
        {"id": "plan", "algorithm": "Weekly planner (CP-SAT, exact)",
         "what": "Places the week's jobs optimally against every rule at once.",
         "before": {"label": "Manual, department by department", "value": len(manual.placements), "unit": f"of {plan.n_tasks} jobs placed"},
         "after": {"label": f"CP-SAT {plan.status.lower()}", "value": len(plan.assignments), "unit": f"of {plan.n_tasks} jobs placed"},
         "detail": f"Optimality gap {plan.gap_pct}%, solved in {plan.wall_s:.0f} s, {plan.micro_gap_count} jobs placed into gaps between trains.",
         "how": "Same task pool and windows for both. Manual is plan_manually (first-come-first-served per department, night and megablock windows only).",
         "repro": "scripts/05_run_impact_study.py"},
        {"id": "interval", "algorithm": "Interval tree (gap lookup)",
         "what": "Answers what is free here between these times without scanning every window.",
         "before": {"label": "Scan every window", "value": it["scan_ms"], "unit": f"ms for {it['queries']} queries"},
         "after": {"label": "Interval tree", "value": it["tree_ms"], "unit": f"ms for {it['queries']} queries"},
         "detail": f"{it['speedup_x']}x faster, identical answers: {'yes' if it['identical'] else 'NO'}.",
         "how": "The same range queries answered by a full scan and by the tree; result sets compared for equality.",
         "repro": "GET /api/algorithms/proof"},
    ]
    if rl:
        cards.append({
            "id": "rl", "algorithm": "Reactive dispatcher (offline RL)",
            "what": "Re-plans in milliseconds when an unplanned defect appears, learned from CP-SAT's own solutions.",
            "before": {"label": "CP-SAT full re-solve", "value": round(rl["cpsat_ms"] / 1000, 1), "unit": "s per re-plan"},
            "after": {"label": rl["policy"], "value": round(rl["rl_ms"] / 1000, 2), "unit": "s per re-plan"},
            "detail": f"{rl['gap']}% from CP-SAT's objective on {rl['instances']} held-out instances; constraint violations {rl['violations']}. Today an unplanned defect waits for the next weekly cycle.",
            "how": "Held-out instances split by instance id (never by transition). Both scored with CP-SAT's own objective.",
            "repro": "scripts/06_evaluate_rl.py"})
    return {
        "cards": cards,
        "headline": {
            "capacity_gain_pct": round(100 * (ours_h - manual_h) / max(1, manual_h)),
            "urgent_jobs_natural": exp["natural_placed"], "urgent_jobs_creation": exp["with_creation_placed"],
            "urgent_jobs_total": exp["jobs"],
            "blocks_manual": len(manual.placements), "blocks_ours": blocks_ours,
            "jobs_placed_manual": len(manual.placements), "jobs_placed_ours": len(plan.assignments),
        },
        "limits": [
            "Maintenance jobs, coordination times and speed limits are synthetic (ASSUMPTIONS.md lists every one).",
            "The before case is a model of decentralised practice, not measured field data; its two parameters are adjustable below.",
            "The RL benchmark is on generated instances; it has not been validated against real defect logs.",
            "The IR system adapters are mocks; the payload shapes are our assumptions pending access.",
        ],
    }
