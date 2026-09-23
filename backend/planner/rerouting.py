"""Rerouting and track-swap levers (SPEC §9).

<!-- serves: J1, J2 -->

Two distinct levers, because the domain rule is not symmetric:

  INTERCITY / FREIGHT_MAIL  have a fixed origin and destination but NOT a fixed physical
                            route, so they may be rerouted onto an alternate path, provided
                            the added delay stays inside their acceptable limit.

  SUBURBAN_LOCAL            serves fixed public stations and is NEVER rerouted. Its only
                            flexibility is running single-line working on its OWN track pair -
                            using the up track for both directions while the down track of the
                            SAME section is under a block, or vice versa. That is a designation
                            swap on one section, not a path change, and it never touches the
                            fast pair that carries intercity and freight traffic.

Guardrail (CLAUDE.md invariant): `reroute_candidates` refuses a SUBURBAN_LOCAL outright. This
module is deliberately kept separate from backend/planner/cpsat.py. The solver already reaches
OPTIMAL at a 0% gap; wiring path selection into its objective is the highest-risk change left
in the project, so this ships as a real, testable, standalone advisor instead - it analyses
whether a lever exists for a task that could not be placed, without touching the constraint set
that is already working.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import networkx as nx

from backend.config import load_config
from backend.domain.models import Section, Train, TrainClass
from backend.domain.network import Network
from backend.domain.task import Task
from backend.gaps.engine import CandidateWindow, GapType


class RerouteGuardrailError(Exception):
    """Raised if anything ever asks to reroute a SUBURBAN_LOCAL. Should be unreachable."""


@dataclass
class ReroutePath:
    train_id: str
    train_class: str
    sections: list[str]
    added_delay_min: float
    within_limit: bool


@dataclass
class TrackSwapOpportunity:
    section_id: str
    blocked_track: str
    swap_to_track: str
    locals_affected_per_hour: float
    max_single_line_min: int


@dataclass
class Opportunity:
    task_id: str
    zone_ref: str
    shortfall_min: int  # how much longer than the best existing window this task needs
    reroute_paths: list[ReroutePath] = field(default_factory=list)
    track_swap: TrackSwapOpportunity | None = None

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "zone_ref": self.zone_ref,
            "shortfall_min": self.shortfall_min,
            "reroute_paths": [vars(p) for p in self.reroute_paths],
            "track_swap": vars(self.track_swap) if self.track_swap else None,
        }


def _simple_weighted_graph(net: Network) -> nx.Graph:
    """A plain Graph view of the network, min-weighted over any parallel sections.

    `nx.shortest_simple_paths` does not support MultiGraph, which is what the merged network
    uses to allow more than one section between a pair of stations. Collapsing to the
    cheapest parallel edge is the right simplification for path search: we want the fastest
    way between two stations, not to enumerate which physical section achieves it.
    """
    g = nx.Graph()
    g.add_nodes_from(net.graph.nodes(data=True))
    for u, v, data in net.graph.edges(data=True):
        w = data.get("length_km", 1.0)
        if not g.has_edge(u, v) or g[u][v]["length_km"] > w:
            g.add_edge(u, v, length_km=w)
    return g


def k_shortest_paths(net: Network, origin: str, destination: str, k: int) -> list[list[str]]:
    """Up to k shortest station-sequences between origin and destination, by route length."""
    if origin not in net.graph or destination not in net.graph:
        return []
    g = _simple_weighted_graph(net)
    try:
        gen = nx.shortest_simple_paths(g, origin, destination, weight="length_km")
        return [p for _, p in zip(range(k), gen)]
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return []


def _path_sections(net: Network, nodes: list[str]) -> list[Section] | None:
    out = []
    for a, b in zip(nodes, nodes[1:]):
        sec = net.section_between(a, b)
        if sec is None:
            return None
        out.append(sec)
    return out


def _path_delay_min(net: Network, direct: list[Section], alt: list[Section]) -> float:
    """Extra running time an alternate path costs, versus the direct one."""
    direct_s = sum(s.nominal_run_time_s() for s in direct)
    alt_s = sum(s.nominal_run_time_s() for s in alt)
    return max(0.0, (alt_s - direct_s) / 60.0)


def reroute_candidates(net: Network, train: Train, avoid_section_id: str,
                       k: int | None = None) -> list[ReroutePath]:
    """Alternate paths for a reroutable train that avoid the given section.

    GUARDRAIL: refuses outright for SUBURBAN_LOCAL. A local serves fixed public stations and
    must never be offered an alternate route - only the track-swap lever applies to it, and
    that is a different function entirely.
    """
    if train.train_class is TrainClass.SUBURBAN_LOCAL or not train.reroutable:
        raise RerouteGuardrailError(
            f"{train.id} is {train.train_class.value} and must never be rerouted "
            f"(CLAUDE.md invariant)."
        )

    cfg = load_config()
    k = k or int(cfg.get_path("rerouting.k_alternate_paths", 3))
    limit = float(cfg.get_path(f"rerouting.max_delay_min.{train.train_class.value}", 30))

    paths = k_shortest_paths(net, train.origin, train.destination, k + 1)
    # Baseline for "added delay" is the shortest route between the train's own origin and
    # destination. Comparing against an adjacent-station hop (the old baseline) made every
    # multi-section train look like it lost no time at all on a detour.
    direct = _path_sections(net, paths[0]) if paths else None
    direct = direct or []
    out: list[ReroutePath] = []
    for nodes in paths:
        secs = _path_sections(net, nodes)
        if secs is None:
            continue
        if any(s.id == avoid_section_id for s in secs):
            continue  # doesn't actually avoid the closed section
        delay = _path_delay_min(net, direct, secs) if direct else 0.0
        out.append(ReroutePath(
            train_id=train.id, train_class=train.train_class.value,
            sections=[s.id for s in secs],
            added_delay_min=round(delay, 1),
            within_limit=delay <= limit,
        ))
    return out


def track_swap_opportunity(net: Network, section: Section,
                           occupancy_per_hour: float) -> TrackSwapOpportunity | None:
    """Can a local section run single-line working on its own track pair?

    Only ever proposes swapping WITHIN the section's own local (slow, or sole) pair. A
    four-track section's fast pair - which carries intercity and freight, not locals - is
    never touched by this function; there is nothing for a local to swap onto there.
    """
    tracks = section.tracks
    local_pair = (
        [t for t in tracks if t.endswith("_SLOW")] if any(t.endswith("_SLOW") for t in tracks)
        else tracks
    )
    if len(local_pair) != 2:
        return None  # not a simple bidirectional pair; no swap lever available

    cfg = load_config()["rerouting"]
    a, b = sorted(local_pair)
    return TrackSwapOpportunity(
        section_id=section.id, blocked_track=a, swap_to_track=b,
        locals_affected_per_hour=round(occupancy_per_hour, 1),
        max_single_line_min=int(cfg["max_single_line_min"]),
    )


def find_opportunities(net: Network, tasks: list[Task], windows: list[CandidateWindow],
                       unplaced_ids: list[str], week_trains: list[Train]) -> list[Opportunity]:
    """For each task that CP-SAT could not place, what lever could create a window."""
    by_id = {t.id: t for t in tasks}
    trains_by_section: dict[str, list[Train]] = {}
    for tr in week_trains:
        for prev, nxt in zip(tr.stops, tr.stops[1:]):
            sec = net.section_between(prev.station_code, nxt.station_code)
            if sec:
                trains_by_section.setdefault(sec.id, []).append(tr)

    out: list[Opportunity] = []
    for tid in unplaced_ids:
        task = by_id.get(tid)
        if task is None or task.zone.section_id is None:
            continue
        sec = net.sections.get(task.zone.section_id)
        if sec is None:
            continue

        candidate_windows = [w for w in windows if w.section_id == sec.id]
        best_usable = max((w.usable_min(task.requires_power_block) for w in candidate_windows),
                          default=0)
        shortfall = max(0, task.duration_min - best_usable)
        if shortfall <= 0:
            continue  # a window exists; this task just wasn't picked, not a real capacity gap

        opp = Opportunity(task_id=tid, zone_ref=sec.id, shortfall_min=shortfall)

        section_trains = trains_by_section.get(sec.id, [])
        for tr in section_trains:
            if not tr.reroutable:
                continue
            try:
                paths = reroute_candidates(net, tr, sec.id, k=2)
            except RerouteGuardrailError:
                continue  # defensive; reroutable already filters this
            opp.reroute_paths.extend(p for p in paths if p.within_limit)
            if len(opp.reroute_paths) >= 3:
                break

        n_locals = sum(1 for tr in section_trains if tr.train_class is TrainClass.SUBURBAN_LOCAL)
        opp.track_swap = track_swap_opportunity(net, sec, n_locals / 24.0)

        out.append(opp)
    return out
