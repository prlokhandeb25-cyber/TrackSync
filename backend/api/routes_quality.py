"""Is the plan right, and will it hold? The referee, and the robustness of each block.

<!-- serves: J2, J5 -->

    GET /api/plan/verify        every rule re-checked from the timetable, not from the solver
    GET /api/plan/robustness    chance each block clears before the next train; the same plan
                                with each start centred; and the plan without the robustness term
"""

from __future__ import annotations

import threading

from fastapi import APIRouter

from backend.api.state import STATE, ensure_plan, ensure_world, get_pax, occupancy_by_section
from backend.config import load_config
from backend.planner.robustness import assess, centre_plan
from backend.planner.verify import verify_plan

router = APIRouter()

_ROB: dict = {"status": "idle", "ablation": None, "error": None}
_LOCK = threading.Lock()


@router.get("/api/plan/verify")
def plan_verify() -> dict:
    w = ensure_world()
    plan = ensure_plan()
    rep = verify_plan(w.net, w.tasks, plan.assignments, w.windows, occupancy_by_section())
    d = rep.to_dict()
    d.update(n_jobs=len(plan.assignments), status=plan.status)
    return d


def _stats(rows) -> dict:
    n = len(rows)
    return {"mean": round(sum(r.p_clear for r in rows) / n, 4) if n else 1.0,
            "risky": sum(1 for r in rows if r.p_clear < 0.9),
            "expected_overruns": round(sum(1 - r.p_clear for r in rows), 2), "blocks": n}


def _ablation() -> None:
    """The same week solved WITHOUT the robustness term: what the solver alone would have chosen."""
    from backend.planner.cpsat import solve_with_relaxation
    try:
        w = ensure_world()
        pax = get_pax()
        occ = occupancy_by_section()
        tasks = [t.model_copy(deep=True) for t in w.tasks]
        for t in tasks:
            t.scheduled_start_s = t.scheduled_end_s = None
        res = solve_with_relaxation(w.net, tasks, w.windows,
                                    time_limit_s=load_config()["planner"]["solve_time_s_demo"], pax=pax,
                                    weights={"w10_fragile_window": 0.0})
        by = {t.id: t for t in tasks}
        raw = assess(res.assignments, by, occ)
        _, rep = centre_plan(w.net, tasks, res.assignments, w.windows, occ)
        with _LOCK:
            _ROB.update(status="done", ablation={
                "placed": len(res.assignments), "solver": res.status, "raw": _stats(raw), "centred": _stats(rep.after),
                "moved": rep.moved})
    except Exception as e:                                              # shown on the page, not swallowed
        with _LOCK:
            _ROB.update(status="error", error=repr(e))


@router.get("/api/plan/robustness")
def plan_robustness() -> dict:
    w = ensure_world()
    plan = ensure_plan()
    occ = occupancy_by_section()
    by = {t.id: t for t in w.tasks}
    now = assess(plan.assignments, by, occ)              # the plan as it stands: already centred
    with _LOCK:
        if _ROB["status"] == "idle":
            _ROB["status"] = "running"
            threading.Thread(target=_ablation, daemon=True).start()
        snap = dict(_ROB)
    weakest = sorted(now, key=lambda r: r.p_clear)[:5]
    return {
        "samples": STATE.robust.get("samples", 400),
        "plan": _stats(now),
        "before_centring": STATE.robust.get("before"), "centred_moves": STATE.robust.get("moves", 0),
        "weakest": [r.to_dict() for r in weakest],
        "ablation_status": snap["status"], "ablation": snap["ablation"], "error": snap["error"],
        "how": "Each block is simulated 400 times: the train ahead runs late as the delay model says, the work "
               "overruns by a random amount (spread 15%), and we count how often the line is handed back before "
               "the next train with the 5-minute lookout to spare. Invented spreads, A-043.",
    }
