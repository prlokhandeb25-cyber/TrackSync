"""Adapter interfaces and mock implementations (SPEC §16).

<!-- serves: J4 -->
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from backend.config import load_config
from backend.domain.task import Department, Task


@dataclass
class AdapterInfo:
    system: str
    full_name: str
    role: str
    direction: str            # "in" | "out" | "both"
    department: str | None
    methods: list[str]
    mode: str
    schema_status: str = (
        "assumed - internal IR system, no public API; shapes pending access"
    )

    def to_dict(self) -> dict:
        return self.__dict__


class Adapter(ABC):
    system = "UNKNOWN"
    full_name = ""
    role = ""
    direction = "in"
    department: str | None = None

    @property
    def mode(self) -> str:
        return str(load_config().get_path("adapters.mode", "mock"))

    @abstractmethod
    def methods(self) -> list[str]: ...

    def info(self) -> AdapterInfo:
        return AdapterInfo(self.system, self.full_name, self.role, self.direction,
                           self.department, self.methods(), self.mode)


class _TaskSource(Adapter):
    """Common shape for the three systems that hold departmental maintenance records."""

    dept: Department = Department.PWI
    direction = "in"

    def methods(self) -> list[str]:
        return [f"fetch_{self.system.lower()}_tasks()", "post_work_completion(task, outcome)"]

    def fetch_tasks(self, tasks: list[Task]) -> list[dict]:
        """Mock: the tasks this department would have raised in its own system."""
        return [
            {
                "source_system": self.system,
                "external_ref": f"{self.system}-{t.id}",
                "department": t.department.value,
                "asset": t.zone.ref,
                "asset_kind": t.zone.kind.value,
                "defect_type": t.task_type,
                "description": t.label,
                "estimated_minutes": t.duration_min,
                "priority": t.priority,
                "raised_at_s": t.released_s,
            }
            for t in tasks if t.department is self.dept
        ]

    def post_work_completion(self, task: Task, outcome: str) -> dict:
        return {"source_system": self.system, "external_ref": f"{self.system}-{task.id}",
                "status": "ACKNOWLEDGED", "asset": task.zone.ref, "outcome": outcome}


class TMSAdapter(_TaskSource):
    system = "TMS"
    full_name = "Track Management System"
    role = "Track and P-Way asset condition; the source of PWI work"
    dept = Department.PWI
    department = "PWI"


class SMMSAdapter(_TaskSource):
    system = "SMMS"
    full_name = "Signalling Maintenance Management System"
    role = "Signalling and telecom maintenance records; the source of S&T work"
    dept = Department.S_AND_T
    department = "S_AND_T"


class TDMSAdapter(_TaskSource):
    system = "TDMS"
    full_name = "Traction Distribution Management System"
    role = "Overhead equipment and traction distribution; the source of OWD work"
    dept = Department.OWD
    department = "OWD"

    def methods(self) -> list[str]:
        return super().methods() + ["fetch_power_block_constraints()"]

    def fetch_power_block_constraints(self, tasks: list[Task]) -> list[dict]:
        """Which jobs need the overhead line de-energised, and what that costs in time."""
        cfg = load_config()["gaps"]
        extra = int(cfg["power_block_extra_min"])
        return [
            {"external_ref": f"TDMS-{t.id}", "asset": t.zone.ref,
             "requires_power_block": True,
             "isolation_minutes": extra, "de_earthing_minutes": extra}
            for t in tasks if t.requires_power_block
        ]


class BDMSAdapter(Adapter):
    system = "BDMS"
    full_name = "Block Demand Management System"
    role = "Where block demands are raised and sanctioned; our plan is submitted here"
    direction = "out"

    def methods(self) -> list[str]:
        return ["fetch_pending_block_demands()", "submit_block_plan(plan)",
                "fetch_sanction_status(block_id)"]

    def submit_block_plan(self, assignments: list, tasks_by_id: dict) -> list[dict]:
        """The plan, expressed as the block demands BDMS would receive."""
        out = []
        for a in assignments:
            t = tasks_by_id.get(a.task_id)
            if t is None:
                continue
            out.append({
                "block_demand_ref": f"BDMS-REQ-{a.task_id}",
                "section": a.section_id,
                "work_zone": a.zone_ref,
                "track": a.track,
                "department": t.department.value,
                "from_s": a.start_s,
                "to_s": a.end_s,
                "duration_min": t.duration_min,
                "nature_of_work": t.label,
                "power_block_required": t.requires_power_block,
                "traffic_block_required": t.requires_traffic_block,
                "window_kind": a.gap_type,
                "status": "SUBMITTED",
            })
        return out

    def fetch_sanction_status(self, block_id: str) -> dict:
        return {"block_demand_ref": block_id, "status": "SANCTIONED",
                "sanctioned_by": "Divisional Control (mock)"}


class COAAdapter(Adapter):
    system = "COA"
    full_name = "Control Office Application"
    role = "Live train running and control charts; closes the loop on block impact"
    direction = "both"

    def methods(self) -> list[str]:
        return ["fetch_live_train_positions()", "fetch_actual_running(date)",
                "notify_block_impact(block_ref, trains_affected)"]

    def fetch_live_train_positions(self, trains: list[dict]) -> list[dict]:
        return [{"train_id": t["id"], "class": t["cls"], "section": t["section"],
                 "lat": t["lat"], "lon": t["lon"]} for t in trains]

    def notify_block_impact(self, block_ref: str, trains_affected: int) -> dict:
        return {"block_demand_ref": block_ref, "trains_affected": trains_affected,
                "status": "NOTIFIED"}


def registry() -> dict[str, Adapter]:
    return {
        "TMS": TMSAdapter(), "SMMS": SMMSAdapter(), "TDMS": TDMSAdapter(),
        "BDMS": BDMSAdapter(), "COA": COAAdapter(),
    }


def all_adapters() -> list[dict]:
    return [a.info().to_dict() for a in registry().values()]
