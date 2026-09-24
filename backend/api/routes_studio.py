"""The planning studio: scale test, trade-off plans, machine limits, approvals, and learning from execution.

<!-- serves: J1, J2, J3, J5 -->

Every long computation runs once in a background thread on COPIES and is served as it finishes; none of it touches the
live plan. The only routes that change live state are the explicit ones a coordinator uses: apply and revert an
APPROVED proposal (planner/approvals.py). Only one heavy job runs at a time so the rest of the app stays responsive.

    /api/studio/scale        POST run, GET progress and the timing curve
    /api/studio/pareto       POST run, GET trade-off plans; POST propose a plan
    /api/studio/resources    GET live plan against machine limits; POST run the machine-constrained solve; POST propose it
    /api/approvals           GET proposals and the audit trail; POST decide / apply / revert
    /api/learning            GET estimate; POST log a completion, simulate a stream, reset the simulated stream
"""

from __future__ import annotations

import threading

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.api.state import STATE, ensure_plan, ensure_world, get_pax, occupancy_by_section
from backend.planner import approvals as AP
from backend.planner import learning as LN
from backend.planner import pareto as PA
from backend.planner import resource_plan as RP
from backend.planner import scale as SC

router = APIRouter()
_LOCK = threading.Lock()
_JOB = {"running": None}
_S: dict[str, dict] = {k: {"status": "idle", "progress": [0, 1], "data": None, "error": None} for k in ("scale", "pareto", "resources")}
_PARETO_ASSIGN: dict[str, list] = {}
_RES_ASSIGN: dict = {}


def _start(name: str, fn) -> dict:
    with _LOCK:
        if _JOB["running"]:
            return {"started": False, "busy_with": _JOB["running"]}
        _JOB["running"] = name
        _S[name].update(status="running", progress=[0, 1], error=None)

    def work():
        try:
            data = fn(lambda i, n: _S[name].update(progress=[i, n]))
            with _LOCK:
                _S[name].update(status="done", data=data)
        except Exception as e:                                        # shown on the page, not swallowed
            with _LOCK:
                _S[name].update(status="error", error=repr(e))
        finally:
            with _LOCK:
                _JOB["running"] = None

    threading.Thread(target=work, daemon=True).start()
    return {"started": True}


def _state(name: str) -> dict:
    with _LOCK:
        d = dict(_S[name])
        d["busy_with"] = _JOB["running"] if _JOB["running"] != name else None
        return d


# ------------------------------------------------------------------------------------------- scale


def _scale(progress):
    w = ensure_world()
    pax = get_pax()
    rows = []
    for i, n in enumerate(SC.SIZES):
        rows.append(SC.run_size(w, pax, n, SC.BUDGET_S[n]))
        with _LOCK:
            _S["scale"]["data"] = {"rows": list(rows), "partial": True}
        progress(i + 1, len(SC.SIZES))
    return {"rows": rows, "partial": False,
            "how": "Random jobs on the live network and timetable, solved by the exact solver with a fixed time budget per size; the solver's own progress "
                   "is logged. 'Proven optimal' only if the gap closed to zero inside the budget. The per-day block cap grows with the workload. The fast "
                   "heuristic ignores the gang and daily-block limits, so its count is an upper bound on what it could place legally.",
            "caveat": "One seeded job mix per size; the jobs are synthetic like the rest of the project's jobs (A-016)."}


@router.post("/api/studio/scale/run")
def scale_run() -> dict:
    return _start("scale", _scale)


@router.get("/api/studio/scale")
def scale_get() -> dict:
    return _state("scale")


# ------------------------------------------------------------------------------------------ pareto


