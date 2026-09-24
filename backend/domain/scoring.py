"""Compatibility score per task, and the pair verdict the whole system uses.

<!-- serves: J1, J5 -->

`compatibility()` (compatibility.py) is the rule engine and stays exactly as it is: one of
COMPATIBLE / REQUIRES_IWP / INCOMPATIBLE from zones, departments and time. What it does not know is
what the department raising a job said about it: on the form, each department ticks which OTHER
departments it is willing to share a block with. `pair_verdict` layers that on top - if either side
did not allow the other and they could overlap, the pair is INCOMPATIBLE by declaration (rule id
DECL) - and every consumer (the planner, live scheduling, clustering, this score) goes through it,
so a declaration is honoured everywhere, not just on screen.

The score answers "how well does this job fit with the jobs around it?":

    score = 100 x (compatible pairs + 0.5 x pairs needing a permit) / cross-department pairs

taken over the other departments' jobs in the same cluster (jobs close enough to share a block).
A job with no such neighbours has nothing to conflict with and scores 100, flagged standalone.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.domain.compatibility import (
    CompatibilityResult, Verdict, ZoneRelation, compatibility, overlaps_in_time, zone_relation,
)
from backend.domain.network import Network
from backend.domain.risk import assess_job, assess_pair
from backend.domain.task import Task


def _allows(a: Task, b: Task) -> bool:
    return a.allows_with is None or b.department in a.allows_with or a.department == b.department


def pair_verdict(net: Network, a: Task, b: Task) -> CompatibilityResult:
    """The rule engine's verdict, after the departments' own declarations."""
    if a.department != b.department and overlaps_in_time(a, b):
        blocker = a if not _allows(a, b) else b if not _allows(b, a) else None
        if blocker is not None:
            other = b if blocker is a else a
            return CompatibilityResult(
                Verdict.INCOMPATIBLE,
                (f"{blocker.department.value} did not allow {other.department.value} to work "
                 f"alongside its job, so the two must be at different times (declared)."),
                "DECL", zone_relation(a.zone, b.zone),
            )
    return compatibility(net, a, b)


@dataclass
class TaskScore:
    task_id: str
    score: int
    cluster_id: int | None
    mates: int                       # cross-department jobs in the same cluster
    compatible: int = 0
    requires_iwp: int = 0
    incompatible: int = 0
    standalone: bool = False
    pairs: list[dict] = field(default_factory=list)
    risk: dict | None = None         # hazards, likelihood x severity, controls, residual (domain/risk.py)

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id, "score": self.score, "cluster_id": self.cluster_id,
            "mates": self.mates, "compatible": self.compatible,
            "requires_iwp": self.requires_iwp, "incompatible": self.incompatible,
            "standalone": self.standalone, "pairs": self.pairs, "risk": self.risk,
        }


def score_tasks(net: Network, tasks: list[Task], clusters: list) -> dict[str, TaskScore]:
    """Score every task against the cross-department jobs in its own cluster."""
    by_id = {t.id: t for t in tasks}
    unscheduled = {
        t.id: t.model_copy(update={"scheduled_start_s": None, "scheduled_end_s": None})
        for t in tasks
    }
    out: dict[str, TaskScore] = {}
    for c in clusters:
        for tid in c.task_ids:
            t = by_id[tid]
            sc = TaskScore(task_id=tid, score=100, cluster_id=c.id, mates=0)
            pair_risks: list[tuple[str, dict]] = []
            for oid in c.task_ids:
                o = by_id[oid]
                if oid == tid or o.department == t.department:
                    continue
                sc.mates += 1
                r = pair_verdict(net, unscheduled[tid], unscheduled[oid])
                if r.value is Verdict.COMPATIBLE:
                    sc.compatible += 1
                elif r.value is Verdict.REQUIRES_IWP:
                    sc.requires_iwp += 1
                else:
                    sc.incompatible += 1
                pr = assess_pair(t, o, r.value.value, r.zone_relation.value)
                pair_risks.append((oid, pr))
                sc.pairs.append({"other": oid, "department": o.department.value,
                                 "verdict": r.value.value, "reason": r.reason, "rule": r.rule_id,
                                 "risk": {k: pr[k] for k in ("inherent", "inherent_band", "residual", "residual_band", "top")}})
            if sc.mates:
                sc.score = round(100 * (sc.compatible + 0.5 * sc.requires_iwp) / sc.mates)
            else:
                sc.standalone = True
            sc.risk = assess_job(t, pair_risks)
            out[tid] = sc
    return out
