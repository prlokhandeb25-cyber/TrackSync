"""The referee, robust placement and minimum-churn re-planning (verify.py, robustness.py, replan.py).

The referee is only worth having if it can fail, so it is shown catching deliberate violations. Robust
placement must never make a plan worse or illegal. Re-planning must account for every job it was given.
"""

from __future__ import annotations

import copy

import pytest

from backend.config import seed_everything
from backend.domain.models import WorkZoneKind
from backend.domain.task import TASK_TYPES, Department, Task, TaskCategory, WorkZone
from backend.planner.context import sample_instance
from backend.planner.cpsat import solve_with_relaxation
from backend.planner.replan import replan_with_block
from backend.planner.robustness import assess, centre_plan
from backend.planner.verify import verify_plan


@pytest.fixture(scope="module")
def solved():
    seed_everything()
    w = sample_instance(n_tasks=30, task_seed=11, corridor="central_line")
    res = solve_with_relaxation(w.net, w.tasks, w.windows, time_limit_s=10)
    occ: dict = {}
    for o in w.occupancy:
        occ.setdefault(o.section_id, []).append(o)
    assert res.assignments
    return w, res, occ


def test_a_real_plan_passes_the_referee(solved):
    w, res, occ = solved
    rep = verify_plan(w.net, w.tasks, res.assignments, w.windows, occ)
    assert rep.ok, rep.violations[:3]
    assert sum(rep.checks.values()) > 100


def test_the_referee_catches_a_job_outside_its_window(solved):
    w, res, occ = solved
    bad = [copy.copy(a) for a in res.assignments]
    bad[0].start_s -= 3 * 3600
    bad[0].end_s -= 3 * 3600
    rep = verify_plan(w.net, w.tasks, bad, w.windows, occ)
    assert not rep.ok


def test_the_referee_catches_a_train_on_the_track(solved):
    w, res, occ = solved
    a = next(x for x in res.assignments if x.zone_ref in w.net.sections and not x.window_id.startswith("CW-"))
    hit = next(o for o in occ[a.zone_ref] if o.track == a.track)
    bad = [copy.copy(x) for x in res.assignments]
    b = next(x for x in bad if x.task_id == a.task_id)
    dur = b.end_s - b.start_s
    b.start_s, b.end_s = hit.enter_s, hit.enter_s + dur          # right on top of a running train
    rep = verify_plan(w.net, w.tasks, bad, w.windows, occ)
    assert any("train" in v for v in rep.violations)


def test_the_referee_catches_two_incompatible_jobs_overlapping(solved):
    w, res, occ = solved
    by = {t.id: t for t in w.tasks}
    a0 = res.assignments[0]
    t0 = by[a0.task_id]
    twin = t0.model_copy(update={"id": "TWIN-1"})
    tasks = list(w.tasks) + [twin]
    ta = copy.copy(a0)
    ta.task_id = "TWIN-1"                                        # same department, same zone, same instant
    rep = verify_plan(w.net, tasks, list(res.assignments) + [ta], w.windows, occ)
    assert not rep.ok


def test_centring_never_makes_a_plan_worse_or_illegal(solved):
    w, res, occ = solved
    by = {t.id: t for t in w.tasks}
    before = assess(res.assignments, by, occ)
    new, rep = centre_plan(w.net, w.tasks, res.assignments, w.windows, occ)
    after = assess(new, by, occ)
    assert sum(r.p_clear for r in after) >= sum(r.p_clear for r in before) - 1e-9
    assert verify_plan(w.net, w.tasks, new, w.windows, occ).ok
    # the plan itself is untouched: same jobs, same days, same windows
    assert {(a.task_id, a.window_id, a.start_s // 86400) for a in new} == \
           {(a.task_id, a.window_id, a.start_s // 86400) for a in res.assignments}


def test_replanning_accounts_for_every_job_and_moves_few(solved):
    w, res, occ = solved
    tt = next(t for t in TASK_TYPES if t.department is Department.PWI)
    sec = next(iter(w.net.sections))
    nt = Task(id="NEW-1", task_type=tt.code, department=tt.department, zone=WorkZone(kind=WorkZoneKind.SECTION, ref=sec),
              duration_min=60, priority=2, category=TaskCategory.DEMAND, requires_power_block=tt.requires_power_block,
              requires_traffic_block=tt.requires_traffic_block, released_s=0, due_by_s=7 * 86400, source="WHATIF")
    r = replan_with_block(w.net, w.tasks, w.windows, res, nt, [], time_limit_s=10)
    assert r.status in ("OPTIMAL", "FEASIBLE")
    planned = len(res.assignments)
    assert len(r.unchanged) + len(r.moved) + len(r.dropped) == planned
    assert len(r.unchanged) >= planned // 2                    # a new block does not reshuffle the week
