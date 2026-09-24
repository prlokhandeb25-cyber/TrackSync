"""The four proposed methods: crew-history buffers, bundling, the digital twin, predictive blocks.

What has to hold: the estimator recovers the (hidden) crew behaviour from history; a buffer really is
reserved by the solver and checked by the referee; bundling never makes a plan worse or illegal; the twin
never reroutes a suburban local (CLAUDE.md invariant) and its responses genuinely differ; and warning
early never costs more emergencies than not warning.
"""

from __future__ import annotations

import pytest

from backend.config import seed_everything
from backend.domain.models import TrainClass
from backend.planner.bundle import bundle_plan
from backend.planner.context import sample_instance
from backend.planner.cpsat import solve_with_relaxation
from backend.planner.crew_profile import TRUE_MEAN, CrewModel, synthetic_history
from backend.planner.verify import verify_plan


@pytest.fixture(scope="module")
def world():
    seed_everything()
    w = sample_instance(n_tasks=30, task_seed=11, corridor="central_line")
    occ: dict = {}
    for o in w.occupancy:
        occ.setdefault(o.section_id, []).append(o)
    return w, occ


def test_the_estimator_recovers_the_crew_table_from_history():
    m = CrewModel(synthetic_history(600))
    for key, truth in TRUE_MEAN.items():
        assert abs(m.stats[key].mean - truth) < 0.06, (key, m.stats[key].mean, truth)
    # wet weather costs the outdoor crews more, and the buffer follows
    assert m.buffer_min("OWD", True, 120) > m.buffer_min("OWD", False, 120) >= 0
    assert m.buffer_min("PWI", True, 100) <= 50                       # capped at half the job


def test_a_buffer_is_reserved_by_the_solver_and_passes_the_referee(world):
    w, occ = world
    tasks = [t.model_copy(deep=True) for t in w.tasks]
    for t in tasks:
        t.scheduled_start_s = t.scheduled_end_s = None
        t.buffer_min = 15
    res = solve_with_relaxation(w.net, tasks, w.windows, time_limit_s=10)
    assert res.assignments
    by = {t.id: t for t in tasks}
    assert all(a.end_s - a.start_s == by[a.task_id].reserved_min * 60 for a in res.assignments)
    assert verify_plan(w.net, tasks, res.assignments, w.windows, occ).ok


def test_bundling_never_adds_blocks_and_stays_legal(world):
    w, occ = world
    res = solve_with_relaxation(w.net, w.tasks, w.windows, time_limit_s=10)
    new, rep = bundle_plan(w.net, w.tasks, res.assignments, w.windows, occ)
    assert rep.blocks_after <= rep.blocks_before
    assert rep.held_min_after <= rep.held_min_before
    assert verify_plan(w.net, w.tasks, new, w.windows, occ).ok
    assert {a.task_id for a in new} == {a.task_id for a in res.assignments}     # nothing lost or invented


def test_the_twin_never_reroutes_a_local_and_its_responses_differ(world):
    from backend.planner.twin import Twin, closure_ripple

    w, _ = world
    by_train = {}
    for o in w.occupancy:
        by_train[o.train_id] = o.train_class
    asked = []

    def divert(tid: str):
        asked.append(tid)
        return 5.0

    tw = Twin(w.occupancy)
    sec = next(s for s in w.net.sections.values() if len(s.tracks) >= 2)
    tracks = sorted(sec.tracks)
    r = closure_ripple(tw, sec.id, {tracks[0]}, 1 * 86400 + 12 * 3600, 90, divert, (tracks[0], tracks[1]), scenarios=4)
    assert all(by_train[t] is not TrainClass.SUBURBAN_LOCAL for t in asked), "a local was offered for rerouting"
    pol = r["policies"]
    assert set(pol) == {"HOLD", "DIVERT", "DIVERT_SINGLE"}
    assert all(v["pax_min"] >= 0 for v in pol.values())
    assert len({round(v["pax_min"]) for v in pol.values()}) > 1               # the choice actually matters


def test_early_warning_never_causes_more_emergencies():
    from backend.api.state import ensure_interval_index, ensure_plan, ensure_world, get_pax, make_creator
    from backend.planner.predictive import predictive_experiment

    w = ensure_world()
    ensure_plan()
    r = predictive_experiment(w.net, ensure_interval_index(), [t for t in w.tasks if t.scheduled_start_s is not None],
                              make_creator(), get_pax(), n_events=24, seed=1)
    em = [x["emergencies"] for x in r["predictive"]]
    assert em == sorted(em, reverse=True)                                     # more warning, fewer emergencies
    assert all(e <= r["reactive"]["emergencies"] for e in em)
    assert r["reactive"]["emergencies"] == r["failures"]                      # with no warning, every failure is one
