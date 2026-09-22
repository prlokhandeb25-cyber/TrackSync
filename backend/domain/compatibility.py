"""Department work compatibility — the automated replacement for manual coordination.

<!-- serves: J1, J5 -->

Today, workers report needed work to their department head, and the S&T, OWD and PWI heads
coordinate between themselves by phone to decide who can work where and when without
conflicting. This module computes that decision instead.

Rules, in evaluation order (SPEC §7.2):

    R0  Allotment. A department may only work inside the section set the control office
        allotted it. Work outside it is infeasible, full stop.
    R1  Same work zone, overlapping time, different departments -> REQUIRES_IWP.
        An Integrated Work Permission is a distinct status: not "compatible", not
        "incompatible". It is a limited daily resource that has to be granted.
    R2  Physically distinct but adjacent zones, overlapping time -> COMPATIBLE.
        The canonical case: PWI on the Matunga-Dadar section while OWD works Matunga station.
        They share an endpoint but do not overlap, so they do not physically conflict.
    R3  Incompatible -> different time slots entirely. A hard constraint, never a penalty.
    R4  Department-pair base matrix, then the geometric relation. A hook for domain rules
        that hold regardless of geometry.

Every verdict carries a human-readable reason. Those strings are what the UI shows and what
ends up screenshotted in the deck, so they are written to be read by a person.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from backend.config import load_config
from backend.domain.network import Network
from backend.domain.task import Department, Task, WorkZone
from backend.domain.models import WorkZoneKind


class Verdict(str, Enum):
    COMPATIBLE = "COMPATIBLE"
    REQUIRES_IWP = "REQUIRES_IWP"
    INCOMPATIBLE = "INCOMPATIBLE"


class ZoneRelation(str, Enum):
    SAME_ZONE = "SAME_ZONE"
    ADJACENT = "ADJACENT"
    DISJOINT = "DISJOINT"


@dataclass
class CompatibilityResult:
    value: Verdict
    reason: str
    rule_id: str
    zone_relation: ZoneRelation

    def to_dict(self) -> dict:
        return {
            "value": self.value.value,
            "reason": self.reason,
            "rule_id": self.rule_id,
            "zone_relation": self.zone_relation.value,
        }


# R4: department-pair base matrix. COMPATIBLE here means "geometry decides"; a pair set to
# INCOMPATIBLE would be barred from sharing a slot no matter where the work is. All three
# pairs are currently geometry-decided — we have no evidence for a blanket department-pair
# prohibition, and inventing one would be fiction.
BASE_MATRIX: dict[tuple[Department, Department], Verdict] = {
    (Department.PWI, Department.OWD): Verdict.COMPATIBLE,
    (Department.PWI, Department.S_AND_T): Verdict.COMPATIBLE,
    (Department.OWD, Department.S_AND_T): Verdict.COMPATIBLE,
}


def base_verdict(a: Department, b: Department) -> Verdict:
    if a == b:
        return Verdict.COMPATIBLE
    return BASE_MATRIX.get((a, b)) or BASE_MATRIX.get((b, a)) or Verdict.COMPATIBLE


def zone_relation(z1: WorkZone, z2: WorkZone) -> ZoneRelation:
    """How two work zones sit relative to each other.

    A SECTION and a STATION_NODE at one of its endpoints are ADJACENT, not overlapping — that
    is the whole basis of R2, and it is why WorkZone keeps the two kinds distinct.
    """
    if z1.kind == z2.kind and z1.ref == z2.ref:
        return ZoneRelation.SAME_ZONE
    if z1.endpoints & z2.endpoints:
        return ZoneRelation.ADJACENT
    return ZoneRelation.DISJOINT


def overlaps_in_time(t1: Task, t2: Task) -> bool:
    """Do two scheduled tasks overlap? Unscheduled tasks are treated as potentially overlapping."""
    if None in (t1.scheduled_start_s, t1.scheduled_end_s, t2.scheduled_start_s, t2.scheduled_end_s):
        return True
    return t1.scheduled_start_s < t2.scheduled_end_s and t2.scheduled_start_s < t1.scheduled_end_s


def is_allotted(net: Network, dept: Department, zone: WorkZone) -> bool:
    """R0. A station-node task is allotted if the department holds any section touching it."""
    allotted = set(net.allotments.get(dept.value, []))
    if zone.kind == WorkZoneKind.SECTION:
        return zone.ref in allotted
    return any(zone.ref in sid.split("-") for sid in allotted)


def check_allotment(net: Network, task: Task) -> CompatibilityResult | None:
    """Returns a rejection if the task falls outside its department's allotment, else None."""
    if is_allotted(net, task.department, task.zone):
        return None
    return CompatibilityResult(
        Verdict.INCOMPATIBLE,
        (f"{task.department.value} is not allotted {task.zone.describe()} by the control "
         f"office this week, so it cannot work there at any time (R0)."),
        "R0",
        ZoneRelation.DISJOINT,
    )


