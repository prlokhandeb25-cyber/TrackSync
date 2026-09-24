"""Machines and travel as real constraints on the plan.

<!-- serves: J1, J5 -->

The live plan treats gangs as interchangeable and ignores machines. In practice a tamping machine or a tower
wagon is in ONE place at a time, and moving it between sections takes time. This adds that to the exact solver as
extra constraints (through the `extra` hook of `cpsat.build_and_solve`, which is off unless asked for):

  - each kind of machine has a small pool (`resources.machines`, ASSUMED, A-057);
  - every job that needs a machine is given one of the pool's machines while it runs;
  - two jobs on the SAME machine must be separated by the machine's travel time between their sections
    (a fixed shunt plus distance at a travelling speed).

`machine_conflicts` checks ANY plan against the same rules, so the live plan can be scored against them and the
constrained plan can be shown to have none. Nothing in the live plan changes unless a coordinator applies a
constrained proposal (see `approvals.py`).
"""

from __future__ import annotations

import math

from backend.config import load_config
from backend.domain.task import Task
from backend.planner.clustering import _position, _to_km

MACHINE_OF = {"PWI_TAMPING": "Tamping machine", "PWI_BALLAST": "Ballast cleaning machine",
              "OWD_TENSION": "Tower wagon", "OWD_INSULATOR": "Tower wagon", "OWD_DROPPER": "Tower wagon", "OWD_MAST": "Tower wagon"}


def _cfg(pools: dict | None = None) -> dict:
    c = load_config().get_path("resources", {}) or {}
    m = c.get("machines", {}) or {}
    return {"pools": {"Tamping machine": int(m.get("tamping_machine", 1)), "Ballast cleaning machine": int(m.get("ballast_cleaning_machine", 1)),
                      "Tower wagon": int(m.get("tower_wagon", 2))},
            "speed_kmph": float(c.get("machine_speed_kmph", 25)), "shunt_min": int(c.get("machine_shunt_min", 15))} | (
        {"pools": {**{"Tamping machine": 1, "Ballast cleaning machine": 1, "Tower wagon": 2}, **pools}} if pools else {})


def travel_s(net, za: str, zb: str, speed: float, shunt_min: int, kinds=None) -> int:
    """Seconds to move a machine from one job's place to the other's (0 if the same place)."""
    if za == zb:
        return 0
    from backend.domain.task import WorkZone
    from backend.domain.models import WorkZoneKind

    def pos(ref):
        kind = WorkZoneKind.SECTION if ref in net.sections else WorkZoneKind.STATION_NODE
        t = Task.model_construct(zone=WorkZone(kind=kind, ref=ref))
        return _to_km(*_position(net, t))
    (x1, y1), (x2, y2) = pos(za), pos(zb)
    km = math.hypot(x1 - x2, y1 - y2)
    return int((shunt_min + km / speed * 60.0) * 60)


def make_extra(net, pools: dict | None = None):
    cfg = _cfg(pools)

    def extra(model, live, interval, start, end, scheduled):
        for mname, k in cfg["pools"].items():
            ts = [t for t in live if MACHINE_OF.get(t.task_type) == mname]
            if len(ts) < 2:
                continue
            use = {}
            for t in ts:
                lits = [model.NewBoolVar(f"mach_{mname}_{t.id}_{m}") for m in range(k)]
                for m, b in enumerate(lits):
                    use[(t.id, m)] = b
                model.Add(sum(lits) == 1).OnlyEnforceIf(scheduled[t.id])
                model.Add(sum(lits) == 0).OnlyEnforceIf(scheduled[t.id].Not())
            for i, a in enumerate(ts):
                for b in ts[i + 1:]:
                    tab = travel_s(net, a.zone.ref, b.zone.ref, cfg["speed_kmph"], cfg["shunt_min"])
                    order = model.NewBoolVar(f"mord_{a.id}_{b.id}")
                    for m in range(k):
                        same = [use[(a.id, m)], use[(b.id, m)]]
                        model.Add(end[a.id] + tab <= start[b.id]).OnlyEnforceIf(same + [order])
                        model.Add(end[b.id] + tab <= start[a.id]).OnlyEnforceIf(same + [order.Not()])
    return extra


def machine_conflicts(net, tasks: list[Task], assignments, pools: dict | None = None) -> list[dict]:
    """Jobs a plan cannot serve with the machine pools: each job, in time order, takes the first machine that is free
    (and has had time to travel there); a job with none free is a conflict."""
    cfg = _cfg(pools)
    by = {t.id: t for t in tasks}
    out = []
    for mname, k in cfg["pools"].items():
        jobs = sorted(((a.start_s, a.end_s, by[a.task_id]) for a in assignments
                       if a.task_id in by and MACHINE_OF.get(by[a.task_id].task_type) == mname), key=lambda x: x[0])
        free = [(-10**9, None)] * k           # (time free, where it is)
        for s, e, t in jobs:
            best = None
            for m, (tf, where) in enumerate(free):
                need = 0 if where is None else travel_s(net, where, t.zone.ref, cfg["speed_kmph"], cfg["shunt_min"])
                if tf + need <= s:
                    best = m
                    break
            if best is None:
                m = min(range(k), key=lambda i: free[i][0])
                tf, where = free[m]
                need = 0 if where is None else travel_s(net, where, t.zone.ref, cfg["speed_kmph"], cfg["shunt_min"])
                out.append({"machine": mname, "task_id": t.id, "label": t.label, "zone": t.zone.ref,
                            "start_s": s, "short_by_min": round((tf + need - s) / 60),
                            "kind": "double-booked" if tf > s else "no time to travel there"})
                free[best if best is not None else m] = (e, t.zone.ref)
            else:
                free[best] = (e, t.zone.ref)
    return out


def machine_jobs(tasks: list[Task]) -> int:
    return sum(1 for t in tasks if MACHINE_OF.get(t.task_type))
