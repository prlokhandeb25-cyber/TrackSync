"""Dynamic priority aging: a job that keeps waiting (or keeps being pushed aside) gradually outranks newer work.

<!-- serves: J1, J5 -->

Strict priorities starve low-priority work: routine jobs (P4, P5) are outranked by everything new, week after week.
Aging fixes that without changing what "urgent" means:

    effective priority = priority - steps,   steps = floor(hours waiting / aging.hours_per_step) + times pushed aside

- Only `steps` move; the job's own priority is never rewritten in the data.
- Aging stops at `aging.floor` (P2 by default), so no amount of waiting lets routine work outrank a P1 emergency.
  A job that is P1 to begin with stays P1.
- Where it is used: a sudden task may push aside only jobs whose EFFECTIVE priority is lower than its own, so a
  job that has waited or been moved before is protected; a job carried over from a previous week is planned at
  its aged priority (`age_carried`); the early-finish reuse list ranks by effective priority.

The step length and floor are assumptions (A-059).
"""

from __future__ import annotations

from backend.config import load_config
from backend.domain.task import Task

_BUMPS: dict[str, int] = {}          # times a job has been pushed aside by a more urgent one (this run)


def _cfg() -> tuple[float, int, bool]:
    c = load_config()
    return (float(c.get_path("aging.hours_per_step", 48.0)), int(c.get_path("aging.floor", 2)),
            bool(c.get_path("aging.enabled", True)))


def record_bump(task_id: str) -> None:
    _BUMPS[task_id] = _BUMPS.get(task_id, 0) + 1


def bumps(task_id: str) -> int:
    return _BUMPS.get(task_id, 0)


def reset() -> None:
    _BUMPS.clear()


def steps(task: Task, now_s: int, extra_weeks: int = 0) -> int:
    """How many priority levels the job has moved up: waiting time, weeks carried over, times pushed aside."""
    hours_per_step, _, enabled = _cfg()
    if not enabled:
        return 0
    waited_h = max(0.0, (now_s - (task.released_s or 0)) / 3600.0)
    return int(waited_h // hours_per_step) + extra_weeks + bumps(task.id)


def effective_priority(task: Task, now_s: int = 0, extra_weeks: int = 0) -> int:
    """The priority number to rank by (lower is more urgent). Never better than the floor, never worse than its own."""
    _, floor, _ = _cfg()
    if task.priority <= floor:
        return task.priority
    return max(floor, task.priority - steps(task, now_s, extra_weeks))


def age_carried(tasks: list[Task], weeks_waited: dict[str, int]) -> dict[str, int]:
    """A job left over from the last week is planned one level more urgent for each week it has been carried.

    Rewrites `priority` on the (copied) carried tasks so the planner's own priority weights see it; returns
    {task id: original priority} for every job that moved, so the screen can say "P4, aged to P3".
    """
    _, floor, enabled = _cfg()
    moved: dict[str, int] = {}
    if not enabled:
        return moved
    for t in tasks:
        weeks = weeks_waited.get(t.id, 0)
        if weeks and t.priority > floor:
            new = max(floor, t.priority - weeks)
            if new != t.priority:
                moved[t.id] = moved.get(t.id, t.priority)
                t.priority = new
    return moved


def explain(task: Task, now_s: int = 0) -> dict:
    hours_per_step, floor, _ = _cfg()
    eff = effective_priority(task, now_s)
    return {"id": task.id, "priority": task.priority, "effective": eff, "steps": task.priority - eff,
            "waited_h": round(max(0.0, (now_s - (task.released_s or 0)) / 3600.0), 1), "pushed_aside": bumps(task.id),
            "hours_per_step": hours_per_step, "floor": floor}
