"""API routes (SPEC §17).

<!-- serves: J2, J4, J5 -->
"""

from __future__ import annotations

import time
from collections import Counter

from fastapi import APIRouter, HTTPException

from backend.api.state import STATE, ensure_plan, ensure_world, new_demand_task, reset
from backend.config import load_config
from backend.domain.compatibility import coordination_conflicts, matrix
from backend.domain.models import TrackStatus, s_to_hhmm
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


@router.get("/api/plan")
def plan() -> dict:
    res = ensure_plan()
    d = res.to_dict()
    d["by_day"] = {DAYS[i]: sum(1 for a in res.assignments if a.day == i) for i in range(7)}
    d["by_gap_type"] = dict(Counter(a.gap_type for a in res.assignments))
    return d


@router.post("/api/tasks/demand")
def inject_demand(zone_ref: str | None = None, at_s: int = 0) -> dict:
    t = new_demand_task(at_s or STATE.sim_time_s, zone_ref)
    STATE.log(at_s or STATE.sim_time_s,
              f"Unplanned defect reported: {t.describe()}.", "demand")
    return {"task": {"id": t.id, "describe": t.describe(), "zone": t.zone.ref,
                     "department": t.department.value, "duration_min": t.duration_min,
                     "priority": t.priority}}


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
    w = ensure_world()
    plan = ensure_plan()
    from backend.rl.agents import GreedyPolicy
    policy = GreedyPolicy()
    try:
        import torch

        from backend.rl.agents import TorchPolicy
        from backend.rl.nets import QNet
        blob = torch.load(REPO_ROOT_MODELS / "cql_dqn.pt", map_location="cpu", weights_only=True)
        net = QNet(blob["state_dim"], blob["action_dim"], blob["hidden"])
        net.load_state_dict(blob["state_dict"]); net.eval()
        policy = TorchPolicy(net, "CQL-DQN")
    except Exception:  # noqa: BLE001 - fall back to greedy if the model is unavailable
        pass
    rep = compute_impact(w.net, w.tasks, w.windows, plan, policy)
    return rep.to_dict()


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
