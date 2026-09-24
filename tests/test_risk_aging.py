"""Risk assessment, priority aging, and the everyday phrasings the chatbot has to understand."""

from __future__ import annotations

import pytest

from backend.chat.engine import answer
from backend.config import load_config
from backend.domain.risk import assess_job, assess_pair, band
from backend.domain.task import Department, Task, TaskCategory, WorkZone
from backend.domain.models import WorkZoneKind
from backend.planner import aging


def _task(tid: str, dept: Department, code: str, ref: str = "DR", prio: int = 3, power: bool = False, released: int = 0) -> Task:
    return Task(id=tid, task_type=code, department=dept, zone=WorkZone(kind=WorkZoneKind.STATION_NODE, ref=ref), duration_min=60,
                priority=prio, category=TaskCategory.PLANNED, requires_power_block=power, released_s=released)


def test_bands_follow_the_five_by_five_matrix():
    assert [band(x) for x in (1, 4, 5, 9, 10, 16, 17, 25)] == ["Low", "Low", "Medium", "Medium", "High", "High", "Extreme", "Extreme"]


def test_controls_lower_the_risk_and_time_separation_lowers_it_most():
    a = _task("A", Department.OWD, "OWD_INSULATOR", power=True)
    b = _task("B", Department.PWI, "PWI_TAMPING")
    same = assess_pair(a, b, "REQUIRES_IWP", "SAME_ZONE")
    apart = assess_pair(a, b, "INCOMPATIBLE", "SAME_ZONE")
    assert same["inherent"] == apart["inherent"] == 20                    # 4 x 5, before any control
    assert apart["residual"] < same["residual"] < same["inherent"]        # kept at different times < permit < nothing
    assert any(h["id"] == "electrical" for h in same["hazards"])
    assert all(h["residual"] <= h["inherent"] for h in same["hazards"])


def test_no_electrical_hazard_without_overhead_work():
    r = assess_pair(_task("A", Department.PWI, "PWI_TAMPING"), _task("B", Department.S_AND_T, "SNT_POINT_MACHINE"), "REQUIRES_IWP", "SAME_ZONE")
    assert not any(h["id"] == "electrical" for h in r["hazards"])
    assert any(h["id"] == "signal_fault" for h in r["hazards"])


def test_job_risk_is_the_worst_of_its_pairs():
    t = _task("A", Department.OWD, "OWD_INSULATOR", power=True)
    b = _task("B", Department.PWI, "PWI_TAMPING")
    j = assess_job(t, [("B", assess_pair(t, b, "REQUIRES_IWP", "SAME_ZONE"))])
    assert j["inherent"] >= 20 and j["residual_band"] in ("Medium", "High") and j["controls"]


def test_aging_moves_up_but_never_past_the_floor_or_a_p1():
    floor, hps = int(load_config().get_path("aging.floor", 2)), float(load_config().get_path("aging.hours_per_step", 48))
    t = _task("R", Department.PWI, "PWI_JOINT", prio=5)
    assert aging.effective_priority(t, 0) == 5
    assert aging.effective_priority(t, int(hps * 3600)) == 4
    assert aging.effective_priority(t, int(hps * 3600 * 50)) == floor        # waits a long time: stops at the floor
    assert aging.effective_priority(_task("U", Department.PWI, "PWI_JOINT", prio=1), int(hps * 3600 * 50)) == 1


def test_a_job_pushed_aside_is_protected_next_time():
    aging.reset()
    t = _task("P", Department.PWI, "PWI_JOINT", prio=4)
    assert aging.effective_priority(t, 0) == 4
    aging.record_bump("P")
    assert aging.effective_priority(t, 0) == 3
    aging.reset()


def test_carried_jobs_are_planned_more_urgently_each_week():
    ts = [_task("C1", Department.PWI, "PWI_JOINT", prio=5), _task("C2", Department.PWI, "PWI_JOINT", prio=2)]
    moved = aging.age_carried(ts, {"C1": 1, "C2": 1})
    assert ts[0].priority == 4 and moved == {"C1": 5}
    assert ts[1].priority == 2                                              # already at the floor


# ------------------------------------------------------------------- the chat understands everyday phrasing


@pytest.fixture(scope="module")
def world():
    from backend.api.state import ensure_plan, ensure_world
    w = ensure_world()
    ensure_plan()
    return w


@pytest.mark.parametrize("q,intent", [
    ("how many workers needed for track tamping", "resources"),
    ("how many people for a rail welding job", "resources"),
    ("what equipment is needed for signal cable laying", "resources"),
    ("how long will an OHE wire replacement take with 3 workers", "crew"),
    ("will low priority jobs starve", "aging"),
])
def test_everyday_questions_reach_the_right_handler(world, q, intent):
    assert answer(q, world, None, 25200).intent == intent


def test_add_workers_is_a_change_to_the_normal_crew(world):
    a = answer("what if I add 2 more workers to the tamping job", world, None, 25200)
    assert a.intent == "crew" and "**7** normally → **9** workers" in a.text


def test_welding_is_rail_renewal_and_pantograph_is_overhead(world):
    assert "weld renewal" in answer("how many people for a rail welding job", world, None, 25200).text.lower()
    assert "(ohe)" in answer("crew needed for pantograph inspection", world, None, 25200).text.lower()


def test_together_answer_carries_the_risk(world):
    a = answer("how risky is it if OHE insulator work and tamping happen together at Kurla", world, None, 25200)
    assert a.intent == "together" and "Risk if worked together" in a.text and a.visuals
