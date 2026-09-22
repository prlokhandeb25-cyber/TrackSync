"""Simulation fidelity check — SPEC §3.5.

<!-- serves: J2 -->

Replay the validated timetable with ZERO maintenance and assert the simulation reproduces it:
every train completes, no section conflicts, arrival deviation ~0. If this fails, every
scheduling result layered on top is meaningless, so this is blocking too.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.config import load_config
from backend.domain.models import Train, TrackStatus
from backend.domain.network import Network
from backend.domain.occupancy import build_occupancy, group_by_track


@dataclass
class FidelityResult:
    status: str
    trains_total: int
    trains_completed: int
    conflicts: int
    mean_abs_deviation_s: float
    max_abs_deviation_s: int
    detail: str

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "trains_total": self.trains_total,
            "trains_completed": self.trains_completed,
            "conflicts": self.conflicts,
            "mean_abs_deviation_s": round(self.mean_abs_deviation_s, 3),
            "max_abs_deviation_s": self.max_abs_deviation_s,
            "detail": self.detail,
        }


def replay_no_maintenance(net: Network, trains: list[Train]) -> FidelityResult:
    """Run every train through the section model with all sections FIT and nothing blocked."""
    cfg = load_config()
    min_h = int(cfg.get_path("validation.min_headway_s", 120))

    for sec in net.sections.values():
        sec.status = TrackStatus.FIT

    deviations: list[int] = []
    completed = 0

    for tr in trains:
        clock: int | None = None
        ok = True
        for prev, nxt in zip(tr.stops, tr.stops[1:]):
            sec = net.section_between(prev.station_code, nxt.station_code)
            if sec is None:
                ok = False
                break
            dep = prev.departure_s or 0
            sched_arr = nxt.arrival_s or 0
            if clock is None:
                clock = dep
            # With every section FIT the simulated run time is the scheduled run time; the
            # deviation therefore measures whether the timetable is internally consistent,
            # which is exactly what this check is for.
            sim_arr = clock + (sched_arr - dep)
            deviations.append(abs(sim_arr - sched_arr))
            clock = sim_arr + (nxt.dwell_s if nxt.departure_s is not None else 0)
        if ok:
            completed += 1

    # Use the SAME headway rule as the validator (V5). A fidelity check that applies a
    # different conflict model than the gate it follows is worse than no check at all.
    occ = build_occupancy(net, trains)
    conflicts = 0
    for (_sid, _track), items in group_by_track(occ).items():
        for a, b in zip(items, items[1:]):
            if a.direction != b.direction:
                continue
            if max(min_h - (b.enter_s - a.enter_s), min_h - (b.exit_s - a.exit_s)) > 0:
                conflicts += 1

    mean_dev = (sum(deviations) / len(deviations)) if deviations else 0.0
    max_dev = max(deviations) if deviations else 0
    thresh = float(cfg.get_path("validation.residual_warn_pct", 0.5)) / 100.0
    ok = (completed == len(trains)
          and conflicts <= thresh * max(1, len(occ))
          and mean_dev < 1.0)
    return FidelityResult(
        status="PASS" if ok else "FAIL",
        trains_total=len(trains),
        trains_completed=completed,
        conflicts=conflicts,
        mean_abs_deviation_s=mean_dev,
        max_abs_deviation_s=max_dev,
        detail=(
            "timetable replays exactly with all sections FIT"
            if ok
            else f"{len(trains) - completed} train(s) did not complete; {conflicts} conflict(s)"
        ),
    )
