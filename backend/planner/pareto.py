"""A small set of trade-off plans, solved exactly, for a coordinator to choose between.

<!-- serves: J1, J5 -->

One plan hides a choice. The weekly model has three things a decision-maker can want more or less of:

    JOBS         how many jobs get done
    PASSENGERS   how many passengers are within reach of the work (fewer is better)
    ROBUSTNESS   how often blocks are handed back before the next train (higher is better)

Each plan below is the exact solver's answer to a different weighting of the same model (same rules, same gaps,
same jobs). Every plan is scored on all three measures with the same yardsticks and the plans that another plan
beats on all three are marked dominated. Sliding between them shows what each gains, what it costs, and exactly
which jobs move against the plan currently in force.

Only weights change; no rule is relaxed, and nothing here touches the live plan (see `approvals.py` for how a
coordinator adopts one).
"""

from __future__ import annotations

import time

from backend.config import load_config
from backend.planner.cpsat import build_and_solve
from backend.planner.robustness import assess

# (id, title, what it favours, weight overrides as multipliers of the live weights; None = zero the term)
CHURN = 25.0    # cost of moving one job away from where the plan in force has it

POINTS = [
    ("jobs", "Most jobs done", "places as many jobs as possible, ignores passengers and fragility", {"w9_pax_exposure": 0.0, "w10_fragile_window": 0.0}),
    ("balanced", "As planned today", "the weights the live plan uses", {}),
    ("robust", "Most robust", "leaves room before every next train", {"w10_fragile_window": 8.0}),
    ("quiet", "Fewest passengers", "keeps work away from busy services", {"w9_pax_exposure": 8.0}),
    ("safe_quiet", "Quiet and robust", "both of the above", {"w9_pax_exposure": 8.0, "w10_fragile_window": 8.0}),
]


def _weights(over: dict) -> dict:
    base = dict(load_config()["planner"]["weights"])
    out = {}
    for k, m in over.items():
        out[k] = float(base.get(k, 0.0)) * m if m else 0.0
        if m and not base.get(k):
            out[k] = 6.0 * m                       # a term the live weights leave at zero gets a working scale
    return out


def score(plan_assignments, tasks_by_id, occ, pax) -> dict:
    rows = assess(plan_assignments, tasks_by_id, occ, samples=200)
    return {"placed": len(plan_assignments),
            "passengers": int(sum(pax.job_exposure(a.section_id, a.start_s, a.end_s) for a in plan_assignments)),
            "robust": round(sum(r.p_clear for r in rows) / max(1, len(rows)), 4)}


def diff_vs(reference: list, new: list, tasks_by_id: dict) -> dict:
    """What changes going from the plan in force to this one."""
    ref = {a.task_id: a for a in reference}
    nw = {a.task_id: a for a in new}
    moved, added, dropped = [], [], []
    for tid, a in nw.items():
        r = ref.get(tid)
        t = tasks_by_id.get(tid)
        lab = t.label if t else tid
        if r is None:
            added.append({"task_id": tid, "label": lab, "to": [a.start_s, a.end_s]})
        elif (r.start_s, r.track, r.zone_ref) != (a.start_s, a.track, a.zone_ref):
            moved.append({"task_id": tid, "label": lab, "department": t.department.value if t else "", "zone": a.zone_ref,
                          "from": [r.start_s, r.end_s], "to": [a.start_s, a.end_s]})
    for tid, r in ref.items():
        if tid not in nw:
            t = tasks_by_id.get(tid)
            dropped.append({"task_id": tid, "label": t.label if t else tid, "from": [r.start_s, r.end_s]})
    return {"moved": moved, "added": added, "dropped": dropped, "unchanged": len(set(ref) & set(nw)) - len(moved)}


def dominated(points: list[dict]) -> None:
    for p in points:
        p["dominated"] = any(
            q is not p and q["placed"] >= p["placed"] and q["passengers"] <= p["passengers"] and q["robust"] >= p["robust"]
            and (q["placed"], -q["passengers"], q["robust"]) != (p["placed"], -p["passengers"], p["robust"])
            for q in points)


def solve_points(world, pax, occ, reference_assignments, per_solve_s: float = 15.0, progress=None) -> dict:
    """Solve every point on fresh copies of the jobs. Returns the points with metrics and diffs; keeps the assignments."""
    by_id = {t.id: t for t in world.tasks}
    # every plan starts from the plan in force and pays a small cost per job it moves (as re-plans do, A-044), so what moves
    # is what the trade-off really needs, not solver noise between equally good arrangements
    anchor = {a.task_id: (a.window_id, a.start_s) for a in reference_assignments if a.window_id and not a.window_id.startswith("CW-")}
    pts = []
    for i, (pid, title, why, over) in enumerate(POINTS):
        tasks = [t.model_copy(deep=True) for t in world.tasks]
        for t in tasks:
            t.scheduled_start_s = t.scheduled_end_s = None
            t.window_id = t.gap_type = None
        t0 = time.time()
        w = {**_weights(over), "w11_churn": CHURN}
        res = build_and_solve(world.net, tasks, world.windows, per_solve_s, pax=pax, weights=w, anchor=anchor)
        m = score(res.assignments, by_id, occ, pax)
        pts.append({"id": pid, "title": title, "why": why, "status": res.status, "gap_pct": round(res.gap_pct, 2),
                    "wall_s": round(time.time() - t0, 1), "objective": res.objective, **m, "assignments": res.assignments,
                    "diff": diff_vs(reference_assignments, res.assignments, by_id)})
        if progress is not None:
            progress(i + 1, len(POINTS))
    dominated(pts)
    ref = score(reference_assignments, by_id, occ, pax)
    return {"reference": ref, "points": pts}
