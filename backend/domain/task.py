"""Maintenance tasks, departments and work zones.

<!-- serves: J1, J5 -->

Three departments issue maintenance work on Indian Railways, and each maps onto an existing
IR system that already holds its records (SPEC §16):

    PWI      Permanent Way Inspector   track and gearing        -> TMS
    OWD      Overhead Wire Department  traction / OHE           -> TDMS
    S_AND_T  Signalling & Telecom      signalling and telecom   -> SMMS

Today the three department heads negotiate compatibility between themselves by phone. That
negotiation is what this system automates (see compatibility.py).
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from backend.domain.models import TrackStatus, WorkZoneKind


class Department(str, Enum):
    PWI = "PWI"
    OWD = "OWD"
    S_AND_T = "S_AND_T"

    @property
    def label(self) -> str:
        return {
            "PWI": "Permanent Way (P.Way)",
            "OWD": "Overhead Wire (Traction)",
            "S_AND_T": "Signalling & Telecom",
        }[self.value]

    @property
    def source_system(self) -> str:
        """The existing IR system this department's tasks would arrive from (SPEC §16)."""
        return {"PWI": "TMS", "OWD": "TDMS", "S_AND_T": "SMMS"}[self.value]


class TaskCategory(str, Enum):
    PLANNED = "PLANNED"  # decided on the weekly cycle, finalised every Monday
    DEMAND = "DEMAND"  # discovered during execution; must still be fitted properly


class WorkZone(BaseModel):
    """Where work physically happens.

    The SECTION / STATION_NODE distinction is load-bearing: rule R2 turns on the fact that a
    section and a station at one of its ends are adjacent, not overlapping. Collapsing the two
    would silently delete that rule.
    """

    kind: WorkZoneKind
    ref: str  # section id ("DR-MTN") or station code ("MTN")

    @property
    def endpoints(self) -> set[str]:
        return set(self.ref.split("-")) if self.kind == WorkZoneKind.SECTION else {self.ref}

    @property
    def section_id(self) -> str | None:
        return self.ref if self.kind == WorkZoneKind.SECTION else None

    def describe(self) -> str:
        return (f"the {self.ref} section" if self.kind == WorkZoneKind.SECTION
                else f"{self.ref} station")

    def __hash__(self) -> int:
        return hash((self.kind, self.ref))


class TaskType(BaseModel):
    code: str
    label: str
    department: Department
    min_duration_min: int
    max_duration_min: int
    requires_power_block: bool = False
    requires_traffic_block: bool = True
    # Probability of each outcome when the work is completed with its FULL time allowance.
    # A job squeezed into less than it needs degrades more often — see fsm.sample_outcome.
    outcome_weights: dict[str, float] = Field(
        default_factory=lambda: {"FIT": 0.75, "CAUTION_ORDER": 0.20, "STOP_AND_START": 0.05}
    )


