"""Train frequency and passenger exposure — how many people a piece of work is close to.

<!-- serves: J1, J5 -->

Maintenance is cheapest to the public when it happens where and when few trains run. This module
turns the timetable into two numbers a scheduler can price:

  trains/hour   how many services pass a section around a time
  passengers    an estimate of the people on those services, from a time-of-day load profile

A job placed in a window is "exposed" to every train that passes its section shortly before, during
and after it: those are the services a hold, a diversion or a single-line restriction would touch,
and the ones whose passengers feel any overrun. It is a HEURISTIC, not a measurement of delay:
nothing here says a passenger *was* delayed, only how many were within reach of it.

The load profile and per-train loads are invented (ASSUMPTIONS.md A-040). Real figures would come
from ticketing / footfall counts per station-hour.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass

from backend.config import load_config
from backend.domain.models import SectionOccupancy, TrainClass

DAY_S = 86400

# Share of a train's peak load that is actually on board, by hour of day. Two commuter peaks,
# a quiet middle, an almost empty night.
HOURLY_LOAD = [0.05, 0.02, 0.02, 0.02, 0.06, 0.25, 0.50, 0.85, 1.00, 0.95, 0.75, 0.60,
               0.55, 0.55, 0.55, 0.65, 0.85, 1.00, 1.00, 0.90, 0.70, 0.50, 0.30, 0.15]


def train_pax(cls: TrainClass, t_s: int) -> float:
    """Estimated passengers on one train of this class entering a section at t_s."""
    cfg = load_config()["pax"]
    peak = {TrainClass.SUBURBAN_LOCAL: float(cfg["peak_pax_local"]),
            TrainClass.INTERCITY: float(cfg["peak_pax_intercity"])}.get(cls, 0.0)
    return peak * HOURLY_LOAD[(t_s % DAY_S) // 3600]


@dataclass
class Exposure:
    passengers: int          # people on services within reach of the window
    trains: int              # those services
    trains_per_hour: float   # frequency over the measured span
    span_min: int

    def to_dict(self) -> dict:
        return {"passengers": self.passengers, "trains": self.trains,
                "trains_per_hour": round(self.trains_per_hour, 1), "span_min": self.span_min}


class PaxModel:
    """Prefix sums over each section's train movements, so any window is answered in O(log n)."""

    def __init__(self, occ_by_section: dict[str, list[SectionOccupancy]]):
        self._times: dict[str, list[int]] = {}
        self._cum: dict[str, list[float]] = {}
        for sec, items in occ_by_section.items():
            rows = sorted(items, key=lambda o: o.enter_s)
            ts = [o.enter_s for o in rows]
            cum, acc = [0.0], 0.0
            for o in rows:
                acc += train_pax(o.train_class, o.enter_s)
                cum.append(acc)
            self._times[sec], self._cum[sec] = ts, cum
        self._margin_s = int(load_config()["pax"]["margin_min"]) * 60

    def exposure(self, section_id: str, start_s: int, end_s: int) -> Exposure:
        """Passengers on the section's services from `margin` before the window to `margin` after."""
        ts = self._times.get(section_id)
        lo, hi = start_s - self._margin_s, end_s + self._margin_s
        span_min = max(1, (hi - lo) // 60)
        if not ts:
            return Exposure(0, 0, 0.0, span_min)
        a, b = bisect_left(ts, lo), bisect_right(ts, hi)
        pax = self._cum[section_id][b] - self._cum[section_id][a]
        n = b - a
        return Exposure(int(round(pax)), n, n * 60.0 / span_min, span_min)

    def trains_per_hour(self, section_id: str, at_s: int, half_span_min: int = 30) -> float:
        ts = self._times.get(section_id) or []
        lo, hi = at_s - half_span_min * 60, at_s + half_span_min * 60
        return (bisect_right(ts, hi) - bisect_left(ts, lo)) * 60.0 / (2 * half_span_min)

    def hour_profile(self, section_id: str, day: int) -> list[dict]:
        """Trains and passengers for each hour of one day — the section's quiet and busy hours."""
        out = []
        for h in range(24):
            e = self.exposure_exact(section_id, day * DAY_S + h * 3600, day * DAY_S + (h + 1) * 3600)
            out.append({"hour": h, "trains": e[0], "passengers": e[1]})
        return out

    def exposure_exact(self, section_id: str, lo: int, hi: int) -> tuple[int, int]:
        ts = self._times.get(section_id) or []
        if not ts:
            return 0, 0
        a, b = bisect_left(ts, lo), bisect_left(ts, hi)
        return b - a, int(round(self._cum[section_id][b] - self._cum[section_id][a]))

    def job_exposure(self, section_id: str, start_s: int, end_s: int) -> int:
        """Passenger-hours a job is exposed to: services within reach, scaled by how long it runs.

        The window exposure counts people once; a two-hour job is within reach of them for longer,
        so the scheduler's price scales with duration in hours."""
        e = self.exposure(section_id, start_s, end_s)
        return int(round(e.passengers * max(1.0, (end_s - start_s) / 3600.0)))

    def network_mean_tph(self, days: int = 7) -> float:
        """Average trains per hour on a section over the whole week - the yardstick a chosen site is
        compared with to show the scheduler really did pick quiet places."""
        if not self._times:
            return 0.0
        return sum(len(v) for v in self._times.values()) / len(self._times) / (24.0 * days)
