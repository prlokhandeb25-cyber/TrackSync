"""Track status state machine.

<!-- serves: J1, J5 -->

    FIT ──defect_reported──────────────► SICK
    SICK ──task_scheduled──────────────► SICK   (window set; status unchanged)
    SICK ──work_started────────────────► SICK   (section closed for the block)
    SICK ──work_completed(outcome)─────► FIT | CAUTION_ORDER | STOP_AND_START
    CAUTION_ORDER ──followup_completed─► FIT
    STOP_AND_START ──followup_completed► CAUTION_ORDER | FIT
    ANY ──demand_defect_found──────────► SICK  + a new DEMAND task

CAUTION_ORDER and STOP_AND_START are not "done": they are degraded operation that costs train
time every day they persist, which is what makes clearing them measurable in the impact study.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from backend.config import load_config
from backend.domain.models import TrackStatus
from backend.domain.task import Task, TaskCategory


class IllegalTransition(Exception):
    pass


class Event(str):
    DEFECT_REPORTED = "defect_reported"
    TASK_SCHEDULED = "task_scheduled"
    WORK_STARTED = "work_started"
    WORK_COMPLETED = "work_completed"
    FOLLOWUP_COMPLETED = "followup_completed"
    DEMAND_DEFECT_FOUND = "demand_defect_found"


# Which statuses each event may be applied from. work_completed's destination depends on the
# sampled outcome, so it is validated separately.
LEGAL_FROM: dict[str, set[TrackStatus]] = {
    Event.DEFECT_REPORTED: {TrackStatus.FIT, TrackStatus.CAUTION_ORDER, TrackStatus.STOP_AND_START},
    Event.TASK_SCHEDULED: {TrackStatus.SICK},
    Event.WORK_STARTED: {TrackStatus.SICK},
    Event.WORK_COMPLETED: {TrackStatus.SICK},
    Event.FOLLOWUP_COMPLETED: {TrackStatus.CAUTION_ORDER, TrackStatus.STOP_AND_START},
    Event.DEMAND_DEFECT_FOUND: {
        TrackStatus.FIT, TrackStatus.SICK, TrackStatus.CAUTION_ORDER, TrackStatus.STOP_AND_START,
    },
}

# A follow-up on a restricted section lifts it by one step; it does not always go straight to FIT.
FOLLOWUP_RESULT: dict[TrackStatus, list[tuple[TrackStatus, float]]] = {
    TrackStatus.CAUTION_ORDER: [(TrackStatus.FIT, 1.0)],
    TrackStatus.STOP_AND_START: [(TrackStatus.CAUTION_ORDER, 0.65), (TrackStatus.FIT, 0.35)],
}


@dataclass
class Transition:
    zone_ref: str
    event: str
    from_status: TrackStatus
    to_status: TrackStatus
    at_s: int
    task_id: str | None = None
    note: str = ""


@dataclass
class StatusRegistry:
    """Current status of every work zone, plus the transition log."""

    status: dict[str, TrackStatus] = field(default_factory=dict)
    log: list[Transition] = field(default_factory=list)

    def get(self, ref: str) -> TrackStatus:
        return self.status.get(ref, TrackStatus.FIT)

    def set_initial(self, ref: str, st: TrackStatus = TrackStatus.FIT) -> None:
        self.status[ref] = st

    def apply(self, ref: str, event: str, at_s: int, to: TrackStatus,
              task_id: str | None = None, note: str = "") -> Transition:
        cur = self.get(ref)
        allowed = LEGAL_FROM.get(event)
        if allowed is None:
            raise IllegalTransition(f"unknown event {event!r}")
        if cur not in allowed:
            raise IllegalTransition(
                f"{event} is not legal from {cur.value} (zone {ref}); "
                f"legal from {{{', '.join(sorted(s.value for s in allowed))}}}"
            )
        tr = Transition(ref, event, cur, to, at_s, task_id, note)
        self.status[ref] = to
        self.log.append(tr)
        return tr

    def degraded_zones(self) -> dict[str, TrackStatus]:
        return {r: s for r, s in self.status.items()
                if s in (TrackStatus.CAUTION_ORDER, TrackStatus.STOP_AND_START)}


def sample_outcome(task: Task, allotted_min: int | None, rng: random.Random) -> TrackStatus:
    """Outcome of completed work, given how much time the job actually got.

    A job squeezed into less time than it needs finishes degraded more often. This is what
    stops micro-gap scheduling from looking like free lunch: fitting work into a short gap
    between trains is a real option, but it carries a real risk, and the optimiser should be
    pricing that risk rather than ignoring it.
    """
    weights = dict(task.type_def.outcome_weights)
    if allotted_min is not None and allotted_min < task.duration_min:
        shortfall = 1.0 - (allotted_min / max(1, task.duration_min))
        # Shift probability mass out of FIT and into the two restricted outcomes.
        moved = weights.get("FIT", 0.0) * min(0.9, shortfall * 1.5)
        weights["FIT"] = weights.get("FIT", 0.0) - moved
        weights["CAUTION_ORDER"] = weights.get("CAUTION_ORDER", 0.0) + moved * 0.75
        weights["STOP_AND_START"] = weights.get("STOP_AND_START", 0.0) + moved * 0.25
    names = list(weights)
    return TrackStatus(rng.choices(names, weights=[weights[n] for n in names], k=1)[0])


def complete_work(reg: StatusRegistry, task: Task, at_s: int, rng: random.Random,
                  allotted_min: int | None = None) -> tuple[Transition, Task | None]:
    """Finish a task: transition the zone, clear the task, and raise any follow-up.

    Returns (transition, follow_up_task_or_None). The caller removes the task from the active
    pool — completion must remove it from backend state and from the map, not just mark it.
    """
    outcome = sample_outcome(task, allotted_min, rng)
    tr = reg.apply(task.zone.ref, Event.WORK_COMPLETED, at_s, outcome, task.id,
                   note=f"{task.label} completed")
    task.completed = True
    task.outcome = outcome

    follow_up: Task | None = None
    if outcome in (TrackStatus.CAUTION_ORDER, TrackStatus.STOP_AND_START):
        cfg = load_config()
        follow_up = Task(
            id=f"{task.id}-FU",
            task_type=task.task_type,
            department=task.department,
            zone=task.zone,
            duration_min=max(20, task.duration_min // 2),
            priority=max(1, task.priority - 1),  # a restricted section outranks routine work
            category=TaskCategory.PLANNED,
            requires_power_block=task.requires_power_block,
            requires_traffic_block=task.requires_traffic_block,
            released_s=at_s,
            due_by_s=at_s + int(cfg.get_path("tasks.followup_due_hours", 72)) * 3600,
            is_followup=True,
        )
    return tr, follow_up


def complete_followup(reg: StatusRegistry, task: Task, at_s: int,
                      rng: random.Random) -> Transition:
    cur = reg.get(task.zone.ref)
    options = FOLLOWUP_RESULT.get(cur)
    if options is None:
        raise IllegalTransition(f"followup_completed is not legal from {cur.value}")
    to = rng.choices([o for o, _ in options], weights=[w for _, w in options], k=1)[0]
    task.completed = True
    task.outcome = to
    return reg.apply(task.zone.ref, Event.FOLLOWUP_COMPLETED, at_s, to, task.id,
                     note="restriction lifted")
