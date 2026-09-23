import numpy as np
from typing import List, Dict, Tuple, Any, Optional
from backend.domain.network import NetworkGraph
from backend.domain.task import Task, TaskCategory, Department
from backend.gaps.gap_engine import CandidateWindow, GapType
from backend.domain.compatibility import DepartmentCompatibilityEngine, CompatibilityVerdictValue

class SchedulingMDP:
    """
    Defines the Markov Decision Process (MDP) state encoding, action masking, and reward logic
    for reactive dispatching.
    """

    STATE_DIM = 64
    MAX_TASKS = 15
    MAX_WINDOWS = 10
    ACTION_DIM = MAX_TASKS * MAX_WINDOWS + 1  # +1 for NO_OP / DEFER action

    def __init__(self, network: NetworkGraph, compatibility_engine: DepartmentCompatibilityEngine):
        self.network = network
        self.comp_engine = compatibility_engine

    def encode_state(
        self,
        current_time_min: int,
        tasks: List[Task],
        candidate_windows: List[CandidateWindow],
        iwp_quota_remaining: int
    ) -> np.ndarray:
        vec = np.zeros(self.STATE_DIM, dtype=np.float32)

        vec[0] = (current_time_min % 1440) / 1440.0   # time of day
        vec[1] = (current_time_min // 1440) / 7.0     # day of week
        vec[2] = len(tasks) / float(self.MAX_TASKS)
        vec[3] = iwp_quota_remaining / 5.0

        sorted_tasks = sorted(tasks, key=lambda t: (t.priority, t.due_by_min))[:self.MAX_TASKS]
        for idx, task in enumerate(sorted_tasks):
            base = 4 + idx * 2
            vec[base] = task.priority / 5.0
            vec[base + 1] = float(task.duration_min) / 300.0

        sorted_windows = candidate_windows[:self.MAX_WINDOWS]
        for idx, win in enumerate(sorted_windows):
            base = 35 + idx * 2
            vec[base] = float(win.usable_min) / 300.0
            vec[base + 1] = 1.0 if win.gap_type == GapType.MICRO_GAP else 0.0

        return vec

    def compute_action_mask(
        self,
        tasks: List[Task],
        candidate_windows: List[CandidateWindow],
        iwp_quota_remaining: int
    ) -> np.ndarray:
        mask = np.zeros(self.ACTION_DIM, dtype=np.float32)
        mask[-1] = 1.0  # NO_OP is always legal

        sorted_tasks = sorted(tasks, key=lambda t: (t.priority, t.due_by_min))[:self.MAX_TASKS]
        sorted_windows = candidate_windows[:self.MAX_WINDOWS]

        for t_idx, task in enumerate(sorted_tasks):
            for w_idx, win in enumerate(sorted_windows):
                action_idx = t_idx * self.MAX_WINDOWS + w_idx

                if task.section_id != win.section_id:
                    continue

                if task.duration_min > win.usable_min:
                    continue

                if not self.comp_engine.check_allotment(task):
                    continue

                mask[action_idx] = 1.0

        return mask

    def calculate_reward(
        self,
        task: Optional[Task],
        chosen_window: Optional[CandidateWindow],
        is_no_op: bool = False
    ) -> float:
        if is_no_op or task is None or chosen_window is None:
            return -2.0

        reward = +20.0 * (6 - task.priority)

        if chosen_window.gap_type == GapType.MICRO_GAP:
            reward += 15.0

        return float(reward)
