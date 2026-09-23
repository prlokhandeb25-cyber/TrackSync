"""The live Operations-page simulation (backend/planner/live_sim.py).

Three things matter here: the Max-to-Min ordering is real, a placement never contradicts what
the department-compatibility rule engine would say about the same pair (it reuses that engine
rather than a parallel simplified check), and the simulation never moves a task outside the
zone it was generated for — the module never touches train rerouting, so the SUBURBAN_LOCAL
guardrail in backend/planner/rerouting.py does not need to be re-asserted here, but "stays in
its own zone" is the analogous property this module owns.
"""

from __future__ import annotations

import random

import pytest

from backend.config import seed_everything
from backend.domain.compatibility import Verdict, compatibility
from backend.planner.context import sample_instance
from backend.planner.cpsat import solve_with_relaxation
from backend.planner.interval_index import build_interval_index
from backend.planner.live_sim import (
    LiveSimState,
    alns_lite_insert,
    order_max_to_min,
    random_task,
)


@pytest.fixture(scope="module")
def world():
    seed_everything()
    w = sample_instance(n_tasks=30, task_seed=11, corridor="central_line")
    res = solve_with_relaxation(w.net, w.tasks, w.windows, time_limit_s=10)
    assert res.assignments, "fixture needs a real plan so committed tasks carry real times"
    return w


def test_order_max_to_min_sorts_longest_first(world):
    rng = random.Random(1)
    batch = [random_task(world.net, rng, at_s=0, seq=i) for i in range(6)]
    ordered = order_max_to_min(batch)
    durations = [t.duration_min for t in ordered]
    assert durations == sorted(durations, reverse=True)


def test_placements_never_stay_outside_their_own_zone(world):
    index = build_interval_index(world.windows)
    sim_state = LiveSimState()
    rng = random.Random(2)
    for i in range(25):
        t = random_task(world.net, rng, at_s=0, seq=i)
        placement = alns_lite_insert(world.net, t, index, world.tasks, sim_state)
        if placement.placed:
            assert placement.window.zone_ref == t.zone.ref


def test_placements_never_conflict_with_the_committed_plan_or_each_other(world):
    index = build_interval_index(world.windows)
    sim_state = LiveSimState()
    rng = random.Random(3)

    for i in range(40):
        t = random_task(world.net, rng, at_s=0, seq=i)
        alns_lite_insert(world.net, t, index, world.tasks, sim_state)

    placed = [p.task for p in sim_state.placed if p.placed]
    everything = world.tasks + placed

    checked = 0
    for i, a in enumerate(everything):
        if a.scheduled_start_s is None:
            continue
        for b in everything[i + 1:]:
            if b.scheduled_start_s is None:
                continue
            if not (a.zone.endpoints & b.zone.endpoints):
                continue
            checked += 1
            verdict = compatibility(world.net, a, b)
            assert verdict.value is not Verdict.INCOMPATIBLE, (
                f"{a.id} and {b.id} were both left scheduled but the rule engine "
                f"considers them incompatible: {verdict.reason}"
            )
    assert checked > 0, "fixture should exercise at least one interacting pair"
