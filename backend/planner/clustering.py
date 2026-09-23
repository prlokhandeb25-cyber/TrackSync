"""Job clustering — grouping nearby maintenance tasks into candidate integrated blocks.

<!-- serves: J1, J5 -->

Three departments raise work independently. Work that sits in the same stretch of line can share
one protected block (an integrated block) instead of three separate ones, so the first question is
"which jobs are close enough to belong together?". This answers it with average-linkage
agglomerative hierarchical clustering over each job's geographic position, cut at a distance
threshold (config `clustering.cut_km`), using scipy's standard implementation.

Clustering is a grouping signal only. Whether two grouped jobs may actually run at the same time
is still decided by the rule engine (backend/domain/compatibility.py); every cluster reports the
rule engine's verdict tally for its cross-department pairs so the two stay visibly consistent.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage

from backend.config import load_config
from backend.domain.compatibility import Verdict, compatibility
from backend.domain.models import WorkZoneKind
from backend.domain.network import Network
from backend.domain.task import Task


@dataclass
class TaskCluster:
    id: int
    task_ids: list[str]
    zones: list[str]
    departments: list[str]
    total_min: int
    label: str
    lat: float
    lon: float
    compatible: int = 0
    requires_iwp: int = 0
    incompatible: int = 0
    cross_pairs: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id, "size": len(self.task_ids), "task_ids": self.task_ids,
            "zones": sorted(set(self.zones)), "departments": self.departments,
            "total_min": self.total_min, "label": self.label, "lat": self.lat, "lon": self.lon,
            "compatible": self.compatible, "requires_iwp": self.requires_iwp,
            "incompatible": self.incompatible, "cross_pairs": self.cross_pairs,
        }


def _position(net: Network, task: Task) -> tuple[float, float]:
    """Where a job physically is: a station's own position, or the middle of a section."""
    if task.zone.kind == WorkZoneKind.STATION_NODE:
        st = net.stations[task.zone.ref]
        return st.lat, st.lon
    sec = net.sections[task.zone.ref]
    a, b = net.stations[sec.from_station], net.stations[sec.to_station]
    return (a.lat + b.lat) / 2, (a.lon + b.lon) / 2


def _to_km(lat: float, lon: float) -> tuple[float, float]:
    return lon * 111.32 * math.cos(math.radians(lat)), lat * 110.57


def cluster_tasks(net: Network, tasks: list[Task], cut_km: float | None = None) -> list[TaskCluster]:
    """Average-linkage agglomerative clustering of jobs by position, cut at `cut_km`."""
    if not tasks:
        return []
    cut = float(cut_km if cut_km is not None
                else load_config().get_path("clustering.cut_km", 5.0))

    pos = [_position(net, t) for t in tasks]
    if len(tasks) == 1:
        labels = np.array([1])
    else:
        pts = np.array([_to_km(la, lo) for la, lo in pos])
        labels = fcluster(linkage(pts, method="average"), t=cut, criterion="distance")

    groups: dict[int, list[int]] = {}
    for i, lab in enumerate(labels):
        groups.setdefault(int(lab), []).append(i)

    def nearest_station_name(lat: float, lon: float) -> str:
        cx, cy = _to_km(lat, lon)
        return min(
            net.stations.values(),
            key=lambda s: (_to_km(s.lat, s.lon)[0] - cx) ** 2 + (_to_km(s.lat, s.lon)[1] - cy) ** 2,
        ).name

    clusters: list[TaskCluster] = []
    for members in sorted(groups.values(), key=len, reverse=True):
        lat = sum(pos[i][0] for i in members) / len(members)
        lon = sum(pos[i][1] for i in members) / len(members)
        c = TaskCluster(
            id=len(clusters) + 1,
            task_ids=[tasks[i].id for i in members],
            zones=[tasks[i].zone.ref for i in members],
            departments=sorted({tasks[i].department.value for i in members}),
            total_min=sum(tasks[i].duration_min for i in members),
            label=nearest_station_name(lat, lon),
            lat=lat, lon=lon,
        )
        # The rule engine decides what may actually share a block; report its verdicts.
        unscheduled = {
            i: tasks[i].model_copy(update={"scheduled_start_s": None, "scheduled_end_s": None})
            for i in members
        }
        for x, i in enumerate(members):
            for j in members[x + 1:]:
                if tasks[i].department == tasks[j].department:
                    continue
                c.cross_pairs += 1
                v = compatibility(net, unscheduled[i], unscheduled[j]).value
                if v is Verdict.COMPATIBLE:
                    c.compatible += 1
                elif v is Verdict.REQUIRES_IWP:
                    c.requires_iwp += 1
                else:
                    c.incompatible += 1
        clusters.append(c)
    return clusters
