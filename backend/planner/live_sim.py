"""Scheduling for jobs that arrive one at a time: simulated arrivals and jobs raised by a user.

<!-- serves: J1, J5 -->

ROADMAP.md already names this gap ("continuous demand arrivals"). This closes it, kept separate
from the CP-SAT weekly plan and the trained RL dispatcher (backend/planner/cpsat.py, backend/rl/*):
neither is read from or written to here. It answers one question, live: "if a job turns up right
now, where does it go?"

Three ideas, each honestly scoped (see ASSUMPTIONS.md):

  - Max-to-Min greedy (`order_max_to_min`): a batch is inserted longest-first, so a large job gets
    first pick of the gaps that can hold it and short jobs fit into what is left.
  - Integrated blocks: among the windows that fit, the job prefers to start alongside a nearby job
    from another department that the rule engine (and the departments' own declarations) allow to
    share a block - one protected block doing two jobs instead of two blocks.
  - ALNS-lite: a REPAIR step (best-scoring feasible window, from the interval tree) and, if nothing
    fits, gap CREATION (backend/gaps/creation.py: hold a train, reroute a long-distance train, or
    run single-line) and then ONE bounded DESTROY step (evict a lower-priority simulated job and
    retry). Not run to convergence; it never touches the weekly plan.

Every placement goes through `pair_verdict`, so it can never sit somewhere the rule engine, or a
department's own declaration, would reject. It only ever inserts into the job's OWN zone, so
rerouting of trains happens only inside gap creation, where locals are never offered to it.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Callable

from backend.config import load_config
from backend.data.synth_tasks import generate_demand_task
from backend.domain.compatibility import Verdict
from backend.domain.network import Network
from backend.domain.scoring import pair_verdict
from backend.domain.task import Task
from backend.gaps.creation import CreationOption
from backend.gaps.engine import CandidateWindow, GapType
from backend.planner.interval_index import IntervalWindowIndex

MAX_KEPT = 400   # simulated placements remembered; older ones are long past on the sim clock


@dataclass
class LiveSimPlacement:
    task: Task
    window: CandidateWindow | None
    placed: bool
    reason: str
    start_s: int | None = None
    end_s: int | None = None
    integrated_with: list[str] = field(default_factory=list)
    created: CreationOption | None = None
    steps: list[str] = field(default_factory=list)


@dataclass
class LiveSimState:
    """Bookkeeping for tasks this module has placed — kept apart from STATE.plan on purpose."""

    placed: list[LiveSimPlacement] = field(default_factory=list)

    def occupying(self, zone_ref: str) -> list[LiveSimPlacement]:
        return [p for p in self.placed if p.placed and p.window is not None
                and p.window.zone_ref == zone_ref]

    def add(self, p: LiveSimPlacement) -> None:
        self.placed.append(p)
        del self.placed[:-MAX_KEPT]


def order_max_to_min(tasks: list[Task]) -> list[Task]:
    """Max-to-Min greedy: largest footprint first.

    A big job gets first pick of the gaps that can hold it, while short, flexible jobs (a
    signal-lamp change) can still slip into whatever pockets are left — reversing the order
    would let a run of small jobs fragment the gaps a large job actually needs.
    """
    return sorted(tasks, key=lambda t: t.duration_min, reverse=True)


def random_task(net: Network, rng: random.Random, at_s: int, seq: int) -> Task:
    """One randomly generated unplanned task, in the same shape a real demand injection uses."""
    t = generate_demand_task(net, rng, at_s, tid=f"SIM-{seq:05d}")
    t.source = "SIM"
    return t


def _overheads(task: Task) -> tuple[int, int]:
    """Seconds lost before work starts and after it ends inside a window."""
    g = load_config()["gaps"]
    extra = int(g["power_block_extra_min"]) if task.requires_power_block else 0
    return (int(g["block_setup_min"]) + extra) * 60, (int(g["block_release_min"]) + extra) * 60


def _blocked_by(net: Network, candidate: Task, start_s: int, existing: list[Task]) -> Task | None:
    """The first committed task this start time would conflict with, or None if free.

    Reuses the rule engine (R0-R4) plus the departments' own declarations, rather than a parallel
    simplified check, so a placement can never contradict what the real planner would say.
    """
    end_s = start_s + candidate.duration_min * 60
    candidate.scheduled_start_s = start_s
    candidate.scheduled_end_s = end_s
    for other in existing:
        if other.id == candidate.id or other.scheduled_start_s is None:
            continue
        if other.scheduled_start_s >= end_s or (other.scheduled_end_s or 0) <= start_s:
            continue  # not at the same time: cannot conflict (rule R3)
        if not (other.zone.endpoints & candidate.zone.endpoints):
            continue
        if pair_verdict(net, candidate, other).value is Verdict.INCOMPATIBLE:
            return other
    return None


def _mates(net: Network, candidate: Task, existing: list[Task], radius_km: float) -> list[Task]:
    """Scheduled jobs from another department, close by, that may share a block with this one."""
    from backend.planner.clustering import _position, _to_km  # same geometry as the clustering

    cx, cy = _to_km(*_position(net, candidate))
    out = []
    for o in existing:
        if o.id == candidate.id or o.scheduled_start_s is None or o.department == candidate.department:
            continue
        ox, oy = _to_km(*_position(net, o))
        if (ox - cx) ** 2 + (oy - cy) ** 2 > radius_km ** 2:
            continue
        probe = o.model_copy(update={"scheduled_start_s": None, "scheduled_end_s": None})
        cand = candidate.model_copy(update={"scheduled_start_s": None, "scheduled_end_s": None})
        if pair_verdict(net, cand, probe).value is not Verdict.INCOMPATIBLE:
            out.append(o)
    return out


def _choose_start(candidate: Task, w: CandidateWindow, mates: list[Task]) -> tuple[int, int, list[Task]]:
    """Latest/earliest start inside the window, pulled toward a mate's slot when they can overlap."""
    setup, release = _overheads(candidate)
    dur = candidate.duration_min * 60
    lo = w.start_s + setup
    hi = w.end_s - release - dur
    if hi < lo:
        return lo, 0, []
    best, best_ov, best_with = lo, 0, []
    for m in mates:
        ms, me = m.scheduled_start_s or 0, m.scheduled_end_s or 0
        s = min(max(ms, lo), hi)
        ov = min(s + dur, me) - max(s, ms)
        if ov > best_ov:
            best, best_ov, best_with = s, ov, [m]
    if best_with:
        # anyone else whose slot the chosen start also overlaps
        best_with += [m for m in mates if m not in best_with
                      and min(best + dur, m.scheduled_end_s or 0) - max(best, m.scheduled_start_s or 0) > 0]
    return best, best_ov // 60, best_with


