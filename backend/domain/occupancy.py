"""Section occupancy timelines.

<!-- serves: J1, J2 -->

Produced once from the validated timetable and consumed by both the validation gate (V5, V10)
and the traffic-gap engine in P3. Building it in one place means the gaps the planner sees are
derived from exactly the occupancy the validator checked.
"""

from __future__ import annotations

from collections import defaultdict

import networkx as nx

from backend.domain.models import SectionOccupancy, Train
from backend.domain.network import Network


def track_for(direction: str, section_tracks: list[str],
              train_class: str | None = None,
              track_policy: dict[str, list[str]] | None = None) -> str:
    """Assign a train to a physical track on a section.

    Where the section has separate fast and slow pairs (the CSMT-Kalyan main), suburban EMUs
    take the slow pair and mail/express/freight the fast pair. That separation is how the
    corridor is actually worked, and it is why locals and expresses do not conflict there.
    """
    if train_class and track_policy:
        for candidate in track_policy.get(train_class, []):
            if candidate in section_tracks and candidate.startswith(direction):
                return candidate
    if direction in section_tracks:
        return direction
    for t in section_tracks:
        if t.startswith(direction):
            return t
    return section_tracks[0]


def _path_between(net: Network, a: str, b: str) -> list:
    """Sections a train actually runs through between two consecutive STOPS.

    An express calls at CSMT then Thane without stopping in between, but it still occupies
    every section along the way. Treating a skipped run as "no occupancy" would hide those
    trains from the gap engine entirely, and the planner would then cheerfully schedule a
    block straight into the path of a Rajdhani.
    """
    direct = net.section_between(a, b)
    if direct is not None:
        return [direct]
    try:
        nodes = nx.shortest_path(net.graph, a, b, weight="length_km")
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return []
    out = []
    for u, v in zip(nodes, nodes[1:]):
        sec = net.section_between(u, v)
        if sec is None:
            return []
        out.append(sec)
    return out


def build_occupancy(net: Network, trains: list[Train]) -> list[SectionOccupancy]:
    out: list[SectionOccupancy] = []
    for tr in trains:
        for prev, nxt in zip(tr.stops, tr.stops[1:]):
            path = _path_between(net, prev.station_code, nxt.station_code)
            if not path:
                continue
            if len(path) > 1:
                # Split the run time across the skipped sections in proportion to length.
                enter, exit_ = prev.departure_s, nxt.arrival_s
                if enter is None or exit_ is None:
                    continue
                total_km = sum(x.length_km for x in path) or 1.0
                span = max(1, exit_ - enter)
                cursor = enter
                for seg in path:
                    dur = int(span * seg.length_km / total_km)
                    out.append(
                        SectionOccupancy(
                            section_id=seg.id,
                            track=track_for(tr.direction, seg.tracks, tr.train_class.value,
                                            net.track_policy),
                            direction=tr.direction,
                            train_id=tr.id,
                            train_class=tr.train_class,
                            enter_s=cursor,
                            exit_s=cursor + dur,
                            day_offset=prev.day_offset,
                        )
                    )
                    cursor += dur
                continue
            sec = path[0]
            abs_enter = prev.departure_s
            abs_exit = nxt.arrival_s
            if abs_enter is None or abs_exit is None:
                continue
            out.append(
                SectionOccupancy(
                    section_id=sec.id,
                    track=track_for(tr.direction, sec.tracks, tr.train_class.value,
                                    net.track_policy),
                    direction=tr.direction,
                    train_id=tr.id,
                    train_class=tr.train_class,
                    enter_s=abs_enter,
                    exit_s=abs_exit,
                    day_offset=prev.day_offset,
                )
            )
    return out


def group_by_track(occ: list[SectionOccupancy]) -> dict[tuple[str, str], list[SectionOccupancy]]:
    """(section_id, track) -> occupancies sorted by entry time."""
    grouped: dict[tuple[str, str], list[SectionOccupancy]] = defaultdict(list)
    for o in occ:
        grouped[(o.section_id, o.track)].append(o)
    for key in grouped:
        grouped[key].sort(key=lambda o: o.enter_s)
    return dict(grouped)


def daily_counts(occ: list[SectionOccupancy]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for o in occ:
        counts[o.section_id] += 1
    return dict(counts)


def peak_trains_per_hour(occ: list[SectionOccupancy], section_id: str) -> float:
    """Busiest clock hour on a section, both tracks combined."""
    buckets: dict[int, int] = defaultdict(int)
    for o in occ:
        if o.section_id == section_id:
            buckets[(o.enter_s % 86400) // 3600] += 1
    return float(max(buckets.values())) if buckets else 0.0
