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

from backend.domain.models import Section, SectionOccupancy, Train, TrainClass
from backend.domain.network import Network
from backend.planner.rerouting import reroute_candidates, track_swap_opportunity

MAX_TRAINS_PER_BLOCK = 3


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
                        start_s: int, end_s: int) -> BlockReroute:
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
