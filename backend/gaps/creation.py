"""Gap creation: turning near-miss gaps into windows long enough to work in.

<!-- serves: J1, J5 -->

The gap engine (engine.py) only finds gaps the timetable already contains, and it drops any gap
that would leave under 15 minutes of real working time once protection is set up and released.
A great many gaps miss that by a few minutes. This module asks whether a small, bounded change to
the trains can open one, using three levers taken from how Indian Railways actually gives blocks:

  RETIME       hold the train after the gap by a few minutes, and only as many trains behind it as
               headway forces, so the gap widens. Every hold and its cascade is counted.
  REROUTE      send a long-distance or freight train around the section by another path (the
               k-shortest-path search in backend/planner/rerouting.py, inside each class's delay
               limit). Suburban locals are never rerouted - they are never offered to this lever.
  SINGLE_LINE  run the section on ONE track of a local pair for the length of the job, so the other
               track is clear. Both directions then share one line: only one train may be in the
               section at a time, so the trains that used the closed track wait for their turn.

Nothing here edits the timetable. Each option is a described, priced proposal (which trains, how
many minutes) that the planner may take when it needs a window it cannot otherwise find; the
cheapest option that works is the one chosen.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.config import load_config
from backend.data.week import DAY_S
from backend.domain.pax import train_pax
from backend.domain.models import Section, SectionOccupancy, Train, TrainClass, WorkZoneKind
from backend.domain.network import Network
from backend.domain.task import Task
from backend.gaps.engine import CandidateWindow, GapType, min_raw_gap_min
from backend.planner.rerouting import reroute_candidates

RETIME, REROUTE, SINGLE_LINE, EMERGENCY = "RETIME", "REROUTE", "SINGLE_LINE", "EMERGENCY"

LEVER_LABEL = {
    RETIME: "hold a train a few minutes",
    REROUTE: "send a long-distance train another way",
    SINGLE_LINE: "run one track for both directions",
    EMERGENCY: "stop the trains behind the block until the work is done",
}


@dataclass
class CreationOption:
    lever: str
    section_id: str
    track: str
    day: int
    start_s: int                     # the created window (raw, buffers already excluded)
    end_s: int
    delay_min: float                 # train-minutes of delay this costs, summed over trains
    trains: list[dict] = field(default_factory=list)
    note: str = ""
    pax_delay: int = 0               # passenger-minutes of delay (held/diverted trains x their load)

    @property
    def impact_cost(self) -> float:
        """What the planner minimises: train-minutes plus passenger-minutes per thousand. Ranking by
        train-minutes alone would happily hold a packed peak local to spare an empty freight."""
        return self.delay_min + self.pax_delay / 1000.0

    @property
    def raw_min(self) -> int:
        return (self.end_s - self.start_s) // 60

    def to_window(self, window_id: str, net: Network) -> CandidateWindow:
        sec = net.sections[self.section_id]
        return CandidateWindow(
            id=window_id, section_id=self.section_id, zone_ref=self.section_id,
            zone_kind=WorkZoneKind.SECTION, track=self.track,
            direction="UP" if self.track.startswith("UP") else "DN",
            start_s=self.start_s, end_s=self.end_s, gap_type=GapType.MICRO_GAP,
            station_tier=sec.tier, created_by=self.lever, delay_cost_min=self.delay_min,
            created_note=self.note,
        )

    def to_dict(self) -> dict:
        return {
            "lever": self.lever, "lever_label": LEVER_LABEL[self.lever],
            "section_id": self.section_id, "track": self.track, "day": self.day,
            "start_s": self.start_s, "end_s": self.end_s, "raw_min": self.raw_min,
            "delay_min": round(self.delay_min, 1), "trains": self.trains, "note": self.note,
            "pax_delay": self.pax_delay,
        }


@dataclass
class _Move:
    enter: int
    exit: int
    train_id: str
    cls: TrainClass


def _cfg(stretch: float = 1.0) -> dict:
    """Creation limits. `stretch` > 1 widens the hold and delay caps for emergency work: a control
    office will disrupt more trains to clear a critical fault than to fit a routine job (A-042)."""
    c = load_config()
    g = c["gap_creation"]
    return {
        "buf": int(c["gaps"]["headway_buffer_s"]),
        # same trailing margin the gap engine uses, so a created window is no more generous than a real one
        "look": max(int(c["gaps"]["headway_buffer_s"]), int(c["gaps"].get("lookout_min", 5)) * 60),
        "hw": int(c["validation"]["min_headway_s"]),
        "hold_cap": int(g["max_hold_min"] * stretch) * 60,
        "total_cap": float(g["max_total_delay_min"]) * stretch,
        "sl_hold_cap": int(g["single_line_max_hold_min"] * stretch) * 60,
        "sl_total_cap": float(g["single_line_max_total_min"]) * stretch,
        "max_reroutes": int(g["max_reroutes_per_gap"] * stretch),
    }


def raw_needed_min(task: Task) -> int:
    """Raw gap length a task needs: its work plus set-up, release and (for OHE) isolation."""
    g = load_config()["gaps"]
    need = task.duration_min + int(g["block_setup_min"]) + int(g["block_release_min"])
    if task.requires_power_block:
        need += 2 * int(g["power_block_extra_min"])
    return need


def sequences(section_occ: list[SectionOccupancy]) -> dict[tuple[str, int], list[_Move]]:
    """One section's train movements grouped by (track, day) and sorted by time."""
    out: dict[tuple[str, int], list[_Move]] = {}
    for o in section_occ:
        out.setdefault((o.track, o.enter_s // DAY_S), []).append(
            _Move(o.enter_s, o.exit_s, o.train_id, o.train_class))
    for v in out.values():
        v.sort(key=lambda m: m.enter)
    return out


# ------------------------------------------------------------------------------- reroute cache


class RerouteCache:
    """Whether (and at what cost) a long-distance train can avoid a section, computed once per
    origin/destination/class/section so repeated services on the same path share the search."""

    def __init__(self, net: Network, week_by_id: dict[str, Train]):
        self.net, self.week, self._memo = net, week_by_id, {}

    def delay_min(self, train_id: str, section_id: str) -> float | None:
        train = self.week.get(train_id)
        if train is None or not train.reroutable:
            return None  # locals, and anything unknown, are never rerouted
        key = (train.origin, train.destination, train.train_class.value, section_id)
        if key not in self._memo:
            paths = reroute_candidates(self.net, train, section_id, k=2)
            ok = [p for p in paths if p.within_limit]
            self._memo[key] = ok[0].added_delay_min if ok else None
        return self._memo[key]


# ----------------------------------------------------------------------------------- the levers


def _retime(seq: list[_Move], i: int, need_s: int, c: dict) -> tuple[int, int, dict[int, int]] | None:
    """Widen the gap after seq[i] to `need_s` by holding seq[i+1] and whatever headway forces."""
    if i + 1 >= len(seq):
        return None
    raw = seq[i + 1].enter - seq[i].exit - c["buf"] - c["look"]
    extra = need_s - raw
    if extra <= 0 or extra > c["hold_cap"]:
        return None
    holds = {i + 1: extra}
    for j in range(i + 1, len(seq) - 1):
        needed = seq[j].exit + holds[j] + c["hw"] - seq[j + 1].enter
        if needed <= 0:
            break
        if needed > c["hold_cap"]:
            return None
        holds[j + 1] = needed
    if sum(holds.values()) / 60.0 > c["total_cap"]:
        return None
    start = seq[i].exit + c["buf"]
    return start, seq[i + 1].enter + holds[i + 1] - c["look"], holds


def _retime_option(section: Section, track: str, day: int, seq: list[_Move], i: int,
                   need_s: int, c: dict) -> CreationOption | None:
    r = _retime(seq, i, need_s, c)
    if r is None:
        return None
    start, end, holds = r
    return CreationOption(
        lever=RETIME, section_id=section.id, track=track, day=day, start_s=start, end_s=end,
        delay_min=sum(holds.values()) / 60.0,
        pax_delay=int(sum(h / 60.0 * train_pax(seq[j].cls, seq[j].enter) for j, h in holds.items())),
        trains=[{"train_id": seq[j].train_id, "class": seq[j].cls.value,
                 "action": f"held {h / 60:.1f} min"} for j, h in holds.items()],
        note=f"Hold the next train {holds[i + 1] / 60:.1f} min"
             + (f" (and {len(holds) - 1} behind it)" if len(holds) > 1 else ""),
    )


def _reroute_options(section: Section, track: str, day: int, seq: list[_Move], need_s: int,
                     c: dict, rc: RerouteCache) -> list[CreationOption]:
    """Remove a run of long-distance/freight trains from the section and see if a gap opens."""
    out: list[CreationOption] = []
    n = len(seq)
    ok = [rc.delay_min(m.train_id, section.id) for m in seq]
    for a in range(n):
        if ok[a] is None:
            continue
        for b in range(a, min(n, a + c["max_reroutes"])):
            if ok[b] is None:
                break
            lo_exit = seq[a - 1].exit if a > 0 else None
            hi_enter = seq[b + 1].enter if b + 1 < n else None
            if lo_exit is None or hi_enter is None:
                continue
            start, end = lo_exit + c["buf"], hi_enter - c["look"]
            if end - start < need_s:
                continue
            # only worth creating if no existing gap in that span already fits the job
            span = seq[a - 1:b + 2]
            if any(y.enter - x.exit - c["buf"] - c["look"] >= need_s for x, y in zip(span, span[1:])):
                continue
            moved = seq[a:b + 1]
            out.append(CreationOption(
                lever=REROUTE, section_id=section.id, track=track, day=day,
                start_s=start, end_s=end, delay_min=sum(ok[a:b + 1]),  # type: ignore[arg-type]
                pax_delay=int(sum(ok[k] * train_pax(m.cls, m.enter)  # type: ignore[operator]
                                  for k, m in zip(range(a, b + 1), moved))),
                trains=[{"train_id": m.train_id, "class": m.cls.value,
                         "action": f"rerouted +{ok[k]:.1f} min"} for k, m in zip(range(a, b + 1), moved)],
                note=f"Divert {len(moved)} long-distance/freight train(s) around {section.id}",
            ))
            break
    return out


def _local_pair(section: Section, track: str) -> str | None:
    """The other track of this track's local pair, or None if it has no bidirectional partner."""
    tracks = section.tracks
    if any(t.endswith("_SLOW") for t in tracks):
        if not track.endswith("_SLOW"):
            return None
        other = ("DN" if track.startswith("UP") else "UP") + "_SLOW"
    else:
        other = "DN" if track == "UP" else "UP"
    return other if other in tracks and other != track else None


def _single_line_options(section: Section, track: str, day: int, by_track: dict, need_s: int,
                         c: dict, from_s: int) -> list[CreationOption]:
    other = _local_pair(section, track)
    if other is None:
        return []
    t_seq = by_track.get((track, day), [])
    o_seq = by_track.get((other, day), [])
    max_min = int(load_config()["rerouting"]["max_single_line_min"])
    if need_s / 60 > max_min:
        return []

    starts = sorted({day * DAY_S} | {m.exit + c["buf"] for m in t_seq if m.exit + c["buf"] >= from_s - need_s})
    out: list[CreationOption] = []
    for t0 in starts:
        t1 = t0 + need_s
        if t1 > (day + 1) * DAY_S:
            break
        moving = [m for m in t_seq if m.enter < t1 + c["buf"] and m.exit > t0 - c["buf"]]
        near = [m for m in o_seq if m.enter < t1 + 900 and m.exit > t0 - 900]
        merged = sorted(moving + near, key=lambda m: m.enter)
        # one train in the section at a time, one after another, none held past its limit
        holds: dict[str, int] = {}
        prev_exit = None
        ok = True
        for m in merged:
            run = m.exit - m.enter
            enter = m.enter if prev_exit is None else max(m.enter, prev_exit + c["hw"])
            hold = enter - m.enter
            if hold > c["sl_hold_cap"]:
                ok = False
                break
            if hold > 0:
                holds[m.train_id] = hold
            prev_exit = enter + run
        total = sum(holds.values()) / 60.0
        if not ok or total > c["sl_total_cap"]:
            continue
        out.append(CreationOption(
            lever=SINGLE_LINE, section_id=section.id, track=track, day=day, start_s=t0, end_s=t1,
            delay_min=total,
            pax_delay=int(sum(holds[m.train_id] / 60.0 * train_pax(m.cls, m.enter)
                              for m in merged if m.train_id in holds)),
            trains=[{"train_id": k, "class": "SUBURBAN_LOCAL", "action": f"waits {v / 60:.1f} min"}
                    for k, v in list(holds.items())[:6]],
            note=f"{track} closed; {len(moving)} train(s) run on {other} single-line",
        ))
        if len(out) >= 6:
            break
    return out


def _emergency_options(section: Section, track: str, day: int, seq: list[_Move], need_s: int,
                       c: dict, from_s: int, stretch: float) -> list[CreationOption]:
    """An emergency block for a critical or high-priority fault: take the track as soon as the
    train in the section has cleared, and hold every train that would arrive until the work is done.
    It is the blunt lever, used only when the gentler ones open nothing in time, and it is priced in
    train-minutes and passengers like the others (A-042)."""
    cap = float(load_config().get_path("sudden.emergency_max_train_min", 400)) * (stretch / 3.0)
    lead = int(load_config().get_path("sudden.emergency_lead_min", 10)) * 60
    out: list[CreationOption] = []
    starts = [from_s + lead] + [m.exit + c["buf"] for m in seq if from_s <= m.exit + c["buf"] <= from_s + 3 * 3600]
    for t0 in sorted(set(starts)):
        # a train already in the section has to clear first
        inside = [m for m in seq if m.enter < t0 and m.exit + c["buf"] > t0]
        if inside:
            t0 = max(m.exit + c["buf"] for m in inside)
        t1 = t0 + need_s
        queue = [m for m in seq if t0 - c["buf"] <= m.enter < t1 + c["look"]]
        holds: dict[str, int] = {}
        nxt = t1 + c["look"]
        for m in queue:
            holds[m.train_id] = max(0, nxt - m.enter)
            nxt += c["hw"]
        total = sum(holds.values()) / 60.0
        if total > cap:
            continue
        movers = {m.train_id: m for m in queue}
        out.append(CreationOption(
            lever=EMERGENCY, section_id=section.id, track=track, day=t0 // DAY_S, start_s=t0, end_s=t1,
            delay_min=total,
            pax_delay=int(sum(holds[k] / 60.0 * train_pax(movers[k].cls, movers[k].enter) for k in holds)),
            trains=[{"train_id": k, "class": movers[k].cls.value, "action": f"held {v / 60:.0f} min"}
                    for k, v in list(holds.items())[:6]],
            note=f"Emergency block on {track}: {len(queue)} train(s) stopped behind it until the work is done",
        ))
        if len(out) >= 4:
            break
    return out


# -------------------------------------------------------------------------- task-driven creation


def options_for_task(net: Network, task: Task, section_occ: list[SectionOccupancy],
                     rc: RerouteCache, from_s: int = 0, horizon_days: int = 2,
                     max_options: int = 5, deadline_s: int | None = None,
                     stretch: float = 1.0) -> list[CreationOption]:
    """Priced ways to open a window for this task on its section, cheapest first."""
    if task.zone.kind is not WorkZoneKind.SECTION or task.zone.ref not in net.sections:
        return []
    section = net.sections[task.zone.ref]
    c = _cfg(stretch)
    need_s = raw_needed_min(task) * 60
    by_track = sequences(section_occ)
    first_day = max(0, from_s // DAY_S)
    out: list[CreationOption] = []

    for day in range(first_day, first_day + horizon_days):
        # work named for one exact line opens a gap on that line only
        for track in ([task.track] if task.track in section.tracks else section.tracks):
            seq = by_track.get((track, day), [])
            for i in range(len(seq) - 1):
                if seq[i + 1].exit < from_s:
                    continue
                o = _retime_option(section, track, day, seq, i, need_s, c)
                if o is not None and o.end_s >= from_s:
                    out.append(o)
            out += [o for o in _reroute_options(section, track, day, seq, need_s, c, rc)
                    if o.end_s >= from_s]
            out += [o for o in _single_line_options(section, track, day, by_track, need_s, c, from_s)
                    if o.end_s >= from_s]
            if stretch > 1.0 and day == first_day:
                out += _emergency_options(section, track, day, seq, need_s, c, from_s, stretch)

    if deadline_s is not None:
        # the job must FINISH by its deadline: start + its work + release, inside the window
        out = [o for o in out if o.start_s + (need_s - 0) <= deadline_s + 0]
    out.sort(key=lambda o: (o.impact_cost, o.start_s))
    seen, best = set(), []
    for o in out:
        key = (o.lever, o.track, o.start_s // 600)
        if key in seen:
            continue
        seen.add(key)
        best.append(o)
        if len(best) >= max_options:
            break
    return best


# ----------------------------------------------------------------------- network-wide survey


def survey(net: Network, occ_by_section: dict[str, list[SectionOccupancy]],
           rc: RerouteCache, days: range = range(7)) -> dict:
    """How many near-miss gaps could be widened into workable windows, and at what cost.

    Applies creation greedily along each track-day (holds really shift later trains; a rerouted
    train really leaves the sequence), so the figures are cumulative and consistent, not a sum of
    independent best cases.
    """
    c = _cfg()
    need_s = min_raw_gap_min() * 60
    max_deficit_s = int(load_config()["gap_creation"]["survey_max_deficit_min"]) * 60
    overhead = int(load_config()["gaps"]["block_setup_min"]) + int(load_config()["gaps"]["block_release_min"])

    res = {"track_days": 0, "natural_gaps": 0, "near_gaps": 0, "created": 0,
           RETIME: 0, REROUTE: 0, "usable_hours_added": 0.0, "delay_train_min": 0.0,
           "trains_held": 0, "trains_rerouted": 0}

    for section_id, occ in occ_by_section.items():
        section = net.sections.get(section_id)
        if section is None:
            continue
        for (track, day), seq0 in sequences(occ).items():
            if day not in days:
                continue
            res["track_days"] += 1
            seq = [_Move(m.enter, m.exit, m.train_id, m.cls) for m in seq0]
            i = 0
            while i < len(seq) - 1:
                raw = seq[i + 1].enter - seq[i].exit - c["buf"] - c["look"]
                if raw >= need_s:
                    res["natural_gaps"] += 1
                elif need_s - raw <= max_deficit_s:
                    res["near_gaps"] += 1
                    r = _retime(seq, i, need_s, c)
                    if r is not None:
                        start, end, holds = r
                        for j, h in holds.items():
                            seq[j].enter += h
                            seq[j].exit += h
                        res["created"] += 1
                        res[RETIME] += 1
                        res["usable_hours_added"] += ((end - start) / 60 - overhead) / 60
                        res["delay_train_min"] += sum(holds.values()) / 60
                        res["trains_held"] += len(holds)
                    else:
                        opts = _reroute_options(section, track, day, seq[max(0, i - 3):i + 5],
                                                need_s, c, rc)
                        if opts:
                            o = opts[0]
                            gone = {t["train_id"] for t in o.trains}
                            seq = [m for m in seq if m.train_id not in gone]
                            res["created"] += 1
                            res[REROUTE] += 1
                            res["usable_hours_added"] += (o.raw_min - overhead) / 60
                            res["delay_train_min"] += o.delay_min
                            res["trains_rerouted"] += len(gone)
                            continue
                i += 1

    res["usable_hours_added"] = round(res["usable_hours_added"], 1)
    res["delay_train_min"] = round(res["delay_train_min"], 1)
    return res
