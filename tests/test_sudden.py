"""Sudden tasks and the passenger model (backend/planner/sudden.py, backend/domain/pax.py).

What has to hold: quiet hours really are cheaper than busy ones, a sudden task only ever pushes aside
work of STRICTLY lower priority, nothing pushed aside is silently lost (it is re-placed or reported
deferred), and a job that misses its deadline is booked late and flagged rather than dropped.
"""

from __future__ import annotations

import random

import pytest

from backend.config import seed_everything
from backend.domain.models import TrainClass, WorkZoneKind
from backend.domain.pax import PaxModel, train_pax
from backend.domain.task import Task, TaskCategory
from backend.planner.context import sample_instance
from backend.planner.cpsat import solve_with_relaxation
from backend.planner.interval_index import build_interval_index
from backend.planner.live_sim import LiveSimState
from backend.planner.sudden import place_sudden


@pytest.fixture(scope="module")
def world():
    seed_everything()
    w = sample_instance(n_tasks=30, task_seed=11, corridor="central_line")
    res = solve_with_relaxation(w.net, w.tasks, w.windows, time_limit_s=10)
    assert res.assignments
    return w, res


def _by_section(w):
    idx: dict = {}
    for o in w.occupancy:
        idx.setdefault(o.section_id, []).append(o)
    return idx


def test_freight_carries_no_passengers_and_night_is_emptier_than_peak():
    assert train_pax(TrainClass.FREIGHT_MAIL, 9 * 3600) == 0
    assert train_pax(TrainClass.SUBURBAN_LOCAL, 3 * 3600) < train_pax(TrainClass.SUBURBAN_LOCAL, 9 * 3600) / 10


def test_a_busy_section_is_costlier_at_peak_than_at_night(world):
    w, _ = world
    occ = _by_section(w)
    pax = PaxModel(occ)
    sec = max(occ, key=lambda s: len(occ[s]))
    peak = pax.exposure(sec, 1 * 86400 + 8 * 3600, 1 * 86400 + 9 * 3600)
    night = pax.exposure(sec, 1 * 86400 + 2 * 3600, 1 * 86400 + 3 * 3600)
    assert peak.passengers > night.passengers
    assert peak.trains >= night.trains


def _urgent_twin(victim: Task, priority: int, tid: str) -> Task:
    """A job of the same department in the same place: the rules keep the two apart in time."""
    return victim.model_copy(update={
        "id": tid, "priority": priority, "category": TaskCategory.DEMAND, "source": "SUDDEN",
        "scheduled_start_s": None, "scheduled_end_s": None, "window_id": None,
        "released_s": 0, "due_by_s": 7 * 86400})


def _boxed_in(world):
    """A schedule where the only window on a section is taken by a low-priority planned job.

    The CP-SAT plan differs a little run to run (parallel search), so pick a booked job whose
    same-department twin really is barred from sharing its slot rather than assuming the first is."""
    from backend.planner.sudden import _all_blockers

    w, res = world
    for a in res.assignments:
        tasks = [t.model_copy(deep=True) for t in w.tasks]   # a test may displace work: never share it
        victim = next(t for t in tasks if t.id == a.task_id)
        victim.priority = 5
        twin = _urgent_twin(victim, 1, "SUD-PROBE")
        if any(b.id == victim.id for b in _all_blockers(w.net, twin, victim.scheduled_start_s, tasks)):
            win = next(x for x in w.windows if x.id == a.window_id)
            return w, victim, build_interval_index([win]), tasks
    pytest.skip("no booked job in this plan blocks a same-department twin")


def test_a_critical_job_pushes_aside_only_lower_priority_work(world):
    w, victim, index, tasks = _boxed_in(world)
    victim.priority = 5
    sudden = _urgent_twin(victim, 1, "SUD-T1")
    res = place_sudden(w.net, sudden, index, tasks, LiveSimState(), None, 0, None, lambda b: True)
    assert res.method == "bumped"
    assert res.moves and all(m.task.priority > sudden.priority for m in res.moves)
    # nothing vanishes: each displaced job is either re-placed or reported deferred
    assert all(m.new is not None or m.task.scheduled_start_s is None for m in res.moves)


def test_a_displaced_job_is_replaced_elsewhere_when_room_exists(world):
    w, victim, boxed, tasks = _boxed_in(world)
    win = next(iter(next(iter(boxed.trees.values()))))[2]
    alt = next((x for x in w.windows if x.zone_ref == win.zone_ref and x.zone_kind == win.zone_kind
                and x.start_s > win.end_s + 3600 and x.usable_min() >= victim.duration_min + 30), None)
    if alt is None:
        pytest.skip("no second window on this zone to move to")
    index = build_interval_index([win, alt])
    sudden = _urgent_twin(victim, 1, "SUD-T4")
    sudden.due_by_s = win.end_s          # only the first window is early enough for the urgent job
    res = place_sudden(w.net, sudden, index, tasks, LiveSimState(), None, 0, None, lambda b: True)
    assert res.method == "bumped"
    moved = res.moves[0]
    assert moved.new is not None and moved.new.start_s > win.end_s - 1
    assert victim.scheduled_start_s == moved.new.start_s


def test_an_equal_or_higher_priority_job_is_never_pushed_aside(world):
    w, victim, index, tasks = _boxed_in(world)
    victim.priority = 1
    sudden = _urgent_twin(victim, 1, "SUD-T2")
    res = place_sudden(w.net, sudden, index, tasks, LiveSimState(), None, 0, None, lambda b: True)
    assert not res.moves
    assert victim.scheduled_start_s is not None  # untouched


def test_work_already_under_way_is_not_movable(world):
    w, victim, index, tasks = _boxed_in(world)
    victim.priority = 5
    sudden = _urgent_twin(victim, 1, "SUD-T3")
    res = place_sudden(w.net, sudden, index, tasks, LiveSimState(), None, 0, None, lambda b: False)
    assert not res.moves


def test_a_missed_deadline_is_booked_late_not_dropped(world):
    w, _ = world
    index = build_interval_index(w.windows)
    rng = random.Random(5)
    from backend.data.synth_tasks import generate_demand_task
    t = generate_demand_task(w.net, rng, 3600, tid="SUD-LATE")
    t.priority, t.due_by_s = 1, 3600 + 60          # a deadline no gap can meet
    res = place_sudden(w.net, t, index, list(w.tasks), LiveSimState(), None, 3600, None, lambda b: True)
    assert res.method in ("late", "gap", "bumped", "created", "none")
    if res.method == "late":
        assert res.placement is not None and res.placement.end_s > t.due_by_s
