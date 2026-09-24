"""A small digital twin: what does a closure do to the next twelve hours, and which response is best?

<!-- serves: J1, J5 -->

When a track has to close, the question is not only "which trains are due through it" but "how far does
the delay travel, and does a different response make it travel less?". This replays the real timetable
(every train's sequence of sections, tracks and times) with the closure in it, propagating delay the
way a timetable does:

  - a train carries its delay into its next section, losing a little at each hop (schedules have slack);
  - on every track, a train cannot enter until the one ahead has cleared plus the headway, so one late
    train pushes the ones behind it (this is the ripple);
  - random lateness (the configured gamma delay model) is applied to every train, identically in the
    closure run and in the baseline run without it, so what is reported is the closure's own effect.

Three responses are compared, each a real lever the system already has:

  HOLD          everything due on the closed track waits until it reopens, queued at the headway
  DIVERT        long-distance and freight trains that have a path inside their delay limit go round
                (cost = the reroute search's added minutes); locals wait. Locals are NEVER rerouted.
  DIVERT+SINGLE as DIVERT, and locals run single-line on the open track of their pair, one train at a
                time, both directions taking turns

Each is run over many random days; the reported figures are averages of the extra passenger-minutes,
extra train-minutes, trains late by more than five minutes, and how many sections the delay reached.
The recovery per hop and the queue discipline are invented (ASSUMPTIONS.md A-046); the timetable, the
train classes and the reroute costs are the real ones in the system.
"""

from __future__ import annotations

import bisect
import random
from dataclasses import dataclass, field

from backend.config import load_config
from backend.domain.models import SectionOccupancy, TrainClass
from backend.domain.pax import train_pax
from backend.planner.robustness import _delay_draws

POLICIES = ("HOLD", "DIVERT", "DIVERT_SINGLE")
LABEL = {"HOLD": "Hold everything", "DIVERT": "Divert long-distance, hold locals",
         "DIVERT_SINGLE": "Divert long-distance, locals single-line"}


@dataclass
class Twin:
    """The week's timetable, indexed once."""

    occ: list[SectionOccupancy]
    by_time: list[SectionOccupancy] = field(default_factory=list)
    enters: list[int] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.by_time = sorted(self.occ, key=lambda o: o.enter_s)
        self.enters = [o.enter_s for o in self.by_time]

    def window(self, t0: int, horizon_s: int) -> list[SectionOccupancy]:
        return self.by_time[bisect.bisect_left(self.enters, t0):bisect.bisect_right(self.enters, t0 + horizon_s)]


def _cfg() -> dict:
    c = load_config().get_path("twin", {}) or {}
    return {"horizon_h": float(c.get("horizon_h", 12)), "scenarios": int(c.get("scenarios", 30)),
            "recover_s": float(c.get("recovery_s_per_hop", 30)), "hw": int(load_config()["validation"]["min_headway_s"]),
            "cap_s": float(c.get("cancel_after_min", 90)) * 60.0, "lateness_scale": float(c.get("lateness_scale", 0.3))}


