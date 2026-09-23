"""Rollout environment: run a policy on an instance and score it against CP-SAT.

<!-- serves: J1, J5 -->

The policy is rolled out through the same state encoding and legality mask used to build the
training data, then its schedule is scored with the SAME objective function CP-SAT minimised.
Scoring the two with different yardsticks would make the headline "within X% of optimal"
number meaningless, so the objective is computed once here and applied to both.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np

from backend.config import load_config
from backend.domain.compatibility import Verdict, compatibility
from backend.domain.network import Network
from backend.domain.task import Task
from backend.gaps.engine import CandidateWindow, GapType
from backend.planner.cpsat import DAY_S, PlanResult, build_window_index, eligible_windows
from backend.rl.mdp import (
    DispatchState,
    decode_action,
    encode_state,
    legal_mask,
    noop_index,
    reward as step_reward,
)


@dataclass
class Rollout:
    placements: list[tuple[Task, CandidateWindow]] = field(default_factory=list)
    unscheduled: list[str] = field(default_factory=list)
    total_reward: float = 0.0
    steps: int = 0
    noops: int = 0
    decision_latencies_ms: list[float] = field(default_factory=list)
    violations: int = 0
    iwp_used: int = 0

    @property
    def micro_gap_count(self) -> int:
        return sum(1 for _, w in self.placements if w.gap_type is GapType.MICRO_GAP)

    @property
    def mean_latency_ms(self) -> float:
        return float(np.mean(self.decision_latencies_ms)) if self.decision_latencies_ms else 0.0

    @property
    def p95_latency_ms(self) -> float:
        return float(np.percentile(self.decision_latencies_ms, 95)) if self.decision_latencies_ms else 0.0


def objective_of(placements: list[tuple[Task, CandidateWindow]], all_tasks: list[Task],
                 iwp_used: int = 0) -> float:
    """The CP-SAT objective, recomputed from a schedule.

    Mirrors backend/planner/cpsat.py's objective term for term. If the two ever drift apart,
    the reported gap stops measuring policy quality and starts measuring the discrepancy.
    """
    w = load_config()["planner"]["weights"]
    placed = {t.id for t, _ in placements}
    total = 0.0
    for t in all_tasks:
        pw = 6 - t.priority
        if t.id not in placed:
            total += float(w["w2_unscheduled_task"]) * pw
    for t, win in placements:
        pw = 6 - t.priority
        total += float(w["w3_degraded_status_hours"]) * pw * (win.start_s // DAY_S)
        if win.gap_type is GapType.MICRO_GAP:
            total -= float(w["w7_micro_gap_bonus"])
    total += float(w["w6_iwp_usage"]) * iwp_used
    return total


def rollout(policy, net: Network, tasks: list[Task], windows: list[CandidateWindow],
            max_steps: int | None = None) -> Rollout:
    cfg = load_config()
    cap = int(cfg.get_path("planner.max_blocks_per_day", 8))
    gangs = int(cfg.get_path("departments.gangs_per_department", 2))
    quota = int(cfg.get_path("departments.iwp_quota_per_day", 2)) * 7

    window_index = build_window_index(windows)
    eligible = {t.id: eligible_windows(t, windows, window_index) for t in tasks}
    state = DispatchState(time_s=0, pending=list(tasks))
    out = Rollout()
    limit = max_steps if max_steps is not None else len(tasks) * 2 + 10

    for _ in range(limit):
        if not state.pending:
            break
        mask = legal_mask(state, net, eligible)
        if not mask.any() or (mask.sum() == 1 and mask[noop_index()]):
            break  # nothing legal left but idling

        vec = encode_state(state, net, eligible)
        t0 = time.perf_counter()
        action = policy.act(vec, mask)
        out.decision_latencies_ms.append((time.perf_counter() - t0) * 1000)
        out.steps += 1

        if not mask[action]:
            # Should be impossible: every policy selects through the mask. Counted rather
            # than silently corrected, because a non-zero value here is a real defect.
            out.violations += 1
            action = noop_index()

        if action == noop_index():
            out.noops += 1
            # Idling forever is not a strategy; advance to the next decision point.
            future = [w.start_s for t in state.pending for w in eligible.get(t.id, [])
                      if w.start_s > state.time_s]
            if not future:
                break
            state = DispatchState(
                time_s=min(future), pending=state.pending, scheduled=state.scheduled,
                iwp_used=state.iwp_used, blocks_today=state.blocks_today,
                gang_busy=state.gang_busy,
            )
            continue

        decoded = decode_action(action, state, eligible, net)
        if decoded is None:
            out.noops += 1
            continue
        task, window, _choice = decoded

        uses_iwp = False
        start, end = window.start_s, window.start_s + task.duration_min * 60
        probe = task.model_copy(update={"scheduled_start_s": start, "scheduled_end_s": end})
        for other in state.scheduled:
            if not (other.zone.endpoints & task.zone.endpoints):
                continue
            if not (start < (other.scheduled_end_s or 0) and (other.scheduled_start_s or 0) < end):
                continue
            if compatibility(net, probe, other).value is Verdict.REQUIRES_IWP:
                uses_iwp = True
                break

        out.total_reward += step_reward(task, window, state, uses_iwp)
        out.placements.append((task, window))
        day = window.start_s // DAY_S
        state = DispatchState(
            # The planning cursor deliberately does NOT jump to the chosen window. Advancing
            # it would mean that placing one job in a Sunday slot strands every task whose
            # windows fall earlier in the week - a restriction CP-SAT does not labour under,
            # which would make the comparison against it measure the handicap, not the policy.
            time_s=state.time_s,
            pending=[t for t in state.pending if t.id != task.id],
            scheduled=state.scheduled + [probe],
            iwp_used=state.iwp_used + (1 if uses_iwp else 0),
            blocks_today={**state.blocks_today, day: state.blocks_today.get(day, 0) + 1},
            gang_busy=dict(state.gang_busy),
        )

    out.unscheduled = [t.id for t in state.pending]
    out.iwp_used = state.iwp_used
    return out


@dataclass
class EvalResult:
    policy: str
    objective: float
    cpsat_objective: float
    gap_pct: float
    scheduled: int
    n_tasks: int
    micro_gap: int
    mean_latency_ms: float
    p95_latency_ms: float
    violations: int
    full_replan_ms: float

    def to_dict(self) -> dict:
        return self.__dict__


def evaluate(policy, net: Network, tasks: list[Task], windows: list[CandidateWindow],
             cpsat: PlanResult) -> EvalResult:
    t0 = time.perf_counter()
    r = rollout(policy, net, tasks, windows)
    full_ms = (time.perf_counter() - t0) * 1000

    obj = objective_of(r.placements, tasks, r.iwp_used)
    # CP-SAT's own objective also carries a reward for integrated blocks, which the dispatcher was
    # never trained to chase and objective_of does not include. Add it back so both sides are
    # scored on the same placement objective; otherwise the gap would measure that missing term.
    w8 = float(load_config()["planner"]["weights"].get("w8_integrated_block", 0.0))
    ref = cpsat.objective + w8 * getattr(cpsat, "integrated_pairs", 0)
    # A near-zero reference makes a ratio meaningless; fall back to an absolute difference.
    gap = ((obj - ref) / abs(ref) * 100) if abs(ref) > 1e-6 else (obj - ref)

    return EvalResult(
        policy=getattr(policy, "name", "policy"),
        objective=round(obj, 2),
        cpsat_objective=round(ref, 2),
        gap_pct=round(gap, 2),
        scheduled=len(r.placements),
        n_tasks=len(tasks),
        micro_gap=r.micro_gap_count,
        mean_latency_ms=round(r.mean_latency_ms, 4),
        p95_latency_ms=round(r.p95_latency_ms, 4),
        violations=r.violations,
        full_replan_ms=round(full_ms, 2),
    )