def _hhmm(s: int) -> str:
    s %= 86400
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}"


Creator = Callable[[Task, int], list[CreationOption]]


def alns_lite_insert(net: Network, candidate: Task, index: IntervalWindowIndex,
                     committed_tasks: list[Task], sim_state: LiveSimState,
                     creator: Creator | None = None, at_s: int | None = None) -> LiveSimPlacement:
    """Place one task now. See the module docstring for the algorithm."""
    radius = float(load_config().get_path("clustering.cut_km", 5.0))
    from_s = candidate.released_s if at_s is None else at_s
    existing = committed_tasks + [p.task for p in sim_state.placed if p.placed]
    steps: list[str] = []

    windows = index.eligible(candidate)
    setup, release = _overheads(candidate)
    dur_s = candidate.duration_min * 60
    if candidate.due_by_s is not None:
        # an urgent job must be finished by its deadline; a gap that opens later is no use
        windows = [w for w in windows if w.start_s + setup + dur_s <= candidate.due_by_s]
        steps.append(f"It must be finished by {_hhmm(candidate.due_by_s)}"
                     f" (day {candidate.due_by_s // 86400 + 1}); only gaps before then count.")
    steps.append(f"{len(windows)} gaps on {candidate.zone.ref} are long enough for {candidate.duration_min} min of work.")
    mates = _mates(net, candidate, existing, radius)
    if mates:
        steps.append(f"{len(mates)} nearby job(s) from other departments could share a block with it.")

    scored = []
    for w in windows:
        start, ov, with_ = _choose_start(candidate, w, mates)
        # integrated blocks first, then gaps between trains, then the soonest slot
        score = (0 if w.gap_type is GapType.MICRO_GAP else 30) - 3 * ov + (start - from_s) / 3600
        scored.append((score, start, ov, with_, w))
    scored.sort(key=lambda r: r[0])

    def done(w: CandidateWindow, start: int, with_: list[Task], why: str,
             created: CreationOption | None = None) -> LiveSimPlacement:
        end = start + candidate.duration_min * 60
        candidate.scheduled_start_s, candidate.scheduled_end_s = start, end
        candidate.window_id, candidate.gap_type = w.id, w.gap_type.value
        p = LiveSimPlacement(candidate, w, True, why, start, end,
                             [m.id for m in with_], created, steps)
        sim_state.add(p)
        return p

    # REPAIR: best-scoring feasible window.
    for _, start, ov, with_, w in scored:
        if _blocked_by(net, candidate, start, existing) is None:
            kind = {GapType.MICRO_GAP: "gap between trains", GapType.NIGHT_WINDOW: "night window",
                    GapType.MEGABLOCK: "Sunday megablock"}[w.gap_type]
            why = (f"placed {_hhmm(start)}-{_hhmm(start + candidate.duration_min * 60)} on "
                   f"{w.section_id} ({w.track}), {kind}")
            if with_:
                why += f", alongside {with_[0].department.value} job {with_[0].id} in one block"
                steps.append(f"Started it at {_hhmm(start)} so it overlaps {with_[0].id}: one protected block, two jobs.")
            else:
                steps.append(f"Took the best open slot at {_hhmm(start)}.")
            return done(w, start, with_, why)

    # CREATE: no gap in the timetable fits, so ask what small change to the trains would open one.
    if creator is not None:
        steps.append("No natural gap fits, so I looked for a small change to the trains that opens one.")
        for opt in creator(candidate, from_s):
            if candidate.due_by_s is not None and opt.start_s + setup + dur_s > candidate.due_by_s:
                continue
            w = opt.to_window(f"C{len(sim_state.placed):05d}-{opt.section_id}", net)
            setup, _ = _overheads(candidate)
            start = w.start_s + setup
            if _blocked_by(net, candidate, start, existing) is None:
                steps.append(f"Opened a gap: {opt.note}. It costs {opt.delay_min:.1f} train-minutes.")
                why = (f"no gap long enough, so one was created ({opt.note}; "
                       f"{opt.delay_min:.1f} train-min) — placed {_hhmm(start)}-"
                       f"{_hhmm(start + candidate.duration_min * 60)} on {w.section_id} ({w.track})")
                return done(w, start, [], why, created=opt)

    # DESTROY, once: evict one lower-priority SIM-placed task from a contested window if the new
    # job outranks it, then retry that one window.
    for _, start, ov, with_, w in scored:
        blocker = _blocked_by(net, candidate, start, existing)
        if (blocker is not None and blocker.id.startswith("SIM-")
                and blocker.priority > candidate.priority):
            sim_state.placed = [p for p in sim_state.placed if p.task.id != blocker.id]
            existing = [t for t in existing if t.id != blocker.id]
            if _blocked_by(net, candidate, start, existing) is None:
                steps.append(f"Moved aside lower-priority {blocker.id} to make room.")
                return done(w, start, [], f"placed {_hhmm(start)} on {w.section_id} after moving "
                            f"aside lower-priority {blocker.id}")

    p = LiveSimPlacement(candidate, None, False, "no free window right now", steps=steps)
    sim_state.add(p)
    return p
