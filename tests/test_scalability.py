import pytest
from backend.data.ingest import TimetableIngester
from backend.data.validate import ValidationGate
from backend.data.synth_tasks import TaskGenerator
from backend.gaps.gap_engine import TrafficGapEngine
from backend.domain.compatibility import DepartmentCompatibilityEngine
from backend.planner.cp_sat_planner import CPSatBlockPlanner

def test_j3_scalability_pune_solapur_corridor():
    """
    J3 Scalability Assertion:
    Adding a new corridor = adding config file + data. Zero code changes.
    """
    config_path = "config/network/pune_solapur.yaml"

    # 1. Ingest & Build Network
    ingester = TimetableIngester(config_path)
    trains = ingester.generate_synthetic_timetable(seed=123)

    # 2. Validate
    gate = ValidationGate(ingester.network)
    is_valid, _ = gate.validate(trains)
    assert is_valid == True

    # 3. Gaps
    gap_engine = TrafficGapEngine(ingester.network)
    windows = gap_engine.find_candidate_windows(trains)
    assert len(windows) > 0

    # 4. Tasks & Compatibility
    tasks = TaskGenerator.generate_weekly_planned_tasks(ingester.network, num_tasks=15, seed=123)
    comp_engine = DepartmentCompatibilityEngine(ingester.network, allotments=[])

    # 5. Batch Planner
    planner = CPSatBlockPlanner(ingester.network, comp_engine, max_time_in_seconds=5)
    sol = planner.solve(tasks, windows)

    assert sol.status in ("OPTIMAL", "FEASIBLE")
    assert len(sol.scheduled_tasks) > 0
