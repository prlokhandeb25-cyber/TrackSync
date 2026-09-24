"""What happens to the rest of the week if a coordinator asks for one more block?

<!-- serves: J1, J5 -->

A block coordinator does not just want to know where a new block FITS; they want to know what it
DISTURBS. This answers that on a copy of the schedule, with an exact solve that is told to keep the
existing plan as it is unless moving something is worth it:

  - the current weekly plan goes in as an anchor and as the solver's starting hint;
  - every job that ends up anywhere other than where it was pays a churn cost (`w11_churn`), small
    next to leaving a job unplaced but large next to shifting a job by a day for no reason;
  - the new job may carry a hard deadline ("by Friday");
  - jobs raised or injected elsewhere (yours, simulated, sudden) that touch the new job's ground are
    held fixed as obstacles, so the answer never collides with something already promised.

The result lists, by name, what stays, what moves (from -> to), and what is dropped, so the
knock-on effects can be read off, drawn and questioned. Nothing is written back to the live plan.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from backend.config import load_config
from backend.data.week import DAY_S
from backend.domain.models import WorkZoneKind
from backend.domain.network import Network
from backend.domain.task import Task
from backend.gaps.engine import CandidateWindow, GapType
from backend.planner.cpsat import build_and_solve


@dataclass
class SlotView:
    start_s: int
    end_s: int
    zone_ref: str
    section_id: str
    track: str
    gap_type: str

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class MoveView:
    task_id: str
    label: str
    department: str
    zone: str
    old: SlotView | None
    new: SlotView | None          # None: could not be kept in the plan

    def to_dict(self) -> dict:
        return {"task_id": self.task_id, "label": self.label, "department": self.department, "zone": self.zone,
                "old": self.old and self.old.to_dict(), "new": self.new and self.new.to_dict()}


@dataclass
class ReplanResult:
    new_task: Task
    status: str
    placed: bool
    new_slot: SlotView | None
    moved: list[MoveView] = field(default_factory=list)
    dropped: list[MoveView] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    solve_s: float = 0.0
    baseline_placed: int = 0
    after_placed: int = 0
    fixed_obstacles: int = 0
    assignments: list = field(default_factory=list)     # the re-solved plan, for callers that refine it
    tasks: list = field(default_factory=list)           # every task that was in the solve (incl. fixed ones)
    windows: list = field(default_factory=list)


def _slot(a) -> SlotView:
    return SlotView(a.start_s, a.end_s, a.zone_ref, a.section_id, a.track, a.gap_type)


def _pin_window(t: Task, start_s: int, end_s: int, wid: str, net: Network) -> CandidateWindow:
    """A one-job window exactly around an existing booking, so the solver can keep it where it is."""
    g = load_config()["gaps"]
    extra = int(g["power_block_extra_min"]) * 60 if t.requires_power_block else 0
    ref = t.zone.ref
    sec = ref if t.zone.kind is WorkZoneKind.SECTION else next(
        (s.id for s in net.sections.values() if ref in (s.from_station, s.to_station)), ref)
    return CandidateWindow(
        id=wid, section_id=sec, zone_ref=ref, zone_kind=t.zone.kind, track="UP", direction="UP",
        start_s=start_s - int(g["block_setup_min"]) * 60 - extra, end_s=end_s + int(g["block_release_min"]) * 60 + extra,
        gap_type=GapType.MICRO_GAP, station_tier=None, created_by="BOOKED")


def replan_with_block(net: Network, tasks: list[Task], windows: list[CandidateWindow], plan,
                      new_task: Task, extra_booked: list[Task], pax=None,
                      time_limit_s: float = 10.0, churn: float = 25.0, hard_deadline: bool = True
                      ) -> ReplanResult:
    """Solve the week again with `new_task` added, changing as little as possible."""
    t0 = time.time()
    copies = {t.id: t.model_copy(deep=True) for t in tasks}
    for c in copies.values():
        c.scheduled_start_s = c.scheduled_end_s = None
        c.window_id = c.gap_type = None
    known = {w.id for w in windows}
    old = {a.task_id: a for a in plan.assignments}

    anchor: dict[str, tuple[str, int]] = {}
    pinned: list[CandidateWindow] = []
    solve_tasks: list[Task] = []
    for tid, c in copies.items():
        a = old.get(tid)
        if a is not None:
            if a.window_id not in known:                       # placed in a created gap: keep it as booked
                pw = _pin_window(c, a.start_s, a.end_s, a.window_id, net)
                pinned.append(pw)
            anchor[tid] = (a.window_id, a.start_s)
        solve_tasks.append(c)

    # jobs already promised elsewhere that touch the new job's ground stay exactly where they are
    ends = new_task.zone.endpoints
    obstacles = 0
    for b in extra_booked:
        if b.id in copies or b.scheduled_start_s is None or not (b.zone.endpoints & ends):
            continue
        c = b.model_copy(deep=True)
        s, e = c.scheduled_start_s, c.scheduled_end_s
        c.released_s, c.scheduled_start_s, c.scheduled_end_s = s, None, None
        wid = f"FIX-{c.id}"
        pinned.append(_pin_window(c, s, e, wid, net))
        anchor[c.id] = (wid, s)
        solve_tasks.append(c)
        obstacles += 1

    nt = new_task.model_copy(deep=True)
    nt.scheduled_start_s = nt.scheduled_end_s = None
    solve_tasks.append(nt)

    res = build_and_solve(net, solve_tasks, windows + pinned, time_limit_s=time_limit_s, relax=[], pax=pax,
                          weights={"w11_churn": churn}, anchor=anchor,
                          hard_due={nt.id} if hard_deadline and nt.due_by_s else None)

    out = ReplanResult(new_task=nt, status=res.status, placed=False, new_slot=None,
                       solve_s=round(time.time() - t0, 1), baseline_placed=len(plan.assignments),
                       fixed_obstacles=obstacles)
    if res.status not in ("OPTIMAL", "FEASIBLE"):
        return out
    out.assignments, out.tasks, out.windows = list(res.assignments), solve_tasks, windows + pinned
    now = {a.task_id: a for a in res.assignments}
    if nt.id in now:
        out.placed, out.new_slot = True, _slot(now[nt.id])
    for tid, a in old.items():
        c = copies.get(tid)
        if c is None:
            continue
        b = now.get(tid)
        mv = MoveView(tid, c.label, c.department.value, c.zone.ref, _slot(a), _slot(b) if b else None)
        if b is None:
            out.dropped.append(mv)
        elif b.start_s != a.start_s:      # a job that kept its time (whatever track) has not been disturbed
            out.moved.append(mv)
        else:
            out.unchanged.append(tid)
    out.after_placed = sum(1 for tid in now if tid in copies)
    return out
