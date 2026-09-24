"""Adaptive buffers: learn how long crews really take, and reserve for it.

<!-- serves: J1, J5 -->

A block is booked for the planned work plus hand-back. Crews do sometimes run past it - more so in the
rain, more so for some departments - and when they do the next train is held. A flat contingency
protects everyone equally, which is too much for most jobs and too little for the worst. This learns
the overrun of each kind of job from history and reserves exactly that much, no more:

    ratio = (time actually taken) / (time planned)          one number per past job
    buffer = (80th percentile of ratio for that department and weather) - 1, times the planned time,
             rounded up to 5 minutes and capped at half the job

The buffer becomes part of the job's reserved length (`Task.buffer_min`), so the solver must find a gap
that holds it and the referee checks it, instead of the buffer being wished on afterwards.

WHAT IS AND IS NOT REAL HERE: there is no crew-performance data in this project. The history is
SYNTHETIC, drawn from a hidden "true" table below that the estimator never sees. What the experiment
therefore demonstrates is the mechanism - that the estimator recovers the table from a realistic amount
of history and that reserving by it makes blocks clear more often for a small cost in booked time - not
that any real crew behaves like this. Real logs from the works-management system replace the generator
one for one. (ASSUMPTIONS.md A-045.)
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from backend.config import load_config

# The hidden truth used to generate history and to score plans: mean overrun multiplier by
# (department, rain). Invented; PWI and OWD work is outdoors, S&T mostly cabin/relay-room.
TRUE_MEAN: dict[tuple[str, bool], float] = {
    ("PWI", False): 1.05, ("PWI", True): 1.20,
    ("OWD", False): 1.08, ("OWD", True): 1.25,
    ("S_AND_T", False): 1.03, ("S_AND_T", True): 1.08,
}
SPREAD = 0.15


def rain_days() -> set[int]:
    """Days of the week forecast wet (synthetic forecast, config `weather.rain_days`)."""
    return {int(d) for d in load_config().get_path("weather.rain_days", [1, 2])}


def true_mean(dept: str, day: int) -> float:
    return TRUE_MEAN[(dept, day % 7 in rain_days())]


def _draw(mean: float, rng: random.Random) -> float:
    return rng.lognormvariate(math.log(mean) - SPREAD * SPREAD / 2, SPREAD)


def synthetic_history(n: int = 600, seed: int | None = None) -> list[tuple[str, bool, float]]:
    """Past jobs: (department, was it raining, actual / planned)."""
    rng = random.Random((int(load_config()["seed"]) if seed is None else seed) + 4242)
    keys = list(TRUE_MEAN)
    return [(k[0], k[1], _draw(TRUE_MEAN[k], rng)) for k in (rng.choice(keys) for _ in range(n))]


@dataclass
class GroupStat:
    n: int
    mean: float
    p80: float


class CrewModel:
    """Overrun by (department, weather), with pooling for groups that have little history."""

    def __init__(self, history: list[tuple[str, bool, float]], min_n: int = 30):
        self.stats: dict[tuple[str, bool], GroupStat] = {}
        pooled = sorted(r for _, _, r in history) or [1.0]
        for key in TRUE_MEAN:
            rows = sorted(r for d, w, r in history if (d, w) == key)
            src = rows if len(rows) >= min_n else pooled          # too little history: fall back to everyone
            self.stats[key] = GroupStat(len(rows), sum(src) / len(src), src[min(len(src) - 1, int(0.8 * len(src)))])

    def buffer_min(self, dept: str, rain: bool, duration_min: int, cap: float = 0.5) -> int:
        """Minutes to reserve after the work: the p80 overrun, capped, rounded up to 5 min."""
        extra = min(max(0.0, self.stats[(dept, rain)].p80 - 1.0) * duration_min, cap * duration_min)
        return int(math.ceil(extra / 5.0) * 5) if extra > 0 else 0

    def table(self) -> list[dict]:
        return [{"department": k[0], "rain": k[1], "n": s.n, "learned_mean": round(s.mean, 3),
                 "true_mean": TRUE_MEAN[k], "learned_p80": round(s.p80, 3)} for k, s in self.stats.items()]
