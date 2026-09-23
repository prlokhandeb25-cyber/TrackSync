import numpy as np
from typing import List, Dict, Any, Optional
from backend.rl.mdp import SchedulingMDP

class GreedyDispatcher:
    """
    Baseline Heuristic Dispatcher: Selects earliest-usable-gap x highest-priority task,
    respecting strict action masking.
    """

    def predict_action(self, state: np.ndarray, action_mask: np.ndarray) -> int:
        valid_indices = np.where(action_mask > 0.5)[0]
        if len(valid_indices) == 1 and valid_indices[0] == SchedulingMDP.ACTION_DIM - 1:
            return SchedulingMDP.ACTION_DIM - 1  # NO_OP

        # Filter out NO_OP from greedy selection unless it's the only valid action
        non_noop_valid = [idx for idx in valid_indices if idx != SchedulingMDP.ACTION_DIM - 1]
        if not non_noop_valid:
            return SchedulingMDP.ACTION_DIM - 1

        # Select earliest valid task-window index
        return non_noop_valid[0]
