"""Shared setup: build the world once, reuse it everywhere.

<!-- serves: J2, J3 -->

Every entry point - the planner script, expert-data generation, the RL environment, the API -
needs the same objects built the same way. Doing it in one place is what keeps the plan the
RL trains on identical to the plan the UI shows.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from backend.config import all_corridors, load_config, seed_everything
from backend.data.ingest import build_timetable
from backend.data.synth_tasks import generate_tasks, seed_sick_sections
from backend.data.tiers import derive_tiers
from backend.data.validate import Validator
from backend.data.week import build_week
from backend.domain.fsm import StatusRegistry
from backend.domain.models import SectionOccupancy, Train
from backend.domain.network import Network, build_network
from backend.domain.occupancy import build_occupancy
from backend.domain.task import Task
from backend.gaps.engine import CandidateWindow, GapReport, find_gaps, station_node_windows


@dataclass
class World:
    net: Network
    week: list[Train]
    occupancy: list[SectionOccupancy]
    gaps: GapReport
    windows: list[CandidateWindow]
    registry: StatusRegistry
    tasks: list[Task]
    seed: int

    def windows_for(self, zone_ref: str) -> list[CandidateWindow]:
        return [w for w in self.windows if w.zone_ref == zone_ref]


def build_world(n_tasks: int = 40, seed: int | None = None, horizon_days: int = 7,
                corridor: str | None = None, quiet: bool = True) -> World:
    s = seed_everything(seed)
    net = build_network(corridor or all_corridors()[0])

    day = build_timetable(net, s)
    Validator(net, day).run()  # repairs applied in place
    derive_tiers(net, day, build_occupancy(net, day))

    week = build_week(net, day, s)
    occ = build_occupancy(net, week)
    report = find_gaps(net, occ, horizon_days=horizon_days)
    windows = report.windows + station_node_windows(net, report)

    rng = random.Random(s)
    registry = StatusRegistry()
    tasks = generate_tasks(net, n_tasks, rng, registry=registry)
    seed_sick_sections(net, registry, tasks)

    if not quiet:
        print(f"world: {len(week):,} services, {len(windows):,} windows, {len(tasks)} tasks")
    return World(net=net, week=week, occupancy=occ, gaps=report, windows=windows,
                 registry=registry, tasks=tasks, seed=s)
