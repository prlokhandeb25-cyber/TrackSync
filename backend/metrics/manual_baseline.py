from typing import List, Dict, Any
from backend.domain.task import Task, TaskCategory, Department
from backend.gaps.gap_engine import CandidateWindow, GapType

class ManualBaselinePlanner:
    """
    Simulates today's decentralised manual planning baseline:
    - Night windows and Sunday megablocks ONLY (0% micro-gap usage).
    - FCFS department scheduling.
    - Cross-department conflicts incur 4h manual coordination delay per conflict.
    - Unplanned demand tasks wait for next weekly planning cycle (up to 7 days).
    """

    def __init__(self, manual_coordination_hours_per_conflict: float = 4.0):
        self.manual_coordination_hours = manual_coordination_hours_per_conflict

    def plan_weekly(
        self,
        tasks: List[Task],
        candidate_windows: List[CandidateWindow]
    ) -> Dict[str, Any]:
        # Filter candidate windows to NIGHT_WINDOW and MEGABLOCK only
        traditional_windows = [w for w in candidate_windows if w.gap_type in (GapType.NIGHT_WINDOW, GapType.MEGABLOCK)]

        scheduled_tasks = {}
        conflicts_count = 0
        total_coordination_hours = 0.0

        windows_by_sec = {}
        for w in traditional_windows:
            if w.section_id not in windows_by_sec:
                windows_by_sec[w.section_id] = []
            windows_by_sec[w.section_id].append(w)

        dept_allocated_sections = {}

        for task in tasks:
            sec_windows = windows_by_sec.get(task.section_id, [])

            # Check conflict with other departments already scheduled in same section
            if task.section_id in dept_allocated_sections:
                prev_dept = dept_allocated_sections[task.section_id]
                if prev_dept != task.department:
                    conflicts_count += 1
                    total_coordination_hours += self.manual_coordination_hours

            dept_allocated_sections[task.section_id] = task.department

            # Fit into first available traditional window
            for win in sec_windows:
                if task.duration_min <= win.usable_min:
                    scheduled_tasks[task.id] = {
                        "start_min": win.start_min + 15,
                        "end_min": win.start_min + 15 + task.duration_min,
                        "window_id": win.id,
                        "is_micro_gap": False
                    }
                    break

        return {
            "scheduled_count": len(scheduled_tasks),
            "conflicts_count": conflicts_count,
            "total_coordination_hours": total_coordination_hours,
            "micro_gap_tasks_count": 0,
            "scheduled_tasks": scheduled_tasks
        }
