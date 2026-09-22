"""Track status FSM (SPEC §5.3), including every illegal transition."""

from __future__ import annotations

import random

import pytest

from backend.domain.fsm import (
    Event,
    IllegalTransition,
    StatusRegistry,
    complete_followup,
    complete_work,
    sample_outcome,
)
from backend.domain.models import TrackStatus, WorkZoneKind
from backend.domain.task import Department, Task, TaskCategory, WorkZone

ZONE = "GC-TNA"


def zone() -> WorkZone:
    return WorkZone(kind=WorkZoneKind.SECTION, ref=ZONE)


def a_task(tid: str = "T1", ttype: str = "PWI_TAMPING", dur: int = 90) -> Task:
    return Task(id=tid, task_type=ttype, department=Department.PWI, zone=zone(), duration_min=dur)


@pytest.fixture
def reg() -> StatusRegistry:
    r = StatusRegistry()
    r.set_initial(ZONE, TrackStatus.FIT)
    return r


# ------------------------------------------------------------------------- legal transitions


def test_fit_to_sick_on_defect(reg):
    tr = reg.apply(ZONE, Event.DEFECT_REPORTED, 0, TrackStatus.SICK)
    assert tr.from_status is TrackStatus.FIT
    assert reg.get(ZONE) is TrackStatus.SICK


def test_scheduling_a_task_does_not_change_status(reg):
    reg.apply(ZONE, Event.DEFECT_REPORTED, 0, TrackStatus.SICK)
    reg.apply(ZONE, Event.TASK_SCHEDULED, 60, TrackStatus.SICK)
    assert reg.get(ZONE) is TrackStatus.SICK


@pytest.mark.parametrize("outcome", [TrackStatus.FIT, TrackStatus.CAUTION_ORDER,
                                     TrackStatus.STOP_AND_START])
def test_work_completes_to_each_of_the_three_outcomes(reg, outcome):
    reg.apply(ZONE, Event.DEFECT_REPORTED, 0, TrackStatus.SICK)
    reg.apply(ZONE, Event.WORK_COMPLETED, 3600, outcome)
    assert reg.get(ZONE) is outcome


def test_followup_clears_a_caution_order(reg):
    reg.apply(ZONE, Event.DEFECT_REPORTED, 0, TrackStatus.SICK)
    reg.apply(ZONE, Event.WORK_COMPLETED, 3600, TrackStatus.CAUTION_ORDER)
    t = a_task("FU")
    complete_followup(reg, t, 7200, random.Random(1))
    assert reg.get(ZONE) is TrackStatus.FIT


def test_followup_on_stop_and_start_lifts_by_one_step(reg):
    reg.apply(ZONE, Event.DEFECT_REPORTED, 0, TrackStatus.SICK)
    reg.apply(ZONE, Event.WORK_COMPLETED, 3600, TrackStatus.STOP_AND_START)
    complete_followup(reg, a_task("FU"), 7200, random.Random(0))
    assert reg.get(ZONE) in (TrackStatus.CAUTION_ORDER, TrackStatus.FIT)


def test_defect_can_be_reported_on_a_restricted_section(reg):
    reg.apply(ZONE, Event.DEFECT_REPORTED, 0, TrackStatus.SICK)
    reg.apply(ZONE, Event.WORK_COMPLETED, 3600, TrackStatus.CAUTION_ORDER)
    reg.apply(ZONE, Event.DEFECT_REPORTED, 7200, TrackStatus.SICK)
    assert reg.get(ZONE) is TrackStatus.SICK


# ----------------------------------------------------------------------- illegal transitions


def test_cannot_complete_work_on_a_fit_section(reg):
    with pytest.raises(IllegalTransition):
        reg.apply(ZONE, Event.WORK_COMPLETED, 100, TrackStatus.FIT)


def test_cannot_schedule_a_task_on_a_fit_section(reg):
    with pytest.raises(IllegalTransition):
        reg.apply(ZONE, Event.TASK_SCHEDULED, 100, TrackStatus.SICK)


def test_cannot_start_work_on_a_fit_section(reg):
    with pytest.raises(IllegalTransition):
        reg.apply(ZONE, Event.WORK_STARTED, 100, TrackStatus.SICK)


def test_cannot_run_a_followup_on_a_fit_section(reg):
    with pytest.raises(IllegalTransition):
        reg.apply(ZONE, Event.FOLLOWUP_COMPLETED, 100, TrackStatus.FIT)


def test_cannot_run_a_followup_on_a_sick_section(reg):
    reg.apply(ZONE, Event.DEFECT_REPORTED, 0, TrackStatus.SICK)
    with pytest.raises(IllegalTransition):
        complete_followup(reg, a_task("FU"), 100, random.Random(0))


def test_cannot_report_a_defect_on_an_already_sick_section(reg):
    reg.apply(ZONE, Event.DEFECT_REPORTED, 0, TrackStatus.SICK)
    with pytest.raises(IllegalTransition):
        reg.apply(ZONE, Event.DEFECT_REPORTED, 60, TrackStatus.SICK)


def test_unknown_event_is_rejected(reg):
    with pytest.raises(IllegalTransition):
        reg.apply(ZONE, "teleport", 0, TrackStatus.FIT)


# --------------------------------------------------------------- completion semantics


def test_completion_clears_the_task_and_logs_the_transition(reg):
    reg.apply(ZONE, Event.DEFECT_REPORTED, 0, TrackStatus.SICK)
    t = a_task()
    tr, _ = complete_work(reg, t, 3600, random.Random(7))
    assert t.completed is True
    assert t.outcome is not None
    assert reg.log[-1] is tr
    assert tr.task_id == t.id


def test_degraded_outcome_raises_a_followup_task(reg):
    reg.apply(ZONE, Event.DEFECT_REPORTED, 0, TrackStatus.SICK)
    t = a_task(ttype="PWI_TAMPING", dur=180)
    # Squeeze the job hard so a degraded outcome is near-certain.
    _, follow_up = complete_work(reg, t, 3600, random.Random(3), allotted_min=10)
    if t.outcome is TrackStatus.FIT:
        assert follow_up is None
    else:
        assert follow_up is not None
        assert follow_up.is_followup is True
        assert follow_up.zone.ref == ZONE
        assert follow_up.priority <= t.priority


def test_squeezing_a_job_into_a_short_gap_degrades_outcomes_more_often():
    """Micro-gap scheduling is a real option that carries a real risk; the model prices it."""
    t = a_task(ttype="PWI_TAMPING", dur=120)
    rng = random.Random(42)
    full = [sample_outcome(t, 120, rng) for _ in range(400)]
    rng = random.Random(42)
    squeezed = [sample_outcome(t, 30, rng) for _ in range(400)]

    fit_full = full.count(TrackStatus.FIT)
    fit_squeezed = squeezed.count(TrackStatus.FIT)
    assert fit_squeezed < fit_full


def test_outcome_sampling_is_deterministic_under_a_seed():
    t = a_task()
    a = [sample_outcome(t, 60, random.Random(5)) for _ in range(5)]
    b = [sample_outcome(t, 60, random.Random(5)) for _ in range(5)]
    assert a == b


def test_degraded_zones_are_reported(reg):
    reg.apply(ZONE, Event.DEFECT_REPORTED, 0, TrackStatus.SICK)
    reg.apply(ZONE, Event.WORK_COMPLETED, 3600, TrackStatus.CAUTION_ORDER)
    assert reg.degraded_zones() == {ZONE: TrackStatus.CAUTION_ORDER}
