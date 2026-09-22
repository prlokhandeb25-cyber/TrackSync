"""Network graph construction from a corridor YAML.

<!-- serves: J3 -->

Contains no corridor-specific names or special cases. Everything comes from the config file.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import networkx as nx

from backend.config import load_network_config
from backend.domain.models import Section, Station, StationTier, haversine_km


@dataclass
class Network:
    corridor_id: str
    name: str
    stations: dict[str, Station]
    sections: dict[str, Section]
    order: list[str]  # station codes in corridor sequence
    graph: nx.MultiGraph = field(default_factory=nx.MultiGraph)
    megablock: dict = field(default_factory=dict)
    line_code: str = ""
    corridors: list[str] = field(default_factory=list)
    per_corridor: dict = field(default_factory=dict)   # corridor_id -> its own config blob
    suburban: dict = field(default_factory=dict)
    track_policy: dict[str, list[str]] = field(default_factory=dict)
    long_distance: dict = field(default_factory=dict)
    allotments: dict[str, list[str]] = field(default_factory=dict)

    def section_between(self, a: str, b: str) -> Section | None:
        return self.sections.get(f"{a}-{b}") or self.sections.get(f"{b}-{a}")

    def path_sections(self, a: str, b: str) -> list[Section]:
        """Ordered sections traversed going from station a to station b along the corridor."""
        ia, ib = self.order.index(a), self.order.index(b)
        step = 1 if ib > ia else -1
        out = []
        for i in range(ia, ib, step):
            sec = self.section_between(self.order[i], self.order[i + step])
            if sec:
                out.append(sec)
        return out

    def adjacent_zones(self, zone_a: str, zone_b: str) -> bool:
        """Do two work zones share an endpoint without geometrically overlapping?

        Used by compatibility rule R2 in P2. A SECTION and a STATION_NODE at one of its
        endpoints are adjacent, not overlapping — this is the Matunga-Dadar / Matunga case.
        """
        ends = lambda z: set(z.split("-")) if "-" in z else {z}
        ea, eb = ends(zone_a), ends(zone_b)
        if zone_a == zone_b:
            return False  # same zone: overlapping, not adjacent
        if "-" in zone_a and "-" in zone_b:
            return bool(ea & eb)  # two sections sharing a station
        return bool(ea & eb)  # section + station node at its endpoint


def build_network(corridor: str) -> Network:
    cfg = load_network_config(corridor)
    route_factor = float(cfg.get("route_factor", 1.15))
    defaults = cfg.get("defaults", {})
    default_speed = float(defaults.get("line_speed_kmph", 100))
    default_tracks = list(defaults.get("tracks", ["UP", "DN"]))
    overrides = cfg.get("section_overrides", {}) or {}

    stations: dict[str, Station] = {}
    order: list[str] = []
    for s in cfg["stations"]:
        st = Station(
            code=s["code"],
            name=s["name"],
            lat=float(s["lat"]),
            lon=float(s["lon"]),
            corridor_id=cfg["corridor_id"],
            platforms=int(s.get("platforms", 2)),
            is_junction=bool(s.get("junction", False)),
            expect_tier=StationTier(s["expect_tier"]) if s.get("expect_tier") else None,
            line_code=cfg.get("line_code", ""),
            lines=[cfg.get("line_code", "")],
            coord_src=str(s.get("coord_src", "s")),
        )
        stations[st.code] = st
        order.append(st.code)

    sections: dict[str, Section] = {}
    for a, b in zip(order, order[1:]):
        sid = f"{a}-{b}"
        sa, sb = stations[a], stations[b]
        km = haversine_km(sa.lat, sa.lon, sb.lat, sb.lon) * route_factor
        ov = overrides.get(sid, {}) or {}
        sections[sid] = Section(
            id=sid,
            from_station=a,
            to_station=b,
            corridor_id=cfg["corridor_id"],
            length_km=round(km, 3),
            line_speed_kmph=float(ov.get("line_speed_kmph", default_speed)),
            tracks=list(ov.get("tracks", default_tracks)),
            geometry=[(sa.lat, sa.lon), (sb.lat, sb.lon)],
            line_code=cfg.get("line_code", ""),
        )

    g = nx.MultiGraph()
    for code, st in stations.items():
        g.add_node(code, **{"name": st.name, "lat": st.lat, "lon": st.lon})
    for sec in sections.values():
        g.add_edge(sec.from_station, sec.to_station, key=sec.id, length_km=sec.length_km)

    return Network(
        corridor_id=cfg["corridor_id"],
        name=cfg["name"],
        stations=stations,
        sections=sections,
        order=order,
        graph=g,
        megablock=cfg.get("megablock", {}) or {},
        line_code=cfg.get("line_code", ""),
        corridors=[cfg["corridor_id"]],
        per_corridor={cfg["corridor_id"]: cfg},
        track_policy=(defaults.get("track_policy") or {}),
        suburban=cfg.get("suburban", {}) or {},
        long_distance=cfg.get("long_distance", {}) or {},
        allotments=cfg.get("allotments", {}) or {},
    )


def merge_networks(nets: list[Network], name: str = "Mumbai Suburban Network") -> Network:
    """Knit several corridors into one network.

    Stations are merged by code, which is exactly what creates the interchanges: CSMT belongs
    to both Central and Harbour, Thane to Central and Trans-Harbour, Vashi to Harbour and
    Trans-Harbour. Merging on the code means maintenance at an interchange is automatically
    visible to every line that touches it, instead of each corridor holding a private copy
    that can drift.

    Nothing here is corridor-specific. Adding a line is adding a YAML file to config/network
    and a name to config.yaml - which is the scalability claim, made literal.
    """
    if len(nets) == 1:
        return nets[0]

    stations: dict[str, Station] = {}
    sections: dict[str, Section] = {}
    order: list[str] = []
    allotments: dict[str, list[str]] = {}
    per_corridor: dict = {}
    corridors: list[str] = []

    for n in nets:
        corridors.append(n.corridor_id)
        per_corridor.update(n.per_corridor)
        for code, st in n.stations.items():
            if code in stations:
                existing = stations[code]
                for ln in st.lines:
                    if ln and ln not in existing.lines:
                        existing.lines.append(ln)
                existing.is_junction = True      # shared by two corridors: an interchange
                existing.platforms = max(existing.platforms, st.platforms)
            else:
                stations[code] = st
                order.append(code)
        for sid, sec in n.sections.items():
            sections.setdefault(sid, sec)
        for dept, secs in n.allotments.items():
            allotments.setdefault(dept, [])
            allotments[dept].extend(s for s in secs if s not in allotments[dept])

    g = nx.MultiGraph()
    for code, st in stations.items():
        g.add_node(code, name=st.name, lat=st.lat, lon=st.lon)
    for sec in sections.values():
        g.add_edge(sec.from_station, sec.to_station, key=sec.id, length_km=sec.length_km)

    merged = Network(
        corridor_id="mumbai",
        name=name,
        stations=stations,
        sections=sections,
        order=order,
        graph=g,
        megablock=nets[0].megablock,
        line_code="ALL",
        corridors=corridors,
        per_corridor=per_corridor,
        track_policy=nets[0].track_policy,
        suburban={},
        long_distance={},
        allotments=allotments,
    )
    return merged


def build_networks(corridors: list[str]) -> Network:
    return merge_networks([build_network(c) for c in corridors])
