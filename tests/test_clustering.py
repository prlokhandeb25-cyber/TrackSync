"""Job clustering (backend/planner/clustering.py): grouping by position, cut at a distance."""

from __future__ import annotations

import pytest

from backend.config import seed_everything
from backend.domain.models import WorkZoneKind
from backend.domain.network import build_network
from backend.domain.task import Department, Task, WorkZone
from backend.planner.clustering import cluster_tasks


@pytest.fixture(scope="module")
def net():
    seed_everything()
    return build_network("central_line")


def _task(tid: str, dept: Department, code: str, section: str) -> Task:
    return Task(id=tid, task_type=code, department=dept, duration_min=40,
                zone=WorkZone(kind=WorkZoneKind.SECTION, ref=section))


def test_every_task_lands_in_exactly_one_cluster(net):
    sections = list(net.sections)[:12]
    tasks = [_task(f"T{i}", Department.PWI, "PWI_JOINT", s) for i, s in enumerate(sections)]
    clusters = cluster_tasks(net, tasks, cut_km=5.0)
    seen = [tid for c in clusters for tid in c.task_ids]
    assert sorted(seen) == sorted(t.id for t in tasks)


def test_neighbouring_jobs_group_and_distant_jobs_do_not(net):
    first, second = list(net.sections)[0], list(net.sections)[1]
    far = list(net.sections)[-1]
    tasks = [
        _task("A", Department.PWI, "PWI_JOINT", first),
        _task("B", Department.S_AND_T, "SNT_TRACK_CIRCUIT", second),
        _task("C", Department.OWD, "OWD_DROPPER", far),
    ]
    clusters = cluster_tasks(net, tasks, cut_km=5.0)
    by_task = {tid: c.id for c in clusters for tid in c.task_ids}
    assert by_task["A"] == by_task["B"], "adjacent sections should share a cluster"
    assert by_task["A"] != by_task["C"], "a section tens of km away should not"


def test_a_tighter_cut_never_produces_fewer_clusters(net):
    sections = list(net.sections)[:20]
    tasks = [_task(f"T{i}", Department.PWI, "PWI_JOINT", s) for i, s in enumerate(sections)]
    loose = len(cluster_tasks(net, tasks, cut_km=15.0))
    tight = len(cluster_tasks(net, tasks, cut_km=2.0))
    assert tight >= loose


def test_empty_and_single_task_are_handled(net):
    assert cluster_tasks(net, []) == []
    one = [_task("solo", Department.OWD, "OWD_DROPPER", list(net.sections)[0])]
    assert len(cluster_tasks(net, one)) == 1
