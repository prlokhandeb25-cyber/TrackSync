"""Multi-department bundling: fewer, fuller blocks.

<!-- serves: J1, J5 -->

Three departments raise work separately, and a planner that treats each job on its own opens a
protected block for every one. Clustering (clustering.py) says which jobs sit close together; the
weekly solver already rewards putting a compatible pair in one block (`w8_integrated_block`), but it
does so under a time limit and only among the pairs it happened to consider worth the search.

This is a second, cheap pass over the FINISHED plan that goes looking for merges the solver left:

    for each pair of jobs in one cluster, from different departments, that the rule engine calls
    COMPATIBLE and that do not currently overlap - can the LATER one be slid (in time, and to another
    of its own eligible gaps) so that the two share one block?

A merge is accepted only if

    - the later job lands on the same day or an earlier one (never pushed back: the plan's lateness
      cost cannot get worse),
    - the independent referee (verify.py) still passes on the whole plan, and
    - the number of protected blocks actually goes down.

It is the "dynamic window creation" idea: two jobs near each other in space, which nobody asked to
be together, end up under one possession. The gain is measured on the same plan, before and after,
in two numbers a coordinator cares about: protected blocks, and track-hours held closed.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

from backend.config import load_config
from backend.data.week import DAY_S
from backend.domain.compatibility import Verdict
from backend.domain.models import SectionOccupancy
from backend.domain.network import Network
from backend.domain.scoring import pair_verdict
from backend.domain.task import Task
from backend.planner.clustering import cluster_tasks
from backend.planner.cpsat import build_window_index
from backend.planner.verify import verify_plan


@dataclass
class BundleReport:
    blocks_before: int = 0
    blocks_after: int = 0
    held_min_before: int = 0
    held_min_after: int = 0
    merges: list[dict] = field(default_factory=list)
    tried: int = 0

    def to_dict(self) -> dict:
        return {"blocks_before": self.blocks_before, "blocks_after": self.blocks_after,
                "held_hours_before": round(self.held_min_before / 60, 1),
                "held_hours_after": round(self.held_min_after / 60, 1),
                "merges": self.merges, "pairs_tried": self.tried}


def count_blocks(tasks_by_id: dict[str, Task], assignments: list, cluster_of: dict[str, int]) -> tuple[int, int]:
    """(protected blocks, minutes of track held closed).

    Two jobs share a block when they are from different departments, in the same cluster, and overlap in
    time. Held minutes are the union of each block's intervals, so a shared block counts once."""
    n = len(assignments)
    parent = list(range(n))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for i in range(n):
        ti = tasks_by_id.get(assignments[i].task_id)
        for j in range(i + 1, n):
            tj = tasks_by_id.get(assignments[j].task_id)
            if ti is None or tj is None or ti.department == tj.department:
                continue
            ci, cj = cluster_of.get(ti.id), cluster_of.get(tj.id)
            if ci is not None and ci == cj and assignments[i].start_s < assignments[j].end_s \
                    and assignments[j].start_s < assignments[i].end_s:
                parent[find(i)] = find(j)
    groups: dict[int, list[tuple[int, int]]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append((assignments[i].start_s, assignments[i].end_s))
    held = 0
    for spans in groups.values():
        spans.sort()
        cur_s, cur_e = spans[0]
        for s, e in spans[1:]:
            if s > cur_e:
                held += cur_e - cur_s
                cur_s, cur_e = s, e
            else:
                cur_e = max(cur_e, e)
        held += cur_e - cur_s
    return len(groups), held // 60


def bundle_plan(net: Network, tasks: list[Task], assignments: list, windows: list,
                occ_by_section: dict[str, list[SectionOccupancy]], max_merges: int = 30
                ) -> tuple[list, BundleReport]:
    """Return a copy of the plan with as many extra shared blocks as the rules allow, and the measurement."""
    by_id = {t.id: t for t in tasks}
    placed_tasks = [by_id[a.task_id] for a in assignments if a.task_id in by_id]
    cluster_of: dict[str, int] = {}
    for c in cluster_tasks(net, placed_tasks):
        for tid in c.task_ids:
            cluster_of[tid] = c.id

    new = [copy.copy(a) for a in assignments]
    rep = BundleReport()
    rep.blocks_before, rep.held_min_before = count_blocks(by_id, new, cluster_of)
    widx = build_window_index(windows)
    g = load_config()["gaps"]
    setup_s, release_s, extra_s = int(g["block_setup_min"]) * 60, int(g["block_release_min"]) * 60, int(g["power_block_extra_min"]) * 60
    pos = {a.task_id: i for i, a in enumerate(new)}
    blocks_now = rep.blocks_before

    # candidate pairs: same cluster, different departments, not already sharing a block
    pairs = []
    for c in {v for v in cluster_of.values()}:
        ids = [t for t, cid in cluster_of.items() if cid == c and t in pos]
        for x, a in enumerate(ids):
            for b in ids[x + 1:]:
                if by_id[a].department != by_id[b].department:
                    pairs.append((a, b))
    pairs.sort(key=lambda p: abs(new[pos[p[0]]].start_s - new[pos[p[1]]].start_s))     # nearest in time first

    for a_id, b_id in pairs:
        if len(rep.merges) >= max_merges:
            break
        A, B = new[pos[a_id]], new[pos[b_id]]
        if A.start_s < B.end_s and B.start_s < A.end_s:
            continue                                               # already sharing a block
        mover, anchor = (A, B) if A.start_s >= B.start_s else (B, A)   # the later job joins the earlier one
        mt = by_id[mover.task_id]
        if (mover.window_id or "").startswith(("CW-", "FIX-")) or (anchor.window_id or "").startswith(("CW-", "FIX-")):
            continue
        rep.tried += 1
        ov_probe_m = mt.model_copy(update={"scheduled_start_s": anchor.start_s, "scheduled_end_s": anchor.start_s + mt.duration_min * 60})
        ov_probe_a = by_id[anchor.task_id].model_copy(update={"scheduled_start_s": anchor.start_s, "scheduled_end_s": anchor.end_s})
        if pair_verdict(net, ov_probe_m, ov_probe_a).value is not Verdict.COMPATIBLE:
            continue
        dur = mt.duration_min * 60
        extra = extra_s if mt.requires_power_block else 0
        best = None
        for w in widx.get((mt.zone.ref, mt.zone.kind), []):
            if w.usable_min(power_block=mt.requires_power_block) < mt.duration_min:
                continue
            lo, hi = w.start_s + setup_s + extra, w.end_s - release_s - extra - dur
            lo = max(lo, mt.released_s)
            if hi < lo:
                continue
            # start that overlaps the anchor as much as the window allows, nearest the anchor's start
            s = min(max(anchor.start_s, lo), hi)
            if not (s < anchor.end_s and anchor.start_s < s + dur):
                continue
            if s // DAY_S > mover.start_s // DAY_S:
                continue                                           # never later than it already was
            score = abs(s - anchor.start_s)
            if best is None or score < best[0]:
                best = (score, s, w)
        if best is None:
            continue
        _, s, w = best
        old = (mover.start_s, mover.end_s, mover.window_id, mover.track, mover.section_id, mover.zone_ref, mover.gap_type)
        mover.start_s, mover.end_s = s, s + dur
        mover.window_id, mover.track, mover.section_id, mover.zone_ref, mover.gap_type = w.id, w.track, w.section_id, w.zone_ref, w.gap_type.value
        n_blocks, held = count_blocks(by_id, new, cluster_of)
        ok = n_blocks < blocks_now and verify_plan(net, tasks, new, windows, occ_by_section).ok
        if ok:
            blocks_now = n_blocks
            rep.merges.append({"task_id": mover.task_id, "joined": anchor.task_id, "from_s": old[0], "to_s": s,
                               "zone": mt.zone.ref, "blocks_after": n_blocks})
        else:
            (mover.start_s, mover.end_s, mover.window_id, mover.track, mover.section_id,
             mover.zone_ref, mover.gap_type) = old
    rep.blocks_after, rep.held_min_after = count_blocks(by_id, new, cluster_of)
    return new, rep
