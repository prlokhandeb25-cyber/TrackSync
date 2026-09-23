"""The 15-minute rule, gap creation, and declared compatibility.

Three properties the new pipeline stands on: no window anywhere leaves under 15 minutes of real
work; gap creation never offers a suburban local to the reroute lever and every option it returns
really is long enough; and a department's own "do not work alongside" declaration is honoured
wherever two jobs could overlap.
"""

from __future__ import annotations

import pytest

from backend.config import load_config, seed_everything
from backend.domain.compatibility import Verdict, compatibility
from backend.domain.models import WorkZoneKind
from backend.domain.scoring import pair_verdict, score_tasks
from backend.domain.task import Department, Task, WorkZone
from backend.gaps.creation import RerouteCache, options_for_task, raw_needed_min
from backend.planner.clustering import cluster_tasks
from backend.planner.context import sample_instance


@pytest.fixture(scope="module")
def world():
    seed_everything()
    return sample_instance(n_tasks=20, task_seed=3, corridor="central_line")


def _task(tid: str, dept: Department, code: str, ref: str, allows=None) -> Task:
    return Task(id=tid, task_type=code, department=dept, duration_min=40, allows_with=allows,
                zone=WorkZone(kind=WorkZoneKind.SECTION, ref=ref))


def test_every_window_leaves_at_least_the_minimum_workable_time(world):
    floor = int(load_config()["gaps"]["min_workable_min"])
    assert world.windows
    assert min(w.usable_min() for w in world.windows) >= floor


def test_a_suburban_local_is_never_offered_to_the_reroute_lever(world):
    week = {t.id: t for t in world.week}
    rc = RerouteCache(world.net, week)
    locals_ = [t for t in world.week if not t.reroutable][:20]
    assert locals_
    section = next(iter(world.net.sections))
    assert all(rc.delay_min(t.id, section) is None for t in locals_)


def test_created_options_really_are_long_enough(world):
    occ: dict = {}
    for o in world.occupancy:
        occ.setdefault(o.section_id, []).append(o)
    rc = RerouteCache(world.net, {t.id: t for t in world.week})
    found = []
    for sec in list(world.net.sections.values())[:12]:
        task = _task("X", Department.PWI, "PWI_TAMPING", sec.id)
        task.duration_min = 60
        need = raw_needed_min(task)
        for o in options_for_task(world.net, task, occ.get(sec.id, []), rc,
                                  from_s=86400 + 3600, horizon_days=1):
            assert o.raw_min >= need, f"{o.lever} on {sec.id} is shorter than the job needs"
            assert o.delay_min >= 0
            found.append(o)
    assert found, "somewhere on the corridor a 60 minute window should be openable at night"


def test_a_declaration_keeps_two_departments_apart(world):
    net = world.net
    sec = next(iter(net.sections))
    a = _task("A", Department.PWI, "PWI_JOINT", sec, allows=[Department.S_AND_T])   # OWD not allowed
    b = _task("B", Department.OWD, "OWD_DROPPER", sec)
    r = pair_verdict(net, a, b)
    assert r.value is Verdict.INCOMPATIBLE and r.rule_id == "DECL"

    a_open = _task("A2", Department.PWI, "PWI_JOINT", sec, allows=[Department.OWD])
    assert pair_verdict(net, a_open, b).value is compatibility(net, a_open, b).value


def test_a_job_with_nothing_nearby_scores_a_standalone_hundred(world):
    net = world.net
    first, last = list(net.sections)[0], list(net.sections)[-1]
    tasks = [_task("A", Department.PWI, "PWI_JOINT", first), _task("B", Department.OWD, "OWD_DROPPER", last)]
    scores = score_tasks(net, tasks, cluster_tasks(net, tasks))
    assert scores["A"].standalone and scores["A"].score == 100
