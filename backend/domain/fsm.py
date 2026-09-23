import random
from typing import Tuple, Optional
from backend.domain.network import TrackStatus, Section
from backend.domain.task import Task, TaskCategory, Department, WorkZoneType

class InvalidStateTransition(Exception):
    pass

class TrackStatusFSM:
    """
    Finite State Machine for section track status:
    FIT -> SICK -> CAUTION_ORDER / STOP_AND_START -> FIT
    """

    VALID_TRANSITIONS = {
        TrackStatus.FIT: [TrackStatus.SICK],
        TrackStatus.SICK: [TrackStatus.SICK, TrackStatus.FIT, TrackStatus.CAUTION_ORDER, TrackStatus.STOP_AND_START],
        TrackStatus.CAUTION_ORDER: [TrackStatus.FIT, TrackStatus.SICK],
        TrackStatus.STOP_AND_START: [TrackStatus.CAUTION_ORDER, TrackStatus.FIT, TrackStatus.SICK]
    }

    @staticmethod
    def transition(current: TrackStatus, target: TrackStatus) -> TrackStatus:
        if target not in TrackStatusFSM.VALID_TRANSITIONS.get(current, []):
            raise InvalidStateTransition(f"Illegal transition from {current.value} to {target.value}")
        return target

    @staticmethod
    def sample_work_completion_outcome(
        task: Task,
        allocated_window_min: float,
        seed: Optional[int] = None
    ) -> TrackStatus:
        """
        Samples task outcome on completion based on task type and gap ratio.
        If allocated window is tight (allocated < required duration), probability of degraded state increases.
        """
        if seed is not None:
            random.seed(seed)

        ratio = allocated_window_min / max(1.0, float(task.duration_min))

        # Base probabilities
        if ratio >= 1.0:
            prob_fit = 0.85
            prob_caution = 0.12
            prob_stop_start = 0.03
        elif ratio >= 0.8:
            prob_fit = 0.50
            prob_caution = 0.35
            prob_stop_start = 0.15
        else:
            prob_fit = 0.20
            prob_caution = 0.50
            prob_stop_start = 0.30

        roll = random.random()
        if roll < prob_fit:
            return TrackStatus.FIT
        elif roll < prob_fit + prob_caution:
            return TrackStatus.CAUTION_ORDER
        else:
            return TrackStatus.STOP_AND_START

    @staticmethod
    def handle_work_completion(
        section: Section,
        task: Task,
        allocated_window_min: float
    ) -> Tuple[TrackStatus, Optional[Task]]:
        """
        Executes work completion. Returns (new_section_status, follow_up_task).
        """
        outcome = TrackStatusFSM.sample_work_completion_outcome(task, allocated_window_min)
        new_status = TrackStatusFSM.transition(section.status, outcome)
        section.status = new_status

        followup_task = None
        if new_status in (TrackStatus.CAUTION_ORDER, TrackStatus.STOP_AND_START):
            # Auto-create follow-up task to restore section to FIT
            followup_task = Task(
                id=f"FOLLOWUP_{task.id}",
                department=task.department,
                task_type=f"followup_{task.task_type}",
                section_id=task.section_id,
                work_zone_type=task.work_zone_type,
                work_zone_id=task.work_zone_id,
                duration_min=30,
                priority=min(5, task.priority + 1),
                category=TaskCategory.PLANNED,
                requires_power_block=False,
                requires_traffic_block=True,
                released_at_min=task.scheduled_end_min or 0,
                due_by_min=(task.scheduled_end_min or 0) + 1440
            )

        return new_status, followup_task
