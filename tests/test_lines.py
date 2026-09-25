"""Work on one exact line of a section: compatibility, planning, and rerouting are all per line."""

from __future__ import annotations

import pytest

from backend.domain.compatibility import Verdict, compatibility
from backend.domain.models import TrainClass, WorkZoneKind
from backend.domain.task import Department, Task, TaskCategory, WorkZone


@pytest.fixture(scope="module")
def world():
    from backend.api.state import ensure_world
    return ensure_world()


def _job(tid, dept, code, sec, track):
    return Task(id=tid, task_type=code, department=dept, zone=WorkZone(kind=WorkZoneKind.SECTION, ref=sec), duration_min=60,
                priority=3, category=TaskCategory.PLANNED, track=track)


def _four_track_section(world):
    return next(s for s in world.net.sections.values() if len(s.tracks) == 4)


def test_different_lines_of_one_section_can_share_the_time(world):
    s = _four_track_section(world)
    a = _job("A", Department.PWI, "PWI_TAMPING", s.id, "UP_SLOW")
    b = _job("B", Department.OWD, "OWD_INSULATOR", s.id, "DN_SLOW")
    r = compatibility(world.net, a, b)
    assert r.value is Verdict.COMPATIBLE and r.rule_id == "R5"


def test_the_same_line_or_an_unnamed_line_is_still_the_old_rule(world):
    s = _four_track_section(world)
    same = compatibility(world.net, _job("A", Department.PWI, "PWI_TAMPING", s.id, "UP_SLOW"), _job("B", Department.OWD, "OWD_INSULATOR", s.id, "UP_SLOW"))
    unnamed = compatibility(world.net, _job("A", Department.PWI, "PWI_TAMPING", s.id, "UP_SLOW"), _job("B", Department.OWD, "OWD_INSULATOR", s.id, None))
    assert same.value is Verdict.REQUIRES_IWP and unnamed.value is Verdict.REQUIRES_IWP
    two_pwi = compatibility(world.net, _job("A", Department.PWI, "PWI_TAMPING", s.id, "UP_SLOW"), _job("B", Department.PWI, "PWI_BALLAST", s.id, "UP_SLOW"))
    assert two_pwi.value is Verdict.INCOMPATIBLE


def test_a_named_line_only_uses_that_lines_gaps(world):
    from backend.planner.cpsat import eligible_windows
    s = _four_track_section(world)
    t = _job("A", Department.PWI, "PWI_TAMPING", s.id, "UP_FAST")
    got = eligible_windows(t, world.windows)
    assert got and {w.track for w in got} == {"UP_FAST"}
    t.track = None
    assert {w.track for w in eligible_windows(t, world.windows)} > {"UP_FAST"}


def _occ():
    from backend.api.routes import _occupancy_by_section
    return _occupancy_by_section()


def test_closing_one_line_moves_only_that_lines_trains(world):
    from backend.planner.active_reroute import plan_block_reroutes
    s = _four_track_section(world)
    occ = _occ().get(s.id, [])
    week = {t.id: t for t in world.week}
    b = plan_block_reroutes(world.net, week, occ, s, 9 * 3600, 10 * 3600 + 1800, "UP_SLOW")
    assert b.track_swap is not None and b.track_swap["blocked_track"] == "UP_SLOW"
    assert b.track_swap["swap_to_track"] == "DN_SLOW"                        # locals: the opposite line of their own pair
    on_line = {o.train_id for o in occ if o.track == "UP_SLOW" and o.enter_s < 10 * 3600 + 1800 and o.exit_s > 9 * 3600}
    assert {t["train_id"] for t in b.track_swap["trains"]} <= on_line          # nothing from the other lines is touched
    assert all(t["delay_min"] >= 0 for t in b.track_swap["trains"])
    assert not any(r["train_class"] == TrainClass.SUBURBAN_LOCAL.value for r in b.reroutes)   # locals are never rerouted


def test_a_closed_fast_line_sends_through_trains_to_the_slow_line_or_round(world):
    from backend.planner.active_reroute import partner_line, plan_block_reroutes
    s = _four_track_section(world)
    assert partner_line(s, "UP_FAST", True) == ("UP_SLOW", "slow_line")
    assert partner_line(s, "UP_FAST", False) == ("DN_FAST", "single_line")      # a local never leaves its own kind of line
    occ = _occ().get(s.id, [])
    b = plan_block_reroutes(world.net, {t.id: t for t in world.week}, occ, s, 9 * 3600, 10 * 3600, "UP_FAST")
    for t in (b.track_swap or {}).get("trains", []):
        assert t["chosen"] == "swap" and t["to"] in ("UP_SLOW", "DN_FAST")


def test_no_line_named_keeps_the_old_whole_section_behaviour(world):
    from backend.planner.active_reroute import plan_block_reroutes
    s = _four_track_section(world)
    b = plan_block_reroutes(world.net, {t.id: t for t in world.week}, _occ().get(s.id, []), s, 9 * 3600, 10 * 3600)
    assert b.section_id == s.id                                                # unchanged path still works
