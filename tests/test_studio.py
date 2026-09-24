"""The planning studio: trade-off plans, machine limits, approvals with an audit trail, learning from execution, scale timing.

What has to hold: every trade-off plan and the machine-constrained plan pass the independent referee; the machine checker
catches a double-booked machine and the constrained plan has none; a proposal cannot be applied unless approved with a
reason, applying and reverting restore the plan in force exactly, and an apply is refused while sudden tasks depend on the
plan; the learned buffer is zero with no data and follows the data once there is some; and the scale timing curve is
recorded honestly (a gap that never increases, a proven flag only when the solver said OPTIMAL).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from backend.planner import approvals as AP
from backend.planner import learning as LN
from backend.planner import pareto as PA
from backend.planner import resource_plan as RP
from backend.planner.cpsat import Assignment, build_and_solve
from backend.planner.verify import verify_plan


@pytest.fixture
def tmp_path():
    """A scratch folder that does not depend on pytest's own temp root (locked down on some Windows setups)."""
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture(scope="module")
def live():
    from backend.api.state import ensure_plan, ensure_world, get_pax, occupancy_by_section
    return ensure_world(), ensure_plan(), get_pax(), occupancy_by_section()


@pytest.fixture(scope="module")
def points(live):
    w, plan, pax, occ = live
    return PA.solve_points(w, pax, occ, list(plan.assignments), per_solve_s=6)


def test_every_tradeoff_plan_is_legal_and_dominance_is_computed_correctly(live, points):
    w, plan, pax, occ = live
    assert [p["id"] for p in points["points"]] == [x[0] for x in PA.POINTS]
    for p in points["points"]:
        tasks = [t.model_copy(deep=True) for t in w.tasks]
        assert verify_plan(w.net, tasks, p["assignments"], w.windows, occ).ok, p["id"]
        assert p["placed"] == len(p["assignments"]) and 0.0 <= p["robust"] <= 1.0
    pts = [{"placed": 5, "passengers": 10, "robust": 0.9}, {"placed": 5, "passengers": 12, "robust": 0.9},
           {"placed": 4, "passengers": 5, "robust": 0.9}]
    PA.dominated(pts)
    assert [p["dominated"] for p in pts] == [False, True, False]        # the second is beaten on passengers, the third trades jobs for passengers


def test_machine_checker_catches_a_double_booking_and_the_constrained_plan_has_none(live):
    w, plan, pax, occ = live
    tamp = [t for t in w.tasks if t.task_type == "PWI_TAMPING"][:2]
    assert len(tamp) == 2
    a = Assignment(tamp[0].id, "x", tamp[0].zone.ref, tamp[0].zone.ref, "UP", 1000, 1000 + 3600, "NIGHT_WINDOW", 0)
    b = Assignment(tamp[1].id, "y", tamp[1].zone.ref, tamp[1].zone.ref, "UP", 2000, 2000 + 3600, "NIGHT_WINDOW", 0)
    assert RP.machine_conflicts(w.net, w.tasks, [a, b]), "two overlapping tamping jobs on one machine must conflict"
    assert not RP.machine_conflicts(w.net, w.tasks, [a, b], {"Tamping machine": 2})          # a second machine removes it
    tasks = [t.model_copy(deep=True) for t in w.tasks]
    for t in tasks:
        t.scheduled_start_s = t.scheduled_end_s = None
    res = build_and_solve(w.net, tasks, w.windows, 15, pax=pax, extra=RP.make_extra(w.net))
    assert not RP.machine_conflicts(w.net, tasks, res.assignments)
    assert verify_plan(w.net, [t.model_copy(deep=True) for t in w.tasks], res.assignments, w.windows, occ).ok


def test_the_extra_hook_is_off_by_default_so_the_live_model_is_unchanged(live):
    w, plan, pax, occ = live
    a = build_and_solve(w.net, [t.model_copy(deep=True) for t in w.tasks], w.windows, 5, pax=pax)
    b = build_and_solve(w.net, [t.model_copy(deep=True) for t in w.tasks], w.windows, 5, pax=pax, extra=None, progress=None)
    assert {x.task_id for x in a.assignments} and a.status == b.status


