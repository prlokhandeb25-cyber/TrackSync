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
from backend.domain.network import Network, build_network, merge_networks
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


_BASE_CACHE: dict[tuple, "World"] = {}


def build_base_world(seed: int | None = None, horizon_days: int = 7,
                     corridor: str | None = None) -> World:
    """Network, timetable, occupancy and candidate windows - everything but the tasks.

    This is cached per process because it is identical across sampled instances and costs
    seconds to rebuild: the real schedules file is ~79 MB and parsing it once per instance
    dominated expert-data generation entirely. What varies between instances is the
    maintenance workload, which is exactly the variation we want, so the timetable side is
    built once and shared.
    """
    key = (seed, horizon_days, corridor)
    if key in _BASE_CACHE:
        return _BASE_CACHE[key]

    s = seed_everything(seed)
    # Each corridor is ingested on its own network - suburban patterns, megablock and track
    # policy are all per-line - and the networks are merged afterwards so shared stations
    # become real interchanges instead of duplicates.
    names = [corridor] if corridor else all_corridors()
    nets = [build_network(c) for c in names]
    day: list = []
    for n in nets:
        day.extend(build_timetable(n, s))
    net = merge_networks(nets)
    Validator(net, day).run()
    derive_tiers(net, day, build_occupancy(net, day))
    week = build_week(net, day, s)
    occ = build_occupancy(net, week)
    report = find_gaps(net, occ, horizon_days=horizon_days)
    windows = report.windows + station_node_windows(net, report)

    world = World(net=net, week=week, occupancy=occ, gaps=report, windows=windows,
                  registry=StatusRegistry(), tasks=[], seed=s)
    _BASE_CACHE[key] = world
    return world


def sample_instance(n_tasks: int, task_seed: int, base_seed: int | None = None,
                    horizon_days: int = 7, corridor: str | None = None) -> World:
    """A fresh instance: the shared corridor, a freshly sampled maintenance workload."""
    base = build_base_world(base_seed, horizon_days, corridor)
    rng = random.Random(task_seed)
    registry = StatusRegistry()
    tasks = generate_tasks(base.net, n_tasks, rng, registry=registry)
    seed_sick_sections(base.net, registry, tasks)
    return World(net=base.net, week=base.week, occupancy=base.occupancy, gaps=base.gaps,
                 windows=base.windows, registry=registry, tasks=tasks, seed=task_seed)


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
