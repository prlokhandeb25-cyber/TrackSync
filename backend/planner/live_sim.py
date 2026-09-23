"""Live Operations-page simulation: unplanned tasks arrive continuously and get gap-scheduled
in real time on the map.

<!-- serves: J1, J5 -->

ROADMAP.md already names this gap ("continuous demand arrivals... ran out of clock"). This
closes it, deliberately kept separate from the CP-SAT weekly plan and the trained RL dispatcher
(backend/planner/cpsat.py, backend/rl/*) — neither is read from or written to here. It exists to
answer one question, live, several times a minute: "if a bit of unplanned work turns up right
now, can it be slotted in without breaking anything already booked?"

Two named heuristics, honestly scoped (see ASSUMPTIONS.md):

  - Max-to-Min greedy (`order_max_to_min`) — before insertion, a tick's tasks are sorted
    longest-first, so a large job gets first pick of the gaps that can hold it and small jobs
    fit into whatever is left. The classic argument for why insertion order matters in bin
    packing.
  - ALNS-lite (`alns_lite_insert`) — a REPAIR step (cheapest/soonest feasible window, found via
    the interval tree) and, if nothing fits, ONE bounded DESTROY step (evict a single
    lower-priority live-sim task from a contested window and retry once). This is a small,
    honestly-labelled slice of destroy-and-repair local search, not a metaheuristic run to
    convergence — it never touches the authoritative weekly plan, and it reuses the same
    department-compatibility rule engine (backend/domain/compatibility.py) that CP-SAT's model
    is built from, so it can never place a task somewhere the rule engine would reject. It only
    ever inserts into the task's OWN zone's windows, so rerouting never enters the picture and
    the SUBURBAN_LOCAL guardrail (backend/planner/rerouting.py) is not applicable here.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from backend.data.synth_tasks import generate_demand_task
from backend.domain.compatibility import Verdict, compatibility
from backend.domain.network import Network
from backend.domain.task import Task
from backend.gaps.engine import CandidateWindow, GapType
from backend.planner.interval_index import IntervalWindowIndex


@dataclass
class LiveSimPlacement:
    task: Task
    window: CandidateWindow | None
    placed: bool
    reason: str


@dataclass
class LiveSimState:
    """Bookkeeping for tasks this module has placed — kept apart from STATE.plan on purpose."""

    placed: list[LiveSimPlacement] = field(default_factory=list)

    def occupying(self, zone_ref: str) -> list[LiveSimPlacement]:
        return [p for p in self.placed if p.placed and p.window is not None
                and p.window.zone_ref == zone_ref]


def order_max_to_min(tasks: list[Task]) -> list[Task]:
    """Max-to-Min greedy: largest footprint first.

    A big job gets first pick of the gaps that can hold it, while short, flexible jobs (a
    signal-lamp change) can still slip into whatever pockets are left — reversing the order
    would let a run of small jobs fragment the gaps a large job actually needs.
    """
    return sorted(tasks, key=lambda t: t.duration_min, reverse=True)


def random_task(net: Network, rng: random.Random, at_s: int, seq: int) -> Task:
    """One randomly generated unplanned task, in the same shape a real demand injection uses."""
    return generate_demand_task(net, rng, at_s, tid=f"SIM-{seq:05d}")


def _blocked_by(net: Network, candidate: Task, window: CandidateWindow,
                existing: list[Task]) -> Task | None:
    """The first already-committed task this window would conflict with, or None if free.

    Reuses the exact rule engine CP-SAT's model is built from (R0-R4), rather than a parallel
    simplified check, so a live-sim placement can never contradict what the real planner would
    have said about the same pair.
    """
    candidate.scheduled_start_s = window.start_s
    candidate.scheduled_end_s = window.start_s + candidate.duration_min * 60
    for other in existing:
        if other.id == candidate.id or other.scheduled_start_s is None:
            continue
        if not (other.zone.endpoints & candidate.zone.endpoints):
            continue
        verdict = compatibility(net, candidate, other)
        if verdict.value is Verdict.INCOMPATIBLE:
            return other
    return None


def alns_lite_insert(net: Network, candidate: Task, index: IntervalWindowIndex,
                     committed_tasks: list[Task], sim_state: LiveSimState) -> LiveSimPlacement:
    """Try to fit one task into a live gap right now. See module docstring for the algorithm."""
    candidates = index.eligible(candidate)
    # Prefer a gap between trains — the capacity this whole system exists to unlock — then
    # whichever slot comes soonest.
    candidates.sort(key=lambda w: (w.gap_type is not GapType.MICRO_GAP, w.start_s))

    existing = committed_tasks + [p.task for p in sim_state.placed if p.placed]

    # REPAIR: cheapest feasible insertion.
    for w in candidates:
        if _blocked_by(net, candidate, w, existing) is None:
            placement = LiveSimPlacement(candidate, w, True, f"fitted into a {w.describe()}")
            sim_state.placed.append(placement)
            return placement

    # DESTROY, once: evict one lower-priority SIM-placed task from a contested window if the
    # new job outranks it, then retry that one window.
    for w in candidates:
        blocker = _blocked_by(net, candidate, w, existing)
        if (blocker is not None and blocker.id.startswith("SIM-")
                and blocker.priority > candidate.priority):
            sim_state.placed = [p for p in sim_state.placed if p.task.id != blocker.id]
            existing = [t for t in existing if t.id != blocker.id]
            if _blocked_by(net, candidate, w, existing) is None:
                placement = LiveSimPlacement(
                    candidate, w, True,
                    f"fitted into a {w.describe()} after moving aside lower-priority {blocker.id}",
                )
                sim_state.placed.append(placement)
                return placement

    placement = LiveSimPlacement(candidate, None, False, "no free window right now")
    sim_state.placed.append(placement)
    return placement
