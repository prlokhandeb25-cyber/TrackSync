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
from backend.planner.creation_plan import solve_with_creation
from backend.planner.interval_index import IntervalWindowIndex, build_interval_index
from backend.gaps.creation import RerouteCache, options_for_task
from backend.domain.pax import PaxModel
from backend.planner.live_sim import LiveSimPlacement, LiveSimState

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
    user_placements: dict[str, LiveSimPlacement] = field(default_factory=dict)
    user_counter: int = 0
    user_unplaced: dict[str, str] = field(default_factory=dict)
    reroute_cache: RerouteCache | None = None
    occ_by_section: dict | None = None
    plan_natural: PlanResult | None = None      # weekly plan before any gap creation
    creation_used: list = field(default_factory=list)
    pax: PaxModel | None = None
    week_by_id: dict | None = None
    robust: dict = field(default_factory=dict)   # what centring did to the weekly plan (before / after / moves)
    # sudden tasks: never in the planned pool; their own bookings, log, and the planned/simulated
    # jobs they displaced (task id -> new slot, or None if it could not be re-placed)
    sudden_state: LiveSimState = field(default_factory=LiveSimState)
    sudden_seq: int = 0
    sudden_log: list = field(default_factory=list)
    overrides: dict = field(default_factory=dict)
    # predictive blocks: the watch list, and the proactive blocks booked from it (kept apart from the planned week)
    forecast_state: LiveSimState = field(default_factory=LiveSimState)
    forecast_rows: list = field(default_factory=list)
    forecast_summary: dict = field(default_factory=dict)
    daily_state: LiveSimState = field(default_factory=LiveSimState)   # routine daily jobs placed from 04:00 on
    daily_summary: dict = field(default_factory=dict)

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


def creation_summary(world: World, res: PlanResult, created: list) -> list[dict]:
    """The created windows the final plan actually used, with what each one cost."""
    by_id = {t.id: t for t in world.tasks}
    used = []
    for w in created:
        a = next((x for x in res.assignments if x.window_id == w.id), None)
        if a is None:
            continue
        t = by_id.get(a.task_id)
        used.append({
            "window_id": w.id, "task_id": a.task_id, "task": t.label if t else a.task_id,
            "department": t.department.value if t else "", "section_id": w.section_id,
            "track": w.track, "lever": w.created_by, "delay_min": round(w.delay_cost_min, 1),
            "note": w.created_note, "start_s": a.start_s, "end_s": a.end_s,
        })
    return used


def ensure_plan() -> PlanResult:
    world = ensure_world()
    # Built BEFORE taking the lock: these helpers call ensure_world(), which takes the same
    # (non-reentrant) lock, so calling them while holding it deadlocks the whole API.
    occ, rc, pax = occupancy_by_section(), reroute_cache(), get_pax()
    with _LOCK:
        if STATE.plan is not None:
            return STATE.plan
        natural, res, created = solve_with_creation(
            world.net, world.tasks, world.windows, occ, rc,
            time_limit_s=load_config()["planner"]["solve_time_s_demo"], pax=pax,
        )
        # Robust placement: slide each job to the start that is most likely to clear before the next
        # train. Only start times change, each move is re-checked by the referee, and it is measured.
        from backend.planner.robustness import centre_plan
        centred, rep = centre_plan(world.net, world.tasks, res.assignments, world.windows, occ, samples=30)
        by = {t.id: t for t in world.tasks}
        for a in centred:
            t = by.get(a.task_id)
            if t is not None and a.window_id and not a.window_id.startswith("CW-"):
                t.scheduled_start_s, t.scheduled_end_s = a.start_s, a.end_s
        res.assignments = centred
        d = rep.to_dict()
        STATE.robust = {"moves": rep.moved, "samples": rep.samples,
                        "before": {"mean": d["mean_before"], "risky": d["risky_before"], "expected_overruns": d["expected_overruns_before"]},
                        "after": {"mean": d["mean_after"], "risky": d["risky_after"], "expected_overruns": d["expected_overruns_after"]}}
        STATE.plan_natural = natural
        STATE.plan = res
        STATE.creation_used = creation_summary(world, res, created)
        STATE.log(0, (f"Weekly block plan solved: {len(res.assignments)} of {res.n_tasks} jobs "
                      f"placed, {res.micro_gap_count} of them into gaps between trains."), "plan")
        if len(res.assignments) > len(natural.assignments):
            STATE.log(0, (f"Gap creation opened {len(STATE.creation_used)} extra window(s): "
                          f"{len(natural.assignments)} -> {len(res.assignments)} jobs placed."), "plan")
        return res


def ensure_interval_index() -> IntervalWindowIndex:
    world = ensure_world()
    with _LOCK:
        if STATE.interval_index is None:
            STATE.interval_index = build_interval_index(world.windows)
        return STATE.interval_index


def occupancy_by_section() -> dict:
    world = ensure_world()
    if STATE.occ_by_section is None:
        idx: dict = {}
        for o in world.occupancy:
            idx.setdefault(o.section_id, []).append(o)
        STATE.occ_by_section = idx
    return STATE.occ_by_section


def reroute_cache() -> RerouteCache:
    world = ensure_world()
    if STATE.reroute_cache is None:
        STATE.reroute_cache = RerouteCache(world.net, {t.id: t for t in world.week})
    return STATE.reroute_cache


def get_pax() -> PaxModel:
    """Trains per hour and passengers per section, built once from the week's occupancy."""
    occ = occupancy_by_section()
    if STATE.pax is None:
        STATE.pax = PaxModel(occ)
    return STATE.pax


def week_by_id() -> dict:
    world = ensure_world()
    if STATE.week_by_id is None:
        STATE.week_by_id = {t.id: t for t in world.week}
    return STATE.week_by_id


def make_creator():
    """A function the scheduler calls when no natural gap fits: priced ways to open one."""
    world = ensure_world()
    occ = occupancy_by_section()
    rc = reroute_cache()

    def creator(task, from_s):
        # critical and high-priority faults may disrupt more trains than routine work (A-042)
        stretch = {1: 3.0, 2: 2.0}.get(task.priority, 1.0)
        return options_for_task(world.net, task, occ.get(task.zone.ref, []), rc,
                                from_s=from_s, horizon_days=2, deadline_s=task.due_by_s,
                                stretch=stretch)
    return creator


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
        STATE.user_placements = {}
        STATE.user_counter = 0
        STATE.user_unplaced = {}
        STATE.plan_natural = None
        STATE.creation_used = []
        STATE.sudden_state = LiveSimState()
        STATE.sudden_seq = 0
        STATE.sudden_log = []
        STATE.overrides = {}
        STATE.forecast_state = LiveSimState()
        STATE.forecast_rows = []
        STATE.forecast_summary = {}
        STATE.daily_state = LiveSimState()
        STATE.daily_summary = {}
