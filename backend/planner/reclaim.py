"""Time given back: when a block finishes early, the rest of it goes to small jobs already waiting.

<!-- serves: J1, J5 -->

A 10-hour block that is finished in 8 hours has 2 hours of protected, powered-off, gang-on-site track left. The
protection is already up, so a small job waiting on the same section can start straight away: no new block, no
second set-up and hand-back. This module measures what that is worth over a week, and answers the live question
"this block just finished early - what gets pulled in?".

How it works (`reclaim_week`):
  1. every block in the weekly plan is given the time its crew REALLY takes: a draw around the crews' behaviour
     (`crew_profile.true_mean`, spread 15%; crews tend to run a little over, so this is the cautious case), and again
     with crews who take the planned time on average (`neutral`), so both are reported;
  2. a block that finishes early frees `planned - actual` minutes on the same section;
  3. a standing backlog of small "as-and-when" jobs (<= `reclaim.max_job_min`, ASSUMED, A-053) is matched to the
     freed time: same section (or a station at its ends), department allotted, priority first, longest first
     (Max-to-Min), only if it fits in what is left;
  4. each job pulled in avoids its own protected block, so its set-up and hand-back time is counted as saved.

Repeated over several random weeks so the answer is an average with its spread, not one lucky draw.
"""

from __future__ import annotations

import random
import statistics

from backend.planner.aging import effective_priority
from backend.config import load_config
from backend.data.synth_tasks import generate_demand_task
from backend.domain.compatibility import check_allotment
from backend.domain.models import WorkZoneKind
from backend.planner.crew_profile import _draw, true_mean

DAY_S = 86400


def _cfg() -> dict:
    c = load_config().get_path("reclaim", {}) or {}
    return {"backlog": int(c.get("backlog_jobs", 240)), "max_job_min": int(c.get("max_job_min", 60)),
            "seeds": int(c.get("seeds", 12)), "grid": int(load_config()["gaps"].get("block_grid_min", 5))}


def make_backlog(net, seed: int, n: int, max_min: int):
    rng = random.Random(seed)
    out = []
    while len(out) < n:
        t = generate_demand_task(net, rng, 0, tid=f"BK-{seed}-{len(out):04d}")
        t.priority = rng.choices([2, 3, 4, 5], weights=[10, 30, 30, 30], k=1)[0]     # routine work, mostly low
        t.source = "BACKLOG"
        if t.duration_min <= max_min and check_allotment(net, t) is None:
            out.append(t)
    return out


def _endpoints(net, zone_ref: str) -> set[str]:
    sec = net.sections.get(zone_ref)
    return {zone_ref, sec.from_station, sec.to_station} if sec else {zone_ref}


def fill(net, host_zone: str, freed_min: int, backlog: list, used: set[str], now_s: int = 0) -> list:
    """Jobs to pull into `freed_min` minutes on `host_zone`: priority first, then longest, only while they fit."""
    ends = _endpoints(net, host_zone)
    cand = sorted((t for t in backlog if t.id not in used and t.zone.ref in ends and t.duration_min <= freed_min),
                  key=lambda t: (effective_priority(t, now_s), -t.duration_min))
    take, left = [], freed_min
    for t in cand:
        if t.duration_min <= left:
            take.append(t)
            left -= t.duration_min
    return take


def reclaim_week(world, plan, seed: int = 0, neutral: bool = False) -> dict:
    net = world.net
    c = _cfg()
    g = load_config()["gaps"]
    per_job_saved = int(g["block_setup_min"]) + int(g["block_release_min"])
    tasks = {t.id: t for t in world.tasks}
    runs = []
    example: list[dict] = []
    for k in range(c["seeds"]):
        rng = random.Random(seed * 1000 + k)
        backlog = make_backlog(net, seed * 1000 + 500 + k, c["backlog"], c["max_job_min"])
        used: set[str] = set()
        early = freed_total = pulled = pulled_min = 0
        rows = []
        for a in plan.assignments:
            t = tasks.get(a.task_id)
            if t is None:
                continue
            mult = _draw(1.0 if neutral else true_mean(t.department.value, a.start_s // DAY_S), rng)
            planned = (a.end_s - a.start_s) // 60
            freed = int(planned * (1 - mult)) // c["grid"] * c["grid"] if mult < 1 else 0
            if freed < 10:
                continue
            early += 1
            freed_total += freed
            take = fill(net, a.zone_ref, freed, backlog, used)
            for j in take:
                used.add(j.id)
            pulled += len(take)
            pulled_min += sum(j.duration_min for j in take)
            rows.append({"task_id": a.task_id, "label": t.label, "department": t.department.value, "zone_ref": a.zone_ref,
                         "planned_min": planned, "actual_min": planned - freed, "freed_min": freed,
                         "start_s": a.start_s, "end_s": a.end_s, "freed_from_s": a.start_s + (planned - freed) * 60,
                         "pulled": [{"id": j.id, "label": j.label, "department": j.department.value, "duration_min": j.duration_min,
                                     "priority": j.priority} for j in take]})
        runs.append({"blocks": len(plan.assignments), "early": early, "freed_h": freed_total / 60, "pulled": pulled,
                     "pulled_h": pulled_min / 60, "saved_setup_h": pulled * per_job_saved / 60})
        if k == 0:
            example = sorted(rows, key=lambda r: -len(r["pulled"]) * 1000 - r["freed_min"])[:8]

    def mean(key):
        return round(statistics.fmean(r[key] for r in runs), 1)

    def sd(key):
        return round(statistics.pstdev(r[key] for r in runs), 1)

    return {"weeks": len(runs), "blocks": runs[0]["blocks"], "early_blocks": mean("early"), "freed_h": mean("freed_h"),
            "pulled": mean("pulled"), "pulled_sd": sd("pulled"), "pulled_h": mean("pulled_h"),
            "saved_setup_h": mean("saved_setup_h"), "backlog": c["backlog"], "max_job_min": c["max_job_min"],
            "used_share": round(mean("pulled_h") / max(0.1, mean("freed_h")), 2), "examples": example,
            "how": (f"Each block in the weekly plan is given the time its crew really takes (crews vary; some overrun, some finish early). "
                    f"A block that finishes early frees the rest of its protected time; small waiting jobs on the same section fill it, "
                    f"priority first, longest first. Averaged over {len(runs)} random weeks."),
            "neutral": None if neutral else reclaim_week(world, plan, seed, neutral=True),
            "caveat": (f"The waiting list ({c['backlog']} small jobs of up to {c['max_job_min']} min spread over the network) and the crews' "
                       "timing are assumed (A-053, A-045); the matching and the rules are real.")}
