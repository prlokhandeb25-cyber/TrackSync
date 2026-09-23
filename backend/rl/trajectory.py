"""Replay CP-SAT solutions as decision trajectories.

<!-- serves: J1 -->

This is the bridge the whole innovation claim rests on: the solver's optimal plan is walked
through in chronological order and, at each decision point, recorded as the action an expert
would have taken from that state. The result is an offline dataset of (state, action, reward,
next_state, mask) that a policy can be trained on without ever running the solver again.

The trajectory must be replayed through the SAME environment the policy will later act in,
otherwise the states it trains on are not the states it will see.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from backend.domain.network import Network
from backend.domain.task import Department, Task
from backend.gaps.engine import CandidateWindow, GapType
from backend.planner.cpsat import PlanResult, build_window_index, eligible_windows
from backend.rl.mdp import (
    DAY_S,
    DispatchState,
    GapChoice,
    N_GAP_CHOICES,
    action_space_size,
    encode_state,
    legal_mask,
    max_tasks,
    noop_index,
    pick_window,
    rank_tasks,
    reward,
)


@dataclass
class Transition:
    state: np.ndarray
    action: int
    reward: float
    next_state: np.ndarray
    mask: np.ndarray
    next_mask: np.ndarray
    done: bool
    instance_id: int


@dataclass
class TrajectoryStats:
    n_transitions: int = 0
    n_expert_actions: int = 0
    n_noop: int = 0
    total_return: float = 0.0
    micro_gap_actions: int = 0
    unmatched: int = 0  # expert placements we could not express as an action
    gap_choice_counts: dict[int, int] = field(default_factory=dict)


def _gap_choice_for(window: CandidateWindow) -> GapChoice:
    return {
        GapType.MICRO_GAP: GapChoice.MICRO_GAP,
        GapType.NIGHT_WINDOW: GapChoice.NIGHT_WINDOW,
        GapType.MEGABLOCK: GapChoice.MEGABLOCK,
    }[window.gap_type]


def replay(net: Network, tasks: list[Task], windows: list[CandidateWindow],
           plan: PlanResult, instance_id: int) -> tuple[list[Transition], TrajectoryStats]:
    """Walk the expert plan in time order, emitting one transition per placement."""
    stats = TrajectoryStats()
    by_id = {t.id: t for t in tasks}
    window_index = build_window_index(windows)
    eligible = {t.id: eligible_windows(t, windows, window_index) for t in tasks}
    window_by_id = {w.id: w for w in windows}

    placements = sorted(plan.assignments, key=lambda a: a.start_s)
    pending = [t for t in tasks if t.id in {a.task_id for a in placements}]
    # Tasks the expert could not place are still in the pool the policy sees; leaving them out
    # would train the policy on an easier world than the one it will be asked to work in.
    pending += [t for t in tasks if t.id in set(plan.unscheduled)]

    state = DispatchState(time_s=0, pending=list(pending))
    transitions: list[Transition] = []

    for i, a in enumerate(placements):
        task = by_id.get(a.task_id)
        window = window_by_id.get(a.window_id)
        if task is None or window is None:
            stats.unmatched += 1
            continue

        s_vec = encode_state(state, net, eligible)
        mask = legal_mask(state, net, eligible)

        # Which action index expresses this expert placement?
        ordered = rank_tasks(state.pending, state.time_s)[:max_tasks()]
        try:
            slot = ordered.index(task)
        except ValueError:
            # The expert placed a task outside the visible slots. Recording a NO-OP here would
            # teach the policy to idle when it should act, so the step is skipped instead.
            stats.unmatched += 1
            continue

        choice = _gap_choice_for(window)
        # Only label the specific gap kind if that is what the action would actually resolve
        # to; otherwise EARLIEST is the honest label for what the expert did.
        resolved = pick_window(task, choice, eligible.get(task.id, []), state.time_s)
        if resolved is None or resolved.id != window.id:
            alt = pick_window(task, GapChoice.EARLIEST, eligible.get(task.id, []), state.time_s)
            if alt is not None and alt.id == window.id:
                choice = GapChoice.EARLIEST
        action = slot * N_GAP_CHOICES + int(choice)

        if not mask[action]:
            # The expert did something the mask forbids. That is a modelling disagreement, not
            # a valid label, and training on it would teach the policy to break constraints.
            stats.unmatched += 1
            continue

        r = reward(task, window, state)
        day = window.start_s // DAY_S

        nxt = DispatchState(
            time_s=max(state.time_s, window.start_s),
            pending=[t for t in state.pending if t.id != task.id],
            scheduled=state.scheduled + [task.model_copy(update={
                "scheduled_start_s": a.start_s, "scheduled_end_s": a.end_s})],
            iwp_used=state.iwp_used,
            blocks_today={**state.blocks_today, day: state.blocks_today.get(day, 0) + 1},
            gang_busy=dict(state.gang_busy),
        )
        n_vec = encode_state(nxt, net, eligible)
        n_mask = legal_mask(nxt, net, eligible)
        done = i == len(placements) - 1

        transitions.append(Transition(s_vec, action, r, n_vec, mask, n_mask, done, instance_id))
        stats.n_expert_actions += 1
        stats.total_return += r
        if window.gap_type is GapType.MICRO_GAP:
            stats.micro_gap_actions += 1
        stats.gap_choice_counts[int(choice)] = stats.gap_choice_counts.get(int(choice), 0) + 1
        state = nxt

    stats.n_transitions = len(transitions)
    return transitions, stats


def to_arrays(transitions: list[Transition]) -> dict[str, np.ndarray]:
    if not transitions:
        return {}
    return {
        "state": np.stack([t.state for t in transitions]),
        "action": np.asarray([t.action for t in transitions], dtype=np.int64),
        "reward": np.asarray([t.reward for t in transitions], dtype=np.float32),
        "next_state": np.stack([t.next_state for t in transitions]),
        "mask": np.stack([t.mask for t in transitions]),
        "next_mask": np.stack([t.next_mask for t in transitions]),
        "done": np.asarray([t.done for t in transitions], dtype=np.float32),
        "instance_id": np.asarray([t.instance_id for t in transitions], dtype=np.int64),
    }
