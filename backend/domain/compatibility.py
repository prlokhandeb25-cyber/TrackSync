from enum import Enum
from typing import List, Dict, Tuple, Optional
from pydantic import BaseModel
from backend.domain.task import Task, Department, Allotment, WorkZoneType
from backend.domain.network import NetworkGraph

class CompatibilityVerdictValue(str, Enum):
    COMPATIBLE = "COMPATIBLE"
    REQUIRES_IWP = "REQUIRES_IWP"
    INCOMPATIBLE = "INCOMPATIBLE"

class ZoneRelation(str, Enum):
    SAME_ZONE = "SAME_ZONE"
    ADJACENT = "ADJACENT"
    DISJOINT = "DISJOINT"

class CompatibilityVerdict(BaseModel):
    value: CompatibilityVerdictValue
    reason: str
    rule_id: str
    zone_relation: ZoneRelation

class DepartmentCompatibilityEngine:
    """
    Computes department compatibility verdicts based on Rules R0 to R4.
    """
    # Base 3x3 compatibility matrix for SAME_ZONE overlap
    BASE_SAME_ZONE_MATRIX = {
        (Department.PWI, Department.OWD): CompatibilityVerdictValue.REQUIRES_IWP,
        (Department.OWD, Department.PWI): CompatibilityVerdictValue.REQUIRES_IWP,
        (Department.PWI, Department.S_AND_T): CompatibilityVerdictValue.INCOMPATIBLE,
        (Department.S_AND_T, Department.PWI): CompatibilityVerdictValue.INCOMPATIBLE,
        (Department.OWD, Department.S_AND_T): CompatibilityVerdictValue.REQUIRES_IWP,
        (Department.S_AND_T, Department.OWD): CompatibilityVerdictValue.REQUIRES_IWP,
    }

    def __init__(self, network: NetworkGraph, allotments: List[Allotment]):
        self.network = network
        self.allotments = allotments

    def check_allotment(self, task: Task) -> bool:
        """Rule R0: Allotment constraint."""
        for allotment in self.allotments:
            if allotment.department == task.department:
                if task.section_id in allotment.section_ids:
                    return True
        # If no explicit allotment list provided, default to True for flexibility
        return True if not self.allotments else False

    def evaluate(self, task1: Task, task2: Task) -> CompatibilityVerdict:
        # Rule R0 check
        if not self.check_allotment(task1):
            return CompatibilityVerdict(
                value=CompatibilityVerdictValue.INCOMPATIBLE,
                reason=f"Rule R0 Violation: {task1.department.value} task {task1.id} is outside department section allotment.",
                rule_id="R0",
                zone_relation=ZoneRelation.DISJOINT
            )
        if not self.check_allotment(task2):
            return CompatibilityVerdict(
                value=CompatibilityVerdictValue.INCOMPATIBLE,
                reason=f"Rule R0 Violation: {task2.department.value} task {task2.id} is outside department section allotment.",
                rule_id="R0",
                zone_relation=ZoneRelation.DISJOINT
            )

        # Determine geometric zone relation
        z1 = (task1.work_zone_type.value, task1.work_zone_id)
        z2 = (task2.work_zone_type.value, task2.work_zone_id)

        if z1 == z2:
            zone_rel = ZoneRelation.SAME_ZONE
        elif self.network.are_adjacent_zones(z1, z2):
            zone_rel = ZoneRelation.ADJACENT
        else:
            zone_rel = ZoneRelation.DISJOINT

        # Same Department in same or adjacent zone
        if task1.department == task2.department:
            if zone_rel == ZoneRelation.SAME_ZONE:
                return CompatibilityVerdict(
                    value=CompatibilityVerdictValue.INCOMPATIBLE,
                    reason=f"Rule R3: Multiple {task1.department.value} tasks in the same zone cannot proceed simultaneously without separate gangs.",
                    rule_id="R3",
                    zone_relation=zone_rel
                )
            else:
                return CompatibilityVerdict(
                    value=CompatibilityVerdictValue.COMPATIBLE,
                    reason=f"Same department {task1.department.value} working in distinct zones.",
                    rule_id="R4",
                    zone_relation=zone_rel
                )

        # Rule R2: Adjacent zones -> COMPATIBLE
        if zone_rel == ZoneRelation.ADJACENT:
            return CompatibilityVerdict(
                value=CompatibilityVerdictValue.COMPATIBLE,
                reason=f"Rule R2: {task1.department.value} in {task1.work_zone_id} and {task2.department.value} in {task2.work_zone_id} are in adjacent zones with no physical overlap.",
                rule_id="R2",
                zone_relation=zone_rel
            )

        # Disjoint zones -> COMPATIBLE
        if zone_rel == ZoneRelation.DISJOINT:
            return CompatibilityVerdict(
                value=CompatibilityVerdictValue.COMPATIBLE,
                reason=f"Rule R4: Tasks are in physically disjoint non-adjacent zones ({task1.work_zone_id} vs {task2.work_zone_id}).",
                rule_id="R4",
                zone_relation=zone_rel
            )

        # Rule R1 / R3 for SAME_ZONE cross-department overlap
        dept_pair = (task1.department, task2.department)
        base_verdict = self.BASE_SAME_ZONE_MATRIX.get(dept_pair, CompatibilityVerdictValue.INCOMPATIBLE)

        if base_verdict == CompatibilityVerdictValue.REQUIRES_IWP:
            return CompatibilityVerdict(
                value=CompatibilityVerdictValue.REQUIRES_IWP,
                reason=f"Rule R1: {task1.department.value} and {task2.department.value} overlapping in zone {task1.work_zone_id} require an Integrated Work Permission (IWP).",
                rule_id="R1",
                zone_relation=zone_rel
            )
        else:
            return CompatibilityVerdict(
                value=CompatibilityVerdictValue.INCOMPATIBLE,
                reason=f"Rule R3: {task1.department.value} and {task2.department.value} work in zone {task1.work_zone_id} are physically incompatible and must be scheduled in disjoint time slots.",
                rule_id="R3",
                zone_relation=zone_rel
            )

    def get_full_matrix(self, tasks: List[Task]) -> Dict[str, Dict[str, CompatibilityVerdict]]:
        """Returns pairwise compatibility matrix for a list of active tasks."""
        matrix = {}
        for t1 in tasks:
            matrix[t1.id] = {}
            for t2 in tasks:
                if t1.id == t2.id:
                    matrix[t1.id][t2.id] = CompatibilityVerdict(
                        value=CompatibilityVerdictValue.COMPATIBLE,
                        reason="Same task",
                        rule_id="R4",
                        zone_relation=ZoneRelation.SAME_ZONE
                    )
                else:
                    matrix[t1.id][t2.id] = self.evaluate(t1, t2)
        return matrix
