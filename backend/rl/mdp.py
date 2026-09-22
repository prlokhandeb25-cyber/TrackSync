"""The dispatching MDP: state encoding, action space, reward, and the legality mask.

<!-- serves: J1 -->

Transfer from the reference paper (arXiv:2409.10589, offline RL for job-shop dispatching):

    JSSP job      ->  maintenance task
    JSSP machine  ->  block corridor time-slot on a track section
    dispatch rule ->  which pending task to release next, and into which kind of gap

ACTION SPACE. An action is (task, gap preference): pick a pending task and say what kind of
window to put it in - the earliest feasible one, or specifically a micro-gap, a night window
or a megablock. Choosing the gap KIND rather than a specific window is what keeps the action
space fixed and small while preserving the decision that actually matters here, which is
whether work goes between trains or waits for the night.

    action_index = task_slot * N_GAP_CHOICES + gap_choice      (plus a final NO-OP)

CONSTRAINTS ARE ENFORCED BY MASKING, NEVER BY REWARD. An action that would violate allotment,
compatibility, capacity or window fit is masked to -inf before the argmax or softmax. The
policy therefore cannot emit an illegal schedule, which is why its constraint-violation rate
is zero by construction rather than by training luck. NO-OP is always legal, so the agent can
never be cornered into an illegal move.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum

import numpy as np

from backend.config import load_config
from backend.domain.compatibility import Verdict, check_allotment, compatibility
from backend.domain.models import StationTier
from backend.domain.network import Network
from backend.domain.task import Department, Task, TaskCategory
from backend.gaps.engine import CandidateWindow, GapType

DAY_S = 86400
WEEK_S = 7 * DAY_S


class GapChoice(IntEnum):
    EARLIEST = 0
    MICRO_GAP = 1
    NIGHT_WINDOW = 2
    MEGABLOCK = 3


N_GAP_CHOICES = len(GapChoice)
TASK_FEATURES = 17
GLOBAL_FEATURES = 9


def max_tasks() -> int:
    return int(load_config().get_path("rl.max_tasks_in_state", 20))


def action_space_size() -> int:
    return max_tasks() * N_GAP_CHOICES + 1  # + NO-OP


def noop_index() -> int:
    return action_space_size() - 1


@dataclass
class DispatchState:
    """Everything the policy sees at one decision point."""

    time_s: int
    pending: list[Task]
    scheduled: list[Task] = field(default_factory=list)
    iwp_used: int = 0
    blocks_today: dict[int, int] = field(default_factory=dict)
    gang_busy: dict[Department, int] = field(default_factory=dict)


def _tier_onehot(tier: StationTier | None) -> list[float]:
    return [
        float(tier is StationTier.TIER_1),
        float(tier is StationTier.TIER_2),
        float(tier is StationTier.TIER_3),
    ]


def encode_task(t: Task, net: Network, windows_for_task: list[CandidateWindow],
                now_s: int, n_conflicts: int) -> list[float]:
    sec = net.sections.get(t.zone.ref)
    tier = sec.tier if sec else net.stations.get(t.zone.ref).tier if t.zone.ref in net.stations else None
    earliest = min((w.start_s for w in windows_for_task), default=WEEK_S)
    micro = sum(1 for w in windows_for_task if w.gap_type is GapType.MICRO_GAP)
    night = sum(1 for w in windows_for_task if w.gap_type is GapType.NIGHT_WINDOW)
    slack = ((t.due_by_s or WEEK_S) - now_s) / WEEK_S
    return [
        float(t.department is Department.PWI),
        float(t.department is Department.OWD),
        float(t.department is Department.S_AND_T),
        t.duration_min / 360.0,
        (6 - t.priority) / 5.0,
        min(1.0, (now_s - t.released_s) / DAY_S),      # age in days, capped
        max(-1.0, min(1.0, slack)),
        float(t.requires_power_block),
        float(t.requires_traffic_block),
        float(t.category is TaskCategory.DEMAND),
        float(t.is_followup),
        *_tier_onehot(tier),
        min(1.0, len(windows_for_task) / 50.0),
        min(1.0, micro / 25.0),
        min(1.0, night / 10.0),
    ]


def encode_state(state: DispatchState, net: Network,
                 eligible: dict[str, list[CandidateWindow]]) -> np.ndarray:
    """Fixed-length vector. Task slots beyond the pool are zero-padded and masked out."""
    cfg = load_config()
    n = max_tasks()
    quota = int(cfg.get_path("departments.iwp_quota_per_day", 2)) * 7
    cap = int(cfg.get_path("planner.max_blocks_per_day", 8))

    ordered = rank_tasks(state.pending, state.time_s)[:n]
    rows: list[float] = [
        state.time_s / WEEK_S,
        (state.time_s % DAY_S) / DAY_S,
        float(state.time_s // DAY_S) / 7.0,
        min(1.0, len(state.pending) / 60.0),
        min(1.0, len(state.scheduled) / 60.0),
        state.iwp_used / max(1, quota),
        min(1.0, state.blocks_today.get(state.time_s // DAY_S, 0) / cap),
        min(1.0, sum(state.gang_busy.values()) / 6.0),
        float(any(t.category is TaskCategory.DEMAND for t in state.pending)),
    ]
    for i in range(n):
        if i < len(ordered):
            t = ordered[i]
            rows.extend(encode_task(t, net, eligible.get(t.id, []), state.time_s, 0))
        else:
            rows.extend([0.0] * TASK_FEATURES)
    return np.asarray(rows, dtype=np.float32)


def rank_tasks(pending: list[Task], now_s: int) -> list[Task]:
    """Stable ordering of the pool into action slots.

    The slot a task occupies has to be a deterministic function of the state, or the same
    action index would mean different things at training and inference time.
    """
    return sorted(
        pending,
        key=lambda t: (t.priority, -(now_s - t.released_s), t.due_by_s or WEEK_S, t.id),
    )


def pick_window(task: Task, choice: GapChoice, windows: list[CandidateWindow],
                now_s: int) -> CandidateWindow | None:
    """The concrete window an action resolves to: earliest of the requested kind."""
    usable = [w for w in windows if w.start_s >= now_s
              and w.usable_min(task.requires_power_block) >= task.duration_min]
    if choice is not GapChoice.EARLIEST:
        want = {
            GapChoice.MICRO_GAP: GapType.MICRO_GAP,
            GapChoice.NIGHT_WINDOW: GapType.NIGHT_WINDOW,
            GapChoice.MEGABLOCK: GapType.MEGABLOCK,
        }[choice]
        usable = [w for w in usable if w.gap_type is want]
    return min(usable, key=lambda w: w.start_s) if usable else None


def legal_mask(state: DispatchState, net: Network,
               eligible: dict[str, list[CandidateWindow]]) -> np.ndarray:
    """Boolean mask over the action space. NO-OP is always legal."""
    cfg = load_config()
    cap = int(cfg.get_path("planner.max_blocks_per_day", 8))
    gangs = int(cfg.get_path("departments.gangs_per_department", 2))

    n = max_tasks()
    mask = np.zeros(action_space_size(), dtype=bool)
    mask[noop_index()] = True

    ordered = rank_tasks(state.pending, state.time_s)[:n]
    for slot, task in enumerate(ordered):
        windows = eligible.get(task.id, [])
        if check_allotment(net, task) is not None:  # R0
            continue
        if state.gang_busy.get(task.department, 0) >= gangs:
            continue
        for choice in GapChoice:
            w = pick_window(task, choice, windows, state.time_s)
            if w is None:
                continue
            if state.blocks_today.get(w.start_s // DAY_S, 0) >= cap:
                continue
            if _conflicts_with_scheduled(net, task, w, state):
                continue
            mask[slot * N_GAP_CHOICES + int(choice)] = True
    return mask


def _conflicts_with_scheduled(net: Network, task: Task, window: CandidateWindow,
                              state: DispatchState) -> bool:
    """Would placing this task here break compatibility with work already placed?"""
    start = window.start_s
    end = start + task.duration_min * 60
    probe = task.model_copy(update={"scheduled_start_s": start, "scheduled_end_s": end})
    for other in state.scheduled:
        if other.scheduled_start_s is None:
            continue
        if not (other.zone.endpoints & task.zone.endpoints):
            continue
        if not (start < (other.scheduled_end_s or 0) and (other.scheduled_start_s or 0) < end):
            continue
        v = compatibility(net, probe, other).value
        if v is Verdict.INCOMPATIBLE:
            return True
        if v is Verdict.REQUIRES_IWP:
            quota = int(load_config().get_path("departments.iwp_quota_per_day", 2)) * 7
            if state.iwp_used >= quota:
                return True
    return False


def decode_action(index: int, state: DispatchState,
                  eligible: dict[str, list[CandidateWindow]]
                  ) -> tuple[Task, CandidateWindow, GapChoice] | None:
    """Action index -> concrete (task, window). None means NO-OP."""
    if index == noop_index():
        return None
    slot, choice_i = divmod(index, N_GAP_CHOICES)
    ordered = rank_tasks(state.pending, state.time_s)[:max_tasks()]
    if slot >= len(ordered):
        return None
    task = ordered[slot]
    choice = GapChoice(choice_i)
    w = pick_window(task, choice, eligible.get(task.id, []), state.time_s)
    return (task, w, choice) if w is not None else None


def reward(task: Task, window: CandidateWindow, state: DispatchState,
           uses_iwp: bool = False) -> float:
    """Dense reward, aligned term for term with the CP-SAT objective.

    Alignment matters: if the policy optimised something different from the solver that
    produced its training data, the objective gap reported later would be meaningless.
    """
    w = load_config()["planner"]["weights"]
    pw = 6 - task.priority
    r = float(w["w2_unscheduled_task"]) * pw / 10.0               # completion bonus
    if window.gap_type is GapType.MICRO_GAP:
        r += float(w["w7_micro_gap_bonus"]) / 10.0                # the capacity we want used
    r -= float(w["w3_degraded_status_hours"]) * pw * (window.start_s // DAY_S) / 10.0
    if uses_iwp:
        r -= float(w["w6_iwp_usage"]) / 10.0
    return r


WAITING_PENALTY = 0.05


def noop_reward(state: DispatchState) -> float:
    """Idling has a cost, or the policy would learn to do nothing and never be punished."""
    return -WAITING_PENALTY * len(state.pending)
