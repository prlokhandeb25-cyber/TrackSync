"""Synthetic maintenance task generation.

<!-- serves: J1, J4 -->

Maintenance task data has no public source, so it is generated here. The structure is what
matters and it is not arbitrary: tasks are drawn from real categories of departmental work,
respect the control office's allotments, and are weighted toward sections that are already
SICK or under restriction — which is how a real backlog behaves.

In deployment these tasks arrive from the systems that already hold them:
PWI from TMS, S&T from SMMS, OWD from TDMS (SPEC §16).
"""

from __future__ import annotations

import random

from backend.config import load_config
from backend.domain.compatibility import is_allotted
from backend.domain.fsm import StatusRegistry
from backend.domain.models import TrackStatus, WorkZoneKind
from backend.domain.network import Network
from backend.domain.task import (
    TASK_TYPES,
    Department,
    Task,
    TaskCategory,
    TaskType,
    WorkZone,
)

# Degraded sections attract follow-up attention; SICK ones attract the most.
STATUS_WEIGHT = {
    TrackStatus.FIT: 1.0,
    TrackStatus.CAUTION_ORDER: 4.0,
    TrackStatus.STOP_AND_START: 6.0,
    TrackStatus.SICK: 8.0,
}


def _candidate_zones(net: Network, tt: TaskType) -> list[WorkZone]:
    """Zones this task type could legally occupy, respecting R0 allotment."""
    zones: list[WorkZone] = []
    for sid in net.sections:
        z = WorkZone(kind=WorkZoneKind.SECTION, ref=sid)
        if is_allotted(net, tt.department, z):
            zones.append(z)
    # Point machines, interlocking and OHE at stations are station-node work by nature.
    if tt.code in ("SNT_POINT_MACHINE", "SNT_INTERLOCK", "SNT_CABLE_RELAY",
                   "OWD_INSULATOR", "OWD_MAST", "PWI_POINTS"):
        for code in net.order:
            z = WorkZone(kind=WorkZoneKind.STATION_NODE, ref=code)
            if is_allotted(net, tt.department, z):
                zones.append(z)
    return zones


def generate_tasks(
    net: Network,
    n: int,
    rng: random.Random,
    registry: StatusRegistry | None = None,
    category: TaskCategory = TaskCategory.PLANNED,
    released_s: int = 0,
    id_prefix: str = "T",
) -> list[Task]:
    cfg = load_config()
    due_h = int(cfg.get_path("tasks.planned_due_hours", 168))
    tasks: list[Task] = []

    for i in range(n):
        tt = rng.choice(TASK_TYPES)
        zones = _candidate_zones(net, tt)
        if not zones:
            continue
        if registry is not None:
            weights = [STATUS_WEIGHT[registry.get(z.ref)] for z in zones]
            zone = rng.choices(zones, weights=weights, k=1)[0]
        else:
            zone = rng.choice(zones)

        duration = rng.randint(tt.min_duration_min, tt.max_duration_min)
        # Priority skews high for safety-critical categories and restricted sections.
        base_priority = rng.choices([1, 2, 3, 4, 5], weights=[6, 16, 40, 26, 12], k=1)[0]
        if registry is not None and registry.get(zone.ref) in (
            TrackStatus.STOP_AND_START, TrackStatus.CAUTION_ORDER
        ):
            base_priority = max(1, base_priority - 1)

        tasks.append(
            Task(
                id=f"{id_prefix}-{i:04d}",
                task_type=tt.code,
                department=tt.department,
                zone=zone,
                duration_min=duration,
                priority=base_priority,
                category=category,
                requires_power_block=tt.requires_power_block,
                requires_traffic_block=tt.requires_traffic_block,
                released_s=released_s,
                due_by_s=released_s + due_h * 3600,
            )
        )
    return tasks


def generate_demand_task(net: Network, rng: random.Random, at_s: int,
                         zone: WorkZone | None = None, tid: str = "D-0001") -> Task:
    """A defect discovered during execution, which was not in the weekly plan.

    Demand tasks are the live case for the RL dispatcher: they arrive mid-schedule and have to
    be fitted properly rather than appended to the end of the queue.
    """
    cfg = load_config()
    tt = rng.choice([t for t in TASK_TYPES if t.min_duration_min <= 60])
    if zone is None:
        zones = _candidate_zones(net, tt)
        zone = rng.choice(zones)
    return Task(
        id=tid,
        task_type=tt.code,
        department=tt.department,
        zone=zone,
        duration_min=rng.randint(tt.min_duration_min, min(tt.max_duration_min, 90)),
        priority=rng.choices([1, 2, 3], weights=[35, 45, 20], k=1)[0],
        category=TaskCategory.DEMAND,
        requires_power_block=tt.requires_power_block,
        requires_traffic_block=tt.requires_traffic_block,
        released_s=at_s,
        due_by_s=at_s + int(cfg.get_path("tasks.demand_due_hours", 24)) * 3600,
    )


def seed_sick_sections(net: Network, registry: StatusRegistry, tasks: list[Task],
                       at_s: int = 0) -> None:
    """Mark every zone that has outstanding work as SICK.

    A task exists because a defect was found, so the two must not drift apart: a pending task
    on a zone the registry still calls FIT would be a lie the whole simulation inherits.
    """
    from backend.domain.fsm import Event

    for zone_ref in {t.zone.ref for t in tasks}:
        if registry.get(zone_ref) is TrackStatus.FIT:
            registry.apply(zone_ref, Event.DEFECT_REPORTED, at_s, TrackStatus.SICK,
                           note="defect identified by department inspection")
