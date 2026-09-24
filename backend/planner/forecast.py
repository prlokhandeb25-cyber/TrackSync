"""Predictive blocks in the live plan: act on warnings early, without over-planning.

<!-- serves: J1, J5 -->

A condition-monitoring feed (inspection drones, track-recording cars, telemetry) would flag assets that
are likely to fail. Each warning carries a risk. Turning every warning into a block would be its own
failure: the blocks pile up, and if they have to be forced into the timetable the trains pay for them.
So the rule here is a guard against over-prediction, not just a forecast:

  ACT     only on warnings whose risk clears a threshold;
  NATURAL only into gaps that already exist between trains (no train is held, retimed or rerouted for
          a block that may not have been needed);
  ONE     block per section per day: the crew checks every flagged asset on the section in one visit;
  LEFT    a warning that cannot be placed that way stays on the watch list, and if it does fail it is
          an ordinary emergency (which may then use the emergency levers, as before).

`policy_sweep` measures what each choice costs, on the same warnings, in trains delayed and blocks
added, so the threshold is chosen from a measurement rather than by taste.

WHAT IS AND IS NOT REAL: the warnings are SIMULATED. There is no video or sensor data here, so risk
scores and which assets really fail are drawn from a seeded model (ASSUMPTIONS.md A-048). What is real
is everything after the warning: the gap finder, the schedulers, the emergency levers and the timetable.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from backend.config import load_config
from backend.data.synth_tasks import _candidate_zones
from backend.domain.models import WorkZoneKind
from backend.domain.task import TASK_TYPES_BY_CODE, Task, TaskCategory, WorkZone
from backend.planner.live_sim import LiveSimState, alns_lite_insert
from backend.planner.sudden import place_sudden

FAULT_TYPES = ["SNT_TRACK_CIRCUIT", "SNT_AXLE_COUNTER", "PWI_JOINT", "PWI_GAUGE", "OWD_DROPPER", "OWD_INSULATOR"]
CUE = {   # what the monitoring feed says it saw, in plain words
    "SNT_TRACK_CIRCUIT": "track circuit readings drifting", "SNT_AXLE_COUNTER": "axle counter dropouts rising",
    "PWI_JOINT": "rail joint wear on the camera pass", "PWI_GAUGE": "gauge creeping out of tolerance",
    "OWD_DROPPER": "loose dropper seen on the overhead wire", "OWD_INSULATOR": "insulator flashover marks",
}
PEAK_HOURS = (7, 8, 9, 10, 17, 18, 19, 20)
DAY_S = 86400


@dataclass
class Warn:
    id: str
    tt: object
    zone: WorkZone
    risk: float                # the feed's probability that this asset fails within its window
    fail_s: int                # when it would fail, if it does
    dur: int
    lead_d: float
    fails: bool                # hidden truth used only to score decisions, never shown as a fact

    @property
    def warn_s(self) -> int:
        return max(0, self.fail_s - int(self.lead_d * DAY_S))


def _cfg() -> dict:
    c = load_config().get_path("predictive", {}) or {}
    return {"threshold": float(c.get("act_threshold", 0.5)), "n": int(c.get("warnings", 40)),
            "per_section_day": int(c.get("max_blocks_per_section_day", 1)),
            "max_per_day": int(c.get("max_blocks_per_day", 6))}


def watchlist(net, n: int | None = None, seed: int | None = None) -> list[Warn]:
    """The simulated feed: n warnings over the week, strong signals and weak ones mixed."""
    c = _cfg()
    n = c["n"] if n is None else n
    rng = random.Random((int(load_config()["seed"]) if seed is None else seed) + 4242)
    out: list[Warn] = []
    i = 0
    while len(out) < n and i < n * 6:
        i += 1
        tt = TASK_TYPES_BY_CODE[rng.choice(FAULT_TYPES)]
        zones = [z for z in _candidate_zones(net, tt) if z.kind is WorkZoneKind.SECTION]
        if not zones:
            continue
        strong = rng.random() < 0.4
        risk = rng.uniform(0.6, 0.95) if strong else rng.uniform(0.08, 0.5)
        out.append(Warn(id=f"PRD-{len(out) + 1:03d}", tt=tt, zone=rng.choice(zones), risk=round(risk, 2),
                        fail_s=int(rng.uniform(1.2, 6.5) * DAY_S),
                        dur=rng.randint(tt.min_duration_min, min(tt.max_duration_min, 90)),
                        lead_d=rng.uniform(2.0, 8.0), fails=rng.random() < risk))
    out.sort(key=lambda w: w.warn_s)
    return out


def _proactive_task(w: Warn) -> Task:
    tt = w.tt
    due = max(w.fail_s - 6 * 3600, w.warn_s + 12 * 3600)
    return Task(id=w.id, task_type=tt.code, department=tt.department, zone=WorkZone(kind=WorkZoneKind.SECTION, ref=w.zone.ref),
                duration_min=w.dur, priority=3, category=TaskCategory.DEMAND,
                requires_power_block=tt.requires_power_block, requires_traffic_block=tt.requires_traffic_block,
                released_s=w.warn_s, due_by_s=due, source="PRED",
                description=f"Early warning: {CUE.get(tt.code, tt.label)}")


def _emergency_task(w: Warn) -> Task:
    tt = w.tt
    return Task(id=f"F-{w.id[4:]}", task_type=tt.code, department=tt.department,
                zone=WorkZone(kind=WorkZoneKind.SECTION, ref=w.zone.ref), duration_min=w.dur, priority=1,
                category=TaskCategory.DEMAND, requires_power_block=tt.requires_power_block,
                requires_traffic_block=tt.requires_traffic_block, released_s=w.fail_s,
                due_by_s=w.fail_s + 2 * 3600, source="PRED")


@dataclass
class Policy:
    name: str
    threshold: float
    allow_create: bool = False


def run_policy(net, index, committed, creator, pax, warns: list[Warn], pol: Policy,
               with_rows: bool = False, state: LiveSimState | None = None, play_failures: bool = True) -> dict:
    """Play the warnings and their failures through one policy. Everything runs on copies of `committed`.

    Phase 1 places the proactive blocks, strongest warning first, under two guards: one block per section
    per day, and a cap on proactive blocks in any one day (crew capacity). Phase 2 then plays the failures
    in time order; any the blocks did not get ahead of become emergencies. Proactive blocks are all booked
    before the failures are played, which can only make an emergency harder to place, never easier."""
    cfg = _cfg()
    cap_sec, cap_day = cfg["per_section_day"], cfg["max_per_day"]
    state = LiveSimState() if state is None else state       # the live plan passes its own, so blocks persist
    rows: list[dict] = []
    booked: dict[tuple[str, int], tuple[str, int]] = {}   # (section, day) -> (block id, its end) covering it
    per_day: dict[int, int] = {}
    prevented: dict[str, bool] = {}
    decision: dict[str, dict] = {}
    by_id = {w.id: w for w in warns}

    for w in warns:
        decision[w.id] = {
            "id": w.id, "section": w.zone.ref, "type": w.tt.code, "label": w.tt.label, "cue": CUE.get(w.tt.code, ""),
            "department": w.tt.department.value, "risk": w.risk, "warn_s": w.warn_s, "fail_s": w.fail_s,
            "decision": "watch", "why": f"risk {int(w.risk * 100)}% is under the {int(pol.threshold * 100)}% action threshold",
            "start_s": None, "end_s": None, "track": None, "method": None, "train_min": 0.0, "pax_delay": 0}

    for w in sorted((x for x in warns if x.risk >= pol.threshold), key=lambda x: -x.risk):
        d = decision[w.id]
        pl = alns_lite_insert(net, _proactive_task(w), index, committed, state,
                              creator=creator if pol.allow_create else None, at_s=w.warn_s, pax=pax)
        if not (pl.placed and pl.start_s is not None):
            d.update(decision="no gap", why="no existing gap fits before it is due, so it stays on the watch list"
                     if not pol.allow_create else "no gap fits, even after changing trains")
            continue
        day = pl.start_s // DAY_S
        key = (w.zone.ref, day)
        if key in booked and cap_sec > 0:
            state.placed = [p for p in state.placed if p.task.id != w.id]        # one visit already covers it
            other, other_end = booked[key]
            d.update(decision="covered", why=f"block {other} on {w.zone.ref} that day already covers it")
            prevented[w.id] = w.fails and other_end <= w.fail_s
            continue
        if per_day.get(day, 0) >= cap_day:
            state.placed = [p for p in state.placed if p.task.id != w.id]
            d.update(decision="budget", why=f"the day already has {cap_day} proactive blocks; stronger warnings took them")
            continue
        booked[key] = (w.id, pl.end_s)
        per_day[day] = per_day.get(day, 0) + 1
        cr = pl.created
        d.update(decision="planned", why="planned in a gap made by changing trains" if cr else "planned in a gap that already exists",
                 start_s=pl.start_s, end_s=pl.end_s, track=pl.window.track if pl.window else None,
                 method="created" if cr else "gap", train_min=float(cr.delay_min) if cr else 0.0,
                 pax_delay=int(cr.pax_delay) if cr else 0, reach=int((pl.exposure or {}).get("passengers", 0)),
                 mates=list(pl.integrated_with), zone_ref=pl.window.zone_ref if pl.window else w.zone.ref)
        prevented[w.id] = w.fails and pl.end_s <= w.fail_s

    for w in sorted((x for x in warns if x.fails and play_failures), key=lambda x: x.fail_s):
        if prevented.get(w.id):
            continue
        res = place_sudden(net, _emergency_task(w), index, committed, state, creator, w.fail_s, pax, lambda b: False)
        pl = res.placement
        cr = pl.created if pl is not None else None
        rows.append({"id": w.id, "placed": pl is not None and pl.placed, "method": res.method,
                     "start_s": pl.start_s if pl else None, "train_min": float(cr.delay_min) if cr else 0.0,
                     "pax_delay": int(cr.pax_delay) if cr else 0})

    ds = list(decision.values())
    planned = [d for d in ds if d["decision"] == "planned"]
    fails = [w for w in warns if w.fails]
    hit = sum(1 for w in fails if prevented.get(w.id))
    pro_created = sum(1 for d in planned if d["method"] == "created")
    em_created = sum(1 for r in rows if r["method"] == "created")
    train_min = sum(d["train_min"] for d in planned) + sum(r["train_min"] for r in rows)
    pax_min = sum(d["pax_delay"] for d in planned) + sum(r["pax_delay"] for r in rows)
    false_blocks = sum(1 for d in planned if not by_id[d["id"]].fails)
    out = {
        "policy": pol.name, "threshold": pol.threshold, "allow_create": pol.allow_create,
        "warnings": len(warns), "failures": len(fails), "blocks_added": len(planned),
        "false_alarm_blocks": false_blocks, "prevented": hit, "emergencies": len(rows),
        "gaps_made_proactive": pro_created, "gaps_made_emergency": em_created,
        "train_min": round(train_min, 1), "pax_hours": round(pax_min / 60),
        "block_hours": round(sum((d["end_s"] - d["start_s"]) for d in planned) / 3600, 1),
        "wasted_hours": round(sum((d["end_s"] - d["start_s"]) for d in planned if not by_id[d["id"]].fails) / 3600, 1),
        "peak_blocks_a_day": max(per_day.values(), default=0),
        "in_peak": sum(1 for d in planned if ((d["start_s"] % DAY_S) // 3600) in PEAK_HOURS),
        "recall": round(hit / max(1, len(fails)), 2),
        "precision": round((len(planned) - false_blocks) / max(1, len(planned)), 2),
    }
    if with_rows:
        out["rows"] = ds
    return out


POLICIES = [Policy("React only (no forecast)", 2.0, False),
            Policy("Plan every warning, changing trains if needed", 0.0, True),
            Policy("Plan every warning, existing gaps only", 0.0, False),
            Policy("Act at risk 30% and above, existing gaps", 0.3, False),
            Policy("Act at risk 50% and above, existing gaps", 0.5, False),
            Policy("Act at risk 70% and above, existing gaps", 0.7, False)]


def policy_sweep(net, index, committed, creator, pax, scales=(1, 3)) -> dict:
    """The same warnings scored under each way of acting on them (and under not acting at all), at the
    normal feed size and at `scales` times as many warnings, since over-prediction only bites when there are many."""
    base = _cfg()["n"]
    out = []
    for k in scales:
        warns = watchlist(net, base * k)
        table = [run_policy(net, index, committed, creator, pax, warns, p) for p in POLICIES]
        out.append({"scale": k, "warnings": len(warns), "failures": sum(1 for w in warns if w.fails), "table": table})
    return {"scales": out, "in_use_threshold": _cfg()["threshold"],
            "how": "The same simulated warnings played through six policies on the real timetable and schedulers, at the "
                   "normal feed size and at three times as many. Failures a policy did not get ahead of are handled as "
                   "emergencies. Scored by trains delayed, gaps made by changing trains, blocks added and blocks that turned out unnecessary.",
            "caveat": "The warnings and which assets really fail are simulated (A-048): there is no sensor or video feed here. "
                      "The costs after a warning are the real schedulers' costs on the real timetable."}