def _simulate(records: list[SectionOccupancy], closure: tuple[str, set[str], int, int] | None, policy: str,
              divert_delay_min, base_late: dict[str, float], recover_s: float, hw: int,
              pair: tuple[str, str] | None, cap_s: float) -> list[float]:
    """One replay. Returns each record's delay in seconds, in the order of `records`, capped at `cap_s`
    (a train later than that is in practice cancelled or short-terminated, so its delay stops counting)."""
    carried: dict[str, float] = {}
    last_exit: dict[tuple[str, str], float] = {}
    queue_clock: dict[tuple[str, str], float] = {}
    single_clock = 0.0
    sec_c, tracks_c, c0, c1 = closure if closure else ("", set(), 0, 0)
    douts: list[float] = []

    for r in records:
        d_in = carried.get(r.train_id)
        if d_in is None:
            d_in = base_late.get(r.train_id, 0.0)                      # random lateness at its first section in the window
        enter = r.enter_s + d_in
        run = r.exit_s - r.enter_s
        track = r.track
        closed_hit = (closure is not None and r.section_id == sec_c and c0 <= r.enter_s < c1
                      and (r.track in tracks_c or (policy == "DIVERT_SINGLE" and pair and r.track in pair
                                                   and r.train_class is TrainClass.SUBURBAN_LOCAL)))
        if closed_hit:
            if policy in ("DIVERT", "DIVERT_SINGLE") and r.train_class in (TrainClass.INTERCITY, TrainClass.FREIGHT_MAIL):
                dm = divert_delay_min(r.train_id)          # locals are never offered: only long-distance and freight
                if dm is not None:
                    d_out = min(cap_s, d_in + dm * 60.0)   # it leaves the section: no queue behind it here
                    carried[r.train_id] = d_out
                    douts.append(d_out)
                    continue
            if policy == "DIVERT_SINGLE" and r.train_class is TrainClass.SUBURBAN_LOCAL and pair and r.track in pair:
                enter = max(enter, single_clock)                       # one train at a time on the open track
                single_clock = enter + run + hw
                track = pair[0] if r.track == pair[1] else pair[1]     # it runs on the OTHER track of the pair
            elif r.track in tracks_c:
                key = (r.section_id, r.track)
                enter = max(enter, queue_clock.get(key, float(c1)))    # held until the track reopens, then queued
                queue_clock[key] = enter + hw
        key2 = (r.section_id, track)
        enter = max(enter, last_exit.get(key2, -1e18) + hw)            # cannot follow the train ahead too closely
        exit_ = enter + run
        last_exit[key2] = exit_
        d_out = min(cap_s, max(0.0, exit_ - r.exit_s))
        carried[r.train_id] = max(0.0, d_out - recover_s)
        douts.append(d_out)
    return douts


def closure_ripple(twin: Twin, section_id: str, blocked_tracks: set[str], start_s: int, duration_min: int,
                   divert_delay_min, local_pair: tuple[str, str] | None, scenarios: int | None = None,
                   seed: int = 0) -> dict:
    """Average effect of the closure, by response, over random days.

    Only delay the closure ADDS counts: for every record, run delay minus the same day's baseline delay,
    floored at zero (a response that happens to clear a late freight off a track is not credited)."""
    c = _cfg()
    n = scenarios or c["scenarios"]
    end_s = start_s + duration_min * 60
    recs = twin.window(start_s - 1800, int(c["horizon_h"] * 3600) + 1800)
    trains = {r.train_id: r for r in recs}
    pax = [train_pax(r.train_class, r.enter_s) for r in recs]
    out = {}
    for pol in POLICIES:
        acc = {"pax_min": 0.0, "train_min": 0.0, "late5": 0.0, "sections": 0.0, "cancelled": 0.0}
        for k in range(n):
            rng = random.Random(seed * 7919 + k)                       # the same days for every policy
            late = {tid: _delay_draws(r.train_class, r.enter_s, 1, rng)[0] * c["lateness_scale"] for tid, r in trains.items()}
            base = _simulate(recs, None, pol, divert_delay_min, late, c["recover_s"], c["hw"], local_pair, c["cap_s"])
            run = _simulate(recs, (section_id, blocked_tracks, start_s, end_s), pol, divert_delay_min, late,
                            c["recover_s"], c["hw"], local_pair, c["cap_s"])
            per_train: dict[str, float] = {}
            per_sec: dict[str, float] = {}
            cancelled: set[str] = set()
            for i, r in enumerate(recs):
                extra = max(0.0, run[i] - base[i])
                if extra <= 0:
                    continue
                acc["pax_min"] += extra * pax[i] / 60.0
                acc["train_min"] += extra / 60.0
                per_train[r.train_id] = max(per_train.get(r.train_id, 0.0), extra)
                per_sec[r.section_id] = per_sec.get(r.section_id, 0.0) + extra
                if run[i] >= c["cap_s"] - 1e-6:
                    cancelled.add(r.train_id)
            acc["late5"] += sum(1 for d in per_train.values() if d > 300)
            acc["sections"] += sum(1 for d in per_sec.values() if d > 300)
            acc["cancelled"] += len(cancelled)
        out[pol] = {k: round(v / n, 1) for k, v in acc.items()}
        out[pol]["label"] = LABEL[pol]
    best = min(POLICIES, key=lambda p: (round(out[p]["pax_min"]), out[p]["train_min"]))   # passengers first, then train-minutes
    return {"policies": out, "best": best, "scenarios": n, "horizon_h": c["horizon_h"], "trains_in_window": len(trains)}
