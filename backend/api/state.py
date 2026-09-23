"""Server-side world state, built once at startup.

<!-- serves: J2 -->

The API, the simulation and the UI all read this one object, so what the map draws is the
same plan the solver produced rather than a parallel copy that can drift.
"""

from __future__ import annotations

import random
import threading
from dataclasses import dataclass, field

from backend.config import load_config
from backend.data.synth_tasks import generate_demand_task, generate_tasks, seed_sick_sections
from backend.domain.fsm import StatusRegistry
from backend.domain.task import Task, WorkZone
from backend.planner.context import World, build_base_world
from backend.planner.cpsat import PlanResult, solve_with_relaxation
from backend.planner.interval_index import IntervalWindowIndex, build_interval_index
from backend.planner.live_sim import LiveSimState

_LOCK = threading.Lock()


@dataclass
class AppState:
    world: World | None = None
    plan: PlanResult | None = None
    rl_plan: PlanResult | None = None
    event_log: list[dict] = field(default_factory=list)
    demand_counter: int = 0
    sim_time_s: int = 0
    playing: bool = False
    speed: int = 60  # simulated seconds per real second
    interval_index: IntervalWindowIndex | None = None
    live_sim: LiveSimState = field(default_factory=LiveSimState)
    sim_seq: int = 0

    def log(self, at_s: int, text: str, kind: str = "info") -> None:
        self.event_log.append({"at_s": at_s, "text": text, "kind": kind})
        del self.event_log[:-400]


STATE = AppState()


def ensure_world(n_tasks: int = 40) -> World:
    with _LOCK:
        if STATE.world is not None:
            return STATE.world
        base = build_base_world()
        rng = random.Random(load_config()["seed"])
        registry = StatusRegistry()
        tasks = generate_tasks(base.net, n_tasks, rng, registry=registry)
        seed_sick_sections(base.net, registry, tasks)
        STATE.world = World(
            net=base.net, week=base.week, occupancy=base.occupancy, gaps=base.gaps,
            windows=base.windows, registry=registry, tasks=tasks, seed=base.seed,
        )
        STATE.log(0, f"Week opened with {len(tasks)} maintenance tasks from three departments.",
                  "info")
        return STATE.world


def ensure_plan() -> PlanResult:
    world = ensure_world()
    with _LOCK:
        if STATE.plan is not None:
            return STATE.plan
        res = solve_with_relaxation(
            world.net, world.tasks, world.windows,
            time_limit_s=load_config()["planner"]["solve_time_s_demo"],
        )
        STATE.plan = res
        STATE.log(0, (f"Weekly block plan solved: {len(res.assignments)} of {res.n_tasks} jobs "
                      f"placed, {res.micro_gap_count} of them into gaps between trains."), "plan")
        return res


def ensure_interval_index() -> IntervalWindowIndex:
    world = ensure_world()
    with _LOCK:
        if STATE.interval_index is None:
            STATE.interval_index = build_interval_index(world.windows)
        return STATE.interval_index


def new_demand_task(at_s: int, zone_ref: str | None = None) -> Task:
    world = ensure_world()
    STATE.demand_counter += 1
    rng = random.Random(load_config()["seed"] + STATE.demand_counter * 131)
    zone = None
    if zone_ref:
        from backend.domain.models import WorkZoneKind
        kind = WorkZoneKind.SECTION if "-" in zone_ref else WorkZoneKind.STATION_NODE
        zone = WorkZone(kind=kind, ref=zone_ref)
    t = generate_demand_task(world.net, rng, at_s, zone=zone,
                             tid=f"D-{STATE.demand_counter:04d}")
    world.tasks.append(t)
    return t


def reset() -> None:
    with _LOCK:
        STATE.world = None
        STATE.plan = None
        STATE.rl_plan = None
        STATE.event_log = []
        STATE.demand_counter = 0
        STATE.sim_time_s = 0
        STATE.interval_index = None
        STATE.live_sim = LiveSimState()
        STATE.sim_seq = 0
