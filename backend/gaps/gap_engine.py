from enum import Enum
from typing import List, Dict, Tuple, Optional
from pydantic import BaseModel, Field
from backend.domain.network import NetworkGraph, StationTier
from backend.domain.train import Train

class GapType(str, Enum):
    NIGHT_WINDOW = "NIGHT_WINDOW"
    MEGABLOCK = "MEGABLOCK"
    MICRO_GAP = "MICRO_GAP"

class CandidateWindow(BaseModel):
    id: str
    section_id: str
    track: str = "DN"                     # "UP" or "DN"
    start_min: int                        # Minutes from week start
    end_min: int
    raw_min: int
    usable_min: int
    gap_type: GapType
    station_tier: StationTier = StationTier.TIER_2
    trains_affected_if_extended: List[str] = Field(default_factory=list)
    extension_cost_min: float = 0.0

class TrafficGapEngine:
    """
    Analyzes section occupancy timelines and classifies traffic gaps into
    NIGHT_WINDOW, MEGABLOCK, and MICRO_GAP with setup/release overhead accounting.
    """

    def __init__(
        self,
        network: NetworkGraph,
        headway_buffer_min: float = 2.0,   # 120 seconds
        block_setup_min: int = 15,
        block_release_min: int = 10,
        power_block_extra_min: int = 10,
        min_usable_gap_min: int = 20
    ):
        self.network = network
        self.headway_buffer_min = headway_buffer_min
        self.block_setup_min = block_setup_min
        self.block_release_min = block_release_min
        self.power_block_extra_min = power_block_extra_min
        self.min_usable_gap_min = min_usable_gap_min

    def compute_section_occupancy(self, trains: List[Train]) -> Dict[Tuple[str, str], List[Tuple[float, float, str]]]:
        """
        Builds sorted occupancy interval lists per (section_id, track).
        Returns dict: (section_id, track) -> list of (entry_min, exit_min, train_id).
        """
        occupancy: Dict[Tuple[str, str], List[Tuple[float, float, str]]] = {}

        for tr in trains:
            for i in range(len(tr.stops) - 1):
                s1 = tr.stops[i]
                s2 = tr.stops[i + 1]
                sec_id = s1.section_id_next
                if not sec_id:
                    continue

                entry = s1.dep_min - self.headway_buffer_min
                exit_t = s2.arr_min + self.headway_buffer_min

                # Default to DN track for simplicity, or split UP/DN based on direction
                track = "DN" if tr.destination == "KJT" or tr.destination == "KYN" else "UP"

                key = (sec_id, track)
                if key not in occupancy:
                    occupancy[key] = []
                occupancy[key].append((entry, exit_t, tr.id))

        # Sort intervals per section & track
        for key in occupancy:
            occupancy[key].sort(key=lambda x: x[0])

        return occupancy

    def find_candidate_windows(self, trains: List[Train], is_owd_power_block: bool = False) -> List[CandidateWindow]:
        occupancy = self.compute_section_occupancy(trains)
        candidate_windows: List[CandidateWindow] = []

        total_overhead = self.block_setup_min + self.block_release_min
        if is_owd_power_block:
            total_overhead += (self.power_block_extra_min * 2)

        window_id_counter = 1

        for sec_id, section in self.network.sections.items():
            st_from = self.network.stations.get(section.from_station)
            station_tier = st_from.tier if st_from else StationTier.TIER_2

            for track in ["DN", "UP"]:
                key = (sec_id, track)
                intervals = occupancy.get(key, [])

                # If no traffic on section for entire week (0..10080 min)
                if not intervals:
                    raw = 10080
                    usable = raw - total_overhead
                    candidate_windows.append(CandidateWindow(
                        id=f"WIN_{window_id_counter:04d}",
                        section_id=sec_id,
                        track=track,
                        start_min=0,
                        end_min=10080,
                        raw_min=raw,
                        usable_min=usable,
                        gap_type=GapType.NIGHT_WINDOW,
                        station_tier=station_tier
                    ))
                    window_id_counter += 1
                    continue

                # Find gaps between consecutive train occupancies
                prev_end = 0.0

                for entry, exit_t, tr_id in intervals:
                    gap_start = int(prev_end)
                    gap_end = int(entry)
                    raw_gap = gap_end - gap_start

                    if raw_gap >= (total_overhead + self.min_usable_gap_min):
                        usable = raw_gap - total_overhead

                        # Determine gap type based on time-of-day and day-of-week
                        # 0..10080 min -> day = min // 1440, tod = min % 1440
                        tod_start = gap_start % 1440
                        day_of_week = (gap_start // 1440) % 7  # 6 = Sunday

                        if day_of_week == 6 and (630 <= tod_start <= 930):  # Sunday 10:30 - 15:30
                            gap_type = GapType.MEGABLOCK
                        elif (tod_start >= 60 and tod_start <= 240) or (tod_start >= 1380):  # Night 01:00-04:00
                            gap_type = GapType.NIGHT_WINDOW
                        else:
                            gap_type = GapType.MICRO_GAP

                        candidate_windows.append(CandidateWindow(
                            id=f"WIN_{window_id_counter:04d}",
                            section_id=sec_id,
                            track=track,
                            start_min=gap_start,
                            end_min=gap_end,
                            raw_min=raw_gap,
                            usable_min=usable,
                            gap_type=gap_type,
                            station_tier=station_tier
                        ))
                        window_id_counter += 1

                    prev_end = max(prev_end, exit_t)

                # Tail gap after last train until week end (10080)
                if prev_end < 10080:
                    raw_gap = int(10080 - prev_end)
                    if raw_gap >= (total_overhead + self.min_usable_gap_min):
                        candidate_windows.append(CandidateWindow(
                            id=f"WIN_{window_id_counter:04d}",
                            section_id=sec_id,
                            track=track,
                            start_min=int(prev_end),
                            end_min=10080,
                            raw_min=raw_gap,
                            usable_min=raw_gap - total_overhead,
                            gap_type=GapType.NIGHT_WINDOW,
                            station_tier=station_tier
                        ))
                        window_id_counter += 1

        return candidate_windows
