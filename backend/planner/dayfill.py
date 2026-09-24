"""Daily routine maintenance in the rest of the day: 04:00 onward.

<!-- serves: J1, J5 -->

The weekly solver puts most planned jobs in the quiet 01:00-04:00 gaps, because the passenger term prices work
near busy services. That is right for the planned jobs, but a real network also carries small routine jobs every
day (lamp and joint checks, short attention jobs) that cannot all wait for the small hours. This places a standing
list of them into gaps between trains from 04:00 to the end of each day, quietest slot first, with the same gap
finder, rules and passenger model as everything else, and only into gaps that already exist.

The daily list itself is ASSUMED (how many jobs a day, how long, which kinds: A-055); the placement is real.
Sudden tasks are not part of this list: they are booked live wherever a gap is, at any hour their deadline needs.
"""

from __future__ import annotations

import random

from backend.config import load_config
from backend.data.synth_tasks import generate_demand_task
from backend.domain.task import Task
from backend.planner.live_sim import LiveSimState, alns_lite_insert, order_max_to_min

DAY_S = 86400


def _cfg() -> dict:
    c = load_config().get_path("daily", {}) or {}
    return {"per_day": int(c.get("jobs_per_day", 4)), "max_min": int(c.get("max_job_min", 45)),
            "from_h": int(c.get("from_hour", 4)), "days": int(c.get("days", 7))}


def daily_jobs(net, day: int, seed: int) -> list[Task]:
    c = _cfg()
    rng = random.Random(seed * 131 + day)
    out: list[Task] = []
    while len(out) < c["per_day"]:
        t = generate_demand_task(net, rng, day * DAY_S + c["from_h"] * 3600, tid=f"DLY-{day}-{len(out) + 1}")
        if t.duration_min > c["max_min"]:
            continue
        t.priority = rng.choice([4, 5])
        t.source = "DAILY"
        t.due_by_s = (day + 1) * DAY_S                      # done the same day
        out.append(t)
    return out


def fill_days(net, index, committed: list[Task], pax, state: LiveSimState, seed: int) -> dict:
    """Place each day's routine jobs from 04:00 on; return what went where and what did not fit."""
    c = _cfg()
    placed = unplaced = 0
    hours: list[int] = []
    for day in range(c["days"]):
        nb = day * DAY_S + c["from_h"] * 3600
        for t in order_max_to_min(daily_jobs(net, day, seed)):
            p = alns_lite_insert(net, t, index, committed, state, creator=None, at_s=nb, pax=pax, allow_destroy=False,
                                 not_before_s=nb)
            if p.placed:
                placed += 1
                hours.append((p.start_s % DAY_S) // 3600)
            else:
                unplaced += 1
    return {"placed": placed, "unplaced": unplaced, "from_hour": c["from_h"], "per_day": c["per_day"], "hours": hours}