def compatibility(net: Network, t1: Task, t2: Task) -> CompatibilityResult:
    """The verdict for a pair of tasks. Order-independent."""
    rel = zone_relation(t1.zone, t2.zone)

    # R0 first: an unallotted task cannot be paired with anything.
    for t in (t1, t2):
        rejection = check_allotment(net, t)
        if rejection is not None:
            return rejection

    if not overlaps_in_time(t1, t2):
        return CompatibilityResult(
            Verdict.COMPATIBLE,
            "Scheduled in different time slots, so they cannot conflict.",
            "R3", rel,
        )

    base = base_verdict(t1.department, t2.department)
    if base == Verdict.INCOMPATIBLE:
        return CompatibilityResult(
            Verdict.INCOMPATIBLE,
            (f"{t1.department.value} and {t2.department.value} work is barred from sharing a "
             f"slot regardless of location (R4 base matrix)."),
            "R4", rel,
        )

    # R1 — same zone, same time.
    if rel == ZoneRelation.SAME_ZONE:
        if t1.department == t2.department:
            return CompatibilityResult(
                Verdict.INCOMPATIBLE,
                (f"Both jobs are {t1.department.value} work in {t1.zone.describe()}; one gang "
                 f"cannot do both at once, so they must be sequenced (R1)."),
                "R1", rel,
            )
        return CompatibilityResult(
            Verdict.REQUIRES_IWP,
            (f"{t1.department.value} and {t2.department.value} both need {t1.zone.describe()} "
             f"at the same time. Working together in one zone requires an Integrated Work "
             f"Permission (R1)."),
            "R1", rel,
        )

    # R2 — adjacent but physically distinct.
    if rel == ZoneRelation.ADJACENT:
        shared = ", ".join(sorted(t1.zone.endpoints & t2.zone.endpoints))
        if t1.department == t2.department:
            who = (f"Two {t1.department.value} jobs, one on {t1.zone.describe()} and one on "
                   f"{t2.zone.describe()}")
        else:
            who = (f"{t1.department.value} is on {t1.zone.describe()} while "
                   f"{t2.department.value} is on {t2.zone.describe()}")
        return CompatibilityResult(
            Verdict.COMPATIBLE,
            (f"{who}. They meet at {shared} but do not physically overlap, so both can "
             f"proceed together (R2)."),
            "R2", rel,
        )

    # Disjoint zones, overlapping time.
    return CompatibilityResult(
        Verdict.COMPATIBLE,
        (f"{t1.zone.describe().capitalize()} and {t2.zone.describe()} are separate parts of the "
         f"corridor, so the two jobs do not interact (R2)."),
        "R2", rel,
    )


def matrix(net: Network, tasks: list[Task]) -> dict:
    """Full pairwise matrix for the UI, with per-cell reasons and a summary."""
    cells: list[dict] = []
    counts = {v.value: 0 for v in Verdict}
    for i, a in enumerate(tasks):
        for b in tasks[i + 1:]:
            r = compatibility(net, a, b)
            counts[r.value.value] += 1
            cells.append({"a": a.id, "b": b.id, **r.to_dict()})
    return {
        "tasks": [
            {
                "id": t.id, "department": t.department.value, "label": t.label,
                "zone": t.zone.ref, "zone_kind": t.zone.kind.value,
                "duration_min": t.duration_min, "priority": t.priority,
                "category": t.category.value,
            }
            for t in tasks
        ],
        "cells": cells,
        "summary": counts,
        "iwp_quota_per_day": load_config().get_path("departments.iwp_quota_per_day", 2),
        "base_matrix": [
            {"a": a.value, "b": b.value, "value": v.value}
            for (a, b), v in BASE_MATRIX.items()
        ],
    }


def coordination_conflicts(net: Network, tasks: list[Task]) -> int:
    """Cross-department pairs a human would have had to negotiate.

    This is the count the "before" baseline multiplies by its per-conflict negotiation time,
    so it is the hinge of the department-coordination metric in the impact study.
    """
    n = 0
    for i, a in enumerate(tasks):
        for b in tasks[i + 1:]:
            if a.department == b.department:
                continue
            r = compatibility(net, a, b)
            if r.value in (Verdict.REQUIRES_IWP, Verdict.INCOMPATIBLE):
                n += 1
    return n
