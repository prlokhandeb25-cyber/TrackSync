"""Does the exact solver still work as the workload grows? A timing curve on random instances.

<!-- serves: J2, J3 -->

For each size (40, 100, 200, 400 random jobs on the live network and timetable) the weekly model is built and solved
with a fixed time budget, and the solver's own progress is recorded: when it first had a plan, when its best plan
was provably within 10%, 5% and 1% of the best possible, and where it stopped. "Proven optimal" means the solver
closed the gap to zero inside the budget; anything else is reported as the gap it reached, never rounded up.

A fast heuristic (the live scheduler's insert-one-at-a-time repair) is run on the same jobs beside it: much
quicker, but it carries no proof and ignores the gang and daily-block limits, so its count is an upper bound on
what it could place legally.

The per-day block cap grows with the workload (a bigger workload means a bigger division), otherwise every size
above 40 jobs simply runs into the same cap. Job mixes are random but seeded, so the curve is reproducible.
"""

from __future__ import annotations

import math
import random
import time

from backend.config import load_config
from backend.data.synth_tasks import generate_tasks
from backend.domain.fsm import StatusRegistry
from backend.planner.cpsat import Assignment, build_and_solve
from backend.planner.interval_index import build_interval_index
from backend.planner.live_sim import LiveSimState, alns_lite_insert, order_max_to_min
from backend.planner.verify import verify_plan

SIZES = (40, 100, 200, 400)
BUDGET_S = {40: 30.0, 100: 60.0, 200: 90.0, 400: 120.0}
FAST_SIZES = (800, 1600)          # the fast path only: how it behaves far beyond what the exact solver can prove


def _first_within(curve: list[tuple[float, float, float]], pct: float) -> float | None:
    for t, obj, bound in curve:
        if abs(obj) > 1e-9 and abs(obj - bound) / abs(obj) * 100 <= pct:
            return t
    return None


def _referee(world, occ, tasks, assignments, cap: int) -> dict:
    """The independent checker on a plan: how many rule checks were made and how many failed, by kind."""
    rep = verify_plan(world.net, [t.model_copy(deep=True) for t in tasks], assignments, world.windows, occ, max_blocks_per_day=cap)
    return {"checks": sum(rep.checks.values()), "violations": len(rep.violations)}


def _as_assignments(placements) -> list:
    out = []
    for p in placements:
        if p.placed and p.window is not None:
            w = p.window
            out.append(Assignment(p.task.id, w.id, w.section_id, w.zone_ref, w.track, p.start_s, p.end_s, w.gap_type.value, p.start_s // 86400))
    return out


def run_fast(world, pax, occ, n: int, seed: int = 0) -> dict:
    """The fast heuristic alone on n random jobs, far past what the exact solver can prove; checked by the referee."""
    rng = random.Random(seed * 100003 + n)
    tasks = generate_tasks(world.net, n, rng, registry=StatusRegistry(), id_prefix=f"F{n}")
    cap = math.ceil(int(load_config().get_path("planner.max_blocks_per_day", 8)) * n / 40)
    idx = build_interval_index(world.windows)
    st = LiveSimState()
    t0 = time.time()
    ps = [alns_lite_insert(world.net, t, idx, [], st, creator=None, at_s=0, pax=pax, allow_destroy=False)
          for t in order_max_to_min([t.model_copy(deep=True) for t in tasks])]
    wall = time.time() - t0
    asg = _as_assignments(ps)
    return {"n": n, "placed": len(asg), "wall_s": round(wall, 2), "jobs_per_s": round(n / max(wall, 1e-6), 1),
            "referee": _referee(world, occ, tasks, asg, cap)}


def run_size(world, pax, n: int, budget_s: float, seed: int = 0, occ=None) -> dict:
    net = world.net
    rng = random.Random(seed * 100003 + n)
    tasks = generate_tasks(net, n, rng, registry=StatusRegistry(), id_prefix=f"S{n}")
    cap = math.ceil(int(load_config().get_path("planner.max_blocks_per_day", 8)) * n / 40)
    progress: list[tuple[float, float, float]] = []
    t0 = time.time()
    res = build_and_solve(net, [t.model_copy(deep=True) for t in tasks], world.windows, budget_s, pax=pax,
                          max_blocks_per_day=cap, progress=progress)
    wall = time.time() - t0
    # the fast heuristic on the same jobs
    idx = build_interval_index(world.windows)
    st = LiveSimState()
    h0 = time.time()
    placed_h = 0
    hp = []
    for t in order_max_to_min([t.model_copy(deep=True) for t in tasks]):
        p = alns_lite_insert(net, t, idx, [], st, creator=None, at_s=0, pax=pax, allow_destroy=False)
        hp.append(p)
        placed_h += 1 if p.placed else 0
    heur_s = time.time() - h0
    cap_ = cap
    ref_solver = _referee(world, occ, tasks, res.assignments, cap_) if occ is not None else None
    ref_heur = _referee(world, occ, tasks, _as_assignments(hp), cap_) if occ is not None else None
    curve = [(t, 100.0 * abs(o - b) / abs(o) if abs(o) > 1e-9 else 0.0) for t, o, b in progress]
    if len(curve) > 40:
        step = len(curve) / 40.0
        curve = [curve[int(i * step)] for i in range(40)] + [curve[-1]]
    return {"n": n, "budget_s": budget_s, "status": res.status, "proven_optimal": res.status == "OPTIMAL",
            "placed": len(res.assignments), "wall_s": round(wall, 1), "final_gap_pct": round(res.gap_pct, 2),
            "first_plan_s": round(progress[0][0], 1) if progress else None,
            "within_10_s": _first_within(progress, 10.0), "within_5_s": _first_within(progress, 5.0),
            "within_1_s": _first_within(progress, 1.0), "windows": res.n_windows_considered, "block_cap_per_day": cap,
            "curve": [(round(t, 1), round(g, 2)) for t, g in curve],
            "heuristic": {"placed": placed_h, "wall_s": round(heur_s, 2), "referee": ref_heur},
            "referee": ref_solver, "jobs_per_s_solver": round(len(res.assignments) / max(wall, 1e-6), 2)}
