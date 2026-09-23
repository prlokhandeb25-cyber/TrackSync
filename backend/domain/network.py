from enum import Enum
from typing import List, Optional, Tuple, Dict
from pydantic import BaseModel, Field
import networkx as nx

class StationTier(str, Enum):
    TIER_1 = "TIER_1"  # Top quantile frequency (CSMT, Dadar, Thane, Kalyan)
    TIER_2 = "TIER_2"  # Middle quantile frequency (Dombivli, Ambernath)
    TIER_3 = "TIER_3"  # Bottom quantile frequency (Neral, Bhivpuri Road)

class TrackStatus(str, Enum):
    FIT = "FIT"                          # Normal operation at line speed
    SICK = "SICK"                        # Defect reported, TSR enforced (e.g. 30 km/h)
    CAUTION_ORDER = "CAUTION_ORDER"      # Work done, operate at reduced speed
    STOP_AND_START = "STOP_AND_START"    # Work done, stop-and-start penalty enforced

class Station(BaseModel):
    id: str
    name: str
    code: str
    lat: float
    lon: float
    is_junction: bool = False
    platforms: int = 2
    tier: StationTier = StationTier.TIER_2

class Section(BaseModel):
    id: str
    from_station: str
    to_station: str
    length_km: float
    line_speed_kmph: float
    tracks: List[str] = Field(default_factory=lambda: ["UP", "DN"])
    alternate_section_ids: List[str] = Field(default_factory=list)
    status: TrackStatus = TrackStatus.FIT
    status_effective_speed: Optional[float] = None

class NetworkGraph:
    """Pure in-memory multigraph representation of the railway network."""
    def __init__(self):
        self.graph = nx.MultiGraph()
        self.stations: Dict[str, Station] = {}
        self.sections: Dict[str, Section] = {}

    def add_station(self, station: Station):
        self.stations[station.id] = station
        self.graph.add_node(station.id, data=station)

    def add_section(self, section: Section):
        self.sections[section.id] = section
        self.graph.add_edge(
            section.from_station,
            section.to_station,
            key=section.id,
            weight=section.length_km,
            data=section
        )

    def get_k_shortest_paths(self, origin: str, destination: str, k: int = 3) -> List[List[str]]:
        """Computes k shortest station paths between origin and destination."""
        try:
            generator = nx.shortest_simple_paths(self.graph, origin, destination, weight="weight")
            paths = []
            for path in generator:
                paths.append(path)
                if len(paths) >= k:
                    break
            return paths
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return []

    def are_adjacent_zones(self, zone1: Tuple[str, str], zone2: Tuple[str, str]) -> bool:
        """
        Determines if two work zones are adjacent.
        A work zone is either a ('SECTION', section_id) or ('STATION_NODE', station_id).
        Adjacent = share an endpoint node but do not geometrically overlap.
        """
        type1, id1 = zone1
        type2, id2 = zone2

        if type1 == type2 and id1 == id2:
            return False  # Same zone, not adjacent

        if type1 == "SECTION" and type2 == "STATION_NODE":
            sec = self.sections.get(id1)
            if sec and (sec.from_station == id2 or sec.to_station == id2):
                return True
        elif type1 == "STATION_NODE" and type2 == "SECTION":
            sec = self.sections.get(id2)
            if sec and (sec.from_station == id1 or sec.to_station == id1):
                return True
        elif type1 == "SECTION" and type2 == "SECTION":
            sec1 = self.sections.get(id1)
            sec2 = self.sections.get(id2)
            if sec1 and sec2:
                nodes1 = {sec1.from_station, sec1.to_station}
                nodes2 = {sec2.from_station, sec2.to_station}
                # Adjacent if they share exactly 1 station node
                if len(nodes1.intersection(nodes2)) == 1:
                    return True
        return False