def test_approvals_need_a_reason_apply_only_after_approval_and_revert_restores_exactly(live, points, tmp_path, monkeypatch):
    from backend.api.state import STATE
    monkeypatch.setattr(AP, "AUDIT_PATH", tmp_path / "audit.jsonl")
    AP._AUDIT.clear()
    pt = points["points"][3]
    before = sorted((a.task_id, a.start_s, a.end_s, a.track) for a in STATE.plan.assignments)
    sched_before = sorted((t.id, t.scheduled_start_s) for t in live[0].tasks)
    pr = AP.propose("pareto", "test", "tester", pt["assignments"], {k: pt[k] for k in ("placed", "passengers", "robust", "status", "gap_pct", "objective")}, pt["diff"])
    with pytest.raises(ValueError):
        AP.apply(pr["id"], "tester")                                    # not approved yet
    with pytest.raises(ValueError):
        AP.decide(pr["id"], True, "   ", "tester")                      # no reason given
    AP.decide(pr["id"], True, "fewer passengers is worth one job", "tester")
    with pytest.raises(ValueError):
        AP.decide(pr["id"], False, "changed my mind", "tester")         # decided once
    STATE.overrides["X"] = None
    with pytest.raises(ValueError):
        AP.apply(pr["id"], "tester")                                    # sudden tasks depend on the plan
    STATE.overrides.pop("X")
    AP.apply(pr["id"], "tester")
    assert len(STATE.plan.assignments) == pt["placed"]
    from backend.api.routes_tasks import schedule_week
    assert schedule_week()["summary"]["placed"] >= pt["placed"]         # the rest of the app keeps working on the new plan
    AP.revert("tester")
    assert sorted((a.task_id, a.start_s, a.end_s, a.track) for a in STATE.plan.assignments) == before
    assert sorted((t.id, t.scheduled_start_s) for t in live[0].tasks) == sched_before
    assert [e["event"] for e in AP.audit()][:4] == ["reverted", "applied", "approved", "proposed"]
    assert (tmp_path / "audit.jsonl").read_text(encoding="utf-8").count("\n") == 4          # written to disk, append-only


def test_learning_starts_neutral_and_follows_the_data(monkeypatch, tmp_path):
    monkeypatch.setattr(LN, "LOG_PATH", tmp_path / "log.jsonl")
    monkeypatch.setattr(LN, "_REAL", [])
    assert all(r["buffer_min_120"] == 0 and r["mean"] == 1.0 for r in LN.estimate("real"))     # no data: no invented buffer
    for i in range(30):
        LN.log_completion(f"T{i}", "OWD", False, 100, 130 + (i % 5))
    row = next(r for r in LN.estimate("real") if r["department"] == "OWD" and not r["rain"])
    assert row["n"] == 30 and 1.2 < row["mean"] < 1.35 and row["buffer_min_120"] > 0
    assert next(r for r in LN.estimate("real") if r["department"] == "PWI" and not r["rain"])["n"] == 0
    assert LN.buffer_min("OWD", False, 120) > LN.buffer_min("PWI", False, 120)
    assert (tmp_path / "log.jsonl").read_text(encoding="utf-8").count("\n") == 30
    with pytest.raises(ValueError):
        LN.log_completion("T", "XXX", False, 60, 60)
    with pytest.raises(ValueError):
        LN.log_completion("T", "PWI", False, 0, 60)


def test_the_simulated_stream_is_separate_and_the_estimate_converges_on_the_hidden_truth(monkeypatch):
    monkeypatch.setattr(LN, "_REAL", [])
    LN.reset_simulated()
    LN.simulate(500)
    assert not LN.records("real") and len(LN.records("simulated")) == 500
    conv = LN.convergence("simulated")
    assert conv[-1]["mean_abs_error"] < conv[0]["mean_abs_error"] and conv[-1]["mean_abs_error"] < 0.05
    LN.reset_simulated()


def test_scale_timing_is_recorded_honestly(live):
    from backend.planner import scale as SC
    r = SC.run_size(live[0], live[2], 40, 8.0)
    assert r["n"] == 40 and r["status"] in ("OPTIMAL", "FEASIBLE")
    gaps = [g for _, g in r["curve"]]
    assert gaps == sorted(gaps, reverse=True)                            # a proven gap only ever tightens
    assert r["proven_optimal"] == (r["status"] == "OPTIMAL")
    assert r["heuristic"]["wall_s"] < r["wall_s"] + 5
