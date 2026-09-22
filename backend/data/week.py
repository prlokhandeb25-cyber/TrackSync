"""Expand the single-day timetable into the full planning week.

<!-- serves: J1, J2 -->

Planned maintenance is decided on a weekly cycle, so the planner needs a week of occupancy,
not a day. The week is built from the same day pattern because that is how a suburban
timetable actually works - the same services run every weekday - with two real differences:

  * Long-distance services only appear on the days they actually run (A-012).
  * Sunday carries a reduced suburban service inside the megablock window.

The second point matters more than it looks: it means the Sunday megablock shows up in the
occupancy data as a genuine thinning of services, so the gap engine DISCOVERS it rather than
being told about it. The configured window then becomes something we can verify against the
data instead of an assertion.
"""

from __future__ import annotations

import random
from copy import deepcopy

from backend.domain.models import Stop, Train, TrainClass, hhmmss_to_s
from backend.domain.network import Network

DAY_S = 86400
WEEK_DAYS = 7
SUNDAY = 6  # Monday = 0


def _shift(train: Train, days: int, suffix: str) -> Train:
    t = deepcopy(train)
    t.id = f"{train.id}{suffix}"
    t.stops = [
        Stop(
            station_code=s.station_code,
            arrival_s=None if s.arrival_s is None else s.arrival_s + days * DAY_S,
            departure_s=None if s.departure_s is None else s.departure_s + days * DAY_S,
        )
        for s in train.stops
    ]
    return t


def _in_megablock(train: Train, net: Network, day: int) -> bool:
    # Each line runs its own megablock window, so look up the train's own corridor rather
    # than applying one line's window to the whole network.
    cfg = (net.per_corridor or {}).get(train.corridor_id, {})
    mb = cfg.get("megablock") or net.megablock or {}
    start = hhmmss_to_s(mb.get("start", "10:30")) or 0
    end = hhmmss_to_s(mb.get("end", "15:30")) or 0
    lo, hi = day * DAY_S + start, day * DAY_S + end
    return train.start_s < hi and train.end_s > lo


def build_week(net: Network, day_trains: list[Train], seed: int) -> list[Train]:
    """Replicate the day pattern across the week, honouring running days and the megablock."""
    rng = random.Random(seed + 991)
    week: list[Train] = []

    for day in range(WEEK_DAYS):
        for tr in day_trains:
            if tr.is_real and day not in tr.days_of_week:
                continue

            shifted = _shift(tr, day, f"+d{day}")

            if day == SUNDAY and _in_megablock(shifted, net, day):
                # Megablock: suburban services through the worked section are curtailed, and
                # freight is not pathed at all. Long-distance runs, diverted or regulated.
                if shifted.train_class is TrainClass.SUBURBAN_LOCAL:
                    if rng.random() < 0.80:   # ~80% of locals cancelled in the window
                        continue
                elif shifted.train_class is TrainClass.FREIGHT_MAIL:
                    continue

            week.append(shifted)

    return week


def day_of(abs_s: int) -> int:
    return abs_s // DAY_S


def time_of_day(abs_s: int) -> int:
    return abs_s % DAY_S
