"""CP-SAT block planner — the optimal batch scheduler, and the expert for offline RL.

<!-- serves: J1, J2, J5 -->

This module does two jobs. It produces the weekly block plan, and its solutions are replayed
as decision trajectories to train the RL dispatcher (P6/P7). Because the policy can only be as
good as the expert it learns from, the model here is worth getting right rather than fast.

Constraints implemented (SPEC §10.2):
  1. A task sits entirely inside one candidate window, with enough usable time for the job.
  2. Compatibility (SPEC §7): INCOMPATIBLE pairs get disjoint times, REQUIRES_IWP pairs may
     overlap only by consuming an Integrated Work Permission from the daily quota.
  3. R0 allotment: filtered out before the model is built, with a reason recorded.
  4. Gang capacity per department.
  5. Station-tier concurrency caps.
  6. Due dates: hard for priority-1 work, soft otherwise.

The objective deliberately rewards micro-gap usage (w7). Fitting work between trains is the
capacity this system is claiming to unlock, so the optimiser has to want it - otherwise it
will always take the easy night window and the claim evaporates.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from ortools.sat.python import cp_model

from backend.config import load_config
from backend.domain.compatibility import Verdict, check_allotment, compatibility
from backend.domain.network import Network
from backend.domain.task import Task
from backend.gaps.engine import CandidateWindow, GapType

DAY_S = 86400


@dataclass
class Assignment:
    task_id: str
    window_id: str
    section_id: str
    zone_ref: str
    track: str
    start_s: int
    end_s: int
    gap_type: str
    day: int
    uses_iwp: bool = False


@dataclass
class PlanResult:
    status: str
    objective: float
    best_bound: float
    gap_pct: float
    wall_s: float
    assignments: list[Assignment] = field(default_factory=list)
    unscheduled: list[str] = field(default_factory=list)
    rejected: dict[str, str] = field(default_factory=dict)  # task_id -> R0 reason
    iwp_used: int = 0
    relaxations: list[str] = field(default_factory=list)
    n_tasks: int = 0
    n_windows_considered: int = 0

    @property
    def micro_gap_count(self) -> int:
        return sum(1 for a in self.assignments if a.gap_type == GapType.MICRO_GAP.value)

    def summary(self) -> str:
        n = len(self.assignments)
        return (f"{self.status}: {n}/{self.n_tasks} tasks scheduled "
                f"({self.micro_gap_count} into micro-gaps), objective {self.objective:.0f}, "
                f"gap {self.gap_pct:.1f}%, {self.wall_s:.1f}s")

    def to_dict(self) -> dict:
        return {
            "status": self.status, "objective": self.objective, "best_bound": self.best_bound,
            "gap_pct": round(self.gap_pct, 2), "wall_s": round(self.wall_s, 2),
            "n_tasks": self.n_tasks, "n_scheduled": len(self.assignments),
            "n_unscheduled": len(self.unscheduled), "n_rejected_allotment": len(self.rejected),
            "micro_gap_count": self.micro_gap_count, "iwp_used": self.iwp_used,
            "relaxations": self.relaxations,
            "n_windows_considered": self.n_windows_considered,
            "assignments": [a.__dict__ for a in self.assignments],
            "unscheduled": self.unscheduled,
            "rejected": self.rejected,
        }


def eligible_windows(task: Task, windows: list[CandidateWindow]) -> list[CandidateWindow]:
    """Windows that could physically hold this job.

    A window qualifies only if its USABLE time covers the duration - raw gap time is not
    working time. Power-block work pays the isolation overhead twice, which removes a lot of
    short windows for OHE jobs and is exactly the sort of thing a planner must not miss.
    """
    out = []
    for w in windows:
        if w.zone_ref != task.zone.ref or w.zone_kind != task.zone.kind:
            continue
        if w.usable_min(power_block=task.requires_power_block) < task.duration_min:
            continue
        if w.end_s < task.released_s:
            continue
        out.append(w)
    return out


def build_and_solve(
    net: Network,
    tasks: list[Task],
    windows: list[CandidateWindow],
    time_limit_s: float | None = None,
    horizon_days: int = 7,
    relax: list[str] | None = None,
    log: bool = False,
) -> PlanResult:
    cfg = load_config()
    w = cfg["planner"]["weights"]
    relax = relax or []
    t0 = time.time()

    # ---- R0: reject unallotted work before the model exists, with a reason.
    rejected: dict[str, str] = {}
    live: list[Task] = []
    for t in tasks:
        r = check_allotment(net, t)
        if r is not None:
            rejected[t.id] = r.reason
        else:
            live.append(t)

    # ---- candidate windows per task
    cand: dict[str, list[CandidateWindow]] = {t.id: eligible_windows(t, windows) for t in live}
    n_considered = sum(len(v) for v in cand.values())

    model = cp_model.CpModel()
    horizon = horizon_days * DAY_S

    x: dict[tuple[str, str], cp_model.IntVar] = {}       # task -> window selection
    scheduled: dict[str, cp_model.IntVar] = {}
    start: dict[str, cp_model.IntVar] = {}
    end: dict[str, cp_model.IntVar] = {}
    interval: dict[str, cp_model.IntervalVar] = {}
    day_var: dict[str, cp_model.IntVar] = {}
    by_id = {t.id: t for t in live}

    for t in live:
        dur = t.duration_min * 60
        sched = model.NewBoolVar(f"sched_{t.id}")
        scheduled[t.id] = sched
        s = model.NewIntVar(0, horizon, f"start_{t.id}")
        e = model.NewIntVar(0, horizon, f"end_{t.id}")
        start[t.id], end[t.id] = s, e
        interval[t.id] = model.NewOptionalIntervalVar(s, dur, e, sched, f"iv_{t.id}")

        lits = []
        for cw in cand[t.id]:
            b = model.NewBoolVar(f"x_{t.id}_{cw.id}")
            x[(t.id, cw.id)] = b
            lits.append(b)
            # Constraint 1: the job sits inside the window's usable span.
            overhead = 0
            gcfg = cfg["gaps"]
            overhead += int(gcfg["block_setup_min"]) * 60
            if t.requires_power_block:
                overhead += int(gcfg["power_block_extra_min"]) * 60
            lo = cw.start_s + overhead
            hi = cw.end_s - int(gcfg["block_release_min"]) * 60
            if t.requires_power_block:
                hi -= int(gcfg["power_block_extra_min"]) * 60
            model.Add(s >= lo).OnlyEnforceIf(b)
            model.Add(e <= hi).OnlyEnforceIf(b)
        # exactly one window iff scheduled
        if lits:
            model.Add(sum(lits) == 1).OnlyEnforceIf(sched)
            model.Add(sum(lits) == 0).OnlyEnforceIf(sched.Not())
        else:
            model.Add(sched == 0)

        # An unscheduled task has a free start variable, which would otherwise drift into a
        # day bucket and consume that day's block allowance. Pin it.
        model.Add(s == 0).OnlyEnforceIf(sched.Not())

        dv = model.NewIntVar(0, horizon_days - 1, f"day_{t.id}")
        model.AddDivisionEquality(dv, s, DAY_S)
        day_var[t.id] = dv

        # Release time, and due dates (hard for priority 1 unless relaxed).
        model.Add(s >= t.released_s).OnlyEnforceIf(sched)
        if t.due_by_s is not None and t.priority == 1 and "drop_due_dates" not in relax:
            model.Add(e <= min(t.due_by_s, horizon)).OnlyEnforceIf(sched)

    # ---- Constraint 2: compatibility between every pair that could coincide
    iwp_lits: dict[int, list[cp_model.IntVar]] = {d: [] for d in range(horizon_days)}
    for i, a in enumerate(live):
        for b_task in live[i + 1:]:
            # Only pairs that could physically interact need a constraint.
            if not (a.zone.endpoints & b_task.zone.endpoints):
                continue
            verdict = compatibility(net, a, b_task)
            ia, ib = interval[a.id], interval[b_task.id]

            if verdict.value is Verdict.INCOMPATIBLE:
                # Hard disjunction: different time slots entirely. Never a soft penalty.
                model.AddNoOverlap([ia, ib])

            elif verdict.value is Verdict.REQUIRES_IWP:
                # Either separated in time, or overlapping under an Integrated Work Permission.
                overlap = model.NewBoolVar(f"iwp_{a.id}_{b_task.id}")
                before = model.NewBoolVar(f"before_{a.id}_{b_task.id}")
                after = model.NewBoolVar(f"after_{a.id}_{b_task.id}")
                model.Add(end[a.id] <= start[b_task.id]).OnlyEnforceIf(before)
                model.Add(end[b_task.id] <= start[a.id]).OnlyEnforceIf(after)
                both = model.NewBoolVar(f"both_{a.id}_{b_task.id}")
                model.AddBoolAnd([scheduled[a.id], scheduled[b_task.id]]).OnlyEnforceIf(both)
                model.AddBoolOr([scheduled[a.id].Not(), scheduled[b_task.id].Not()]).OnlyEnforceIf(
                    both.Not())
                # If both run, exactly one of {before, after, overlap-with-IWP} holds.
                model.Add(before + after + overlap == 1).OnlyEnforceIf(both)
                model.Add(before + after + overlap == 0).OnlyEnforceIf(both.Not())
                for d in range(horizon_days):
                    iwp_lits[d].append(overlap)

    # ---- Constraint 4: gang capacity per department
    gangs = int(cfg.get_path("departments.gangs_per_department", 2))
    if "drop_gang_capacity" not in relax:
        for dept in {t.department for t in live}:
            ivs = [interval[t.id] for t in live if t.department is dept]
            if len(ivs) > gangs:
                model.AddCumulative(ivs, [1] * len(ivs), gangs)

    # ---- Constraint 5: station-tier concurrency caps
    if "drop_tier_caps" not in relax:
        tier_cfg = cfg["station_tiers"]
        for code, st in net.stations.items():
            ivs = [interval[t.id] for t in live if code in t.zone.endpoints]
            if not ivs:
                continue
            cap = int({
                "TIER_1": tier_cfg["max_concurrent_blocks_tier1"],
                "TIER_2": tier_cfg["max_concurrent_blocks_tier2"],
                "TIER_3": tier_cfg["max_concurrent_blocks_tier3"],
            }.get(st.tier.value if st.tier else "TIER_2", 2))
            if len(ivs) > cap:
                model.AddCumulative(ivs, [1] * len(ivs), cap)

    # ---- Blocks granted per day, corridor-wide
    # Without this the optimiser puts almost the whole week's work on Monday night, because
    # finishing sooner is cheaper and nothing forbids it. No control office grants twenty-five
    # blocks in one night: the number of blocks a division can protect, staff and supervise in
    # a day is finite, and it is the real reason weekly plans are spread rather than stacked.
    max_per_day = int(cfg.get_path("planner.max_blocks_per_day", 8))
    if "drop_daily_block_cap" not in relax and live:
        for d in range(horizon_days):
            on_day = []
            for t in live:
                b = model.NewBoolVar(f"onday_{t.id}_{d}")
                # b <=> (scheduled AND starts on day d). Both directions matter: without the
                # reverse implication the solver can simply set b=0 and ignore the cap.
                model.Add(day_var[t.id] == d).OnlyEnforceIf(b)
                model.AddBoolAnd([scheduled[t.id]]).OnlyEnforceIf(b)
                nb = b.Not()
                off = model.NewBoolVar(f"offday_{t.id}_{d}")
                model.Add(day_var[t.id] != d).OnlyEnforceIf(off)
                model.AddBoolOr([off, scheduled[t.id].Not()]).OnlyEnforceIf(nb)
                on_day.append(b)
            model.Add(sum(on_day) <= max_per_day)

    # ---- Objective (SPEC §10.3)
    terms = []
    for t in live:
        pw = (6 - t.priority)  # priority 1 -> weight 5
        # Leaving work unplanned is the dominant cost, weighted by priority and age.
        terms.append(int(w["w2_unscheduled_task"] * pw) * scheduled[t.id].Not())
        # Prefer finishing sooner: cost grows with the day the work lands on.
        terms.append(int(w["w3_degraded_status_hours"] * pw) * day_var[t.id])
        # Micro-gap bonus: we want work fitted between trains, not queued for the night.
        for cw in cand[t.id]:
            if cw.gap_type is GapType.MICRO_GAP:
                terms.append(-int(w["w7_micro_gap_bonus"]) * x[(t.id, cw.id)])

    all_iwp = [lit for lits in iwp_lits.values() for lit in lits]
    unique_iwp = list({id(l): l for l in all_iwp}.values())
    if unique_iwp:
        terms.append(int(w["w6_iwp_usage"]) * sum(unique_iwp))
        quota = int(cfg.get_path("departments.iwp_quota_per_day", 2))
        if "drop_iwp_quota" not in relax:
            model.Add(sum(unique_iwp) <= quota * horizon_days)

    model.Minimize(sum(terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(
        time_limit_s if time_limit_s is not None else cfg["planner"]["solve_time_s_demo"])
    solver.parameters.num_search_workers = int(cfg["planner"]["num_search_workers"])
    solver.parameters.random_seed = int(cfg["seed"]) % (2**31 - 1)
    solver.parameters.log_search_progress = bool(log)
    status = solver.Solve(model)

    wall = time.time() - t0
    name = solver.StatusName(status)
    result = PlanResult(
        status=name, objective=0.0, best_bound=0.0, gap_pct=0.0, wall_s=wall,
        rejected=rejected, n_tasks=len(tasks), n_windows_considered=n_considered,
        relaxations=list(relax),
    )
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        result.unscheduled = [t.id for t in live]
        return result

    obj, bound = solver.ObjectiveValue(), solver.BestObjectiveBound()
    result.objective = obj
    result.best_bound = bound
    result.gap_pct = 0.0 if abs(obj) < 1e-9 else abs(obj - bound) / max(1e-9, abs(obj)) * 100

    for t in live:
        if not solver.Value(scheduled[t.id]):
            result.unscheduled.append(t.id)
            continue
        chosen = next((cw for cw in cand[t.id] if solver.Value(x[(t.id, cw.id)])), None)
        if chosen is None:
            result.unscheduled.append(t.id)
            continue
        s_val = solver.Value(start[t.id])
        result.assignments.append(
            Assignment(
                task_id=t.id, window_id=chosen.id, section_id=chosen.section_id,
                zone_ref=chosen.zone_ref, track=chosen.track,
                start_s=s_val, end_s=s_val + t.duration_min * 60,
                gap_type=chosen.gap_type.value, day=s_val // DAY_S,
            )
        )
        t.scheduled_start_s = s_val
        t.scheduled_end_s = s_val + t.duration_min * 60
        t.window_id = chosen.id
        t.gap_type = chosen.gap_type.value

    result.iwp_used = sum(solver.Value(l) for l in unique_iwp) if unique_iwp else 0
    return result


# Relaxations are tried in this order. Reporting WHICH one restored feasibility is far more
# useful than returning a bare "infeasible" to the UI, which would be a dead demo.
RELAXATION_LADDER = [
    [],
    ["drop_due_dates"],
    ["drop_due_dates", "drop_daily_block_cap"],
    ["drop_due_dates", "drop_tier_caps"],
    ["drop_due_dates", "drop_tier_caps", "drop_gang_capacity"],
    ["drop_due_dates", "drop_tier_caps", "drop_gang_capacity", "drop_iwp_quota"],
]


def solve_with_relaxation(net: Network, tasks: list[Task], windows: list[CandidateWindow],
                          time_limit_s: float | None = None, horizon_days: int = 7) -> PlanResult:
    last: PlanResult | None = None
    for relax in RELAXATION_LADDER:
        res = build_and_solve(net, tasks, windows, time_limit_s, horizon_days, relax=relax)
        if res.status in ("OPTIMAL", "FEASIBLE"):
            return res
        last = res
    return last  # type: ignore[return-value]
