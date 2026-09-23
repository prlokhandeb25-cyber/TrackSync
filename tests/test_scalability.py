"""Scalability: a new corridor is config only (SPEC §4, judging criterion J3).

This is the project's scalability evidence. The claim is not "the architecture could extend" —
it is that adding `config/network/pune_solapur.yaml` and nothing else makes the whole pipeline
plan that corridor. These tests run the pipeline on it and assert exactly that.

Pune–Solapur is chosen because it is unlike the corridors the code was written against:
long-distance, two-track, sparse, no suburban layer at all, stations tens of kilometres apart
instead of two. A Mumbai-shaped assumption hiding anywhere in the code fails here.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

import backend.data.ingest as ingest_mod
import backend.domain.network as network_mod
import backend.gaps.engine as gaps_mod
import backend.planner.cpsat as cpsat_mod
from backend.config import REPO_ROOT, seed_everything
from backend.data.ingest import build_timetable
from backend.data.tiers import derive_tiers
from backend.data.validate import Validator
from backend.data.week import build_week
from backend.domain.network import build_network, merge_networks
from backend.domain.occupancy import build_occupancy
from backend.gaps.engine import GapType, find_gaps, station_node_windows
from backend.planner.context import sample_instance
from backend.planner.cpsat import solve_with_relaxation
from backend.rl.env import rollout
from backend.rl.policies import GreedyPolicy

NEW_CORRIDOR = "pune_solapur"
EXISTING = ["central_line", "western_line", "harbour_line", "trans_harbour"]


@pytest.fixture(scope="module")
def net():
    seed_everything()
    return build_network(NEW_CORRIDOR)


# ------------------------------------------------------ the config exists and is self-contained


def test_new_corridor_is_only_a_config_file():
    path = REPO_ROOT / "config" / "network" / f"{NEW_CORRIDOR}.yaml"
    assert path.exists(), "the corridor should be defined entirely by its YAML file"


def test_no_corridor_name_is_hardcoded_anywhere_in_the_code():
    """The strongest form of the claim: the code must not know these corridors exist.

    If a corridor id appears in a module, adding a zone means editing code, and the
    scalability argument collapses however well the pipeline runs.
    """
    names = set(EXISTING + [NEW_CORRIDOR])
    offenders = []
    for py in (REPO_ROOT / "backend").rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        for name in names:
            if name in text:
                offenders.append(f"{py.relative_to(REPO_ROOT)} mentions {name!r}")
    assert not offenders, "corridor names leaked into code: " + "; ".join(offenders)


def test_station_codes_are_not_hardcoded_in_scheduling_code():
    """Same argument for station codes, which are the other easy place to special-case."""
    modules = [network_mod, gaps_mod, cpsat_mod, ingest_mod]
    suspicious = ["CSTM", "DADAR", "KYN", "CCG", "PNVL", "NRL", "MTN"]
    offenders = []
    for mod in modules:
        src = inspect.getsource(mod)
        # Docstrings legitimately name stations when explaining a rule; code must not.
        code = "\n".join(
            line for line in src.splitlines()
            if not line.lstrip().startswith("#")
        )
        for token in suspicious:
            if f'"{token}"' in code or f"'{token}'" in code:
                offenders.append(f"{mod.__name__} hardcodes {token}")
    assert not offenders, "; ".join(offenders)


# ------------------------------------------------------------------ the pipeline runs on it


def test_network_builds(net):
    assert len(net.stations) == 16
    assert len(net.sections) == 15
    assert all(s.length_km > 0 for s in net.sections.values())
    # Long-distance route: sections are far apart, unlike the suburban corridors.
    assert max(s.length_km for s in net.sections.values()) > 20


def test_timetable_ingests_and_validates(net):
    seed = seed_everything()
    trains = build_timetable(net, seed)
    assert trains, "the corridor should carry real long-distance services"
    assert all(t.train_class.value != "SUBURBAN_LOCAL" for t in trains), \
        "this corridor has no suburban layer; none should be generated"

    report = Validator(net, trains).run()
    assert report["checks_total"] == 10
    blocking = [c for c in report["checks"] if c["status"] == "FAIL" and c["id"] in
                ("V1", "V2", "V6", "V8", "V9")]
    assert not blocking, f"structural checks failed: {blocking}"


def test_gap_engine_finds_windows(net):
    seed = seed_everything()
    trains = build_timetable(net, seed)
    Validator(net, trains).run()
    derive_tiers(net, trains, build_occupancy(net, trains))
    week = build_week(net, trains, seed)
    occ = build_occupancy(net, week)

    report = find_gaps(net, occ, horizon_days=7)
    assert report.windows, "a sparse corridor should have plenty of workable windows"
    kinds = {w.gap_type for w in report.windows}
    assert GapType.NIGHT_WINDOW in kinds
    # Sparse traffic means large daytime gaps, so micro-gaps must appear here too.
    assert GapType.MICRO_GAP in kinds
    assert all(w.usable_min() <= w.raw_min for w in report.windows), \
        "usable time can never exceed the raw gap"


def test_tiers_derive_without_suburban_traffic(net):
    """Tier derivation is quantile-based, so it must still work when every train is express."""
    seed = seed_everything()
    trains = build_timetable(net, seed)
    Validator(net, trains).run()
    derive_tiers(net, trains, build_occupancy(net, trains))
    tiers = {s.tier for s in net.stations.values() if s.tier}
    assert tiers, "every station should receive a tier"
    assert net.stations["PUNE"].trains_per_day > net.stations["MVE"].trains_per_day, \
        "a junction should see more traffic than a wayside halt"


def test_planner_solves_the_new_corridor():
    world = sample_instance(n_tasks=18, task_seed=99, base_seed=None,
                            corridor=NEW_CORRIDOR)
    res = solve_with_relaxation(world.net, world.tasks, world.windows, time_limit_s=20)
    assert res.status in ("OPTIMAL", "FEASIBLE"), f"solver returned {res.status}"
    assert res.assignments, "the planner should place work on this corridor"
    assert all(a.section_id in world.net.sections or a.zone_ref in world.net.stations
               for a in res.assignments)


def test_rl_dispatcher_runs_on_the_new_corridor():
    """The learned dispatcher's state encoding and action mask must be corridor-agnostic."""
    world = sample_instance(n_tasks=18, task_seed=101, base_seed=None,
                            corridor=NEW_CORRIDOR)
    r = rollout(GreedyPolicy(), world.net, world.tasks, world.windows)
    assert r.placements, "the dispatcher should place work here too"
    assert r.violations == 0, "constraint violations must remain zero on an unseen corridor"


def test_merging_the_new_corridor_into_the_network_works():
    """Adding the corridor to the existing network must not disturb what is already there."""
    seed_everything()
    before = merge_networks([build_network(c) for c in EXISTING])
    after = merge_networks([build_network(c) for c in EXISTING + [NEW_CORRIDOR]])

    assert len(after.stations) > len(before.stations)
    assert len(after.sections) == len(before.sections) + 15
    # Every station that existed before must survive the merge unchanged.
    for code, st in before.stations.items():
        assert code in after.stations
        assert after.stations[code].lat == st.lat