# Task catalogue. Durations and outcome weights are assumptions (A-016); the task types
# themselves are real categories of work these departments carry out.
TASK_TYPES: list[TaskType] = [
    # ---- PWI: track and gearing
    TaskType(code="PWI_RAIL_RENEWAL", label="Rail / weld renewal", department=Department.PWI,
             min_duration_min=90, max_duration_min=360,
             outcome_weights={"FIT": 0.80, "CAUTION_ORDER": 0.17, "STOP_AND_START": 0.03}),
    TaskType(code="PWI_TAMPING", label="Track tamping", department=Department.PWI,
             min_duration_min=60, max_duration_min=180,
             outcome_weights={"FIT": 0.55, "CAUTION_ORDER": 0.40, "STOP_AND_START": 0.05}),
    TaskType(code="PWI_BALLAST", label="Ballast screening", department=Department.PWI,
             min_duration_min=120, max_duration_min=300,
             outcome_weights={"FIT": 0.60, "CAUTION_ORDER": 0.35, "STOP_AND_START": 0.05}),
    TaskType(code="PWI_JOINT", label="Fish-plate / joint attention", department=Department.PWI,
             min_duration_min=20, max_duration_min=60,
             outcome_weights={"FIT": 0.85, "CAUTION_ORDER": 0.13, "STOP_AND_START": 0.02}),
    TaskType(code="PWI_POINTS", label="Points & crossings attention", department=Department.PWI,
             min_duration_min=45, max_duration_min=150,
             outcome_weights={"FIT": 0.70, "CAUTION_ORDER": 0.25, "STOP_AND_START": 0.05}),
    TaskType(code="PWI_GAUGE", label="Gauge correction", department=Department.PWI,
             min_duration_min=40, max_duration_min=120,
             outcome_weights={"FIT": 0.65, "CAUTION_ORDER": 0.30, "STOP_AND_START": 0.05}),
    # ---- OWD: overhead equipment. Power block required throughout.
    TaskType(code="OWD_TENSION", label="OHE wire tension adjustment", department=Department.OWD,
             min_duration_min=60, max_duration_min=180, requires_power_block=True),
    TaskType(code="OWD_INSULATOR", label="Insulator replacement", department=Department.OWD,
             min_duration_min=45, max_duration_min=120, requires_power_block=True),
    TaskType(code="OWD_DROPPER", label="Dropper / jumper repair", department=Department.OWD,
             min_duration_min=30, max_duration_min=90, requires_power_block=True),
    TaskType(code="OWD_MAST", label="Mast / cantilever attention", department=Department.OWD,
             min_duration_min=90, max_duration_min=240, requires_power_block=True),
    # ---- S&T: signalling and telecom
    TaskType(code="SNT_POINT_MACHINE", label="Point machine servicing", department=Department.S_AND_T,
             min_duration_min=40, max_duration_min=120),
    TaskType(code="SNT_TRACK_CIRCUIT", label="Track circuit fault", department=Department.S_AND_T,
             min_duration_min=25, max_duration_min=90),
    TaskType(code="SNT_SIGNAL_LAMP", label="Signal lamp / LED replacement",
             department=Department.S_AND_T, min_duration_min=20, max_duration_min=45,
             requires_traffic_block=False),
    TaskType(code="SNT_AXLE_COUNTER", label="Axle counter attention", department=Department.S_AND_T,
             min_duration_min=30, max_duration_min=100),
    TaskType(code="SNT_CABLE_RELAY", label="Cable & relay room work", department=Department.S_AND_T,
             min_duration_min=60, max_duration_min=200, requires_traffic_block=False),
    TaskType(code="SNT_INTERLOCK", label="Interlocking testing", department=Department.S_AND_T,
             min_duration_min=120, max_duration_min=300),
]

TASK_TYPES_BY_CODE = {t.code: t for t in TASK_TYPES}


class Task(BaseModel):
    id: str
    task_type: str  # -> TASK_TYPES_BY_CODE
    department: Department
    zone: WorkZone
    duration_min: int
    buffer_min: int = 0  # extra time reserved after the work for a crew that usually overruns (A-045)
    priority: int = 3  # 1 = highest
    category: TaskCategory = TaskCategory.PLANNED
    requires_power_block: bool = False
    requires_traffic_block: bool = True
    released_s: int = 0  # absolute seconds from week start
    due_by_s: int | None = None
    # set once scheduled / executed
    scheduled_start_s: int | None = None
    scheduled_end_s: int | None = None
    window_id: str | None = None
    gap_type: str | None = None
    completed: bool = False
    outcome: TrackStatus | None = None
    is_followup: bool = False
    # Where the job came from and what its raiser said about it. `allows_with` is the checkbox the
    # raising department ticks: the OTHER departments it is willing to share a block with. None
    # means no restriction (generated jobs), leaving the decision entirely to the rule engine.
    # The exact line the work is on (one of the section's tracks, e.g. UP_SLOW). None = any line of the section,
    # the planner picks; set = work only on that line and no other (A-061).
    track: str | None = None
    source: str = "SYNTH"           # SYNTH | SIM | USER
    description: str = ""
    allows_with: list[Department] | None = None

    @property
    def reserved_min(self) -> int:
        """Minutes of block the job holds: its work plus any adaptive buffer."""
        return self.duration_min + self.buffer_min

    @property
    def type_def(self) -> TaskType:
        return TASK_TYPES_BY_CODE[self.task_type]

    @property
    def label(self) -> str:
        return self.type_def.label

    def describe(self) -> str:
        """One human-readable line, for the status board."""
        cat = "unplanned" if self.category == TaskCategory.DEMAND else "planned"
        if self.description:
            return (f"{self.department.value} - {self.description} on {self.zone.describe()}, "
                    f"{self.duration_min} min, priority {self.priority} ({cat})")
        return (f"{self.department.value} {self.label.lower()} on {self.zone.describe()}, "
                f"{self.duration_min} min, priority {self.priority} ({cat})")
