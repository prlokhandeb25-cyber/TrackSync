from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field

class Department(str, Enum):
    S_AND_T = "S_AND_T"  # Signalling & Telecom
    OWD = "OWD"          # Overhead Wire Department (Traction / Electrical)
    PWI = "PWI"          # Permanent Way Inspector (Track & Gearing)

class TaskCategory(str, Enum):
    PLANNED = "PLANNED"  # Weekly batch cycle (Monday start)
    DEMAND = "DEMAND"    # Unplanned defect discovered during execution

class WorkZoneType(str, Enum):
    SECTION = "SECTION"
    STATION_NODE = "STATION_NODE"

class TaskStatus(str, Enum):
    PENDING = "PENDING"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    DEFERRED = "DEFERRED"

class Task(BaseModel):
    id: str
    department: Department
    task_type: str                      # e.g. "rail_renewal", "ohe_tension", "point_machine"
    section_id: str                     # Target section or station yard
    work_zone_type: WorkZoneType = WorkZoneType.SECTION
    work_zone_id: str = ""              # section_id or station_id
    duration_min: int                   # Work duration in minutes
    priority: int = 1                   # 1 (highest) to 5 (lowest)
    category: TaskCategory = TaskCategory.PLANNED
    requires_power_block: bool = False  # OWD isolation required
    requires_traffic_block: bool = True
    released_at_min: int = 0            # Release timestamp in minutes
    due_by_min: int = 10080             # Deadline timestamp in minutes (e.g. week end)
    status: TaskStatus = TaskStatus.PENDING
    scheduled_start_min: Optional[int] = None
    scheduled_end_min: Optional[int] = None
    assigned_window_id: Optional[str] = None
    resulting_status_on_completion: str = "FIT"

    def model_post_init(self, __context):
        if not self.work_zone_id:
            object.__setattr__(self, "work_zone_id", self.section_id)

class Allotment(BaseModel):
    department: Department
    section_ids: List[str]
    valid_from_min: int = 0
    valid_to_min: int = 10080
