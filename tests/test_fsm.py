import pytest
from backend.domain.network import TrackStatus, Section
from backend.domain.task import Task, Department, TaskCategory, WorkZoneType
from backend.domain.fsm import TrackStatusFSM, InvalidStateTransition

def test_valid_state_transitions():
    assert TrackStatusFSM.transition(TrackStatus.FIT, TrackStatus.SICK) == TrackStatus.SICK
    assert TrackStatusFSM.transition(TrackStatus.SICK, TrackStatus.CAUTION_ORDER) == TrackStatus.CAUTION_ORDER
    assert TrackStatusFSM.transition(TrackStatus.CAUTION_ORDER, TrackStatus.FIT) == TrackStatus.FIT
    assert TrackStatusFSM.transition(TrackStatus.STOP_AND_START, TrackStatus.CAUTION_ORDER) == TrackStatus.CAUTION_ORDER

def test_invalid_state_transitions():
    with pytest.raises(InvalidStateTransition):
        TrackStatusFSM.transition(TrackStatus.FIT, TrackStatus.CAUTION_ORDER)

    with pytest.raises(InvalidStateTransition):
        TrackStatusFSM.transition(TrackStatus.FIT, TrackStatus.STOP_AND_START)

def test_handle_work_completion():
    sec = Section(id="SEC_TEST", from_station="A", to_station="B", length_km=5.0, line_speed_kmph=100, status=TrackStatus.SICK)
    task = Task(
        id="TASK_TEST_1",
        department=Department.PWI,
        task_type="rail_renewal",
        section_id="SEC_TEST",
        duration_min=60,
        scheduled_end_min=300
    )

    # Sample outcome with deterministic seed
    new_status, followup = TrackStatusFSM.handle_work_completion(sec, task, allocated_window_min=60.0)
    assert sec.status in (TrackStatus.FIT, TrackStatus.CAUTION_ORDER, TrackStatus.STOP_AND_START)
    if sec.status in (TrackStatus.CAUTION_ORDER, TrackStatus.STOP_AND_START):
        assert followup is not None
        assert followup.id == "FOLLOWUP_TASK_TEST_1"
