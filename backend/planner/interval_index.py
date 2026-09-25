"""Augmented interval tree over candidate windows — fast gap/window lookups.

<!-- serves: J1, J5 -->

`eligible_windows` (backend/planner/cpsat.py) already narrows candidates to one zone via a
plain dict bucket, but still scans every window in that bucket for the release-time and
duration filters. That is fine for the batch weekly solve, called a handful of times. The live
Operations-page simulation (backend/planner/live_sim.py) calls a per-task lookup dozens of
times a minute against buckets that can hold hundreds of windows on a busy interchange, and the
map's click panel needs a query the dict index cannot answer at all: "what is free in this
zone between now and the next few hours". An interval tree answers both — a range query narrows
to only the windows that could possibly qualify before any per-window filter runs, in
O(log n + k) instead of O(n).

This is a new, additional structure alongside the existing `WindowIndex`
(backend/planner/cpsat.py), not a replacement — the CP-SAT/RL call sites that index already
serves are untouched.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from intervaltree import IntervalTree

from backend.domain.models import WorkZoneKind
from backend.domain.task import Task
from backend.gaps.engine import CandidateWindow

ZoneKey = tuple[str, WorkZoneKind]


@dataclass
class IntervalWindowIndex:
    """One augmented interval tree per (zone_ref, zone_kind) bucket."""

    trees: dict[ZoneKey, IntervalTree] = field(default_factory=dict)

    def eligible(self, task: Task) -> list[CandidateWindow]:
        """Windows that could hold this task, same semantics as cpsat.eligible_windows."""
        tree = self.trees.get((task.zone.ref, task.zone.kind))
        if tree is None:
            return []
        lo, hi = task.released_s, tree.end()
        if lo >= hi:
            return []
        out = []
        for iv in tree.overlap(lo, hi):
            w: CandidateWindow = iv.data
            if w.end_s < task.released_s:
                continue
            if task.track is not None and w.track != task.track:
                continue
            if w.usable_min(power_block=task.requires_power_block) < task.reserved_min:
                continue
            out.append(w)
        return out

    def free_in(self, zone_ref: str, zone_kind: WorkZoneKind,
               start_s: int, end_s: int) -> list[CandidateWindow]:
        """Windows overlapping an arbitrary [start_s, end_s) range.

        The query a plain dict bucket cannot answer without scanning everything — used by the
        Operations map's "next available gap" click-panel summary.
        """
        tree = self.trees.get((zone_ref, zone_kind))
        if tree is None or start_s >= end_s:
            return []
        return sorted((iv.data for iv in tree.overlap(start_s, end_s)), key=lambda w: w.start_s)


def build_interval_index(windows: list[CandidateWindow]) -> IntervalWindowIndex:
    trees: dict[ZoneKey, IntervalTree] = {}
    for w in windows:
        if w.end_s <= w.start_s:
            continue  # a zero/negative-length window cannot occur from find_gaps, but be safe
        key = (w.zone_ref, w.zone_kind)
        trees.setdefault(key, IntervalTree())[w.start_s:w.end_s] = w
    return IntervalWindowIndex(trees=trees)