def _pareto(progress):
    w = ensure_world()
    plan = ensure_plan()
    r = PA.solve_points(w, get_pax(), occupancy_by_section(), list(plan.assignments), per_solve_s=15.0, progress=progress)
    _PARETO_ASSIGN.clear()
    for p in r["points"]:
        _PARETO_ASSIGN[p["id"]] = p.pop("assignments")
    return {"reference": r["reference"], "points": r["points"],
            "how": "Five plans, each the exact solver's answer to a different weighting of the same model (same rules, gaps and jobs), scored on jobs "
                   "placed, passengers within reach and how often blocks clear before the next train. A plan is dominated if another beats it on all three. "
                   "The comparison with the plan in force lists exactly which jobs move.",
            "caveat": "Each plan had a 15-second budget: the gap it reached is shown, and a plan is not called optimal unless the solver proved it."}


@router.post("/api/studio/pareto/run")
def pareto_run() -> dict:
    return _start("pareto", _pareto)


@router.get("/api/studio/pareto")
def pareto_get() -> dict:
    return _state("pareto")


class ProposeReq(BaseModel):
    point_id: str = ""
    by: str = "coordinator"


@router.post("/api/studio/pareto/propose")
def pareto_propose(req: ProposeReq) -> dict:
    d = _S["pareto"]["data"]
    pt = next((p for p in (d or {}).get("points", []) if p["id"] == req.point_id), None)
    if pt is None or req.point_id not in _PARETO_ASSIGN:
        raise HTTPException(status_code=404, detail="run the trade-off plans first")
    summary = {k: pt[k] for k in ("placed", "passengers", "robust", "status", "gap_pct", "objective")}
    return AP.propose("pareto", f"Trade-off plan: {pt['title']}", req.by, _PARETO_ASSIGN[req.point_id], summary, pt["diff"])


# --------------------------------------------------------------------------------------- machines


def _pools(tamper: int, ballast: int, tower: int) -> dict:
    return {"Tamping machine": max(1, tamper), "Ballast cleaning machine": max(1, ballast), "Tower wagon": max(1, tower)}


@router.get("/api/studio/resources")
def resources_get(tamper: int = 1, ballast: int = 1, tower: int = 2) -> dict:
    """The plan in force against the machine limits (instant), plus the last constrained solve if there is one."""
    w = ensure_world()
    plan = ensure_plan()
    pools = _pools(tamper, ballast, tower)
    c = RP.machine_conflicts(w.net, w.tasks, plan.assignments, pools)
    return {"pools": pools, "machine_jobs": RP.machine_jobs(w.tasks), "live_conflicts": c, "solve": _state("resources"),
            "assumption": "machine pools, speed and shunt time are assumed (A-057)"}


def _resources(pools: dict):
    def go(progress):
        w = ensure_world()
        pax = get_pax()
        plan = ensure_plan()
        from backend.planner.cpsat import build_and_solve

        def fresh():
            out = [t.model_copy(deep=True) for t in w.tasks]
            for t in out:
                t.scheduled_start_s = t.scheduled_end_s = None
                t.window_id = t.gap_type = None
            return out
        t_free, t_mach = fresh(), fresh()
        free = build_and_solve(w.net, t_free, w.windows, 25, pax=pax)
        progress(1, 2)
        mach = build_and_solve(w.net, t_mach, w.windows, 25, pax=pax, extra=RP.make_extra(w.net, pools))
        progress(2, 2)
        by = {t.id: t for t in w.tasks}
        cf = RP.machine_conflicts(w.net, w.tasks, free.assignments, pools)
        cm = RP.machine_conflicts(w.net, w.tasks, mach.assignments, pools)
        _RES_ASSIGN["assignments"] = list(mach.assignments)
        _RES_ASSIGN["pools"] = pools
        d = PA.diff_vs(list(plan.assignments), list(mach.assignments), by)
        _RES_ASSIGN["diff"] = d
        _RES_ASSIGN["summary"] = {**PA.score(mach.assignments, by, occupancy_by_section(), pax), "status": mach.status,
                                  "gap_pct": round(mach.gap_pct, 2), "objective": mach.objective}
        return {"pools": pools, "without": {"status": free.status, "placed": len(free.assignments), "objective": round(free.objective),
                                            "conflicts": cf},
                "with": {"status": mach.status, "placed": len(mach.assignments), "objective": round(mach.objective), "conflicts": cm},
                "moved_vs_live": len(d["moved"]),
                "how": "The same week solved twice by the exact solver, once as the live plan is (machines ignored) and once with each machine in one "
                       "place at a time and travel time between sections. Both plans are then checked against the machine rules.",
                "caveat": "Machine pools, travel speed and shunt time are assumed (A-057). The two solves had a 25-second budget each."}
    return go


