"""Sudden tasks: work that appears mid-week and was never in the planned pool.

<!-- serves: J1, J5 -->

A defect reported on Tuesday afternoon cannot wait for the weekly cycle, and re-solving the whole
week (`planner/cpsat.py`, seconds) for every report is not how a control room works. This places
one such job in the live schedule, in milliseconds, in this order:

  1. FIT     the best existing gap: it must finish before the job's deadline, follow the rules
             against every job already booked, prefer a quiet stretch of line (few trains and
             passengers within reach), and start alongside a compatible neighbour if one is close.
  2. CREATE  if no gap fits in time, open one with a small priced change to the trains (hold one
             a few minutes, divert a long-distance train, or run one track for both directions).
             Suburban locals are never rerouted.
  3. BUMP    if that still fails, and the job outranks what is in the way, push at most
             `sudden.max_bumped` LOWER-priority jobs aside and re-place each of them elsewhere.
             A job that cannot be re-placed is reported as deferred, never silently lost.

It is the same ALNS-style destroy/repair used for simulated arrivals (`live_sim.py`), with a real
deadline by priority and a tighter rule about what may be displaced. Every step is written down.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from backend.planner.aging import effective_priority, record_bump
from backend.config import load_config
from backend.domain.compatibility import Verdict
from backend.domain.network import Network
from backend.domain.scoring import pair_verdict
from backend.domain.task import Task
from backend.gaps.engine import CandidateWindow
from backend.planner.interval_index import IntervalWindowIndex
from backend.planner.live_sim import (
    Creator, LiveSimPlacement, LiveSimState, _hhmm, _mates, _overheads, alns_lite_insert,
    rank_windows,
)

LEVELS = {"low": 5, "medium": 3, "high": 2, "critical": 1}
LEVEL_NAME = {5: "Low", 4: "Low", 3: "Medium", 2: "High", 1: "Critical"}


def due_hours(priority: int) -> int:
    table = load_config().get_path("sudden.due_hours", {})
    return int(table.get(priority, table.get(str(priority), 72)))


@dataclass
class Move:
    """One job pushed aside by a sudden task, and where it went."""

    task: Task
    old: dict
    new: LiveSimPlacement | None      # None: could not be re-placed, deferred


@dataclass
class SuddenResult:
    task: Task
    placement: LiveSimPlacement | None
    method: str                       # gap | created | bumped | none
    moves: list[Move] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    response_ms: float = 0.0


def _slot(t: Task) -> dict:
    return {"start_s": t.scheduled_start_s, "end_s": t.scheduled_end_s, "zone": t.zone.ref}


def _all_blockers(net: Network, candidate: Task, start_s: int, existing: list[Task]) -> list[Task]:
    end_s = start_s + candidate.duration_min * 60
    candidate.scheduled_start_s, candidate.scheduled_end_s = start_s, end_s
    out = []
    for other in existing:
        if other.id == candidate.id or other.scheduled_start_s is None:
            continue
        if other.scheduled_start_s >= end_s or (other.scheduled_end_s or 0) <= start_s:
            continue
        if not (other.zone.endpoints & candidate.zone.endpoints):
            continue
        if pair_verdict(net, candidate, other).value is Verdict.INCOMPATIBLE:
            out.append(other)
    return out


def place_sudden(net: Network, task: Task, index: IntervalWindowIndex, committed: list[Task],
                 state: LiveSimState, creator: Creator | None, at_s: int, pax,
                 movable: Callable[[Task], bool]) -> SuddenResult:
    """Fit, then create, then bump. `committed` is everything already booked, whatever its source."""
    t0 = time.perf_counter()
    max_bumped = int(load_config().get_path("sudden.max_bumped", 2))
    res = SuddenResult(task, None, "none")

    p = alns_lite_insert(net, task, index, committed, state, creator=creator, at_s=at_s,
                         pax=pax, allow_destroy=False)
    res.steps = list(p.steps)
    if p.placed:
        res.placement = p
        res.method = "created" if p.created is not None else "gap"
        res.response_ms = (time.perf_counter() - t0) * 1000
        return res

    # BUMP: the cheapest set of strictly lower-priority jobs whose removal frees a window.
    res.steps.append("Nothing fits, even after opening a gap, so I looked at pushing lower-priority work aside.")
    existing = committed + [x.task for x in state.placed if x.placed]
    setup, _ = _overheads(task)
    dur_s = task.duration_min * 60
    windows = [w for w in index.eligible(task) if w.end_s > at_s
               and (task.due_by_s is None or w.start_s + setup + dur_s <= task.due_by_s)]
    mates = _mates(net, task, existing, 5.0)
    options = []
    for r in rank_windows(net, task, windows, existing, mates, at_s, pax):
        blockers = _all_blockers(net, task, r["start"], existing)
        if not blockers or len(blockers) > max_bumped:
            continue
        # aging: a job that has waited a long time, or been moved before, is protected (planner/aging.py)
        if any(effective_priority(b, at_s) <= task.priority or not movable(b) for b in blockers):
            continue
        options.append((len(blockers), -sum(b.priority for b in blockers), r["score"], r, blockers))
    options.sort(key=lambda o: o[:3])

    if not options:
        res.steps.append("No lower-priority job can be moved to make room either.")
        # LATE: book the earliest slot there is and say plainly that the deadline is missed, rather
        # than leave an urgent fault with no plan at all.
        due, task.due_by_s = task.due_by_s, None
        late = alns_lite_insert(net, task, index, committed, state, creator=None, at_s=at_s,
                                pax=pax, allow_destroy=False)
        task.due_by_s = due
        res.steps.append("No slot exists before the deadline. Booked the earliest one that does and flagged it late."
                         if late.placed else "No slot exists at all in the coming days.")
        if late.placed:
            res.placement, res.method = late, "late"
        res.response_ms = (time.perf_counter() - t0) * 1000
        return res

    _, _, _, r, blockers = options[0]
    old = {b.id: _slot(b) for b in blockers}
    for b in blockers:
        record_bump(b.id)          # each time a job is pushed aside it ages one step, so it cannot be pushed forever
    for b in blockers:
        b.scheduled_start_s = b.scheduled_end_s = None
    w: CandidateWindow = r["window"]
    start = r["start"]
    task.scheduled_start_s, task.scheduled_end_s = start, start + dur_s
    task.window_id, task.gap_type = w.id, w.gap_type.value
    exp = pax.exposure(w.section_id, start, start + dur_s) if pax is not None else None
    res.steps.append(f"Pushed aside {len(blockers)} lower-priority job(s): "
                     + ", ".join(f"{b.id} (P{b.priority})" for b in blockers) + ".")
    place = LiveSimPlacement(task, w, True,
                             f"placed {_hhmm(start)}-{_hhmm(start + dur_s)} on {w.section_id} "
                             f"({w.track}) after moving lower-priority work",
                             start, start + dur_s, [], None, res.steps,
                             None if exp is None else exp.to_dict())
    state.add(place)
    res.placement, res.method = place, "bumped"

    # REPAIR the displaced jobs: each gets the chance to go somewhere else, from now on.
    rest = [t for t in existing if t.id not in old]
    for b in blockers:
        scratch = LiveSimState()
        np = alns_lite_insert(net, b, index, rest + [task], scratch, creator=None, at_s=at_s,
                              pax=pax, commit=False, allow_destroy=False)
        res.moves.append(Move(b, old[b.id], np if np.placed else None))
        if np.placed:
            rest.append(b)
            res.steps.append(f"{b.id} re-placed at {_hhmm(np.start_s or 0)} on {b.zone.ref}.")
        else:
            b.scheduled_start_s = b.scheduled_end_s = None
            res.steps.append(f"{b.id} could not be re-placed and is deferred.")
    res.response_ms = (time.perf_counter() - t0) * 1000
    return res
