"""Core domain types.

<!-- serves: J1, J3 -->

Pure and I/O-free: solver, RL, simulation, API and UI all read these same objects.
P1 defines the network and timetable half. Tasks, departments, compatibility and the
track-status FSM land in P2 (the TrackStatus enum is here because ingest already needs it).
"""

from __future__ import annotations

import math
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

Direction = Literal["UP", "DN"]


class TrainClass(str, Enum):
    SUBURBAN_LOCAL = "SUBURBAN_LOCAL"
    INTERCITY = "INTERCITY"
    FREIGHT_MAIL = "FREIGHT_MAIL"


class TrackStatus(str, Enum):
    """SPEC §5.2. Transitions are enforced by the FSM in P2, not here."""

    FIT = "FIT"
    SICK = "SICK"
    CAUTION_ORDER = "CAUTION_ORDER"
    STOP_AND_START = "STOP_AND_START"


class StationTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class WorkZoneKind(str, Enum):
    """Kept distinct because R2 adjacency compatibility depends on it (SPEC §7.2)."""

    SECTION = "SECTION"
    STATION_NODE = "STATION_NODE"


class Station(BaseModel):
    code: str
    name: str
    lat: float
    lon: float
    corridor_id: str
    platforms: int = 2
    is_junction: bool = False
    expect_tier: StationTier | None = None
    # derived at ingest
    tier: StationTier | None = None
    trains_per_day: int = 0
    peak_trains_per_hour: float = 0.0
    status: TrackStatus = TrackStatus.FIT


class Section(BaseModel):
    id: str  # "CSTM-BY"
    from_station: str
    to_station: str
    corridor_id: str
    length_km: float
    line_speed_kmph: float
    tracks: list[str] = Field(default_factory=lambda: ["UP", "DN"])
    geometry: list[tuple[float, float]] = Field(default_factory=list)  # [(lat, lon), ...]
    alternate_section_ids: list[str] = Field(default_factory=list)
    status: TrackStatus = TrackStatus.FIT
    # derived
    trains_per_day: int = 0
    peak_trains_per_hour: float = 0.0
    tier: StationTier | None = None

    def nominal_run_time_s(self, speed_kmph: float | None = None) -> float:
        v = speed_kmph or self.line_speed_kmph
        return (self.length_km / v) * 3600.0


class Stop(BaseModel):
    """Times are ABSOLUTE seconds from the start of the service week.

    Never store a wrapped clock time. Wrapping at 86400 and carrying the day separately makes
    every later mutation (dwell clipping, headway repair, delay injection) able to silently
    lose a day when it crosses midnight. day_offset is derived, never set.
    """

    station_code: str
    arrival_s: int | None  # None at origin
    departure_s: int | None  # None at destination

    @property
    def day_offset(self) -> int:
        t = self.arrival_s if self.arrival_s is not None else self.departure_s
        return (t or 0) // 86400

    @property
    def time_of_day_s(self) -> int:
        t = self.arrival_s if self.arrival_s is not None else self.departure_s
        return (t or 0) % 86400

    @property
    def dwell_s(self) -> int:
        if self.arrival_s is None or self.departure_s is None:
            return 0
        return max(0, self.departure_s - self.arrival_s)


class Train(BaseModel):
    id: str
    number: str
    name: str
    train_class: TrainClass
    corridor_id: str
    origin: str
    destination: str
    direction: Direction
    stops: list[Stop]
    days_of_week: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4, 5, 6])
    priority: int = 3  # 1 = highest
    max_acceptable_delay_min: int = 0
    is_real: bool = False  # provenance: True = from the public dataset, False = synthesised

    @property
    def reroutable(self) -> bool:
        """Locals serve fixed public stations and are NEVER reroutable (CLAUDE.md invariant).

        Their only flexibility is an UP/DN track swap on the same section, which is modelled
        separately and is not a reroute.
        """
        return self.train_class in (TrainClass.INTERCITY, TrainClass.FREIGHT_MAIL)

    @property
    def start_s(self) -> int:
        for s in self.stops:
            if s.departure_s is not None:
                return s.departure_s
        return 0

    @property
    def end_s(self) -> int:
        for s in reversed(self.stops):
            if s.arrival_s is not None:
                return s.arrival_s
        return 0


class SectionOccupancy(BaseModel):
    """One train's traversal of one track of one section."""

    section_id: str
    track: str
    direction: Direction
    train_id: str
    train_class: TrainClass
    enter_s: int
    exit_s: int
    day_offset: int = 0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def hhmmss_to_s(value: str | None) -> int | None:
    """'17:18:00' -> seconds. Returns None for the dataset's 'None' sentinel."""
    if value is None or value in ("None", "", "null"):
        return None
    parts = value.strip().split(":")
    if len(parts) == 2:
        parts.append("00")
    try:
        h, m, sec = (int(p) for p in parts)
    except ValueError:
        return None
    return h * 3600 + m * 60 + sec


def s_to_hhmm(seconds: int) -> str:
    seconds = int(seconds) % 86400
    return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}"
