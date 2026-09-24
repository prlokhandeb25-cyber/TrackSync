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
from backend.domain.compatibility import Verdict
from backend.domain.scoring import pair_verdict
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
    medoid_id: str | None = None      # K-Medoids only: the job at the group's centre
    mean_priority: float = 0.0
    priority_spread: int = 0          # most urgent to least urgent job in the group (0 = all alike)
    anchor_id: str | None = None      # the biggest job: the block the small ones ride in
    riders: list = field(default_factory=list)   # small, compatible, similarly urgent jobs that ride in the anchor block
    setup_saved_min: int = 0          # set-up + hand-back time not spent because riders share the anchor block

    def to_dict(self) -> dict:
        return {
            "medoid_id": self.medoid_id, "mean_priority": round(self.mean_priority, 1), "priority_spread": self.priority_spread,
            "anchor_id": self.anchor_id, "riders": self.riders, "setup_saved_min": self.setup_saved_min,
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


def _pw(priority_km: float | None) -> float:
    return float(priority_km if priority_km is not None else load_config().get_path("clustering.priority_km", 2.0))


def _feat(net: Network, tasks: list[Task], priority_km: float | None = None) -> np.ndarray:
    """Where a job is (km) plus how urgent it is (priority steps x `priority_km`): jobs group when they are
    both close and similarly urgent, so a P1 is not made to wait for the P5 next to it."""
    w = _pw(priority_km)
    return np.array([[*_to_km(*_position(net, t)), w * t.priority] for t in tasks])


def _dist(pts: np.ndarray) -> np.ndarray:
    d = pts[:, None, :] - pts[None, :, :]
    return np.sqrt((d ** 2).sum(-1))


def pam(D: np.ndarray, k: int, seed: int = 0, restarts: int = 6) -> tuple[np.ndarray, list[int]]:
    """K-Medoids by partitioning around medoids: greedy build, then swap until no swap lowers the cost.

    A medoid is an actual job, not an average point, so the group's "centre" is a real place where
    a shared block could go. Restarts guard against a poor start; the best total distance wins.
    """
    n = len(D)
    rng = np.random.default_rng(seed)
    best_cost, best = float("inf"), None
    for r in range(restarts):
        med = [int(np.argmin(D.sum(1)))] if r == 0 else [int(rng.integers(n))]
        while len(med) < k:                                   # BUILD: add the job that helps most
            cur = D[:, med].min(1)
            gain = np.array([(cur - np.minimum(cur, D[:, j])).sum() if j not in med else -1.0 for j in range(n)])
            med.append(int(np.argmax(gain)))
        cost = D[:, med].min(1).sum()
        improved = True
        while improved:                                       # SWAP: try each (medoid, non-medoid) exchange
            improved = False
            for mi in range(k):
                for j in range(n):
                    if j in med:
                        continue
                    trial = med[:mi] + [j] + med[mi + 1:]
                    c = D[:, trial].min(1).sum()
                    if c < cost - 1e-9:
                        med, cost, improved = trial, c, True
        if cost < best_cost:
            best_cost, best = cost, list(med)
    labels = D[:, best].argmin(1)
    return labels, best


def silhouette(D: np.ndarray, labels: np.ndarray) -> float:
    """Mean silhouette: 1 = tight and well separated, 0 = borderline, below 0 = probably misplaced."""
    n = len(D)
    uniq = np.unique(labels)
    if len(uniq) < 2 or len(uniq) >= n:
        return 0.0
    s = np.zeros(n)
    for i in range(n):
        same = (labels == labels[i])
        if same.sum() <= 1:
            continue                                          # a singleton scores 0 by convention
        a = D[i, same].sum() / (same.sum() - 1)
        b = min(D[i, labels == u].mean() for u in uniq if u != labels[i])
        s[i] = (b - a) / max(a, b, 1e-9)
    return float(s.mean())


def kmedoids_auto(pts: np.ndarray, k_max: int = 12) -> tuple[np.ndarray, list[int], int]:
    """K-Medoids with the number of groups chosen by silhouette rather than by a fixed distance cut."""
    D = _dist(pts)
    n = len(pts)
    if n < 3:
        return np.zeros(n, dtype=int), [0], 1
    best = None
    for k in range(2, min(k_max, n - 1) + 1):
        labels, med = pam(D, k)
        sc = silhouette(D, labels)
        if best is None or sc > best[0] + 1e-9:
            best = (sc, labels, med, k)
    return best[1], best[2], best[3]


def compare_methods(net: Network, tasks: list[Task], cut_km: float | None = None) -> dict:
    """Both groupings on the same jobs, scored the same way: silhouette, group count, and how far
    the jobs in a group sit from the group's centre (mean km) and from each other (widest km)."""
    cut = float(cut_km if cut_km is not None else load_config().get_path("clustering.cut_km", 5.0))
    if len(tasks) < 4:
        return {"n": len(tasks), "methods": []}
    pts = np.array([_to_km(*_position(net, t)) for t in tasks])         # where jobs are, for the km figures
    feats = _feat(net, tasks)                                           # where AND how urgent, for the grouping
    D = _dist(feats)
    Dk = _dist(pts)
    out = []

    def score(name: str, labels: np.ndarray, centres: dict[int, int | None]) -> dict:
        groups = {int(u): np.where(labels == u)[0] for u in np.unique(labels)}
        multi = [g for g in groups.values() if len(g) > 1]
        to_centre = []
        for u, g in groups.items():
            c = centres.get(u)
            centre = pts[c] if c is not None else pts[g].mean(0)
            to_centre += [float(np.hypot(*(pts[i] - centre))) for i in g]
        return {"method": name, "groups": len(groups), "shared_groups": len(multi),
                "silhouette": round(silhouette(D, labels), 3),
                "mean_km_to_centre": round(float(np.mean(to_centre)), 2),
                "widest_group_km": round(max((float(Dk[np.ix_(g, g)].max()) for g in multi), default=0.0), 2)}

    lab_h = fcluster(linkage(feats, method="average"), t=cut, criterion="distance")
    out.append(score("Average-linkage (hierarchical)", lab_h, {}))
    lab_k, med, k = kmedoids_auto(feats)
    out.append(score("K-Medoids (k by silhouette)", lab_k, {int(u): int(med[int(u)]) for u in np.unique(lab_k)}))
    return {"n": len(tasks), "cut_km": cut, "methods": out}


def cluster_tasks(net: Network, tasks: list[Task], cut_km: float | None = None,
                  method: str | None = None, priority_km: float | None = None) -> list[TaskCluster]:
    """Group jobs by position: average-linkage cut at `cut_km` (default), or K-Medoids (`method="kmedoids"`)."""
    if not tasks:
        return []
    cut = float(cut_km if cut_km is not None
                else load_config().get_path("clustering.cut_km", 5.0))
    method = method or str(load_config().get_path("clustering.method", "average"))

    pos = [_position(net, t) for t in tasks]
    medoid_of: dict[int, int] = {}
    if len(tasks) == 1:
        labels = np.array([1])
    elif method == "kmedoids" and len(tasks) >= 3:
        pts = _feat(net, tasks, priority_km)
        lab0, med, _ = kmedoids_auto(pts)
        labels = lab0 + 1
        medoid_of = {int(u) + 1: int(med[int(u)]) for u in np.unique(lab0)}
    else:
        pts = _feat(net, tasks, priority_km)
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
    for lab, members in sorted(groups.items(), key=lambda kv: len(kv[1]), reverse=True):
        mi = medoid_of.get(lab)
        if mi is not None:                    # K-Medoids: the group's centre is one of its own jobs
            lat, lon = pos[mi]
        else:
            lat = sum(pos[i][0] for i in members) / len(members)
            lon = sum(pos[i][1] for i in members) / len(members)
        c = TaskCluster(
            id=len(clusters) + 1,
            task_ids=[tasks[i].id for i in members],
            zones=[tasks[i].zone.ref for i in members],
            departments=sorted({tasks[i].department.value for i in members}),
            total_min=sum(tasks[i].duration_min for i in members),
            label=nearest_station_name(lat, lon),
            lat=lat, lon=lon, medoid_id=None if mi is None else tasks[mi].id,
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
                v = pair_verdict(net, unscheduled[i], unscheduled[j]).value
                if v is Verdict.COMPATIBLE:
                    c.compatible += 1
                elif v is Verdict.REQUIRES_IWP:
                    c.requires_iwp += 1
                else:
                    c.incompatible += 1
        prios = [tasks[i].priority for i in members]
        c.mean_priority = sum(prios) / len(prios)
        c.priority_spread = max(prios) - min(prios)
        _attach_riders(net, c, [tasks[i] for i in members], {tasks[i].id: unscheduled[i] for i in members})
        clusters.append(c)
    return clusters


def _attach_riders(net: Network, c: TaskCluster, members: list[Task], unsched: dict) -> None:
    """The biggest job is the anchor; small jobs the rules allow beside it, of similar urgency, ride in its block."""
    if len(members) < 2:
        return
    cfg = load_config()
    small = int(cfg.get_path("clustering.small_job_min", 45))
    gap = int(cfg.get_path("clustering.rider_priority_gap", 1))
    g = cfg["gaps"]
    anchor = max(members, key=lambda t: (t.duration_min, -t.priority))
    if anchor.duration_min <= small:
        return                                                    # no big job here: nothing to ride on
    c.anchor_id = anchor.id
    for t in members:
        if t.id == anchor.id or t.duration_min > small or abs(t.priority - anchor.priority) > gap:
            continue
        v = pair_verdict(net, unsched[t.id], unsched[anchor.id]).value
        if v is Verdict.INCOMPATIBLE and t.department != anchor.department:
            continue                                              # same department simply runs after the anchor in the block
        c.riders.append({"id": t.id, "label": t.label, "department": t.department.value, "duration_min": t.duration_min,
                         "priority": t.priority, "verdict": v.value})
    c.setup_saved_min = len(c.riders) * (int(g["block_setup_min"]) + int(g["block_release_min"]))


def priority_effect(net: Network, tasks: list[Task]) -> dict:
    """Grouping by place alone against place AND urgency, on the same jobs: how many groups mix very urgent with very
    routine work, and how many small jobs get to ride in a big job's block."""
    def stats(pk: float) -> dict:
        cl = cluster_tasks(net, tasks, method="average", priority_km=pk)
        multi = [x for x in cl if len(x.task_ids) > 1]
        return {"groups": len(cl), "shared_groups": len(multi),
                "mixed_urgency_groups": sum(1 for x in multi if x.priority_spread >= 3),
                "riders": sum(len(x.riders) for x in cl), "setup_saved_min": sum(x.setup_saved_min for x in cl)}
    return {"place_only": stats(0.0), "place_and_urgency": stats(_pw(None)), "priority_km": _pw(None),
            "small_job_min": int(load_config().get_path("clustering.small_job_min", 45))}


def cluster_trace(net: Network, tasks: list[Task], cut_km: float | None = None) -> dict:
    """The clustering run laid out step by step, for the explainer pages.

    Same positions, same linkage, same cut as `cluster_tasks`; this returns the merge history
    (scipy's linkage matrix) alongside the final groups so a UI can replay it.
    """
    cut = float(cut_km if cut_km is not None
                else load_config().get_path("clustering.cut_km", 5.0))
    pos = [_position(net, t) for t in tasks]
    pts = _feat(net, tasks) if tasks else np.zeros((0, 3))
    merges = []
    labels: list[int] = []
    if len(tasks) >= 2:
        z = linkage(pts, method="average")
        labels = [int(x) for x in fcluster(z, t=cut, criterion="distance")]
        n = len(tasks)
        for k, (a, b, d, size) in enumerate(z):
            merges.append({"a": int(a), "b": int(b), "distance_km": round(float(d), 2),
                           "size": int(size), "id": n + k})
    elif tasks:
        labels = [1]
    return {
        "cut_km": cut, "method": "average-linkage agglomerative (scipy)",
        "points": [
            {"index": i, "id": t.id, "x_km": round(float(pts[i][0]), 2), "y_km": round(float(pts[i][1]), 2),
             "lat": pos[i][0], "lon": pos[i][1], "department": t.department.value,
             "zone": t.zone.ref, "label": t.label, "cluster": labels[i]}
            for i, t in enumerate(tasks)
        ],
        "merges": merges,
    }
