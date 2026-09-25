"""Live rerouting for sections under an active block.

<!-- serves: J1, J5 -->

`rerouting.py` answers "could a lever create a window?" for work that could not be placed. This
answers the operational question the map has to show: a block is active on a section RIGHT NOW,
so which long-distance and freight trains were due to run through it, and where do they go
instead?

It reuses `reroute_candidates` unchanged, so the guardrail is inherited rather than re-implemented:
only INTERCITY / FREIGHT_MAIL trains are ever passed in (a SUBURBAN_LOCAL is filtered out before
the call, and `reroute_candidates` would refuse it anyway). Locals get the other lever - single-line
working on their own track pair - reported as `track_swap`.

Nothing here rewrites the timetable or the cached occupancy the rest of the app reads: a reroute
is an overlay computed from them, which is why it is safe to compute repeatedly.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.config import load_config
from backend.domain.models import Section, SectionOccupancy, Train, TrainClass
from backend.domain.network import Network
from backend.planner.rerouting import reroute_candidates, track_swap_opportunity

MAX_TRAINS_PER_BLOCK = 3


def _forward(net: Network, train: Train | None, section: Section) -> bool:
    """Does this train run through the section from its `from` station to its `to` station? (For drawing.)"""
    if train is not None:
        for prev, nxt in zip(train.stops, train.stops[1:]):
            sec = net.section_between(prev.station_code, nxt.station_code)
            if sec is not None and sec.id == section.id:
                return prev.station_code == section.from_station
    return True


def _dir(track: str) -> str:
    return "UP" if track.startswith("UP") else "DN"


def partner_line(section: Section, track: str, through: bool) -> tuple[str, str] | None:
    """The line a train changes over to when `track` is closed, and how: (line, "single_line" | "slow_line").

    Locals only ever swap to the opposite line of their own pair (single-line working: UP_SLOW <-> DN_SLOW), as the
    project's rule says. A long-distance or freight train on a closed FAST line may instead run on the SAME-direction
    slow line, behind the locals, when the section has one.
    """
    tracks = set(section.tracks)
    if through and track.endswith("_FAST"):
        same = track.replace("_FAST", "_SLOW")
        if same in tracks:
            return same, "slow_line"
    opp = {"UP_SLOW": "DN_SLOW", "DN_SLOW": "UP_SLOW", "UP_FAST": "DN_FAST", "DN_FAST": "UP_FAST", "UP": "DN", "DN": "UP"}.get(track)
    if opp in tracks:
        return opp, "single_line"
    return None


def _changeover(moved: list[SectionOccupancy], existing: list[SectionOccupancy], to_dir_of: dict[str, str],
                headway_s: int) -> dict[str, int]:
    """Delay (seconds) for each train moved onto the open line: it waits for a gap.

    On a single line a train must not meet an opposite-direction train, so it waits until that one clears; trains
    running the same way keep the minimum headway. Trains already on the open line are not held (they keep priority).
    """
    placed = [(o.enter_s, o.exit_s, _dir(o.track)) for o in existing]
    delays: dict[str, int] = {}
    for m in sorted(moved, key=lambda o: o.enter_s):
        dur = m.exit_s - m.enter_s
        d = to_dir_of[m.train_id]
        t = m.enter_s
        for _ in range(200):
            clash = None
            for (a, b, dd) in placed:
                if dd != d and a - headway_s < t + dur and b + headway_s > t:
                    clash = max(clash or 0, b + headway_s)
                elif dd == d and abs(a - t) < headway_s:
                    clash = max(clash or 0, a + headway_s)
            if clash is None:
                break
            t = clash
        placed.append((t, t + dur, d))
        delays[m.train_id] = t - m.enter_s
    return delays


@dataclass
class BlockReroute:
    section_id: str
    start_s: int
    end_s: int
    reroutes: list[dict] = field(default_factory=list)
    no_path: list[str] = field(default_factory=list)
    track_swap: dict | None = None
    locals_in_window: int = 0

    def to_dict(self) -> dict:
        return {
            "section_id": self.section_id, "start_s": self.start_s, "end_s": self.end_s,
            "reroutes": self.reroutes, "no_path": self.no_path, "track_swap": self.track_swap,
            "locals_in_window": self.locals_in_window,
        }


def plan_block_reroutes(net: Network, week_by_id: dict[str, Train],
                        section_occ: list[SectionOccupancy], section: Section,
                        start_s: int, end_s: int, track: str | None = None) -> BlockReroute:
    if track is not None and track in section.tracks:
        return _plan_line_block(net, week_by_id, section_occ, section, track, start_s, end_s)
    out = BlockReroute(section_id=section.id, start_s=start_s, end_s=end_s)

    in_window = [o for o in section_occ if o.enter_s < end_s and o.exit_s > start_s]
    out.locals_in_window = len({o.train_id for o in in_window
                                if o.train_class is TrainClass.SUBURBAN_LOCAL})

    seen: set[str] = set()
    for o in in_window:
        if o.train_class is TrainClass.SUBURBAN_LOCAL or o.train_id in seen:
            continue
        seen.add(o.train_id)
        if len(seen) > MAX_TRAINS_PER_BLOCK:
            break
        train = week_by_id.get(o.train_id)
        if train is None or not train.reroutable:
            continue
        paths = reroute_candidates(net, train, section.id, k=3)
        usable = [p for p in paths if p.within_limit] or paths
        if not usable:
            out.no_path.append(train.id)
            continue
        best = usable[0]
        out.reroutes.append({
            "train_id": train.id, "train_name": train.name, "train_class": best.train_class,
            "sections": best.sections, "added_delay_min": best.added_delay_min,
            "within_limit": best.within_limit,
            # when the train was due through the closed section, so the map can walk it round the detour
            "enter_s": o.enter_s, "exit_s": o.exit_s, "track": o.track,
        })

    swap = track_swap_opportunity(net, section, out.locals_in_window / max(1.0, (end_s - start_s) / 3600))
    if swap is not None:
        out.track_swap = {"blocked_track": swap.blocked_track, "swap_to_track": swap.swap_to_track,
                          "max_single_line_min": swap.max_single_line_min}
    return out


def _plan_line_block(net: Network, week_by_id: dict[str, Train], section_occ: list[SectionOccupancy], section: Section,
                     track: str, start_s: int, end_s: int) -> BlockReroute:
    """One line of a section is closed: what happens to the trains that were due on THAT line.

    Trains on the other lines are untouched. Each affected train is moved onto the best open line, with the delay it would
    really pick up waiting for a gap (`_changeover`); a long-distance or freight train may instead take an alternate route
    through the network, and the cheaper of the two is chosen. Locals are never sent on an alternate route.
    """
    cfg = load_config()
    headway = int(cfg.get_path("validation.min_headway_s", 120))
    cap_single = int(cfg["rerouting"]["max_single_line_min"])
    out = BlockReroute(section_id=section.id, start_s=start_s, end_s=end_s)

    on_line = [o for o in section_occ if o.track == track and o.enter_s < end_s and o.exit_s > start_s]
    out.locals_in_window = len({o.train_id for o in on_line if o.train_class is TrainClass.SUBURBAN_LOCAL})
    if not on_line:
        return out

    block_min = (end_s - start_s) / 60.0
    trains: list[dict] = []
    by_target: dict[str, list[SectionOccupancy]] = {}
    plans: list[tuple[SectionOccupancy, dict]] = []
    seen: set[str] = set()
    for o in sorted(on_line, key=lambda x: x.enter_s):
        if o.train_id in seen:
            continue
        seen.add(o.train_id)
        train = week_by_id.get(o.train_id)
        through = o.train_class is not TrainClass.SUBURBAN_LOCAL
        part = partner_line(section, track, through)
        alt = None
        if through and train is not None and train.reroutable:
            paths = reroute_candidates(net, train, section.id, k=3)
            usable = [p for p in paths if p.within_limit] or paths
            if usable:
                alt = usable[0]
        can_swap = part is not None and (part[1] != "single_line" or block_min <= cap_single)
        if can_swap:
            by_target.setdefault(part[0], []).append(o)
        plans.append((o, {"part": part if can_swap else None, "alt": alt, "through": through, "train": train}))

    delays: dict[str, int] = {}
    for target, moved in by_target.items():
        existing = [x for x in section_occ if x.track == target and x.enter_s < end_s + 3600 and x.exit_s > start_s - 3600]
        delays.update(_changeover(moved, existing, {m.train_id: _dir(target) for m in moved}, headway))

    swap_target = None
    for o, info in plans:
        part, alt, through, train = info["part"], info["alt"], info["through"], info["train"]
        opts = []
        swap_delay = None
        if part is not None:
            swap_delay = delays.get(o.train_id, 0) / 60.0
            opts.append({"kind": "swap", "to": part[0], "mode": part[1], "delay_min": round(swap_delay, 1)})
        if alt is not None:
            opts.append({"kind": "detour", "delay_min": round(alt.added_delay_min, 1), "sections": alt.sections})
        choose_alt = alt is not None and (part is None or alt.added_delay_min < swap_delay)
        if choose_alt:
            out.reroutes.append({
                "train_id": o.train_id, "train_name": train.name if train else o.train_id, "train_class": alt.train_class,
                "sections": alt.sections, "added_delay_min": alt.added_delay_min, "within_limit": alt.within_limit,
                "enter_s": o.enter_s, "exit_s": o.exit_s, "track": o.track, "options": opts, "chosen": "detour",
            })
        elif part is not None:
            swap_target = swap_target or part
            trains.append({"train_id": o.train_id, "name": train.name if train else o.train_id, "cls": o.train_class.value,
                           "enter_s": o.enter_s, "exit_s": o.exit_s, "delay_min": round(swap_delay, 1), "to": part[0],
                           "fwd": _forward(net, train, section),
                           "options": opts, "chosen": "swap"})
        elif through:
            out.no_path.append(o.train_id)
        # a local with no lever simply holds until the line reopens (it is never rerouted)

    if swap_target is not None:
        ds = [t["delay_min"] for t in trains]
        out.track_swap = {"blocked_track": track, "swap_to_track": swap_target[0], "mode": swap_target[1],
                          "max_single_line_min": cap_single, "trains": trains[:12], "n_trains": len(trains),
                          "mean_delay_min": round(sum(ds) / len(ds), 1) if ds else 0.0,
                          "max_delay_min": max(ds) if ds else 0.0}
    return out
