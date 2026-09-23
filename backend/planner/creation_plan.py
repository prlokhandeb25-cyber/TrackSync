"""Weekly planning with gap creation.

<!-- serves: J1, J5 -->

Plan the week exactly on the gaps the timetable really has (CP-SAT). Then, for each job CP-SAT could
not place, ask backend/gaps/creation.py what small change to the trains would open a window, and
place the job there if a priced option fits without breaking the rule engine. That second step is a
fast repair pass rather than another full solve: it reuses the same scheduler the live jobs use
(backend/planner/live_sim.py) against an empty window index, so it can only ever use created gaps,
never quietly take a natural one CP-SAT had already ruled out for a reason the repair pass cannot
see (the daily block cap, a station's concurrency limit).

Both plans are kept, so the effect of creation is measured rather than claimed. Known
simplification (ASSUMPTIONS.md): the repair pass checks compatibility with everything already
placed but not the daily block cap or station concurrency caps.
"""

from __future__ import annotations

import copy

from backend.domain.network import Network
from backend.domain.task import Task
from backend.gaps.creation import RerouteCache, options_for_task
from backend.gaps.engine import CandidateWindow
from backend.planner.cpsat import DAY_S, Assignment, PlanResult, solve_with_relaxation
from backend.planner.interval_index import IntervalWindowIndex
from backend.planner.live_sim import LiveSimState, alns_lite_insert


def _fresh(tasks: list[Task]) -> None:
    for t in tasks:
        t.scheduled_start_s = t.scheduled_end_s = None
        t.window_id = t.gap_type = None


def solve_with_creation(net: Network, tasks: list[Task], windows: list[CandidateWindow],
                        occ_by_section: dict, rc: RerouteCache, time_limit_s: float,
                        pax=None) -> tuple[PlanResult, PlanResult, list[CandidateWindow]]:
    """(plan on natural gaps, plan after creation, the created windows the final plan uses)."""
    _fresh(tasks)
    natural = solve_with_relaxation(net, tasks, windows, time_limit_s=time_limit_s, pax=pax)
    by_id = {t.id: t for t in tasks}
    if not natural.unscheduled:
        return natural, natural, []

    def creator(task: Task, from_s: int):
        return options_for_task(net, task, occ_by_section.get(task.zone.ref, []), rc,
                                from_s=from_s, horizon_days=7, max_options=6)

    final = copy.copy(natural)
    final.assignments = list(natural.assignments)
    final.unscheduled = []
    empty_index = IntervalWindowIndex()
    state = LiveSimState()
    used: list[CandidateWindow] = []

    for tid in natural.unscheduled:
        t = by_id.get(tid)
        if t is None:
            continue
        committed = [x for x in tasks if x.scheduled_start_s is not None and x.id != tid]
        p = alns_lite_insert(net, t, empty_index, committed, state, creator=creator, at_s=t.released_s)
        if p.placed and p.window is not None and p.created is not None:
            w = p.window
            w.id = f"CW-{tid}-0"
            final.assignments.append(Assignment(
                task_id=tid, window_id=w.id, section_id=w.section_id, zone_ref=w.zone_ref,
                track=w.track, start_s=p.start_s, end_s=p.end_s, gap_type=w.gap_type.value,
                day=p.start_s // DAY_S))
            t.window_id, t.gap_type = w.id, w.gap_type.value
            used.append(w)
        else:
            t.scheduled_start_s = t.scheduled_end_s = None
            final.unscheduled.append(tid)
    return natural, final, used