class PoolsReq(BaseModel):
    tamper: int = 1
    ballast: int = 1
    tower: int = 2


@router.post("/api/studio/resources/run")
def resources_run(req: PoolsReq) -> dict:
    return _start("resources", _resources(_pools(req.tamper, req.ballast, req.tower)))


@router.post("/api/studio/resources/propose")
def resources_propose(req: ProposeReq) -> dict:
    if not _RES_ASSIGN.get("assignments"):
        raise HTTPException(status_code=404, detail="run the machine-constrained solve first")
    return AP.propose("machines", "Plan that respects machine limits and travel", req.by, _RES_ASSIGN["assignments"], _RES_ASSIGN["summary"],
                      _RES_ASSIGN["diff"], {"pools": _RES_ASSIGN["pools"]})


# ---------------------------------------------------------------------------------------- approvals


class DecideReq(BaseModel):
    approve: bool
    reason: str = ""
    by: str = "coordinator"


class ActorReq(BaseModel):
    by: str = "coordinator"


@router.get("/api/approvals")
def approvals_get() -> dict:
    return {"proposals": AP.proposals(), "audit": AP.audit(), "can_revert": AP.can_revert(),
            "plan_in_force": {"placed": len(ensure_plan().assignments), "status": ensure_plan().status}}


@router.post("/api/approvals/{pid}/decide")
def approvals_decide(pid: str, req: DecideReq) -> dict:
    try:
        return AP.decide(pid, req.approve, req.reason, req.by)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown proposal")
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/api/approvals/{pid}/apply")
def approvals_apply(pid: str, req: ActorReq) -> dict:
    try:
        return AP.apply(pid, req.by)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown proposal")
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/api/approvals/revert")
def approvals_revert(req: ActorReq) -> dict:
    try:
        return AP.revert(req.by)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


# ---------------------------------------------------------------------------------------- learning


class LogReq(BaseModel):
    task_id: str
    actual_min: int
    rain: bool = False
    note: str = ""


class SimReq(BaseModel):
    n: int = 30


@router.get("/api/learning")
def learning_get(source: str = "real") -> dict:
    source = "simulated" if source == "simulated" else "real"
    recs = LN.records(source)
    return {"source": source, "n": len(recs), "estimate": LN.estimate(source), "convergence": LN.convergence("simulated") if source == "simulated" else [],
            "recent": recs[-8:][::-1], "n_real": len(LN.records("real")), "n_simulated": len(LN.records("simulated")),
            "note": "Starts from a neutral prior (crews take the planned time). With no logged jobs the buffer is 0, not an invented one."}


@router.get("/api/learning/tasks")
def learning_tasks() -> dict:
    w = ensure_world()
    return {"tasks": [{"id": t.id, "label": t.label, "department": t.department.value, "planned_min": t.duration_min}
                      for t in w.tasks if t.scheduled_start_s is not None]}


@router.post("/api/learning/log")
def learning_log(req: LogReq) -> dict:
    w = ensure_world()
    t = next((x for x in w.tasks if x.id == req.task_id), None)
    if t is None:
        raise HTTPException(status_code=404, detail="unknown task")
    try:
        rec = LN.log_completion(t.id, t.department.value, req.rain, t.duration_min, req.actual_min, req.note)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    AP.load_audit()
    return {"logged": rec, "n_real": len(LN.records("real"))}


@router.post("/api/learning/simulate")
def learning_simulate(req: SimReq) -> dict:
    return {"n_simulated": LN.simulate(max(1, min(600, req.n)))}


@router.post("/api/learning/reset-simulated")
def learning_reset() -> dict:
    LN.reset_simulated()
    return {"n_simulated": 0}
