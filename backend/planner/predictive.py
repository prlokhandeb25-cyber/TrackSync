"""Predictive blocks: early warning against emergency response.

<!-- serves: J1, J5 -->

Today most defect work is found when something fails. If a condition-monitoring system (inspection
drones, track-recording cars, axle-counter and OHE telemetry) can warn days ahead, the job can be
planned as an ordinary block in a quiet gap instead of arriving as an emergency at 08:00. This measures
what that is worth, on the real timetable, with the real schedulers:

  REACTIVE     a failure at time T raises a CRITICAL job (due in 2 h) placed by the sudden-task scheduler:
               existing gap if one is free, else a created gap or an emergency block.
  PREDICTIVE   a warning `lead` days before T (with probability `p_detect`) raises an ordinary job due
               six hours before T, placed by the routine scheduler into the quietest gap that fits;
               failures nobody warned about are still handled as emergencies.

Both see the same failures, on the same schedule, and are scored on emergencies, train-minutes lost,
passengers within reach, work in the peaks, and failures actually prevented.

WHAT IS AND IS NOT REAL: the detection itself is not built. There is no video or sensor data here, so
"detected with probability p a few days ahead" is an ASSUMPTION, stated in the results and varied in a
sensitivity table. What is measured is the value of the warning if it exists: what emergency response
costs on this timetable, against planning the same work early. (ASSUMPTIONS.md A-047.)
"""

from __future__ import annotations

import random

from backend.config import load_config
from backend.data.synth_tasks import _candidate_zones
from backend.domain.models import WorkZoneKind
from backend.domain.task import TASK_TYPES_BY_CODE, Task, TaskCategory, WorkZone
from backend.planner.live_sim import LiveSimState, alns_lite_insert
from backend.planner.sudden import place_sudden

FAULT_TYPES = ["SNT_TRACK_CIRCUIT", "SNT_AXLE_COUNTER", "PWI_JOINT", "PWI_GAUGE", "OWD_DROPPER", "OWD_INSULATOR"]
PEAK_HOURS = (7, 8, 9, 10, 17, 18, 19, 20)
DAY_S = 86400


def _events(net, n: int, seed: int) -> list[dict]:
    rng = random.Random(seed + 555)
    out = []
    for i in range(n):
        tt = TASK_TYPES_BY_CODE[rng.choice(FAULT_TYPES)]
        zones = [z for z in _candidate_zones(net, tt) if z.kind is WorkZoneKind.SECTION]
        if not zones:
            continue
        zone = rng.choice(zones)
        out.append({"i": i, "tt": tt, "zone": zone, "fail_s": int(rng.uniform(1.0, 6.5) * DAY_S),
                    "dur": rng.randint(tt.min_duration_min, min(tt.max_duration_min, 90)),
                    "lead_d": rng.uniform(2.0, 10.0), "detect_u": rng.random()})
    return out


def _task(ev: dict, tid: str, priority: int, released: int, due: int) -> Task:
    tt = ev["tt"]
    return Task(id=tid, task_type=tt.code, department=tt.department, zone=WorkZone(kind=WorkZoneKind.SECTION, ref=ev["zone"].ref),
                duration_min=ev["dur"], priority=priority, category=TaskCategory.DEMAND,
                requires_power_block=tt.requires_power_block, requires_traffic_block=tt.requires_traffic_block,
                released_s=released, due_by_s=due, source="PRED")


def run_strategy(net, index, committed, creator, pax, events: list[dict], predictive: bool, p_detect: float) -> dict:
    state = LiveSimState()
    rows = []
    # everything that happens, in time order: a warning (predictive) or a failure
    todo = []
    for ev in events:
        detected = predictive and ev["detect_u"] < p_detect
        if detected:
            todo.append((max(0, ev["fail_s"] - int(ev["lead_d"] * DAY_S)), "warn", ev))
        else:
            todo.append((ev["fail_s"], "fail", ev))
    todo.sort(key=lambda x: x[0])

    for t_at, kind, ev in todo:
        if kind == "fail":
            task = _task(ev, f"F-{ev['i']:03d}", 1, t_at, t_at + 2 * 3600)
            res = place_sudden(net, task, index, committed, state, creator, t_at, pax, lambda b: False)
            pl = res.placement
            created = pl.created if pl is not None else None
            rows.append({"kind": "emergency", "placed": pl is not None and pl.placed, "method": res.method,
                         "start_s": pl.start_s if pl else None, "end_s": pl.end_s if pl else None,
                         "train_min": created.delay_min if created else 0.0, "pax_delay": created.pax_delay if created else 0,
                         "pax_reach": (pl.exposure or {}).get("passengers", 0) if pl else 0,
                         "before_failure": False, "fail_s": ev["fail_s"]})
        else:
            due = ev["fail_s"] - 6 * 3600
            task = _task(ev, f"P-{ev['i']:03d}", 3, t_at, max(due, t_at + 12 * 3600))
            pl = alns_lite_insert(net, task, index, committed, state, creator=creator, at_s=t_at, pax=pax)
            created = pl.created if pl is not None else None
            rows.append({"kind": "planned", "placed": pl.placed, "method": "created" if created else "gap",
                         "start_s": pl.start_s, "end_s": pl.end_s,
                         "train_min": created.delay_min if created else 0.0, "pax_delay": created.pax_delay if created else 0,
                         "pax_reach": (pl.exposure or {}).get("passengers", 0),
                         "before_failure": bool(pl.placed and pl.end_s is not None and pl.end_s <= ev["fail_s"]),
                         "fail_s": ev["fail_s"]})
    n = len(rows)
    placed = [r for r in rows if r["placed"] and r["start_s"] is not None]
    peak = sum(1 for r in placed if ((r["start_s"] % DAY_S) // 3600) in PEAK_HOURS)
    return {
        "events": n,
        "emergencies": sum(1 for r in rows if r["kind"] == "emergency"),
        "prevented": sum(1 for r in rows if r["kind"] == "planned" and r["before_failure"]),
        "train_min": round(sum(r["train_min"] for r in rows), 1),
        "pax_delay_min": int(sum(r["pax_delay"] for r in rows)),
        "pax_reach": int(sum(r["pax_reach"] for r in placed)),
        "peak_jobs": peak, "placed": len(placed),
        "late": sum(1 for r in rows if r["kind"] == "emergency" and r["method"] in ("late", "none")),
    }


def predictive_experiment(net, index, committed, creator, pax, n_events: int = 40, seed: int = 0,
                          p_detect_grid=(0.5, 0.8, 0.95)) -> dict:
    events = _events(net, n_events, seed)
    reactive = run_strategy(net, index, committed, creator, pax, events, False, 0.0)
    table = []
    for p in p_detect_grid:
        table.append({"p_detect": p, **run_strategy(net, index, committed, creator, pax, events, True, p)})
    return {"failures": len(events), "reactive": reactive, "predictive": table,
            "lead_days": "2 to 10 (assumed)", "assumed_p_detect": load_config().get_path("predictive.p_detect", 0.8),
            "how": "The same failures handled two ways on the real timetable: as emergencies when they happen, "
                   "or, when warned days ahead, as ordinary blocks placed into the quietest gap that fits.",
            "caveat": "Detection is assumed, not built: no video or sensor data exists here (A-047). The table varies the assumed "
                      "detection rate; the costs on the left are the real schedulers' costs on the real timetable."}
